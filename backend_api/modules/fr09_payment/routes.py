import math
import os
import re
import uuid
import stripe
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from html import escape
from urllib.parse import urlencode, urlparse

from flask import Blueprint, request, jsonify, g, current_app, has_request_context, Response

from auth_utils import auth_required
from utils import utc_now_iso
from services.commerce_money import record_money, public_pricing_breakdown
from services.local_lan import is_lan_address, local_lan_networks
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
    build_initial_fulfillment_record,
    package_amount_minor_units,
    package_trip_compatible,
    validate_package_departure,
)
from sequence_contract.validators import validatePaymentInput
from sequence_contract.firebase_firestore import claimRecord, retrieveRecord, updateRecord

bp = Blueprint('fr09_payments', __name__, url_prefix='/api/fr9')
ORDER_COLLECTION = 'checkout_orders'
PACKAGE_ATTEMPT_COLLECTION = 'package_checkout_attempts'
PACKAGE_FULFILLMENT_COLLECTION = 'package_fulfillments'


class CheckoutContractError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


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
    if isinstance(value, bool):
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if math.isfinite(amount) and amount > 0 else None


def _safe_quote_snapshot(quote):
    allowed = {
        'quoteId', 'offerId', 'hotelId', 'name', 'hotelName', 'roomName', 'boardName',
        'price', 'currency', 'priceBasis', 'priceScope',
        'priceSemanticsStatus', 'taxesAndFeesStatus', 'taxesAndFees', 'cancellation',
        'refundable', 'source', 'sourceLabel', 'quoteCompleteness',
        'roundTripComplete', 'travellerCount', 'passengerComposition',
        'passengerPriceBasis', 'outboundSegments', 'returnSegments',
        'tripType', 'priceStatus', 'currencyStatus', 'checkin', 'checkout',
        'roomQuantity', 'occupancies', 'guestCount', 'transactionMode',
        'supplierBookingStatus', 'acceptedAt', 'expiresAt',
    }
    return {key: quote.get(key) for key in allowed if key in quote}


def _hotel_checkout_quote(payload):
    accepted_id = str(
        payload.get('acceptedPrebookSnapshotId') or
        payload.get('acceptedPrebookId') or ''
    ).strip()
    quote_id = str(payload.get('quoteId') or '').strip()
    offer_id = str(payload.get('offerId') or '').strip()
    if not accepted_id or not quote_id or not offer_id:
        raise ValueError('An accepted hotel prebook snapshot, quote, and offer are required for Checkout.')
    record = retrieveRecord('hotel_prebook_attempts', accepted_id)
    if not record or record.get('travellerId') != g.uid:
        raise ValueError('The accepted hotel prebook was not found or is not owned by this traveller.')
    accepted = record.get('acceptedPrebookSnapshot')
    if not isinstance(accepted, dict) or accepted.get('id') != accepted_id:
        raise ValueError('This hotel prebook predates the secure Checkout contract. Validate the offer again.')
    if accepted.get('travellerId') != g.uid or record.get('status') != 'succeeded':
        raise ValueError('This hotel prebook is not eligible for Checkout.')
    try:
        expires = datetime.fromisoformat(str(accepted.get('expiresAt') or '').replace('Z', '+00:00'))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
    except ValueError:
        expires = datetime.min.replace(tzinfo=timezone.utc)
    if expires <= datetime.now(timezone.utc):
        raise ValueError('This accepted hotel price has expired. Search and validate the offer again.')
    if (str(accepted.get('quoteId') or '') != quote_id or
            str(accepted.get('offerId') or '') != offer_id):
        raise ValueError('This accepted hotel prebook is bound to a different quote or offer.')
    amount = _finite_amount(accepted.get('amount'))
    currency = str(accepted.get('currency') or '').upper()
    if amount is None:
        raise ValueError('This accepted hotel prebook has no authoritative payable amount.')
    if currency != 'MYR':
        raise ValueError('This accepted hotel prebook has no validated MYR currency.')
    if accepted.get('priceBasis') != 'stay_total':
        raise ValueError('This accepted hotel prebook does not prove a total for the requested stay and rooms.')
    if accepted.get('taxesAndFeesStatus') not in {'included', 'excluded', 'mixed'}:
        raise ValueError('This accepted hotel prebook does not disclose its taxes and fees.')
    if (not accepted.get('checkin') or not accepted.get('checkout') or
            not accepted.get('occupancies') or not accepted.get('roomQuantity')):
        raise ValueError('This accepted hotel prebook has incomplete stay or occupancy details.')
    if accepted.get('supplierBookingStatus') != 'not_created':
        raise ValueError('This accepted hotel prebook has already entered supplier booking.')
    validated = record.get('validatedOffer') or {}
    if validated and (
            _finite_amount(validated.get('price')) != amount or
            str(validated.get('currency') or '').upper() != currency or
            str(validated.get('offerId') or '') != offer_id):
        raise ValueError('The accepted hotel price no longer matches the validated prebook.')
    criteria = record.get('criteria') or {}
    if criteria and any(
            accepted.get(key) != criteria.get(key)
            for key in ('checkin', 'checkout', 'roomQuantity', 'occupancies')
    ):
        raise ValueError('The accepted hotel stay no longer matches the validated occupancy.')
    snapshot = _safe_quote_snapshot({
        **accepted,
        'quoteId': quote_id,
        'offerId': offer_id,
    })
    itinerary_id = str(payload.get('itineraryId') or '').strip()
    attempt = accepted.get('hotelBookingAttemptId')
    booking_id = operation_document_id('hotel_book', g.uid, attempt) if attempt else None
    booking = retrieveRecord('hotel_bookings', booking_id) if booking_id else None
    if booking and booking.get('travellerId') == g.uid and booking.get('itineraryAttachmentStatus') == 'succeeded':
        itinerary_id = itinerary_id or booking.get('itineraryId')
    attachment = {}
    if itinerary_id:
        from modules.fr08_hotel_booking.routes import _hotel_trip_compatibility
        if not attempt:
            raise ValueError('Validate and add the hotel to the trip before Checkout.')
        trip = retrieveRecord('itineraries', itinerary_id)
        if (not trip or trip.get('travellerId') != g.uid
                or trip.get('packageTrip') or trip.get('tripType') == 'package'
                or trip.get('hotelBookingId') != booking_id or not booking
                or _finite_amount(trip.get('hotelCost')) != amount
                or booking.get('travellerId') != g.uid
                or booking.get('itineraryId') != itinerary_id
                or booking.get('itineraryAttachmentStatus') != 'succeeded'
                or booking.get('acceptedPrebookSnapshotId') != accepted_id
                or booking.get('providerMutationCalled') is not False
                or _hotel_trip_compatibility(trip, criteria)[1]):
            raise ValueError('The selected hotel is no longer attached to this trip. Reopen Hotels before Checkout.')
        attachment = {'itineraryId': itinerary_id, 'hotelBookingId': booking_id}
    return {
        'quoteType': 'hotel', 'quoteId': quote_id, 'offerId': offer_id,
        'acceptedPrebookSnapshotId': accepted_id,
        'hotelBookingAttemptId': accepted.get('hotelBookingAttemptId'),
        'amount': amount, 'currency': currency, 'quoteSnapshot': snapshot,
        'amountMinor': round(amount * 100),
        'amountBasis': 'provider_offer_total_includes_base_and_included_taxes_fees',
        'sandbox': accepted.get('transactionMode') == 'provider_sandbox',
        **attachment,
    }


