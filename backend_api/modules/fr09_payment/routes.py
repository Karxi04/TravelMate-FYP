import math
import os
import re
import uuid
from copy import deepcopy
from datetime import date, timedelta
from html import escape
from urllib.parse import urlparse

from flask import Blueprint, request, jsonify, g, current_app, Response

from auth_utils import auth_required
from utils import utc_now_iso
from services.stripe_service import (
    createPaymentSession,
    createCheckoutSession,
    normalizePaymentStatus,
    processPaymentAttempt,
    retrieveCheckoutSession,
    returnPaymentStatus,
    constructStripeWebhookEvent,
)
from services.transaction_reliability import (
    is_ambiguous_provider_error,
    normalize_attempt_id,
    operation_document_id,
    provider_idempotency_key,
)
from services.package_checkout_contract import (
    package_amount_minor_units,
    package_trip_compatible,
)
from sequence_contract.validators import validatePaymentInput
from sequence_contract.firebase_firestore import claimRecord, retrieveRecord, updateRecord

bp = Blueprint('fr09_payments', __name__, url_prefix='/api/fr9')
ORDER_COLLECTION = 'checkout_orders'
PACKAGE_ATTEMPT_COLLECTION = 'package_checkout_attempts'
PACKAGE_FULFILLMENT_COLLECTION = 'package_fulfillments'


def _legacy_payment_mutations_enabled():
    """Keep legacy mutations available only to the deterministic test harness."""
    return current_app.config.get('TESTING', False) and os.getenv(
        'TRAVELMATE_TESTING', '').strip().lower() in {'1', 'true', 'yes'}


def _legacy_payment_route_blocked():
    if _legacy_payment_mutations_enabled():
        return None
    return jsonify({
        'ok': False,
        'error': 'Use a validated Checkout order for payment.',
    }), 409


def _order_document_id(attempt_id):
    return operation_document_id('checkout_order', g.uid, attempt_id)


def _finite_amount(value):
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if math.isfinite(amount) and amount > 0 else None


def _safe_quote_snapshot(quote):
    allowed = {
        'quoteId', 'offerId', 'hotelId', 'name', 'roomName', 'boardName',
        'price', 'currency', 'priceBasis', 'priceScope',
        'priceSemanticsStatus', 'taxesAndFeesStatus', 'cancellation',
        'refundable', 'source', 'sourceLabel', 'quoteCompleteness',
        'roundTripComplete', 'travellerCount', 'passengerComposition',
        'passengerPriceBasis', 'outboundSegments', 'returnSegments',
        'tripType', 'priceStatus', 'currencyStatus',
    }
    return {key: quote.get(key) for key in allowed if key in quote}


def _hotel_checkout_quote(payload):
    quote_id = str(payload.get('quoteId') or '').strip()
    offer_id = str(payload.get('offerId') or '').strip()
    if not quote_id or not offer_id:
        raise ValueError('A stored hotel quote and offer are required for Checkout.')
    record = retrieveRecord('hotel_offer_quotes', f'{g.uid}_{quote_id}')
    if not record or record.get('travellerId') != g.uid:
        raise ValueError('The hotel quote was not found or is not owned by this traveller.')
    offer = dict(record.get('offer') or {})
    if str(offer.get('offerId') or '') != offer_id:
        raise ValueError('This hotel quote is bound to a different offer.')
    amount = _finite_amount(offer.get('price'))
    currency = str(offer.get('currency') or '').upper()
    if offer.get('priceStatus') != 'available' or amount is None:
        raise ValueError('This hotel quote has no authoritative payable amount.')
    if currency != 'MYR' or offer.get('currencyStatus') != 'known':
        raise ValueError('This hotel quote has no validated MYR currency.')
    if offer.get('priceBasis') != 'stay_total':
        raise ValueError('This hotel quote does not prove a total for the requested stay and rooms.')
    if offer.get('taxesAndFeesStatus') not in {'included', 'excluded', 'mixed'}:
        raise ValueError('This hotel quote does not disclose its taxes and fees.')
    snapshot = _safe_quote_snapshot({**offer, 'quoteId': quote_id})
    return {
        'quoteType': 'hotel', 'quoteId': quote_id, 'offerId': offer_id,
        'amount': amount, 'currency': currency, 'quoteSnapshot': snapshot,
        'amountBasis': 'provider_offer_total_includes_base_and_included_taxes_fees',
        'sandbox': offer.get('rateProvenance') == 'sandbox_provider_quote',
    }


def _flight_checkout_quote(payload):
    search_id = str(payload.get('searchId') or payload.get('quoteId') or '').strip()
    option_id = str(payload.get('optionId') or '').strip()
    if not search_id or not option_id:
        raise ValueError('A completed flight quote and option are required for Checkout.')
    record = retrieveRecord('flight_quotes', f'{g.uid}_{search_id}')
    if not record or record.get('travellerId') != g.uid:
        raise ValueError('The flight quote was not found or is not owned by this traveller.')
    criteria = dict(record.get('criteria') or {})
    option = next((dict(item) for item in record.get('items', [])
                   if isinstance(item, dict) and str(item.get('optionId') or item.get('id') or '') == option_id), None)
    if not option:
        raise ValueError('The selected flight option is not part of the owned quote.')
    if record.get('source') == 'sample_fixture':
        raise ValueError('Sample flight fixtures cannot enter Checkout.')
    amount = _finite_amount(option.get('price'))
    currency = str(option.get('currency') or '').upper()
    travellers = int(criteria.get('traveller_count') or 0)
    composition = option.get('passengerComposition') or {}
    if amount is None or currency != 'MYR' or option.get('currencyStatus') != 'known':
        raise ValueError('This flight quote has no validated MYR payable amount.')
    if option.get('quoteCompleteness') != 'complete' or option.get('budgetEligible') is False:
        raise ValueError('Complete flight quote selection is required before Checkout.')
    if criteria.get('return_date') and not option.get('roundTripComplete'):
        raise ValueError('A complete round-trip quote is required before Checkout.')
    if option.get('priceScope') != 'provider_ticket_price' or option.get('priceSemanticsStatus') != 'provider_response_requested_adults':
        raise ValueError('This flight quote does not prove an adult-party ticket total.')
    if not travellers or option.get('travellerCount') != travellers or composition.get('adults') != travellers:
        raise ValueError('This flight quote does not match the requested adult party.')
    if criteria.get('return_date') and not str(option.get('priceBasis') or '').startswith('provider_round_trip_'):
        raise ValueError('This round-trip quote has no verified combined ticket total.')
    snapshot = _safe_quote_snapshot({**option, 'quoteId': search_id, 'offerId': option_id})
    return {
        'quoteType': 'flight', 'quoteId': search_id, 'optionId': option_id,
        'amount': amount, 'currency': currency, 'quoteSnapshot': snapshot,
        'amountBasis': 'provider_ticket_price_requested_adults', 'sandbox': False,
    }


