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
from services.pricing_registry import enrich_candidate_pricing
from services.review_service import published_review
from services.recommendation_taxonomy import candidate_concepts
from services.preference_learning import (
    apply_explicit_feedback,
    canonical_concepts,
    effective_preference_profile,
    effective_profile_version,
    public_learning_state,
    reset_learning_profile,
)
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
    deduplicateRecommendations,
    diversifyRecommendations,
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


def _preference_version(preference, learned_profile=None):
    explicit = (
        preference.get('preferenceProfileVersion')
        or preference.get('profileVersion')
        or preference.get('version')
        or preference.get('updatedAt')
    )
    if explicit:
        base_version = str(explicit)
    else:
        encoded = json.dumps(preference or {}, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')
        base_version = f"profile_{hashlib.sha256(encoded).hexdigest()[:16]}"
    return effective_profile_version(base_version, learned_profile)


def _destination_id(item):
    return str(
        (item or {}).get('destinationId')
        or (item or {}).get('place_id')
        or (item or {}).get('data_id')
        or (item or {}).get('id')
        or (item or {}).get('title')
        or ''
    ).strip()


def _feedback_destination(payload, user_id):
    destination_id = str(payload.get('destinationId') or '').strip()
    generation_id = str(
        payload.get('recommendationGenerationId') or '').strip()
    if not destination_id:
        return None, 'destinationId is required', 400
    if generation_id:
        snapshot = retrieveRecord('recommendation_snapshots', generation_id)
        owner_id = str((snapshot or {}).get('travellerId') or
                       (snapshot or {}).get('userId') or '')
        if not snapshot or owner_id != user_id:
            return None, 'Recommendation snapshot not found', 404
        for item in snapshot.get('recommendationResults', []) or []:
            if _destination_id(item) == destination_id:
                return dict(item), '', 200
        return None, 'Destination does not belong to this recommendation snapshot', 409
    concepts = canonical_concepts(payload.get('destinationConcepts', []))
    if not concepts:
        concepts = sorted(candidate_concepts(payload))
    return {**payload, 'destinationId': destination_id,
            'destinationConcepts': concepts}, '', 200


@bp.get('/preference-feedback')
@auth_required(['traveller'])
def get_preference_feedback():
    profile = retrieveRecord('learned_preference_profiles', g.uid)
    return jsonify({'ok': True, 'learning': public_learning_state(profile)})


@bp.post('/preference-feedback')
@auth_required(['traveller'])
def submit_preference_feedback():
    payload = request.get_json(silent=True) or {}
    item, error, status = _feedback_destination(payload, g.uid)
    if item is None:
        return jsonify({'ok': False, 'error': error}), status
    concepts = canonical_concepts(
        item.get('destinationConcepts') or candidate_concepts(item))
    current = retrieveRecord('learned_preference_profiles', g.uid)
    try:
        updated, event, changed = apply_explicit_feedback(
            current,
            user_id=g.uid,
            destination_id=_destination_id(item),
            feedback_type=str(payload.get('feedbackType') or '').strip(),
            destination_concepts=concepts,
            recommendation_generation_id=payload.get(
                'recommendationGenerationId', ''),
            source_context=payload.get(
                'sourceContext', 'recommendation_card'),
        )
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    if changed:
        storeRecord('learned_preference_profiles', updated, g.uid, merge=True)
        storeRecord(
            'recommendation_feedback_events', event,
            event['feedbackEventId'])
    return jsonify({
        'ok': True,
        'changed': changed,
        'feedbackEvent': event,
        'learning': public_learning_state(updated),
        'message': 'Thanks — this will help improve future recommendations.',
    })


@bp.delete('/preference-feedback')
@auth_required(['traveller'])
def reset_preference_feedback():
    current = retrieveRecord('learned_preference_profiles', g.uid)
    reset, event, had_learning = reset_learning_profile(
        current, user_id=g.uid)
    storeRecord('learned_preference_profiles', reset, g.uid, merge=True)
    storeRecord(
        'recommendation_feedback_events', event,
        event['feedbackEventId'])
    return jsonify({
        'ok': True,
        'changed': had_learning,
        'learning': public_learning_state(reset),
    })


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
    result = enrich_candidate_pricing(item or {})
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

    learned_profile = retrieveRecord('learned_preference_profiles', g.uid)
    effective_pref = effective_preference_profile(pref, learned_profile)
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

    collaborative = [x for x in retrieveRecord('feedback', limit=500) if published_review(x)]
    peer_profiles_raw = retrieveRecord('travel_preferences', limit=500)
    peer_profiles = {
        str(row.get('travellerId') or row.get('id') or ''): row
        for row in (peer_profiles_raw or [])
        if str(row.get('travellerId') or row.get('id') or '')
    }

    prepared = prepareRecommendationInput(
        effective_pref, candidates, collaborative)
    content = applyContentBasedFiltering(prepared)
    combined = applyCollaborativeFiltering(
        content,
        collaborative,
        peerPreferences=peer_profiles,
        currentPreference=pref,
        currentTravellerId=g.uid,
    )
    scored = calculateRecommendationScore(combined)
    unique_candidates = deduplicateRecommendations(scored)
    ranked_candidates = diversifyRecommendations(
        rankRecommendations(unique_candidates),
        pref,
        limit=12,
    )
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
        'preferenceProfileVersion': _preference_version(
            pref, learned_profile),
        'source': source,
        'engine': {
            'contentBasedFiltering': True,
            'collaborativeFiltering': True,
            'weightedScoring': {'content': 0.60, 'collaborative': 0.30, 'popularity': 0.10},
            'contentTaxonomy': True,
            'collaborativeColdStart': 'neutral_confidence_aware',
            'deduplication': True,
            'diversityReranking': True,
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