def _flight_checkout_quote(payload):
    search_id = str(payload.get('searchId') or payload.get('quoteId') or '').strip()
    option_id = str(payload.get('optionId') or '').strip()
    if not search_id or not option_id:
        raise CheckoutContractError('invalid_flight_quote', 'A completed flight quote and option are required for Checkout.')
    record = retrieveRecord('flight_quotes', f'{g.uid}_{search_id}')
    if not record or record.get('travellerId') != g.uid:
        raise CheckoutContractError('invalid_flight_quote', 'The flight quote was not found or is not owned by this traveller.')
    try:
        expires_at = datetime.fromisoformat(str(record.get('expiresAt') or '').replace('Z', '+00:00'))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise CheckoutContractError('invalid_flight_quote', 'The flight quote has invalid expiry metadata.')
    if expires_at <= datetime.now(timezone.utc):
        raise CheckoutContractError('flight_quote_expired', 'This flight quote has expired. Search again.')
    criteria = dict(record.get('criteria') or {})
    candidates = list(record.get('items') or []) + list((record.get('completedOptions') or {}).values())
    option = next((dict(item) for item in candidates
                   if isinstance(item, dict) and str(item.get('optionId') or item.get('id') or '') == option_id), None)
    if not option:
        raise CheckoutContractError('invalid_flight_quote', 'The selected flight option is not part of the owned quote.')
    if record.get('source') == 'sample_fixture':
        raise CheckoutContractError('invalid_flight_quote', 'Sample flight fixtures cannot enter Checkout.')
    amount = _finite_amount(option.get('price'))
    currency = str(option.get('currency') or '').upper()
    travellers = int(criteria.get('traveller_count') or 0)
    composition = option.get('passengerComposition') or {}
    if amount is None or currency != 'MYR' or option.get('currencyStatus') != 'known':
        raise CheckoutContractError('flight_price_unavailable', 'This flight quote has no validated MYR payable amount.')
    if option.get('quoteCompleteness') != 'complete' or option.get('budgetEligible') is False:
        raise CheckoutContractError('invalid_flight_quote', 'Complete flight quote selection is required before Checkout.')
    if criteria.get('return_date') and not option.get('roundTripComplete'):
        raise CheckoutContractError('invalid_flight_quote', 'A complete round-trip quote is required before Checkout.')
    if option.get('priceScope') != 'provider_ticket_price' or option.get('priceSemanticsStatus') != 'provider_response_requested_adults':
        raise CheckoutContractError('flight_price_unavailable', 'This flight quote does not prove an adult-party ticket total.')
    if not travellers or option.get('travellerCount') != travellers or composition.get('adults') != travellers:
        raise CheckoutContractError('invalid_flight_quote', 'This flight quote does not match the requested adult party.')
    if criteria.get('return_date') and not str(option.get('priceBasis') or '').startswith('provider_round_trip_'):
        raise CheckoutContractError('flight_price_unavailable', 'This round-trip quote has no verified combined ticket total.')
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


