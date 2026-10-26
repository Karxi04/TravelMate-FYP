"""Optional MYR planning estimates; never infer units for historical amounts."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from math import isfinite
from copy import deepcopy


PRICING_FIELDS = (
    'pricingUnit', 'unitPrice', 'costCategory', 'costProvenance',
    'priceSourceUrl', 'priceVerifiedAt', 'overlapsAllowance', 'pricingEvidence',
)
PRICING_UNITS = {'per_person', 'per_group', 'already_aggregated'}
PROVENANCE = {'verified_ticket', 'catalog_estimate', 'user_entered'}


def pricing_snapshot(activity):
    # effectiveCost is derived, never an input to subsequent calculations.
    return {key: deepcopy(activity[key]) for key in PRICING_FIELDS if key in activity}


def traveller_count(value):
    try:
        count = Decimal(str(value))
        if count.is_finite() and count >= 1 and count == count.to_integral_value():
            return int(count)
    except (InvalidOperation, TypeError, ValueError):
        pass
    return 1


def _money(value):
    try:
        amount = Decimal(str(value))
        if amount.is_finite() and amount >= 0:
            return amount
    except (InvalidOperation, TypeError, ValueError):
        pass
    return None


def activity_pricing(activity, travellers=1):
    unit = str(activity.get('pricingUnit') or 'unknown')
    if unit not in PRICING_UNITS:
        unit = 'unknown'
    provenance = str(activity.get('costProvenance') or 'unverified')
    if provenance not in PROVENANCE:
        provenance = 'unverified'
    raw = _money(activity.get('estimatedCost'))
    price = raw
    if unit in {'per_person', 'per_group'} and 'unitPrice' in activity:
        price = _money(activity['unitPrice'])
    issues = []
    evidence = activity.get('pricingEvidence')
    if isinstance(evidence, dict) and evidence.get('applicability') != 'applicable':
        issues.append('conditional_or_unverified_admission')
    if unit == 'unknown':
        issues.append('unknown_pricing_unit')
    if price is None:
        issues.append('invalid_or_missing_price')
    if provenance == 'unverified':
        issues.append('unverified_price')
    # A provenance label alone is not evidence of free admission.
    if price == 0 and not (
        provenance == 'verified_ticket'
        and activity.get('priceSourceUrl') and activity.get('priceVerifiedAt')
    ):
        issues.append('unverified_zero_price')
    if unit == 'per_person' and _money(travellers) != Decimal(traveller_count(travellers)):
        issues.append('invalid_traveller_count')
    amount = price if price is not None else (raw or Decimal(0))
    if unit == 'per_person' and price is not None:
        amount *= traveller_count(travellers)
    try:
        effective = float(amount if unit == 'unknown' else amount.quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP))
        if not isfinite(effective):
            raise InvalidOperation
    except InvalidOperation:
        effective = 0.0
        issues.append('invalid_or_missing_price')
    overlap = activity.get('overlapsAllowance') is True or (
        str(activity.get('costCategory') or '') in {'food', 'transport', 'spending_allowance'}
        and effective > 0
    )
    return {
        'effectiveCost': effective,
        'pricingUnit': unit,
        'costProvenance': provenance,
        'pricingIssues': list(dict.fromkeys(issues)),
        'overlapsAllowance': overlap,
    }


def refresh_activity_costs(itinerary):
    """Refresh derived costs without rearranging or repricing stored raw activities."""
    count = itinerary.get('travellerCount', 1)
    activities = [dict(item) for item in itinerary.get('activities', [])]
    for item in activities:
        if item.get('pricingUnit'):
            item['effectiveCost'] = activity_pricing(item, count)['effectiveCost']
    patch = {'activities': activities}
    if 'dailySchedule' in itinerary:
        by_id = {item.get('activityId'): item for item in activities if item.get('activityId')}
        daily = []
        for day in itinerary.get('dailySchedule') or []:
            items = [dict(by_id.get(item.get('activityId'), item))
                     for item in day.get('activities', [])]
            daily.append({**day, 'activities': items, 'estimatedCost': round(sum(
                activity_pricing(item, count)['effectiveCost'] for item in items), 2)})
        patch['dailySchedule'] = daily
    return patch