def _resolve_checkout_quote(payload):
    quote_type = str(payload.get('quoteType') or '').strip().lower()
    if quote_type == 'hotel':
        return _hotel_checkout_quote(payload)
    if quote_type == 'flight':
        return _flight_checkout_quote(payload)
    raise ValueError('quoteType must be hotel or flight.')


def _safe_order(record):
    return {
        key: value for key, value in record.items()
        if key not in {'providerIdempotencyKey'}
    }


def _configured_checkout_url(name, fallback):
    value = os.getenv(name, fallback).strip()
    parsed = urlparse(value)
    if parsed.scheme not in {'https', 'http'} or not parsed.netloc:
        raise RuntimeError(f'{name} is not configured with an absolute URL.')
    if parsed.hostname and parsed.hostname.lower() in {'example.com', 'www.example.com'}:
        raise RuntimeError(f'{name} must be an explicit TravelMate return URL.')
    return value


def _stripe_value(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _order_status_from_session(session):
    status = str(_stripe_value(session, 'status', '') or '').lower()
    payment_status = str(_stripe_value(session, 'payment_status', '') or '').lower()
    if status == 'expired':
        return 'expired', payment_status
    if status == 'complete' and payment_status in {'paid', 'no_payment_required'}:
        return 'paid', payment_status
    if status == 'complete':
        return 'payment_pending', payment_status
    return 'checkout_open', payment_status


def _apply_checkout_session(record, session):
    if str(record.get('status') or '').lower() == 'paid':
        return {
            'status': 'paid',
            'paymentStatus': 'paid',
            'stripePaymentIntentId': record.get('stripePaymentIntentId'),
            'reconciliationRequired': False,
            'updatedAt': utc_now_iso(),
        }
    status, payment_status = _order_status_from_session(session)
    amount_total = _stripe_value(session, 'amount_total')
    currency = str(_stripe_value(session, 'currency', '') or '').upper()
    expected_cents = int(record.get('amountMinor') or round(float(record.get('amount') or 0) * 100))
    if amount_total is not None and int(amount_total) != expected_cents:
        status = 'payment_mismatch'
    if currency and currency != str(record.get('currency') or '').upper():
        status = 'payment_mismatch'
    payment_intent = _stripe_value(session, 'payment_intent')
    return {
        'status': status,
        'paymentStatus': payment_status or None,
        'stripePaymentIntentId': str(payment_intent) if payment_intent else None,
        'reconciliationRequired': status in {'checkout_open', 'payment_pending', 'payment_mismatch'},
        'updatedAt': utc_now_iso(),
    }


def _package_attempt_for_checkout(attempt_id):
    attempt = retrieveRecord(PACKAGE_ATTEMPT_COLLECTION, attempt_id)
    if not attempt or attempt.get('travellerId') != g.uid:
        raise PermissionError('Package checkout attempt was not found.')
    snapshot = attempt.get('packageSnapshot') or {}
    package_amount_minor_units(snapshot)
    if (str(attempt.get('checkoutStatus') or '').lower() in {'paid', 'cancelled', 'expired'} or
            str(attempt.get('paymentStatus') or '').lower() in {'paid', 'succeeded'}):
        raise ValueError('This package checkout attempt is no longer payable.')
    return attempt, snapshot


def _package_order_document_id(attempt_id):
    return operation_document_id('package_checkout_order', g.uid, attempt_id)


def _legacy_package_fulfillment(order, attempt):
    """Keep already-created quantity-one attempts on their original path."""
    attempt_id = str(order.get('packageAttemptId') or '')
    trip_id = str(attempt.get('intendedTripId') or '')
    trip = retrieveRecord('itineraries', trip_id) if trip_id else None
    if not trip:
        return {'fulfillmentStatus': 'fulfillment_pending', 'fulfillmentRetryRequired': True,
                'fulfillmentError': 'No valid Trip is currently bound to this package payment.'}
    snapshot = attempt.get('packageSnapshot') or {}
    if trip.get('travellerId') != order.get('travellerId') or not package_trip_compatible(snapshot, trip):
        return {'fulfillmentStatus': 'fulfillment_failed', 'fulfillmentRetryRequired': True,
                'fulfillmentError': 'The current Trip cannot safely receive this package.'}
    fulfillment_id = operation_document_id('package_fulfillment', order['travellerId'], attempt_id)
    claimed, created = claimRecord(PACKAGE_FULFILLMENT_COLLECTION, fulfillment_id, {
        'id': fulfillment_id, 'travellerId': order['travellerId'], 'checkoutOrderId': order['id'],
        'packageAttemptId': attempt_id, 'tripId': trip_id, 'status': 'fulfillment_pending',
        'createdAt': utc_now_iso(), 'updatedAt': utc_now_iso(),
    })
    purchases = list(trip.get('purchasedPackages') or [])
    attached = next((item for item in purchases if isinstance(item, dict) and
                     item.get('packageAttemptId') == attempt_id), None)
    if not attached:
        association = {
            'packageAttemptId': attempt_id, 'checkoutOrderId': order['id'],
            'packageId': snapshot.get('packageId'), 'operatorId': snapshot.get('operatorId'),
            'packageSnapshot': snapshot, 'fulfilledAt': utc_now_iso(),
        }
        purchases.append(association)
        updateRecord('itineraries', trip_id, {'purchasedPackages': purchases, 'updatedAt': utc_now_iso()})
    if created or claimed.get('status') != 'fulfilled':
        updateRecord(PACKAGE_FULFILLMENT_COLLECTION, fulfillment_id, {
            'status': 'fulfilled', 'updatedAt': utc_now_iso(),
        })
    return {'fulfillmentStatus': 'fulfilled', 'fulfillmentRetryRequired': False,
            'fulfilledTripId': trip_id}


def _package_trip_schedule(snapshot):
    start_text = str(snapshot.get('selectedDepartureDate') or '')
    start = date.fromisoformat(start_text) if start_text else None
    schedule, activities = [], []
    for index, raw_day in enumerate(snapshot.get('itineraryDays') or []):
        if not isinstance(raw_day, dict):
            continue
        day_number = index + 1
        day_items = []
        raw_acts = raw_day.get('activities') or []
        if isinstance(raw_acts, str):
            raw_acts = [x.strip() for x in raw_acts.replace('\r', '').split('\n') if x.strip()]
        for item_index, raw_activity in enumerate(raw_acts):
            if isinstance(raw_activity, dict):
                activity = deepcopy(raw_activity)
                name = activity.get('title') or activity.get('name') or activity.get('activityName') or 'Package activity'
                time_slot = activity.get('scheduledStartTime') or activity.get('timeSlot') or activity.get('time')
                time_match = re.match(r'^(\d{1,2}:\d{2}(?:\s*(?:AM|PM|am|pm))?)\s*[-:–—]\s*(.+)$', str(name))
                if time_match:
                    if not time_slot:
                        time_slot = time_match.group(1).strip()
                    name = time_match.group(2).strip()
                activity['activityName'] = name
                if time_slot:
                    activity['timeSlot'] = str(time_slot).strip()
                    activity['scheduledStartTime'] = str(time_slot).strip()
            else:
                act_text = str(raw_activity).strip()
                time_match = re.match(r'^(\d{1,2}:\d{2}(?:\s*(?:AM|PM|am|pm))?)\s*[-:–—]\s*(.+)$', act_text)
                if time_match:
                    activity = {
                        'activityName': time_match.group(2).strip(),
                        'timeSlot': time_match.group(1).strip(),
                        'scheduledStartTime': time_match.group(1).strip(),
                        'category': 'Package itinerary',
                    }
                else:
                    activity = {
                        'activityName': act_text,
                        'category': 'Package itinerary',
                    }
            activity.setdefault('activityId', f'package_{day_number}_{item_index + 1}')
            activity.update({'dayNo': day_number, 'source': 'purchased_package_snapshot'})
            day_items.append(activity)
            activities.append(activity)
        raw_meals = raw_day.get('meals') or []
        if isinstance(raw_meals, str):
            raw_meals = [x.strip() for x in raw_meals.replace('\r', '').split('\n') if x.strip()]
        schedule.append({
            'dayNo': day_number,
            'dayDate': (start + timedelta(days=index)).isoformat() if start else '',
            'title': raw_day.get('title'), 'description': raw_day.get('description'),
            'activities': day_items, 'meals': deepcopy(raw_meals),
            'accommodation': raw_day.get('accommodation'),
            'transportNotes': raw_day.get('transportNotes'),
            'planningBlocks': [], 'estimatedCost': 0,
            'weather': {'source': 'unavailable'},
        })
    return schedule, activities


def _independent_package_fulfillment(order, attempt):
    attempt_id = str(order.get('packageAttemptId') or '')
    snapshot = attempt.get('packageSnapshot') or {}
    traveller_id = str(order.get('travellerId') or '')
    fulfillment_id = operation_document_id('package_fulfillment', traveller_id, attempt_id)
    trip_id = operation_document_id('package_trip', traveller_id, attempt_id)
    now = utc_now_iso()
    claimed, _created = claimRecord(PACKAGE_FULFILLMENT_COLLECTION, fulfillment_id, {
        'id': fulfillment_id, 'travellerId': traveller_id, 'checkoutOrderId': order['id'],
        'packageAttemptId': attempt_id, 'tripId': trip_id, 'status': 'fulfillment_pending',
        'createdAt': now, 'updatedAt': now,
    })
    if (claimed.get('checkoutOrderId') != order.get('id') or claimed.get('tripId') != trip_id):
        return {'fulfillmentStatus': 'fulfillment_failed', 'fulfillmentRetryRequired': True,
                'fulfillmentError': 'The package fulfillment claim is inconsistent.'}
    schedule, activities = _package_trip_schedule(snapshot)
    start_text = str(snapshot.get('selectedDepartureDate') or '')
    duration = int(snapshot.get('durationDays') or len(schedule) or 1)
    start = date.fromisoformat(start_text) if start_text else None
    end_text = (start + timedelta(days=duration - 1)).isoformat() if start else ''
    trip_record = {
        'id': trip_id, 'travellerId': traveller_id,
        'title': snapshot.get('title') or 'Purchased travel package',
        'destinationArea': snapshot.get('destination') or '',
        'startDate': start_text, 'endDate': end_text, 'tripDays': max(1, duration),
        'travellerCount': snapshot.get('groupSize') or 1,
        'participants': deepcopy(snapshot.get('participants') or {'adults': 1, 'children': 0, 'total': 1}),
        'tripType': 'package', 'packageTrip': True, 'status': 'planned',
        'activities': activities, 'dailySchedule': schedule,
        'packageSnapshot': deepcopy(snapshot), 'packageId': snapshot.get('packageId'),
        'operatorId': snapshot.get('operatorId'), 'packageAttemptId': attempt_id,
        'checkoutOrderId': order.get('id'), 'paidTotal': order.get('amount'),
        'paidTotalMinor': order.get('amountMinor'), 'currency': order.get('currency'),
        'supplierReservationStatus': 'not_created',
        'budgetLimit': order.get('amount'),
        'budgetEstimate': {
            'total': order.get('amount'), 'currency': order.get('currency'),
            'source': 'verified_package_payment',
        },
        'createdAt': now, 'updatedAt': now,
    }
    trip, _trip_created = claimRecord('itineraries', trip_id, trip_record)
    if (trip.get('travellerId') != traveller_id or trip.get('checkoutOrderId') != order.get('id')):
        return {'fulfillmentStatus': 'fulfillment_failed', 'fulfillmentRetryRequired': True,
                'fulfillmentError': 'The package Trip claim is inconsistent.'}
    updateRecord(PACKAGE_FULFILLMENT_COLLECTION, fulfillment_id, {
        'status': 'fulfilled', 'updatedAt': utc_now_iso(),
    })
    return {'fulfillmentStatus': 'fulfilled', 'fulfillmentRetryRequired': False,
            'fulfilledTripId': trip_id}


def _fulfill_package_order(order):
    """Fulfill verified payment idempotently; never roll payment back here."""
    attempt_id = str(order.get('packageAttemptId') or '')
    attempt = retrieveRecord(PACKAGE_ATTEMPT_COLLECTION, attempt_id)
    if not attempt or attempt.get('travellerId') != order.get('travellerId'):
        return {'fulfillmentStatus': 'fulfillment_failed', 'fulfillmentRetryRequired': True,
                'fulfillmentError': 'The package purchase intent is unavailable.'}
    if attempt.get('fulfillmentMode') == 'independent_package_trip':
        try:
            return _independent_package_fulfillment(order, attempt)
        except Exception:
            return {'fulfillmentStatus': 'fulfillment_pending', 'fulfillmentRetryRequired': True,
                    'fulfillmentError': 'The paid Package Trip is awaiting recovery.'}
    return _legacy_package_fulfillment(order, attempt)


def _apply_package_payment(order, session):
    patch = _apply_checkout_session(order, session)
    if patch['status'] != 'paid':
        return patch
    fulfillment = _fulfill_package_order(order)
    updateRecord(PACKAGE_ATTEMPT_COLLECTION, order['packageAttemptId'], {
        'checkoutStatus': 'checkout_complete', 'paymentStatus': 'paid',
        **fulfillment, 'updatedAt': utc_now_iso(),
    })
    return {**patch, **fulfillment}


@bp.post('/package-checkout-attempts/<attempt_id>/checkout/session')
@auth_required(['traveller'])
def create_package_checkout_session(attempt_id):
    try:
        attempt, snapshot = _package_attempt_for_checkout(attempt_id)
    except PermissionError:
        return jsonify({'ok': False, 'error': 'Package checkout attempt was not found.'}), 404
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 409
    minor_units = package_amount_minor_units(snapshot)
    order_id = _package_order_document_id(attempt_id)
    now = utc_now_iso()
    record = {
        'id': order_id, 'travellerId': g.uid, 'orderAttemptId': attempt_id,
        'packageAttemptId': attempt_id, 'quoteType': 'package',
        'packageId': snapshot.get('packageId'), 'operatorId': snapshot.get('operatorId'),
        'packageSnapshot': snapshot, 'amount': minor_units / 100,
        'amountMinor': minor_units, 'currency': 'MYR', 'taxIncluded': snapshot.get('taxIncluded'),
        'taxNotes': snapshot.get('taxNotes'), 'status': 'checkout_pending',
        'participants': snapshot.get('participants'), 'groupSize': snapshot.get('groupSize'),
        'departureDate': snapshot.get('selectedDepartureDate'),
        'fulfillmentMode': attempt.get('fulfillmentMode'),
        'paymentStatus': 'unpaid', 'fulfillmentStatus': 'fulfillment_pending',
        'provider': 'stripe_checkout_test',
        'providerIdempotencyKey': provider_idempotency_key('package_checkout', g.uid, attempt_id, 'session'),
        'createdAt': now, 'updatedAt': now,
    }
    try:
        claimed, created = claimRecord(ORDER_COLLECTION, order_id, record)
    except Exception:
        return jsonify({'ok': False, 'error': 'Order storage is unavailable. Try again later.'}), 503
    if claimed.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'This order is not owned by the current traveller.'}), 403
    if claimed.get('packageAttemptId') != attempt_id or str(claimed.get('amountMinor')) != str(minor_units):
        return jsonify({'ok': False, 'error': 'Package checkout attempt is already bound to another order.'}), 409
    if str(claimed.get('status') or '').lower() == 'paid':
        return jsonify({'ok': False, 'error': 'This package Checkout order has already been paid.'}), 409
    if claimed.get('checkoutSessionId') and claimed.get('checkoutUrl'):
        return jsonify({'ok': True, 'order': _safe_order(claimed), 'reused': True})
    try:
        session = createCheckoutSession(
            snapshot['price'], 'MYR', g.uid, order_id,
            _configured_checkout_url('STRIPE_CHECKOUT_SUCCESS_URL',
                'http://127.0.0.1:5000/api/fr9/checkout/return/success?session_id={CHECKOUT_SESSION_ID}'),
            _configured_checkout_url('STRIPE_CHECKOUT_CANCEL_URL',
                'http://127.0.0.1:5000/api/fr9/checkout/return/cancel?session_id={CHECKOUT_SESSION_ID}'),
            metadata={'packageAttemptId': attempt_id, 'quoteType': 'package'},
            idempotency_key=claimed['providerIdempotencyKey'],
            product_name=f"TravelMate package test order: {snapshot.get('title') or snapshot.get('packageId')}",
        )
        session_id, checkout_url = str(_stripe_value(session, 'id', '') or ''), str(_stripe_value(session, 'url', '') or '')
        if not session_id or not checkout_url:
            raise RuntimeError('Stripe did not return a Checkout URL.')
        patch = {'checkoutSessionId': session_id, 'checkoutUrl': checkout_url,
                 'status': 'checkout_open', 'updatedAt': utc_now_iso()}
        updated = updateRecord(ORDER_COLLECTION, order_id, patch) or {**claimed, **patch}
        updateRecord(PACKAGE_ATTEMPT_COLLECTION, attempt_id, {
            'checkoutStatus': 'checkout_open', 'checkoutOrderId': order_id,
            'updatedAt': utc_now_iso(),
        })
        return jsonify({'ok': True, 'order': _safe_order(updated), 'reused': not created})
    except Exception as exc:
        if is_ambiguous_provider_error(exc):
            updateRecord(ORDER_COLLECTION, order_id, {'reconciliationRequired': True, 'updatedAt': utc_now_iso()})
            return jsonify({'ok': True, 'order': _safe_order(claimed), 'reconciliationRequired': True}), 202
        updateRecord(ORDER_COLLECTION, order_id, {'status': 'checkout_failed',
            'failureReason': 'Stripe Checkout could not be created.', 'updatedAt': utc_now_iso()})
        return jsonify({'ok': False, 'error': 'Stripe Checkout is unavailable. Configure Stripe test mode and try again.'}), 502


