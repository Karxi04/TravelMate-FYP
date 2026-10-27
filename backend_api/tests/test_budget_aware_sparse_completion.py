"""Synthetic offline equivalents of F3-P2C characteristics, not live venue data."""
from copy import deepcopy
import json
from math import ceil
from statistics import median
from time import perf_counter
from unittest.mock import patch

import pytest

from services import budget_aware_selection as selector
from services.budget_aware_generation import generate_with_budget_selection, qualify_selection_budget
from sequence_contract.domain_functions import calculateBudget, generateItinerary
from test_budget_aware_selection import activity, trip, unknown


def penang_pool(size=12, free_count=1):
    # Names/scores mirror audit characteristics; hours, coordinates and prices are fixtures.
    names = ['Kek Lok Si Temple', 'Georgetown UNESCO Site', 'Penang Street Art',
             'Wonderfood Museum', 'Fort Cornwallis', 'Georgetown Heritage Site',
             'Sun Yat Sen Museum', 'King Street Heritage Area', 'Colonial Penang Museum',
             'Clan Jetties of Penang', 'Penang Little India', 'Pinang Peranakan Mansion']
    scores = [72.34, 72.34, 72.34, 71.71, 63.22, 70.98, 70.93, 70.66, 69.91, 51.07, 52.38, 65.22]
    items = []
    for index in range(size):
        item = (activity(f'p{index:02}', 0) if index < free_count else unknown(f'p{index:02}'))
        item.update({'activityName': names[index] if index < len(names) else f'Synthetic venue {index}',
                     'score': scores[index] if index < len(scores) else 50-index/10,
                     'recommendedDurationMinutes': 100,
                     'gps_coordinates': {'latitude': 5.414+index*.0001, 'longitude': 100.329}})
        if index in (3, 11):
            item.update({'estimatedCost': 30, 'unitPrice': 30, 'pricingUnit': 'per_person',
                         'costProvenance': 'verified_ticket',
                         'priceSourceUrl': 'https://example.invalid/conditional-fixture',
                         'priceVerifiedAt': '2026-10-26',
                         'pricingEvidence': {'applicability': 'conditional', 'eligibility': 'residency_and_age'}})
        items.append(item)
    return items


def three_days(**changes):
    return trip(endDate='2026-11-03', budgetLimit=2000, **changes)


@pytest.mark.parametrize('free_count', [0, 1, 2])
def test_sparse_penang_completes_feasible_candidates_without_a_density_quota(free_count, capsys):
    items, data = penang_pool(free_count=free_count), three_days()
    before = deepcopy((items, data))
    legacy = generateItinerary([], {}, {**data, 'activities': items})
    result = selector.select_budget_aware_activities(items, data)
    legacy_ids = {item['activityId'] for item in legacy['activities']}
    selected_ids = {item['activityId'] for item in result['selectedActivities']}
    with capsys.disabled():
        print('\nPENANG_SPARSE_EVIDENCE=' + json.dumps({'free': free_count,
            'legacyDays': [len(day['activities']) for day in legacy['dailySchedule']],
            'selectedDays': [len(day['activities']) for day in result['schedule']],
            'legacyCount': len(legacy_ids), 'selectedCount': len(selected_ids),
            'scoreSum': result['selectedRelevanceTotal'],
            'excluded': [{'id': entry['activity']['activityId'], 'reason': entry['reasonCode']}
                         for entry in result['unselectedActivities']]}))
    # Expected identities come from actual engine feasibility, not a hardcoded count.
    assert selected_ids == legacy_ids
    assert (items, data) == before
    assert result == selector.select_budget_aware_activities(items, data)
    scores = {item['activityId']: item['score'] for item in items}
    assert all(item['score'] == scores[item['activityId']] for item in result['selectedActivities'])
    assert result['budget']['status'] == 'provisional'
    assert result['budget']['categoryTotals']['activities'] is None
    assert result['budget']['knownActivitySubtotal'] == 0
    assert result['budget']['unresolvedSelectedActivityCount'] == len(selected_ids)-free_count


