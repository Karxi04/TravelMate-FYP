"""All prices, scores, quotes and users here are synthetic offline fixtures."""
from copy import deepcopy
from pathlib import Path
from statistics import median
from time import perf_counter
from unittest.mock import patch
import json
import platform

import pytest

from services.budget_aware_selection import select_budget_aware_activities
from services.pricing_registry import enrich_candidate_pricing
from services.malaysian_locality import filter_candidates
from sequence_contract.domain_functions import calculateBudget, calculateRecommendationScore, generateItinerary


def activity(identity, price=20, score=80, unit='per_person', **changes):
    return {
        'activityId': identity, 'destinationId': 'synthetic-' + identity,
        'activityName': 'Synthetic cultural attraction ' + identity,
        'address': 'George Town, Penang, Malaysia', 'category': 'museum',
        'gps_coordinates': {'latitude': 5.414, 'longitude': 100.329},
        'recommendedDurationMinutes': 60, 'durationSource': 'confirmed',
        'openingHours': '09:00-18:00', 'score': score,
        'estimatedCost': price, 'pricingUnit': unit, 'unitPrice': price,
        'costCategory': 'admission', 'costProvenance': 'verified_ticket',
        'priceSourceUrl': 'https://example.invalid/synthetic-ticket-fixture',
        'priceVerifiedAt': '2026-10-26',
        'pricingEvidence': {'applicability': 'applicable', 'eligibility': 'synthetic_all_adult_fixture',
                            'currency': 'MYR', 'ticketProductId': 'synthetic-' + identity},
        **changes,
    }


def trip(**changes):
    return {'title': 'Synthetic offline selector test', 'destinationArea': 'Penang',
            'startDate': '2026-11-01', 'endDate': '2026-11-01',
            'travellerCount': 2, 'budgetLimit': 250,
            'travelMode': 'public_transport', 'accommodationChoice': 'return_home',
            'carRentalChoice': 'not_required', **changes}


def unknown(identity='unknown', **changes):
    item = activity(identity, **changes)
    for key in ('pricingUnit', 'unitPrice', 'costProvenance', 'priceSourceUrl', 'priceVerifiedAt', 'pricingEvidence'):
        item.pop(key, None)
    item['estimatedCost'] = 0
    return item


def scenarios():
    pool = [activity('expensive', 90, 95), activity('affordable', 15, 90), activity('free', 0, 60)]
    return {
        'two_traveller_low_budget_culture': (pool, trip()),
        'four_traveller_per_person': ([activity('ticket', 20), activity('group', 25, 70, 'per_group')],
                                    trip(travellerCount=4, budgetLimit=400)),
        'mixed_free_paid_unknown': (pool + [unknown()], trip()),
        'all_unknown': ([unknown('u1'), unknown('u2')], trip()),
        'conditional_residency': ([activity('conditional', 30, pricingEvidence={
            'applicability': 'conditional', 'eligibility': 'MyKad_or_foreign_tariff'}), activity('free', 0, 60)], trip()),
        'high_budget': (pool, trip(budgetLimit=2000)),
        'substantial_flight_hotel': ([activity('costly', 100, 90, 'per_group'), activity('affordable', 30, 80, 'per_group')],
            trip(endDate='2026-11-03', budgetLimit=1250, travelMode='flight', accommodationChoice='paid_hotel',
                 selectedFlight={'price': 300, 'currency': 'MYR', 'priceBasis': 'synthetic_group_total'},
                 flightCost=300, flightCurrency='MYR', flightPriceBasis='synthetic_group_total',
                 selectedHotel={'currency': 'MYR'}, hotelCost=400, hotelCurrency='MYR')),
        'geographically_infeasible_cheap': ([activity('far_cheap', 1, 99, 'per_group', address='Kuala Lumpur, Malaysia',
            gps_coordinates={'latitude': 3.14, 'longitude': 101.69}), activity('local', 80, 80, 'per_group')], trip()),
        'high_relevance_expensive': ([activity('relevant', 90, 99, 'per_group'), activity('low_relevance', 20, 5, 'per_group')], trip()),
        'very_low_relevance_cheap': ([activity('relevant', 40, 95), activity('low_relevance', 20, 1, 'per_group')], trip()),
        'greedy_trap': ([activity('A', 100, 90, 'per_group'), activity('B', 50, 65, 'per_group'),
                         activity('C', 50, 64, 'per_group')], trip(budgetLimit=255)),
    }


