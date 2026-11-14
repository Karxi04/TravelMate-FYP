import hashlib
import json
import logging
import os
import traceback
from pathlib import Path
from uuid import uuid4
from math import isfinite
from flask import Blueprint, jsonify, g, request
from google.cloud.firestore_v1 import GeoPoint
from google.api_core.exceptions import GoogleAPICallError, InvalidArgument
from werkzeug.exceptions import HTTPException
from auth_utils import auth_required
from utils import utc_now_iso
from services.serpapi_service import retrieveDestinationResults
from services.local_catalog import DESTINATIONS
from services.pricing_registry import enrich_candidate_pricing
from services.review_service import published_review
from services.recommendation_taxonomy import candidate_concepts
from services.recommendation_discovery import DISCOVERY_MODE, discovery_annotations, discovery_queries, enrich_discovery_candidate, is_planning_candidate
from services.recommendation_snapshot_storage import validation_reason
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
from sequence_contract.firebase_firestore import (
    loadRecommendationSnapshot, retrieveRecord, storeRecord, transactPreferenceLearning,
)
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


def _correlation_id():
    return g.setdefault('recommendation_request_id',uuid4().hex[:16])


@bp.before_request
def correlate_request():
    _correlation_id()


@bp.after_request
def correlate_response(response):
    response.headers['X-Request-ID'] = _correlation_id()
    response.headers['X-TravelMate-Recommendations'] = DISCOVERY_MODE
    return response


@bp.errorhandler(Exception)
def recommendation_failure(error):
    if isinstance(error, HTTPException):
        return jsonify(ok=False,error='The recommendation request could not be completed.',
                       requestId=_correlation_id()),error.code
    frames = [f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}'
              for frame in traceback.extract_tb(error.__traceback__)]
    # Never log exception values, request payloads, tokens, UIDs or stored records.
    logger.error('recommendation_failure request_id=%s type=%s frames=%s',
                 _correlation_id(),type(error).__name__,' > '.join(frames))
    return jsonify(ok=False,error='Recommendations are temporarily unavailable. Please try again.',
                   code='recommendations_unavailable',requestId=_correlation_id()), (503 if isinstance(error,GoogleAPICallError) else 500)


def _firestore_json_values(value):
    if isinstance(value,GeoPoint):
        return {'latitude':value.latitude,'longitude':value.longitude}
    if isinstance(value,dict):
        return {key:_firestore_json_values(item) for key,item in value.items()}
    if isinstance(value,(list,tuple)):
        return [_firestore_json_values(item) for item in value]
    return value


def _fallback_mode():
    return os.getenv('FALLBACK_MODE', 'false').lower() in {'1', 'true', 'yes'}


def _requested_area(value):
    return normalize_destination_scope(value).get('scopeKey') or ''


def _is_destination_relevant(item, destination_area):
    eligible, _ = validate_candidate(item, destination_area)
    return eligible


def _filter_for_destination(items, destination_area):
    accepted, _ = filter_candidates(_firestore_json_values(items), destination_area)
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


def _profile_fingerprint(preference):
    return hashlib.sha256(json.dumps(preference,sort_keys=True,separators=(',', ':'),default=str).encode()).hexdigest()


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
    if not isinstance(payload,dict):
        return jsonify(ok=False,error='Use a JSON object.'),400
    item, error, status = _feedback_destination(payload, g.uid)
    if item is None:
        return jsonify({'ok': False, 'error': error}), status
    concepts = canonical_concepts(
        item.get('destinationConcepts') or candidate_concepts(item))
    try:
        updated, event, changed = transactPreferenceLearning(g.uid, lambda current: apply_explicit_feedback(
            current,
            user_id=g.uid,
            destination_id=_destination_id(item),
            feedback_type=str(payload.get('feedbackType') or '').strip(),
            destination_concepts=concepts,
            recommendation_generation_id=payload.get(
                'recommendationGenerationId', ''),
            source_context=payload.get(
                'sourceContext', 'recommendation_card'),
        ))
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception:
        return jsonify(ok=False,error='Feedback could not be saved. Please retry.'),503
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
    try:
        reset, event, had_learning = transactPreferenceLearning(g.uid, lambda current: reset_learning_profile(current, user_id=g.uid))
    except Exception:
        return jsonify(ok=False,error='Preference learning could not be reset. Please retry.'),503
    return jsonify({
        'ok': True,
        'changed': had_learning,
        'learning': public_learning_state(reset),
    })