@pytest.mark.parametrize('limit', [195, 2000])
def test_mixed_completion_preserves_paid_costs_and_evidence(limit):
    conditional = activity('conditional', 30, 99, pricingEvidence={
        'applicability': 'conditional', 'eligibility': 'MyKad_adult'})
    items = [activity('paid', 20, 95), activity('free', 0, 70), conditional,
             unknown('legacy', score=85), activity('expensive', 100, 100)]
    items[3]['estimatedCost'] = 57
    data = trip(budgetLimit=limit)
    generated = generate_with_budget_selection({**data, 'activities': items}, {}, [])
    result = generated['budgetAwareSelection']
    by_id = {item['activityId']: item for item in generated['activities']}
    assert {'paid', 'free', 'conditional', 'legacy'} <= by_id.keys()
    assert by_id['paid']['effectiveCost'] == 40
    assert by_id['paid']['pricingEvidence'] == items[0]['pricingEvidence']
    assert 'selectionPriceStatus' not in by_id['paid']
    assert by_id['conditional']['pricingEvidence']['applicability'] == 'conditional'
    assert by_id['legacy']['estimatedCost'] == 57
    assert all(by_id[key]['selectionGroupCost'] is None for key in ('legacy', 'conditional'))
    expected_known = 40 if limit == 195 else 240
    assert result['budget']['knownActivitySubtotal'] == expected_known
    assert result['budget']['knownCategoryTotals']['activities'] == expected_known
    assert result['budget']['categoryTotals']['activities'] is None
    assert result['budget']['status'] == 'provisional'
    if limit == 195:
        assert 'expensive' not in by_id
        assert next(entry for entry in result['unselectedActivities']
                    if entry['activity']['activityId'] == 'expensive')['reasonCode'] == 'known_budget_exceeded'
    budget = qualify_selection_budget(calculateBudget(generated), result)
    assert budget['completenessStatus'] == 'incomplete'
    assert budget['affordabilityStatus'] != 'within_budget'
    assert calculateBudget(generated)['completenessStatus'] == 'incomplete'
    assert all(day['applicableActivityCost'] is None for day in generated['dailySchedule'] if
               any(item.get('selectionPriceStatus') == 'unresolved' for item in day['activities']))


@pytest.mark.parametrize('problem', ['closed', 'geography', 'coordinates', 'duration', 'travel', 'split'])
def test_provisional_completion_cannot_bypass_joint_constraints(problem):
    known = activity('known', 0, 90, openingHours='09:00-10:00')
    unpriced = unknown('unpriced', score=99, openingHours='10:00-11:00')
    if problem == 'closed':
        unpriced['openingHours'] = 'Permanently closed'
    elif problem == 'geography':
        unpriced.update(address='Kuala Lumpur, Malaysia', gps_coordinates={'latitude': 3.14, 'longitude': 101.69})
    elif problem == 'coordinates':
        unpriced['gps_coordinates'] = {}
    elif problem == 'duration':
        unpriced['recommendedDurationMinutes'] = 700
    elif problem == 'travel':
        unpriced.update(providerTravelDurationMinutes=90, travelTimeSource='provider')
    else:
        unpriced.update(openingHours='10:00-10:30, 14:00-14:30', recommendedDurationMinutes=60)
    result = selector.select_budget_aware_activities([known, unpriced], trip())
    assert [item['activityId'] for item in result['selectedActivities']] == ['known']
    excluded = result['unselectedActivities'][0]
    assert excluded['explanation']
    assert excluded['reasonCode'] in {'geography_unverified_or_out_of_scope', 'joint_schedule_infeasible'}
    if problem != 'travel':
        assert all(not day['activities'] for day in selector.select_budget_aware_activities(
            [unpriced], three_days())['schedule'])


def test_no_forced_completion_when_known_fixed_expenses_already_exceed_budget():
    result = selector.select_budget_aware_activities(penang_pool(), three_days(foodCost=2100))
    assert result['selectedActivities'] == []
    assert result['budget']['status'] == 'over_budget'
    assert result['provisionalAdditionTrials'] == 0


def test_uncertain_hours_weather_and_pace_remain_provisional():
    items = [activity('free', 0, 80), unknown('uncertain', score=99, openingHours='Closed now', indoor=True)]
    forecast = {'daily': {'time': ['2026-11-01'], 'precipitation_probability_max': [95], 'weather_code': [61]}}
    result = selector.select_budget_aware_activities(items, trip(travelPace='relaxed'), forecast)
    visit = next(item for item in result['selectedActivities'] if item['activityId'] == 'uncertain')
    assert visit['scheduleFeasibility'] == 'provisional'
    assert visit['weather']['heavyRainLikely'] is True
    assert result['scheduledItinerary']['paceApplied'] == 'relaxed'
    assert result['schedulingStatus'] == 'provisional'
    assert result['budget']['status'] == 'provisional'


