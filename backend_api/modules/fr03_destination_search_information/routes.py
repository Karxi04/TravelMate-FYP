import os
import math
import re
from flask import Blueprint, request, jsonify, g

from auth_utils import auth_required
from utils import utc_now_iso
from services.local_catalog import DESTINATIONS
from services.serpapi_service import (
    retrieveDestinationResults,
    retrieveDestinationDetails,
)
from sequence_contract.validators import (
    validateSearchInput,
    validateFilterOption,
    validateSortingOption,
)
from sequence_contract.domain_functions import (
    applyDestinationFilter,
    applyDestinationSorting,
)
from sequence_contract.firebase_firestore import (
    retrieveRecord,
    storeRecord,
    deleteRecord,
)
from services.public_content_projection import public_review
from services.review_service import approved_reviews
from services.malaysian_locality import (
    normalize_destination_scope,
    normalize_candidate_geography,
    filter_candidates,
    FOREIGN_DESTINATIONS,
)

bp = Blueprint('fr03_destinations', __name__, url_prefix='/api/fr3')


def _fallback_mode():
    return os.getenv('FALLBACK_MODE', 'false').lower() in {'1', 'true', 'yes'}


def _document_id(value):
    return str(value or '').replace('/', '_')


def _destination_id(item):
    return str(
        item.get('place_id')
        or item.get('data_id')
        or item.get('data_cid')
        or item.get('destinationId')
        or item.get('title')
        or ''
    ).strip()


_SEARCH_ALIASES = {
    'georgetown': 'george town',
    'kek loksi': 'kek lok si',
    'pulau pinang': 'penang',
    'curry me': 'curry mee',
    'char kway teow': 'char koay teow',
    'ayer itam': 'air itam',
    'attractions': 'attraction',
    'restaurants': 'restaurant',
}

_SEARCH_NOISE = {
    'best', 'find', 'in', 'malaysia', 'near', 'penang', 'place', 'places',
    'show', 'the', 'to', 'top',
}

_AREA_TYPES = {
    'administrative area', 'city', 'locality', 'neighborhood', 'neighbourhood',
    'sublocality', 'town',
}


def _search_text(value):
    text = re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower()).strip()
    for alias, canonical in _SEARCH_ALIASES.items():
        text = re.sub(rf'\b{re.escape(alias)}\b', canonical, text)
    return text


def _search_scope(location):
    raw_location = str(location or '').strip()
    if not raw_location:
        # Default policy: When no location is provided, default to Penang for backward compatibility and to avoid unbounded provider search.
        requested = normalize_destination_scope('Penang')
        provider_location = requested.get('canonicalName') or 'Penang, Malaysia'
        return requested, requested, provider_location

    requested = normalize_destination_scope(raw_location)
    if not requested.get('resolved') or requested.get('country') != 'Malaysia':
        return requested, None, None

    provider_location = requested.get('canonicalName') or (
        f"{raw_location}, Malaysia" if 'malaysia' not in raw_location.lower() else raw_location
    )
    state = requested.get('state')
    state_scope = normalize_destination_scope(state) if state else requested
    return requested, state_scope, provider_location


def _provider_query(query):
    normalized = _search_text(query)
    query_scope = normalize_destination_scope(normalized)
    city = query_scope.get('city')
    state = query_scope.get('state')
    if city:
        exact_area_names = {
            _search_text(city),
            _search_text(f'{city} {state}' if state else f'{city} Malaysia'),
            _search_text(f'{city} {state} Malaysia' if state else f'{city} Malaysia'),
            _search_text(f'{city} Penang'),
            _search_text(f'{city} Penang Malaysia'),
        }
        if normalized in exact_area_names:
            return f'places to visit {city}'
    elif state:
        exact_area_names = {
            _search_text(state),
            _search_text(f'{state} Malaysia'),
        }
        if normalized in exact_area_names:
            return f'places to visit {state}'
    if normalized in {
        'penang attraction', 'attraction penang',
        'kuala lumpur attraction', 'attraction kuala lumpur',
        'melaka attraction', 'attraction melaka',
        'sabah attraction', 'attraction sabah',
        'sarawak attraction', 'attraction sarawak',
        'malaysia attraction', 'attraction malaysia',
    }:
        return 'tourist attractions'
    return normalized


