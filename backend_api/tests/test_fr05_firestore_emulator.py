"""Opt-in real SDK/transaction acceptance; never connects to a real project.

Run with FIRESTORE_EMULATOR_HOST=127.0.0.1:18085,
GOOGLE_CLOUD_PROJECT=demo-travelmate-fr05-f2ce,
TRAVELMATE_FIRESTORE_EMULATOR_ACCEPTANCE=1 and pytest -m integration
--allow-hosts=127.0.0.1 --timeout=90. Start the cached emulator separately
with --project_id demo-travelmate-fr05-f2ce --single_project_mode_error true.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from google.cloud.firestore_v1.transaction import Transaction

from modules.fr05_smart_itinerary_budget_planner import routes
from modules.fr07_flight_search import routes as flights
from sequence_contract.domain_functions import calculateBudget, compareBudget


pytestmark = pytest.mark.integration
PROJECT = 'demo-travelmate-fr05-f2ce'
HOST = '127.0.0.1:18085'
HEADERS = {'Authorization': 'Bearer valid_test_token'}


@pytest.fixture
def emulator(monkeypatch, block_live_firebase):
    # Validate configuration before constructing a channel or issuing any write.
    assert os.environ.get('TRAVELMATE_FIRESTORE_EMULATOR_ACCEPTANCE') == '1'
    assert os.environ.get('FIRESTORE_EMULATOR_HOST') == HOST
    assert os.environ.get('GOOGLE_CLOUD_PROJECT') == PROJECT
    for name in ('GOOGLE_APPLICATION_CREDENTIALS', 'FIREBASE_SERVICE_ACCOUNT',
                 'FIREBASE_SERVICE_ACCOUNT_JSON'):
        assert not os.environ.get(name), f'{name} must be disabled'
    db = firestore.Client(project=PROJECT, credentials=AnonymousCredentials(),
                          client_options={'api_endpoint': HOST})
    assert db.project == PROJECT and db._emulator_host == HOST
    assert db._firestore_api.transport._host == HOST
    assert isinstance(db._credentials, AnonymousCredentials)

    def forbidden(*args, **kwargs):
        raise AssertionError('Production credentials/providers forbidden in emulator acceptance')

    monkeypatch.setattr('google.auth.default', forbidden)
    monkeypatch.setattr('firebase_service.init_firebase', forbidden)
    monkeypatch.setattr('sequence_contract.firebase_firestore.get_db', lambda: db)
    monkeypatch.setattr(routes, 'retrieveLowerCostFlights', forbidden)
    monkeypatch.setattr(flights, 'retrieveFlightOptions', forbidden)
    monkeypatch.setattr(flights, '_FLIGHT_QUOTES', {})
    monkeypatch.setattr(flights, '_TEST_DURABLE_QUOTES', {})
    yield db
    db.close()


@pytest.fixture
def stay(emulator, mock_traveller_auth):
    tag = 'f2ce-' + uuid4().hex
    uid = 'test_traveller_uid'
    trip_id, search_id = tag + '-trip', tag + '-search'
    old_id, new_id = tag + '-old', tag + '-new'
    segment = {'departureAirportCode': 'KUL', 'arrivalAirportCode': 'PEN',
               'departureDate': '2026-11-01', 'arrivalDate': '2026-11-01'}
    old_flight = {'price': 200, 'currency': 'MYR', 'priceBasis': 'group_total',
                  'travellerCount': 2, 'outboundSegments': [segment], 'returnSegments': []}
    option = {**old_flight, 'price': 120, 'optionId': 'option',
              'quoteCompleteness': 'complete', 'budgetEligible': True,
              'source': 'emulator_fixture', 'transactionMode': 'planning_reference'}
    quote = {'id': search_id, 'travellerId': uid,
             'expiresAt': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
             'criteria': {'traveller_count': 2, 'outbound_date': '2026-11-01',
                          'departure_id': 'KUL', 'arrival_id': 'PEN'}, 'items': [option]}
    booking = {'travellerId': uid, 'bookingStatus': 'confirmed',
               'hotelCurrency': 'MYR', 'hotelCost': 120, 'amountSource': 'validated_offer',
               'stayCriteria': {'checkin': '2026-11-01', 'checkout': '2026-11-03',
                                'adults': 2, 'roomQuantity': 1, 'destination': 'Penang'},
               'selectedHotel': {'currency': 'MYR', 'sandbox': True},
               'source': 'emulator_fixture'}
    trip = {'title': 'Synthetic emulator acceptance only', 'travellerId': uid,
            'destinationArea': 'Penang', 'startDate': '2026-11-01', 'endDate': '2026-11-03',
            'travellerCount': 2, 'budgetLimit': 1500, 'activities': [],
            'flightCost': 200, 'flightCurrency': 'MYR', 'flightPriceBasis': 'group_total',
            'selectedFlight': old_flight, 'travelMode': 'flight',
            'hotelCost': 200, 'hotelCurrency': 'MYR', 'hotelBookingId': old_id,
            'selectedHotel': {'currency': 'MYR'}, 'accommodationChoice': 'paid_hotel',
            'carRentalChoice': 'undecided', 'createdAt': firestore.SERVER_TIMESTAMP}
    # The timestamp round-trip also exercises hashing of real SDK snapshots.
    trip['budgetEstimate'] = calculateBudget(trip)
    refs = [emulator.collection('itineraries').document(trip_id),
            emulator.collection('flight_quotes').document(flights._quote_doc_id(uid, search_id)),
            emulator.collection('hotel_bookings').document(old_id),
            emulator.collection('hotel_bookings').document(new_id)]
    try:
        for ref, value in zip(refs, [trip, quote, {**deepcopy(booking), 'hotelCost': 200}, booking]):
            ref.set(value, timeout=10)
        yield {'db': emulator, 'trip': refs[0], 'quote': refs[1], 'hotel': refs[3],
               'path': f'/api/fr5/itineraries/{trip_id}/lower-cost-alternatives/apply',
               'trip_id': trip_id, 'flight': {'searchId': search_id, 'optionId': 'option'},
               'hotel_reference': {'hotelBookingId': new_id}}
    finally:
        # Never flush a database or delete documents not created by this fixture.
        for ref in refs:
            ref.delete(timeout=10)


def _apply(client, stay, kind, **extra):
    data = stay['flight'] if kind == 'flight' else stay['hotel_reference']
    return client.post(stay['path'], headers=HEADERS,
                       json={'type': kind, 'data': {**data, 'price': -999, 'currency': 'USD'},
                             'estimatedSavings': 999999, **extra})


def _assert_budget(saved):
    expected = calculateBudget(saved)
    expected['comparison'] = compareBudget(expected)
    assert saved['budgetEstimate'] == expected
    assert expected['budgetLimit'] == 1500
    assert sum(expected['categoryTotals'].values()) == expected['totalEstimatedCost']
    assert all(value >= 0 for value in expected['categoryTotals'].values())
    assert expected['completenessStatus'] == 'incomplete'
    assert expected['expenseBreakdown']['carRental']['state'] == 'undecided'
    assert 'carRental' in expected['pendingExpenseCategories']


@pytest.mark.parametrize('kind', ['transport', 'food', 'schedule', 'activity'])
def test_advisory_rejection_does_not_persist(client, stay, kind):
    before = stay['trip'].get(timeout=10)
    response = _apply(client, stay, kind)
    assert response.status_code == 409
    expected = 'ACTIVITY_REPLACEMENT_UNAVAILABLE' if kind == 'activity' else 'ADVISORY_ALTERNATIVE'
    assert response.json['code'] == expected
    after = stay['trip'].get(timeout=10)
    assert before.to_dict() == after.to_dict() and before.update_time == after.update_time


@pytest.mark.parametrize('kind', ['flight', 'hotel'])
def test_real_transaction_apply_reload_and_repeat(client, stay, kind):
    before = stay['trip'].get(timeout=10)
    response = _apply(client, stay, kind)
    assert response.status_code == 200, response.json
    assert response.json['applied']['estimatedSavings'] == 80
    saved = stay['trip'].get(timeout=10)
    assert saved.to_dict()[f'{kind}Cost'] == 120
    assert saved.update_time != before.update_time
    _assert_budget(saved.to_dict())
    reloaded = client.get(f"/api/fr5/itineraries/{stay['trip_id']}", headers=HEADERS)
    assert reloaded.status_code == 200
    assert reloaded.json['itinerary']['budgetEstimate'] == saved.to_dict()['budgetEstimate']
    repeated = _apply(client, stay, kind)
    assert repeated.status_code == 200 and repeated.json['reused'] is True
    assert stay['trip'].get(timeout=10).update_time == saved.update_time


@pytest.mark.parametrize('kind,invalid', [('flight', 'expired'), ('flight', 'owner'),
                                         ('flight', 'missing'), ('hotel', 'cancelled'),
                                         ('hotel', 'owner')])
def test_invalid_references_do_not_persist(client, stay, kind, invalid):
    if kind == 'flight':
        if invalid == 'expired':
            stay['quote'].update({'expiresAt': '2000-01-01T00:00:00+00:00'})
        elif invalid == 'owner':
            stay['quote'].update({'travellerId': 'another-emulator-user'})
        else:
            stay['quote'].delete()
    else:
        stay['hotel'].update({'bookingStatus': 'cancelled'} if invalid == 'cancelled'
                             else {'travellerId': 'another-emulator-user'})
    before = stay['trip'].get(timeout=10)
    response = _apply(client, stay, kind)
    assert response.status_code == 409, response.json
    after = stay['trip'].get(timeout=10)
    assert after.to_dict() == before.to_dict() and after.update_time == before.update_time


def test_stale_preview_is_rejected_without_write(client, stay):
    before = {'id': stay['trip_id'], **stay['trip'].get(timeout=10).to_dict()}
    version = routes._alternative_state(before)
    stay['trip'].update({'title': 'Changed in emulator after preview'})
    changed = stay['trip'].get(timeout=10)
    response = _apply(client, stay, 'flight', stateVersion=version)
    assert response.status_code == 409 and response.json['code'] == 'STALE_ALTERNATIVE'
    assert stay['trip'].get(timeout=10).update_time == changed.update_time


@pytest.mark.parametrize('change', ['owner', 'budget'])
def test_transaction_rechecks_current_document(client, stay, monkeypatch, change):
    real_commit = routes._commit_cost_alternative
    changed = []

    def modify_then_commit(iid, expected, patch):
        stay['trip'].update({'travellerId': 'another-emulator-user'} if change == 'owner'
                            else {'budgetLimit': 1600})
        changed.append(stay['trip'].get(timeout=10))
        return real_commit(iid, expected, patch)

    monkeypatch.setattr(routes, '_commit_cost_alternative', modify_then_commit)
    response = _apply(client, stay, 'flight')
    assert response.status_code == 409 and response.json['code'] == 'STALE_ALTERNATIVE'
    saved = stay['trip'].get(timeout=10)
    assert saved.to_dict() == changed[0].to_dict() and saved.update_time == changed[0].update_time
    assert saved.to_dict()['flightCost'] == 200


def test_real_concurrent_transactions_allow_only_one_state_change(app, stay, monkeypatch):
    real_commit = routes._commit_cost_alternative
    barrier = Barrier(2)

    def synchronize(iid, expected, patch):
        barrier.wait(timeout=15)
        return real_commit(iid, expected, patch)

    monkeypatch.setattr(routes, '_commit_cost_alternative', synchronize)

    def worker(kind):
        with app.test_client() as client:
            response = _apply(client, stay, kind)
            return kind, response.status_code, response.json

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, ['flight', 'hotel']))
    assert sorted(status for _, status, _ in results) == [200, 409], results
    winner = next(kind for kind, status, _ in results if status == 200)
    loser = next(body for _, status, body in results if status == 409)
    assert loser['code'] == 'STALE_ALTERNATIVE'
    saved = stay['trip'].get(timeout=10).to_dict()
    assert saved[f'{winner}Cost'] == 120
    assert saved['hotelCost' if winner == 'flight' else 'flightCost'] == 200
    _assert_budget(saved)


def test_server_rejected_atomic_commit_leaves_no_partial_update(client, stay, monkeypatch):
    real_commit = Transaction._commit
    missing = stay['db'].collection('itineraries').document('f2ce-missing-' + uuid4().hex)
    assert not missing.get(timeout=10).exists

    def commit_with_missing_document(transaction):
        # The emulator must reject this actual multi-write commit atomically.
        transaction.update(missing, {'mustNotExist': True})
        return real_commit(transaction)

    monkeypatch.setattr(Transaction, '_commit', commit_with_missing_document)
    before = stay['trip'].get(timeout=10)
    response = _apply(client, stay, 'flight')
    assert response.status_code == 503 and response.json['ok'] is False
    assert missing.id not in response.get_data(as_text=True)
    after = stay['trip'].get(timeout=10)
    assert after.to_dict() == before.to_dict() and after.update_time == before.update_time
    assert not missing.get(timeout=10).exists
