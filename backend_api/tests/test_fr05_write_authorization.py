"""Registered FR05 routes, real decorators and isolated auth/persistence doubles."""
from copy import deepcopy

import pytest

from modules.fr05_smart_itinerary_budget_planner import routes


AUTH = {'Authorization': 'Bearer synthetic-token'}


def draft():
    return {'title': 'Manual Penang trip', 'destinationArea': 'Penang',
            'startDate': '2027-01-01', 'endDate': '2027-01-03',
            'travellerCount': 2, 'budgetLimit': 1500, 'activities': []}


@pytest.fixture
def storage(monkeypatch, mock_traveller_auth):
    records = {'trip': {**draft(), 'id': 'trip', 'travellerId': 'test_traveller_uid',
                        'createdAt': 'original', 'updatedAt': 'original', 'status': 'draft',
                        'budgetAwareSelection': {'applied': True, 'isProvisional': True}}}
    writes = []

    def retrieve(collection, document_id=None, **kwargs):
        if collection == 'itineraries':
            return deepcopy(records.get(document_id)) if document_id else list(deepcopy(records).values())
        return None

    def update(collection, document_id, patch):
        assert collection == 'itineraries'
        writes.append(deepcopy(patch))
        records[document_id].update(deepcopy(patch))
        return deepcopy(records[document_id])

    def store(collection, data, document_id=None):
        assert collection == 'itineraries'
        identity = document_id or 'created'
        writes.append(deepcopy(data))
        records[identity] = {'id': identity, **deepcopy(data)}
        return deepcopy(records[identity])

    monkeypatch.setattr(routes, 'retrieveRecord', retrieve)
    monkeypatch.setattr(routes, 'updateRecord', update)
    monkeypatch.setattr(routes, 'storeRecord', store)
    return records, writes


PROTECTED = [
    ('travellerId', 'other'), ('createdAt', 'forged'), ('updatedAt', 'forged'),
    ('tripType', 'package'), ('checkoutOrderId', 'forged'), ('paidTotal', 0),
    ('packageSnapshot', {'title': 'forged'}), ('paymentStatus', 'paid'),
    ('id', 'other'), ('operatorId', 'other'), ('packageTrip', True),
    ('bookingStatus', 'confirmed'), ('supplierReservationStatus', 'confirmed'),
    ('fulfillmentStatus', 'fulfilled'), ('budgetEstimate', {'total': 0}),
    ('dailySchedule', []), ('budgetAwareSelection', {'applied': True}),
    ('status', 'paid'), ('providerIdempotencyKey', 'forged'),
    ('ownerId', 'other'), ('traveller_id', 'other'),
    ('packageSnapshot.operatorId', 'other'), ('travellerId.uid', 'other'),
    ('selectedFlight', {'price': 0}), ('carRentalCost', 0),
]


@pytest.mark.parametrize('field,value', PROTECTED)
@pytest.mark.parametrize('method', ['post', 'put'])
def test_protected_fields_rejected_atomically(client, storage, field, value, method):
    records, writes = storage
    before = deepcopy(records)
    payload = draft() if method == 'post' else {'title': 'Do not partially apply'}
    payload[field] = value
    path = '/api/fr5/itineraries' + ('/trip' if method == 'put' else '')
    response = getattr(client, method)(path, headers=AUTH, json=payload)
    assert response.status_code == 400
    assert response.json['ok'] is False
    assert records == before and writes == []


def test_valid_edit_and_reload_preserves_owner_and_server_metadata(client, storage):
    records, _ = storage
    response = client.put('/api/fr5/itineraries/trip', headers=AUTH,
        json={'title': 'Edited', 'startDate': '2027-02-01', 'endDate': '2027-02-03',
              'travellerCount': 3, 'budgetLimit': 2000, 'originLocation': 'Kuala Lumpur',
              'travelMode': 'public_transport', 'accommodationChoice': 'return_home',
              'carRentalChoice': 'not_required', 'travelPace': 'Moderate'})
    assert response.status_code == 200
    saved = client.get('/api/fr5/itineraries/trip', headers=AUTH).json['itinerary']
    assert saved == records['trip'] and saved['title'] == 'Edited'
    assert saved['travellerId'] == 'test_traveller_uid' and saved['createdAt'] == 'original'
    assert saved['updatedAt'] != 'original'
    assert saved['budgetAwareSelection'] == {'applied': True, 'isProvisional': True}
    assert saved['budgetEstimate']['budgetLimit'] == 2000
    assert saved['travelPace'] == 'Moderate'


def test_manual_blank_creation(client, storage):
    response = client.post('/api/fr5/itineraries', headers=AUTH, json=draft())
    assert response.status_code == 201
    saved = response.json['itinerary']
    assert saved['activities'] == [] and saved['status'] == 'draft'
    assert saved['travellerId'] == 'test_traveller_uid'
    assert saved['createdAt'] and saved['updatedAt'] and saved['budgetEstimate']


def test_nonowner_and_missing_auth_never_write(client, storage):
    records, writes = storage
    records['trip']['travellerId'] = 'another-user'
    assert client.put('/api/fr5/itineraries/trip', headers=AUTH, json={'title': 'No'}).status_code == 404
    assert client.put('/api/fr5/itineraries/trip', json={'title': 'No'}).status_code == 401
    assert client.post('/api/fr5/itineraries', json=draft()).status_code == 401
    assert writes == []