def _provider_results(data):
    if not isinstance(data, dict) or data.get('error'):
        raise ValueError('Malformed place-search provider response')
    if 'local_results' in data:
        if not isinstance(data['local_results'], list):
            raise ValueError('Malformed place-search provider response')
        raw_results = data['local_results']
    elif 'place_results' in data:
        if not isinstance(data['place_results'], dict) or not data['place_results']:
            raise ValueError('Malformed place-search provider response')
        raw_results = [data['place_results']]
    else:
        raise ValueError('Malformed place-search provider response')
    output = []
    for provider_order, raw in enumerate(raw_results):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        position = item.get('position')
        if not item.get('gps_coordinates') and isinstance(position, dict):
            item['gps_coordinates'] = {
                'latitude': position.get('latitude', position.get('lat')),
                'longitude': position.get('longitude', position.get('lng')),
            }
        item.setdefault('source', 'serpapi')
        item['resultKind'] = _result_kind(item)
        item['_providerOrder'] = provider_order
        output.append(item)
    return output


def _kind_from_type(value):
    text = _search_text(value)
    if any(area_type in text for area_type in _AREA_TYPES):
        return 'area'
    if any(term in text for term in (
            'restaurant', 'food', 'cafe', 'coffee shop', 'hawker')):
        return 'restaurant'
    if any(term in text for term in ('temple', 'mosque', 'church', 'cultural')):
        return 'cultural_site'
    if any(term in text for term in ('landmark', 'monument')):
        return 'landmark'
    if any(term in text for term in (
            'attraction', 'museum', 'park', 'garden', 'beach', 'tourist')):
        return 'attraction'
    return None


def _result_kind(item):
    primary_kind = _kind_from_type(item.get('type') or item.get('category'))
    if primary_kind:
        return primary_kind
    secondary_types = item.get('types')
    for secondary_type in secondary_types if isinstance(secondary_types, list) else []:
        secondary_kind = _kind_from_type(secondary_type)
        if secondary_kind:
            return secondary_kind
    return 'place'


def _filter_by_category(items, filter_option):
    selected = _search_text(filter_option)
    if not selected or selected == 'all':
        return list(items)
    category_terms = {
        'food': {'restaurant', 'food', 'cafe', 'hawker'},
        'culture': {'culture', 'cultural', 'heritage', 'museum', 'temple', 'mosque', 'church'},
        'nature': {'nature', 'park', 'garden', 'hill', 'beach', 'outdoor'},
        'shopping': {'shopping', 'mall', 'market'},
    }.get(selected)
    if not category_terms:
        return applyDestinationFilter(items, filter_option)
    return [
        item for item in items
        if any(term in _search_text(' '.join(str(item.get(field) or '') for field in (
            'type', 'category', 'title', 'description', 'resultKind'
        ))) for term in category_terms)
    ]


def _result_identity_values(item):
    return {
        str(item.get(field) or '').strip().lower()
        for field in ('place_id', 'data_id', 'data_cid', 'destinationId', 'id')
        if str(item.get(field) or '').strip()
    }


def _canonical_place_name(item):
    name = _search_text(item.get('title') or item.get('name'))
    return {
        'kek lok si': 'kek lok si temple',
    }.get(name, name)


def _same_place(left, right):
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    left_ids = _result_identity_values(left)
    right_ids = _result_identity_values(right)
    if left_ids and right_ids and left_ids.intersection(right_ids):
        return True
    left_name = _canonical_place_name(left)
    right_name = _canonical_place_name(right)
    if not left_name or left_name != right_name:
        return False

    left_coords = _coords(left)
    right_coords = _coords(right)
    if left_coords and right_coords:
        distance = _distance_km(left_coords, right_coords)
        return distance is not None and distance <= 0.5

    left_geo = normalize_candidate_geography(left)
    right_geo = normalize_candidate_geography(right)
    if left_geo.get('state') and right_geo.get('state'):
        if left_geo['state'] != right_geo['state']:
            return False
        if (left_geo.get('city') and right_geo.get('city') and
                left_geo['city'] != right_geo['city']):
            return False
        return True

    left_address = _search_text(left.get('address') or left.get('location'))
    right_address = _search_text(right.get('address') or right.get('location'))
    if left_address and right_address:
        return left_address in right_address or right_address in left_address
    return True


def _enrich_search_result(item):
    """Fill missing trusted geography without replacing provider fields."""
    enriched = dict(item or {})
    for local in DESTINATIONS:
        if _same_place(enriched, local):
            for field in ('address', 'gps_coordinates', 'city', 'state'):
                if not enriched.get(field) and local.get(field):
                    enriched[field] = local[field]
            break

    title_scope = normalize_destination_scope(
        enriched.get('title') or enriched.get('name') or ''
    )
    if title_scope.get('state') and not enriched.get('state'):
        enriched['state'] = title_scope['state']
    if title_scope.get('city') and not enriched.get('city'):
        enriched['city'] = title_scope['city']
    if not enriched.get('resultKind'):
        enriched['resultKind'] = _result_kind(enriched)
    return enriched


