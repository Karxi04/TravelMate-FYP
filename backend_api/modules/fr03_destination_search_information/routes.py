import os
from services.destination_candidates import cached_candidates, normalise, same_place, discovery_diagnostics
from services.recommendation_discovery import is_planning_candidate
from services.serpapi_service import destination_pagination
import math
import re
from flask import Blueprint, current_app, request, jsonify, g

from auth_utils import auth_required
from utils import utc_now_iso
from services.local_catalog import DESTINATIONS
from services.destination_research import named_attractions, attraction_identity
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
from services.review_service import approved_reviews, genuine_review
from services.fyp_reviews import (
    dataset_for, dataset_reviews, private_dataset, regional_demo_destinations, regional_demo_reviews,
    PENANG_DESTINATION_IDS,
)
from services.review_destination import review_destination_id, review_destination_ids
from services.malaysian_locality import (
    normalize_destination_scope,
    resolve_area_query,
    normalize_candidate_geography,
    filter_candidates,
    FOREIGN_DESTINATIONS,
    discovery_scope,
)

bp = Blueprint('fr03_destinations', __name__, url_prefix='/api/fr3')
REVIEW_CONTEXT_HEADER = 'X-TravelMate-Review-Context'


def _local_demo_request():
    return (current_app.config.get('LOCAL_FYP_SAMPLE_REVIEWS')
            and request.headers.get(REVIEW_CONTEXT_HEADER) == 'fyp-v1')


def _private_review_dataset(*, discovery=False):
    if request.headers.get(REVIEW_CONTEXT_HEADER) != 'fyp-v1':
        return None
    if current_app.config.get('LOCAL_FYP_SAMPLE_REVIEWS'):
        return private_dataset() if discovery else None
    if request.args.get('view') != 'samples':
        return dataset_for(g.uid)
    return None


@bp.after_request
def _prevent_shared_review_caching(response):
    if request.endpoint in {
        'fr03_destinations.local_ratings', 'fr03_destinations.ratings_reviews',
        'fr03_destinations.search_destinations', 'fr03_destinations.destination_details',
    }:
        response.headers['Cache-Control'] = 'private, no-store'
        response.vary.add('Authorization')
        response.vary.add(REVIEW_CONTEXT_HEADER)
    if request.endpoint == 'fr03_destinations.destination_details' and response.status_code == 200:
        payload = response.get_json(silent=True)
        if isinstance(payload, dict) and isinstance(payload.get('destination'), dict):
            from services.place_summary import place_summary
            payload['destination']['placeSummary'] = place_summary(payload['destination'])
            response.set_data(current_app.json.dumps(payload))
    return response


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

    try:
        requested = resolve_area_query(raw_location, remote=True)
    except Exception:
        requested = resolve_area_query(raw_location)
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
    return same_place(left, right)


def _enrich_search_result(item):
    """Fill missing trusted geography without replacing provider fields."""
    enriched = dict(item or {})
    enriched.pop('reviewDestinationId', None)
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
    canonical_review = _review_identity(enriched)
    if canonical_review:
        enriched['reviewDestinationId'] = canonical_review
    return enriched


def _deduplicate_results(items):
    output = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        index = next((i for i, existing in enumerate(output) if _same_place(item, existing) or
               (item.get('reviewDestinationId') and (
                    item['reviewDestinationId'] == existing.get('reviewDestinationId')
                    or item['reviewDestinationId'] == _destination_id(existing)))
               or (existing.get('reviewDestinationId') and existing['reviewDestinationId'] == _destination_id(item))
               ), None)
        if index is not None:
            from services.destination_candidates import merge_candidates
            existing = output[index]
            merged = merge_candidates([existing], [item])
            if len(merged) == 1:
                output[index] = merged[0]
            continue
        output.append(item)
    return output


