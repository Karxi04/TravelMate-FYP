from copy import deepcopy
from sequence_contract.domain_functions import calculateBudget, compareBudget


def _synthetic_flight_quote(**overrides):
    quote = {
        'airline': 'AirAsia',
        'flightNumber': 'AK 6114',
        'departureAirport': 'KUL',
        'arrivalAirport': 'PEN',
        'departureTime': '08:00',
        'arrivalTime': '09:00',
        'price': 256.0,
        'currency': 'MYR',
        'priceBasis': 'provider_round_trip_ticket_price_requested_adults',
        'priceStatus': 'available',
        'source': 'serpapi',
    }
    quote.update(overrides)
    return quote


def _base_trip(**overrides):
    trip = {
        'title': 'Penang Heritage Getaway',
        'destinationArea': 'Penang',
        'startDate': '2026-11-01',
        'endDate': '2026-11-03',
        'travellerCount': 1,
        'budgetLimit': 1000.0,
        'activities': [],
    }
    trip.update(overrides)
    return trip


# 1. Historical missing travelMode + valid selected flight quote
def test_01_historical_missing_travel_mode_with_valid_selected_flight():
    trip = _base_trip(
        flightCost=256.0,
        flightCurrency='MYR',
        flightPriceBasis='provider_round_trip_ticket_price_requested_adults',
        flightSelectionStatus='selected',
        selectedFlight=_synthetic_flight_quote(),
    )
    assert 'travelMode' not in trip

    budget = calculateBudget(trip)

    assert budget['categoryTotals']['flight'] == 256.0
    assert budget['flight'] == 256.0
    assert budget['expenseBreakdown']['flight']['state'] == 'priced'
    assert budget['expenseBreakdown']['flight']['amount'] == 256.0
    assert 'flight' not in budget['pendingExpenseCategories']
    assert budget['costProvenance']['flight'] == 'confirmed_total'


# 2. Historical missing travelMode + no flight quote
def test_02_historical_missing_travel_mode_with_no_flight_quote():
    trip = _base_trip(
        accommodationChoice='return_home',
        carRentalChoice='not_required',
    )
    assert 'travelMode' not in trip

    budget = calculateBudget(trip)

    assert budget['categoryTotals']['flight'] == 0.0
    assert budget['flight'] == 0.0
    assert budget['expenseBreakdown']['flight']['state'] == 'undecided'
    assert 'flight' in budget['pendingExpenseCategories']
    assert budget['costProvenance']['flight'] == 'not_selected'


# 3. Explicit travelMode = flight with selected quote
def test_03_explicit_travel_mode_flight_with_selected_quote():
    trip = _base_trip(
        travelMode='flight',
        flightCost=300.0,
        flightCurrency='MYR',
        flightPriceBasis='provider_round_trip_ticket_price_requested_adults',
        flightSelectionStatus='selected',
        selectedFlight=_synthetic_flight_quote(price=300.0),
    )

    budget = calculateBudget(trip)

    assert budget['categoryTotals']['flight'] == 300.0
    assert budget['flight'] == 300.0
    assert budget['expenseBreakdown']['flight']['state'] == 'priced'
    assert 'flight' not in budget['pendingExpenseCategories']


# 4. Explicit travelMode = flight without quote
def test_04_explicit_travel_mode_flight_without_quote():
    trip = _base_trip(
        travelMode='flight',
    )

    budget = calculateBudget(trip)

    assert budget['categoryTotals']['flight'] == 0.0
    assert budget['flight'] == 0.0
    assert budget['expenseBreakdown']['flight']['state'] == 'selected_unpriced'
    assert 'flight' in budget['pendingExpenseCategories']
    assert budget['costProvenance']['flight'] == 'pending_unpriced'


# 5. Explicit travelMode = undecided with an attached quote
def test_05_explicit_travel_mode_undecided_with_attached_quote():
    trip = _base_trip(
        travelMode='undecided',
        flightCost=256.0,
        flightCurrency='MYR',
        flightPriceBasis='provider_round_trip_ticket_price_requested_adults',
        flightSelectionStatus='selected',
        selectedFlight=_synthetic_flight_quote(),
    )

    budget = calculateBudget(trip)

    # Explicit traveller choice 'undecided' is preserved
    assert budget['expenseBreakdown']['flight']['state'] == 'undecided'
    assert 'flight' in budget['pendingExpenseCategories']
    assert budget['affordabilityStatus'] == 'incomplete'
    # Numeric legacy total is preserved
    assert budget['categoryTotals']['flight'] == 256.0
    assert any('undecided' in lim.lower() for lim in budget['estimateLimitations'])