def _checkout_action(record, session_verified=False):
    status = str(record.get('status') or '').strip().lower()
    payment_status = str(record.get('paymentStatus') or '').strip().lower()
    if status == 'paid' or payment_status in {'paid', 'succeeded'}:
        return 'view_booking'
    if status in {'expired', 'checkout_failed', 'payment_failed', 'cancelled', 'canceled'}:
        return 'restart_payment'
    verified_open = session_verified or record.get('checkoutSessionStatus') == 'open'
    if (verified_open and status == 'checkout_open' and
            record.get('checkoutSessionId') and record.get('checkoutUrl')):
        return 'continue_payment'
    return 'check_status'


def _safe_order(record, session_verified=False):
    safe = {
        key: value for key, value in record.items()
        if key not in {'providerIdempotencyKey', 'checkoutUrl'}
    }
    action = _checkout_action(record, session_verified=session_verified)
    safe['checkoutAction'] = action
    if session_verified and action == 'continue_payment':
        safe['checkoutUrl'] = record.get('checkoutUrl')
    if safe.get('quoteType') == 'hotel':
        status = str(safe.get('status') or '').lower()
        payment_status = str(safe.get('paymentStatus') or '').lower()
        is_paid = status == 'paid' or payment_status == 'paid'
        safe.setdefault('fulfillmentStatus', 'demo_only' if is_paid else 'not_started')
        safe.setdefault('supplierBookingStatus', 'not_created')
        safe.setdefault('isSimulated', True)
        safe.setdefault('fulfillmentMode', 'demo_only')
        safe.setdefault('bookingReference', None)
        safe.setdefault('demoDisclosure', 'Demo reservation — no supplier room has been reserved.')
    return safe


def _payment_history_title(record):
    kind = record.get('quoteType')
    package = record.get('packageSnapshot')
    quote = record.get('quoteSnapshot')
    package = package if isinstance(package, dict) else {}
    quote = quote if isinstance(quote, dict) else {}
    if kind == 'package' or package:
        names = (package.get('title'), package.get('name'), record.get('packageTitle'))
        fallback = 'Tourism package'
    elif kind == 'hotel':
        names = (quote.get('name'), quote.get('hotelName'), record.get('hotelName'), quote.get('title'))
        fallback = 'Hotel stay'
    else:
        names = (quote.get('name'), quote.get('title'))
        fallback = None
    return next((name.strip() for name in (*names, record.get('productTitle'))
                 if isinstance(name, str) and name.strip()
                 and not name.strip().lower().startswith(('travelmate hotel test order',
                                                          'travelmate package test order'))), fallback)


def _payment_history_provider(record):
    provider = str(record.get('provider') or '').strip().lower()
    reference = str(record.get('transactionReference') or '').strip().lower()
    if provider == 'stripe_checkout_test':
        return 'stripe', True
    if reference.startswith('pi_sim_'):
        return 'travelmate_simulation', True
    if reference.startswith('pi_'):
        return 'stripe', None
    return None, None


def _payment_history_item(record, source):
    provider, test_mode = _payment_history_provider(record)
    timestamp = (
        record.get('paidAt') or record.get('updatedAt') or record.get('createdAt')
    )
    if source == 'checkout_order':
        booking_type = str(record.get('quoteType') or 'unknown').strip().lower()
        order_status = str(record.get('status') or 'unknown').strip().lower()
        raw_payment_status = record.get('paymentStatus')
        payment_status = str(
            raw_payment_status or ('paid' if order_status == 'paid' else 'unknown')
        ).strip().lower()
    else:
        booking_type = str(record.get('bookingType') or 'legacy_payment').strip().lower()
        payment_status = normalizePaymentStatus(record.get('paymentStatus'))
        order_status = None
    currency = record_money(record)[1]
    item = {
        'id': record.get('id'),
        'orderReference': record.get('id'),
        'bookingType': booking_type,
        'timestamp': timestamp,
        'amount': record.get('amount'),
        'currency': None if currency == 'UNKNOWN' else currency,
        'paymentStatus': payment_status,
        'orderStatus': order_status,
        'testMode': test_mode,
        'paymentProvider': provider,
        'relatedTripId': record.get('fulfilledTripId') or record.get('tripId'),
        'relatedBookingId': record.get('bookingId'),
        'productTitle': _payment_history_title(record),
        'source': source,
    }
    if source == 'checkout_order':
        item['checkoutAction'] = _checkout_action(record)
        if booking_type == 'package' and (record.get('packageSnapshot') or {}).get('pricingBreakdown'):
            item['pricingBreakdown'] = public_pricing_breakdown((record.get('packageSnapshot') or {}).get('pricingBreakdown'))
            item['promoCode'] = (record.get('packageSnapshot') or {}).get('requestedPromoCode', '')
        if booking_type == 'hotel':
            item['itineraryId'] = record.get('itineraryId')
            item['hotelBookingId'] = record.get('hotelBookingId')
            item['relatedTripId'] = record.get('itineraryId')
            item['fulfillmentStatus'] = record.get('fulfillmentStatus') or (
                'demo_only' if payment_status == 'paid' else 'not_started'
            )
            item['supplierBookingStatus'] = record.get('supplierBookingStatus') or 'not_created'
            item['isSimulated'] = record.get('isSimulated', True)
            item['fulfillmentMode'] = record.get('fulfillmentMode', 'demo_only')
            item['bookingReference'] = record.get('bookingReference')
            item['demoDisclosure'] = record.get('demoDisclosure', 'Demo reservation — no supplier room has been reserved.')
            item['hotelBookingAttemptId'] = record.get('hotelBookingAttemptId')
            item['acceptedPrebookSnapshotId'] = record.get('acceptedPrebookSnapshotId')
            quote_snapshot = record.get('quoteSnapshot')
            if isinstance(quote_snapshot, dict):
                item['hotelName'] = quote_snapshot.get('name') or quote_snapshot.get('hotelName')
                item['roomName'] = quote_snapshot.get('roomName')
                item['checkin'] = quote_snapshot.get('checkin')
                item['checkout'] = quote_snapshot.get('checkout')
                item['roomQuantity'] = quote_snapshot.get('roomQuantity')
                item['occupancies'] = quote_snapshot.get('occupancies')
        if booking_type == 'package' and item['checkoutAction'] == 'restart_payment':
            snapshot = record.get('packageSnapshot') or {}
            participants = record.get('participants') or snapshot.get('participants') or {}
            item['packageId'] = record.get('packageId') or snapshot.get('packageId')
            item['departureDate'] = record.get('departureDate') or snapshot.get('selectedDepartureDate')
            item['participants'] = {
                'adults': participants.get('adults'),
                'children': participants.get('children'),
            }
    if source == 'legacy_payment':
        if record.get('cardBrand'):
            item['cardBrand'] = record.get('cardBrand')
        if record.get('cardLast4'):
            item['cardLast4'] = record.get('cardLast4')
    return item