@pytest.mark.parametrize('payload', [
    {}, [], 'invalid', None, {'title': {'travellerId': 'other'}},
    {'budgetLimit': True}, {'budgetLimit': -1}, {'budgetLimit': float('inf')},
    {'budgetLimit': float('nan')}, {'budgetLimit': 10**400},
    {'travellerCount': 0}, {'travellerCount': 1.5},
    {'travellerCount': '2'}, {'startDate': ['2027-01-01']}, {'travelMode': {}},
    {'originLocation': {'ownerId': 'other'}}, {'title': ''},
    {'metadata': {'paymentStatus': 'paid'}}, {'hotelBookingId': {'id': 'hotel'}},
    {'activities': []}, {'trusted': True},
])
def test_invalid_update_shapes_types_and_nested_injection(client, storage, payload):
    records, writes = storage
    before = deepcopy(records)
    response = client.put('/api/fr5/itineraries/trip', headers=AUTH, json=payload)
    assert response.status_code == 400 and records == before and writes == []


@pytest.mark.parametrize('activity', [
    {'activityName': {'paymentStatus': 'paid'}},
    {'activityName': 'Place', 'checkoutOrderId': 'forged'},
    {'activityName': 'Place', 'pricingEvidence': {'travellerId': 'other'}},
    {'activityName': 'Place', 'pricingEvidence': {'packageSnapshot.paidTotal': 0}},
    {'activityName': 'Place', 'gps_coordinates': {'latitude': {'ownerId': 'other'}}},
    {'activityName': 'Place', 'images': [{'url': {'paymentStatus': 'paid'}}]},
    {'activityName': 'Place', 'effectiveCost': 0},
    {'activityName': 'Place', 'scheduledStartTime': '09:00'},
])
def test_nested_creation_fields_cannot_smuggle_protected_claims(client, storage, activity):
    records, writes = storage
    before = deepcopy(records)
    response = client.post('/api/fr5/itineraries', headers=AUTH,
        json={**draft(), 'activities': [activity]})
    assert response.status_code == 400 and records == before and writes == []


def test_raw_activity_inputs_and_unknown_prices_remain_supported(client, storage):
    activity = {'activityName': 'Unpriced place', 'destinationId': 'synthetic-place',
        'dayNo': 2, 'timeSlot': '', 'gps_coordinates': {'latitude': 5.4, 'longitude': 100.3},
        'estimatedCost': 0, 'pricingUnit': 'unknown', 'costProvenance': 'unverified'}
    response = client.post('/api/fr5/itineraries', headers=AUTH,
        json={**draft(), 'activities': [activity]})
    assert response.status_code == 201
    saved = response.json['itinerary']
    assert saved['activities'] == [activity]
    assert saved['budgetEstimate']['completenessStatus'] == 'incomplete'
    assert 'dailySchedule' not in saved


@pytest.mark.parametrize('field,value', PROTECTED)
def test_personalised_creation_cannot_bypass_public_field_boundary(client, storage, field, value):
    records, writes = storage
    before = deepcopy(records)
    response = client.post('/api/fr5/personalised-trips/generate', headers=AUTH,
        json={**draft(), 'generationRequestId': 'request-synthetic-123',
              'recommendationGenerationId': 'synthetic-snapshot', field: value})
    assert response.status_code == 400 and records == before and writes == []


def test_owned_hotel_lookup_is_server_authoritative(client, storage, monkeypatch):
    records, writes = storage
    original_retrieve = routes.retrieveRecord
    booking = {'id': 'hotel', 'travellerId': 'test_traveller_uid',
        'bookingStatus': 'confirmed', 'amountSource': 'validated_offer',
        'hotelCurrency': 'MYR', 'hotelCost': 123,
        'selectedHotel': {'hotelId': 'synthetic-hotel', 'name': 'Owned Hotel'}}
    monkeypatch.setattr(routes, 'retrieveRecord', lambda collection, identity=None, **kwargs:
        deepcopy(booking) if collection == 'hotel_bookings' and identity == 'hotel'
        else original_retrieve(collection, identity, **kwargs))
    response = client.put('/api/fr5/itineraries/trip', headers=AUTH, json={'hotelBookingId': 'hotel'})
    assert response.status_code == 200
    assert records['trip']['hotelCost'] == 123
    assert records['trip']['selectedHotel'] == booking['selectedHotel']
    assert records['trip']['accommodationChoice'] == 'paid_hotel'
    writes.clear()
    before = deepcopy(records)
    for override in ({'hotelCost': 0}, {'selectedHotel': {'paymentStatus': 'paid'}}, {'hotelCurrency': 'USD'}):
        response = client.put('/api/fr5/itineraries/trip', headers=AUTH,
            json={'hotelBookingId': 'hotel', **override})
        assert response.status_code == 400 and records == before and writes == []


def test_foreign_hotel_lookup_rejected_without_mutation(client, storage, monkeypatch):
    records, writes = storage
    original_retrieve = routes.retrieveRecord
    monkeypatch.setattr(routes, 'retrieveRecord', lambda collection, identity=None, **kwargs:
        {'travellerId': 'another-user'} if collection == 'hotel_bookings'
        else original_retrieve(collection, identity, **kwargs))
    response = client.put('/api/fr5/itineraries/trip', headers=AUTH, json={'hotelBookingId': 'foreign'})
    assert response.status_code == 409 and writes == []


def test_purchased_trip_cannot_be_demoted_to_personal(client, storage):
    records, writes = storage
    records['trip'].update({'tripType': 'package', 'packageTrip': True,
        'packageSnapshot': {'operatorId': 'operator-original', 'price': 999},
        'checkoutOrderId': 'original-order', 'paidTotal': 999,
        'supplierReservationStatus': 'not_created'})
    before = deepcopy(records)
    for payload in ({'title': 'No'}, {'tripType': 'personal', 'packageTrip': False}):
        response = client.put('/api/fr5/itineraries/trip', headers=AUTH, json=payload)
        assert response.status_code == 409 and records == before and writes == []