# 6. Explicit travelMode = own_vehicle with a historical attached quote
def test_06_explicit_travel_mode_own_vehicle_with_historical_attached_quote():
    trip = _base_trip(
        travelMode='own_vehicle',
        flightCost=256.0,
        flightCurrency='MYR',
        flightPriceBasis='provider_round_trip_ticket_price_requested_adults',
        selectedFlight=_synthetic_flight_quote(),
    )

    budget = calculateBudget(trip)

    # Non-flight choice takes precedence
    assert budget['categoryTotals']['flight'] == 0.0
    assert budget['flight'] == 0.0
    assert budget['expenseBreakdown']['flight']['state'] == 'not_required'
    assert 'flight' not in budget['pendingExpenseCategories']
    assert 'ownVehicleFuelAndTolls' in budget['excludedExpenseCategories']
    assert any('conflict' in lim.lower() for lim in budget['estimateLimitations'])


# 7. Explicit travelMode = public_transport with a historical attached quote
def test_07_explicit_travel_mode_public_transport_with_historical_attached_quote():
    trip = _base_trip(
        travelMode='public_transport',
        flightCost=256.0,
        flightCurrency='MYR',
        flightPriceBasis='provider_round_trip_ticket_price_requested_adults',
        selectedFlight=_synthetic_flight_quote(),
    )

    budget = calculateBudget(trip)

    # Non-flight choice takes precedence
    assert budget['categoryTotals']['flight'] == 0.0
    assert budget['flight'] == 0.0
    assert budget['expenseBreakdown']['flight']['state'] == 'not_required'
    assert 'flight' not in budget['pendingExpenseCategories']
    assert any('conflict' in lim.lower() for lim in budget['estimateLimitations'])


# 8. Historical selected quote with missing/incomplete price
def test_08_historical_selected_quote_with_missing_or_incomplete_price():
    # 8a: priceStatus unknown and zero price
    trip_unknown = _base_trip(
        flightCost=0,
        flightCurrency='MYR',
        flightPriceBasis='provider_round_trip_ticket_price_requested_adults',
        selectedFlight=_synthetic_flight_quote(priceStatus='unknown', price=0),
    )
    budget_unknown = calculateBudget(trip_unknown)
    assert budget_unknown['expenseBreakdown']['flight']['state'] == 'selected_unpriced'
    assert 'flight' in budget_unknown['pendingExpenseCategories']

    # 8b: non-MYR currency
    trip_currency = _base_trip(
        flightCost=256.0,
        flightCurrency='USD',
        flightPriceBasis='provider_round_trip_ticket_price_requested_adults',
        selectedFlight=_synthetic_flight_quote(currency='USD'),
    )
    budget_currency = calculateBudget(trip_currency)
    assert budget_currency['categoryTotals']['flight'] == 0.0
    assert budget_currency['expenseBreakdown']['flight']['state'] == 'selected_unpriced'
    assert 'flight' in budget_currency['pendingExpenseCategories']

    # 8c: missing price basis
    trip_no_basis = _base_trip(
        flightCost=256.0,
        flightCurrency='MYR',
        flightPriceBasis=None,
        selectedFlight=_synthetic_flight_quote(priceBasis=None),
    )
    budget_no_basis = calculateBudget(trip_no_basis)
    assert budget_no_basis['categoryTotals']['flight'] == 0.0
    assert budget_no_basis['expenseBreakdown']['flight']['state'] == 'selected_unpriced'
    assert 'flight' in budget_no_basis['pendingExpenseCategories']


# 9. Quote marked selected versus confirmed booking
def test_09_quote_marked_selected_versus_confirmed_booking():
    # A SerpApi quote is a planning quote, never presented as a confirmed ticket/booking
    trip_live = _base_trip(
        flightCost=256.0,
        flightCurrency='MYR',
        flightPriceBasis='provider_round_trip_ticket_price_requested_adults',
        flightSelectionStatus='selected',
        flightSelectionSource='serpapi',
        selectedFlight=_synthetic_flight_quote(source='serpapi'),
    )
    budget_live = calculateBudget(trip_live)
    assert budget_live['expenseBreakdown']['flight']['state'] == 'priced'
    assert budget_live['expenseBreakdown']['flight']['provenance'] == 'selected_flight'
    assert budget_live['expenseBreakdown']['flight']['selectionStatus'] == 'selected'

    # A sandbox quote retains sandbox / simulated disclosure
    trip_sandbox = _base_trip(
        flightCost=256.0,
        flightCurrency='MYR',
        flightPriceBasis='provider_round_trip_ticket_price_requested_adults',
        flightSelectionStatus='selected',
        selectedFlight=_synthetic_flight_quote(sandbox=True),
    )
    budget_sandbox = calculateBudget(trip_sandbox)
    assert budget_sandbox['expenseBreakdown']['flight']['state'] == 'simulated_estimate'
    assert any('planning or sandbox estimate, not a completed reservation' in lim
               for lim in budget_sandbox['estimateLimitations'])


