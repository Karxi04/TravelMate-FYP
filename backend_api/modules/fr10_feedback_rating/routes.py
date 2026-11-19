from flask import Blueprint, request, jsonify, g
from auth_utils import auth_required
from utils import utc_now_iso
from sequence_contract.firebase_firestore import retrieveRecord, claimRecord, updateRecord, deleteRecord
from services.review_service import (valid_review, review_id, screen_submission, ReviewConflict,
                                     review_revision, edits_used, MAX_REVIEW_EDITS)
from services.review_destination import review_destination_id, review_destination_ids
from google.api_core.exceptions import Aborted, DeadlineExceeded

bp = Blueprint('fr10_feedback', __name__, url_prefix='/api/fr10')


@bp.get('/feedback')
@auth_required(['traveller'])
def own_feedback():
    rows = retrieveRecord('feedback', filters=[('travellerId', '==', g.uid)])
    return jsonify({'ok': True, 'items': [{**row, 'revision': review_revision(row),
                    'editsRemaining': max(0, MAX_REVIEW_EDITS - edits_used(row))} for row in rows]})


@bp.post('/feedback')
@auth_required(['traveller'])
def submit_feedback():
    payload = request.get_json(silent=True)
    if not valid_review(payload):
        return jsonify({'ok': False, 'error': 'Choose a place, rate it 1–5 and write 5–2000 characters.'}), 400
    opened_id = payload['destinationId']
    canonical = review_destination_id(opened_id)
    if canonical == opened_id and not canonical.startswith('local_'):
        from modules.fr03_destination_search_information.routes import _review_identity
        try:
            cached = retrieveRecord('destination_cache', opened_id.replace('/', '_'))
        except Exception:
            return jsonify(ok=False, error='Reviews are temporarily unavailable. Please try again.'), 503
        if isinstance(cached, dict):
            canonical = _review_identity(cached) or canonical
    payload = {**payload, 'destinationId': canonical,
               'comment': payload['comment'].strip()}
    try:
        existing = [
            item for identity in dict.fromkeys((*review_destination_ids(payload['destinationId']), opened_id))
            for item in retrieveRecord('feedback', filters=[
                ('travellerId', '==', g.uid), ('destinationId', '==', identity),
            ]) or []
        ]
        existing = sorted(existing, key=lambda x: str(x.get('submittedAt') or ''), reverse=True)
        profile = retrieveRecord('users', g.uid) or {}
        now = utc_now_iso()
        data = {**payload, 'travellerId': g.uid, 'travellerName': profile.get('name') or 'Traveller',
                'submittedAt': now, 'updatedAt': now, 'editCount': 0,
                **screen_submission(payload['comment'], payload['rating'])}
        identity = review_id(g.uid, payload['destinationId'])
        try:
            result, created = (existing[0], False) if existing else claimRecord('feedback', identity, data)
        except (Aborted, DeadlineExceeded):
            # A concurrent claim may have committed. One bounded read can safely
            # acknowledge it; never retry a write or return success without a record.
            result = retrieveRecord('feedback', identity)
            if not result:
                raise
            created = False
        if not created:
            if (result.get('travellerId') != g.uid or
                    review_destination_id(result.get('destinationId') or '') not in {payload['destinationId'], opened_id}):
                return jsonify({'ok': False, 'error': 'Review could not be submitted.'}), 409
            if result.get('feedbackStatus') == 'removed':
                return jsonify({'ok': False, 'error': 'This review was removed. Contact support if you need help.'}), 409
            if any(result.get(key) != payload[key] for key in ('rating', 'comment')):
                return jsonify({'ok': False, 'error': 'You already reviewed this place. Edit your existing review.'}), 409
        return jsonify({'ok': True, 'id': result['id'], 'feedback': result, 'reused': not created}), (201 if created else 200)
    except Exception:
        return jsonify({'ok': False, 'error': 'Reviews are temporarily unavailable. Please try again.'}), 503


@bp.put('/feedback/<fid>')
@auth_required(['traveller'])
def update_feedback(fid):
    current = retrieveRecord('feedback', fid)
    if not current or current.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'Feedback not found'}), 404
    if current.get('feedbackStatus') == 'removed':
        return jsonify({'ok': False, 'error': 'This feedback was removed by the Administrator and cannot be republished by editing it'}), 409
    payload = request.get_json(silent=True)
    if not valid_review(payload, partial=True):
        return jsonify({'ok': False, 'error': 'Invalid feedback update'}), 400
    expected_revision = payload.pop('expectedRevision', None)
    expected_updated = payload.pop('expectedUpdatedAt', None)
    if 'comment' in payload:
        payload['comment'] = payload['comment'].strip()
    if all(current.get(key) == value for key, value in payload.items()):
        return jsonify({'ok': True, 'feedback': current})
    if ((expected_revision and expected_revision != review_revision(current))
            or (expected_updated is not None and expected_updated != current.get('updatedAt'))):
        return jsonify(ok=False, error='This review changed. Refresh before editing again.'), 409
    if edits_used(current) >= MAX_REVIEW_EDITS:
        return jsonify(ok=False, error='No edits remaining. Each review can be edited twice.'), 409
    screening = screen_submission(
        payload.get('comment', current.get('comment', '')),
        payload.get('rating', current.get('rating')),
    )
    updates = {**payload, 'editCount': edits_used(current) + 1, 'updatedAt': utc_now_iso(), **screening}
    try:
        return jsonify({'ok': True, 'feedback': updateRecord('feedback', fid, updates, expected=current)})
    except ReviewConflict as error:
        return jsonify({'ok': False, 'error': str(error)}), 409
    except Exception:
        return jsonify({'ok': False, 'error': 'Reviews are temporarily unavailable. Please try again.'}), 503


@bp.delete('/feedback/<fid>')
@auth_required(['traveller'])
def delete_feedback(fid):
    current = retrieveRecord('feedback', fid)
    if not current or current.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'Feedback not found'}), 404
    try:
        deleteRecord('feedback', fid, expected=current)
        return jsonify({'ok': True})
    except ReviewConflict as error:
        return jsonify({'ok': False, 'error': str(error)}), 409
    except Exception:
        return jsonify({'ok': False, 'error': 'Reviews are temporarily unavailable. Please try again.'}), 503