def _provider_destinations(query, location, start=0):
    scope = location if isinstance(location, dict) else normalize_destination_scope(location)
    result = retrieveDestinationResults(
        query,
        scope.get('canonicalName') or str(location or ''),
        {
            'latitude': scope.get('latitude'),
            'longitude': scope.get('longitude'),
        },
        **({'start': start} if start else {}),
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
        if 'rating' in item:
            item['ratingSource'] = 'provider'
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
    record = _firestore_json_values(dict(record or {}))
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
            'Response geographic guard removed %s stored candidate(s)',
            len(rejected),
        )
    return {**record, 'recommendationResults': safe_results}


def _page(record, options):
    try:
        discovery = options.get('discoveryMode')
        if discovery not in (None,'',DISCOVERY_MODE):raise ValueError
        basis = options.get('scoreBasis') or 'hybrid_v1'
        if basis not in {'hybrid_v1','personal_v2'}:raise ValueError
        if any(isinstance(options.get(key),bool) for key in ('minimumMatchScore','offset','limit')):
            raise ValueError
        minimum = float(options.get('minimumMatchScore', 0))
        offset = int(options.get('offset', 0))
        limit = int(options.get('limit', 12))
        if any(isinstance(options.get(key),float) and not options[key].is_integer() for key in ('offset','limit')):
            raise ValueError
        if not 0 <= minimum <= 100 or not 0 <= offset <= 200 or not 1 <= limit <= 50:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        return None
    view = _snapshot_response_view(record)
    all_items = view['recommendationResults']
    qualified = []
    for item in all_items:
        if options.get('purpose') == 'trip_planning' and not is_planning_candidate(item):
            continue
        if discovery:
            if item.get('discoveryEligible') is True:qualified.append(item)
            continue
        try:
            score = float(item.get('personalSuitabilityScore') if basis=='personal_v2' else item.get('finalScore') if item.get('finalScore') is not None else item.get('score') or 0)
            if isfinite(score) and 0 <= score <= 100 and score >= minimum:
                qualified.append(item)
        except (ValueError,TypeError,OverflowError):
            continue
    end = offset + limit
    return {**view, 'recommendationResults': qualified[offset:end], 'pagination': {
        'minimumMatchScore': minimum, 'scoreBasis':basis, 'offset': offset, 'limit': limit,
        'discoveryMode': discovery or None, 'thresholdApplied': not bool(discovery),
        'candidateCount': len(all_items), 'qualifiedCount': len(qualified),
        'personalEvidenceCount': sum(isinstance(item.get('personalSuitabilityScore'), (int,float)) and not isinstance(item.get('personalSuitabilityScore'),bool) for item in all_items),
        'nextOffset': end if end < len(qualified) else None,
        'hasMore': end < len(qualified), 'providerHasMore': bool(record.get('providerHasMore')),
    }}