@bp.post('/checkout/session')
@auth_required(['traveller'])
def create_checkout_session():
    payload = request.get_json(silent=True) or {}
    try:
        attempt_id = normalize_attempt_id(
            payload.get('orderAttemptId') or payload.get('paymentAttemptId'),
            'orderAttemptId',
        )
        quote = _resolve_checkout_quote(payload)
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 409
    order_id = _order_document_id(attempt_id)
    now = utc_now_iso()
    record = {
        'id': order_id,
        'travellerId': g.uid,
        'orderAttemptId': attempt_id,
        **quote,
        'status': 'checkout_pending',
        'paymentStatus': 'unpaid',
        'provider': 'stripe_checkout_test',
        'providerIdempotencyKey': provider_idempotency_key(
            'checkout', g.uid, attempt_id, 'session'
        ),
        'createdAt': now,
        'updatedAt': now,
    }
    try:
        claimed, created = claimRecord(ORDER_COLLECTION, order_id, record)
    except Exception:
        return jsonify({'ok': False, 'error': 'Order storage is unavailable. Try again later.'}), 503
    if claimed.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'This order is not owned by the current traveller.'}), 403
    if str(claimed.get('status') or '').lower() == 'paid':
        return jsonify({'ok': False, 'error': 'This Checkout order has already been paid.'}), 409
    for key in ('quoteType', 'quoteId', 'offerId', 'optionId', 'amount', 'currency'):
        if key in record and str(claimed.get(key)) != str(record.get(key)):
            return jsonify({'ok': False, 'error': 'Order attempt is already bound to another quote.'}), 409
    if claimed.get('checkoutSessionId') and claimed.get('checkoutUrl'):
        return jsonify({'ok': True, 'order': _safe_order(claimed), 'reused': True})
    try:
        session = createCheckoutSession(
            quote['amount'], quote['currency'], g.uid, order_id,
            _configured_checkout_url(
                'STRIPE_CHECKOUT_SUCCESS_URL',
                'http://127.0.0.1:5000/api/fr9/checkout/return/success?session_id={CHECKOUT_SESSION_ID}',
            ),
            _configured_checkout_url(
                'STRIPE_CHECKOUT_CANCEL_URL',
                'http://127.0.0.1:5000/api/fr9/checkout/return/cancel?session_id={CHECKOUT_SESSION_ID}',
            ),
            metadata={
                'orderAttemptId': attempt_id,
                'quoteType': quote['quoteType'],
                'quoteId': quote['quoteId'],
            },
            idempotency_key=claimed['providerIdempotencyKey'],
            product_name=f"TravelMate {quote['quoteType']} test order",
        )
        session_id = str(_stripe_value(session, 'id', '') or '')
        checkout_url = str(_stripe_value(session, 'url', '') or '')
        if not session_id or not checkout_url:
            raise RuntimeError('Stripe did not return a Checkout URL.')
        updated = updateRecord(ORDER_COLLECTION, order_id, {
            'checkoutSessionId': session_id,
            'checkoutUrl': checkout_url,
            'status': 'checkout_open',
            'updatedAt': utc_now_iso(),
        }) or {**claimed, 'checkoutSessionId': session_id, 'checkoutUrl': checkout_url, 'status': 'checkout_open'}
        return jsonify({'ok': True, 'order': _safe_order(updated), 'reused': not created})
    except Exception as exc:
        if is_ambiguous_provider_error(exc):
            pending = updateRecord(ORDER_COLLECTION, order_id, {
                'status': 'checkout_pending',
                'reconciliationRequired': True,
                'updatedAt': utc_now_iso(),
            }) or {**claimed, 'status': 'checkout_pending', 'reconciliationRequired': True}
            return jsonify({'ok': True, 'order': _safe_order(pending), 'reconciliationRequired': True}), 202
        updateRecord(ORDER_COLLECTION, order_id, {
            'status': 'checkout_failed',
            'failureReason': 'Stripe Checkout could not be created.',
            'updatedAt': utc_now_iso(),
        })
        return jsonify({'ok': False, 'error': 'Stripe Checkout is unavailable. Configure Stripe test mode and try again.'}), 502


