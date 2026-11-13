from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from modules.fr05_smart_itinerary_budget_planner.routes import _alternative_state
from sequence_contract.domain_functions import calculateBudget, compareBudget, buildLowerCostAlternatives


P = 'modules.fr05_smart_itinerary_budget_planner.routes.'
F = 'modules.fr07_flight_search.routes.'
HEADERS = {'Authorization': 'Bearer valid_test_token'}
PATH = '/api/fr5/itineraries/trip/lower-cost-alternatives'


@contextmanager
def _fixture():
    segment = {'departureAirportCode': 'KUL', 'arrivalAirportCode': 'PEN',
               'departureDate': '2026-11-01', 'arrivalDate': '2026-11-01'}
    old_flight = {'price': 200, 'currency': 'MYR', 'priceBasis': 'group_total',
                  'travellerCount': 2, 'outboundSegments': [segment], 'returnSegments': []}
    option = {**old_flight, 'price': 120, 'optionId': 'option', 'quoteCompleteness': 'complete',
              'budgetEligible': True, 'source': 'test_fixture', 'transactionMode': 'planning_reference'}
    quote = {'id': 'search', 'travellerId': 'test_traveller_uid',
             'expiresAt': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
             'criteria': {'traveller_count': 2, 'outbound_date': '2026-11-01',
                          'departure_id': 'KUL', 'arrival_id': 'PEN'}, 'items': [option]}
    criteria = {'checkin': '2026-11-01', 'checkout': '2026-11-03', 'adults': 2,
                'roomQuantity': 1, 'destination': 'Penang'}
    booking = {'travellerId': 'test_traveller_uid', 'bookingStatus': 'confirmed',
               'hotelCurrency': 'MYR', 'hotelCost': 120, 'amountSource': 'validated_offer',
               'stayCriteria': criteria, 'selectedHotel': {'currency': 'MYR', 'sandbox': True},
               'source': 'sandbox_fixture'}
    bookings = {'new': booking, 'old': {**deepcopy(booking), 'hotelCost': 200}}
    trip = {'id': 'trip', 'title': 'Existing trip', 'travellerId': 'test_traveller_uid',
            'destinationArea': 'Penang', 'startDate': '2026-11-01', 'endDate': '2026-11-03',
            'travellerCount': 2, 'budgetLimit': 100, 'activities': [],
            'flightCost': 200, 'flightCurrency': 'MYR', 'flightPriceBasis': 'group_total',
            'selectedFlight': old_flight, 'travelMode': 'flight',
            'hotelCost': 200, 'hotelCurrency': 'MYR', 'hotelBookingId': 'old',
            'selectedHotel': {'currency': 'MYR'}, 'accommodationChoice': 'paid_hotel',
            'carRentalChoice': 'not_required'}
    trip['budgetEstimate'] = calculateBudget(trip)

    def retrieve(collection, doc_id=None, **kwargs):
        if collection == 'itineraries':
            return deepcopy(trip)
        if collection == 'hotel_bookings':
            if doc_id is None:
                return [{'id': key, **deepcopy(row)} for key, row in bookings.items()]
            return deepcopy(bookings.get(doc_id))
        return None

    def persist(collection, doc_id, values):
        assert collection == 'itineraries' and doc_id == 'trip'
        trip.update(deepcopy(values))
        return deepcopy(trip)

    with patch(P + 'retrieveRecord', side_effect=retrieve), \
         patch(P + '_commit_cost_alternative', side_effect=lambda iid, expected, changes: persist('itineraries', iid, changes)) as update, \
         patch(P + 'storeRecord') as store, \
         patch('services.serpapi_service.retrieveFlightOptions', side_effect=AssertionError('No provider calls')), \
         patch(P + '_fallback_mode', return_value=True), \
         patch.dict(F + '_FLIGHT_QUOTES', {'search': quote}, clear=True), \
         patch(F + 'retrieveRecord', return_value=None):
        yield trip, quote, bookings, update, store


@pytest.mark.parametrize('kind,old_saving', [('transport', 45), ('food', 35), ('schedule', 25)])
def test_empty_preview_has_one_guidance_message_and_legacy_strategies_cannot_apply(client, mock_traveller_auth, kind, old_saving):
    with _fixture() as (trip, _, _, update, store):
        trip.update(hotelBookingId=None, accommodationChoice='undecided', hotelCost=0)
        original = deepcopy(trip)
        response = client.post(PATH, headers=HEADERS, json={})
        assert response.status_code == 200
        assert response.json['alternatives'] == []
        assert response.json['activityAlternativeStatus'] == 'priced_replacement_unavailable'
        for _ in range(2):
            result = client.post(PATH + '/apply', headers=HEADERS,
                                 json={'type': kind, 'saving': old_saving, 'estimatedSavings': 999999})
            assert result.status_code == 409
        assert trip == original
        update.assert_not_called()
        store.assert_not_called()


