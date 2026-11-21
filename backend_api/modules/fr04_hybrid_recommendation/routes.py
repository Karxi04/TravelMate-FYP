import hashlib
import json
import logging
import os
import traceback
from pathlib import Path
from uuid import uuid4
from math import isfinite
from flask import Blueprint, jsonify, g, request, current_app
from google.cloud.firestore_v1 import GeoPoint
from google.api_core.exceptions import GoogleAPICallError, InvalidArgument
from werkzeug.exceptions import HTTPException
from auth_utils import auth_required
from utils import utc_now_iso
from services.serpapi_service import retrieveDestinationResults
from services.destination_candidates import provider_page, cached_candidates, discovery_pool, merge_candidates, normalise, facts_signature
from services.local_catalog import DESTINATIONS
from services.pricing_registry import enrich_candidate_pricing
from services.review_destination import review_destination_id, review_candidate_id
from services.review_service import genuine_review
from services.recommendation_review_evidence import approved_contributions, review_summaries
from services import demonstration_recommendations
from services.recommendation_taxonomy import candidate_concepts, preference_concepts, display_concepts
from services.recommendation_taxonomy import planning_preferences
from services.recommendation_discovery import (
    DISCOVERY_MODE, discovery_annotations, discovery_queries, enrich_discovery_candidate,
    is_administrative_facility, is_planning_candidate,
)
from services.recommendation_snapshot_storage import validation_reason, latest_snapshot
from services.preference_learning import (
    apply_explicit_feedback,
    canonical_concepts,
    effective_preference_profile,
    effective_profile_version,
    public_learning_state,
    reset_learning_profile,
)
from services.malaysian_locality import (
    destination_locations, resolve_destination_scope, resolve_selected_scope, search_destination_locations,
    filter_candidates,
    normalize_destination_scope,
    validate_candidate,
    discovery_scope,
)
from sequence_contract.firebase_firestore import (
    loadRecommendationSnapshot, retrieveRecord, retrieveRecordsById, storeRecord, transactPreferenceLearning,
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


def _demonstration_allowed():
    return request.headers.get('X-TravelMate-Review-Context') == 'fyp-v1' and (
        bool(current_app.config.get('LOCAL_FYP_SAMPLE_REVIEWS')) or
        bool(os.getenv('FYP_REVIEW_VIEWER_UID', '').strip() == g.uid))


def _evaluation_mode():
    return current_app.config.get('RECOMMENDATION_EVIDENCE_MODE', 'genuine') == 'fyp_evaluation'


def _evaluation_session():
    return current_app.extensions.setdefault('recommendation_evaluation', demonstration_recommendations.EvaluationSession())


def _evaluation_recommendations(options, *, generate=False):
    if not _demonstration_allowed():
        return jsonify(ok=False, error='Evaluation recommendations require the authorized local review context.'), 403
    if options.get('evidenceMode', 'genuine') != 'genuine' or _page({}, options) is None:
        return jsonify(ok=False, error='Evidence configuration is server-controlled; use valid recommendation options.'), 400
    session = _evaluation_session()
    generation_id = str(options.get('previousGenerationId' if generate else 'generationId') or '')
    previous = session.snapshot(g.uid, generation_id) if generation_id else None
    if generation_id and not previous:
        return jsonify(ok=False, error='Evaluation recommendations expired or belong to another context. Regenerate recommendations.'), 404
    if not generate and not generation_id and not options.get('destinationArea'):
        previous = session.snapshot(g.uid)  # Home follows the owner's latest area, as genuine mode does.
    area = str(options.get('destinationArea') or (previous or {}).get('requestedDestination') or 'Malaysia').strip()
    try:
        geographic_mode = options.get('geographicMode', (previous or {}).get('canonicalDestinationScope', {}).get('geographicMode'))
        scope = discovery_scope(resolve_selected_scope(area, options.get('destinationScopeKey'), options.get('destinationLocationId')), geographic_mode)
        if not scope.get('resolved'):
            raise ValueError
    except ValueError:
        return jsonify(ok=False, error='Choose a supported Malaysian destination area.'), 400
    if previous and previous['canonicalDestinationScope']['scopeKey'] != scope['scopeKey']:
        return jsonify(ok=False, error='Recommendation generation does not belong to this destination.'), 404
    preference = retrieveRecord('travel_preferences', g.uid)
    if not isinstance(preference, dict) or not isinstance(preference.get('interests'), list):
        return jsonify(ok=False, error='Complete travel preferences first'), 400
    learning = session.learning(g.uid)
    profile = effective_preference_profile(preference, learning)
    record = previous or session.snapshot(g.uid, scope_key=scope['scopeKey'])
    if generate:
        try:
            places, rows = demonstration_recommendations.load_sources(scope)
            candidates = merge_candidates(normalise([*DESTINATIONS, *places], scope, source='local_catalog'),
                                          cached_candidates(retrieveRecord, scope))[:150]
            candidates = [row for row in candidates if row.get('synthetic') is not True
                          and row.get('recommendationEvidenceMode', 'genuine') == 'genuine']
            ranked = demonstration_recommendations.evaluate(profile, candidates, rows, evidence_mode='fyp_evaluation')
        except (ValueError, GoogleAPICallError, TimeoutError):
            return jsonify(ok=False, error='Approved sample community evidence is unavailable. No genuine recommendations were changed.'), 503
        ranked = [{**_snapshot_item(row, 'fyp_evaluation'), **discovery_annotations(row, profile)} for row in ranked]
        datasets = sorted({str(row.get('dataset') or 'penang_private') for row in rows})
        record = {'recommendationGenerationId': 'fyp-evaluation-' + uuid4().hex,
            'travellerId': g.uid, 'recommendationEvidenceMode': 'fyp_evaluation', 'synthetic': True,
            'generatedAt': utc_now_iso(), 'requestedDestination': area, 'canonicalDestinationScope': scope,
            'preferenceProfileVersion': _preference_version(preference, learning),
            'preferenceFingerprint': _profile_fingerprint(preference),
            'planningPreferences': planning_preferences(profile),
            'recommendationResults': ranked, 'source': 'fyp_evaluation', 'providerHasMore': False,
            'requestedInterestConcepts': sorted(preference_concepts(profile.get('interests') or [])),
            'evidenceProvenance': {'source': 'sample_community_evaluation',
                'dataset': '+'.join(datasets), 'datasets': datasets,
                'localReviewPolicy': 'approved_local_first',
                'synthetic': True, 'persistence': 'owner_scoped_process_memory',
                'approvedContributions': sum(map(len, approved_contributions(rows, demonstration=True).values()))},
            'engine': {'discoveryVersion': DISCOVERY_MODE, 'scoringVersion': 'recovery_v3',
                'weightedScoring': {'content': .6, 'collaborative': .3, 'popularity': .1}}}
        session.save(record)
    stale = bool(record and (record['preferenceProfileVersion'] != _preference_version(preference, learning)
                            or record['preferenceFingerprint'] != _profile_fingerprint(preference)))
    page = _page(record or {'canonicalDestinationScope': scope, 'requestedDestination': area}, options, evidence_mode='fyp_evaluation')
    page.pop('travellerId', None)
    if stale:
        page['recommendationResults'] = []
    response = jsonify(ok=True, recommendationEvidenceMode='fyp_evaluation', synthetic=True,
        evidenceProvenance=(record or {}).get('evidenceProvenance', {'source': 'sample_community_evaluation', 'synthetic': True}),
        recommendationGenerationId=(record or {}).get('recommendationGenerationId', ''),
        snapshot=page, recommendations=page['recommendationResults'], pagination=page['pagination'],
        engine=(record or {}).get('engine', {}), source='fyp_evaluation', stale=stale,
        requiresExplicitRegeneration=not record or stale,
        discoveryMessage='No further saved destination candidates are available. No provider search was made.' if options.get('expandCandidates') else None)
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def _correlation_id():
    return g.setdefault('recommendation_request_id',uuid4().hex[:16])


@bp.before_request
def correlate_request():
    _correlation_id()


@bp.after_request
def correlate_response(response):
    response.headers['X-Request-ID'] = _correlation_id()
    response.headers['X-TravelMate-Recommendations'] = DISCOVERY_MODE
    response.headers['X-TravelMate-Recommendation-Evidence'] = current_app.config.get('RECOMMENDATION_EVIDENCE_MODE', 'genuine')
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
        snapshot = (_evaluation_session().snapshot(user_id, generation_id) if _evaluation_mode()
                    else None if generation_id.startswith('fyp-evaluation-') else retrieveRecord('recommendation_snapshots', generation_id))
        owner_id = str((snapshot or {}).get('travellerId') or
                       (snapshot or {}).get('userId') or '')
        if not snapshot or owner_id != user_id:
            return None, 'Recommendation snapshot not found', 404
        for item in snapshot.get('recommendationResults', []) or []:
            if _destination_id(item) == destination_id:
                return dict(item), '', 200
        return None, 'Destination does not belong to this recommendation snapshot', 409
    if _evaluation_mode():
        return None, 'Choose a destination from your current evaluation recommendations.', 409
    concepts = canonical_concepts(payload.get('destinationConcepts', []))
    if not concepts:
        concepts = sorted(candidate_concepts(payload))
    return {**payload, 'destinationId': destination_id,
            'destinationConcepts': concepts}, '', 200


@bp.get('/preference-feedback')
@auth_required(['traveller'])
def get_preference_feedback():
    if _evaluation_mode() and not _demonstration_allowed():
        return jsonify(ok=False, error='Evaluation recommendations require the authorized local review context.'), 403
    profile = _evaluation_session().learning(g.uid) if _evaluation_mode() else retrieveRecord('learned_preference_profiles', g.uid)
    return jsonify({'ok': True, 'learning': public_learning_state(profile)})


@bp.post('/preference-feedback')
@auth_required(['traveller'])
def submit_preference_feedback():
    if _evaluation_mode() and not _demonstration_allowed():
        return jsonify(ok=False, error='Evaluation recommendations require the authorized local review context.'), 403
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload,dict):
        return jsonify(ok=False,error='Use a JSON object.'),400
    item, error, status = _feedback_destination(payload, g.uid)
    if item is None:
        return jsonify({'ok': False, 'error': error}), status
    concepts = canonical_concepts(
        item.get('destinationConcepts') or candidate_concepts(item))
    try:
        update = lambda current: apply_explicit_feedback(
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
        updated, event, changed = (_evaluation_session().learning(g.uid, update) if _evaluation_mode()
                                 else transactPreferenceLearning(g.uid, update))
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
    if _evaluation_mode() and not _demonstration_allowed():
        return jsonify(ok=False, error='Evaluation recommendations require the authorized local review context.'), 403
    try:
        update = lambda current: reset_learning_profile(current, user_id=g.uid)
        reset, event, had_learning = (_evaluation_session().learning(g.uid, update) if _evaluation_mode()
                                     else transactPreferenceLearning(g.uid, update))
    except Exception:
        return jsonify(ok=False,error='Preference learning could not be reset. Please retry.'),503
    return jsonify({
        'ok': True,
        'changed': had_learning,
        'learning': public_learning_state(reset),
    })


def _provider_destinations(query, location, start=0):
    return provider_page(retrieveDestinationResults, query, location, start)


def _snapshot_item(item, source):
    result = enrich_candidate_pricing(item or {})
    result['recommendationSource'] = source
    result['finalScore'] = result.get('score', 0)
    result['recommendationReason'] = result.get('reason', '')
    return result


def _snapshot_response_view(record, evidence_mode='genuine'):
    record = _firestore_json_values(dict(record or {}))
    scope = record.get('canonicalDestinationScope')
    if not isinstance(scope, dict):
        scope = normalize_destination_scope(
            record.get('requestedDestination') or record.get('destinationArea')
        )
    safe_results, rejected = filter_candidates(
        [row for row in record.get('recommendationResults', [])
         if row.get('recommendationEvidenceMode', 'genuine') == evidence_mode
         and (row.get('synthetic') is True if evidence_mode == 'fyp_evaluation' else row.get('synthetic') is not True)],
        scope,
    )
    if rejected:
        logger.warning(
            'Response geographic guard removed %s stored candidate(s)',
            len(rejected),
        )
    return {**record, 'recommendationResults': safe_results}


def _page(record, options, *, evidence_mode='genuine'):
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
    view = _snapshot_response_view(record, evidence_mode)
    all_items = view['recommendationResults']
    qualified = []
    for item in all_items:
        if (is_administrative_facility(item)
                or options.get('purpose') == 'trip_planning' and not is_planning_candidate(item)):
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
    search_status = 'matches' if qualified else 'no_relevant_matches' if all_items else 'no_candidates'
    stored_scope = record.get('canonicalDestinationScope')
    area = (stored_scope.get('canonicalName') if isinstance(stored_scope, dict) else None) or record.get('requestedDestination') or 'this destination'
    diagnostics = dict(record.get('discoveryDiagnostics') or {})
    if not all_items and diagnostics.get('rawProviderCount') and not diagnostics.get('geographicallyValidCount'):
        search_status = 'no_exact_locality_matches'
    nearby = isinstance(stored_scope, dict) and stored_scope.get('geographicMode') == 'nearby'
    search_message = (None if qualified else f'Attractions were found, but none match your interests or selected threshold for {area}.' if all_items
                      else f'No verified nearby attractions within 10 km straight-line distance of {area}.' if nearby
                      else f'No attractions could be verified within the exact locality {area}. You can explicitly explore nearby places.' if search_status == 'no_exact_locality_matches'
                      else f'No verified destination candidates are available for {area}.')
    diagnostics.update(preferenceMatchCount=len(qualified), displayedCount=len(qualified[offset:end]))
    coverage = {concept: {'eligible': sum(concept in r.get('discoveryMatchedConcepts',[]) for r in all_items),
                          'displayed': sum(concept in r.get('discoveryMatchedConcepts',[]) for r in qualified[offset:end])}
                for concept in record.get('requestedInterestConcepts',[])}
    missing = [c for c,v in coverage.items() if not v['eligible']]
    elsewhere = [c for c,v in coverage.items() if v['eligible'] and not v['displayed']]
    return {**view, 'searchStatus': search_status, 'searchMessage': search_message,
        'interestCoverage': coverage,
        'coverageNotice': ('No verified eligible candidates for: '+', '.join(display_concepts(missing))+'. The geographic scope has not been expanded.') if missing else (
            'This page has no matches for: '+', '.join(display_concepts(elsewhere))+'. Matching candidates exist elsewhere in this saved generation.' if elsewhere else None),
        'nearbyAvailable': bool(isinstance(stored_scope, dict) and stored_scope.get('city')
                                and stored_scope.get('coordinateStatus') == 'verified_locality'),
        'discoveryDiagnostics': diagnostics,
        'recommendationResults': qualified[offset:end], 'pagination': {
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
    if _evaluation_mode():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify(ok=False, error='Use a JSON object.'), 400
        return _evaluation_recommendations(payload, generate=True)
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
    if payload.get('evidenceMode', 'genuine') != 'genuine':
        return jsonify(ok=False, error='Use the separate Demonstration review data view.'), 400
    if _page({}, payload) is None:
        return jsonify(ok=False, error='Invalid recommendation threshold or page.'), 400
    destination_area = str(payload.get('destinationArea') or payload.get('location') or 'Malaysia').strip()
    try:
        destination_scope = resolve_selected_scope(destination_area, payload.get('destinationScopeKey'), payload.get('destinationLocationId'))
        destination_scope = discovery_scope(destination_scope, payload.get('geographicMode'))
    except ValueError:
        return jsonify(ok=False, error='Choose a supported Malaysian destination area.'), 400
    except Exception:
        return jsonify(ok=False, code='location_lookup_unavailable', error='The selected Malaysian location could not be verified. Please try its location lookup again.'), 502
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
    if previous_id and (not previous or previous.get('travellerId') != g.uid or previous_key != destination_scope['scopeKey']
                        or previous.get('recommendationEvidenceMode', 'genuine') != 'genuine'):
        return jsonify(ok=False, error='Recommendation snapshot not found for this destination.'), 404
    expand = payload.get('expandCandidates') is True
    displayed = payload.get('displayedDestinationIds', [])
    previous_ids = {_destination_id(r) for r in (previous or {}).get('recommendationResults', [])}
    if (not isinstance(displayed, list) or len(displayed) > 150 or
            any(not isinstance(v, str) or v not in previous_ids for v in displayed)):
        return jsonify(ok=False, error='Displayed destinations must belong to the previous generation.'), 400
    cache = cached_candidates(retrieveRecord, destination_scope)
    candidates = merge_candidates(normalise((previous or {}).get('recommendationResults', []), destination_scope, source='snapshot'), cache)
    cursors = (previous or {}).get('providerCursors') or {}
    stored_queries = (previous or {}).get('providerQueries') or []
    previous_queries = [q for q in stored_queries if isinstance(q, str) and len(q) <= 200][:3] if isinstance(stored_queries, list) else []
    if not isinstance(cursors, dict):
        cursors = {}
    if previous and not cursors:
        # Legacy snapshots share one offset; never infer further pages from candidate count.
        offset = previous.get('providerNextOffset')
        cursors = {q: offset if previous.get('providerHasMore') and type(offset) is int and offset in (20, 40) else None for q in previous_queries}
    used = (previous or {}).get('providerRequestsUsed')
    if type(used) is not int or not 0 <= used <= 6:
        offset = (previous or {}).get('providerNextOffset')
        offset = offset if type(offset) is int and offset in (0, 20, 40, 60) else 0
        used = min(6, len(previous_queries) * max(1, offset // 20))
    planned = ([search_query] if search_query != 'tourist attractions' or payload.get('discoveryMode') != DISCOVERY_MODE
               else discovery_queries(effective_pref, candidates))
    pending = [q for q in previous_queries if cursors.get(q) is not None]
    provider_queries = list(dict.fromkeys([*pending, *planned]))[:3]
    pool = discovery_pool(retrieveRecord, _provider_destinations, destination_scope, effective_pref,
        previous=(previous or {}).get('recommendationResults', []), cached=cache,
        queries=provider_queries, cursors=cursors, used=used,
        allow_provider=bool(os.getenv('SERPAPI_KEY', '').strip()) and (not previous or expand))
    candidates = pool['items']
    source = pool['source'] if pool['providerRequests'] else (previous or {}).get('source', 'cache')
    provider_has_more = pool['providerHasMore']
    next_offsets = [v for v in pool['cursors'].values() if type(v) is int]
    provider_offset = min(next_offsets) if next_offsets else 60
    if pool['providerErrors']:
        logger.warning('recommendation_provider_unavailable request_id=%s types=%s',
                       _correlation_id(), ','.join(pool['providerFailureTypes']))
    for item in pool['providerItems']:
        did = _destination_id(item)
        try:
            storeRecord('destination_cache', {**item, 'requestedDestination': destination_area,
                'canonicalDestinationScope': destination_scope['scopeKey'],
                'canonicalDestinationName': destination_scope['canonicalName'],
                'recommendationSource': 'live_provider', 'cachedAt': utc_now_iso()}, did, merge=True)
        except InvalidArgument as error:
            logger.warning('recommendation_cache_invalid request_id=%s reason=%s', _correlation_id(), validation_reason(error))

    if not candidates and _fallback_mode():
        fallback_candidates = [{**x,'ratingSource':'unverified_local_catalog'} for x in DESTINATIONS]
        try:
            admin_items = retrieveRecord('admin_destinations') or []
            for ad in admin_items:
                if isinstance(ad, dict) and ad.get('status', 'active') != 'archived':
                    fallback_candidates.append({**ad,'ratingSource':'unverified_local_catalog'})
        except Exception:
            pass
        candidates = [item for item in _filter_for_destination(fallback_candidates, destination_scope)
                      if is_planning_candidate(item)]
        source = 'fallback'

    if not candidates and pool['providerErrors']:
        return jsonify(ok=False, code='destination_provider_unavailable',
                       error='Destination search is temporarily unavailable and no verified saved places are available for this area.'), 502
    if not candidates and not os.getenv('SERPAPI_KEY', '').strip() and not _fallback_mode():
        return jsonify(ok=False, code='discovery_unavailable',
                       error='Destination search is not configured and no verified saved places are available for this area.'), 503

    if expand and previous and not pool['providerRequests'] and facts_signature(candidates) == facts_signature(previous['recommendationResults']):
        page = _page(previous, {**payload, 'offset': len(displayed)})
        return jsonify(ok=True, recommendationGenerationId=previous_id, snapshot=page,
                       recommendations=page['recommendationResults'], pagination=page['pagination'],
                       source=previous.get('source'), expanded=False,
                       discoveryMessage='No additional matching places found in the available candidates.')

    local_ids = {_destination_id(item) for item in DESTINATIONS}
    candidates = [{**item,'ratingSource':'unverified_local_catalog'} if
                  _destination_id(item) in local_ids and item.get('ratingSource') != 'provider' else item for item in candidates]
    candidates = [enrich_discovery_candidate(item) for item in candidates
                  if item.get('synthetic') is not True and item.get('recommendationEvidenceMode', 'genuine') == 'genuine']

    # This is a retrieval cap, not a minimum evidence requirement.
    groups = approved_contributions(retrieveRecord('feedback', limit=500) or [])
    summaries = review_summaries(groups)
    collaborative = [row for group in groups.values() for row in group]
    candidate_ids = {review_candidate_id(row) for row in candidates}
    reviewer_ids = {str(row.get('travellerId') or '') for row in collaborative
                    if review_destination_id(str(row.get('destinationId') or '')) in candidate_ids} - {'', str(g.uid)}
    peer_profiles = {}
    for profile in retrieveRecordsById('travel_preferences', reviewer_ids):
        uid = str(profile.get('id') or '')
        if (uid in reviewer_ids and str(profile.get('travellerId') or uid) == uid and genuine_review(profile)
                and profile.get('recommendationEvidenceMode', 'genuine') == 'genuine'):
            peer_profiles[uid] = profile

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
    scored = calculateRecommendationScore(combined, summaries)
    unique_candidates = deduplicateRecommendations(scored)
    ranked_candidates = diversifyRecommendations(
        rankRecommendations(unique_candidates),
        effective_pref,
        limit=150,
        coverageAware=payload.get('discoveryMode') == DISCOVERY_MODE,
    )
    ranked_ids = {_destination_id(row) for row in ranked_candidates}
    ranked_candidates += [row for row in unique_candidates if _destination_id(row) in displayed
                          and _destination_id(row) not in ranked_ids]
    final_candidates, rejected_final = filter_candidates(
        ranked_candidates,
        destination_scope,
    )
    if destination_scope.get('geographicMode') == 'nearby' and len(preference_concepts(effective_pref.get('interests') or [])) <= 1:
        final_candidates.sort(key=lambda row: (-float(row.get('score') or 0), row['nearbyDistanceKm']))
    if rejected_final:
        logger.warning(
            'Final geographic guard rejected %s recommendation candidate(s) for %s',
            len(rejected_final),
            destination_scope['scopeKey'],
        )
    ranked = [{**_snapshot_item(item, source),**discovery_annotations(item,effective_pref)}
              for item in final_candidates]

    # Continue after the already displayed eligible prefix, retaining its visible order.
    by_id = {_destination_id(row): row for row in ranked}
    retained = [by_id[key] for key in dict.fromkeys(displayed) if key in by_id] if expand else []
    retained_ids = {_destination_id(row) for row in retained}
    ranked = (retained + [row for row in ranked if _destination_id(row) not in retained_ids])[:150]
    ranked = [{**row, 'candidatePoolRankNo': row.get('rankNo'), 'rankNo': i + 1} for i, row in enumerate(ranked)]
    generation_id = uuid4().hex
    record = {
        'recommendationGenerationId': generation_id,
        'recommendationEvidenceMode': 'genuine',
        'userId': g.uid,
        'travellerId': g.uid,
        'generatedAt': utc_now_iso(),
        'requestedDestination': destination_area,
        'destinationArea': destination_area,
        'canonicalDestinationScope': destination_scope,
        'preferenceProfileVersion': _preference_version(
            pref, learned_profile),
        'preferenceFingerprint': _profile_fingerprint(pref),
        'planningPreferences': planning_preferences(effective_pref),
        'source': source,
        'cacheFallbackNotice': ('Using saved destination metadata; some cache dates are stale or unavailable. Check venue details before travelling.'
            if source != 'live_provider' and any(row.get('cacheFreshness') in {'stale', 'unknown'} for row in ranked) else None),
        'scoreBasis':payload.get('scoreBasis') or 'hybrid_v1',
        'providerHasMore': provider_has_more,
        'providerNextOffset': provider_offset,
        'providerQueries': list(pool['cursors']) or provider_queries,
        'providerCursors': pool['cursors'],
        'providerRequestsUsed': pool['providerRequestsUsed'],
        'previousGenerationId': previous_id or None,
        'requestedInterestConcepts': sorted(preference_concepts(effective_pref.get('interests') or [])),
        'discoveryDiagnostics': {'providerRequests': pool['providerRequests'], 'providerErrors': pool['providerErrors'],
                                 **pool['diagnostics'], 'candidateCount': len(ranked), 'retainedDisplayedCount': len(retained)},
        'engine': {
            'discoveryVersion': DISCOVERY_MODE,
            'scoringVersion':'recovery_v3',
            'listSelection': 'strong_interest_coverage_v1' if payload.get('discoveryMode') == DISCOVERY_MODE else 'bounded_diversity',
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

    page_options = dict(payload)
    if retained:
        retained_page = _page({**record, 'recommendationResults': retained}, payload)
        page_options['offset'] = retained_page['pagination']['qualifiedCount']
    response_record = _page(record, page_options)
    return jsonify({
        'ok': True,
        'recommendationGenerationId': generation_id,
        'snapshot': response_record,
        'recommendations': response_record['recommendationResults'],
        'source': source,
        'engine': record['engine'],
        'pagination': response_record['pagination'],
        'discoveryMessage': ('Provider search is temporarily unavailable; available saved candidates are preserved.'
                             if pool['providerErrors'] == pool['providerRequests'] and pool['providerRequests'] else
                             f"Found {len(response_record['recommendationResults'])} additional matching places."
                             if response_record['recommendationResults'] else
                             'No additional matching places found in the available candidates.') if expand or pool['providerErrors'] else record.get('cacheFallbackNotice'),
    })


@bp.get('/recommendations')
@auth_required(['traveller'])
def get_recommendations():
    if _evaluation_mode():
        return _evaluation_recommendations(request.args)
    if request.args.get('evidenceMode', 'genuine') != 'genuine':
        return jsonify(ok=False, error='Use the separate Demonstration review data view.'), 400
    generation_id = str(request.args.get('generationId') or '').strip()
    if generation_id.startswith('fyp-evaluation-'):
        return jsonify(ok=False, error='Recommendation snapshot not found'), 404
    destination_area = str(request.args.get('destinationArea') or '').strip()
    record = None
    if generation_id:
        record = retrieveRecord('recommendation_snapshots', generation_id) or {}
        if (not record or record.get('travellerId') != g.uid
                or record.get('recommendationEvidenceMode', 'genuine') != 'genuine'):
            return jsonify({'ok': False, 'error': 'Recommendation snapshot not found'}), 404
    scope = resolve_destination_scope(destination_area) if destination_area else None
    stored = record.get('canonicalDestinationScope') if record else None
    mode = request.args.get('geographicMode')
    if mode not in (None, '', 'strict', 'nearby'):
        return jsonify(ok=False, error='Choose strict or nearby discovery.'), 400
    if isinstance(stored, dict) and mode is not None and (mode or 'strict') != stored.get('geographicMode', 'strict'):
        return jsonify(ok=False, error='Recommendation snapshot not found for this discovery mode.'), 404
    if mode is None and isinstance(stored, dict):
        mode = stored.get('geographicMode')
    if scope and scope.get('resolved'):
        try:
            scope = discovery_scope(scope, mode)
        except ValueError:
            return jsonify(ok=False, error='Choose a verified locality and strict or nearby discovery.'), 400
    if scope and not scope.get('resolved') and isinstance(stored, dict) and stored.get('country') == 'Malaysia':
        if str(stored.get('canonicalName') or '').strip().casefold() == destination_area.casefold():
            scope = stored  # Owned, previously verified immutable scope; no geocoder call on a saved-result read.
    if scope and not scope.get('resolved'):
        return jsonify(ok=False, error='Choose a supported Malaysian destination area.'), 400
    if generation_id:
        actual = record.get('canonicalDestinationScope')
        actual = actual if isinstance(actual, dict) else resolve_destination_scope(record.get('requestedDestination'))
        if scope and scope['scopeKey'] != actual.get('scopeKey'):
            return jsonify(ok=False, error='Recommendation snapshot not found for this destination.'), 404
    else:
        record = latest_snapshot(retrieveRecord, loadRecommendationSnapshot, g.uid,
                                 scope)
    if record and record.get('recommendationEvidenceMode', 'genuine') != 'genuine':
        return jsonify(ok=False, error='Recommendation snapshot not found'), 404
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
        'demonstrationAvailable': _demonstration_allowed(),
    })


@bp.get('/recommendations/demonstration')
@auth_required(['traveller'])
def demonstration_recommendations_view():
    if not _demonstration_allowed():
        return jsonify(ok=False, error='Demonstration review data is unavailable in this context.'), 403
    key = request.args.get('profileKey', 'current')
    if key not in {'current', *demonstration_recommendations.SIMULATED_PROFILES}:
        return jsonify(ok=False, error='Choose a supported demonstration profile.'), 400
    areas = sorted({'Penang', 'Malaysia', *(row.get('state') for row in
        demonstration_recommendations.regional_demo_destinations().values() if row.get('state'))})
    area = request.args.get('destinationArea', 'Penang')
    if area not in areas:
        return jsonify(ok=False, error='Choose an available demonstration area.'), 400
    profile = (retrieveRecord('travel_preferences', g.uid) if key == 'current' else
               demonstration_recommendations.SIMULATED_PROFILES[key])
    if not profile or not profile.get('interests'):
        return jsonify(ok=False, error='Complete your preferences or choose a simulated profile.'), 400
    try:
        candidates, rows = demonstration_recommendations.load_sources(area)
        results = demonstration_recommendations.evaluate(profile, candidates, rows)
    except (ValueError, GoogleAPICallError, TimeoutError):
        return jsonify(ok=False, error='Existing demonstration reviews and approvals could not be loaded. No saved recommendations were changed.'), 503
    generation_id = 'demonstration-' + hashlib.sha256(json.dumps(
        [area, profile, results], sort_keys=True, default=str).encode()).hexdigest()[:24]
    response = jsonify(ok=True, recommendationEvidenceMode='demonstration', synthetic=True,
        label='Demonstration review data', recommendationGenerationId=generation_id,
        recommendations=results, destinationArea=area, profileKey=key, areas=areas,
        profiles=[{'key': 'current', 'label': 'My preferences (simulation only)'},
            *[{'key': identity, 'label': value['label']} for identity, value in
              demonstration_recommendations.SIMULATED_PROFILES.items()]],
        disclosure='Simulated traveller profiles and approved demonstration reviews. Read-only results; genuine saved recommendations are unchanged.')
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@bp.get('/locations')
@auth_required(['traveller'])
def supported_locations():
    fields = ('country', 'state', 'city', 'kind', 'canonicalName', 'scopeKey', 'aliases', 'locationId', 'district', 'population', 'dataSource', 'dataLicense')
    return jsonify(ok=True, locations=[{key: row.get(key) for key in fields} for row in destination_locations()])


@bp.get('/locations/search')
@auth_required(['traveller'])
def location_lookup():
    query = str(request.args.get('q') or '').strip()
    if not 2 <= len(query) <= 100:
        return jsonify(ok=False, error='Enter 2 to 100 characters for a Malaysian location.'), 400
    try:
        rows = search_destination_locations(query, remote=request.args.get('remote') == 'true')
        return jsonify(ok=True, locations=rows,
                       message=None if rows else 'No verified Malaysian location was found. Try its state or another established name.')
    except Exception:
        return jsonify(ok=False, code='location_lookup_unavailable',
                       error='Additional Malaysian location lookup is unavailable. Existing suggestions remain available.'), 502


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