@bp.get('/checkout/return/<outcome>')
def checkout_return(outcome):
    """Show a generic server-verified return state; details stay in owned history."""
    if outcome not in {'success', 'cancel'}:
        return Response('TravelMate Checkout return is invalid.', status=404, mimetype='text/plain')
    session_id = str(request.args.get('session_id') or '').strip()
    if not session_id:
        return Response(
            'TravelMate could not verify this Checkout session. Open the app and check Orders.',
            status=400, mimetype='text/plain',
        )
    try:
        session = retrieveCheckoutSession(session_id)
        metadata = _stripe_value(session, 'metadata', {}) or {}
        order_id = str(metadata.get('orderId') or '').strip()
        record = retrieveRecord(ORDER_COLLECTION, order_id)
        if not order_id or not record or record.get('checkoutSessionId') != session_id:
            raise ValueError('Checkout session is not bound to a TravelMate order.')
        patch = (_apply_package_payment(record, session)
                 if record.get('quoteType') == 'package'
                 else _apply_checkout_session(record, session))
        updated = updateRecord(ORDER_COLLECTION, order_id, patch) or {**record, **patch}
        status = str(updated.get('status') or '').lower()
        if status == 'paid':
            heading = 'Payment verified'
            message = 'Stripe confirmed this test payment. Open TravelMate Orders to view it.'
        elif status in {'checkout_open', 'payment_pending'}:
            heading = 'Payment pending verification'
            message = 'TravelMate has not received a final payment confirmation yet. Open Orders to retry verification.'
        else:
            heading = 'Payment not completed'
            message = 'No successful payment was confirmed. Open TravelMate Orders to review the order.'
        html = (
            '<!doctype html><meta charset="utf-8"><title>TravelMate Checkout</title>'
            f'<h1>{escape(heading)}</h1><p>{escape(message)}</p>'
            '<p>You can close this page and return to the TravelMate app.</p>'
        )
        return Response(html, status=200, mimetype='text/html')
    except Exception:
        return Response(
            'TravelMate could not verify this Checkout session. Open the app and check Orders.',
            status=502, mimetype='text/plain',
        )


