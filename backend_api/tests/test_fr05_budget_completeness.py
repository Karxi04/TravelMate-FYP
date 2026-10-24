from math import isfinite
from unittest.mock import patch

from sequence_contract.domain_functions import calculateBudget, compareBudget


PENANG_COSTS = [20, 30, 12, 25, 20, 35, 20, 10, 0, 50, 55]


def _trip(**changes):
    trip = {
        'title': 'Budget contract trip',
        'destinationArea': 'Penang',
        'startDate': '2026-11-01',
        'endDate': '2026-11-03',
        'travellerCount': 2,
        'budgetLimit': 1500,
        'activities': [],
    }
    trip.update(changes)
    return trip


def test_return_home_trip_marks_flight_hotel_and_rental_not_required():
    budget = calculateBudget(_trip(
        originLocation='Penang mainland',
        destinationArea='Penang island',
        endDate='2026-11-01',
        travelMode='public_transport',
        accommodationChoice='return_home',
        carRentalChoice='not_required',
        activities=[{'estimatedCost': cost} for cost in PENANG_COSTS],
    ))

    assert budget['knownEstimatedSubtotal'] == 432
    assert budget['expenseBreakdown']['flight']['state'] == 'not_required'
    assert budget['expenseBreakdown']['hotel']['state'] == 'not_required'
    assert budget['expenseBreakdown']['carRental']['state'] == 'not_required'
    assert budget['pendingExpenseCategories'] == ['activities']
    assert budget['affordabilityStatus'] == 'incomplete'


def test_selected_flight_and_paid_hotel_without_prices_remain_pending():
    budget = calculateBudget(_trip(
        travelMode='flight',
        accommodationChoice='paid_hotel',
        carRentalChoice='not_required',
    ))

    assert budget['flight'] == 0
    assert budget['hotel'] == 0
    assert budget['expenseBreakdown']['flight']['state'] == 'selected_unpriced'
    assert budget['expenseBreakdown']['hotel']['state'] == 'selected_unpriced'
    assert budget['pendingExpenseCategories'] == ['flight', 'hotel']
    assert budget['affordabilityStatus'] == 'incomplete'
    assert 'incomplete' in compareBudget(budget).lower()


def test_own_vehicle_and_family_stay_disclose_outside_scope_costs():
    budget = calculateBudget(_trip(
        travelMode='own_vehicle',
        accommodationChoice='staying_with_family',
        carRentalChoice='not_required',
    ))

    assert budget['flight'] == 0
    assert budget['hotel'] == 0
    assert budget['carRental'] == 0
    assert budget['knownEstimatedSubtotal'] == 465
    assert budget['excludedExpenseCategories'] == ['ownVehicleFuelAndTolls']
    assert budget['affordabilityStatus'] == 'incomplete'
    assert any('fuel and toll' in item.lower() for item in budget['estimateLimitations'])


def test_priced_selected_flight_and_hotel_count_against_one_group_budget():
    budget = calculateBudget(_trip(
        travelMode='flight',
        accommodationChoice='paid_hotel',
        carRentalChoice='not_required',
        selectedFlight={
            'price': 300, 'currency': 'MYR', 'priceStatus': 'available',
            'priceBasis': 'provider_round_trip_ticket_price_requested_adults',
            'source': 'serpapi',
        },
        flightCost=300,
        flightCurrency='MYR',
        flightPriceBasis='provider_round_trip_ticket_price_requested_adults',
        selectedHotel={'currency': 'MYR', 'rateProvenance': 'live_provider_quote'},
        hotelCost=400,
        hotelCurrency='MYR',
    ))

    assert budget['knownEstimatedSubtotal'] == 1165
    assert budget['totalEstimatedCost'] == 1165
    assert budget['budgetLimit'] == 1500
    assert budget['affordabilityStatus'] == 'within_budget'
    assert budget['completenessStatus'] == 'complete'
    assert budget['categoryTotals'] == {
        'flight': 300, 'hotel': 400, 'carRental': 0,
        'transport': 105, 'food': 360, 'activities': 0,
    }


def test_known_overrun_wins_even_when_flight_and_hotel_are_pending():
    budget = calculateBudget(_trip(
        travelMode='flight',
        accommodationChoice='paid_hotel',
        carRentalChoice='undecided',
        activities=[{'estimatedCost': 1100}],
    ))

    assert budget['knownEstimatedSubtotal'] == 1565
    assert budget['overBy'] == 65
    assert budget['affordabilityStatus'] == 'over_budget'
    assert budget['completenessStatus'] == 'incomplete'


