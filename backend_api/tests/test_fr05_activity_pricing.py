from copy import deepcopy
from unittest.mock import patch

import pytest

from modules.fr05_smart_itinerary_budget_planner.routes import _activity_from_destination
from sequence_contract.domain_functions import calculateBudget, generateItinerary, recalculateItinerary
from services.local_catalog import DESTINATIONS


def activity(unit='per_person', amount=10, **extra):
    return {
        'activityId': 'a1', 'activityName': 'Synthetic attraction',
        'destinationId': 'fixture', 'estimatedCost': amount,
        'pricingUnit': unit, 'costProvenance': 'catalog_estimate',
        'costCategory': 'admission', 'recommendedDurationMinutes': 60,
        **extra,
    }


def trip(items, count=2, **extra):
    return {
        'title': 'Synthetic cost fixture', 'destinationArea': 'Penang',
        'startDate': '2026-11-01', 'endDate': '2026-11-03',
        'budgetLimit': 1500, 'travellerCount': count, 'activities': items,
        'travelMode': 'public_transport', 'accommodationChoice': 'return_home',
        'carRentalChoice': 'not_required', **extra,
    }


@pytest.mark.parametrize('count,expected', [(1, 10), (2, 20), (4, 40)])
def test_per_person_scales_once(count, expected):
    data = trip([activity(unitPrice=10)], count)
    before = deepcopy(data)
    budget = calculateBudget(data)
    assert budget['activities'] == expected
    assert budget['total'] == expected + 60 * count * 3 + 35 * 3
    assert budget['affordabilityStatus'] == 'within_budget'
    assert calculateBudget(data) == budget
    assert data == before


@pytest.mark.parametrize('unit', ['per_group', 'already_aggregated'])
@pytest.mark.parametrize('count', [1, 2, 4])
def test_group_amounts_never_scale(unit, count):
    item = activity(unit, amount=25, effectiveCost=999)
    if unit == 'already_aggregated':
        item['unitPrice'] = 999
    assert calculateBudget(trip([item], count))['activities'] == 25


@pytest.mark.parametrize('unit', [None, 'unknown', 'not_a_unit'])
@pytest.mark.parametrize('amount', [0, 25])
def test_unknown_including_zero_keeps_raw_amount_and_incomplete(unit, amount):
    item = activity(unit, amount, unitPrice=999)
    if unit is None:
        item.pop('pricingUnit')
    budget = calculateBudget(trip([item], 4))
    assert budget['activities'] == amount
    assert budget['expenseBreakdown']['activities']['state'] == 'unit_unknown'
    assert budget['completenessStatus'] == 'incomplete'


def test_free_cost_requires_evidence_and_unit():
    free = activity('per_group', 0, costProvenance='verified_ticket',
                    priceSourceUrl='https://example.invalid/synthetic-evidence',
                    priceVerifiedAt='2026-10-25')
    budget = calculateBudget(trip([free]))
    assert budget['activities'] == 0
    assert budget['completenessStatus'] == 'complete'
    free.pop('priceSourceUrl')
    assert calculateBudget(trip([free]))['completenessStatus'] == 'incomplete'


def test_unit_and_reliability_are_separate():
    item = activity(costProvenance='unverified')
    budget = calculateBudget(trip([item]))
    assert budget['activities'] == 20
    assert budget['expenseBreakdown']['activities']['state'] == 'unverified_estimate'
    assert 'unverified_price' in budget['expenseBreakdown']['activities']['pricingIssues']


def test_mixed_daily_budget_recalculation_and_count_change():
    items = [activity('per_person', 10), activity('per_group', 15, activityId='a2'),
             activity('already_aggregated', 8, activityId='a3'),
             {'activityId': 'a4', 'estimatedCost': 7, 'recommendedDurationMinutes': 60},
             activity('per_group', 0, activityId='a5', costProvenance='verified_ticket',
                      priceSourceUrl='https://example.invalid/fixture', priceVerifiedAt='2026-10-25')]
    data = trip(items)
    before = deepcopy(data)
    plan = generateItinerary([], {}, data)
    assert len(plan['activities']) == 5
    assert sum(day['estimatedCost'] for day in plan['dailySchedule']) == 50
    assert calculateBudget(plan)['activities'] == 50
    for _ in range(2):
        plan = recalculateItinerary(plan)
        assert calculateBudget(plan)['activities'] == 50
        assert sum(day['estimatedCost'] for day in plan['dailySchedule']) == 50
    plan = recalculateItinerary({**plan, 'travellerCount': 4})
    assert calculateBudget(plan)['activities'] == 70
    assert sum(day['estimatedCost'] for day in plan['dailySchedule']) == 70
    assert plan['activities'][0]['effectiveCost'] == 40
    assert data == before


