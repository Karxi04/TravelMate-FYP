"""Owner-scoped in-app events from persisted records; no scheduler or financial writes."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math

CATEGORIES = {'payment', 'arrangements_ready', 'upcoming_trip', 'packing', 'weather'}
MYT = timezone(timedelta(hours=8))


def event_id(uid, category, source):
    return hashlib.sha256(json.dumps([uid, category, source], separators=(',', ':')).encode()).hexdigest()


def trip_start(trip):
    try:
        value = str(trip.get('startDate') or '')
        start = date.fromisoformat(value) if len(value) == 10 else None
        end = date.fromisoformat(str(trip['endDate'])) if trip.get('endDate') else start
        return start if start and end >= start else None
    except ValueError:
        return None


def active_trip(trip):
    return not trip.get('deletedAt') and str(trip.get('status') or '').lower() not in {
        'cancelled', 'canceled', 'archived', 'deleted', 'payment_cancelled', 'payment_failed'} and str(
        trip.get('fulfillmentStatus') or '').lower() != 'fulfillment_declined'


def coordinates(trip):
    values = [trip.get('destinationCoordinates'), trip.get('gps_coordinates')]
    values += [a.get('gps_coordinates') or a.get('gpsCoordinates') for a in trip.get('activities', []) if isinstance(a, dict)]
    for value in values:
        if not isinstance(value, dict):
            continue
        try:
            lat, lon = float(value['latitude']), float(value['longitude'])
            if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
                return {'latitude':lat, 'longitude':lon}
        except (KeyError, TypeError, ValueError):
            continue
    return None


def derive_events(uid, orders, trips, checklists=None, forecasts=None, now=None):
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(MYT).date()
    events = {}
    owned_trip_ids = {str(t.get('id')) for t in trips if t.get('travellerId') == uid}
    def add(category, source, title, message, target, occurred_at=None):
        nid = event_id(uid, category, source)
        events[nid] = {'id':nid, 'travellerId':uid, 'category':category, 'sourceEventId':nid,
                       'title':title, 'message':message, 'target':target, 'createdAt':now.isoformat(),
                       'occurredAt':occurred_at, 'read':False}
        if category == 'weather': events[nid]['forecastDate'] = source[1]
    for order in orders:
        if order.get('travellerId') != uid or order.get('isSimulated') or order.get('bookingMode') == 'simulation':
            continue
        oid = str(order.get('orderReference') or order.get('checkoutOrderId') or order.get('orderId') or order.get('id') or '')
        if not oid:
            continue
        state = str(order.get('paymentStatus') or order.get('status') or '').lower()
        state = {'payment_failed':'failed','payment_cancelled':'cancelled','canceled':'cancelled','payment_expired':'expired',
                 'succeeded':'paid','successful':'paid','success':'paid','completed':'paid'}.get(state,state)
        terminal = {'expired':'expired','checkout_failed':'failed','payment_failed':'failed',
                    'cancelled':'cancelled','canceled':'cancelled'}.get(str(order.get('status') or '').lower())
        if state not in {'paid','failed','cancelled','expired','refunded'} and terminal:
            state = terminal
        if state in {'paid','failed','cancelled','expired','refunded'}:
            add('payment', [oid,state], 'Payment status updated', f'Your recorded payment status is {state}.',
                {'screen':'payments','orderId':oid}, (order.get('paidAt') if state == 'paid' else None) or order.get('updatedAt'))
        record = order.get('fulfillmentRecord') or {}
        trip_id = str(order.get('fulfilledTripId') or '')
        if state == 'paid' and order.get('fulfillmentStatus') == 'trip_ready' and record.get('status') == 'trip_ready' and record.get('confirmedBy') and record.get('confirmedAt') and trip_id in owned_trip_ids:
            add('arrangements_ready', oid, 'Package arrangements ready',
                'The operator marked your purchased package arrangements ready. This is an operator attestation.',
                {'screen':'package_trip','tripId':trip_id,'orderId':oid}, record['confirmedAt'])
    for trip in trips:
        if trip.get('travellerId') != uid or not active_trip(trip):
            continue
        start = trip_start(trip)
        tid = str(trip.get('id') or '')
        if not start or not tid:
            continue
        delta = (start - today).days
        title = str(trip.get('title') or trip.get('destinationArea') or 'Your trip')[:150]
        target = {'screen':'package_trip' if trip.get('packageTrip') or trip.get('tripType') == 'package' else 'trip','tripId':tid}
        if delta in {3,1}:
            add('upcoming_trip', [tid,start.isoformat(),delta], 'Upcoming trip',
                f'{title} starts in {delta} day(s), on {start.isoformat()}.', target)
            checklist = (checklists or {}).get(tid) or {}
            items = checklist.get('items')
            if checklist.get('travellerId') == uid and checklist.get('tripId') == tid and isinstance(items, list):
                active = [i for i in items if isinstance(i,dict) and i.get('applicable') is True and i.get('suppressed') is False and isinstance(i.get('isPacked'),bool)]
                packed = sum(i['isPacked'] for i in active)
                if active and packed < len(active):
                    add('packing', [tid,start.isoformat(),delta], 'Review your packing checklist',
                        f'{title}: {packed} / {len(active)} applicable items packed when this reminder was created.',
                        {'screen':'packing','tripId':tid})
        forecast = (forecasts or {}).get(tid) or {}
        daily = forecast.get('daily') or {}
        for index, day in enumerate(daily.get('time') or []):
            try:
                forecast_day = date.fromisoformat(str(day))
                end = date.fromisoformat(str(trip['endDate'])) if trip.get('endDate') else start
            except ValueError:
                continue
            if not 0 <= delta <= 6 or not start <= forecast_day <= end or forecast_day < today:
                continue
            def value(key):
                values = daily.get(key)
                return values[index] if isinstance(values,list) and index < len(values) else None
            code, probability = value('weather_code'), value('precipitation_probability_max')
            rainy = isinstance(probability,(int,float)) and not isinstance(probability,bool) and 80 <= probability <= 100
            concern = 'thunderstorm' if code in {95,96,99} else 'rain' if code in {63,65,67,81,82} or rainy else None
            if concern:
                add('weather', [tid,forecast_day.isoformat(),concern], 'Trip forecast advisory',
                    f'The Open-Meteo forecast for {forecast_day.isoformat()} indicates possible {concern}. Review your plans. This is a forecast advisory, not an official severe-weather alert.', target)
    for event in events.values():
        tid = event['target'].get('tripId')
        source_trip = next((t for t in trips if str(t.get('id')) == tid),None)
        if source_trip: event['tripStartDate'] = source_trip.get('startDate')
    return list(events.values())