@bp.get('/orders')
@auth_required(['traveller'])
def list_orders():
    items = retrieveRecord(ORDER_COLLECTION, filters=[('travellerId', '==', g.uid)]) or []
    return jsonify({'ok': True, 'items': [_safe_order(item) for item in items if isinstance(item, dict)]})


@bp.get('/orders/<order_id>')
@auth_required(['traveller'])
def get_order(order_id):
    record = retrieveRecord(ORDER_COLLECTION, order_id)
    if not record or record.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'Order not found'}), 404
    return jsonify({'ok': True, 'order': _safe_order(record)})


@bp.get('/orders/<order_id>/reconcile')
@auth_required(['traveller'])
def reconcile_order(order_id):
    record = retrieveRecord(ORDER_COLLECTION, order_id)
    if not record or record.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'Order not found'}), 404
    session_id = record.get('checkoutSessionId')
    if not session_id:
        return jsonify({'ok': True, 'order': _safe_order(record), 'reconciliationRequired': True}), 202
    try:
        session = retrieveCheckoutSession(session_id)
        patch = (_apply_package_payment(record, session)
                 if record.get('quoteType') == 'package'
                 else _apply_checkout_session(record, session))
        updated = updateRecord(ORDER_COLLECTION, order_id, patch) or {**record, **patch}
        status_code = 202 if patch['reconciliationRequired'] else 200
        return jsonify({'ok': True, 'order': _safe_order(updated), 'reused': True}), status_code
    except Exception:
        return jsonify({'ok': True, 'order': _safe_order(record), 'reconciliationRequired': True}), 202