# 10. Correct flight expense category state
def test_10_correct_flight_expense_category_state():
    states = {}

    # State: priced
    b1 = calculateBudget(_base_trip(
        flightCost=256.0, flightCurrency='MYR',
        flightPriceBasis='provider_round_trip_ticket_price_requested_adults',
        selectedFlight=_synthetic_flight_quote()))
    states['historical_valid'] = b1['expenseBreakdown']['flight']['state']

    # State: simulated_estimate
    b2 = calculateBudget(_base_trip(
        flightCost=256.0, flightCurrency='MYR',
        flightPriceBasis='provider_round_trip_ticket_price_requested_adults',
        selectedFlight=_synthetic_flight_quote(isSimulated=True)))
    states['simulated'] = b2['expenseBreakdown']['flight']['state']

    # State: selected_unpriced
    b3 = calculateBudget(_base_trip(
        travelMode='flight'))
    states['selected_unpriced'] = b3['expenseBreakdown']['flight']['state']

    # State: undecided
    b4 = calculateBudget(_base_trip(
        travelMode='undecided'))
    states['undecided'] = b4['expenseBreakdown']['flight']['state']

    # State: not_required
    b5 = calculateBudget(_base_trip(
        travelMode='public_transport'))
    states['not_required'] = b5['expenseBreakdown']['flight']['state']

    assert states == {
        'historical_valid': 'priced',
        'simulated': 'simulated_estimate',
        'selected_unpriced': 'selected_unpriced',
        'undecided': 'undecided',
        'not_required': 'not_required',
    }


# 11. Correct pendingExpenseCategories
def test_11_correct_pending_expense_categories():
    # Priced flight -> flight NOT in pending
    b_priced = calculateBudget(_base_trip(
        flightCost=256.0, flightCurrency='MYR',
        flightPriceBasis='provider_round_trip_ticket_price_requested_adults',
        selectedFlight=_synthetic_flight_quote()))
    assert 'flight' not in b_priced['pendingExpenseCategories']

    # Simulated flight -> flight NOT in pending
    b_sim = calculateBudget(_base_trip(
        flightCost=256.0, flightCurrency='MYR',
        flightPriceBasis='provider_round_trip_ticket_price_requested_adults',
        selectedFlight=_synthetic_flight_quote(sandbox=True)))
    assert 'flight' not in b_sim['pendingExpenseCategories']

    # Not required flight -> flight NOT in pending
    b_not_req = calculateBudget(_base_trip(travelMode='public_transport'))
    assert 'flight' not in b_not_req['pendingExpenseCategories']

    # Undecided travelMode -> flight IS in pending
    b_undecided = calculateBudget(_base_trip(travelMode='undecided'))
    assert 'flight' in b_undecided['pendingExpenseCategories']

    # Flight mode without quote -> flight IS in pending
    b_unpriced = calculateBudget(_base_trip(travelMode='flight'))
    assert 'flight' in b_unpriced['pendingExpenseCategories']


# 12. RM256 included exactly once in known subtotal
def test_12_rm256_included_exactly_once_in_known_subtotal():
    # Synthetic equivalent of historical fixture MBdcQ3NF1onYkCXivEaJ
    trip = _base_trip(
        flightCost=256.0,
        flightCurrency='MYR',
        flightPriceBasis='provider_round_trip_ticket_price_requested_adults',
        flightSelectionStatus='selected',
        selectedFlight=_synthetic_flight_quote(price=256.0),
    )
    budget = calculateBudget(trip)

    assert budget['categoryTotals']['flight'] == 256.0
    assert budget['flight'] == 256.0
    # Expected: flight (256.0) + transport (105.0) + food (180.0) = 541.0
    assert budget['totalEstimatedCost'] == 541.0
    assert budget['knownEstimatedSubtotal'] == 541.0
    assert budget['total'] == 541.0
    assert budget['totalEstimatedCost'] == sum(budget['categoryTotals'].values())
    # Flight amount 256.0 is counted exactly once


# 13. Other incomplete expenses remain pending
def test_13_other_incomplete_expenses_remain_pending():
    trip = _base_trip(
        flightCost=256.0,
        flightCurrency='MYR',
        flightPriceBasis='provider_round_trip_ticket_price_requested_adults',
        flightSelectionStatus='selected',
        selectedFlight=_synthetic_flight_quote(),
        accommodationChoice='undecided',
        carRentalChoice='undecided',
    )

    budget = calculateBudget(trip)

    # Flight is resolved and NOT pending
    assert 'flight' not in budget['pendingExpenseCategories']
    # Other undecided expenses remain pending
    assert 'hotel' in budget['pendingExpenseCategories']
    assert 'carRental' in budget['pendingExpenseCategories']
    assert budget['completenessStatus'] == 'incomplete'
    assert budget['affordabilityStatus'] == 'incomplete'
    assert 'incomplete' in compareBudget(budget).lower()