def test_group_budget_overrun_uses_scheduled_group_costs():
    plan = generateItinerary([], {}, trip([activity(amount=100)], 4, budgetLimit=1000))
    budget = calculateBudget(plan)
    assert budget['activities'] == sum(day['estimatedCost'] for day in plan['dailySchedule']) == 400
    assert budget['total'] == 1225
    assert budget['affordabilityStatus'] == 'over_budget'
    assert budget['overBy'] == 225


@pytest.mark.parametrize('category', ['food', 'transport', 'spending_allowance'])
def test_possible_allowance_overlap_keeps_all_selected_spending(category):
    budget = calculateBudget(trip([activity('per_group', 30, costCategory=category)]))
    assert budget['activities'] == 30
    assert budget['food'] == 360
    assert budget['transport'] == 105
    assert budget['total'] == 495
    assert budget['completenessStatus'] == 'incomplete'
    assert budget['expenseBreakdown']['activities']['overlapsAllowance'] is True


def test_shopping_spending_is_not_silently_removed():
    budget = calculateBudget(trip([activity('per_group', 30, costCategory='shopping')]))
    assert budget['activities'] == 30
    assert budget['completenessStatus'] == 'complete'
    budget = calculateBudget(trip([activity('per_group', 30, overlapsAllowance=True)]))
    assert budget['activities'] == 30
    assert budget['completenessStatus'] == 'incomplete'


@pytest.mark.parametrize('count', [0, -1, 'garbage', float('nan'), float('inf'), 1.5])
def test_invalid_traveller_count_is_safe_and_incomplete(count):
    budget = calculateBudget(trip([activity()], count))
    assert budget['activities'] == 10
    assert budget['completenessStatus'] == 'incomplete'


@pytest.mark.parametrize('value', [-1, 'invalid', float('nan'), float('inf')])
def test_invalid_unit_price_does_not_claim_free_activity(value):
    budget = calculateBudget(trip([activity(unitPrice=value)]))
    assert budget['activities'] == 10  # Retain the legacy raw estimate, unscaled.
    assert budget['completenessStatus'] == 'incomplete'


def test_cent_rounding_and_unit_price_precedence():
    budget = calculateBudget(trip([activity(unitPrice=1.005)], 2))
    assert budget['activities'] == 2.01


def test_legacy_snapshot_and_catalog_remain_unchanged():
    catalog_before = deepcopy(DESTINATIONS)
    data = trip([{'estimatedCost': 25}, {'estimatedCost': 0}], 4)
    original = deepcopy(data)
    assert calculateBudget(data)['activities'] == 25
    assert calculateBudget(data)['completenessStatus'] == 'incomplete'
    assert data == original
    assert len(DESTINATIONS) == 35
    assert all(not item.get('pricingUnit') for item in DESTINATIONS)
    assert DESTINATIONS == catalog_before


def test_legacy_fractional_estimates_keep_existing_sum_then_round_behavior():
    budget = calculateBudget(trip([{'estimatedCost': 0.005}, {'estimatedCost': 0.005}]))
    assert budget['activities'] == 0.01
    budget = calculateBudget(trip([{'estimatedCost': 0.005}]))
    assert budget['total'] == round(465 + 0.005, 2)


def test_candidate_projection_preserves_only_pricing_inputs():
    item = activity(unitPrice=12, effectiveCost=999)
    mapped = _activity_from_destination(item, 0)
    assert mapped['unitPrice'] == 12
    assert mapped['pricingUnit'] == 'per_person'
    assert 'effectiveCost' not in mapped
    assert calculateBudget(trip([mapped]))['activities'] == 24


def test_chat_to_trip_preserves_pricing_and_group_count(client, mock_traveller_auth):
    plan = trip([activity(unitPrice=12)], 4)
    plan.pop('travellerCount')
    plan['numberOfTravellers'] = 4
    with patch('modules.fr11_chatbot_travel_assistant.routes.storeRecord',
               side_effect=lambda _c, data: {'id': 'fixture-trip', **deepcopy(data)}):
        response = client.post('/api/fr11/save-plan', json={'plan': plan},
                               headers={'Authorization': 'Bearer valid_test_token'})
    assert response.status_code == 201
    saved = response.get_json()['itinerary']
    assert saved['travellerCount'] == 4
    assert saved['activities'][0]['unitPrice'] == 12
    assert saved['activities'][0]['costProvenance'] == 'catalog_estimate'
    assert saved['travelMode'] == plan['travelMode']
    assert saved['budgetEstimate']['activities'] == 48
    assert saved['budgetEstimate']['completenessStatus'] == 'complete'
    assert calculateBudget(saved)['activities'] == 48