@pytest.mark.parametrize('name', list(scenarios()))
def test_required_offline_scenarios_are_deterministic_and_non_mutating(name):
    candidates, data = scenarios()[name]
    before = deepcopy((candidates, data))
    first = select_budget_aware_activities(candidates, data)
    assert first == select_budget_aware_activities(candidates, data)
    assert (candidates, data) == before
    assert first['offlineOnly'] is True
    assert first['candidateCount'] == len(candidates)
    assert len(first['selectedActivities']) + len(first['unselectedActivities']) == len(candidates)
    budget = first['budget']
    assert budget['knownEstimatedTotal'] == sum(budget['knownCategoryTotals'].values())
    assert budget['knownEstimatedTotal'] <= data['budgetLimit']


def test_one_group_budget_and_per_person_scaling_not_per_person_budget():
    candidates, data = scenarios()['four_traveller_per_person']
    result = select_budget_aware_activities(candidates, data)
    assert result['budget']['knownNonActivitySubtotal'] == 275
    assert result['budget']['availableActivityBudgetFromKnownEstimates'] == 125
    assert result['budget']['knownActivitySubtotal'] == 105
    assert result['budget']['knownEstimatedTotal'] == 380
    assert [entry['groupCost'] for entry in result['selectionRationale']] == [80, 25]


@pytest.mark.parametrize('unit', ['per_group', 'already_aggregated'])
def test_aggregated_or_group_prices_are_not_multiplied(unit):
    result = select_budget_aware_activities([activity('group', 25, unit=unit)], trip(travellerCount=4, budgetLimit=400))
    assert result['budget']['knownActivitySubtotal'] == 25


def test_real_registry_free_admission_is_accepted_without_new_price_truth():
    venue = enrich_candidate_pricing({'destinationId': 'local_kek_lok_si', 'title': 'Kek Lok Si Temple',
                                     'gps_coordinates': {'latitude': 5.3996, 'longitude': 100.2736}})
    item = {**venue, 'activityId': 'free', 'activityName': venue['title'], 'score': 80,
            'address': 'Air Itam, Penang', 'openingHours': '09:00-17:00'}
    result = select_budget_aware_activities([item], trip())
    assert result['budget']['knownActivitySubtotal'] == 0
    assert len(result['selectedActivities']) == 1


def test_unknown_prices_remain_none_and_do_not_create_a_free_complete_plan():
    candidates, data = scenarios()['all_unknown']
    result = select_budget_aware_activities(candidates, data)
    assert len(result['selectedActivities']) == 2
    assert result['budget']['status'] == 'provisional'
    assert result['budget']['unresolvedExpenseCategories'] == ['activities']
    assert all(item['groupCost'] is None for item in result['selectionRationale'])
    assert result['budget']['categoryTotals']['activities'] is None
    assert result['budget']['unresolvedSelectedActivityCount'] == 2
    assert result['budget']['knownActivitySubtotal'] == 0
    assert result['budget']['completenessStatus'] == 'incomplete'
    assert result['selectionMode'] == 'provisional_unpriced_fallback'
    assert result['schedule'][0]['estimatedCost'] is None


def test_unknown_price_destination_retains_a_useful_provisional_plan():
    result = select_budget_aware_activities([unknown('first', score=90), unknown('second', score=75)], trip())
    assert len(result['selectedActivities']) == 2
    assert result['budget']['status'] == 'provisional'
    assert all(entry['groupCost'] is None for entry in result['selectionRationale'])