# 14. Over-budget precedence preserved
def test_14_over_budget_precedence_preserved():
    trip = _base_trip(
        budgetLimit=500.0,
        flightCost=256.0,
        flightCurrency='MYR',
        flightPriceBasis='provider_round_trip_ticket_price_requested_adults',
        flightSelectionStatus='selected',
        selectedFlight=_synthetic_flight_quote(),
        accommodationChoice='undecided',  # hotel pending
    )

    budget = calculateBudget(trip)

    # Total is 541.0, exceeding budgetLimit of 500.0
    assert budget['totalEstimatedCost'] == 541.0
    assert budget['overBy'] == 41.0
    # Over-budget takes precedence over incomplete affordability status
    assert budget['status'] == 'over_budget'
    assert budget['affordabilityStatus'] == 'over_budget'
    assert budget['completenessStatus'] == 'incomplete'
    assert 'over budget by rm 41.00' in compareBudget(budget).lower()


# 15. No historical snapshot mutation
def test_15_no_historical_snapshot_mutation():
    trip = _base_trip(
        flightCost=256.0,
        flightCurrency='MYR',
        flightPriceBasis='provider_round_trip_ticket_price_requested_adults',
        flightSelectionStatus='selected',
        selectedFlight=_synthetic_flight_quote(),
    )
    original = deepcopy(trip)

    calculateBudget(trip)

    # The input dictionary must be identical and completely unmutated
    assert trip == original
    assert 'travelMode' not in trip


# 16. FR07 attachment and removal regressions remain correct
def test_16_fr07_attachment_and_removal_regressions():
    # FR07 flight attachment patch representation:
    attached_trip = _base_trip(
        travelMode='flight',
        flightCost=256.0,
        flightCurrency='MYR',
        flightPriceBasis='provider_round_trip_ticket_price_requested_adults',
        flightSelectionStatus='selected',
        selectedFlight=_synthetic_flight_quote(),
        accommodationChoice='return_home',
        carRentalChoice='not_required',
    )
    b_attached = calculateBudget(attached_trip)
    assert b_attached['expenseBreakdown']['flight']['state'] == 'priced'
    assert 'flight' not in b_attached['pendingExpenseCategories']

    # FR07 flight removal patch representation:
    removed_trip = _base_trip(
        travelMode='undecided',
        flightCost=0,
        flightCurrency=None,
        flightPriceBasis=None,
        flightSelectionStatus='removed',
        selectedFlight=None,
        accommodationChoice='return_home',
        carRentalChoice='not_required',
    )
    b_removed = calculateBudget(removed_trip)
    assert b_removed['flight'] == 0.0
    assert b_removed['expenseBreakdown']['flight']['state'] == 'undecided'
    assert 'flight' in b_removed['pendingExpenseCategories']

    # Historical document with flightSelectionStatus = 'removed' but missing travelMode:
    historical_removed = _base_trip(
        flightCost=0,
        flightSelectionStatus='removed',
        selectedFlight=None,
    )
    b_hist_removed = calculateBudget(historical_removed)
    assert b_hist_removed['flight'] == 0.0
    assert b_hist_removed['expenseBreakdown']['flight']['state'] == 'undecided'
    assert 'flight' in b_hist_removed['pendingExpenseCategories']


# 17. No regression for newly generated trips using B2B travelMode choices
def test_17_no_regression_for_newly_generated_b2b_travel_mode_choices():
    choices = ['flight', 'own_vehicle', 'public_transport', 'other', 'undecided']
    for mode in choices:
        trip = _base_trip(
            travelMode=mode,
            accommodationChoice='return_home',
            carRentalChoice='not_required',
        )
        b = calculateBudget(trip)
        if mode == 'flight':
            assert b['expenseBreakdown']['flight']['state'] == 'selected_unpriced'
            assert 'flight' in b['pendingExpenseCategories']
        elif mode == 'undecided':
            assert b['expenseBreakdown']['flight']['state'] == 'undecided'
            assert 'flight' in b['pendingExpenseCategories']
        elif mode == 'own_vehicle':
            assert b['expenseBreakdown']['flight']['state'] == 'not_required'
            assert 'ownVehicleFuelAndTolls' in b['excludedExpenseCategories']
            assert 'flight' not in b['pendingExpenseCategories']
        elif mode == 'other':
            assert b['expenseBreakdown']['flight']['state'] == 'not_required'
            assert 'otherTravel' in b['excludedExpenseCategories']
            assert 'flight' not in b['pendingExpenseCategories']
        elif mode == 'public_transport':
            assert b['expenseBreakdown']['flight']['state'] == 'not_required'
            assert 'flight' not in b['pendingExpenseCategories']
