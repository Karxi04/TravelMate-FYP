"""Server-owned package checkout preparation; Stripe activation is deliberately separate."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import re

from services.public_content_projection import eligible_package, active_campaign
from services.campaign_schedule import malaysia_today
from services.operator_hotel_service import safe_hotel_snapshot, safe_room_snapshot

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
    if not amount.is_finite() or amount < 0:
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
    - A supplied instant is evaluated on the Malaysia calendar; date-only values stay dates.
    - Otherwise, default to the current calendar date in Malaysia Standard Time (UTC+8).
    """
    try:
        return malaysia_today(now)
    except (ValueError, TypeError):
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
    if not promo_price.is_finite() or promo_price <= 0:
        return False

    regular_raw = package.get('adultPrice', package.get('price'))
    if regular_raw not in (None, ''):
        try:
            regular_price = Decimal(str(regular_raw)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if not regular_price.is_finite() or promo_price >= regular_price:
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
                             participants=None, departure_date=None, campaigns=None, promo_code=''):
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

    subtotal = (regular_adult_price * group['adults'] + (child_price or Decimal('0')) * group['children']
                if price_basis == 'per_person' else regular_adult_price)
    promotion = {'source': 'package_price'} if total < subtotal else {}
    supplied_code = str(promo_code or '').strip().upper()
    matched_code = not supplied_code
    # One best discount on the original subtotal; never stack with brochure pricing.
    for campaign in sorted(campaigns or [], key=lambda c: str(c.get('id') or '')):
        if (str(campaign.get('packageId') or '') != str(package.get('id') or '') or
                campaign.get('operatorId') != package['operatorId'] or
                not active_campaign(campaign, malaysia_today(now))):
            continue
        required_code = str(campaign.get('promoCode') or '').strip().upper()
        if required_code and required_code != supplied_code:
            continue
        try:
            value = Decimal(str(campaign.get('discountValue')))
            kind = campaign.get('discountType')
            if not value.is_finite() or value <= 0 or kind not in {'percentage', 'fixed'}:
                continue
            if kind == 'percentage' and value > 100:
                continue
            discount = (subtotal * value / 100 if kind == 'percentage' else value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            payable = subtotal - discount
        except (InvalidOperation, ValueError, TypeError):
            continue
        if payable <= 0:
            raise ValueError('This promotion leaves no positive payable amount. Free package checkout is not supported; contact the operator.')
        if required_code == supplied_code:
            matched_code = True
        if payable < total:
            total = payable
            effective_adult_price = regular_adult_price
            promotional_price = None
            promotion = {k: campaign.get(k) for k in ('id', 'campaignTitle', 'discountType', 'discountValue')}
            promotion.update(source='campaign', promoCode=required_code)
    if not matched_code:
        raise ValueError('Promo code is not valid for this package and date.')
    breakdown = {'originalSubtotal': _json_money(subtotal), 'promotionDiscount': _json_money(subtotal - total),
                 'finalPayable': _json_money(total), 'currency': currency, 'promotion': promotion}
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
    accommodation_hotel = safe_hotel_snapshot(package.get('accommodationHotel'))
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
        **({'inclusions': deepcopy(package['inclusions'])} if 'inclusions' in package else {}),
        'exclusions': deepcopy(package.get('exclusions') or []),
        **{key: package[key] for key in ('accommodationIncluded', 'transportIncluded', 'guideActivitiesIncluded') if key in package},
        **({'accommodation': {
            **{k: package.get(k) for k in ('accommodationName', 'accommodationCategory', 'roomType', 'accommodationNotes')},
            **({'accommodationHotel': deepcopy(accommodation_hotel)} if accommodation_hotel is not None else {}),
            **({'accommodationRoom': safe_room_snapshot(package['accommodationRoom'], (accommodation_hotel or {}).get('hotelId'))} if package.get('accommodationRoom') else {}),
        }} if any(k in package for k in ('accommodationName', 'accommodationCategory', 'roomType', 'accommodationNotes', 'accommodationHotel')) else {}),
        **({'transport': {k: package.get(k) for k in ('transportTypes', 'transportNotes')}} if any(k in package for k in ('transportTypes', 'transportNotes')) else {}),
        'priceBasis': price_basis,
        'regularAdultUnitPrice': _json_money(regular_adult_price),
        'adultUnitPrice': _json_money(effective_adult_price),
        'childUnitPrice': None if child_price is None else _json_money(child_price),
        'isPromotionEligible': bool(promotion),
        'promotionalUnitPrice': _json_money(promotional_price) if promotional_price is not None else None,
        'originalPrice': _json_money(original_price) if original_price is not None else None,
        'participants': group, 'groupSize': group['total'],
        'pricingBreakdown': breakdown,
        'requestedPromoCode': supplied_code,
        'price': _json_money(total), 'amountMinor': int(total * 100),
        'currency': currency, 'taxIncluded': package.get('taxIncluded'), 'taxNotes': package.get('taxNotes'),
        'revision': package.get('updatedAt') or package.get('createdAt'),
        'snapshotCreatedAt': now or datetime.now(timezone.utc).isoformat(),
    }