def test_bounded_replacement_improves_the_reproducible_greedy_trap():
    candidates = [activity('A', 100, 90, 'per_group'), activity('B', 50, 65, 'per_group'),
                  activity('C', 50, 64, 'per_group')]
    result = select_budget_aware_activities(candidates, trip(budgetLimit=255))
    assert {item['activityId'] for item in result['selectedActivities']} == {'B', 'C'}
    assert result['selectedRelevanceTotal'] == 129
    assert result['budget']['knownActivitySubtotal'] == 100
    assert result['initialGreedyRelevanceTotal'] == 90
    assert result['selectedAverageRelevance'] == 64.5
    assert result['localRepairImproved'] is True
    assert result['unselectedActivities'][0]['reasonCode'] == 'local_quality_replacement'


@pytest.mark.parametrize('evidence', [None, ['malformed'], {'applicability': 'conditional', 'eligibility': 'MyKad'},
                                    {'applicability': 'conditional', 'eligibility': 'dynamic_visit_date'},
                                    {'applicability': 'conditional', 'eligibility': 'adult_rate_only'}])
def test_per_person_eligibility_cannot_be_assumed(evidence):
    item = activity('uncertain', pricingEvidence=evidence)
    result = select_budget_aware_activities([item], trip())
    assert result['knownPricedCandidateCount'] == 0
    assert result['selectionRationale'][0]['groupCost'] is None
    assert result['budget']['status'] == 'provisional'


@pytest.mark.parametrize('changes', [{'currency': 'USD'}, {'unitPrice': -1}, {'unitPrice': True},
                                   {'costProvenance': 'catalog_estimate'}, {'priceSourceUrl': ''},
                                   {'priceVerifiedAt': 'not-a-date'}, {'unitPrice': float('inf')},
                                   {'overlapsAllowance': True}, {'unitPrice': 0, 'priceSourceUrl': ''}])
def test_uncertain_invalid_or_overlapping_prices_are_not_used_as_budget_space(changes):
    result = select_budget_aware_activities([activity('invalid', **changes)], trip())
    assert result['selectionRationale'][0]['groupCost'] is None
    assert result['budget']['status'] == 'provisional'


def test_personality_relevance_wins_over_cheapest_first():
    candidates, data = scenarios()['high_relevance_expensive']
    result = select_budget_aware_activities(candidates, data)
    assert [item['activityId'] for item in result['selectedActivities']] == ['relevant']
    assert result['selectedActivities'][0]['score'] == 99
    assert result['unselectedActivities'][0]['reasonCode'] == 'known_budget_exceeded'


def test_feasible_lower_cost_candidate_can_replace_unaffordable_candidate():
    candidates, data = scenarios()['two_traveller_low_budget_culture']
    result = select_budget_aware_activities(candidates, data)
    assert {item['activityId'] for item in result['selectedActivities']} == {'affordable', 'free'}
    assert result['budget']['knownActivitySubtotal'] == 30
    assert result['selectedRelevanceTotal'] == 150
    assert result['schedulingStatus'] == 'fits_reported_constraints'


def test_geographic_filter_rejects_cheaper_cross_region_substitution():
    candidates, data = scenarios()['geographically_infeasible_cheap']
    result = select_budget_aware_activities(candidates, data)
    assert [item['activityId'] for item in result['selectedActivities']] == ['local']
    assert result['unselectedActivities'][0]['reasonCode'] == 'geography_unverified_or_out_of_scope'


def test_known_flight_hotel_costs_leave_only_residual_activity_budget():
    candidates, data = scenarios()['substantial_flight_hotel']
    result = select_budget_aware_activities(candidates, data)
    assert result['budget']['knownNonActivitySubtotal'] == 1165
    assert result['budget']['availableActivityBudgetFromKnownEstimates'] == 85
    assert result['budget']['knownActivitySubtotal'] == 30
    assert result['budget']['knownEstimatedTotal'] == 1195


@pytest.mark.parametrize('changes,category', [
    ({'travelMode': 'flight'}, 'flight'), ({'accommodationChoice': 'paid_hotel'}, 'hotel'),
    ({'carRentalChoice': 'undecided'}, 'carRental'), ({'travelMode': 'own_vehicle'}, 'ownVehicleFuelAndTolls'),
])
def test_unknown_mandatory_non_activity_expenses_keep_selection_provisional(changes, category):
    result = select_budget_aware_activities([activity('free', 0)], trip(**changes))
    assert result['budget']['status'] == 'provisional' and result['isProvisional']
    assert category in result['budget']['unresolvedExpenseCategories']