def _configured_checkout_url(name, fallback):
    value = os.getenv(name, fallback).strip()
    parsed = urlparse(value)
    if parsed.scheme not in {'https', 'http'} or not parsed.netloc:
        raise RuntimeError(f'{name} is not configured with an absolute URL.')
    if parsed.hostname and parsed.hostname.lower() in {'example.com', 'www.example.com'}:
        raise RuntimeError(f'{name} must be an explicit TravelMate return URL.')
    if os.getenv('APP_ENV', 'development').strip().lower() == 'production' and parsed.scheme != 'https':
        raise RuntimeError(f'{name} must use HTTPS in production.')
    return value


def _checkout_return_url(outcome):
    if outcome not in {'success', 'cancel'}:
        raise RuntimeError('Unsupported Checkout return outcome.')
    networks = local_lan_networks()
    origin = os.getenv('STRIPE_CHECKOUT_RETURN_ORIGIN', '').strip().rstrip('/')
    local_origins = current_app.config.get('LOCAL_LAN_ORIGINS', ()) if networks and has_request_context() else ()
    if local_origins:
        incoming = f'http://{request.host}'
        if incoming in local_origins:
            origin = incoming
        elif request.remote_addr not in {'127.0.0.1', '::1'} or origin not in local_origins:
            raise RuntimeError('Checkout requires an approved LOCAL_LAN_ORIGINS address.')
    if origin:
        parsed = urlparse(origin)
        if (parsed.scheme not in {'https', 'http'} or not parsed.hostname or
                parsed.username or parsed.password or parsed.query or parsed.fragment or
                parsed.path not in {'', '/'}):
            raise RuntimeError('STRIPE_CHECKOUT_RETURN_ORIGIN must be an origin without a path or credentials.')
        if networks:
            if parsed.scheme != 'http' or not is_lan_address(parsed.hostname, networks):
                raise RuntimeError('LOCAL_LAN_DEMO Checkout origin must be reachable inside TRUSTED_LAN_CIDR.')
        elif os.getenv('APP_ENV', 'development').strip().lower() == 'production' and parsed.scheme != 'https':
            raise RuntimeError('STRIPE_CHECKOUT_RETURN_ORIGIN must use HTTPS in production.')
        return f'{origin}/api/fr9/checkout/return/{outcome}?session_id={{CHECKOUT_SESSION_ID}}'
    if networks:
        raise RuntimeError('LOCAL_LAN_DEMO requires STRIPE_CHECKOUT_RETURN_ORIGIN.')
    name = 'STRIPE_CHECKOUT_SUCCESS_URL' if outcome == 'success' else 'STRIPE_CHECKOUT_CANCEL_URL'
    fallback = f'http://127.0.0.1:5000/api/fr9/checkout/return/{outcome}?session_id={{CHECKOUT_SESSION_ID}}'
    return _configured_checkout_url(name, fallback)


def _checkout_return_html(heading, message, order_id, state):
    app_url = 'travelmate://checkout/return?' + urlencode({
        'order_id': str(order_id),
        'state': str(state),
    })
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" '
        'content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
        '<title>TravelMate Checkout</title>'
        '<style>body{font-family:sans-serif;max-width:38rem;margin:4rem auto;padding:0 1.25rem;line-height:1.5}'
        'a{display:inline-block;margin:1rem 0;padding:.8rem 1rem;border-radius:.5rem;'
        'background:#155eef;color:white;text-decoration:none;font-weight:700}</style></head><body>'
        f'<h1>{escape(heading)}</h1><p>{escape(message)}</p>'
        f'<p><a href="{escape(app_url, quote=True)}">Return to TravelMate</a></p>'
        '<p>If TravelMate does not open, close this browser tab, open the app manually, '
        'and check Payment History or Orders. Do not pay again.</p>'
        '</body></html>'
    )


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