_CATALOG_ALIASES = {
    'local_batu_caves': ('batu caves',),
    'local_klcc': ('klcc', 'petronas twin towers', 'menara berkembar petronas', 'petronas skybridge', 'sky bridge'),
    'local_penang_hill': ('bukit bendera',),
    'local_langkawi_skycab': ('langkawi sky bridge', 'langkawi skycab', 'langkawi cable car', 'sky bridge'),
    'local_legoland_malaysia': ('legoland', 'legoland malaysia'),
}


def _place_names(item):
    return [_search_text(value) for value in (
        item.get('title') or item.get('name'),
        *_CATALOG_ALIASES.get(_destination_id(item), ()),
    ) if value]


def _named_match(item, query):
    tokens = set(query.split()) - _SEARCH_NOISE
    return bool(tokens) and any(tokens <= set(name.split()) for name in _place_names(item))


def _review_identity(item):
    # The main resort is distinct from its hotel, water park and aquarium.
    title = _search_text(item.get('title') or item.get('name'))
    if title not in {'legoland malaysia resort', 'legoland malaysia'}:
        from services.recommendation_taxonomy import primary_concepts
        geo = normalize_candidate_geography(item)
        if geo.get('conflict') or not is_planning_candidate(item):
            return None
        matches = []
        for place in DESTINATIONS:
            if title not in _place_names(place):
                continue
            known_geo = normalize_candidate_geography(place)
            if (geo.get('state') != known_geo.get('state')
                    or not primary_concepts(item).intersection(primary_concepts(place))):
                continue
            distance = _distance_km(_coords(item), _coords(place))
            if distance is not None and distance <= .8:
                matches.append(review_destination_id(place['destinationId']))
        return matches[0] if len(set(matches)) == 1 else None
    geo = normalize_candidate_geography(item)
    if geo.get('conflict') or geo.get('state') != 'Johor':
        return None
    coords = _coords(item)
    distance = _distance_km(coords, (1.427361, 103.62987))
    kind = _search_text(item.get('type') or item.get('category'))
    if distance is not None and distance <= .8 and any(word in kind for word in ('theme park', 'amusement park', 'tourist attraction')):
        return 'local_legoland_malaysia'
    return None


def _relevance_rank(item, query):
    query_text = _search_text(query)
    title = _search_text(item.get('title') or item.get('name'))
    category = _search_text(item.get('type') or item.get('category'))
    address = _search_text(item.get('address') or item.get('location'))
    query_tokens = set(query_text.split()) - _SEARCH_NOISE
    if title == query_text or query_text in _place_names(item):
        tier = 0
    elif title.startswith(query_text):
        tier = 1
    elif query_text and query_text in title:
        tier = 2
    elif query_tokens and _named_match(item, query_text):
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
    known_identity = attraction_identity(reference)
    if known_identity and not any(_destination_id(row) == reference for row in DESTINATIONS):
        return known_identity
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
    description = provider.get('description') or provider.get('editorial_summary')
    if isinstance(description, dict):
        description = description.get('overview') or description.get('snippet')
    if not description:
        description = provider.get('snippet')
    if isinstance(provider.get('description'), dict):
        merged['descriptionDetails'] = provider['description']
    elif provider.get('description'):
        merged.pop('descriptionDetails', None)
    if isinstance(description, str) and description.strip():
        merged['description'] = description.strip()
    highlights = []
    about = provider.get('about')
    if isinstance(about, dict):
        for section, attributes in about.items():
            if isinstance(attributes, dict):
                highlights.extend(str(key) for key, value in attributes.items() if value is True)
            elif isinstance(attributes, list):
                highlights.extend(value for value in attributes if isinstance(value, str))
    extensions = provider.get('extensions')
    if isinstance(extensions, list):
        for section in extensions:
            if not isinstance(section, dict):
                continue
            for key in ('highlights', 'accessibility', 'amenities'):
                values = section.get(key)
                if isinstance(values, list):
                    highlights.extend(value.strip() for value in values
                                      if isinstance(value, str) and 0 < len(value.strip()) <= 100)
    merged['highlights'] = list(dict.fromkeys(highlights))[:12] or cached.get('highlights', [])
    if highlights:
        merged['highlightsSource'] = 'provider_about'
    did = cached.get('destinationId') or _destination_id(cached) or _destination_id(merged)
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
        if genuine_review(item) and isinstance(identity, str) and identity:
            grouped.setdefault(review_destination_id(identity), []).append(item)
    result = {}
    for identity, records in grouped.items():
        approved = approved_reviews(records)
        if approved:
            summary = {'rating': round(sum(float(x['rating']) for x in approved) / len(approved), 1),
                       'reviews': len(approved)}
            for alias in review_destination_ids(identity):
                result[alias] = summary
    return jsonify({'ok': True, 'items': result})