@bp.post('/recommendations/generate')
@auth_required(['traveller'])
def generate():
    pref = retrieveRecord('travel_preferences', g.uid)
    if not pref:
        return jsonify({'ok': False, 'error': 'Complete travel preferences first'}), 400

    learned_profile = retrieveRecord('learned_preference_profiles', g.uid)
    if (not isinstance(pref.get('interests',[]),list) or
            (learned_profile and (not isinstance(learned_profile,dict) or
             not isinstance(learned_profile.get('feedbackByDestination',{}),dict) or
             any(not isinstance(learned_profile.get(key,{}) or {},dict) for key in ('affinities','evidence')) or
             any(not isinstance(state,dict) for state in learned_profile.get('feedbackByDestination',{}).values())))):
        logger.warning('recommendation_profile_review request_id=%s',_correlation_id())
        return jsonify(ok=False,error='Saved recommendation preferences need review. Update your preferences or reset recommendation learning.',
                       code='recommendation_profile_review',requestId=_correlation_id()),409
    effective_pref = effective_preference_profile(pref, learned_profile)
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload,dict):
        return jsonify(ok=False,error='Use a JSON object.'),400
    if _page({}, payload) is None:
        return jsonify(ok=False, error='Invalid recommendation threshold or page.'), 400
    destination_area = str(payload.get('destinationArea') or payload.get('location') or 'Malaysia').strip()
    destination_scope = normalize_destination_scope(destination_area)
    if not destination_scope.get('resolved'):
        return jsonify({
            'ok': False,
            'error': 'Requested Malaysian destination could not be resolved',
        }), 400
    search_query = str(payload.get('query') or '').strip()
    if not search_query:
        search_query = 'tourist attractions'

    candidates = []
    source = 'cache'
    previous_id = str(payload.get('previousGenerationId') or '')
    previous = retrieveRecord('recommendation_snapshots', previous_id) if previous_id else None
    previous_scope = previous.get('canonicalDestinationScope') if previous else None
    previous_key = previous_scope.get('scopeKey') if isinstance(previous_scope,dict) else None
    if previous and not previous_key:
        previous_key = _requested_area(previous.get('requestedDestination') or previous.get('destinationArea'))
    if previous_id and (not previous or previous.get('travellerId') != g.uid or previous_key != destination_scope['scopeKey']):
        return jsonify(ok=False, error='Recommendation snapshot not found for this destination.'), 404
    try:
        provider_offset = int((previous or {}).get('providerNextOffset') or 0)
        if not 0 <= provider_offset <= 60 or provider_offset % 20:provider_offset = 0
    except (TypeError,ValueError,OverflowError):provider_offset = 0
    expand = payload.get('expandCandidates') is True
    if previous:
        candidates = _filter_for_destination(previous.get('recommendationResults') or [], destination_scope)
        source = previous.get('source', 'cache')
    provider_has_more = bool((previous or {}).get('providerHasMore'))

    cached = retrieveRecord(
        'destination_cache',
        filters=[] if destination_scope['scopeKey'] == 'my' else [('canonicalDestinationScope', '==', destination_scope['scopeKey'])],
        limit=150,
    )
    if not cached and destination_scope.get('state'):
        cached = retrieveRecord('destination_cache', filters=[('normalizedGeography.state','==',destination_scope['state'])], limit=150)
    if len(cached or []) < 150 and destination_scope['scopeKey'] != 'my':
        # Older seed/cache records predate scope fields; geography still gates every row.
        cached = list(cached or []) + list(retrieveRecord('destination_cache',limit=150) or [])
    if cached:
        # Latest grounded metadata wins for the same identity; prior-only candidates survive.
        refreshed = {_destination_id(item):item for item in _filter_for_destination(cached, destination_scope)}
        candidates = [{**item, **refreshed.get(_destination_id(item), {})} for item in candidates]
        candidates += list(refreshed.values())

    if search_query != 'tourist attractions' or payload.get('discoveryMode') != DISCOVERY_MODE:
        provider_queries = [search_query]
    elif previous and isinstance(previous.get('providerQueries'),list) and previous.get('providerQueries') and all(isinstance(query,str) and query for query in previous['providerQueries'][:2]) and previous.get('preferenceFingerprint') == _profile_fingerprint(pref) and previous.get('preferenceProfileVersion') == _preference_version(pref,learned_profile):
        provider_queries = previous['providerQueries'][:2]
    else:
        provider_queries = discovery_queries(effective_pref,candidates)
    if previous and previous.get('providerQueries') != provider_queries:
        provider_offset = 0
        provider_has_more = bool(os.getenv('SERPAPI_KEY','').strip())

    # Prefer live destination information when SerpApi is configured.
    if os.getenv('SERPAPI_KEY', '').strip() and (not previous or (expand and provider_has_more and provider_offset < 60)):
        try:
            batches = [_provider_destinations(query,destination_scope,provider_offset) for query in provider_queries]
            discovered = [item for batch in batches for item in batch]
            candidates += _filter_for_destination(
                discovered,
                destination_scope,
            )
            source = 'live_provider'
            provider_offset += 20
            provider_has_more = any(len(batch) >= 20 for batch in batches) and provider_offset < 60
            for item in _filter_for_destination(discovered, destination_scope)[:40]:
                did = str(item.get('destinationId') or '')
                if did:
                    try:
                        storeRecord('destination_cache', {
                            **item,
                            'requestedDestination': destination_area,
                            'canonicalDestinationScope': destination_scope['scopeKey'],
                            'canonicalDestinationName': destination_scope['canonicalName'],
                            'recommendationSource': 'live_provider',
                            'cachedAt': utc_now_iso(),
                        }, did, merge=True)
                    except InvalidArgument as error:
                        # The candidate remains in the ranked snapshot even if
                        # Firestore rejects its optional discovery cache entry.
                        logger.warning('recommendation_cache_invalid request_id=%s reason=%s',
                                       _correlation_id(), validation_reason(error))
        except Exception as error:
            logger.warning('recommendation_provider_unavailable request_id=%s type=%s',
                           _correlation_id(),type(error).__name__)
            # Keep an existing snapshot useful when a later provider page fails.
            if expand:
                return jsonify(ok=False, error='Additional destinations could not be loaded. Your current results are preserved.'), 502


    if not candidates and _fallback_mode():
        fallback_candidates = [{**x,'ratingSource':'unverified_local_catalog'} for x in DESTINATIONS]
        try:
            admin_items = retrieveRecord('admin_destinations') or []
            for ad in admin_items:
                if isinstance(ad, dict) and ad.get('status', 'active') != 'archived':
                    fallback_candidates.append({**ad,'ratingSource':'unverified_local_catalog'})
        except Exception:
            pass
        candidates = _filter_for_destination(fallback_candidates, destination_scope)
        source = 'fallback'

    if not candidates:
        return jsonify({'ok': False, 'error': 'No recommendation candidates are available. Configure SerpApi or enable FALLBACK_MODE.'}), 502

    local_ids = {_destination_id(item) for item in DESTINATIONS}
    candidates = [{**item,'ratingSource':'unverified_local_catalog'} if
                  _destination_id(item) in local_ids and item.get('ratingSource') != 'provider' else item for item in candidates]
    candidates = [enrich_discovery_candidate(item) for item in candidates]

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
        effective_pref,
        limit=150,
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
    ranked = [{**_snapshot_item(item, source),**discovery_annotations(item,effective_pref)}
              for item in final_candidates[:150]]

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
        'preferenceFingerprint': _profile_fingerprint(pref),
        'source': source,
        'scoreBasis':payload.get('scoreBasis') or 'hybrid_v1',
        'providerHasMore': provider_has_more,
        'providerNextOffset': provider_offset,
        'providerQueries': provider_queries,
        'engine': {
            'discoveryVersion': DISCOVERY_MODE,
            'scoringVersion':'recovery_v3',
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
    try:
        storeRecord('recommendation_snapshots', record, generation_id)
    except InvalidArgument as error:
        logger.warning('recommendation_snapshot_invalid request_id=%s reason=%s candidates=%d compressed_bytes=%s',
                       _correlation_id(), validation_reason(error), len(ranked),
                       getattr(error, 'snapshot_bytes', 'unavailable'))
        raise

    response_record = _page(record, payload)
    return jsonify({
        'ok': True,
        'recommendationGenerationId': generation_id,
        'snapshot': response_record,
        'recommendations': response_record['recommendationResults'],
        'source': source,
        'engine': record['engine'],
        'pagination': response_record['pagination'],
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
        record = loadRecommendationSnapshot(snapshots[0]) if snapshots else {}
    preference = retrieveRecord('travel_preferences', g.uid)
    learned = retrieveRecord('learned_preference_profiles', g.uid)
    stale = bool(record and isinstance(preference, dict) and isinstance(preference.get('interests'), list)
                 and (record.get('preferenceProfileVersion') != _preference_version(preference, learned)
                      or record.get('preferenceFingerprint') != _profile_fingerprint(preference)))
    engine = record.get('engine') if isinstance(record.get('engine'),dict) else {}
    if record and request.args.get('scoreBasis') == 'personal_v2' and engine.get('scoringVersion') != 'recovery_v3':
        stale = True
    if record and request.args.get('discoveryMode') and engine.get('discoveryVersion') != DISCOVERY_MODE:
        stale = True
    response_record = _page(record, request.args)
    if response_record is None:
        return jsonify(ok=False, error='Invalid recommendation threshold or page.'), 400
    if stale:
        response_record['recommendationResults'] = []
    return jsonify({
        'ok': True,
        'recommendationGenerationId': response_record.get('recommendationGenerationId', ''),
        'recommendation': response_record,
        'snapshot': response_record,
        'recommendations': response_record.get('recommendationResults', []),
        'source': response_record.get('source', ''),
        'engine': response_record.get('engine', {}),
        'pagination': response_record['pagination'],
        'stale': stale,
    })


@bp.get('/settings')
@auth_required(['traveller'])
def recommendation_settings():
    settings = retrieveRecord('recommendation_settings', g.uid) or {}
    return jsonify(ok=True, minimumMatchScore=settings.get('minimumMatchScore', 70),
                   scoreBasis=settings.get('scoreBasis') or ('hybrid_v1' if 'minimumMatchScore' in settings else 'personal_v2'))


@bp.put('/settings')
@auth_required(['traveller'])
def save_recommendation_settings():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload,dict):
        return jsonify(ok=False,error='Use a JSON object.'),400
    value = payload.get('minimumMatchScore')
    previous=retrieveRecord('recommendation_settings',g.uid) or {}
    basis=payload.get('scoreBasis') or previous.get('scoreBasis') or 'hybrid_v1'
    if basis not in {'hybrid_v1','personal_v2'}:
        return jsonify(ok=False,error='Choose personal match or legacy hybrid ranking.'),400
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 40 <= value <= 90:
        return jsonify(ok=False, error='Choose a minimum match between 40 and 90.'), 400
    storeRecord('recommendation_settings', {'travellerId':g.uid, 'minimumMatchScore':value,'scoreBasis':basis, 'updatedAt':utc_now_iso()}, g.uid)
    return jsonify(ok=True, minimumMatchScore=value,scoreBasis=basis)
