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
from google.cloud.firestore_v1.document import DocumentReference

from modules.fr05_smart_itinerary_budget_planner import routes
from modules.fr07_flight_search import routes as flights
from sequence_contract.domain_functions import calculateBudget, compareBudget


pytestmark = pytest.mark.integration
PROJECT = 'demo-travelmate-fr05-f2ce'
HOST = os.getenv('TRAVELMATE_TEST_FIRESTORE_LOOPBACK', '127.0.0.1:18085')
assert HOST in {'127.0.0.1:18085', '127.0.0.1:18086'}
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
    monkeypatch.setattr('services.serpapi_service.retrieveFlightOptions', forbidden)
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
    real_update = DocumentReference.update
    missing = stay['db'].collection('itineraries').document('f2ce-missing-' + uuid4().hex)
    assert not missing.get(timeout=10).exists

    def commit_with_missing_document(ref, values, option=None, **kwargs):
        # Send the real conditional write to a missing document to verify server rejection.
        if ref.path == stay['trip'].path:
            return real_update(missing, values, option=option, **kwargs)
        return real_update(ref, values, option=option, **kwargs)

    monkeypatch.setattr(DocumentReference, 'update', commit_with_missing_document)
    before = stay['trip'].get(timeout=10)
    response = _apply(client, stay, 'flight')
    assert response.status_code == 409 and response.json['code'] == 'STALE_ALTERNATIVE'
    assert missing.id not in response.get_data(as_text=True)
    after = stay['trip'].get(timeout=10)
    assert after.to_dict() == before.to_dict() and after.update_time == before.update_time
    assert not missing.get(timeout=10).exists


def test_package_packing_persists_separately_in_firestore(client, emulator, mock_traveller_auth, monkeypatch):
    from services import packing_weather, packing_checklist_service
    trip_id = 'package-' + uuid4().hex
    uid = 'test_traveller_uid'
    trip = {'travellerId': uid, 'packageTrip': True, 'tripType': 'package',
            'destinationArea': 'Butterworth', 'startDate': '2099-11-12', 'endDate': '2099-11-12',
            'packageSnapshot': {'amount': 75, 'itineraryDays': [{'activities': ['Heritage city walk']}]}}
    trip_ref = emulator.collection('itineraries').document(trip_id)
    checklist_ref = emulator.collection('packing_checklists').document(
        packing_checklist_service.checklist_id(uid, trip_id))
    path = f'/api/fr5/itineraries/{trip_id}/packing-checklist'
    monkeypatch.setattr(packing_weather, 'geocode', lambda *a, **kw: pytest.fail('No geocode for distant trips'))
    trip_ref.set(trip)
    try:
        result = client.post(path, headers=HEADERS, json={})
        assert result.status_code == 200, result.json
        assert result.json['checklist']['tripId'] == trip_id
        assert any(row['itemId'] == 'walking_shoes' for row in result.json['checklist']['items'])
        edited = client.patch(path, headers=HEADERS, json={'action': 'add', 'expectedRevision': 1,
            'itemId': 'custom_camera', 'name': 'Camera', 'category': 'electronics', 'quantity': 2, 'isPacked': True})
        assert edited.status_code == 200, edited.json
        refreshed = client.post(path, headers=HEADERS, json={'action': 'refresh', 'expectedRevision': 2})
        assert refreshed.status_code == 200, refreshed.json
        assert client.get(path, headers=HEADERS).json['progress']['packedItems'] == 1
        assert checklist_ref.get().to_dict()['tripId'] == trip_id
        assert trip_ref.get().to_dict() == trip
    finally:
        checklist_ref.delete()
        trip_ref.delete()