def _deduplicate_results(items):
    output = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if any(_same_place(item, existing) for existing in output):
            continue
        output.append(item)
    return output


def _relevance_rank(item, query):
    query_text = _search_text(query)
    title = _search_text(item.get('title') or item.get('name'))
    category = _search_text(item.get('type') or item.get('category'))
    address = _search_text(item.get('address') or item.get('location'))
    query_tokens = set(query_text.split()) - _SEARCH_NOISE
    title_tokens = set(title.split())
    if title == query_text:
        tier = 0
    elif title.startswith(query_text):
        tier = 1
    elif query_text and query_text in title:
        tier = 2
    elif query_tokens and query_tokens.issubset(title_tokens):
        tier = 3
    elif query_tokens and query_tokens.issubset(set(
            f'{title} {category} {address}'.split())):
        tier = 4
    elif query_tokens.intersection(set(f'{title} {category} {address}'.split())):
        tier = 5
    else:
        tier = 6
    try:
        rating = float(item.get('rating') or 0)
    except (TypeError, ValueError):
        rating = 0
    provider_order = item.get('_providerOrder')
    provider_order = provider_order if isinstance(provider_order, int) else 999
    return tier, provider_order, -rating, title


def _cache(item):
    if not isinstance(item, dict):
        return
    did = _destination_id(item)
    if did:
        storeRecord(
            'destination_cache',
            {**item, 'destinationId': did, 'cachedAt': utc_now_iso()},
            _document_id(did),
            merge=True,
        )


def _cached_destination(reference):
    item = retrieveRecord('destination_cache', _document_id(reference))
    return item if isinstance(item, dict) else None


def _all_destinations():
    items = [dict(x) for x in DESTINATIONS]
    try:
        admin_items = retrieveRecord('admin_destinations') or []
        for ad in admin_items:
            if isinstance(ad, dict) and ad.get('status', 'active') != 'archived':
                items.append(dict(ad))
    except Exception:
        pass
    return items


def _local_destination(reference):
    reference = str(reference or '').strip()
    if not reference:
        return None
    lowered = reference.lower()
    for item in _all_destinations():
        candidates = {
            str(item.get('place_id') or ''),
            str(item.get('destinationId') or ''),
            str(item.get('id') or ''),
            str(item.get('data_id') or ''),
            str(item.get('data_cid') or ''),
            str(item.get('title') or ''),
            str(item.get('name') or ''),
        }
        if reference in candidates or lowered in {x.lower() for x in candidates if x}:
            return dict(item)
    return None


def _coords(item):
    gps = item.get('gps_coordinates') if isinstance(item, dict) else None
    if isinstance(gps, dict):
        try:
            return float(gps.get('latitude')), float(gps.get('longitude'))
        except (TypeError, ValueError):
            return None
    return None


def _distance_km(a, b):
    if not a or not b:
        return None
    lat1, lon1 = a
    lat2, lon2 = b
    radius = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    x = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    x = min(1.0, max(0.0, x))
    return radius * 2 * math.atan2(math.sqrt(x), math.sqrt(1 - x))


def _provider_reference(reference, cached):
    """Return (provider_reference, reference_type) for SerpApi place details."""
    cached = cached or {}
    if cached.get('place_id'):
        return str(cached['place_id']), 'place_id'
    if cached.get('data_cid'):
        return str(cached['data_cid']), 'data_cid'

    # The public endpoint still calls this value `place_id` because that is the
    # sequence-diagram/domain name. In practice a cached Google Maps local result
    # tells us whether it is a place_id or data_cid.
    return str(reference), 'place_id'


def _merge_destination(cached, provider):
    cached = dict(cached or {})
    provider = dict(provider or {})
    merged = {**cached, **provider}
    did = _destination_id(merged)
    if did:
        merged['destinationId'] = did
    return merged


@bp.get('/local-ratings')
@auth_required(['traveller'])
def local_ratings():
    # One read pass for a page of cards; retain the existing approval/dedup policy.
    grouped = {}
    for item in retrieveRecord('feedback'):
        identity = item.get('destinationId')
        if isinstance(identity, str) and identity:
            grouped.setdefault(identity, []).append(item)
    result = {}
    for identity, records in grouped.items():
        approved = approved_reviews(records)
        if approved:
            result[identity] = {'rating': round(sum(float(x['rating']) for x in approved) / len(approved), 1),
                                'reviews': len(approved)}
    return jsonify({'ok': True, 'items': result})


