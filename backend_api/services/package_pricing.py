"""Single server-owned MYR package pricing contract, shared by display and checkout."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from services.campaign_schedule import malaysia_today, campaign_package_ids

MAX_GROUP_PARTICIPANTS = 50

def _integer_count(value, label):
    if isinstance(value, bool):
        raise ValueError(f'{label} must be a non-negative integer.')
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'{label} must be a non-negative integer.')
    if not number.is_finite() or number < 0 or number != number.to_integral_value():
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


def calculate_package_pricing(package, participants=None, campaigns=None, promo_code='', now=None):
    from services.public_content_projection import active_campaign
    group = _participants(package, participants)
    if str(package.get('currency') or '').upper() != 'MYR':
        raise ValueError('Package has no supported authoritative currency.')
    basis = package.get('priceBasis')
    if basis not in {'per_person', 'per_group'}:
        raise ValueError('Package has no verified price basis for checkout.')
    adult = _money(package.get('adultPrice', package.get('price')), 'adult price')
    child = None if package.get('childPrice') in (None, '') else _money(package['childPrice'], 'child price')
    if adult <= 0: raise ValueError('Package has no authoritative payable price.')
    if basis == 'per_person' and group['children'] and child is None:
        raise ValueError('Child pricing is not defined for this package.')
    subtotal = adult if basis == 'per_group' else adult * group['adults'] + (child or Decimal(0)) * group['children']
    total, promotion = subtotal, {}
    supplied = str(promo_code or '').strip().upper()
    matched_code = not supplied
    for campaign in sorted(campaigns or [], key=lambda c: str(c.get('id') or '')):
        if (str(package.get('id') or '') not in campaign_package_ids(campaign)
                or not package.get('operatorId') or campaign.get('operatorId') != package['operatorId']
                or not active_campaign(campaign, malaysia_today(now))):
            continue
        required = str(campaign.get('promoCode') or '').strip().upper()
        if required and required != supplied: continue
        # Unknown structured conditions cannot silently become unconditional discounts.
        if any(campaign.get(k) not in (None, '', [], {}) for k in ('eligibilityConditions', 'usageLimit', 'quantityLimit')):
            continue
        try:
            value = Decimal(str(campaign.get('discountValue')))
            kind = campaign.get('discountType')
            if isinstance(campaign.get('discountValue'), bool) or not value.is_finite() or value <= 0 or kind not in {'percentage', 'fixed'}: continue
            if kind == 'percentage' and value > 100: continue
            discount = min(subtotal, (subtotal * value / 100 if kind == 'percentage' else value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
        except (InvalidOperation, TypeError, ValueError): continue
        if required and required == supplied: matched_code = True
        payable = subtotal - discount
        if payable < total:
            total = payable
            promotion = {k: campaign.get(k, '') for k in ('id', 'campaignTitle', 'discountType', 'discountValue', 'startDate', 'endDate', 'termsConditions')}
            promotion.update(source='campaign', promoCode=required)
    if not matched_code: raise ValueError('Promo code is not valid for this package and date.')
    if total <= 0:
        raise ValueError('This promotion leaves no positive payable amount. Free package checkout is not supported; contact the operator.')
    result = {'pricingVersion': 'campaigns_v1', 'priceBasis': basis, 'participants': group,
        'regularAdultUnitPrice': _json_money(adult), 'childUnitPrice': None if child is None else _json_money(child),
        'originalSubtotal': _json_money(subtotal), 'promotionDiscount': _json_money(subtotal-total),
        'finalPayable': _json_money(total), 'amountMinor': int(total*100), 'currency': 'MYR',
        'promotion': promotion, 'taxIncluded': package.get('taxIncluded'), 'taxNotes': package.get('taxNotes'),
        'stackingPolicy': 'best_single_offer'}
    return result


def pricing_fingerprint(snapshot):
    keys = ('pricingBreakdown', 'participants', 'priceBasis', 'selectedDepartureDate', 'packageId', 'operatorId', 'taxIncluded', 'taxNotes')
    return hashlib.sha256(json.dumps({k: snapshot.get(k) for k in keys}, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def public_package_pricing(package, campaigns):
    """Precompute dated offer amounts; clients select dates without a second money engine."""
    from services.public_content_projection import campaign_publication_eligible
    group = {'adults': max(1, int(package.get('minimumTravellers') or 1)), 'children': 0}
    base = calculate_package_pricing(package, group, [])
    offers = []
    for campaign in campaigns or []:
        if not campaign_publication_eligible(campaign) or str(campaign.get('promoCode') or '').strip(): continue
        try:
            offer = calculate_package_pricing(package, group, [campaign], now=campaign.get('startDate'))
            if offer['promotionDiscount'] > 0: offers.append(offer)
        except (TypeError, ValueError): continue
    return {'base': base, 'offers': offers}