def test_unavoidable_fixed_overrun_does_not_become_affordable_by_selecting_free():
    result = select_budget_aware_activities([activity('free', 0)], trip(budgetLimit=100))
    assert result['selectedActivities'] == []
    assert result['budget']['knownEstimatedTotal'] == 155
    assert result['budget']['status'] == 'over_budget'


def test_simulated_rental_is_accounted_without_claiming_a_live_quote():
    result = select_budget_aware_activities([activity('free', 0)], trip(
        budgetLimit=500, carRentalChoice='selected', selectedCarRental={'id': 'synthetic', 'sandbox': True}, carRentalCost=100))
    assert result['budget']['categoryTotals']['carRental'] == 100
    assert any('not live quotes' in note for note in result['limitations'])


@pytest.mark.parametrize('hours', ['Closed', '18:00-18:15'])
def test_closed_or_insufficient_opening_period_is_rejected(hours):
    result = select_budget_aware_activities([activity('closed', 0, openingHours=hours)], trip())
    assert result['selectedActivities'] == []
    assert result['unselectedActivities'][0]['reasonCode'] == 'joint_schedule_infeasible'


def test_unknown_hours_remain_provisional_not_confirmed_feasible():
    result = select_budget_aware_activities([activity('unknown_hours', 0, openingHours='Closed now')], trip())
    assert len(result['selectedActivities']) == 1
    assert result['schedulingStatus'] == 'provisional' and result['isProvisional']
    assert result['selectedActivities'][0]['scheduleFeasibility'] == 'provisional'


def test_joint_travel_time_and_duration_constraints_are_not_bypassed():
    items = [activity('first', 0, 95, openingHours='09:00-10:00'),
             activity('second', 0, 80, openingHours='10:00-11:00',
                      providerTravelDurationMinutes=90, travelTimeSource='provider')]
    result = select_budget_aware_activities(items, trip())
    assert [item['activityId'] for item in result['selectedActivities']] == ['first']
    assert result['unselectedActivities'][0]['reasonCode'] == 'joint_schedule_infeasible'


def test_split_periods_and_daily_window_are_respected():
    result = select_budget_aware_activities([activity('split', 0, openingHours='09:00-10:00, 14:00-17:00',
                                                    recommendedDurationMinutes=120)], trip())
    assert result['selectedActivities'][0]['scheduledStartTime'] == '14:00'
    assert result['selectedActivities'][0]['scheduledEndTime'] == '16:00'


def test_missing_coordinates_cannot_claim_geographic_feasibility():
    result = select_budget_aware_activities([activity('no_coords', 0, gps_coordinates={})], trip())
    assert result['selectedActivities'] == []
    assert result['unselectedActivities'][0]['reasonCode'] == 'geography_unverified_or_out_of_scope'


@pytest.mark.parametrize('changes', [{'budgetLimit': -1}, {'budgetLimit': True}, {'travellerCount': 1.5},
                                   {'travellerCount': 0}, {'foodCost': float('nan')},
                                   {'endDate': '2026-10-01'}])
def test_invalid_group_inputs_fail_closed(changes):
    with pytest.raises(ValueError):
        select_budget_aware_activities([activity('a')], trip(**changes))


def test_duplicate_ids_are_rejected_and_tie_breaking_is_deterministic():
    with pytest.raises(ValueError):
        select_budget_aware_activities([activity('a'), activity('a')], trip())
    a, b = activity('a', 10), activity('b', 10)
    assert select_budget_aware_activities([a, b], trip()) == select_budget_aware_activities([b, a], trip())


