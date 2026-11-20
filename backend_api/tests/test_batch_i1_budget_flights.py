from copy import deepcopy
from datetime import date, timedelta
from unittest.mock import Mock

import pytest
from modules.fr05_smart_itinerary_budget_planner import routes
from sequence_contract.domain_functions import calculateBudget
from services.trip_budget_replan import preview_budget_replan
from test_local_reviews import memory, headers


def trip():
    start = (date.today() + timedelta(days=20)).isoformat()
    end = (date.today() + timedelta(days=22)).isoformat()
    segment = {'departureAirportCode': 'KUL', 'arrivalAirportCode': 'PEN', 'departureDate': start,
               'arrivalDate': start, 'travelClass': 'Economy'}
    return {'id': 'owned', 'travellerId': 'owner', 'status': 'planned', 'startDate': start, 'endDate': end,
            'destinationArea': 'Penang', 'travellerCount': 2, 'budgetLimit': 700, 'travelMode': 'flight',
            'flightCost': 263, 'flightCurrency': 'MYR', 'flightPriceBasis': 'group_total',
            'foodCost': 360, 'transportCost': 105, 'accommodationChoice': 'undecided',
            'carRentalChoice': 'undecided', 'activities': [{'activityId': 'a', 'activityName': 'Unpriced visit'}],
            'selectedFlight': {'price': 263, 'currency': 'MYR', 'priceBasis': 'group_total',
                               'travellerCount': 2, 'planningOnly': True, 'outboundSegments': [segment]}}


@pytest.mark.parametrize('change,text', [
    ({'selectedFlight': None}, 'No selected flight'),
    ({'flightCurrency': 'USD'}, 'currency'),
    ({'flightCost': 900}, 'amount'),
    ({'flightPriceBasis': None}, 'price basis'),
    ({'flightPaymentId': 'protected'}, 'paid or booking'),
])
def test_flight_rejection_explains_and_never_searches(change, text, monkeypatch):
    current = {**trip(), **change}
    provider = Mock(side_effect=AssertionError('No live provider'))
    monkeypatch.setattr('services.serpapi_service.retrieveFlightOptions', provider)
    diagnostic = routes._flight_comparison_diagnostics(current)
    assert diagnostic['status'] == 'needs_review'
    assert text in ' '.join(diagnostic['reasons'])
    assert routes._flight_alternative_options(current) == []
    provider.assert_not_called()


def test_count_and_cabin_missing_are_distinguished_and_valid_scope_is_eligible():
    current = trip()
    assert routes._flight_comparison_diagnostics(current)['status'] == 'eligible'
    current['selectedFlight'].pop('travellerCount')
    assert 'passenger count' in ' '.join(routes._flight_comparison_diagnostics(current)['reasons'])
    current['selectedFlight']['outboundSegments'][0].pop('travelClass')
    assert 'cabin class' in ' '.join(routes._flight_comparison_diagnostics(current)['reasons'])


def test_reported_728_case_preview_cancel_apply_reopen_isolated(client, memory, monkeypatch):
    current = trip()
    state = {'owned': deepcopy(current)}
    writes = []
    monkeypatch.setattr(routes, '_own', lambda identity: deepcopy(state.get(identity)))
    def update(collection, identity, patch, expected=None):
        assert state[identity] == expected
        state[identity].update(deepcopy(patch)); writes.append(identity)
        return deepcopy(state[identity])
    monkeypatch.setattr(routes, 'updateRecord', update)
    path = '/api/fr5/itineraries/owned/budget-replan'
    initial = client.get(path, headers=headers()).json
    assert initial['budget']['knownEstimatedSubtotal'] == 728
    assert initial['budget']['flight'] == 263
    assert 'carRental' not in initial['budget']['pendingExpenseCategories']
    changes = {'foodCost': 320}
    command = {'changes': changes, 'stateVersion': initial['stateVersion']}
    preview = client.post(path + '/preview', headers=headers(), json=command)
    assert preview.status_code == 200
    assert preview.json['estimatedReduction'] == 40
    assert preview.json['budget']['knownEstimatedSubtotal'] == 688
    assert 'hotel' in preview.json['budget']['pendingExpenseCategories']
    assert preview.json['budget']['affordabilityStatus'] != 'within_budget'
    # Cancel/back does not call apply and persists nothing.
    assert state['owned'] == current and not writes
    assert client.post(path + '/apply', headers=headers(), json={**command, 'previewToken': preview.json['previewToken']}).status_code == 409
    assert not writes
    accepted = {**command, 'confirmed': True, 'previewToken': preview.json['previewToken']}
    assert client.post(path + '/apply', headers=headers(), json=accepted).status_code == 200
    reopened = client.get(path, headers=headers()).json
    assert reopened['budget']['food'] == 320 and reopened['budget']['knownEstimatedSubtotal'] == 688
    assert state['owned']['selectedFlight'] == current['selectedFlight']
    assert client.post(path + '/apply', headers=headers(), json=accepted).status_code == 409
    assert writes == ['owned']


def test_paid_flight_selection_is_blocked_before_quote_resolution(client, memory, monkeypatch):
    from modules.fr07_flight_search import routes as flights
    current = trip()
    current['flightPaymentId'] = 'protected'
    monkeypatch.setattr(flights, '_own_itinerary', lambda _: current)
    quotes = Mock(side_effect=AssertionError('No quote or payment mutation'))
    monkeypatch.setattr(flights, '_quote_item', quotes)
    response = client.post('/api/fr7/flights/select', headers=headers(), json={'itineraryId': 'owned'})
    assert response.status_code == 409
    quotes.assert_not_called()


@pytest.mark.parametrize('count', [None, 1, 3, True])
def test_quote_cannot_attach_to_different_or_missing_trip_passenger_count(client, memory, monkeypatch, count):
    from modules.fr07_flight_search import routes as flights
    current = trip()
    current['travellerCount'] = count
    monkeypatch.setattr(flights, '_own_itinerary', lambda _: current)
    option = {**current['selectedFlight'], 'quoteCompleteness': 'complete'}
    monkeypatch.setattr(flights, '_quote_item', lambda payload: ({'id': 'owned-quote', 'criteria': {}}, option, None))
    update = Mock(side_effect=AssertionError('No write for incompatible passenger count'))
    monkeypatch.setattr(flights, 'updateRecord', update)
    response = client.post('/api/fr7/flights/select', headers=headers(), json={'itineraryId': 'owned'})
    assert response.status_code == 409 and response.json['code'] == 'flight_trip_passenger_mismatch'
    update.assert_not_called()
