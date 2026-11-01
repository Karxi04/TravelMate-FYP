"""Server-owned package checkout preparation; Stripe activation is deliberately separate."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib

from services.public_content_projection import eligible_package

PACKAGE_FULFILLMENT_STATES = {
    'checkout_pending', 'payment_pending', 'payment_verified',
    'fulfillment_pending', 'fulfilled', 'fulfillment_failed',
    'payment_failed', 'payment_cancelled',
    'awaiting_operator_fulfillment', 'partially_fulfilled',
    'trip_ready', 'fulfillment_declined',
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


MYT_TIMEZONE = timezone(timedelta(hours=8))


def _parse_iso_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    if 'T' in text:
        text = text.split('T')[0]
    elif ' ' in text:
        text = text.split(' ')[0]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _resolve_reference_date(now=None):
    """
    Authoritative promotion date evaluation:
    - If now is supplied as a date, datetime or ISO string, its date is used.
    - Otherwise, default to the current calendar date in Malaysia Standard Time (UTC+8).
    """
    if now is not None:
        parsed = _parse_iso_date(now)
        if parsed:
            return parsed
    return datetime.now(MYT_TIMEZONE).date()


def is_package_promotion_active(package, now_ref=None):
    """
    Check whether a promotional discount applies to the package.
    Documented semantics:
    - Package must define a positive promotionalPrice.
    - Promotional price must be strictly less than the regular price.
    - At least one promotion boundary date (promotionStart or promotionEnd) must be configured.
    - If promotionStart is configured, evaluation date >= promotionStart.
    - If promotionEnd is configured, evaluation date <= promotionEnd.
    - Promotion date boundaries are evaluated in Malaysia Standard Time (UTC+8) by default.
    """
    if not package or not isinstance(package, dict):
        return False
    promo_raw = package.get('promotionalPrice')
    if promo_raw in (None, ''):
        return False
    try:
        promo_price = Decimal(str(promo_raw)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return False
    if promo_price <= 0:
        return False

    regular_raw = package.get('adultPrice', package.get('price'))
    if regular_raw not in (None, ''):
        try:
            regular_price = Decimal(str(regular_raw)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if promo_price >= regular_price:
                return False
        except (InvalidOperation, TypeError, ValueError):
            return False

    start_date = _parse_iso_date(package.get('promotionStart'))
    end_date = _parse_iso_date(package.get('promotionEnd'))

    if not start_date and not end_date:
        return False
    if start_date and end_date and start_date > end_date:
        return False

    ref_date = _resolve_reference_date(now_ref)
    if start_date and ref_date < start_date:
        return False
    if end_date and ref_date > end_date:
        return False

    return True


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
    raw_basis = package.get('priceBasis')
    if not raw_basis or str(raw_basis).strip().lower() not in {'per_person', 'per_group'}:
        raise ValueError('Package has no verified price basis for checkout.')
    price_basis = str(raw_basis).strip().lower()

    regular_adult_price = _money(package.get('adultPrice', package.get('price')), 'adult price')
    child_raw = package.get('childPrice')
    child_price = None if child_raw in (None, '') else _money(child_raw, 'child price')
    if regular_adult_price <= 0:
        raise ValueError('Package has no authoritative payable price.')

    is_promo_active = is_package_promotion_active(package, now_ref=now)
    promo_raw = package.get('promotionalPrice')
    promotional_price = None
    if is_promo_active and promo_raw not in (None, ''):
        promotional_price = _money(promo_raw, 'promotional price')

    effective_adult_price = regular_adult_price
    if price_basis == 'per_person':
        if is_promo_active and promotional_price is not None:
            effective_adult_price = promotional_price
        if group['children'] and child_price is None:
            raise ValueError('Child pricing is not defined for this package.')
        total = effective_adult_price * group['adults'] + (child_price or Decimal('0')) * group['children']
    else:  # per_group
        if is_promo_active and promotional_price is not None:
            total = promotional_price
        else:
            total = regular_adult_price

    if total <= 0:
        raise ValueError('Package has no authoritative payable price.')

    original_raw = package.get('originalPrice')
    original_price = None
    if original_raw not in (None, ''):
        try:
            original_price = _money(original_raw, 'original price')
        except ValueError:
            original_price = None

    selected_departure = _departure_date(package, departure_date)
    return {
        'contractVersion': 2,
        'packageId': str(package.get('id') or ''), 'operatorId': str(package['operatorId']),
        'title': package.get('title') or package.get('packageTitle'),
        'destination': package.get('destination') or package.get('destinationName'),
        'durationDays': package.get('durationDays'),
        'durationNights': package.get('durationNights'),
        'departureDates': deepcopy(package.get('departureDates') or []),
        'selectedDepartureDate': selected_departure,
        'itineraryDays': deepcopy(package.get('itineraryDays') or []),
        'inclusions': deepcopy(package.get('inclusions') or []), 'exclusions': deepcopy(package.get('exclusions') or []),
        'accommodation': {k: package.get(k) for k in ('accommodationName', 'accommodationCategory', 'roomType', 'accommodationNotes')},
        'transport': {k: package.get(k) for k in ('transportTypes', 'transportNotes')},
        'priceBasis': price_basis,
        'regularAdultUnitPrice': _json_money(regular_adult_price),
        'adultUnitPrice': _json_money(effective_adult_price),
        'childUnitPrice': None if child_price is None else _json_money(child_price),
        'isPromotionEligible': is_promo_active,
        'promotionalUnitPrice': _json_money(promotional_price) if promotional_price is not None else None,
        'originalPrice': _json_money(original_price) if original_price is not None else None,
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


def derive_required_services(snapshot):
    """
    Dynamically determine required supplier services from package snapshot.
    - Accommodation: durationNights > 0 or durationDays > 1 or hotel named/configured in brochure.
    - Transport: transit modes or transport notes configured in brochure.
    - Guide / Activities: guide/docent in inclusions, tickets/activities in inclusions or itinerary.
    """
    if not isinstance(snapshot, dict):
        snapshot = {}

    # 1. Accommodation
    accom = snapshot.get('accommodation') or {}
    if not isinstance(accom, dict):
        accom = {}
    accom_name = str(accom.get('accommodationName') or snapshot.get('accommodationName') or '').strip()
    room_type = str(accom.get('roomType') or snapshot.get('roomType') or '').strip()
    category = str(accom.get('accommodationCategory') or snapshot.get('accommodationCategory') or '').strip()
    notes = str(accom.get('accommodationNotes') or snapshot.get('accommodationNotes') or '').strip()

    nights_raw = snapshot.get('durationNights')
    try:
        nights = int(nights_raw) if nights_raw is not None else None
    except (TypeError, ValueError):
        nights = None

    days_raw = snapshot.get('durationDays')
    try:
        days = int(days_raw) if days_raw is not None else None
    except (TypeError, ValueError):
        days = None

    accom_required = False
    if nights is not None and nights > 0:
        accom_required = True
    elif nights is None and days is not None and days > 1:
        accom_required = True
    elif bool(accom_name):
        accom_required = True

    # 2. Transportation
    transport = snapshot.get('transport') or {}
    if not isinstance(transport, dict):
        transport = {}
    types = transport.get('transportTypes') or snapshot.get('transportTypes') or []
    if isinstance(types, str):
        types = [t.strip() for t in types.split(',') if t.strip()]
    elif not isinstance(types, list):
        types = []
    t_notes = str(transport.get('transportNotes') or snapshot.get('transportNotes') or '').strip()

    transport_required = bool(types or t_notes)

    # 3. Guide & Activities
    inclusions = snapshot.get('inclusions') or []
    if isinstance(inclusions, str):
        inclusions = [i.strip() for i in inclusions.split('\n') if i.strip()]
    elif not isinstance(inclusions, list):
        inclusions = []
    itinerary_days = snapshot.get('itineraryDays') or []

    guide_keywords = ('guide', 'docent', 'leader', 'escort', 'ticket', 'entrance', 'admission', 'pass', 'tour', 'activity', 'cruise', 'boat')
    has_guide_or_ticket = any(any(k in str(inc).lower() for k in guide_keywords) for inc in inclusions)
    guide_required = bool(has_guide_or_ticket or (bool(inclusions) and len(inclusions) > 0) or bool(itinerary_days))

    return {
        'accommodation': {
            'required': accom_required,
            'brochureName': accom_name,
            'brochureRoomType': room_type,
            'brochureCategory': category,
            'brochureNotes': notes,
        },
        'transport': {
            'required': transport_required,
            'brochureTypes': [str(t) for t in types],
            'brochureNotes': t_notes,
        },
        'guideActivities': {
            'required': guide_required,
            'inclusions': [str(i) for i in inclusions],
            'itineraryDaysCount': len(itinerary_days) if isinstance(itinerary_days, list) else 0,
        },
    }


def build_initial_fulfillment_record(snapshot, now=None):
    """Create the initial embedded fulfillmentRecord for checkout_orders."""
    req = derive_required_services(snapshot)
    timestamp = now or datetime.now(timezone.utc).isoformat()
    return {
        'status': 'awaiting_operator_fulfillment',
        'requiredServices': req,
        'services': {
            'accommodation': {
                'required': req['accommodation']['required'],
                'status': 'unconfirmed' if req['accommodation']['required'] else 'not_required',
                'supplierName': req['accommodation']['brochureName'],
                'reference': '',
                'notes': '',
                'confirmedAt': None,
                'confirmedBy': None,
                'provenance': 'unconfirmed_manual' if req['accommodation']['required'] else 'not_applicable',
            },
            'transport': {
                'required': req['transport']['required'],
                'status': 'unconfirmed' if req['transport']['required'] else 'not_required',
                'providerName': ', '.join(req['transport']['brochureTypes']) if req['transport']['brochureTypes'] else '',
                'reference': '',
                'notes': '',
                'confirmedAt': None,
                'confirmedBy': None,
                'provenance': 'unconfirmed_manual' if req['transport']['required'] else 'not_applicable',
            },
            'guideActivities': {
                'required': req['guideActivities']['required'],
                'status': 'unconfirmed' if req['guideActivities']['required'] else 'not_required',
                'guideOrActivity': ', '.join(req['guideActivities']['inclusions'][:3]) if req['guideActivities']['inclusions'] else '',
                'reference': '',
                'notes': '',
                'confirmedAt': None,
                'confirmedBy': None,
                'provenance': 'unconfirmed_manual' if req['guideActivities']['required'] else 'not_applicable',
            },
        },
        'declineReason': None,
        'declinedAt': None,
        'declinedBy': None,
        'confirmedAt': None,
        'confirmedBy': None,
        'updatedAt': timestamp,
    }

