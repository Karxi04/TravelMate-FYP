"""Evaluate due events when the authenticated Traveller opens/refreshes the app."""
from datetime import datetime, timezone
from flask import Blueprint, g, jsonify, request
from auth_utils import auth_required
from sequence_contract.firebase_firestore import retrieveRecord, claimRecord, storeRecord, updateRecord
from services.traveller_notifications import (
    TRIP_REMINDER_CATEGORIES, MYT, active_trip, canonical_payment_order, coordinates,
    derive_events, event_id, inbox_presentation, matches_trip_reminder, push_presentation, trip_start,
)
from services.packing_checklist_service import checklist_id
from services.open_meteo_service import retrieveSevenDayForecast
from services.notification_delivery import enabled, register_device, queue_notification

bp = Blueprint('traveller_notifications', __name__, url_prefix='/api/traveller/notifications')


@bp.get('')
@auth_required(['traveller'])
def notifications():
    try:
        result = reconcile(g.uid)
        return jsonify(result)
    except Exception:
        return jsonify(ok=False,error='Notifications could not be refreshed. Please try again.'),503


def reconcile(uid):
    now = datetime.now(timezone.utc)
    try:
        orders = retrieveRecord('checkout_orders', filters=[('travellerId','==',uid)]) or []
        checkout_by_id = {str(order.get('id')):order for order in orders if order.get('travellerId') == uid}
        orders += retrieveRecord('payment_records', filters=[('travellerId','==',uid)]) or []
        orders = [canonical_payment_order(order,uid,checkout_by_id.get) for order in orders]
        checkout_by_reference = {str(order.get('orderReference') or oid): order
                                 for oid, order in checkout_by_id.items()}
        trips = retrieveRecord('itineraries', filters=[('travellerId','==',uid)]) or []
        checklists, forecasts = {}, {}
        upcoming = [t for t in trips if t.get('travellerId') == uid and active_trip(t) and trip_start(t)
                    and 0 <= (trip_start(t) - now.astimezone(MYT).date()).days <= 6]
        upcoming.sort(key=lambda t:(t['startDate'],str(t.get('id'))))
        for trip in upcoming:
            tid = str(trip['id'])
            if (trip_start(trip)-now.astimezone(MYT).date()).days in {1,3}:
                checklists[tid] = retrieveRecord('packing_checklists', checklist_id(uid,tid)) or {}
        weather_unavailable = 0
        for trip in upcoming[:3]:
            coords = coordinates(trip)
            if not coords:
                weather_unavailable += 1
                continue
            cache_id = event_id(uid,'weather_cache',[trip['id'],coords,int(now.timestamp())//21600])
            cached = retrieveRecord('notification_weather_cache', cache_id)
            if not cached:
                cached, created = claimRecord('notification_weather_cache',cache_id,{'travellerId':uid,'checkedAt':now.isoformat(),'forecast':{}})
                if created:
                    try:
                        forecast = retrieveSevenDayForecast(coords)
                        if not isinstance(forecast,dict) or not isinstance(forecast.get('daily'),dict):
                            raise ValueError('Forecast unavailable')
                        cached = {'travellerId':uid,'checkedAt':now.isoformat(),'forecast':forecast}
                        storeRecord('notification_weather_cache',cached,cache_id)
                    except Exception:
                        weather_unavailable += 1
            if cached.get('travellerId') == uid:
                forecasts[trip['id']] = cached.get('forecast') or {}
        for event in derive_events(uid,orders,trips,checklists,forecasts,now):
            saved, created = claimRecord('traveller_notifications',event['id'],event)
            queue_notification(saved,created)
        items = retrieveRecord('traveller_notifications',filters=[('travellerId','==',uid)]) or []
        trips_by_id = {str(trip['id']): trip for trip in trips if trip.get('id')}
        items = [dict(item) for item in items if item.get('travellerId') == uid and (
            item.get('category') not in TRIP_REMINDER_CATEGORIES or matches_trip_reminder(
                item, trips_by_id.get(str((item.get('target') or {}).get('tripId') or '')),
            )
        )]
        for item in items:
            reference = str((item.get('target') or {}).get('orderId') or '')
            inbox_presentation(item, checkout_by_reference.get(reference), now=now)
        items.sort(key=lambda item:str(item.get('createdAt') or ''), reverse=True)
        return dict(ok=True,items=items,unreadCount=sum(not item.get('read') for item in items),
                       evaluation='on_open_or_refresh_and_configured_worker',weatherUnavailable=weather_unavailable)
    except Exception:
        raise


@bp.get('/<notification_id>')
@auth_required(['traveller'])
def notification_detail(notification_id):
    item = retrieveRecord('traveller_notifications',notification_id)
    if not item or item.get('travellerId') != g.uid:
        return jsonify(ok=False,error='Notification not found.'),404
    if item.get('category') in TRIP_REMINDER_CATEGORIES:
        trip_id = (item.get('target') or {}).get('tripId')
        trip = retrieveRecord('itineraries', trip_id) if trip_id else None
        if not matches_trip_reminder(item, trip):
            return jsonify(ok=False,error='Notification not found.'),404
    return jsonify(ok=True,item=item,presentation=push_presentation(item))


@bp.post('/devices')
@auth_required(['traveller'])
def device_registration():
    return _device(False)


@bp.delete('/devices')
@bp.post('/devices/unregister')
@auth_required(['traveller'])
def device_unregistration():
    return _device(True)


def _device(disable):
    if not enabled() and not disable:
        return jsonify(ok=False,code='push_disabled',error='Android push is not configured on this backend.'),503
    try:
        key = register_device(g.uid,request.get_json(silent=True),disable)
        return jsonify(ok=True,deviceId=key)
    except ValueError as error:
        return jsonify(ok=False,error=str(error)),400
    except PermissionError:
        return jsonify(ok=False,error='Device registration is unavailable.'),409
    except Exception:
        return jsonify(ok=False,error='Device registration could not be saved.'),503


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
