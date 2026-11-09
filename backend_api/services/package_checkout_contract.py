"""Server-owned package checkout preparation; Stripe activation is deliberately separate."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import re

from services.public_content_projection import eligible_package, active_campaign
from services.campaign_schedule import malaysia_today
from services.package_pricing import (_integer_count, _money, _json_money, calculate_package_pricing, pricing_fingerprint)
from services.operator_hotel_service import safe_hotel_snapshot, safe_room_snapshot

PACKAGE_FULFILLMENT_STATES = {
    'checkout_pending', 'payment_pending', 'payment_verified',
    'fulfillment_pending', 'fulfilled', 'fulfillment_failed',
    'payment_failed', 'payment_cancelled',
    'awaiting_operator_fulfillment', 'partially_fulfilled',
    'trip_ready', 'fulfillment_declined',
}
MAX_GROUP_PARTICIPANTS = 50


def validate_package_departure(package, requested, now=None, allow_default=True):
    available = [str(value).strip() for value in package.get('departureDates') or [] if str(value).strip()]
    requested = str(requested or '').strip()
    if allow_default and not requested and len(available) == 1:
        requested = available[0]
    if available and not requested:
        raise ValueError('Select one of the available package departure dates.')
    if requested and available and requested not in available:
        raise ValueError('The selected package departure date is unavailable.')
    if requested:
        try:
            selected = date.fromisoformat(requested)
            if selected.isoformat()!=requested:raise ValueError
        except ValueError:
            raise ValueError('The selected package departure date is invalid.')
        if selected < malaysia_today(now):
            raise ValueError('The selected departure date has passed in Malaysia. Choose a current or future supported departure.')
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
    breakdown = calculate_package_pricing(package, participants, campaigns, promo_code, now)
    group = breakdown['participants']
    price_basis = breakdown['priceBasis']
    regular_adult_price = Decimal(str(breakdown['regularAdultUnitPrice']))
    effective_adult_price = regular_adult_price
    child_price = None if breakdown['childUnitPrice'] is None else Decimal(str(breakdown['childUnitPrice']))
    promotion = breakdown['promotion']
    total = Decimal(str(breakdown['finalPayable']))
    supplied_code = str(promo_code or '').strip().upper()
    promotional_price = None
    original_price = None

    selected_departure = validate_package_departure(package, departure_date, now)
    accommodation_hotel = safe_hotel_snapshot(package.get('accommodationHotel'))
    snapshot = {
        'contractVersion': 2,
        'pricingVersion': 'campaigns_v1',
        'supplierRequirementVersion': 2,
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
    snapshot['quoteToken'] = pricing_fingerprint(snapshot)
    return snapshot


def create_package_attempt(claim, traveller_id, package, operator, idempotency_key,
                           intended_trip=None, quantity=1, now=None,
                           participants=None, departure_date=None, campaigns=None, promo_code='', expected_quote_token=None):
    """Atomically claim a future-payment attempt; never creates a checkout session."""
    if not idempotency_key:
        raise ValueError('An idempotency key is required.')
    if intended_trip is not None and intended_trip.get('travellerId') != traveller_id:
        raise ValueError('The intended trip is not owned by this traveller.')
    snapshot = prepare_package_snapshot(
        package, operator, quantity, now, participants, departure_date, campaigns, promo_code
    )
    if expected_quote_token and expected_quote_token != snapshot['quoteToken']:
        raise ValueError('Package price or offer terms changed. Refresh and review the current quote.')
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
    if not created and existing.get('paymentStatus') not in {'paid', 'succeeded'} and not existing.get('checkoutOrderId') and existing.get('packageSnapshot', {}).get('quoteToken') != snapshot.get('quoteToken'):
        raise ValueError('Idempotency key has an older quote. Review the current amount with a new checkout attempt.')
    return existing, created


def _guide_exclusion_applies(text, included):
    words = lambda value: set(re.findall(r'[a-z]+',value.lower())) - set(
        'a an the to for of at in and or not no all any other included excluded includes package '
        'standard basic admission admissions ticket tickets guide guided tour tours escort activities '
        'activity services service fee fees optional additional extra separately paid payable charged '
        'mentioned listed specified specifically explicitly this is are be with'.split())
    same_product = any(len(words(text) & words(promise)) >= 2 for promise in included)
    if re.search(r'\b(standard|basic|required)\b',text,re.I) and not re.search(r'not (?:specifically |explicitly )?(?:listed|mentioned|specified)',text,re.I):
        return True
    if re.search(r'not (?:specifically |explicitly )?(?:listed|mentioned|specified)',text,re.I) and not same_product:
        return False
    if re.search(r'\b(optional|additional|extra)\b',text,re.I):
        return same_product and not re.search(r'\b(additional|extra)\b',text,re.I)
    return True


def derive_required_services(snapshot, *, review_optional_extras=False):
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
    # Historical purchases retain their interpretation and authorized clarification workflow.
    review_optional_extras = review_optional_extras or snapshot.get('supplierRequirementVersion') == 2
    guide_excluded = [part.strip() for text in (exclusions if isinstance(exclusions,list) else [])
                      for part in re.split(r'[.;]',str(text)) if part.strip()]
    if review_optional_extras:
        guide_excluded = [text for text in guide_excluded if _guide_exclusion_applies(text,included)]
        negative['guideActivities'] = any(re.search(patterns['guideActivities'],text,re.I) for text in guide_excluded)
    for key, pattern in patterns.items():
        negative[key] |= any(re.search(pattern, text, re.I) and
                             re.search(r'\b(no|not included|excluded)\b', text, re.I) for text in clauses)
    if positive['guideActivities'] and negative['guideActivities']:
        excluded_clauses = (guide_excluded if review_optional_extras else [excluded]) + [text for text in clauses if re.search(r'\b(no|not included|excluded)\b', text, re.I)]
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
                       'conflictingClauses': [text for text in (included if explicit is False else [excluded] + clauses)
                           if re.search(patterns[key], text, re.I)][:8] if uncertain else [],
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


def fulfillment_readiness(order, requirements, record, paid, legacy_reviewed=False, trip_state=None):
    """Explain the same attestation conditions enforced by the readiness action."""
    labels = {'accommodation': 'Accommodation', 'transport': 'Transportation', 'guideActivities': 'Guide / Activities'}
    blockers, components = [], []
    if not paid:
        blockers.append('Awaiting traveller payment.')
    state = order.get('fulfillmentStatus')
    if state == 'fulfillment_declined':
        blockers.append('Unable to Fulfil has been recorded; readiness cannot be changed here.')
    elif state == 'fulfilled' and not legacy_reviewed:
        blockers.append('This legacy fulfilled order requires review before arrangements can be changed.')
    if trip_state is not None and trip_state != 'created':
        blockers.append('The linked Traveller Trip is not available. Recover the paid Package Trip before marking arrangements ready.')
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


def is_paid_order(order):
    payment = str(order.get('paymentStatus') or '').strip().lower()
    status = str(order.get('orderStatus') or order.get('status') or '').strip().lower()
    terminal = {'cancelled', 'checkout_cancelled', 'failed', 'checkout_failed', 'payment_failed',
                'expired', 'checkout_expired', 'refunded', 'partially_refunded', 'rejected'}
    return (payment in {'paid', 'succeeded'} or (not payment and status in {'paid', 'succeeded'})) and status not in terminal