@bp.post('/webhooks/stripe')
def stripe_webhook():
    try:
        event = constructStripeWebhookEvent(
            request.get_data(), request.headers.get('Stripe-Signature', '')
        )
    except ValueError:
        return jsonify({'ok': False, 'error': 'Invalid Stripe webhook'}), 400
    except Exception:
        return jsonify({'ok': False, 'error': 'Stripe webhook verification is unavailable'}), 503
    event_type = str(_stripe_value(event, 'type', '') or '')
    data = _stripe_value(_stripe_value(event, 'data', {}), 'object', {})
    metadata = _stripe_value(data, 'metadata', {}) or {}
    order_id = str(metadata.get('orderId') or _stripe_value(data, 'client_reference_id', '') or '').strip()
    if not order_id:
        return jsonify({'ok': True, 'ignored': True})
    record = retrieveRecord(ORDER_COLLECTION, order_id)
    if not record:
        return jsonify({'ok': True, 'ignored': True})
    if record.get('quoteType') == 'package':
        if (str(metadata.get('packageAttemptId') or '') != str(record.get('packageAttemptId') or '') or
                str(_stripe_value(data, 'id', '') or '') != str(record.get('checkoutSessionId') or '')):
            return jsonify({'ok': False, 'error': 'Stripe event does not match checkout order.'}), 400
    if str(record.get('status') or '').lower() == 'paid' and record.get('quoteType') != 'package':
        return jsonify({'ok': True, 'received': True, 'ignored': True})
    if event_type in {'checkout.session.completed', 'checkout.session.async_payment_succeeded',
                      'checkout.session.async_payment_failed', 'checkout.session.expired'}:
        if event_type == 'checkout.session.async_payment_failed':
            patch = {'status': 'payment_failed', 'paymentStatus': 'failed', 'updatedAt': utc_now_iso()}
        elif event_type == 'checkout.session.expired':
            patch = {'status': 'expired', 'paymentStatus': 'unpaid', 'updatedAt': utc_now_iso()}
        else:
            patch = (_apply_package_payment(record, data)
                     if record.get('quoteType') == 'package'
                     else _apply_checkout_session(record, data))
        updateRecord(ORDER_COLLECTION, order_id, patch)
        if record.get('quoteType') == 'package' and event_type in {
            'checkout.session.async_payment_failed', 'checkout.session.expired',
        }:
            updateRecord(PACKAGE_ATTEMPT_COLLECTION, record['packageAttemptId'], {
                'checkoutStatus': patch['status'], 'paymentStatus': patch['paymentStatus'],
                'fulfillmentStatus': 'fulfillment_pending', 'updatedAt': utc_now_iso(),
            })
    return jsonify({'ok': True, 'received': True})


def _resolve_booking(booking_id):
    if not booking_id:
        return None, None
    bid = str(booking_id).strip()
    rec = retrieveRecord('hotel_bookings', bid)
    if isinstance(rec, dict) and rec:
        return bid, rec
    by_ref = retrieveRecord('hotel_bookings', filters=[('bookingReference', '==', bid)])
    if by_ref and isinstance(by_ref[0], dict):
        return by_ref[0].get('id') or bid, by_ref[0]
    return None, None


def _payment_attempt_id(payload):
    # Legacy callers remain usable, but only a client-retained ID can provide
    # idempotency across a timeout/reconnect boundary.
    raw = payload.get('paymentAttemptId') or f"legacy_{uuid.uuid4().hex}"
    return normalize_attempt_id(raw, 'paymentAttemptId')


def _payment_document_id(attempt_id):
    return operation_document_id('payment', g.uid, attempt_id)


def _payment_response(record, status_code=200, reused=False, **extra):
    status = normalizePaymentStatus(record.get('paymentStatus'))
    payment = {
        key: value for key, value in record.items()
        if key != 'providerIdempotencyKey'
    }
    payment['paymentStatus'] = status
    return jsonify({
        'ok': status != 'failed',
        'payment': payment,
        'paymentAttemptId': payment.get('paymentAttemptId', ''),
        'status': status,
        'reused': reused,
        'reconciliationRequired': status == 'pending',
        **extra,
    }), status_code