def test_b1b1_selected_quotes_and_applicability_are_preserved():
    data = trip([activity()], travelMode='flight', accommodationChoice='paid_hotel',
                carRentalChoice='selected', selectedFlight={'currency': 'MYR', 'priceBasis': 'group_total'},
                flightCost=100, flightCurrency='MYR', selectedHotel={'currency': 'MYR'},
                hotelCost=200, hotelCurrency='MYR',
                selectedCarRental={'sandbox': True}, carRentalCost=50)
    budget = calculateBudget(data)
    assert (budget['flight'], budget['hotel'], budget['carRental']) == (100, 200, 50)
    assert budget['expenseBreakdown']['carRental']['state'] == 'simulated_estimate'
    assert budget['total'] == 835
    missing = calculateBudget(trip([activity()], travelMode='flight', accommodationChoice='paid_hotel'))
    assert missing['pendingExpenseCategories'] == ['flight', 'hotel']


def test_lower_cost_action_updates_unit_price_in_group_terms(client, mock_traveller_auth):
    data = generateItinerary([], {}, trip([activity(unitPrice=10)],
                                         travellerId='test_traveller_uid'))
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', return_value=data), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.updateRecord',
               side_effect=lambda _c, _id, changes: {**data, **changes}):
        response = client.post('/api/fr5/itineraries/fixture/lower-cost-alternatives/apply',
                               json={'type': 'activity', 'estimatedSavings': 6},
                               headers={'Authorization': 'Bearer valid_test_token'})
    assert response.status_code == 200
    saved = response.get_json()['itinerary']
    assert saved['activities'][0]['unitPrice'] == 7
    assert saved['budgetEstimate']['activities'] == 14
    assert sum(day['estimatedCost'] for day in saved['dailySchedule']) == 14


def test_count_update_refreshes_daily_cost_without_reordering(client, mock_traveller_auth):
    data = generateItinerary([], {}, trip([activity(unitPrice=10)],
                                         travellerId='test_traveller_uid'))
    before = deepcopy(data)
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', return_value=data), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.updateRecord',
               side_effect=lambda _c, _id, changes: {**data, **changes}):
        response = client.put('/api/fr5/itineraries/fixture', json={'travellerCount': 4},
                              headers={'Authorization': 'Bearer valid_test_token'})
    assert response.status_code == 200
    saved = response.get_json()['itinerary']
    assert saved['activities'][0]['unitPrice'] == 10
    assert saved['activities'][0]['estimatedCost'] == 10
    assert saved['activities'][0]['scheduledStartTime'] == before['activities'][0]['scheduledStartTime']
    assert saved['budgetEstimate']['activities'] == 40
    assert sum(day['estimatedCost'] for day in saved['dailySchedule']) == 40
    assert data == before


def test_generation_persists_candidate_pricing_and_matching_daily_budget(client, mock_traveller_auth):
    data = trip([], travellerId='test_traveller_uid')
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', return_value=data), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes._destination_candidates',
               return_value=([activity(unitPrice=12)], 'fixture')), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveLocationAndTravelTime', return_value=[]), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes._forecast_for', return_value=({}, None)), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.updateRecord',
               side_effect=lambda _c, _id, changes: {**data, **changes}):
        response = client.post('/api/fr5/itineraries/fixture/generate', json={},
                               headers={'Authorization': 'Bearer valid_test_token'})
    assert response.status_code == 200
    saved = response.get_json()['itinerary']
    assert saved['activities'][0]['pricingUnit'] == 'per_person'
    assert saved['activities'][0]['unitPrice'] == 12
    assert saved['budgetEstimate']['activities'] == 24
    assert sum(day['estimatedCost'] for day in saved['dailySchedule']) == 24


def test_chat_catalog_projection_preserves_price_metadata_without_nlp_changes():
    from modules.fr11_chatbot_travel_assistant.nlp_extractor import build_structured_trip_plan

    record = {**deepcopy(DESTINATIONS[0]), **activity(unitPrice=12)}
    original = deepcopy(record)
    plan, status = build_structured_trip_plan('Penang', 'Penang', days=1,
                                              traveller_count=4, catalog=[record])
    assert status == 'ready'
    assert all(item['pricingUnit'] == 'per_person' and item['unitPrice'] == 12
               for item in plan['activities'])
    assert record == original