@pytest.mark.parametrize('kind,reference', [
    ('flight', {'searchId': 'search', 'optionId': 'option'}),
    ('hotel', {'hotelBookingId': 'new'}),
])
def test_valid_reference_apply_ignores_client_money_and_persists_reload_once(
        client, mock_traveller_auth, kind, reference):
    with _fixture() as (trip, _, _, update, store):
        response = client.post(PATH + '/apply', headers=HEADERS, json={
            'type': kind, 'data': {**reference, 'price': -999, 'currency': 'USD'}, 'saving': 999999})
        assert response.status_code == 200, response.json
        assert trip[f'{kind}Cost'] == 120
        assert response.json['applied']['estimatedSavings'] == 80
        expected_budget = calculateBudget(trip)
        expected_budget['comparison'] = compareBudget(expected_budget)
        assert response.json['budget'] == expected_budget
        assert sum(response.json['budget']['categoryTotals'].values()) == response.json['budget']['totalEstimatedCost']
        assert all(value >= 0 for value in response.json['budget']['categoryTotals'].values())
        repeated = client.post(PATH + '/apply', headers=HEADERS, json={'type': kind, 'data': reference})
        assert repeated.status_code == 200 and repeated.json['reused'] is True
        assert update.call_count == 1
        reloaded = client.get('/api/fr5/itineraries/trip', headers=HEADERS)
        assert reloaded.status_code == 200
        assert reloaded.json['itinerary']['budgetEstimate'] == expected_budget
        assert trip['activities'] == []
        store.assert_not_called()


@pytest.mark.parametrize('change', ['expired', 'wrong_owner', 'count', 'date', 'currency', 'missing', 'id', 'stale'])
def test_invalid_or_stale_flight_references_never_mutate(client, mock_traveller_auth, change):
    with _fixture() as (trip, quote, _, update, store):
        payload = {'type': 'flight', 'data': {'searchId': 'search', 'optionId': 'option'}}
        if change == 'expired':
            quote['expiresAt'] = '2000-01-01T00:00:00+00:00'
        elif change == 'wrong_owner':
            quote['travellerId'] = 'another-user'
        elif change == 'count':
            trip['travellerCount'] = 4
        elif change == 'date':
            trip['startDate'] = '2026-11-02'
        elif change == 'currency':
            quote['items'][0]['currency'] = 'USD'
        elif change == 'missing':
            payload['data']['optionId'] = 'missing'
        elif change == 'id':
            payload['alternativeId'] = 'invalid-reference'
        elif change == 'stale':
            payload['stateVersion'] = _alternative_state(trip)
            trip['budgetLimit'] += 1
        original = deepcopy(trip)
        result = client.post(PATH + '/apply', headers=HEADERS, json=payload)
        assert result.status_code == 409, result.json
        assert trip == original
        update.assert_not_called()
        store.assert_not_called()


@pytest.mark.parametrize('change', ['missing', 'owner', 'cancelled', 'currency', 'rooms', 'dates'])
def test_invalid_hotel_booking_reference_is_rejected(client, mock_traveller_auth, change):
    with _fixture() as (trip, _, bookings, update, store):
        booking = bookings['new']
        if change == 'missing':
            del bookings['new']
        elif change == 'owner':
            booking['travellerId'] = 'another-user'
        elif change == 'cancelled':
            booking['bookingStatus'] = 'cancelled'
        elif change == 'currency':
            booking['hotelCurrency'] = 'USD'
        elif change == 'rooms':
            booking['stayCriteria']['roomQuantity'] = 2
        elif change == 'dates':
            trip['endDate'] = '2026-11-02'
        original = deepcopy(trip)
        response = client.post(PATH + '/apply', headers=HEADERS,
                               json={'type': 'hotel', 'data': {'hotelBookingId': 'new'}})
        assert response.status_code == 409
        assert trip == original
        update.assert_not_called()
        store.assert_not_called()


def test_authentication_and_ownership_are_preserved(client, mock_traveller_auth):
    with _fixture() as (trip, _, _, update, _):
        assert client.post(PATH + '/apply', json={'type': 'food'}).status_code == 401
        trip['travellerId'] = 'another-user'
        assert client.post(PATH + '/apply', headers=HEADERS, json={'type': 'food'}).status_code == 404
        update.assert_not_called()


def test_raw_prices_and_negative_or_unknown_prices_cannot_create_savings():
    trip = {'flightCost': 200, 'hotelCost': 200}
    for price in [None, -1, 0, float('nan'), 100]:
        options = buildLowerCostAlternatives([{'price': price}], [{'price': price}], {'overBy': 0}, trip)
        assert all(item['isAdvisory'] and not item['canApply'] and 'estimatedSavings' not in item for item in options)