def _claim_payment(payload, booking_doc_id):
    attempt_id = _payment_attempt_id(payload)
    document_id = _payment_document_id(attempt_id)
    booking_context = str(payload.get('bookingId') or booking_doc_id or '')
    now = utc_now_iso()
    record = {
        'travellerId': g.uid,
        'paymentAttemptId': attempt_id,
        'bookingId': booking_context,
        'amount': float(payload['amount']),
        'currency': 'myr',
        'paymentStatus': 'pending',
        'operationStage': 'provider_pending',
        'providerIdempotencyKey': provider_idempotency_key(
            'payment', g.uid, attempt_id, 'process'
        ),
        'cardBrand': payload.get('cardBrand', 'Card'),
        'cardLast4': payload.get('cardLast4', ''),
        'cardholderName': payload.get('cardholderName', ''),
        'billingEmail': payload.get('billingEmail', ''),
        'createdAt': now,
        'updatedAt': now,
    }
    claimed, created = claimRecord('payment_records', document_id, record)
    if claimed.get('travellerId') != g.uid:
        raise PermissionError('Payment attempt does not belong to current traveller')
    same_context = (
        str(claimed.get('bookingId') or '') == booking_context
        and float(claimed.get('amount') or 0) == float(payload['amount'])
    )
    if not same_context:
        raise ValueError('paymentAttemptId is already bound to another payment context')
    return document_id, claimed, created


def _finish_payment(document_id, record, intent, booking_doc_id=None):
    intent_id = getattr(intent, 'id', str(intent))
    status = normalizePaymentStatus(getattr(intent, 'status', 'pending'))
    patch = {
        'paymentStatus': status,
        'transactionReference': intent_id,
        'operationStage': 'provider_completed' if status != 'pending' else 'provider_pending',
        'updatedAt': utc_now_iso(),
    }
    updated = updateRecord('payment_records', document_id, patch) or {
        'id': document_id,
        **record,
        **patch,
    }
    if booking_doc_id and status == 'succeeded':
        updateRecord('hotel_bookings', booking_doc_id, {
            'demoPaymentStatus': 'succeeded',
            'demoPaymentReference': intent_id,
            'paymentAttemptId': record.get('paymentAttemptId'),
            'updatedAt': utc_now_iso(),
        })
    return updated


def _execute_payment(document_id, record, payload, booking_doc_id=None):
    try:
        intent = processPaymentAttempt(
            payload,
            g.uid,
            str(record.get('bookingId') or ''),
            record['providerIdempotencyKey'],
        )
        updated = _finish_payment(document_id, record, intent, booking_doc_id)
        return _payment_response(updated)
    except Exception as exc:
        if is_ambiguous_provider_error(exc):
            patch = {
                'paymentStatus': 'pending',
                'operationStage': 'provider_outcome_unknown',
                'reconciliationRequired': True,
                'updatedAt': utc_now_iso(),
            }
            pending = updateRecord('payment_records', document_id, patch) or {
                'id': document_id,
                **record,
                **patch,
            }
            return _payment_response(pending, 202)
        patch = {
            'paymentStatus': 'failed',
            'operationStage': 'provider_failed',
            'failureReason': str(exc),
            'updatedAt': utc_now_iso(),
        }
        updateRecord('payment_records', document_id, patch)
        return jsonify({
            'ok': False,
            'error': str(exc),
            'paymentAttemptId': record.get('paymentAttemptId'),
            'status': 'failed',
            'newAttemptRequired': True,
        }), 502


def _reconcile_payment_record(record):
    status = normalizePaymentStatus(record.get('paymentStatus'))
    if status != 'pending' or not record.get('transactionReference'):
        return record
    try:
        provider_status = normalizePaymentStatus(
            returnPaymentStatus(record['transactionReference'])
        )
    except Exception:
        return record
    patch = {
        'paymentStatus': provider_status,
        'operationStage': 'provider_completed' if provider_status != 'pending' else 'provider_pending',
        'updatedAt': utc_now_iso(),
    }
    return updateRecord('payment_records', record['id'], patch) or {**record, **patch}


@bp.post('/payments/create-intent')
@auth_required(['traveller'])
def create_payment_intent():
    blocked = _legacy_payment_route_blocked()
    if blocked:
        return blocked
    payload = request.get_json(silent=True) or {}
    _, booking = _resolve_booking(payload.get('bookingId'))
    if booking:
        if booking.get('travellerId') and booking.get('travellerId') != g.uid:
            return jsonify({'ok': False, 'error': 'Unauthorized: booking does not belong to current traveller'}), 403
        authoritative = float(booking.get('hotelCost') or booking.get('price') or booking.get('totalPrice') or 0)
        if str(booking.get('hotelCurrency') or '').upper() != 'MYR':
            return jsonify({'ok': False, 'error': 'This booking has no validated MYR amount for the current payment flow.'}), 409
        if booking.get('amountSource') not in {'validated_offer', 'legacy_verified_myr'}:
            return jsonify({'ok': False, 'error': 'This booking amount is not a validated hotel quote.'}), 409
        if authoritative > 0:
            payload['amount'] = authoritative
    if not validatePaymentInput(payload):
        return jsonify({'ok': False, 'error': 'Positive amount is required'}), 400
    try:
        attempt_id = _payment_attempt_id(payload)
        key = provider_idempotency_key('payment', g.uid, attempt_id, 'intent')
        document_id = operation_document_id('payment_intent', g.uid, attempt_id)
        now = utc_now_iso()
        claimed, created = claimRecord('payment_intent_attempts', document_id, {
            'travellerId': g.uid,
            'paymentAttemptId': attempt_id,
            'bookingId': str(payload.get('bookingId', '')),
            'amount': float(payload['amount']),
            'paymentStatus': 'pending',
            'providerIdempotencyKey': key,
            'createdAt': now,
            'updatedAt': now,
        })
        if (
            str(claimed.get('bookingId') or '') != str(payload.get('bookingId', ''))
            or float(claimed.get('amount') or 0) != float(payload['amount'])
        ):
            return jsonify({'ok': False, 'error': 'paymentAttemptId is already bound to another payment context'}), 409
        if not created and claimed.get('transactionReference'):
            return jsonify({
                'ok': True,
                'paymentAttemptId': attempt_id,
                'paymentIntentId': claimed['transactionReference'],
                'clientSecret': claimed.get('clientSecret'),
                'status': claimed.get('providerStatus', 'requires_payment_method'),
                'reused': True,
            })
        session = createPaymentSession(
            payload,
            g.uid,
            str(payload.get('bookingId', '')),
            idempotencyKey=key,
        )
        provider_status = normalizePaymentStatus(
            getattr(session, 'status', 'pending')
        )
        updateRecord('payment_intent_attempts', document_id, {
            'paymentStatus': 'pending',
            'providerStatus': provider_status,
            'transactionReference': getattr(session, 'id', str(session)),
            'clientSecret': getattr(session, 'client_secret', None),
            'updatedAt': utc_now_iso(),
        })
        return jsonify({
            'ok': True,
            'paymentAttemptId': attempt_id,
            'paymentIntentId': getattr(session, 'id', str(session)),
            'clientSecret': getattr(session, 'client_secret', None),
            'status': provider_status,
        })
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        if 'document_id' in locals() and is_ambiguous_provider_error(exc):
            updateRecord('payment_intent_attempts', document_id, {
                'paymentStatus': 'pending',
                'reconciliationRequired': True,
                'updatedAt': utc_now_iso(),
            })
            return jsonify({
                'ok': True,
                'paymentAttemptId': attempt_id,
                'status': 'pending',
                'reconciliationRequired': True,
            }), 202
        return jsonify({'ok': False, 'error': str(exc)}), 502


