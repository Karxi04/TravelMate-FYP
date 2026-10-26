"""Offline prototype only: score-first greedy selection, not an optimal solver.

Inputs are already normalized activities with unique activityId and unchanged FR04
score (0..100). The pool replaces activities in an offline copy, not a persisted
Trip. No pricing lookup, provider, repository or route handler is invoked.
"""
from copy import deepcopy
from datetime import date
from math import isfinite
from urllib.parse import urlparse

from services.activity_pricing import activity_pricing, traveller_count
from services.malaysian_locality import normalize_destination_scope, validate_candidate
from sequence_contract.domain_functions import calculateBudget, generateItinerary


def _number(value, name):
    if isinstance(value, bool):
        raise ValueError(f'{name} must be a finite non-negative number')
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be a finite non-negative number') from None
    if not isfinite(number) or number < 0:
        raise ValueError(f'{name} must be a finite non-negative number')
    return number


def _usable_price(item, count):
    pricing = activity_pricing(item, count)
    issues = list(pricing['pricingIssues'])
    evidence = item.get('pricingEvidence') or {}
    if not isinstance(evidence, dict):
        issues.append('invalid_eligibility_evidence')
        evidence = {}
    if item.get('currency', 'MYR') != 'MYR' or evidence.get('currency', 'MYR') != 'MYR':
        issues.append('unsupported_currency')
    if pricing['costProvenance'] != 'verified_ticket':
        issues.append('price_not_verified')
    try:
        source = urlparse(item.get('priceSourceUrl') or '')
        date.fromisoformat(item.get('priceVerifiedAt') or '')
        if source.scheme not in {'https', 'http'} or not source.netloc:
            raise ValueError
    except (TypeError, ValueError):
        issues.append('missing_source_evidence')
    if (pricing['pricingUnit'] == 'per_person' and pricing['effectiveCost'] > 0
            and (evidence.get('applicability') != 'applicable' or not evidence.get('eligibility'))):
        issues.append('traveller_eligibility_unestablished')
    if pricing['overlapsAllowance']:
        issues.append('allowance_overlap_unresolved')
    return (None if issues else pricing['effectiveCost']), sorted(set(issues))


def _schedule(base, activities, forecast):
    plan = generateItinerary([], deepcopy(forecast or {}), {**deepcopy(base), 'activities': deepcopy(activities)})
    # The existing scheduler timestamps writes; an offline pure result has no clock field.
    plan.pop('updatedAt', None)
    return plan


