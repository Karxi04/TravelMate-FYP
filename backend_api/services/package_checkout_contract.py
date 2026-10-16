"""Server-owned package checkout preparation; Stripe activation is deliberately separate."""
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib

from services.public_content_projection import eligible_package

PACKAGE_FULFILLMENT_STATES = {
    'checkout_pending', 'payment_pending', 'payment_verified',
    'fulfillment_pending', 'fulfilled', 'fulfillment_failed',
    'payment_failed', 'payment_cancelled',
}
MAX_GROUP_PARTICIPANTS = 50


def _integer_count(value, label):
    if isinstance(value, bool):
        raise ValueError(f'{label} must be a non-negative integer.')
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'{label} must be a non-negative integer.')
    if number < 0 or number != number.to_integral_value():
        raise ValueError(f'{label} must be a non-negative integer.')
    return int(number)


def _money(value, label):
    try:
        amount = Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'Package has no authoritative {label}.')
    if amount < 0:
        raise ValueError(f'Package has no authoritative {label}.')
    return amount


def _json_money(value):
    return int(value) if value == value.to_integral_value() else float(value)


def _participants(package, value):
    value = value or {'adults': 1, 'children': 0}
    if not isinstance(value, dict):
        raise ValueError('Package participants must include adult and child counts.')
    adults = _integer_count(value.get('adults', 0), 'Adults')
    children = _integer_count(value.get('children', 0), 'Children')
    total = adults + children
    if total < 1:
        raise ValueError('At least one package participant is required.')
    if adults < 1:
        raise ValueError('At least one adult is required for a package booking.')
    if total > MAX_GROUP_PARTICIPANTS:
        raise ValueError(f'Package groups cannot exceed {MAX_GROUP_PARTICIPANTS} participants.')
    minimum = package.get('minimumTravellers')
    maximum = package.get('maximumTravellers', package.get('maxTravellers'))
    if minimum not in (None, '') and total < _integer_count(minimum, 'Minimum travellers'):
        raise ValueError('The group is smaller than this package minimum.')
    if maximum not in (None, '') and total > _integer_count(maximum, 'Maximum travellers'):
        raise ValueError('The group exceeds this package capacity.')
    return {'adults': adults, 'children': children, 'total': total}


def _departure_date(package, requested):
    available = [str(value).strip() for value in package.get('departureDates') or [] if str(value).strip()]
    requested = str(requested or '').strip()
    if not requested and len(available) == 1:
        requested = available[0]
    if available and not requested:
        raise ValueError('Select one of the available package departure dates.')
    if requested and available and requested not in available:
        raise ValueError('The selected package departure date is unavailable.')
    if requested:
        try:
            date.fromisoformat(requested)
        except ValueError:
            raise ValueError('The selected package departure date is invalid.')
    return requested or None


def package_amount_minor_units(snapshot):
    """Return the immutable MYR amount in Stripe minor units without float rounding."""
    stored_minor = (snapshot or {}).get('amountMinor')
    if stored_minor is not None:
        if isinstance(stored_minor, bool):
            raise ValueError('Package has no authoritative payable price.')
        try:
            minor = int(stored_minor)
        except (TypeError, ValueError):
            raise ValueError('Package has no authoritative payable price.')
        if minor <= 0 or str((snapshot or {}).get('currency') or '').upper() != 'MYR':
            raise ValueError('Package has no supported authoritative currency.')
        return minor
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