@bp.get('/destinations/search')
@auth_required(['traveller'])
def search_destinations():
    q = request.args.get('q', '').strip()
    location_param = request.args.get('location')
    location = (location_param or '').strip()
    filterOption = request.args.get('filter')
    sortOption = request.args.get('sort')

    if not validateSearchInput(q):
        return jsonify({'ok': False, 'error': 'Search query is required'}), 400
    if not validateFilterOption(filterOption) or not validateSortingOption(sortOption):
        return jsonify({'ok': False, 'error': 'Invalid filter or sort option'}), 400

    requested_scope, target_scope, provider_location = _search_scope(location)

    if location_param is not None and location != '':
        if target_scope is None or not requested_scope.get('resolved') or requested_scope.get('country') != 'Malaysia':
            text = _search_text(location)
            is_foreign = any(re.search(rf'\b{re.escape(k)}\b', text) for k in FOREIGN_DESTINATIONS)
            if is_foreign:
                return jsonify({
                    'ok': False,
                    'error': f"TravelMate is dedicated exclusively to travel planning within Malaysia. '{location}' is outside our supported tourism destinations.",
                }), 400
            return jsonify({
                'ok': False,
                'error': f"Requested destination '{location}' could not be resolved as a Malaysian destination.",
            }), 400

    interpreted_query = _provider_query(q)
    coordinates = {
        'latitude': requested_scope.get('latitude'),
        'longitude': requested_scope.get('longitude'),
    }
    provider_unavailable = False
    try:
        data = retrieveDestinationResults(
            interpreted_query,
            provider_location,
            coordinates,
        )
    except Exception:
        if not _fallback_mode():
            return jsonify({
                'ok': False,
                'error': 'Place search is temporarily unavailable. Please try again.',
            }), 502
        provider_unavailable = True
        normalized_query = _search_text(q)
        query_words = set(normalized_query.split())
        matched = []
        for x in _all_destinations():
            text = _search_text(' '.join(str(x.get(k, '')) for k in ['title', 'name', 'type', 'category', 'description', 'location', 'address', 'city', 'state']))
            if normalized_query in text or (query_words and query_words.issubset(set(text.split()))):
                matched.append(dict(x))
            elif query_words and any(word in text for word in query_words if len(word) > 3):
                matched.append(dict(x))
        results = matched
        source = 'local'

        if not results:
            return jsonify({
                'ok': False,
                'error': 'Live place search is temporarily unavailable. Please try again.',
            }), 502
    else:
        try:
            results = _provider_results(data)
        except ValueError:
            return jsonify({
                'ok': False,
                'error': 'Place search returned an unsupported response. Please try again.',
            }), 502
        source = 'serpapi'

    # Always merge matching admin-managed destinations from Firestore
    try:
        admin_items = retrieveRecord('admin_destinations') or []
        for ad in admin_items:
            if isinstance(ad, dict) and ad.get('status', 'active') != 'archived':
                text = _search_text(' '.join(str(ad.get(k, '')) for k in ['title', 'name', 'type', 'category', 'description', 'location', 'address', 'city', 'state']))
                if _search_text(q) in text:
                    did = _destination_id(ad)
                    if not any(_destination_id(r) == did for r in results):
                        results.insert(0, dict(ad))
    except Exception:
        pass

    results = _deduplicate_results(_enrich_search_result(item) for item in results)
    results, _rejected = filter_candidates(results, requested_scope)
    results = _filter_by_category(results, filterOption)
    results = (
        applyDestinationSorting(results, sortOption)
        if sortOption
        else sorted(results, key=lambda item: _relevance_rank(item, q))
    )

    for item in results[:30]:
        item.pop('_providerOrder', None)
        did = _destination_id(item)
        if did and not item.get('destinationId'):
            item['destinationId'] = did
        _cache(item)

    return jsonify({
        'ok': True,
        'results': results,
        'source': source,
        'locationUsed': requested_scope.get('canonicalName') or provider_location,
        'providerUnavailable': provider_unavailable,
    })


@bp.get('/destinations/<path:place_id>')
@auth_required(['traveller'])
def destination_details(place_id):
    cached = _cached_destination(place_id)
    provider_ref, reference_type = _provider_reference(place_id, cached)

    try:
        data = retrieveDestinationDetails(provider_ref, reference_type)
        provider = data.get('place_results') or data.get('local_results') or data
        if not isinstance(provider, dict):
            provider = {}
        result = _merge_destination(cached, provider)
        _cache(result)
        return jsonify(
            {
                'ok': True,
                'destination': result,
                'source': 'serpapi',
                'detailsAvailable': bool(result),
            }
        )
    except Exception as exc:
        # Cached search information is still valuable and allows View Destination
        # Details to work if the live place-details call is unavailable.
        if cached:
            return jsonify(
                {
                    'ok': True,
                    'destination': cached,
                    'source': 'cache',
                    'detailsAvailable': True,
                    'providerWarning': str(exc),
                }
            )

        if not _fallback_mode():
            return jsonify({'ok': False, 'error': str(exc)}), 502

        match = _local_destination(place_id)
        return jsonify(
            {
                'ok': True,
                'destination': match,
                'source': 'local',
                'detailsAvailable': bool(match),
            }
        )