def select_budget_aware_activities(candidates, itinerary, forecast=None):
    """Try higher-score candidates first; accept only budgeted, jointly schedulable sets.

    Unknown/conditional prices are deferred, not assigned RM0. Non-activity costs
    and allowances come from calculateBudget. Pending non-activity costs and any
    deferred pricing keep the selection provisional, even if its known subtotal fits.
    Positive per-person tickets need caller-supplied applicable eligibility evidence;
    this function cannot verify that assertion against real identities or providers.
    """
    base = deepcopy(itinerary)
    start, end = date.fromisoformat(base['startDate']), date.fromisoformat(base['endDate'])
    if end < start:
        raise ValueError('endDate must not precede startDate')
    limit = _number(base.get('budgetLimit'), 'budgetLimit')
    count = _number(base.get('travellerCount'), 'travellerCount')
    if count < 1 or count != traveller_count(count):
        raise ValueError('travellerCount must be a positive integer')
    scope = normalize_destination_scope(base.get('destinationArea'))
    if not scope.get('resolved'):
        raise ValueError('A resolved Malaysian destination is required')
    for field in ('flightCost', 'hotelCost', 'carRentalCost', 'foodCost', 'transportCost'):
        if base.get(field) not in (None, ''):
            _number(base[field], field)
    for field in ('activities', 'unscheduledSuggestions', 'dailySchedule', 'budgetEstimate'):
        base.pop(field, None)
    fixed = calculateBudget({**base, 'activities': []})
    fixed_total = fixed['totalEstimatedCost']
    entries, seen = [], set()
    for item in deepcopy(candidates):
        identity = item.get('activityId')
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError('Candidates require unique non-empty activityId strings')
        seen.add(identity)
        score = _number(item.get('score', item.get('finalScore')), 'recommendation score')
        if score > 100:
            raise ValueError('Recommendation score must be in 0..100')
        cost, issues = _usable_price(item, count)
        entries.append((item, score, cost, issues))
    entries.sort(key=lambda entry: (-entry[1], entry[2] if entry[2] is not None else float('inf'), entry[0]['activityId']))

    selected, excluded, rationale = [], [], []
    plan = _schedule(base, [], forecast)
    for item, score, cost, issues in entries:
        reason, explanation = None, None
        eligible, geographic = validate_candidate(item, scope)
        gps = item.get('gps_coordinates') or item.get('gpsCoordinates') or {}
        try:
            lat, lon = float(gps['latitude']), float(gps['longitude'])
            coordinates_known = isfinite(lat) and isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180
        except (KeyError, TypeError, ValueError):
            coordinates_known = False
        if not eligible or not coordinates_known:
            reason = 'geography_unverified_or_out_of_scope'
            explanation = geographic['geographicEligibility']['reason'] if not eligible else 'Coordinates required for travel-time assessment.'
        elif cost is None:
            reason, explanation = 'unresolved_price', 'No applicable verified MYR group cost; deferred rather than treated as free.'
        elif calculateBudget({**base, 'activities': selected + [item]})['totalEstimatedCost'] > limit:
            reason, explanation = 'known_budget_exceeded', 'Known non-activity costs plus this selection exceed the one group budget.'
        else:
            trial = _schedule(base, selected + [item], forecast)
            if len(trial['activities']) != len(selected) + 1:
                reason = 'joint_schedule_infeasible'
                explanation = '; '.join(x['unscheduledReason'] for x in trial['unscheduledSuggestions'])
            else:
                selected.append(item)
                plan = trial
                rationale.append({'activityId': item['activityId'], 'score': score, 'groupCost': cost,
                                  'explanation': 'Accepted in descending original-score order: known group cost fits and all selected visits fit the existing scheduler.'})
        if reason:
            excluded.append({'activity': item, 'score': score, 'groupCost': cost,
                             'pricingIssues': issues, 'reasonCode': reason, 'explanation': explanation})

    accounting = calculateBudget(plan)
    unresolved = sorted(set(accounting['pendingExpenseCategories'] + accounting['excludedExpenseCategories']
                            + (['activities'] if any(cost is None for _, _, cost, _ in entries) else [])))
    budget_status = ('over_budget' if accounting['totalEstimatedCost'] > limit else
                     'provisional' if unresolved else 'within_known_estimates')
    scheduling = ('no_activities_selected' if not selected else
                  'provisional' if plan['provisionalActivityCount'] else 'fits_reported_constraints')
    return {
        'offlineOnly': True, 'algorithm': 'score_first_budget_and_schedule_greedy',
        'candidateCount': len(entries),
        'knownPricedCandidateCount': sum(cost is not None for _, _, cost, _ in entries),
        'unresolvedPricedCandidateCount': sum(cost is None for _, _, cost, _ in entries),
        'selectedActivities': plan['activities'], 'unselectedActivities': excluded,
        'selectionRationale': rationale, 'schedule': plan['dailySchedule'],
        'schedulingStatus': scheduling,
        'isProvisional': bool(unresolved or scheduling != 'fits_reported_constraints'),
        'selectedRelevanceTotal': round(sum(entry['score'] for entry in rationale), 2),
        'budget': {'groupBudget': limit, 'knownNonActivitySubtotal': fixed_total,
                   'availableActivityBudgetFromKnownEstimates': round(max(0, limit-fixed_total), 2),
                   'knownActivitySubtotal': accounting['activities'],
                   'knownEstimatedTotal': accounting['totalEstimatedCost'],
                   'categoryTotals': accounting['categoryTotals'],
                   'unresolvedExpenseCategories': unresolved, 'status': budget_status},
        'limitations': [
            'Greedy score-first heuristic, not an optimal solver; no runtime integration or save-ready Trip.',
            'Eligibility/source evidence is trusted offline input, not independently verified here.',
            'Shared food/transport allowances are estimates, not live quotes. Separate mandatory fees not included in existing category totals are not modelled.',
            'Reported opening hours and the existing travel-time/duration estimates do not guarantee real-world opening or routing; first/last daily transfers are not modelled.',
            'Unpriced candidates are deferred. Provisional residual activity budget is not guaranteed spending capacity.',
        ],
    }
