"""Shared authorized recommendation evidence; never promotes evaluation rows to Firestore."""
from copy import deepcopy
import hashlib
import json
import os

from flask import current_app, g, request
from services import demonstration_recommendations, review_staging
from services.malaysian_locality import discovery_scope, resolve_selected_scope
from services.preference_learning import effective_profile_version


class SnapshotUnavailable(RuntimeError):
    pass


def evaluation_mode():
    return current_app.config.get('RECOMMENDATION_EVIDENCE_MODE', 'genuine') == 'fyp_evaluation'


def evaluation_allowed():
    return request.headers.get('X-TravelMate-Review-Context') == 'fyp-v1' and (
        bool(current_app.config.get('LOCAL_FYP_SAMPLE_REVIEWS')) or
        bool(os.getenv('FYP_REVIEW_VIEWER_UID', '').strip() == g.uid))


def evaluation_session():
    return current_app.extensions.setdefault('recommendation_evaluation', demonstration_recommendations.EvaluationSession())


def evaluation_evidence_revision(session):
    return f'local-only-v1:{session.evidence_revision()}:{review_staging.evidence_revision()}'


def preference_version(preference, learned_profile=None):
    explicit = next((preference.get(key) for key in
                     ('preferenceProfileVersion','profileVersion','version','updatedAt') if preference.get(key)), None)
    encoded = json.dumps(preference or {}, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')
    base = str(explicit) if explicit else f'profile_{hashlib.sha256(encoded).hexdigest()[:16]}'
    return effective_profile_version(base, learned_profile)


def profile_fingerprint(preference):
    return hashlib.sha256(json.dumps(preference, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def resolve_snapshot(generation_id, destination, read):
    """Resolve only the source selected by the server; preserve legacy genuine reads."""
    if not evaluation_mode():
        if generation_id.startswith('fyp-evaluation-'):
            return None, 'Evaluation recommendations are not available in genuine mode. Refresh suggestions.'
        record = read('recommendation_snapshots', generation_id)
        if not record or record.get('travellerId') != g.uid:
            return None, 'Recommendation snapshot not found for this traveller'
        if record.get('synthetic') is True or (record.get('recommendationEvidenceMode') or 'genuine') != 'genuine':
            return None, 'Recommendation evidence does not belong to genuine mode.'
        return record, None
    if not evaluation_allowed() or not generation_id.startswith('fyp-evaluation-'):
        return None, 'Evaluation recommendations require the authorized local review context. Refresh suggestions.'
    session = evaluation_session()
    record = session.snapshot(g.uid, generation_id)
    if not record or record.get('recommendationGenerationId') != generation_id:
        return None, 'Evaluation suggestions expired or are unavailable in this session. Refresh suggestions.'
    if record.get('recommendationEvidenceMode') != 'fyp_evaluation' or record.get('synthetic') is not True:
        return None, 'Evaluation recommendation evidence is invalid. Refresh suggestions.'
    stored_scope = record.get('canonicalDestinationScope') or {}
    try:
        scope = discovery_scope(resolve_selected_scope(destination), stored_scope.get('geographicMode'))
        if not scope.get('resolved') or scope.get('scopeKey') != stored_scope.get('scopeKey'):
            raise ValueError()
    except (ValueError, TypeError):
        return None, 'Recommendation snapshot destination does not match this trip'
    preference = read('travel_preferences', g.uid)
    if not isinstance(preference, dict) or not isinstance(preference.get('interests'), list):
        return None, 'Complete travel preferences before refreshing suggestions.'
    if (record.get('preferenceProfileVersion') != preference_version(preference, session.learning(g.uid))
            or record.get('preferenceFingerprint') != profile_fingerprint(preference)):
        return None, 'Travel preferences changed. Refresh suggestions before building this trip.'
    try:
        revision = evaluation_evidence_revision(session)
    except review_staging.ReviewStagingUnavailable:
        raise SnapshotUnavailable('Local review evidence is temporarily unavailable. Try building again later.') from None
    if record.get('reviewEvidenceRevision') != revision:
        return None, 'Local review evidence changed. Refresh suggestions before building this trip.'
    result = deepcopy(record)
    rows = result.get('recommendationResults')
    if not isinstance(rows, list) or any(not isinstance(row, dict) or
            row.get('recommendationGenerationId', generation_id) != generation_id for row in rows):
        return None, 'Candidate evidence does not match this recommendation generation. Refresh suggestions.'
    result['recommendationResults'] = [{**row, 'recommendationGenerationId':generation_id} for row in rows]
    return result, None
