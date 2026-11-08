"""Evaluate due events when the authenticated Traveller opens/refreshes the app."""
from datetime import datetime, timezone
from flask import Blueprint, g, jsonify, request
from auth_utils import auth_required
from sequence_contract.firebase_firestore import retrieveRecord, claimRecord, storeRecord, updateRecord
from services.traveller_notifications import derive_events, event_id, trip_start, active_trip, coordinates, MYT
from services.packing_checklist_service import checklist_id
from services.open_meteo_service import retrieveSevenDayForecast

bp = Blueprint('traveller_notifications', __name__, url_prefix='/api/traveller/notifications')


@bp.get('')
@auth_required(['traveller'])
def notifications():
    now = datetime.now(timezone.utc)
    try:
        orders = retrieveRecord('checkout_orders', filters=[('travellerId','==',g.uid)]) or []
        orders += retrieveRecord('payment_records', filters=[('travellerId','==',g.uid)]) or []
        trips = retrieveRecord('itineraries', filters=[('travellerId','==',g.uid)]) or []
        checklists, forecasts = {}, {}
        upcoming = [t for t in trips if t.get('travellerId') == g.uid and active_trip(t) and trip_start(t)
                    and 0 <= (trip_start(t) - now.astimezone(MYT).date()).days <= 6]
        upcoming.sort(key=lambda t:(t['startDate'],str(t.get('id'))))
        for trip in upcoming:
            tid = str(trip['id'])
            if (trip_start(trip)-now.astimezone(MYT).date()).days in {1,3}:
                checklists[tid] = retrieveRecord('packing_checklists', checklist_id(g.uid,tid)) or {}
        weather_unavailable = 0
        for trip in upcoming[:3]:
            coords = coordinates(trip)
            if not coords:
                weather_unavailable += 1
                continue
            cache_id = event_id(g.uid,'weather_cache',[trip['id'],coords,int(now.timestamp())//21600])
            cached = retrieveRecord('notification_weather_cache', cache_id)
            if not cached:
                cached, created = claimRecord('notification_weather_cache',cache_id,{'travellerId':g.uid,'checkedAt':now.isoformat(),'forecast':{}})
                if created:
                    try:
                        forecast = retrieveSevenDayForecast(coords)
                        if not isinstance(forecast,dict) or not isinstance(forecast.get('daily'),dict):
                            raise ValueError('Forecast unavailable')
                        cached = {'travellerId':g.uid,'checkedAt':now.isoformat(),'forecast':forecast}
                        storeRecord('notification_weather_cache',cached,cache_id)
                    except Exception:
                        weather_unavailable += 1
            if cached.get('travellerId') == g.uid:
                forecasts[trip['id']] = cached.get('forecast') or {}
        for event in derive_events(g.uid,orders,trips,checklists,forecasts,now):
            claimRecord('traveller_notifications',event['id'],event)
        items = retrieveRecord('traveller_notifications',filters=[('travellerId','==',g.uid)]) or []
        items = [item for item in items if item.get('travellerId') == g.uid]
        items.sort(key=lambda item:str(item.get('createdAt') or ''), reverse=True)
        return jsonify(ok=True,items=items,unreadCount=sum(not item.get('read') for item in items),
                       evaluation='on_open_or_refresh',weatherUnavailable=weather_unavailable)
    except Exception:
        return jsonify(ok=False,error='Notifications could not be refreshed. Please try again.'),503


@bp.patch('/<notification_id>')
@auth_required(['traveller'])
def mark_read(notification_id):
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload,dict) or set(payload) != {'read'} or not isinstance(payload['read'],bool):
        return jsonify(ok=False,error='Use a read boolean.'),400
    current = retrieveRecord('traveller_notifications',notification_id)
    if not current or current.get('travellerId') != g.uid:
        return jsonify(ok=False,error='Notification not found.'),404
    try:
        updateRecord('traveller_notifications',notification_id,{'read':payload['read'],
                     'readAt':datetime.now(timezone.utc).isoformat() if payload['read'] else None})
        return jsonify(ok=True)
    except Exception:
        return jsonify(ok=False,error='Notification could not be updated. Please retry.'),503
