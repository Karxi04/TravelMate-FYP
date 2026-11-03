"""Backend-only packing resource; no scheduler/provider calls."""
from datetime import datetime, timezone
import json
from flask import g, jsonify, request
from auth_utils import auth_required
from sequence_contract.firebase_firestore import transactPackingChecklist
from services.packing_checklist_service import PackingError, mutate, response_dto, valid_trip_id
from .routes import bp


@bp.route('/itineraries/<iid>/packing-checklist', methods=['GET', 'POST', 'PATCH'])
@auth_required(['traveller'])
def packing_checklist(iid):
    try:
        if not valid_trip_id(iid):
            raise PackingError('Invalid trip ID.')
        payload = {}
        if request.method != 'GET':
            if request.content_length is not None and request.content_length > 16384:
                raise PackingError('Checklist request is too large.', 413)
            raw = request.stream.read(16385)
            if len(raw) > 16384:
                raise PackingError('Checklist request is too large.', 413)
            try:
                payload = json.loads(raw) if request.is_json else None
            except (ValueError, UnicodeDecodeError):
                raise PackingError('Use a JSON object.')
            if not isinstance(payload, dict):
                raise PackingError('Use a JSON object.')
            action = payload.get('action', 'generate')
            if (not isinstance(action, str)
                    or (request.method == 'POST' and action not in {'generate', 'refresh'})
                    or (request.method == 'PATCH' and action not in {'add', 'update', 'remove', 'restore'})):
                raise PackingError('Use the supported action for this method.')
        now = datetime.now(timezone.utc)

        def transform(current, trip, preferences):
            if request.method == 'GET':
                return None, {'ok': True, **response_dto(current, trip, preferences, now)}
            updated, changes = mutate(current, trip, preferences, g.uid, iid, payload, now)
            return updated, {'ok': True, **response_dto(updated, trip, preferences, now), 'changes': changes}

        return jsonify(transactPackingChecklist(iid, g.uid, transform))
    except PackingError as error:
        body = {'ok': False, 'error': str(error)}
        if error.revision is not None:
            body['currentRevision'] = error.revision
        return jsonify(body), error.status
    except Exception:
        return jsonify(ok=False, error='Packing checklist is temporarily unavailable. Please try again.'), 503
