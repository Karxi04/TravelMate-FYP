"""FR05 adapter: caller must gate this behind the default-disabled server flag."""
from copy import deepcopy

from services.activity_pricing import activity_pricing
from services.budget_aware_selection import select_budget_aware_activities


def generate_with_budget_selection(working, forecast, locations):
    result = select_budget_aware_activities(working['activities'], working, forecast)
    generated = result['scheduledItinerary']
    generated['updatedAt'] = working.get('updatedAt')
    generated['generationContext']['locationTravelData'] = locations
    for item in generated['activities']:
        if item.get('selectionPriceStatus') == 'unresolved':
            evidence = deepcopy(item.get('pricingEvidence'))
            evidence = evidence if isinstance(evidence, dict) else {}
            if evidence.get('applicability') not in {'conditional', 'unverified'}:
                evidence['applicability'] = 'unverified'
            evidence['qualification'] = 'No applicable verified price was established during selection.'
            item['pricingEvidence'] = evidence
    # Keep legacy numeric estimates readable; nullable applicable costs live separately.
    for day in generated['dailySchedule']:
        if day.get('estimatedCost') is None:
            day['applicableActivityCost'] = None
            day['costCompletenessStatus'] = 'incomplete'
            day['estimatedCost'] = round(sum(activity_pricing(
                item, working['travellerCount'])['effectiveCost'] for item in day['activities']), 2)
    generated['budgetAwareSelection'] = {
        'enabled': True, 'applied': True,
        **{key: deepcopy(value) for key, value in result.items() if key not in {
            'offlineOnly', 'scheduledItinerary', 'selectedActivities', 'schedule',
        }},
    }
    return generated


def qualify_selection_budget(budget, selection):
    """Add uncertainty to shared accounting, never replace amounts or invent savings."""
    if 'activities' not in selection['budget']['unresolvedExpenseCategories']:
        return budget
    budget = deepcopy(budget)
    budget['pendingExpenseCategories'] = list(dict.fromkeys(budget['pendingExpenseCategories'] + ['activities']))
    budget['incomplete'] = True
    budget['completenessStatus'] = 'incomplete'
    if budget['affordabilityStatus'] != 'over_budget':
        budget['affordabilityStatus'] = budget['status'] = 'incomplete'
    expense = budget['expenseBreakdown']['activities']
    expense['state'] = 'unit_unknown' if expense['state'] == 'unit_unknown' else 'unverified_estimate'
    expense['pricingIssues'] = sorted(set(expense['pricingIssues'] + ['budget_selection_unresolved_prices']))
    note = 'Activity selection includes or defers unresolved admission prices; numeric legacy estimates are not verified admission totals or savings.'
    budget['estimateLimitations'] = list(dict.fromkeys(budget['estimateLimitations'] + [note]))
    budget['attention'] = budget.get('attention') or note
    return budget