def test_completion_keeps_one_for_two_repair_and_does_not_duplicate_visits():
    items = [activity('A', 100, 90, 'per_group'), activity('B', 50, 65, 'per_group'),
             activity('C', 50, 64, 'per_group'), unknown('U', score=99)]
    result = selector.select_budget_aware_activities(items, trip(budgetLimit=255))
    ids = [item['activityId'] for item in result['selectedActivities']]
    assert set(ids) == {'B', 'C', 'U'} and len(ids) == len(set(ids))
    assert result['localRepairImproved'] is True
    assert result['budget']['knownActivitySubtotal'] == 100
    assert result['selectedRelevanceTotal'] == 228
    with pytest.raises(ValueError, match='unique'):
        selector.select_budget_aware_activities(items + [deepcopy(items[-1])], trip())


def test_only_days_with_unresolved_visits_lose_applicable_daily_totals():
    items = [activity('paid', 20, openingHours={
        'Sunday': '09:00-10:00', 'Monday': 'Closed', 'Tuesday': 'Closed'}),
        unknown('unknown', openingHours={
            'Sunday': 'Closed', 'Monday': '09:00-10:00', 'Tuesday': 'Closed'})]
    generated = generate_with_budget_selection({**three_days(), 'activities': items}, {}, [])
    known_day, unknown_day, empty_day = generated['dailySchedule']
    assert known_day['estimatedCost'] == 40
    assert 'applicableActivityCost' not in known_day
    assert unknown_day['applicableActivityCost'] is None
    assert unknown_day['costCompletenessStatus'] == 'incomplete'
    assert empty_day['estimatedCost'] == 0
    assert 'applicableActivityCost' not in empty_day


def test_completion_prefers_original_relevance_when_only_one_provisional_visit_fits():
    items = [activity('free', 0, openingHours='09:00-10:00'),
             unknown('low', score=1, openingHours='10:00-11:30'),
             unknown('high', score=99, openingHours='10:00-11:30')]
    result = selector.select_budget_aware_activities(items, trip())
    assert {item['activityId'] for item in result['selectedActivities']} == {'free', 'high'}
    assert result['provisionalAdditionTrials'] == 2
    assert result['unselectedActivities'][0]['activity']['activityId'] == 'low'
    assert result['unselectedActivities'][0]['reasonCode'] == 'joint_schedule_infeasible'


def test_days_with_no_feasible_visits_are_not_forced_full():
    items = [activity('free', 0, openingHours={'Sunday': '09:00-10:00', 'Monday': 'Closed', 'Tuesday': 'Closed'}),
             unknown('closed', openingHours='Closed')]
    result = selector.select_budget_aware_activities(items, three_days())
    assert [len(day['activities']) for day in result['schedule']] == [1, 0, 0]
    assert result['unselectedActivities'][0]['reasonCode'] == 'joint_schedule_infeasible'


def test_sparse_completion_runtime_and_scheduler_bounds(capsys):
    rows = []
    for size in (12, 20, 35):
        items, data = penang_pool(size), three_days()
        times, legacy_times, calls = [], [], []
        for _ in range(10):
            start = perf_counter()
            legacy = generateItinerary([], {}, {**data, 'activities': items})
            legacy_times.append((perf_counter()-start)*1000)
            with patch.object(selector, 'generateItinerary', wraps=generateItinerary) as scheduler:
                start = perf_counter()
                result = selector.select_budget_aware_activities(items, data)
                times.append((perf_counter()-start)*1000)
                calls.append(scheduler.call_count)
        trials = result.get('provisionalAdditionTrials', 0)
        assert trials == result['unresolvedPricedCandidateCount']
        assert max(calls) <= 1+size+result['localRepairTrials']
        rows.append({'candidates': size, 'repetitions': len(times), 'medianMs': round(median(times), 3),
            'p95Ms': round(sorted(times)[ceil(.95*len(times))-1], 3),
            'legacyMedianMs': round(median(legacy_times), 3),
            'legacyP95Ms': round(sorted(legacy_times)[ceil(.95*len(times))-1], 3),
            'schedulingInvocations': max(calls), 'localRepairTrials': result['localRepairTrials'],
            'provisionalAdditionTrials': trials, 'selected': len(result['selectedActivities']),
            'days': [len(day['activities']) for day in result['schedule']],
            'legacyDays': [len(day['activities']) for day in legacy['dailySchedule']],
            'excludedReasons': [entry['reasonCode'] for entry in result['unselectedActivities']]})
    with capsys.disabled():
        print('\nSPARSE_COMPLETION_BENCHMARK=' + json.dumps(rows))