def prepare_package_snapshot(package, operator, quantity=1, now=None,
                             participants=None, departure_date=None):
    if not eligible_package(package):
        raise ValueError('Package is not approved and available for checkout.')
    if not package.get('operatorId') or not operator:
        raise ValueError('Package operator could not be verified.')
    currency = str(package.get('currency') or '').upper()
    if currency != 'MYR':
        raise ValueError('Package has no supported authoritative currency.')
    if package.get('taxIncluded') is None and not package.get('taxNotes'):
        raise ValueError('Package tax and fee treatment is not established.')
    if _integer_count(quantity, 'Package quantity') != 1:
        raise ValueError('Package quantity is not supported by the current contract.')
    group = _participants(package, participants)
    price_basis = str(package.get('priceBasis') or 'per_person').strip().lower()
    if price_basis not in {'per_person', 'per_group'}:
        raise ValueError('Package price basis is not supported for checkout.')
    adult_price = _money(package.get('adultPrice', package.get('price')), 'adult price')
    child_raw = package.get('childPrice')
    child_price = None if child_raw in (None, '') else _money(child_raw, 'child price')
    if adult_price <= 0:
        raise ValueError('Package has no authoritative payable price.')
    if price_basis == 'per_person':
        if group['children'] and child_price is None:
            raise ValueError('Child pricing is not defined for this package.')
        total = adult_price * group['adults'] + (child_price or Decimal('0')) * group['children']
    else:
        total = adult_price
    if total <= 0:
        raise ValueError('Package has no authoritative payable price.')
    selected_departure = _departure_date(package, departure_date)
    return {
        'contractVersion': 2,
        'packageId': str(package.get('id') or ''), 'operatorId': str(package['operatorId']),
        'title': package.get('title') or package.get('packageTitle'),
        'destination': package.get('destination') or package.get('destinationName'),
        'durationDays': package.get('durationDays'), 'departureDates': deepcopy(package.get('departureDates') or []),
        'selectedDepartureDate': selected_departure,
        'itineraryDays': deepcopy(package.get('itineraryDays') or []),
        'inclusions': deepcopy(package.get('inclusions') or []), 'exclusions': deepcopy(package.get('exclusions') or []),
        'accommodation': {k: package.get(k) for k in ('accommodationName', 'accommodationCategory', 'roomType', 'accommodationNotes')},
        'transport': {k: package.get(k) for k in ('transportTypes', 'transportNotes')},
        'priceBasis': price_basis,
        'adultUnitPrice': _json_money(adult_price),
        'childUnitPrice': None if child_price is None else _json_money(child_price),
        'participants': group, 'groupSize': group['total'],
        'price': _json_money(total), 'amountMinor': int(total * 100),
        'currency': currency, 'taxIncluded': package.get('taxIncluded'), 'taxNotes': package.get('taxNotes'),
        'revision': package.get('updatedAt') or package.get('createdAt'),
        'snapshotCreatedAt': now or datetime.now(timezone.utc).isoformat(),
    }


def create_package_attempt(claim, traveller_id, package, operator, idempotency_key,
                           intended_trip=None, quantity=1, now=None,
                           participants=None, departure_date=None):
    """Atomically claim a future-payment attempt; never creates a checkout session."""
    if not idempotency_key:
        raise ValueError('An idempotency key is required.')
    if intended_trip is not None and intended_trip.get('travellerId') != traveller_id:
        raise ValueError('The intended trip is not owned by this traveller.')
    snapshot = prepare_package_snapshot(
        package, operator, quantity, now, participants, departure_date
    )
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
        'participants': snapshot['participants'], 'groupSize': snapshot['groupSize'],
        'selectedDepartureDate': snapshot['selectedDepartureDate'],
        'fulfillmentMode': 'independent_package_trip',
        'checkoutStatus': 'checkout_pending', 'paymentStatus': 'payment_pending',
        'fulfillmentStatus': 'fulfillment_pending', 'createdAt': snapshot['snapshotCreatedAt'],
        'updatedAt': snapshot['snapshotCreatedAt'],
    }
    existing, created = claim('package_checkout_attempts', attempt_id, record)
    if not created and any(existing.get(field) != record.get(field) for field in (
            'packageId', 'packageRevision', 'participants', 'selectedDepartureDate',
            'fulfillmentMode')):
        raise ValueError('Idempotency key is already bound to another package checkout.')
    return existing, created