def test_original_scoring_generation_and_persistence_are_untouched():
    candidates, data = scenarios()['high_budget']
    score_input = [{'contentScore': 80, 'collaborativeScore': 50, 'rating': 4, 'reviews': 500}]
    score_before = calculateRecommendationScore(score_input)
    baseline = generateItinerary([], {}, {**data, 'activities': candidates})
    with patch('sequence_contract.firebase_firestore.storeRecord') as store, \
         patch('sequence_contract.firebase_firestore.updateRecord') as update:
        select_budget_aware_activities(candidates, data)
        store.assert_not_called()
        update.assert_not_called()
    after = generateItinerary([], {}, {**data, 'activities': candidates})
    baseline.pop('updatedAt')
    after.pop('updatedAt')
    assert baseline == after
    assert calculateRecommendationScore(score_input) == score_before
    # 60%*80 + 30%*50 + 10%*(64+1), not a budget-adjusted personality score.
    assert score_before[0]['score'] == 69.5
    project = Path(__file__).resolve().parents[1]
    for module in ('modules/fr04_hybrid_recommendation/routes.py',):
        assert 'budget_aware_selection' not in (project / module).read_text(encoding='utf-8')


def test_offline_runtime_benchmark(capsys):
    fixtures = scenarios()
    for size in (20, 35):
        fixtures[f'pool_{size}'] = ([activity(f'p{i:02}', i % 5, 100-i*2, 'per_group',
                                              gps_coordinates={'latitude': 5.414+i*0.0001, 'longitude': 100.329})
                                    for i in range(size)], trip(endDate='2026-11-03', budgetLimit=2000))
    fixtures['bounded_repair_pool_20'] = ([activity('A', 100, 90, 'per_group')]
        + [activity(f'b{i:02}', 50, 65-i, 'per_group') for i in range(19)], trip(budgetLimit=255))
    rows = []
    for name, (candidates, data) in fixtures.items():
        times = []
        for _ in range(3):
            start = perf_counter()
            result = select_budget_aware_activities(candidates, data)
            times.append((perf_counter()-start)*1000)
        # Production already filters geography before scheduling: keep that baseline guard.
        eligible, _ = filter_candidates(candidates, data['destinationArea'])
        baseline = generateItinerary([], {}, {**data, 'activities': eligible})
        baseline_budget = calculateBudget(baseline)
        rows.append({'scenario': name, 'candidates': len(candidates),
                     'known': result['knownPricedCandidateCount'], 'unknown': result['unresolvedPricedCandidateCount'],
                     'selected': len(result['selectedActivities']), 'activityMYR': result['budget']['knownActivitySubtotal'],
                     'baselineTotalMYR': baseline_budget['totalEstimatedCost'],
                     'baselineBudgetStatus': baseline_budget['affordabilityStatus'],
                     'selectedTotalMYR': result['budget']['knownEstimatedTotal'],
                     'selectedBudgetStatus': result['budget']['status'],
                     'baselineScoreSum': sum(item['score'] for item in baseline['activities']),
                     'baselineAverageScore': round(sum(item['score'] for item in baseline['activities']) / len(baseline['activities']), 2) if baseline['activities'] else None,
                     'initialGreedyScoreSum': result['initialGreedyRelevanceTotal'],
                     'initialGreedySelected': result['initialGreedyActivityCount'],
                     'selectedScoreSum': result['selectedRelevanceTotal'],
                     'selectedAverageScore': result['selectedAverageRelevance'],
                     'unknownSelected': result['budget']['unresolvedSelectedActivityCount'],
                     'repairTrials': result['localRepairTrials'],
                     'excludedCount': len(result['unselectedActivities']),
                     'schedule': result['schedulingStatus'], 'unresolved': result['budget']['unresolvedExpenseCategories'],
                     'medianMs': round(median(times), 3), 'maxMs': round(max(times), 3)})
        assert max(times) < 5000
    with capsys.disabled():
        print('\nBENCHMARK_ENVIRONMENT=' + json.dumps({'python': platform.python_version(),
              'os': platform.platform(), 'machine': platform.machine(), 'repetitions': 3}))
        print('\nOFFLINE_SYNTHETIC_BENCHMARK=' + json.dumps(rows, sort_keys=True))


