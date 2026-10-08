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


@bp.get('/destinations/search')
@auth_required(['traveller'])
def search_destinations():
    q = request.args.get('q', '').strip()
    location = request.args.get('location', 'Malaysia').strip() or 'Malaysia'
    filterOption = request.args.get('filter')
    sortOption = request.args.get('sort')

    if not validateSearchInput(q):
        return jsonify({'ok': False, 'error': 'Search query is required'}), 400
    if not validateFilterOption(filterOption) or not validateSortingOption(sortOption):
        return jsonify({'ok': False, 'error': 'Invalid filter or sort option'}), 400

    try:
        data = retrieveDestinationResults(q, location)
        results = data.get('local_results', [])
        source = 'serpapi'
    except Exception as exc:
        if not _fallback_mode():
            return jsonify({'ok': False, 'error': str(exc)}), 502
        query_words = set(re.findall(r'\w+', q.lower()))
        matched = []
        for x in _all_destinations():
            text = (' '.join(str(x.get(k, '')) for k in ['title', 'name', 'type', 'category', 'description', 'location', 'address', 'city', 'state'])).lower()
            if q.lower() in text or (query_words and query_words.issubset(set(re.findall(r'\w+', text)))):
                matched.append(dict(x))
            elif query_words and any(word in text for word in query_words if len(word) > 3):
                matched.append(dict(x))
        results = matched
        source = 'local'

    # Always merge matching admin-managed destinations from Firestore
    try:
        admin_items = retrieveRecord('admin_destinations') or []
        for ad in admin_items:
            if isinstance(ad, dict) and ad.get('status', 'active') != 'archived':
                text = (' '.join(str(ad.get(k, '')) for k in ['title', 'name', 'type', 'category', 'description', 'location', 'address', 'city', 'state'])).lower()
                if q.lower() in text:
                    did = _destination_id(ad)
                    if not any(_destination_id(r) == did for r in results):
                        results.insert(0, dict(ad))
    except Exception:
        pass

    results = applyDestinationSorting(
        applyDestinationFilter(results, filterOption),
        sortOption,
    )

    for item in results[:30]:
        did = _destination_id(item)
        if did and not item.get('destinationId'):
            item['destinationId'] = did
        _cache(item)

    return jsonify({'ok': True, 'results': results, 'source': source})


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
    visible = [x for x in records if str(x.get('feedbackStatus', 'visible')).lower() == 'visible']
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
        'review_summary': 'Ratings and reviews submitted by TravelMate Travellers and available for Administrator moderation.' if reviews else 'No Traveller reviews have been submitted for this place yet.',
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
        did = _destination_id(row)
        if did and did == _destination_id(base):
            continue
        distance = _distance_km(base_coords, _coords(row))
        if distance is None:
            continue
        if distance <= float(request.args.get('radiusKm', 12) or 12):
            item = dict(row)
            item['distanceKm'] = round(distance, 1)
            item['nearbyReason'] = f"{item.get('title', 'Place')} is about {distance:.1f} km from {base.get('title') or base.get('name') or 'the selected place'}."
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
