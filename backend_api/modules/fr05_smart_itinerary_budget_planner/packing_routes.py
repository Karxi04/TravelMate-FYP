"""Owner-scoped checklist with weather resolved outside its write transaction."""
from datetime import datetime, timezone
import json
from flask import g, jsonify, request
from auth_utils import auth_required
from sequence_contract.firebase_firestore import transactPackingChecklist
from services.packing_checklist_service import PackingError, mutate, response_dto, valid_trip_id
from services.packing_weather import packing_weather_trip
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
        if request.method == 'GET':
            current, trip, preferences = transactPackingChecklist(
                iid, g.uid, lambda current, trip, preferences: (None, (current, trip, preferences)))
            return jsonify(ok=True, **response_dto(current, packing_weather_trip(trip, now), preferences, now))

        checked_trip = None
        weather_view = None
        if request.method == 'POST':
            checked_trip = transactPackingChecklist(iid, g.uid, lambda current, trip, preferences: (None, trip))
            weather_view = packing_weather_trip(checked_trip, now)

        def transform(current, trip, preferences):
            if weather_view is not None and trip == checked_trip:
                trip = weather_view
            else:
                trip = packing_weather_trip(trip, now, fetch=False)
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
