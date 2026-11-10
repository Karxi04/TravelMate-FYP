"""Owner-scoped in-app events from persisted records; no scheduler or financial writes."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math

CATEGORIES = {'payment', 'arrangements_ready', 'upcoming_trip', 'packing', 'weather',
              'package_booking', 'arrangements_update', 'booking_attention'}
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


def canonical_payment_order(order, uid, lookup):
    """Link a financial projection only to a verified same-owner checkout order."""
    linked_id = order.get('checkoutOrderId') or order.get('orderId')
    linked = lookup(str(linked_id)) if linked_id and order.get('travellerId') == uid else None
    if not linked or linked.get('travellerId') != uid:
        return order
    return {**order, 'quoteType':linked.get('quoteType') or order.get('quoteType'),
            'checkoutOrderId':str(linked.get('id') or linked_id), 'orderReference': str(linked.get('orderReference') or linked.get('id') or linked_id),
            'packageSnapshot': linked.get('packageSnapshot') or order.get('packageSnapshot') or {},
            'paidAt': order.get('paidAt') or linked.get('paidAt')}


def payment_source_label(order, reference):
    title = str((order.get('packageSnapshot') or {}).get('title') or '')[:150]
    return (title + ' · ' if title else '') + 'Order ' + str(reference)


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
        return events[nid]
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
            event = add('payment', [oid,state], 'Payment status updated', f'Your recorded payment status is {state}.',
                {'screen':'payments','orderId':oid}, (order.get('paidAt') if state == 'paid' else None) or order.get('updatedAt'))
            event['sourceOrderId'] = oid
            event['paymentState'] = state
            event['paymentType'] = order.get('quoteType')
            event['paymentOrderId'] = str(order.get('checkoutOrderId') or order.get('id') or '')
            event['sourceLabel'] = payment_source_label(order,oid)
        record = order.get('fulfillmentRecord') or {}
        if not isinstance(record,dict):record={}
        trip_id = str(order.get('fulfilledTripId') or '')
        if state == 'paid' and order.get('fulfillmentStatus') == 'trip_ready' and record.get('status') == 'trip_ready' and record.get('confirmedBy') and record.get('confirmedAt') and trip_id in owned_trip_ids:
            ready = add('arrangements_ready', oid, 'Package arrangements ready',
                'The operator marked your purchased package arrangements ready. This is an operator attestation.',
                {'screen':'package_trip','tripId':trip_id,'orderId':oid}, record['confirmedAt'])
            ready['sourceOrderId'] = str(order.get('id') or '')
        if state == 'paid' and order.get('quoteType') == 'package':
            source_id = str(order.get('id') or '')
            trip = next((t for t in trips if str(t.get('id')) == trip_id and t.get('travellerId') == uid), None)
            linked = (trip and trip.get('checkoutOrderId') == source_id
                      and order.get('operatorId') and trip.get('operatorId') == order['operatorId'])
            target = {'screen':'package_trip','tripId':trip_id,'orderId':oid} if linked else {'screen':'payments','orderId':oid}
            def package_update(category, source, title, message, occurred):
                event = add(category,source,title,message,target,occurred)
                event['sourceOrderId'] = source_id
                return event
            if linked and active_trip(trip):
                package_update('package_booking', oid, 'Package trip created',
                    'Your paid package purchase has a saved trip. This does not confirm supplier reservations.', trip.get('createdAt'))
            if order.get('fulfillmentStatus') == 'partially_fulfilled' and record.get('status') == 'partially_fulfilled':
                services=record.get('services') or {}
                if not isinstance(services,dict):services={}
                for component,label in {'accommodation':'accommodation','transport':'transportation','guideActivities':'guide / activity'}.items():
                    service = services.get(component) or {}
                    if not isinstance(service,dict):continue
                    if (service.get('required') is True and service.get('status') == 'confirmed' and service.get('reference')
                            and service.get('confirmedAt') and service.get('confirmedBy') and service.get('provenance') == 'operator_attested'):
                        package_update('arrangements_update', [oid,component,service['confirmedAt']], 'Package arrangement updated',
                            f'The operator recorded {label} arrangements. This is an operator attestation; review the current booking details.', service['confirmedAt'])
            if (order.get('fulfillmentStatus') == 'fulfillment_declined' and record.get('status') == 'fulfillment_declined'
                    and record.get('declinedAt') and record.get('declinedBy')):
                package_update('booking_attention', [oid,record['declinedAt']], 'Package booking needs attention',
                    'The operator marked the package unable to fulfil. Review your booking. No refund is implied by this update.', record['declinedAt'])
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



def push_presentation(notification):
    """Generic category wording only; no account, itinerary or financial details on the lock screen."""
    title,body = {
        'payment':('Payment update','Your payment status changed. Open TravelMate to review it securely.'),
        'package_booking':('Package trip created','Your package purchase has a saved trip. Review its current arrangement status in TravelMate.'),
        'arrangements_update':('Arrangement update','Your operator recorded an arrangement update. Open TravelMate to review the current details.'),
        'arrangements_ready':('Operator readiness update','Your operator updated package readiness. Review the recorded status in TravelMate.'),
        'booking_attention':('Booking needs attention','A package booking needs your attention. Open TravelMate to review its current status.'),
        'upcoming_trip':('Upcoming trip','You have an upcoming trip. Open TravelMate to review your plans.'),
        'packing':('Packing reminder','Review your trip packing checklist in TravelMate.'),
        'weather':('Trip forecast advisory','A trip forecast advisory is available. Open TravelMate to review it.'),
    }.get(notification.get('category'),('Update','You have a TravelMate update. Open the app to view it securely.'))
    if notification.get('category') == 'payment' and notification.get('paymentState') == 'paid':
        title = 'Payment Successful'
        body = ('Your tourism package payment has been confirmed.' if notification.get('paymentType') == 'package'
                else 'Your payment has been confirmed.')
    return {'title':'TravelMate — '+title,'body':body}