@bp.get('/destinations/search')
@auth_required(['traveller'])
def search_destinations():
    q = request.args.get('q', '').strip()
    try:
        offset = int(request.args.get('offset', 0))
        if offset < 0 or offset > 200 or offset % 20:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'ok': False, 'error': 'Invalid results page.'}), 400
    location_param = request.args.get('location')
    location = (location_param or '').strip()
    filterOption = request.args.get('filter')
    sortOption = request.args.get('sort')

    if not validateSearchInput(q):
        return jsonify({'ok': False, 'error': 'Search query is required'}), 400
    if not validateFilterOption(filterOption) or not validateSortingOption(sortOption):
        return jsonify({'ok': False, 'error': 'Invalid filter or sort option'}), 400

    requested_scope, target_scope, provider_location = _search_scope(location)
    interpretation = 'keyword'
    query_area = normalize_destination_scope(q)
    name_query = _search_text(q)
    catalogue_named = _deduplicate_results([item for item in DESTINATIONS if _named_match(item, name_query)] + named_attractions(q))
    if (location.lower() == 'malaysia'
            and not any(name_query in _place_names(item) for item in catalogue_named)
            and query_area.get('resolved') and query_area.get('city')):
        requested_scope, target_scope, provider_location = _search_scope(q)
        interpretation = 'locality'
    try:
        requested_scope = discovery_scope(requested_scope, request.args.get('geographicMode'))
    except ValueError:
        return jsonify(ok=False, error='Nearby search needs a verified Malaysian locality. Choose strict or nearby discovery.'), 400

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

    if offset == 0 and _local_demo_request():
        matches, _ = filter_candidates(
            [place for place in regional_demo_destinations().values()
             if _search_text(q) == _search_text(place['title'])], requested_scope)
        if matches:
            return jsonify(ok=True, results=_filter_by_category(matches, filterOption),
                           source='fyp_private', nextOffset=None,
                           locationUsed=requested_scope.get('canonicalName') or provider_location)
    demo = _private_review_dataset(discovery=True) if offset == 0 else None
    if demo:
        matches = [place for place in demo[1].values()
                   if _search_text(q) == _search_text(place['title'])]
        matches, _ = filter_candidates(matches, requested_scope)
        if matches:
            results = [_private_destination(place) for place in matches]
            return jsonify({'ok': True, 'results': _filter_by_category(results, filterOption),
                            'source': 'fyp_private', 'nextOffset': None,
                            'locationUsed': requested_scope.get('canonicalName') or provider_location})

    # A validated named-place match stays discoverable even without a provider page.
    named = []
    named_query = _search_text(q)
    general_query = named_query in {
        'attraction', 'tourist attraction', 'places to visit', 'things to do',
        'museum', 'museums', 'temple', 'temples', 'park', 'parks', 'garden', 'beach',
        'food', 'restaurant', 'cafe', 'shopping', 'nature', 'culture',
    }
    nationwide_lookup = (requested_scope.get('scopeKey') == 'my'
                         and interpretation == 'keyword' and not offset and not general_query
                         and _provider_query(q) != 'tourist attractions')
    if nationwide_lookup:
        named = catalogue_named
        named, _ = filter_candidates(named, requested_scope)
        named = _filter_by_category(named, filterOption)
        if len(named) == 1 and named_query in _place_names(named[0]):
            return jsonify(ok=True, source='local_catalog', nextOffset=None,
                           results=normalise(named, requested_scope, source='local_catalog'),
                           locationUsed=requested_scope.get('canonicalName') or provider_location)

    interpreted_query = 'tourist attractions' if interpretation == 'locality' else _provider_query(q)
    if requested_scope.get('geographicMode') == 'nearby':
        interpreted_query = f'{interpreted_query} near {provider_location}'
    coordinates = {
        'latitude': requested_scope.get('latitude'),
        'longitude': requested_scope.get('longitude'),
    }
    provider_unavailable = False
    try:
        args = (interpreted_query, provider_location, coordinates)
        data = retrieveDestinationResults(*args, start=offset) if offset else retrieveDestinationResults(*args)
    except Exception:
        if nationwide_lookup and not named and len(named_query) >= 3:
            try:
                named = [row for row in cached_candidates(retrieveRecord, requested_scope, limit=40)
                         if _named_match(row, named_query)]
            except Exception:
                named = []
        if not named and not _fallback_mode():
            return jsonify({
                'ok': False,
                'error': 'Place search is temporarily unavailable. Please try again.',
                'code': 'destination_provider_unavailable',
            }), 502
        provider_unavailable = True
        normalized_query = _search_text(q)
        query_words = set(normalized_query.split())
        matched = []
        for x in (_all_destinations() if _fallback_mode() else []):
            text = _search_text(' '.join(str(x.get(k, '')) for k in ['title', 'name', 'type', 'category', 'description', 'location', 'address', 'city', 'state']))
            if normalized_query in text or (query_words and query_words.issubset(set(text.split()))):
                matched.append(dict(x))
            elif query_words and any(word in text for word in query_words if len(word) > 3):
                matched.append(dict(x))
        results = named + matched
        source = 'cache' if any(row.get('candidateSource') == 'cache' for row in named) else 'local'

        if not results:
            return jsonify({
                'ok': False,
                'error': 'Live place search is temporarily unavailable. Please try again.',
                'code': 'destination_provider_unavailable',
            }), 502
    else:
        try:
            results = _provider_results(data)
        except ValueError:
            return jsonify({
                'ok': False,
                'error': 'Place search returned an unsupported response. Please try again.',
                'code': 'destination_provider_unavailable',
            }), 502
        source = 'serpapi'

    raw_provider_count = len(results) if source == 'serpapi' else 0
    if source == 'serpapi' and nationwide_lookup:
        if not named and len(named_query) >= 3 and not any(_named_match(row, named_query) for row in results):
            try:
                named = [row for row in cached_candidates(retrieveRecord, requested_scope, limit=40)
                         if _named_match(row, named_query)]
            except Exception:
                named = []
        named = [{**row, 'source': row.get('candidateSource') or 'local_catalog'} for row in named]
        results = [*results, *named]

    # Always merge matching admin-managed destinations from Firestore
    try:
        admin_items = retrieveRecord('admin_destinations') or []
        for ad in admin_items:
            if isinstance(ad, dict) and ad.get('status', 'active') != 'archived':
                text = _search_text(' '.join(str(ad.get(k, '')) for k in ['title', 'name', 'type', 'category', 'description', 'location', 'address', 'city', 'state']))
                if offset == 0 and _search_text(q) in text:
                    did = _destination_id(ad)
                    if not any(_destination_id(r) == did for r in results):
                        results.insert(0, dict(ad))
    except Exception:
        pass

    results = [_enrich_search_result(item) for item in results]
    diagnostics = {**discovery_diagnostics(results, requested_scope),
                   'rawCandidateCount': len(results), 'rawProviderCount': raw_provider_count}
    results = _deduplicate_results(results)
    results, _rejected = filter_candidates(results, requested_scope)
    results = [item for item in results if is_planning_candidate(item)]
    if _search_text(q) in {'food', 'restaurant', 'restaurants', 'cafe', 'cafes', 'hawker centres'}:
        from services.recommendation_taxonomy import primary_concepts
        results = [item for item in results if 'food' in primary_concepts(item)]
    results = _filter_by_category(results, filterOption)
    results = (
        applyDestinationSorting(results, sortOption)
        if sortOption
        else sorted(results, key=lambda item: (_relevance_rank(item, q)[0], item.get('nearbyDistanceKm', 0), _relevance_rank(item, q)[1:])
                    if requested_scope.get('geographicMode') == 'nearby' else _relevance_rank(item, q))
    )

    has_more = destination_pagination(data, offset)['hasMore'] if source == 'serpapi' else len(results) > offset + 20
    if source == 'local':
        results = results[offset:offset + 20]
    results = [row for item in results for row in normalise(
        [item], requested_scope, source=(
            'cache' if item.get('candidateSource') == 'cache' else
            'local_catalog' if item.get('source') == 'local_catalog' or source == 'local' else
            'live_provider' if source == 'serpapi' else 'cache'))]
    for item in results:
        item.pop('_providerOrder', None)
        did = _destination_id(item)
        if did and not item.get('destinationId'):
            item['destinationId'] = did
        if item.get('candidateSource') != 'cache':
            _cache(item)

    diagnostics.update(keywordMatchCount=len(results), displayedCount=len(results))
    if provider_unavailable and not results:
        return jsonify(ok=False, code='destination_provider_unavailable',
                       error='Live place search is temporarily unavailable; no verified saved matches are available for this locality.',
                       discoveryDiagnostics=diagnostics), 502
    status = ('matches' if results else 'provider_unavailable' if provider_unavailable else
              'no_exact_locality_matches' if diagnostics['rawProviderCount'] and not diagnostics['geographicallyValidCount']
              else 'no_matching_attractions' if diagnostics['rawProviderCount'] else 'no_candidates')
    message = (None if results else 'Live place search is temporarily unavailable.' if provider_unavailable else
               'No verified attractions within 10 km straight-line distance of the selected locality.' if requested_scope.get('geographicMode') == 'nearby' else
               'Places were returned, but none could be verified within this exact locality. You can explicitly explore nearby places.' if status == 'no_exact_locality_matches' else
               'No attractions found for this search. Try another keyword or explicitly explore nearby places.')

    return jsonify({
        'ok': True,
        'results': results,
        'source': source,
        'locationUsed': requested_scope.get('canonicalName') or provider_location,
        'providerUnavailable': provider_unavailable,
        'searchStatus': status, 'searchMessage': message, 'discoveryDiagnostics': diagnostics,
        'queryInterpretation': interpretation, 'queryUsed': interpreted_query,
        'canonicalDestinationScope': requested_scope,
        'nearbyAvailable': bool(requested_scope.get('city') and requested_scope.get('coordinateStatus') == 'verified_locality'),
        'nextOffset': offset + 20 if has_more and offset < 200 else None,
    })


