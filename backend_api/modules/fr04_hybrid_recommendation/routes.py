import hashlib
import json
import logging
import os
from uuid import uuid4
from flask import Blueprint, jsonify, g, request
from auth_utils import auth_required
from utils import utc_now_iso
from services.serpapi_service import retrieveDestinationResults
from services.local_catalog import DESTINATIONS
from services.malaysian_locality import (
    filter_candidates,
    normalize_destination_scope,
    validate_candidate,
)
from sequence_contract.firebase_firestore import retrieveRecord, storeRecord
from sequence_contract.domain_functions import (
    prepareRecommendationInput,
    applyContentBasedFiltering,
    applyCollaborativeFiltering,
    calculateRecommendationScore,
    rankRecommendations,
)

bp = Blueprint('fr04_recommendations', __name__, url_prefix='/api/fr4')
logger = logging.getLogger(__name__)


def _fallback_mode():
    return os.getenv('FALLBACK_MODE', 'false').lower() in {'1', 'true', 'yes'}


def _requested_area(value):
    return normalize_destination_scope(value).get('scopeKey') or ''


def _is_destination_relevant(item, destination_area):
    eligible, _ = validate_candidate(item, destination_area)
    return eligible


def _filter_for_destination(items, destination_area):
    accepted, _ = filter_candidates(items, destination_area)
    return accepted