def retrieveRatingsAndReviews(place_id):
    """Retrieve TravelMate Traveller reviews from the shared Firestore database."""
    records = retrieveRecord('feedback', filters=[('destinationId', '==', place_id)])
    if not records:
        cached = _cached_destination(place_id) or _local_destination(place_id)
        if cached:
            other_ids = {
                str(cached.get('destinationId') or ''),
                str(cached.get('place_id') or ''),
                str(cached.get('data_id') or ''),
                str(cached.get('data_cid') or ''),
                str(cached.get('title') or ''),
                str(cached.get('name') or ''),
            } - {'', str(place_id)}
            for alt_id in other_ids:
                records = retrieveRecord('feedback', filters=[('destinationId', '==', alt_id)])
                if records:
                    break
    visible = approved_reviews(records)
    visible.sort(key=lambda x: str(x.get('updatedAt') or x.get('submittedAt') or ''), reverse=True)
    ratings = []
    for item in visible:
        try:
            ratings.append(float(item.get('rating')))
        except (TypeError, ValueError):
            pass
    average = round(sum(ratings) / len(ratings), 1) if ratings else None
    reviews = [public_review(item) for item in visible]
    return {
        'rating': average,
        'reviews': len(reviews),
        'user_reviews': reviews,
        'review_summary': 'Approved TravelMate reviews.' if reviews else 'No TravelMate reviews yet.',
    }


@bp.get('/destinations/<path:place_id>/ratings-reviews')
@auth_required(['traveller'])
def ratings_reviews(place_id):
    result = retrieveRatingsAndReviews(place_id)
    return jsonify({'ok': True, 'source': 'travelmate_database', 'result': result})


@bp.get('/destinations/<path:place_id>/nearby')
@auth_required(['traveller'])
def nearby_places(place_id):
    base = _cached_destination(place_id) or _local_destination(place_id) or {}
    base_coords = _coords(base)
    items = []
    for row in DESTINATIONS:
        if _same_place(row, base):
            continue
        distance = _distance_km(base_coords, _coords(row))
        if distance is None:
            continue
        if distance <= float(request.args.get('radiusKm', 12) or 12):
            item = dict(row)
            item['distanceKm'] = round(distance, 1)
            item['nearbyReason'] = f"{item.get('title', 'Place')} is about {distance:.1f} km from {base.get('title') or base.get('name') or 'the selected place'}."
            if not any(_same_place(item, existing) for existing in items):
                items.append(item)
    items.sort(key=lambda x: x.get('distanceKm', 999))
    for item in items[:12]:
        _cache(item)
    return jsonify({'ok': True, 'base': base, 'items': items[:12], 'source': 'local'})


@bp.get('/favourites')
@auth_required(['traveller'])
def favourites():
    return jsonify(
        {
            'ok': True,
            'items': retrieveRecord(
                'favourites', filters=[('travellerId', '==', g.uid)]
            ),
        }
    )


@bp.post('/favourites')
@auth_required(['traveller'])
def save_favourite():
    payload = request.get_json(silent=True) or {}
    did = str(
        payload.get('destinationId')
        or payload.get('place_id')
        or payload.get('data_id')
        or payload.get('data_cid')
        or ''
    ).strip()

    if not did:
        return jsonify({'ok': False, 'error': 'destinationId is required'}), 400

    doc_id = f'{g.uid}_{did}'.replace('/', '_')
    data = {
        **payload,
        'travellerId': g.uid,
        'destinationId': did,
        'savedAt': utc_now_iso(),
    }
    result = storeRecord('favourites', data, doc_id, merge=True)
    _cache(payload)
    return jsonify({'ok': True, 'id': doc_id, 'favourite': result}), 201


@bp.delete('/favourites/<path:doc_id>')
@auth_required(['traveller'])
def delete_favourite(doc_id):
    item = retrieveRecord('favourites', doc_id)
    if not item or item.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'Favourite not found'}), 404
    deleteRecord('favourites', doc_id)
    return jsonify({'ok': True})