def _apply_hotel_payment(order, session):
    patch = _apply_checkout_session(order, session)
    now = utc_now_iso()
    status = str(patch.get('status') or '').lower()
    payment_status = str(patch.get('paymentStatus') or '').lower()
    if status == payment_status == 'paid' and order.get('status') != 'paid' and (
            _stripe_value(session, 'amount_total') is None or not _stripe_value(session, 'currency', '')):
        status = patch['status'] = 'payment_mismatch'
        patch['reconciliationRequired'] = True
    is_paid = status == 'paid' and payment_status == 'paid'
    if status == 'payment_mismatch':
        patch['paymentStatus'] = 'unverified'
    if is_paid:
        patch.update({
            'fulfillmentStatus': 'demo_only',
            'supplierBookingStatus': 'not_created',
            'isSimulated': True,
            'fulfillmentMode': 'demo_only',
            'bookingReference': None,
            'demoDisclosure': 'Demo reservation — no supplier room has been reserved.',
            'fulfillmentUpdatedAt': order.get('fulfillmentUpdatedAt') or now,
        })
        snapshot_id = order.get('acceptedPrebookSnapshotId')
        if snapshot_id:
            updateRecord('hotel_prebook_attempts', snapshot_id, {
                'orderId': order.get('id'),
                'paymentStatus': 'paid',
                'fulfillmentStatus': 'demo_only',
                'supplierBookingStatus': 'not_created',
                'updatedAt': now,
            })
    else:
        patch.setdefault('fulfillmentStatus', order.get('fulfillmentStatus') or 'not_started')
        patch.setdefault('supplierBookingStatus', 'not_created')
        patch.setdefault('isSimulated', True)
        patch.setdefault('fulfillmentMode', 'demo_only')
        patch.setdefault('bookingReference', None)
        patch.setdefault('demoDisclosure', 'Demo reservation — no supplier room has been reserved.')
    return patch


def _sync_package_attempt_status(order):
    attempt_id = str(order.get('packageAttemptId') or '')
    if not attempt_id:
        return
    updateRecord(PACKAGE_ATTEMPT_COLLECTION, attempt_id, {
        'checkoutStatus': str(order.get('status') or '').lower(),
        'paymentStatus': str(order.get('paymentStatus') or '').lower(),
        'checkoutOrderId': order.get('id'),
        'updatedAt': utc_now_iso(),
    })


def _persist_checkout_update(record, patch):
    if record.get('quoteType') == 'package':
        updated = updateRecord(ORDER_COLLECTION, record['id'], patch, expected=record)
        if not updated:
            raise RuntimeError('Package order storage unavailable')
        return updated
    return updateRecord(ORDER_COLLECTION, record['id'], patch) or {**record, **patch}


def _reconcile_checkout_order(record):
    session_id = str(record.get('checkoutSessionId') or '').strip()
    if not session_id:
        return record, False
    session = retrieveCheckoutSession(session_id)
    if record.get('quoteType') == 'package':
        patch = _apply_package_payment(record, session)
    elif record.get('quoteType') == 'hotel':
        patch = _apply_hotel_payment(record, session)
    else:
        patch = _apply_checkout_session(record, session)
    patch['checkoutSessionStatus'] = str(_stripe_value(session, 'status', '') or '').lower()
    updated = _persist_checkout_update(record, patch)
    if updated.get('quoteType') == 'package':
        _sync_package_attempt_status(updated)
    return updated, True