@bp.post('/payments/process')
@auth_required(['traveller'])
def process_payment():
    blocked = _legacy_payment_route_blocked()
    if blocked:
        return blocked
    payload = request.get_json(silent=True) or {}
    booking_doc_id, booking = _resolve_booking(payload.get('bookingId'))
    if booking:
        if booking.get('travellerId') and booking.get('travellerId') != g.uid:
            return jsonify({'ok': False, 'error': 'Unauthorized: booking does not belong to current traveller'}), 403
        authoritative = float(booking.get('hotelCost') or booking.get('price') or booking.get('totalPrice') or 0)
        if str(booking.get('hotelCurrency') or '').upper() != 'MYR':
            return jsonify({'ok': False, 'error': 'This booking has no validated MYR amount for the current payment flow.'}), 409
        if booking.get('amountSource') not in {'validated_offer', 'legacy_verified_myr'}:
            return jsonify({'ok': False, 'error': 'This booking amount is not a validated hotel quote.'}), 409
        if authoritative > 0:
            payload['amount'] = authoritative
    if not validatePaymentInput(payload):
        return jsonify({'ok': False, 'error': 'Positive amount is required'}), 400
    try:
        document_id, record, created = _claim_payment(payload, booking_doc_id)
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 409
    except PermissionError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 403

    status = normalizePaymentStatus(record.get('paymentStatus'))
    if not created:
        if status == 'succeeded':
            return _payment_response(record, reused=True)
        if status == 'cancelled':
            return _payment_response(record, 409, reused=True)
        if status == 'failed':
            return _payment_response(
                record,
                409,
                reused=True,
                newAttemptRequired=True,
            )
        # A repeated pending request uses the exact same opaque Stripe key. The
        # provider therefore reconciles the logical attempt rather than creating
        # another PaymentIntent. Simulation mode is deterministic by the key.
    return _execute_payment(document_id, record, payload, booking_doc_id)


@bp.get('/payments/attempts/<attempt_id>')
@auth_required(['traveller'])
def reconcile_payment(attempt_id):
    try:
        attempt_id = normalize_attempt_id(attempt_id, 'paymentAttemptId')
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    record = retrieveRecord('payment_records', _payment_document_id(attempt_id))
    if not record or record.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'Payment attempt not found'}), 404
    reconciled = _reconcile_payment_record(record)
    status_code = 202 if normalizePaymentStatus(reconciled.get('paymentStatus')) == 'pending' else 200
    return _payment_response(reconciled, status_code, reused=True)


@bp.post('/payments/<payment_id>/retry')
@auth_required(['traveller'])
def retry_payment(payment_id):
    existing = retrieveRecord('payment_records', payment_id)
    if not existing or existing.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'Payment not found'}), 404
    status = normalizePaymentStatus(existing.get('paymentStatus'))
    if status == 'succeeded':
        return jsonify({'ok': False, 'error': 'Successful payments cannot be retried'}), 409
    if status == 'failed':
        return jsonify({
            'ok': False,
            'error': 'This payment attempt failed. Start a new payment attempt to try again.',
            'newAttemptRequired': True,
        }), 409
    if status == 'cancelled':
        return jsonify({'ok': False, 'error': 'Cancelled payments cannot be retried'}), 409
    reconciled = _reconcile_payment_record(existing)
    return _payment_response(
        reconciled,
        202 if normalizePaymentStatus(reconciled.get('paymentStatus')) == 'pending' else 200,
        reused=True,
    )


@bp.post('/payments/<payment_id>/cancel')
@auth_required(['traveller'])
def cancel_payment(payment_id):
    existing = retrieveRecord('payment_records', payment_id)
    if not existing or existing.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'Payment not found'}), 404
    if normalizePaymentStatus(existing.get('paymentStatus')) == 'succeeded':
        return jsonify({'ok': False, 'error': 'Successful payments cannot be cancelled'}), 409
    provider_status = existing.get('paymentStatus', 'unknown')
    try:
        if existing.get('transactionReference'):
            provider_status = returnPaymentStatus(existing['transactionReference'])
    except Exception:
        pass
    if normalizePaymentStatus(provider_status) == 'succeeded':
        updateRecord('payment_records', payment_id, {
            'paymentStatus': 'succeeded',
            'updatedAt': utc_now_iso(),
        })
        return jsonify({
            'ok': False,
            'error': 'Provider reports this payment succeeded; it cannot be locally cancelled.',
        }), 409
    result = updateRecord('payment_records', payment_id, {
        'paymentStatus': 'cancelled',
        'cancellationScope': 'travelmate_only',
        'providerCancellationPerformed': False,
        'previousProviderStatus': provider_status,
        'updatedAt': utc_now_iso(),
    })
    return jsonify({
        'ok': True,
        'payment': result,
        'message': 'Payment attempt cancelled in TravelMate. No provider refund was performed.',
    })


@bp.get('/payments')
@auth_required(['traveller'])
def list_payments():
    items = retrieveRecord('payment_records', filters=[('travellerId', '==', g.uid)]) or []
    normalized = [
        {
            **{
                key: value for key, value in item.items()
                if key != 'providerIdempotencyKey'
            },
            'paymentStatus': normalizePaymentStatus(item.get('paymentStatus')),
        }
        for item in items
        if isinstance(item, dict)
    ]
    return jsonify({'ok': True, 'items': normalized})