def test_missing_choices_preserve_legacy_numeric_totals_but_are_incomplete():
    budget = calculateBudget(_trip(
        flightCost=200,
        hotelCost=300,
        hotelCurrency='MYR',
        carRentalCost=50,
        activities=[{'estimatedCost': 20}],
    ))

    assert budget['total'] == 1035
    assert budget['totalEstimatedCost'] == 1035
    assert budget['pendingExpenseCategories'] == [
        'flight', 'hotel', 'carRental', 'activities']
    assert budget['affordabilityStatus'] == 'incomplete'


def test_simulated_rental_retains_provenance_without_becoming_confirmed_live_price():
    budget = calculateBudget(_trip(
        travelMode='public_transport',
        accommodationChoice='return_home',
        carRentalChoice='selected',
        selectedCarRental={'id': 'local_car_1', 'sandbox': True, 'totalPrice': 100},
        carRentalCost=100,
    ))

    rental = budget['expenseBreakdown']['carRental']
    assert rental['amount'] == 100
    assert rental['state'] == 'simulated_estimate'
    assert rental['provenance'] == 'simulated_local_catalogue'
    assert any('simulated local catalogue' in item for item in budget['estimateLimitations'])


def test_invalid_money_never_produces_negative_or_non_finite_totals():
    budget = calculateBudget(_trip(
        travelMode='flight',
        accommodationChoice='paid_hotel',
        carRentalChoice='selected',
        selectedFlight={'currency': 'MYR', 'priceBasis': 'group_total'},
        flightCost=float('nan'),
        flightCurrency='MYR',
        flightPriceBasis='group_total',
        selectedHotel={'currency': 'MYR'},
        hotelCost=float('inf'),
        hotelCurrency='MYR',
        selectedCarRental={'sandbox': True},
        carRentalCost=-10,
        transportCost=-5,
        foodCost=float('nan'),
        activities=[{'estimatedCost': -20}],
    ))

    assert budget['knownEstimatedSubtotal'] == 0
    assert isfinite(budget['knownEstimatedSubtotal'])
    assert all(value >= 0 and isfinite(value)
               for value in budget['categoryTotals'].values())


def test_explicit_zero_group_budget_reports_known_costs_as_over_budget():
    budget = calculateBudget(_trip(
        budgetLimit=0,
        travelMode='public_transport',
        accommodationChoice='return_home',
        carRentalChoice='not_required',
    ))

    assert budget['knownEstimatedSubtotal'] == 465
    assert budget['affordabilityStatus'] == 'over_budget'
    assert budget['overBy'] == 465


def test_create_route_persists_additive_trip_context_and_budget_contract(
        client, mock_traveller_auth):
    payload = _trip(
        originLocation='Penang mainland',
        destinationArea='Penang island',
        endDate='2026-11-01',
        travelMode='public_transport',
        accommodationChoice='return_home',
        carRentalChoice='not_required',
    )

    with patch(
            'modules.fr05_smart_itinerary_budget_planner.routes.storeRecord',
            side_effect=lambda _collection, data: {'id': 'trip_budget_1', **data}):
        response = client.post(
            '/api/fr5/itineraries',
            headers={'Authorization': 'Bearer valid_test_token'},
            json=payload,
        )

    assert response.status_code == 201
    itinerary = response.get_json()['itinerary']
    assert itinerary['originLocation'] == 'Penang mainland'
    assert itinerary['travelMode'] == 'public_transport'
    assert itinerary['accommodationChoice'] == 'return_home'
    assert itinerary['carRentalChoice'] == 'not_required'
    assert itinerary['budgetEstimate']['affordabilityStatus'] == 'within_budget'


def test_invalid_planning_choice_is_rejected_by_existing_route_validation(
        client, mock_traveller_auth):
    response = client.post(
        '/api/fr5/itineraries',
        headers={'Authorization': 'Bearer valid_test_token'},
        json=_trip(travelMode='teleport'),
    )

    assert response.status_code == 400


def test_rental_selection_persists_explicit_choice_and_simulation_provenance(
        client, mock_traveller_auth):
    itinerary = _trip(
        travellerId='test_traveller_uid',
        travelMode='public_transport',
        accommodationChoice='return_home',
        carRentalChoice='undecided',
    )
    rental = {'id': 'local_car_1', 'sandbox': True, 'totalPrice': 100}

    with patch(
            'modules.fr08_hotel_booking.routes.retrieveRecord',
            return_value=itinerary), patch(
            'modules.fr08_hotel_booking.routes.updateRecord',
            side_effect=lambda _collection, _document_id, data: {
                **itinerary, **data}):
        response = client.post(
            '/api/fr8/car-rentals/select',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'itineraryId': 'trip_budget_1', 'rental': rental},
        )

    assert response.status_code == 200
    updated = response.get_json()['itinerary']
    assert updated['carRentalChoice'] == 'selected'
    assert updated['budgetEstimate']['expenseBreakdown']['carRental']['state'] == 'simulated_estimate'
