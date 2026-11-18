"""Preview planning changes from the saved itinerary. Payment and booking data stay outside the patch."""
from math import isfinite

from sequence_contract.domain_functions import calculateBudget, recalculateItinerary
from services.activity_pricing import activity_pricing
from utils import utc_now_iso

_ALLOWANCES = {'foodCost': 'food', 'transportCost': 'transport'}
_SCHEDULE = ('activities', 'dailySchedule', 'unscheduledSuggestions', 'scheduledActivityCount',
             'unscheduledActivityCount', 'provisionalActivityCount', 'totalScheduledMinutes',
             'tripDays', 'paceApplied', 'dailyPlanningWindow', 'tripDateRangeLabel')


def protected_activity(row):
    return (any(row.get(key) for key in (
        'completedAt', 'paidAt', 'paymentId', 'paymentRecordId', 'bookingId',
        'bookingReference', 'hotelBookingId', 'supplierArrangementId', 'checkoutOrderId',
        'paid', 'completed', 'locked', 'packageIncluded', 'required',
    )) or any(str(row.get(key) or '').lower() in {
        'paid', 'succeeded', 'completed', 'booked', 'confirmed', 'settled', 'fulfilled',
    } for key in ('status', 'paymentStatus', 'bookingStatus')))


def _removable(trip):
    activities = trip.get('activities') or []
    # A legacy trip-level payment may not identify a particular visit. Keep the
    # itinerary intact until that link can be established; allowances remain editable.
    if (any(trip.get(key) for key in ('paidTotal', 'paymentId', 'paymentRecordId',
                                      'checkoutOrderId', 'purchasedPackages'))
            or any(row.get('type') == 'actual' and row.get('category') == 'Activities'
                   for row in trip.get('manualExpenses') or [] if isinstance(row, dict))
            or any(protected_activity(row) for row in activities)):
        return []
    return [row for row in activities if row.get('activityId') and row.get('optional') is not False]


def budget_replan_options(trip, budget):
    removable = _removable(trip)
    return {
        'allowances': {field: budget[category] for field, category in _ALLOWANCES.items()},
        'visitRemovalLimited': bool(trip.get('activities')) and not removable,
        'optionalVisits': [
            {'activityId': row['activityId'], 'name': row.get('activityName') or 'Planned visit',
             'dayNo': row.get('dayNo'), 'priceKnown': not activity_pricing(row, trip.get('travellerCount'))['pricingIssues']}
            for row in removable
        ],
    }


def preview_budget_replan(trip, changes):
    if not isinstance(changes, dict) or not changes or set(changes) - {*_ALLOWANCES, 'removeActivityIds'}:
        raise ValueError('Choose allowance changes or optional visits to remove.')
    before = calculateBudget(trip)
    patch = {}
    for field, category in _ALLOWANCES.items():
        if field not in changes:
            continue
        value = changes[field]
        if type(value) not in (int, float) or not 0 <= value <= 1000000 or not isfinite(value) or round(value, 2) != value:
            raise ValueError('Enter a non-negative MYR allowance with at most two decimal places.')
        if value != before[category]:
            patch[field] = value
    ids = changes.get('removeActivityIds', [])
    if not isinstance(ids, list) or len(ids) > 20 or any(not isinstance(value, str) for value in ids):
        raise ValueError('Choose optional visits from this trip.')
    if ids:
        allowed = {row['activityId'] for row in _removable(trip)}
        if not set(ids) <= allowed:
            raise ValueError('Only optional visits that are unpaid and incomplete can be removed.')
        removed = set(ids)
        kept = [row for row in trip.get('activities', []) if row.get('activityId') not in removed]
        # Retain suggestions for later. They must not become new billable visits in this preview.
        planned = recalculateItinerary({**trip, 'activities': kept, 'unscheduledSuggestions': []})
        if {row['activityId'] for row in planned['activities']} != {row['activityId'] for row in kept}:
            raise ValueError('The remaining visits cannot fit safely on their assigned days.')
        patch.update({key: planned[key] for key in _SCHEDULE if key in planned})
        patch['unscheduledSuggestions'] = [row for row in trip.get('unscheduledSuggestions') or []
                                           if row.get('activityId') not in removed]
        patch['unscheduledActivityCount'] = len(patch['unscheduledSuggestions'])
    if not patch:
        raise ValueError('Choose a change before previewing the budget.')
    updated = {**trip, **patch}
    budget = calculateBudget(updated)
    patch.update(budgetEstimate=budget, updatedAt=utc_now_iso())
    return patch, {
        'before': before, 'budget': budget,
        'estimatedReduction': round(before['total'] - budget['total'], 2),
        'retainedEstimate': round(budget['total'] - budget['food'] - budget['transport'], 2),
        'dailySchedule': updated.get('dailySchedule') or [],
        'removedActivityIds': sorted(set(ids)),
    }
