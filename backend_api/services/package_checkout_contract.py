"""Server-owned package checkout preparation; Stripe activation is deliberately separate."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib

from services.public_content_projection import eligible_package

PACKAGE_FULFILLMENT_STATES = {
    'checkout_pending', 'payment_pending', 'payment_verified',
    'fulfillment_pending', 'fulfilled', 'fulfillment_failed',
    'payment_failed', 'payment_cancelled',
}


def package_amount_minor_units(snapshot):
    """Return the immutable MYR amount in Stripe minor units without float rounding."""
    try:
        amount = Decimal(str((snapshot or {}).get('price'))).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('Package has no authoritative payable price.')
    if amount <= 0 or str((snapshot or {}).get('currency') or '').upper() != 'MYR':
        raise ValueError('Package has no supported authoritative currency.')
    return int(amount * 100)


def package_trip_compatible(snapshot, trip):
    """Only reject a definite destination mismatch; incomplete data stays recoverable."""
    destination = str((snapshot or {}).get('destination') or '').strip().lower()
    trip_destination = str((trip or {}).get('destinationArea') or '').strip().lower()
    return not (destination and trip_destination and
                destination not in trip_destination and trip_destination not in destination)


def prepare_package_snapshot(package, operator, quantity=1, now=None):
    if not eligible_package(package):
        raise ValueError('Package is not approved and available for checkout.')
    if not package.get('operatorId') or not operator:
        raise ValueError('Package operator could not be verified.')
    try:
        price = float(package.get('adultPrice', package.get('price')))
    except (TypeError, ValueError):
        raise ValueError('Package has no authoritative payable price.')
    currency = str(package.get('currency') or '').upper()
    if price <= 0 or currency != 'MYR':
        raise ValueError('Package has no supported authoritative currency.')
    if package.get('taxIncluded') is None and not package.get('taxNotes'):
        raise ValueError('Package tax and fee treatment is not established.')
    if int(quantity) != 1:
        raise ValueError('Package quantity is not supported by the current contract.')
    return {
        'packageId': str(package.get('id') or ''), 'operatorId': str(package['operatorId']),
        'title': package.get('title') or package.get('packageTitle'),
        'destination': package.get('destination') or package.get('destinationName'),
        'durationDays': package.get('durationDays'), 'departureDates': deepcopy(package.get('departureDates') or []),
        'itineraryDays': deepcopy(package.get('itineraryDays') or []),
        'inclusions': deepcopy(package.get('inclusions') or []), 'exclusions': deepcopy(package.get('exclusions') or []),
        'accommodation': {k: package.get(k) for k in ('accommodationName', 'accommodationCategory', 'roomType', 'accommodationNotes')},
        'transport': {k: package.get(k) for k in ('transportTypes', 'transportNotes')},
        'price': price, 'currency': currency, 'taxIncluded': package.get('taxIncluded'), 'taxNotes': package.get('taxNotes'),
        'revision': package.get('updatedAt') or package.get('createdAt'),
        'snapshotCreatedAt': now or datetime.now(timezone.utc).isoformat(),
    }


def create_package_attempt(claim, traveller_id, package, operator, idempotency_key,
                           intended_trip=None, quantity=1, now=None):
    """Atomically claim a future-payment attempt; never creates a checkout session."""
    if not idempotency_key:
        raise ValueError('An idempotency key is required.')
    if intended_trip is not None and intended_trip.get('travellerId') != traveller_id:
        raise ValueError('The intended trip is not owned by this traveller.')
    snapshot = prepare_package_snapshot(package, operator, quantity, now)
    if not package_trip_compatible(snapshot, intended_trip):
        raise ValueError('Package destination is incompatible with the intended trip.')
    attempt_id = 'package_checkout_' + hashlib.sha256(
        f'{traveller_id}:{idempotency_key}'.encode()).hexdigest()[:24]
    record = {
        'id': attempt_id, 'attemptType': 'package_checkout', 'travellerId': traveller_id,
        'idempotencyKey': idempotency_key, 'packageId': snapshot['packageId'],
        'operatorId': snapshot['operatorId'], 'packageSnapshot': snapshot,
        'amount': snapshot['price'], 'currency': snapshot['currency'],
        'taxIncluded': snapshot['taxIncluded'], 'taxNotes': snapshot['taxNotes'],
        'packageRevision': snapshot['revision'], 'quantity': quantity,
        'intendedTripId': (intended_trip or {}).get('id'),
        'checkoutStatus': 'checkout_pending', 'paymentStatus': 'payment_pending',
        'fulfillmentStatus': 'fulfillment_pending', 'createdAt': snapshot['snapshotCreatedAt'],
        'updatedAt': snapshot['snapshotCreatedAt'],
    }
    existing, created = claim('package_checkout_attempts', attempt_id, record)
    if not created and (existing.get('packageId') != record['packageId'] or
                        existing.get('intendedTripId') != record['intendedTripId']):
        raise ValueError('Idempotency key is already bound to another package or trip.')
    return existing, created