def _package_attempt_for_checkout(attempt_id):
    attempt = retrieveRecord(PACKAGE_ATTEMPT_COLLECTION, attempt_id)
    if not attempt or attempt.get('travellerId') != g.uid:
        raise PermissionError('Package checkout attempt was not found.')
    snapshot = attempt.get('packageSnapshot') or {}
    package_amount_minor_units(snapshot)
    if (str(attempt.get('checkoutStatus') or '').lower() in {'paid', 'cancelled', 'expired'} or
            str(attempt.get('paymentStatus') or '').lower() in {'paid', 'succeeded'}):
        raise ValueError('This package checkout attempt is no longer payable.')
    validate_package_departure(snapshot,snapshot.get('selectedDepartureDate'),allow_default=False)
    package = retrieveRecord('tourism_packages',snapshot.get('packageId'))
    from services.public_content_projection import eligible_package
    if not eligible_package(package) or package.get('operatorId')!=snapshot.get('operatorId'):
        raise ValueError('The package is no longer approved and available for a new checkout. Reopen the package to review it.')
    validate_package_departure(package,snapshot.get('selectedDepartureDate'),allow_default=False)
    # Existing hosted sessions keep their immutable order and reconciliation path.
    existing = retrieveRecord(ORDER_COLLECTION, _package_order_document_id(attempt_id))
    if not existing or not existing.get('checkoutSessionId'):
        from services.package_checkout_contract import prepare_package_snapshot
        from services.package_pricing import pricing_fingerprint
        if snapshot.get('pricingVersion') != 'campaigns_v1':
            raise ValueError('This older unpaid quote must be refreshed. Return to the package and review the current amount.')
        current = prepare_package_snapshot(package, {'id': package.get('operatorId')},
            participants=snapshot.get('participants'), departure_date=snapshot.get('selectedDepartureDate'),
            campaigns=retrieveRecord('promotional_campaigns', filters=[('operatorId', '==', package.get('operatorId'))]),
            promo_code=snapshot.get('requestedPromoCode', ''))
        if pricing_fingerprint(snapshot) != pricing_fingerprint(current):
            raise ValueError('Package price or promotion terms changed. Return to the package, refresh and accept the current quote before payment.')
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
    initial_fulfillment_record = build_initial_fulfillment_record(snapshot, now=now)
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
        'fulfillmentStatus': 'awaiting_operator_fulfillment',
        'supplierReservationStatus': 'not_created',
        'fulfillmentRecord': deepcopy(initial_fulfillment_record),
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
        'status': 'awaiting_operator_fulfillment', 'updatedAt': utc_now_iso(),
    })
    return {'fulfillmentStatus': 'awaiting_operator_fulfillment', 'fulfillmentRetryRequired': False,
            'fulfilledTripId': trip_id, 'fulfillmentRecord': initial_fulfillment_record}


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
    # A replayed paid session is not permission to reopen a terminal order.
    if any(str(order.get(key) or '').lower() in {'refunded', 'partially_refunded', 'rejected'}
           for key in ('status', 'paymentStatus')):
        return {key: order.get(key) for key in ('status', 'paymentStatus')}
    patch = _apply_checkout_session(order, session)
    if patch['status'] != 'paid':
        return patch
    # Supplier progress is independent of repeated payment verification. Omit
    # these fields entirely so a concurrent attestation is not overwritten.
    if (order.get('fulfillmentStatus') in {'trip_ready', 'partially_fulfilled', 'fulfillment_declined'} or
            (order.get('fulfilledTripId') and not order.get('fulfillmentRetryRequired'))):
        return patch
    fulfillment = _fulfill_package_order(order)
    updateRecord(PACKAGE_ATTEMPT_COLLECTION, order['packageAttemptId'], {
        'checkoutStatus': 'checkout_complete', 'paymentStatus': 'paid',
        **fulfillment, 'updatedAt': utc_now_iso(),
    })
    return {**patch, **fulfillment}


@bp.get('/checkout/capabilities')
@auth_required(['traveller'])
def checkout_capabilities():
    # Configuration only: never contact Stripe or disclose credential values.
    available = (os.getenv('STRIPE_SECRET_KEY', '').strip().startswith('sk_test_') and
                 os.getenv('STRIPE_WEBHOOK_SECRET', '').strip().startswith('whsec_') and
                 (current_app.config.get('LOCAL_LAN_ORIGINS') or
                  os.getenv('STRIPE_CHECKOUT_RETURN_ORIGIN', '').strip() or
                  (os.getenv('STRIPE_CHECKOUT_SUCCESS_URL', '').strip() and
                   os.getenv('STRIPE_CHECKOUT_CANCEL_URL', '').strip())))
    try:
        _checkout_return_url('success')
        _checkout_return_url('cancel')
    except RuntimeError:
        available = False
    return jsonify({'ok': True, 'mode': 'test', 'hostedCheckout': bool(available),
                    'packagePricingContract': 'campaigns_v1',
                    'supportedQuoteTypes': ['hotel', 'package'] if available else []})