def create_package_attempt(claim, traveller_id, package, operator, idempotency_key,
                           intended_trip=None, quantity=1, now=None,
                           participants=None, departure_date=None, campaigns=None, promo_code=''):
    """Atomically claim a future-payment attempt; never creates a checkout session."""
    if not idempotency_key:
        raise ValueError('An idempotency key is required.')
    if intended_trip is not None and intended_trip.get('travellerId') != traveller_id:
        raise ValueError('The intended trip is not owned by this traveller.')
    snapshot = prepare_package_snapshot(
        package, operator, quantity, now, participants, departure_date, campaigns, promo_code
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
        'promoCode': str(promo_code or '').strip().upper(),
        'pricingBreakdown': snapshot['pricingBreakdown'],
        'selectedDepartureDate': snapshot['selectedDepartureDate'],
        'fulfillmentMode': 'independent_package_trip',
        'checkoutStatus': 'checkout_pending', 'paymentStatus': 'payment_pending',
        'fulfillmentStatus': 'fulfillment_pending', 'createdAt': snapshot['snapshotCreatedAt'],
        'updatedAt': snapshot['snapshotCreatedAt'],
    }
    existing, created = claim('package_checkout_attempts', attempt_id, record)
    if not created and (any(existing.get(field) != record.get(field) for field in (
            'packageId', 'packageRevision', 'participants', 'selectedDepartureDate',
            'fulfillmentMode')) or str(existing.get('promoCode') or '') != record['promoCode']):
        raise ValueError('Idempotency key is already bound to another package checkout.')
    return existing, created