def test_preview_resolves_authoritative_prices_and_rejects_changed_state(client, mock_traveller_auth):
    with _fixture() as (trip, _, _, update, store), \
         patch(P + '_flight_alternative_options', return_value=[
             {'searchId': 'search', 'optionId': 'option', 'price': 1},
             {'searchId': 'search', 'optionId': 'option', 'price': 1},
         ]):
        original = deepcopy(trip)
        response = client.post(PATH, headers=HEADERS, json={})
        assert response.status_code == 200
        actionable = [item for item in response.json['alternatives'] if item['canApply']]
        assert len(actionable) == 2
        assert response.json['duplicateAlternativeCount'] == 1
        assert {item['alternativeType'] for item in actionable} == {'flight', 'hotel'}
        assert all(item['estimatedSavings'] == 80 and item['data']['price'] == 120 for item in actionable)
        assert all(item['data']['source'] for item in actionable)
        assert trip == original
        update.assert_not_called()
        store.assert_not_called()
        trip['travellerCount'] = 4
        changed = deepcopy(trip)
        result = client.post(PATH + '/apply', headers=HEADERS, json={'alternative': actionable[0]})
        assert result.status_code == 409 and result.json['code'] == 'STALE_ALTERNATIVE'
        assert trip == changed
        update.assert_not_called()


@pytest.mark.parametrize('price', [True, 0, -10, float('nan'), float('inf'), 250])
def test_invalid_or_not_cheaper_server_prices_are_not_applied(client, mock_traveller_auth, price):
    with _fixture() as (trip, quote, _, update, _):
        quote['items'][0]['price'] = price
        original = deepcopy(trip)
        result = client.post(PATH + '/apply', headers=HEADERS,
                             json={'type': 'flight', 'data': {'searchId': 'search', 'optionId': 'option'}})
        assert result.status_code == 409
        assert trip == original
        update.assert_not_called()


def test_different_hotel_identity_with_same_validated_pricing_scope_is_allowed(client, mock_traveller_auth):
    with _fixture() as (trip, _, bookings, update, _):
        bookings['old']['stayCriteria']['hotelIds'] = ['previous-property']
        bookings['new']['stayCriteria']['hotelIds'] = ['different-property']
        response = client.post(PATH + '/apply', headers=HEADERS,
                               json={'type': 'hotel', 'data': {'hotelBookingId': 'new'}})
        assert response.status_code == 200, response.json
        assert trip['hotelBookingId'] == 'new' and update.call_count == 1


@pytest.mark.parametrize('error_type', [RuntimeError, ValueError])
def test_persistence_failure_has_no_false_success_or_exception_disclosure(client, mock_traveller_auth, error_type):
    with _fixture() as (trip, _, _, update, store):
        original = deepcopy(trip)
        update.side_effect = error_type('sensitive-internal-error')
        result = client.post(PATH + '/apply', headers=HEADERS,
                             json={'type': 'flight', 'data': {'searchId': 'search', 'optionId': 'option'}})
        assert result.status_code == 503
        assert 'sensitive-internal-error' not in result.get_data(as_text=True)
        assert result.json['ok'] is False
        assert trip == original and update.call_count == 1
        store.assert_not_called()


def test_atomic_commit_rejects_concurrent_stale_budget_updates(app):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock
    from types import SimpleNamespace
    from flask import g
    from modules.fr05_smart_itinerary_budget_planner.routes import _commit_cost_alternative

    initial = {'id': 'trip', 'travellerId': 'test_traveller_uid', 'flightCost': 200}
    saved = deepcopy(initial)
    lock, barrier = Lock(), Barrier(2)
    writes = []

    class TransactionDatabase:
        def collection(self, name):
            assert name == 'itineraries'
            return self

        def document(self, iid):
            assert iid == 'trip'
            return self

        def transaction(self):
            return self

        def get(self, transaction):
            return SimpleNamespace(id='trip', exists=True, to_dict=lambda: deepcopy(saved))

        def update(self, ref, values):
            saved.update(deepcopy(values))
            writes.append(deepcopy(values))

    def serializable_transaction(function):
        def run(transaction):
            with lock:
                return function(transaction)
        return run

    def worker(cost):
        with app.test_request_context():
            g.uid = 'test_traveller_uid'
            barrier.wait(timeout=5)
            try:
                return _commit_cost_alternative('trip', initial,
                    {'flightCost': cost, 'budgetEstimate': {'flight': cost, 'total': cost}})
            except ValueError:
                return 'stale'

    with patch('sequence_contract.firebase_firestore.get_db', return_value=TransactionDatabase()), \
         patch('firebase_admin.firestore.transactional', side_effect=serializable_transaction):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, [100, 120]))
    assert results.count('stale') == 1
    assert len(writes) == 1
    assert saved['flightCost'] == saved['budgetEstimate']['flight'] == saved['budgetEstimate']['total']