@bp.post('/package-checkout-attempts/<attempt_id>/checkout/session')
@auth_required(['traveller'])
def create_package_checkout_session(attempt_id):
    try:
        attempt, snapshot = _package_attempt_for_checkout(attempt_id)
    except PermissionError:
        return jsonify({'ok': False, 'error': 'Package checkout attempt was not found.'}), 404
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 409
    except Exception:
        return jsonify({'ok':False,'error':'Package price verification is temporarily unavailable. Try again later.'}),503
    minor_units = package_amount_minor_units(snapshot)
    order_id = _package_order_document_id(attempt_id)
    now = utc_now_iso()
    record = {
        'id': order_id, 'travellerId': g.uid, 'orderAttemptId': attempt_id,
        'packageAttemptId': attempt_id, 'quoteType': 'package',
        'packageId': snapshot.get('packageId'), 'operatorId': snapshot.get('operatorId'),
        'packageSnapshot': snapshot, 'amount': minor_units / 100,
        'stripeProductName': _payment_history_title({'quoteType': 'package', 'packageSnapshot': snapshot}),
        'pricingBreakdown': snapshot.get('pricingBreakdown'),
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
        try:
            reconciled, verified = _reconcile_checkout_order(claimed)
            action = _checkout_action(reconciled, verified)
            return jsonify({'ok': True,
                            'order': _safe_order(reconciled, session_verified=verified),
                            'reused': True}), (202 if action == 'check_status' else 200)
        except Exception:
            uncertain = {**claimed, 'checkoutSessionStatus': None}
            return jsonify({'ok': True, 'order': _safe_order(uncertain), 'reused': True,
                            'reconciliationRequired': True}), 202
    try:
        session = createCheckoutSession(
            snapshot['price'], 'MYR', g.uid, order_id,
            _checkout_return_url('success'),
            _checkout_return_url('cancel'),
            metadata={'packageAttemptId': attempt_id, 'quoteType': 'package'},
            idempotency_key=claimed['providerIdempotencyKey'],
            product_name=claimed.get('stripeProductName') or
            f"TravelMate package test order: {snapshot.get('title') or snapshot.get('packageId')}",
        )
        session_id, checkout_url = str(_stripe_value(session, 'id', '') or ''), str(_stripe_value(session, 'url', '') or '')
        if not session_id or not checkout_url:
            raise RuntimeError('Stripe did not return a Checkout URL.')
        patch = {'checkoutSessionId': session_id, 'checkoutUrl': checkout_url,
                 'checkoutSessionStatus': 'open',
                 'status': 'checkout_open', 'updatedAt': utc_now_iso()}
        updated = updateRecord(ORDER_COLLECTION, order_id, patch) or {**claimed, **patch}
        updateRecord(PACKAGE_ATTEMPT_COLLECTION, attempt_id, {
            'checkoutStatus': 'checkout_open', 'checkoutOrderId': order_id,
            'updatedAt': utc_now_iso(),
        })
        return jsonify({'ok': True, 'order': _safe_order(updated, session_verified=True),
                        'reused': not created})
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
    except CheckoutContractError as exc:
        return jsonify({'ok': False, 'code': exc.code, 'error': str(exc)}), 409
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 409
    if quote.get('quoteType') == 'flight':
        return jsonify({
            'ok': False,
            'code': 'flight_ticketing_unavailable',
            'error': 'TravelMate can save this fare as a planning estimate, but cannot issue or reserve an airline ticket.',
        }), 409
    if quote.get('hotelBookingId'):
        # A linked accepted stay has one order even across app reinstalls or taps.
        attempt_id = quote['hotelBookingId']
        prior_id = (retrieveRecord('hotel_prebook_attempts', quote['acceptedPrebookSnapshotId']) or {}).get('orderId')
        if prior_id and prior_id != _order_document_id(attempt_id):
            return jsonify(ok=False, error='This hotel offer already has an order. Open Payment History.'), 409
    order_id = _order_document_id(attempt_id)
    now = utc_now_iso()
    record = {
        'id': order_id,
        'travellerId': g.uid,
        'orderAttemptId': attempt_id,
        **quote,
        'stripeProductName': _payment_history_title(quote),
        'status': 'checkout_pending',
        'paymentStatus': 'unpaid',
        'provider': 'stripe_checkout_test',
        'providerIdempotencyKey': provider_idempotency_key(
            'checkout', g.uid, attempt_id, 'session'
        ),
        'createdAt': now,
        'updatedAt': now,
    }
    if quote.get('quoteType') == 'hotel':
        record.update({
            'fulfillmentStatus': 'not_started',
            'supplierBookingStatus': 'not_created',
            'isSimulated': True,
            'fulfillmentMode': 'demo_only',
            'bookingReference': None,
            'demoDisclosure': 'Demo reservation — no supplier room has been reserved.',
        })
    try:
        claimed, created = claimRecord(ORDER_COLLECTION, order_id, record)
    except Exception:
        return jsonify({'ok': False, 'error': 'Order storage is unavailable. Try again later.'}), 503
    if claimed.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'This order is not owned by the current traveller.'}), 403
    if str(claimed.get('status') or '').lower() == 'paid':
        return jsonify({'ok': False, 'error': 'This Checkout order has already been paid.'}), 409
    for key in (
            'quoteType', 'quoteId', 'offerId', 'optionId', 'amount', 'currency',
            'acceptedPrebookSnapshotId', 'itineraryId', 'hotelBookingId'):
        if key in record and str(claimed.get(key)) != str(record.get(key)):
            return jsonify({'ok': False, 'error': 'Order attempt is already bound to another quote.'}), 409
    if record.get('hotelBookingId') and (created or not claimed.get('checkoutSessionId')):
        try:
            if not updateRecord('hotel_bookings', record['hotelBookingId'], {'checkoutOrderId': order_id}):
                raise RuntimeError('Hotel payment link unavailable')
        except Exception:
            return jsonify(ok=False, error='The hotel payment link is unavailable. Try again.'), 503
    if claimed.get('checkoutSessionId') and claimed.get('checkoutUrl'):
        try:
            reconciled, verified = _reconcile_checkout_order(claimed)
            action = _checkout_action(reconciled, verified)
            return jsonify({'ok': True,
                            'order': _safe_order(reconciled, session_verified=verified),
                            'reused': True}), (202 if action == 'check_status' else 200)
        except Exception:
            uncertain = {**claimed, 'checkoutSessionStatus': None}
            return jsonify({'ok': True, 'order': _safe_order(uncertain), 'reused': True,
                            'reconciliationRequired': True}), 202
    try:
        session = createCheckoutSession(
            quote['amount'], quote['currency'], g.uid, order_id,
            _checkout_return_url('success'),
            _checkout_return_url('cancel'),
            metadata={
                'orderAttemptId': attempt_id,
                'quoteType': quote['quoteType'],
                'quoteId': quote['quoteId'],
            },
            idempotency_key=claimed['providerIdempotencyKey'],
            product_name=claimed.get('stripeProductName') or f"TravelMate {quote['quoteType']} test order",
        )
        session_id = str(_stripe_value(session, 'id', '') or '')
        checkout_url = str(_stripe_value(session, 'url', '') or '')
        if not session_id or not checkout_url:
            raise RuntimeError('Stripe did not return a Checkout URL.')
        updated = updateRecord(ORDER_COLLECTION, order_id, {
            'checkoutSessionId': session_id,
            'checkoutUrl': checkout_url,
            'checkoutSessionStatus': 'open',
            'status': 'checkout_open',
            'updatedAt': utc_now_iso(),
        }) or {**claimed, 'checkoutSessionId': session_id, 'checkoutUrl': checkout_url,
               'checkoutSessionStatus': 'open', 'status': 'checkout_open'}
        if record.get('quoteType') == 'hotel' and record.get('acceptedPrebookSnapshotId'):
            updateRecord('hotel_prebook_attempts', record['acceptedPrebookSnapshotId'], {
                'orderId': order_id,
                'checkoutSessionId': session_id,
                'updatedAt': utc_now_iso(),
            })
        return jsonify({'ok': True, 'order': _safe_order(updated, session_verified=True),
                        'reused': not created})
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
        if record.get('quoteType') == 'package':
            patch = _apply_package_payment(record, session)
        elif record.get('quoteType') == 'hotel':
            patch = _apply_hotel_payment(record, session)
        else:
            patch = _apply_checkout_session(record, session)
        updated = _persist_checkout_update(record, patch)
        status = str(updated.get('status') or '').lower()
        if status == 'paid':
            heading = 'Payment Successful'
            message = 'Your TravelMate test payment has been verified.'
            state = 'paid'
        elif outcome == 'success' and status in {'checkout_open', 'checkout_pending', 'payment_pending'}:
            heading = 'Payment Processing'
            message = 'Your payment is being verified. You may return to TravelMate to check the status.'
            state = 'processing'
        else:
            heading = 'Payment Not Completed'
            message = 'No successful payment was confirmed. Open TravelMate Orders to review the order.'
            state = 'not_completed'
        html = _checkout_return_html(heading, message, order_id, state)
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
    safe = _safe_order(record)
    if record.get('quoteType')=='package':
        from services.booking_requirements import read_public_clarification
        summary = read_public_clarification(record,retrieveRecord)
        if summary:safe['approvedRequirementClarification']=summary
    return jsonify({'ok': True, 'order': safe})


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
        updated, verified = _reconcile_checkout_order(record)
        action = _checkout_action(updated, session_verified=verified)
        status_code = 202 if action == 'check_status' else 200
        return jsonify({'ok': True,
                        'order': _safe_order(updated, session_verified=verified),
                        'reused': True}), status_code
    except Exception:
        return jsonify({'ok': True, 'order': _safe_order(record), 'reconciliationRequired': True}), 202