def derive_required_services(snapshot):
    """
    Dynamically determine required supplier services from package snapshot.
    Only explicit brochure commitments require supplier arrangements. Days,
    nights and itinerary activities alone are not evidence of a reservation.
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

    absent = r'^(none|no|n/?a|not included|not applicable)$'
    accom_required = bool(accom_name and not re.fullmatch(absent, accom_name, re.I))

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

    # 3. Guide & Activities
    inclusions = snapshot.get('inclusions') or []
    if isinstance(inclusions, str):
        inclusions = [i.strip() for i in inclusions.split('\n') if i.strip()]
    elif not isinstance(inclusions, list):
        inclusions = []
    itinerary_days = snapshot.get('itineraryDays') or []

    exclusions = snapshot.get('exclusions') or []
    if isinstance(exclusions, str):
        exclusions = exclusions.splitlines()
    # Negative or self-arranged wording must not become an included service.
    def promised(text):
        return not re.search(r'\b(no|not included|excluded|own|optional|suggested|suggestions?|self[- ]guided|self[- ]drive|public transport(?:ation)?)\b', text, re.I)

    accom_required = accom_required and promised(accom_name)

    clauses = [part.strip() for item in inclusions
               for part in re.split(r'[.;,]|\b(?:and|but)\b', str(item), flags=re.I) if part.strip()]
    included = [part for part in clauses if promised(part)]
    excluded = ' '.join(str(i) for i in exclusions) if isinstance(exclusions, list) else ''
    patterns = {
        'accommodation': r'\b(accommodation|hotel|resort|homestay|apartment|entire (house|property)|lodging|overnight stay)\b',
        'transport': r'\b(transport|transfer|shuttle|chartered|private (van|bus|car))\b',
        'guideActivities': r'\b(guide|guided|docent|escort|tickets?|admission|entrance fee|park pass|paid activit(?:y|ies)|reserved activit(?:y|ies))\b',
    }
    positive = {key: any(re.search(pattern, text, re.I) for text in included)
                for key, pattern in patterns.items()}
    positive['guideActivities'] = any(re.search(patterns['guideActivities'], text, re.I) and not
        (re.search(r'\bfree\b', text, re.I) and not re.search(r'\b(reserved|guide|guided|docent|escort)\b', text, re.I)) for text in included)
    negative = {key: bool(re.search(pattern, excluded, re.I)) for key, pattern in patterns.items()}
    for key, pattern in patterns.items():
        negative[key] |= any(re.search(pattern, text, re.I) and
                             re.search(r'\b(no|not included|excluded)\b', text, re.I) for text in clauses)
    if positive['guideActivities'] and negative['guideActivities']:
        excluded_clauses = [excluded] + [text for text in clauses if re.search(r'\b(no|not included|excluded)\b', text, re.I)]
        subtypes = [r'\b(guide|guided|docent|escort)\b', r'\b(tickets?|admission|entrance fee|park pass)\b', r'\bactivit(?:y|ies)\b']
        negative['guideActivities'] = any(any(re.search(p, text, re.I) for text in included) and
                                           any(re.search(p, text, re.I) for text in excluded_clauses) for p in subtypes)
    transport_required = (any(promised(str(t)) and not re.fullmatch(absent, str(t).strip(), re.I)
                              and not re.search(r'\b(walk|walking|public)\b', str(t), re.I)
                              for t in types) or positive['transport'])
    accom_required = accom_required or positive['accommodation']
    guide_required = positive['guideActivities']
    # Resolve each component independently, always from the purchased snapshot.
    known_inclusions = isinstance(snapshot.get('inclusions'), (list, str))
    legacy_required = {'accommodation': accom_required, 'transport': transport_required,
                       'guideActivities': guide_required}
    known_structure = {
        'accommodation': isinstance(snapshot.get('accommodation'), dict) or 'accommodationName' in snapshot,
        'transport': isinstance(snapshot.get('transport'), dict) or 'transportTypes' in snapshot,
        'guideActivities': known_inclusions,
    }
    states = {}
    for key in patterns:
        explicit = snapshot.get(key + 'Included')
        required = legacy_required[key]
        # Property discovery alone does not establish a promised stay.
        selected_property_only = (key == 'accommodation' and
                                  (accom.get('accommodationHotel') or snapshot.get('accommodationHotel'))
                                  and not positive[key])
        if isinstance(explicit, bool):
            uncertain = (explicit and negative[key]) or (not explicit and positive[key])
            required = explicit
        else:
            uncertain = ((required and negative[key]) or selected_property_only or
                         not (required or negative[key] or (known_inclusions and known_structure[key])))
            if key + 'Included' in snapshot:
                uncertain = True
            if key == 'transport' and t_notes and not types and not positive[key] and not negative[key]:
                uncertain = True
        states[key] = {'required': bool(required and not uncertain), 'uncertain': bool(uncertain),
                       'reviewReason': ('Purchased inclusion and exclusion information conflicts.' if
                                        ((required and negative[key]) or (explicit is False and positive[key])) else
                                        'Purchased snapshot does not establish whether this component is included.') if uncertain else ''}

    return {
        'accommodation': {
            **states['accommodation'],
            'brochureName': accom_name,
            'brochureRoomType': room_type,
            'brochureCategory': category,
            'brochureNotes': notes,
        },
        'transport': {
            **states['transport'],
            'brochureTypes': [str(t) for t in types],
            'brochureNotes': t_notes,
        },
        'guideActivities': {
            **states['guideActivities'],
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
                'providerName': '',
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


def fulfillment_readiness(order, requirements, record, paid):
    """Explain the same attestation conditions enforced by the readiness action."""
    labels = {'accommodation': 'Accommodation', 'transport': 'Transportation', 'guideActivities': 'Guide / Activities'}
    blockers, components = [], []
    if not paid:
        blockers.append('Awaiting traveller payment.')
    state = order.get('fulfillmentStatus')
    if state == 'fulfillment_declined':
        blockers.append('Unable to Fulfil has been recorded; readiness cannot be changed here.')
    elif state == 'fulfilled':
        blockers.append('This legacy fulfilled order requires review before arrangements can be changed.')
    if set(requirements) != set(labels):
        blockers.append('Purchased service requirements are unavailable; review is required.')
    for key, meta in requirements.items():
        label = labels.get(key, key)
        service = (record.get('services') or {}).get(key) or {}
        missing = []
        if meta.get('uncertain'):
            missing.append(f"{label}: {meta.get('reviewReason') or 'Purchased brochure requires review.'}")
        if meta.get('required'):
            if not str(service.get('reference') or '').strip():
                missing.append(f'{label} booking reference is missing.')
            if key == 'transport' and not str(service.get('providerName') or '').strip():
                missing.append('Actual transport provider / fleet is missing.')
            if (service.get('status') != 'confirmed' or service.get('provenance') != 'operator_attested'
                    or not service.get('confirmedBy') or not service.get('confirmedAt')):
                missing.append(f'{label} arrangements have not been attested by the operator.')
        blockers.extend(missing)
        components.append({'key': key, 'label': label, 'required': bool(meta.get('required')),
                           'complete': not missing, 'uncertain': bool(meta.get('uncertain')), 'missing': missing})
    already_ready = state == 'trip_ready'
    if already_ready:
        blockers = ['Already Ready for Traveller.' if all(c['complete'] for c in components) else 'Already Ready for Traveller. Some historical supplier details are incomplete; records have been preserved.']
    return {'canMarkReady': not blockers and not already_ready, 'blockers': blockers,
            'requirementsReliable': set(requirements) == set(labels) and not any(meta.get('uncertain') for meta in requirements.values()),
            'components': components, 'requiredCount': sum(c['required'] for c in components),
            'completedCount': sum(c['required'] and c['complete'] for c in components)}

