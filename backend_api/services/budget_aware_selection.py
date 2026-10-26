"""Score-first selection with bounded repair and provisional completion.

Inputs are already normalized activities with unique activityId and unchanged FR04
score (0..100). The pool replaces activities in an offline copy, not a persisted
Trip. No pricing lookup, provider, repository or route handler is invoked.
"""
from copy import deepcopy
from datetime import date
from itertools import combinations, islice
from math import isfinite
from urllib.parse import urlparse

from services.activity_pricing import activity_pricing, traveller_count
from services.malaysian_locality import normalize_destination_scope, validate_candidate
from sequence_contract.domain_functions import calculateBudget, generateItinerary


LOCAL_REPAIR_TRIAL_LIMIT = 64


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


def _improve_once(base, selected, excluded, scores, forecast, limit):
    """Bounded one-for-two repair of known-price, budget-rejected choices only."""
    rejected = [entry['activity'] for entry in excluded if entry['reasonCode'] == 'known_budget_exceeded']
    best, best_plan, attempts = selected, None, 0
    best_score = round(sum(scores[item['activityId']] for item in selected), 2)
    trials = ((removed, pair) for removed in selected for pair in combinations(rejected, 2))
    for removed, pair in islice(trials, LOCAL_REPAIR_TRIAL_LIMIT):
        attempts += 1
        proposed = [item for item in selected if item['activityId'] != removed['activityId']] + list(pair)
        score = round(sum(scores[item['activityId']] for item in proposed), 2)
        if score <= best_score or calculateBudget({**base, 'activities': proposed})['totalEstimatedCost'] > limit:
            continue
        trial = _schedule(base, proposed, forecast)
        if len(trial['activities']) == len(proposed):
            best, best_plan, best_score = proposed, trial, score
    if best_plan is not None:
        new_ids = {item['activityId'] for item in best}
        excluded = [entry for entry in excluded if entry['activity']['activityId'] not in new_ids]
        for item in selected:
            if item['activityId'] not in new_ids:
                excluded.append({'activity': item, 'score': scores[item['activityId']],
                                 'groupCost': activity_pricing(item, base['travellerCount'])['effectiveCost'],
                                 'pricingIssues': [], 'reasonCode': 'local_quality_replacement',
                                 'explanation': 'Replaced by two jointly schedulable, budgeted activities with higher aggregate original score.'})
    return best, excluded, best_plan, attempts


