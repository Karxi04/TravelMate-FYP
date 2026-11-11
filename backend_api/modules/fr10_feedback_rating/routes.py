from flask import Blueprint, request, jsonify, g
from auth_utils import auth_required
from utils import utc_now_iso
from sequence_contract.firebase_firestore import retrieveRecord, claimRecord, updateRecord, deleteRecord
from services.review_service import valid_review, review_id, screen_submission, ReviewConflict
from services.review_destination import review_destination_id, review_destination_ids
from google.api_core.exceptions import Aborted, DeadlineExceeded

bp = Blueprint('fr10_feedback', __name__, url_prefix='/api/fr10')


@bp.get('/feedback')
@auth_required(['traveller'])
def own_feedback():
    return jsonify({'ok': True, 'items': retrieveRecord('feedback', filters=[('travellerId', '==', g.uid)])})


@bp.post('/feedback')
@auth_required(['traveller'])
def submit_feedback():
    payload = request.get_json(silent=True)
    if not valid_review(payload):
        return jsonify({'ok': False, 'error': 'Choose a place, rate it 1–5 and write 5–2000 characters.'}), 400
    payload = {**payload, 'destinationId': review_destination_id(payload['destinationId']),
               'comment': payload['comment'].strip()}
    try:
        existing = [
            item for identity in review_destination_ids(payload['destinationId'])
            for item in retrieveRecord('feedback', filters=[
                ('travellerId', '==', g.uid), ('destinationId', '==', identity),
            ]) or []
        ]
        existing = sorted(existing, key=lambda x: str(x.get('submittedAt') or ''), reverse=True)
        profile = retrieveRecord('users', g.uid) or {}
        now = utc_now_iso()
        data = {**payload, 'travellerId': g.uid, 'travellerName': profile.get('name') or 'Traveller',
                'submittedAt': now, 'updatedAt': now, **screen_submission(payload['comment'], payload['rating'])}
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
                    review_destination_id(result.get('destinationId') or '') != payload['destinationId']):
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
    if 'comment' in payload:
        payload['comment'] = payload['comment'].strip()
    if all(current.get(key) == value for key, value in payload.items()):
        return jsonify({'ok': True, 'feedback': current})
    screening = screen_submission(
        payload.get('comment', current.get('comment', '')),
        payload.get('rating', current.get('rating')),
    )
    updates = {**payload, 'updatedAt': utc_now_iso(), **screening}
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