def test_mixed_prices_do_not_replace_a_budgeted_plan_with_unknown_costs():
    result = select_budget_aware_activities([activity('known', 20), unknown('unknown', score=99)], trip())
    assert [item['activityId'] for item in result['selectedActivities']] == ['known']
    assert result['selectionMode'] == 'budget_checked'
    assert result['budget']['unresolvedSelectedActivityCount'] == 0
    assert result['budget']['status'] == 'provisional'


def test_fallback_never_counts_a_legacy_unknown_estimate_as_known():
    item = unknown('legacy')
    item['estimatedCost'] = 57
    result = select_budget_aware_activities([item], trip())
    assert result['budget']['knownActivitySubtotal'] == 0
    assert result['budget']['categoryTotals']['activities'] is None
    assert result['selectedActivities'][0]['estimatedCost'] == 57
    assert result['selectedActivities'][0]['selectionGroupCost'] is None
    assert result['schedule'][0]['estimatedCost'] is None


@pytest.mark.parametrize('changes', [{'openingHours': 'Closed'},
    {'address': 'Kuala Lumpur', 'gps_coordinates': {'latitude': 3.14, 'longitude': 101.69}},
    {'gps_coordinates': {}}])
def test_fallback_cannot_bypass_geography_or_closure(changes):
    result = select_budget_aware_activities([unknown('unusable', **changes)], trip())
    assert result['selectedActivities'] == []
    assert result['isProvisional'] is True


def test_fallback_keeps_uncertain_hours_and_mandatory_costs_provisional():
    result = select_budget_aware_activities([unknown('visit', openingHours='Closed now')], trip(travelMode='flight'))
    assert result['schedulingStatus'] == 'provisional'
    assert result['budget']['status'] == 'provisional'
    assert set(result['budget']['unresolvedExpenseCategories']) == {'activities', 'flight'}


def test_fixed_overrun_prevents_unpriced_fallback():
    result = select_budget_aware_activities([unknown()], trip(budgetLimit=100))
    assert result['selectedActivities'] == []
    assert result['budget']['status'] == 'over_budget'


def test_all_verified_free_activities_remain_budget_checked():
    result = select_budget_aware_activities([activity('a', 0), activity('b', 0)], trip())
    assert len(result['selectedActivities']) == 2
    assert result['selectionMode'] == 'budget_checked'
    assert result['budget']['categoryTotals']['activities'] == 0
    assert result['budget']['completenessStatus'] == 'complete'


@pytest.mark.parametrize('invalid', ['closed', 'far', 'time'])
def test_quality_repair_cannot_bypass_joint_constraints(invalid):
    candidates, data = scenarios()['greedy_trap']
    if invalid == 'closed':
        candidates[2]['openingHours'] = 'Closed'
    elif invalid == 'far':
        candidates[2].update({'address': 'Kuala Lumpur', 'gps_coordinates': {'latitude': 3.14, 'longitude': 101.69}})
    else:
        for item in candidates:
            item['openingHours'] = '09:00-10:00'
    result = select_budget_aware_activities(candidates, data)
    assert [item['activityId'] for item in result['selectedActivities']] == ['A']
    assert result['localRepairImproved'] is False


def test_local_repair_has_a_deterministic_trial_bound():
    candidates = [activity('top', 100, 99, 'per_group')]
    candidates += [activity(f'low-{i:02}', 60, 10, 'per_group') for i in range(20)]
    result = select_budget_aware_activities(candidates, trip(budgetLimit=255))
    assert result['localRepairTrials'] == 64
    assert [item['activityId'] for item in result['selectedActivities']] == ['top']


def test_floating_point_score_tie_is_not_reported_as_quality_improvement():
    candidates = [activity('A', 100, 0.3, 'per_group'), activity('B', 50, 0.1, 'per_group'),
                  activity('C', 50, 0.2, 'per_group')]
    result = select_budget_aware_activities(candidates, trip(budgetLimit=255))
    assert [item['activityId'] for item in result['selectedActivities']] == ['A']
    assert result['localRepairImproved'] is False