def select_budget_aware_activities(candidates, itinerary, forecast=None):
    """Select budgeted visits, then complete with explicitly unpriced suggestions.

    Unknown/conditional prices are not assigned RM0. Non-activity costs
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

    greedy_score = sum(entry['score'] for entry in rationale)
    greedy_count = len(selected)
    scores = {item['activityId']: score for item, score, _, _ in entries}
    costs = {item['activityId']: cost for item, _, cost, _ in entries}
    selected, excluded, improved_plan, repair_trials = _improve_once(base, selected, excluded, scores, forecast, limit)
    if improved_plan is not None:
        plan = improved_plan
        rationale = [{'activityId': item['activityId'], 'score': scores[item['activityId']],
                      'groupCost': costs[item['activityId']],
                      'explanation': 'Selected after bounded one-for-two aggregate-score improvement; full budget and scheduling checks passed.'}
                     for item in selected]

    fallback, completion_trials = False, 0
    budgeted_count = len(selected)
    if fixed_total <= limit:
        # One trial per deferred candidate; never displace an already selected visit.
        for entry in list(excluded):
            if entry['reasonCode'] != 'unresolved_price':
                continue
            item = entry['activity']
            completion_trials += 1
            trial = _schedule(base, selected + [item], forecast)
            if len(trial['activities']) != len(selected) + 1:
                entry.update({'reasonCode': 'joint_schedule_infeasible',
                              'explanation': '; '.join(x['unscheduledReason'] for x in trial['unscheduledSuggestions'])})
                continue
            selected.append(item)
            excluded.remove(entry)
            plan, fallback = trial, True
            rationale.append({'activityId': item['activityId'], 'score': entry['score'], 'groupCost': None,
                              'explanation': 'Provisional scheduling suggestion only: admission is unresolved and affordability is not established.'})

    # Unverified legacy estimates are not known applicable costs in the fallback.
    known_selected = [item for item in selected if costs[item['activityId']] is not None]
    accounting = calculateBudget({**base, 'activities': known_selected})
    unknown_selected = len(selected) - len(known_selected)
    if fallback:
        for item in plan['activities']:
            if costs[item['activityId']] is None:
                item.pop('effectiveCost', None)
                item.update({'selectionGroupCost': None, 'selectionPriceStatus': 'unresolved'})
        for day in plan['dailySchedule']:
            if any(costs[item['activityId']] is None for item in day['activities']):
                day['estimatedCost'] = None
    unresolved = sorted(set(accounting['pendingExpenseCategories'] + accounting['excludedExpenseCategories']
                            + (['activities'] if any(cost is None for _, _, cost, _ in entries) else [])))
    budget_status = ('over_budget' if accounting['totalEstimatedCost'] > limit else
                     'provisional' if unresolved else 'within_known_estimates')
    scheduling = ('no_activities_selected' if not selected else
                  'provisional' if plan['provisionalActivityCount'] else 'fits_reported_constraints')
    return {
        'offlineOnly': True, 'algorithm': 'score_first_with_bounded_repair_and_provisional_fallback',
        'selectionMode': ('budget_checked_with_provisional_completion' if fallback and budgeted_count else
                          'provisional_unpriced_fallback' if fallback else 'budget_checked'),
        'initialGreedyRelevanceTotal': greedy_score, 'initialGreedyActivityCount': greedy_count,
        'localRepairTrials': repair_trials, 'localRepairImproved': improved_plan is not None,
        'provisionalAdditionTrials': completion_trials,
        'candidateCount': len(entries),
        'knownPricedCandidateCount': sum(cost is not None for _, _, cost, _ in entries),
        'unresolvedPricedCandidateCount': sum(cost is None for _, _, cost, _ in entries),
        'selectedActivities': plan['activities'], 'unselectedActivities': excluded,
        'scheduledItinerary': plan,
        'selectionRationale': rationale, 'schedule': plan['dailySchedule'],
        'schedulingStatus': scheduling,
        'isProvisional': bool(unresolved or scheduling != 'fits_reported_constraints'),
        'selectedRelevanceTotal': round(sum(entry['score'] for entry in rationale), 2),
        'selectedAverageRelevance': round(sum(entry['score'] for entry in rationale) / len(selected), 2) if selected else None,
        'budget': {'groupBudget': limit, 'knownNonActivitySubtotal': fixed_total,
                   'availableActivityBudgetFromKnownEstimates': round(max(0, limit-fixed_total), 2),
                   'knownActivitySubtotal': accounting['activities'],
                   'knownEstimatedTotal': accounting['totalEstimatedCost'],
                   'categoryTotals': {**accounting['categoryTotals'], 'activities': None if unknown_selected else accounting['activities']},
                   'knownCategoryTotals': accounting['categoryTotals'],
                   'unresolvedSelectedActivityCount': unknown_selected,
                   'completenessStatus': 'incomplete' if unresolved else 'complete',
                   'unresolvedExpenseCategories': unresolved, 'status': budget_status},
        'limitations': [
            'Score-first heuristic with at most 64 one-for-two trials and one accepted repair, not an optimal solver; runtime activation requires separate approval.',
            'Eligibility/source evidence is trusted offline input, not independently verified here.',
            'Shared food/transport allowances are estimates, not live quotes. Separate mandatory fees not included in existing category totals are not modelled.',
            'Reported opening hours and the existing travel-time/duration estimates do not guarantee real-world opening or routing; first/last daily transfers are not modelled.',
            'Schedulable unpriced visits may complete the budget-checked selection as provisional suggestions. Their admission totals remain unknown, not free or proved affordable.',
        ],
    }