@bp.get('/destinations/<path:place_id>')
@auth_required(['traveller'])
def destination_details(place_id):
    researched = attraction_identity(place_id)
    if researched and not any(_destination_id(row) == place_id for row in DESTINATIONS):
        return jsonify(ok=True, destination=researched, source='official_identity', detailsAvailable=False)
    regional = regional_demo_destinations().get(review_destination_id(place_id)) if _local_demo_request() else None
    if regional:
        return jsonify(ok=True, destination=regional, source='fyp_private', detailsAvailable=True)
    demo = _private_review_dataset(discovery=True)
    place = demo[1].get(review_destination_id(place_id)) if demo else None
    if place:
        return jsonify({'ok': True, 'destination': _private_destination(place),
                        'source': 'fyp_private', 'detailsAvailable': True})
    cached = _cached_destination(place_id)
    provider_ref, reference_type = _provider_reference(place_id, cached)

    try:
        data = retrieveDestinationDetails(provider_ref, reference_type)
        provider = data.get('place_results') or data.get('local_results') or data
        if not isinstance(provider, dict):
            provider = {}
        result = _merge_destination(cached, provider)
        canonical_review = _review_identity(result)
        if canonical_review:
            result['reviewDestinationId'] = canonical_review
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


def _private_destination(place):
    known = _local_destination(place['destinationId'])
    return {**place, **(known or {}), 'destinationId': place['destinationId'],
            'place_id': place['destinationId']}