@bp.post('/webhooks/stripe')
def stripe_webhook():
    try:
        event = constructStripeWebhookEvent(
            request.get_data(), request.headers.get('Stripe-Signature', '')
        )
    except (ValueError, stripe.error.SignatureVerificationError):
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
    if (str(record.get('status') or '').lower() == 'paid' and
            record.get('quoteType') != 'package' and
            (record.get('quoteType') != 'hotel' or record.get('fulfillmentStatus') == 'demo_only')):
        return jsonify({'ok': True, 'received': True, 'ignored': True})
    if event_type in {'checkout.session.completed', 'checkout.session.async_payment_succeeded',
                      'checkout.session.async_payment_failed', 'checkout.session.expired'}:
        if event_type == 'checkout.session.async_payment_failed':
            patch = {'status': 'payment_failed', 'paymentStatus': 'failed', 'updatedAt': utc_now_iso()}
            if record.get('quoteType') == 'hotel':
                patch.update({'fulfillmentStatus': 'not_started', 'supplierBookingStatus': 'not_created'})
        elif event_type == 'checkout.session.expired':
            patch = {'status': 'expired', 'paymentStatus': 'unpaid', 'updatedAt': utc_now_iso()}
            if record.get('quoteType') == 'hotel':
                patch.update({'fulfillmentStatus': 'not_started', 'supplierBookingStatus': 'not_created'})
        else:
            if record.get('quoteType') == 'package':
                patch = _apply_package_payment(record, data)
            elif record.get('quoteType') == 'hotel':
                patch = _apply_hotel_payment(record, data)
            else:
                patch = _apply_checkout_session(record, data)
        _persist_checkout_update(record, patch)
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
    ownership_filter = [('travellerId', '==', g.uid)]
    sources = (
        ('checkout_order', retrieveRecord(ORDER_COLLECTION, filters=ownership_filter) or []),
        ('legacy_payment', retrieveRecord('payment_records', filters=ownership_filter) or []),
    )
    normalized = []
    seen = set()
    for source, records in sources:
        for record in records:
            if not isinstance(record, dict) or record.get('travellerId') != g.uid:
                continue
            record_id = record.get('id')
            key = str(record_id)
            if not record_id or key in seen:
                continue
            seen.add(key)
            normalized.append(_payment_history_item(record, source))
    normalized.sort(key=lambda item: str(item.get('timestamp') or ''), reverse=True)
    return jsonify({'ok': True, 'items': normalized})