def test_expense_storage_in_firestore_reloads_and_keeps_orders_immutable(client, emulator, mock_traveller_auth):
    trip_id = 'manual-' + uuid4().hex
    order_id = 'paid-' + uuid4().hex
    hotel_id = 'stay-' + uuid4().hex
    trip = {'travellerId': 'test_traveller_uid', 'title': 'Penang', 'budgetLimit': 100,
            'hotelBookingId': hotel_id,
            'startDate': '2026-11-15', 'endDate': '2026-11-15', 'activities': [],
            'purchasedPackages': [{'checkoutOrderId': order_id}, {'checkoutOrderId': order_id}]}
    paid = {'travellerId': 'test_traveller_uid', 'fulfilledTripId': trip_id, 'status': 'paid',
            'paymentStatus': 'paid', 'amountMinor': 4200, 'currency': 'MYR'}
    trip_ref = emulator.collection('itineraries').document(trip_id)
    order_ref = emulator.collection('checkout_orders').document(order_id)
    hotel_ref = emulator.collection('hotel_bookings').document(hotel_id)
    path = f'/api/fr5/itineraries/{trip_id}/expenses'
    trip_ref.set(trip)
    order_ref.set(paid)
    hotel_ref.set({'travellerId': 'test_traveller_uid', 'bookingStatus': 'confirmed',
                   'hotelCurrency': 'MYR', 'amountSource': 'validated_offer', 'hotelCost': 40})
    try:
        before = client.get(path, headers=HEADERS)
        assert before.status_code == 200, before.json
        assert before.json['overview']['verifiedMinor'] == 4200
        assert before.json['overview']['committedHotelMinor'] == 4000
        hotel_ref.update({'sandbox': True})
        assert client.get(path, headers=HEADERS).json['overview']['committedHotelMinor'] == 0
        row = {'name': 'Breakfast', 'amount': '10.25', 'category': 'Food', 'type': 'actual'}
        added = client.patch(path, headers=HEADERS,
                             json={'action': 'add', 'expense': row, 'expectedRevision': 0})
        assert added.status_code == 200, added.json
        assert added.json['overview']['balanceAfterRecordedActualMinor'] == 8975
        assert client.get(path, headers=HEADERS).json == added.json
        rid = added.json['expenses'][0]['id']
        stale = client.patch(path, headers=HEADERS, json={'action': 'delete', 'expectedRevision': 0, 'expenseId': rid})
        assert stale.status_code == 409
        edited = client.patch(path, headers=HEADERS,
            json={'action': 'edit', 'expectedRevision': 1, 'expenseId': rid, 'expense': {**row, 'amount': '12.05'}})
        assert edited.status_code == 200 and edited.json['overview']['actualMinor'] == 1205
        removed = client.patch(path, headers=HEADERS, json={'action': 'delete', 'expectedRevision': 2, 'expenseId': rid})
        assert removed.status_code == 200 and removed.json['expenses'] == []
        assert order_ref.get().to_dict() == paid
    finally:
        trip_ref.delete()
        order_ref.delete()
        hotel_ref.delete()


def test_activity_replacement_persists_and_replay_does_not_write(client, emulator, mock_traveller_auth):
    from test_fr05_alternative_integrity import _planned_trip
    trip_id = 'alternative-' + uuid4().hex
    trip = {**_planned_trip(), 'id': trip_id}
    # Two adults planning a visit using the mansion's published RM30 adult tariff.
    original = {
        **trip['activities'][0], 'destinationId': 'local_peranakan_mansion',
        'activityName': 'Pinang Peranakan Mansion', 'estimatedCost': 30, 'unitPrice': 30,
        'priceSourceUrl': 'https://www.pinangperanakanmansion.com.my/',
        'gps_coordinates': {'latitude': 5.4187, 'longitude': 100.3416},
        'scheduledStartTime': '09:30', 'timeSlot': '09:30',
    }
    trip['activities'][0] = original
    trip['dailySchedule'][0]['activities'][0] = deepcopy(original)
    ref = emulator.collection('itineraries').document(trip_id)
    path = f'/api/fr5/itineraries/{trip_id}/lower-cost-alternatives'
    ref.set(trip)
    try:
        preview = client.post(path, headers=HEADERS, json={})
        assert preview.status_code == 200, preview.json
        offer = next(row for row in preview.json['alternatives']
                     if row['data'].get('destinationId') == 'local_botanical_gardens')
        assert offer['currentEstimatedCost'] == 60
        assert offer['replacementEstimatedCost'] == 0
        assert offer['estimatedSavings'] == 60
        assert offer['source'].startswith('https://botanicalgardens.penang.gov.my/')
        applied = client.post(path + '/apply', headers=HEADERS, json={'alternative': offer})
        assert applied.status_code == 200, applied.json
        saved = ref.get()
        assert saved.to_dict()['dailySchedule'][1] == trip['dailySchedule'][1]
        assert saved.to_dict()['activities'][0]['destinationId'] == 'local_botanical_gardens'
        reopened = client.get(f'/api/fr5/itineraries/{trip_id}', headers=HEADERS).json['itinerary']
        assert reopened['id'] == trip_id
        assert reopened['activities'][0]['destinationId'] == 'local_botanical_gardens'
        assert reopened['budgetEstimate']['total'] == calculateBudget(trip)['total'] - 60
        replay = client.post(path + '/apply', headers=HEADERS, json={'alternative': offer})
        assert replay.status_code == 409
        assert ref.get().update_time == saved.update_time
    finally:
        ref.delete()