def retrieveRatingsAndReviews(place_id, *, alternate=None):
    """Retrieve TravelMate Traveller reviews from the shared Firestore database."""
    records = [
        item for identity in dict.fromkeys((*review_destination_ids(place_id), *([alternate] if alternate else [])))
        for item in retrieveRecord('feedback', filters=[('destinationId', '==', identity)]) or []
    ]
    return _ratings_and_reviews(records)


def _ratings_and_reviews(records):
    visible = approved_reviews(row for row in records if genuine_review(row))
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
    canonical = review_destination_id(place_id)
    if canonical == place_id and not canonical.startswith('local_'):
        cached = _cached_destination(place_id)
        canonical = (_review_identity(cached) if cached else None) or canonical
    alternate = place_id if canonical != place_id else None
    demo_available = bool(_local_demo_request() or (
        request.headers.get(REVIEW_CONTEXT_HEADER) == 'fyp-v1'
        and os.getenv('FYP_REVIEW_VIEWER_UID', '').strip() == g.uid))
    if request.args.get('view') == 'test':
        if not demo_available:
            return jsonify(ok=False, error='Review testing is unavailable.'), 403
        records = regional_demo_reviews(canonical)
        demo = _private_review_dataset(discovery=True) if _local_demo_request() else dataset_for(g.uid)
        if demo and canonical in demo[1]:
            records = [row for row in dataset_reviews(*demo) if row['destinationId'] == canonical]
        visible = approved_reviews(records)
        result = {
            'rating': round(sum(float(row['rating']) for row in visible) / len(visible), 1) if visible else None,
            'reviews': len(visible), 'user_reviews': [public_review(row) for row in visible],
            'fypPreview': True,
        }
        return jsonify(ok=True, source='fyp_private', result=result,
                       reviewTestModeAvailable=True,
                       disclosure='Fictional review test data. Ratings are separate from visitor reviews.')
    if request.args.get('view') == 'samples':
        return jsonify(ok=False, error='Use the authorized review testing view.'), 404
    result = retrieveRatingsAndReviews(canonical, alternate=alternate)
    if _local_demo_request():
        # One authorized list; genuine aggregates and private provenance stay independent.
        records = regional_demo_reviews(canonical)
        example_status = 'available'
        if not records and canonical in PENANG_DESTINATION_IDS:
            from google.api_core.exceptions import GoogleAPICallError
            try:
                demo = _private_review_dataset(discovery=True)
                if demo and canonical in demo[1]:
                    records = [row for row in dataset_reviews(*demo) if row['destinationId'] == canonical]
            except (ValueError, GoogleAPICallError, TimeoutError) as exc:
                current_app.logger.warning('Private review examples unavailable (%s)', type(exc).__name__)
                example_status = 'unavailable'
        visible = approved_reviews(records)
        examples = [{**public_review(row), 'synthetic': True, 'source': 'fyp_private',
                     'dataset': row.get('dataset') or 'penang_private'} for row in visible]
        result.update(
            user_reviews=result['user_reviews'] + examples,
            privateExamplesAllowed=True,
            sampleSummary={'reviews': len(examples),
                           'rating': round(sum(float(row['rating']) for row in visible)/len(visible), 1) if visible else None},
        )
        return jsonify(ok=True, source='travelmate_database', result=result,
                       reviewEnvironment='private_demo', exampleReviewStatus=example_status)
    return jsonify(ok=True, source='travelmate_database', result=result,
                   **({'reviewTestModeAvailable': True} if demo_available else {}))


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
            'items': [
                {**item, 'id': f"{g.uid}_{item['destinationId']}".replace('/', '_')}
                if item.get('destinationId') else item
                for item in retrieveRecord(
                    'favourites', filters=[('travellerId', '==', g.uid)]
                )
            ],
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
        'id': doc_id,
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