def _preference_version(preference):
    explicit = (
        preference.get('preferenceProfileVersion')
        or preference.get('profileVersion')
        or preference.get('version')
        or preference.get('updatedAt')
    )
    if explicit:
        return str(explicit)
    encoded = json.dumps(preference or {}, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')
    return f"profile_{hashlib.sha256(encoded).hexdigest()[:16]}"


def _provider_destinations(query, location):
    scope = location if isinstance(location, dict) else normalize_destination_scope(location)
    result = retrieveDestinationResults(
        query,
        scope.get('canonicalName') or str(location or ''),
        {
            'latitude': scope.get('latitude'),
            'longitude': scope.get('longitude'),
        },
    )
    items = list(result.get('local_results', []) or [])
    normalized = []
    for raw in items:
        item = dict(raw or {})
        did = str(
            item.get('destinationId')
            or item.get('place_id')
            or item.get('data_id')
            or item.get('data_cid')
            or item.get('id')
            or item.get('title')
            or ''
        ).strip()
        if not did:
            continue
        item['destinationId'] = did
        item['category'] = item.get('category') or item.get('type') or ''
        item['description'] = item.get('description') or item.get('type') or item.get('address') or ''
        normalized.append(item)
    return normalized


def _snapshot_item(item, source):
    result = dict(item or {})
    result['recommendationSource'] = source
    result['finalScore'] = result.get('score', 0)
    result['recommendationReason'] = result.get('reason', '')
    return result


def _snapshot_response_view(record):
    record = dict(record or {})
    scope = record.get('canonicalDestinationScope')
    if not isinstance(scope, dict):
        scope = normalize_destination_scope(
            record.get('requestedDestination') or record.get('destinationArea')
        )
    safe_results, rejected = filter_candidates(
        record.get('recommendationResults', []),
        scope,
    )
    if rejected:
        logger.warning(
            'Response geographic guard removed %s stored candidate(s) from snapshot %s',
            len(rejected),
            record.get('recommendationGenerationId'),
        )
    return {**record, 'recommendationResults': safe_results}


@bp.post('/recommendations/generate')
@auth_required(['traveller'])
def generate():
    pref = retrieveRecord('travel_preferences', g.uid)
    if not pref:
        return jsonify({'ok': False, 'error': 'Complete travel preferences first'}), 400

    payload = request.get_json(silent=True) or {}
    destination_area = str(payload.get('destinationArea') or payload.get('location') or 'Malaysia').strip()
    destination_scope = normalize_destination_scope(destination_area)
    if not destination_scope.get('resolved'):
        return jsonify({
            'ok': False,
            'error': 'Requested Malaysian destination could not be resolved',
        }), 400
    search_query = str(payload.get('query') or '').strip()
    if not search_query:
        interests = pref.get('interests') or []
        interest_text = ' '.join(str(x) for x in interests[:3])
        search_query = f"{interest_text} tourist attractions".strip()

    candidates = []
    source = 'cache'

    # Prefer live destination information when SerpApi is configured.
    if os.getenv('SERPAPI_KEY', '').strip():
        try:
            candidates = _filter_for_destination(
                _provider_destinations(search_query, destination_scope),
                destination_scope,
            )
            source = 'live_provider'
            for item in candidates[:30]:
                did = str(item.get('destinationId') or '')
                if did:
                    storeRecord('destination_cache', {
                        **item,
                        'requestedDestination': destination_area,
                        'canonicalDestinationScope': destination_scope['scopeKey'],
                        'canonicalDestinationName': destination_scope['canonicalName'],
                        'recommendationSource': 'live_provider',
                        'cachedAt': utc_now_iso(),
                    }, did, merge=True)
        except Exception:
            candidates = []

    if not candidates:
        cached = retrieveRecord(
            'destination_cache',
            filters=[('canonicalDestinationScope', '==', destination_scope['scopeKey'])],
            limit=150,
        )
        if cached:
            candidates = _filter_for_destination(cached, destination_scope)
            source = 'cache'

    if not candidates and _fallback_mode():
        fallback_candidates = [dict(x) for x in DESTINATIONS]
        try:
            admin_items = retrieveRecord('admin_destinations') or []
            for ad in admin_items:
                if isinstance(ad, dict) and ad.get('status', 'active') != 'archived':
                    fallback_candidates.append(dict(ad))
        except Exception:
            pass
        candidates = _filter_for_destination(fallback_candidates, destination_scope)
        source = 'fallback'

    if not candidates:
        return jsonify({'ok': False, 'error': 'No recommendation candidates are available. Configure SerpApi or enable FALLBACK_MODE.'}), 502

    collaborative = [x for x in retrieveRecord('feedback', limit=500) if str(x.get('feedbackStatus','visible')).lower() == 'visible']
    peer_profiles_raw = retrieveRecord('travel_preferences', limit=500)
    peer_profiles = {
        str(row.get('travellerId') or row.get('id') or ''): row
        for row in (peer_profiles_raw or [])
        if str(row.get('travellerId') or row.get('id') or '')
    }

    prepared = prepareRecommendationInput(pref, candidates, collaborative)
    content = applyContentBasedFiltering(prepared)
    combined = applyCollaborativeFiltering(
        content,
        collaborative,
        peerPreferences=peer_profiles,
        currentPreference=pref,
    )
    scored = calculateRecommendationScore(combined)
    ranked_candidates = rankRecommendations(scored)
    final_candidates, rejected_final = filter_candidates(
        ranked_candidates,
        destination_scope,
    )
    if rejected_final:
        logger.warning(
            'Final geographic guard rejected %s recommendation candidate(s) for %s',
            len(rejected_final),
            destination_scope['scopeKey'],
        )
    ranked = [_snapshot_item(item, source) for item in final_candidates[:12]]
    if not ranked:
        return jsonify({
            'ok': False,
            'error': 'No geographically eligible recommendation candidates are available',
        }), 502

    generation_id = uuid4().hex
    record = {
        'recommendationGenerationId': generation_id,
        'userId': g.uid,
        'travellerId': g.uid,
        'generatedAt': utc_now_iso(),
        'requestedDestination': destination_area,
        'destinationArea': destination_area,
        'canonicalDestinationScope': destination_scope,
        'preferenceProfileVersion': _preference_version(pref),
        'source': source,
        'engine': {
            'contentBasedFiltering': True,
            'collaborativeFiltering': True,
            'weightedScoring': {'content': 0.60, 'collaborative': 0.30, 'popularity': 0.10},
            'ranking': True,
        },
        'recommendationResults': ranked,
    }
    storeRecord('recommendation_snapshots', record, generation_id)

    response_record = _snapshot_response_view(record)
    return jsonify({
        'ok': True,
        'recommendationGenerationId': generation_id,
        'snapshot': response_record,
        'recommendations': response_record['recommendationResults'],
        'source': source,
        'engine': record['engine'],
    })


@bp.get('/recommendations')
@auth_required(['traveller'])
def get_recommendations():
    generation_id = str(request.args.get('generationId') or '').strip()
    destination_area = str(request.args.get('destinationArea') or '').strip()
    if generation_id:
        record = retrieveRecord('recommendation_snapshots', generation_id) or {}
        if not record or record.get('travellerId') != g.uid:
            return jsonify({'ok': False, 'error': 'Recommendation snapshot not found'}), 404
    else:
        snapshots = retrieveRecord(
            'recommendation_snapshots',
            filters=[('travellerId', '==', g.uid)],
            limit=50,
        ) or []
        if destination_area:
            requested = _requested_area(destination_area)
            snapshots = [
                item for item in snapshots
                if _requested_area(item.get('requestedDestination') or item.get('destinationArea')) == requested
            ]
        snapshots.sort(key=lambda item: str(item.get('generatedAt') or ''), reverse=True)
        record = snapshots[0] if snapshots else {}
    response_record = _snapshot_response_view(record)
    return jsonify({
        'ok': True,
        'recommendationGenerationId': response_record.get('recommendationGenerationId', ''),
        'recommendation': response_record,
        'snapshot': response_record,
        'recommendations': response_record.get('recommendationResults', []),
        'source': response_record.get('source', ''),
        'engine': response_record.get('engine', {}),
    })
