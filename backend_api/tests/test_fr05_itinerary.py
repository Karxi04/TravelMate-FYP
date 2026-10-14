import pytest
from unittest.mock import patch

def test_apply_lower_cost_alternative_not_found(client, mock_traveller_auth):
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord') as mock_retrieve:
        mock_retrieve.return_value = None
        res = client.post(
            '/api/fr5/itineraries/nonexistent/lower-cost-alternatives/apply',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'type': 'flight', 'data': {'price': 99.0}, 'saving': 50.0}
        )
        assert res.status_code == 404
        assert res.get_json()['error'] == 'Itinerary not found'

def test_apply_lower_cost_alternative_success(client, mock_traveller_auth):
    sample_itinerary = {
        'id': 'itin_123',
        'travellerId': 'test_traveller_uid',
        'title': 'Penang Trip',
        'startDate': '2026-09-05',
        'endDate': '2026-09-07',
        'travellerCount': 1,
        'budgetLimit': 500,
        'flightCost': 200,
        'hotelCost': 200,
        'activities': []
    }
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord') as mock_retrieve, \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.updateRecord') as mock_update:
        mock_retrieve.return_value = sample_itinerary
        mock_update.side_effect = lambda coll, doc_id, patch_data: {**sample_itinerary, **patch_data}

        res = client.post(
            '/api/fr5/itineraries/itin_123/lower-cost-alternatives/apply',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={
                'type': 'flight',
                'data': {'flightNumber': 'MH123', 'price': 120.0},
                'saving': 80.0
            }
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert data['itinerary']['flightCost'] == 120.0
        assert 'budget' in data


def test_trip_date_update_persists_when_no_attached_travel_conflicts(client, mock_traveller_auth):
    itinerary = {
        'id': 'editable-trip', 'travellerId': 'test_traveller_uid', 'title': 'Penang',
        'destinationArea': 'Penang', 'startDate': '2026-11-01', 'endDate': '2026-11-03',
        'travellerCount': 1, 'budgetLimit': 500, 'activities': [],
    }
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', return_value=itinerary), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.updateRecord', side_effect=lambda _c, _i, data: {**itinerary, **data}):
        response = client.put('/api/fr5/itineraries/editable-trip', headers={'Authorization': 'Bearer valid_test_token'}, json={
            'startDate': '2026-11-02', 'endDate': '2026-11-04',
        })
    assert response.status_code == 200
    assert response.get_json()['itinerary']['startDate'] == '2026-11-02'


def test_trip_date_update_redates_existing_schedule_and_adds_new_days(client, mock_traveller_auth):
    itinerary = {
        'id': 'schedule-trip', 'travellerId': 'test_traveller_uid', 'title': 'Penang',
        'destinationArea': 'Penang', 'startDate': '2026-11-01', 'endDate': '2026-11-03',
        'travellerCount': 1, 'budgetLimit': 500,
        'activities': [{'dayNo': 2, 'title': 'Keep this activity'}],
        'dailySchedule': [
            {'dayNo': 1, 'dayDate': '2026-11-01', 'activities': []},
            {'dayNo': 2, 'dayDate': '2026-11-02', 'activities': [{'title': 'Keep this activity'}]},
            {'dayNo': 3, 'dayDate': '2026-11-03', 'activities': []},
        ],
    }
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', return_value=itinerary), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.updateRecord', side_effect=lambda _c, _i, data: {**itinerary, **data}):
        response = client.put('/api/fr5/itineraries/schedule-trip', headers={'Authorization': 'Bearer valid_test_token'}, json={
            'startDate': '2026-11-05', 'endDate': '2026-11-09',
        })
    assert response.status_code == 200
    updated = response.get_json()['itinerary']
    assert updated['tripDays'] == 5
    assert [day['dayDate'] for day in updated['dailySchedule']] == [
        '2026-11-05', '2026-11-06', '2026-11-07', '2026-11-08', '2026-11-09',
    ]
    assert updated['dailySchedule'][1]['activities'] == [{'title': 'Keep this activity'}]


def test_trip_date_update_does_not_remove_scheduled_activity(client, mock_traveller_auth):
    itinerary = {
        'id': 'schedule-trip', 'travellerId': 'test_traveller_uid', 'title': 'Penang',
        'destinationArea': 'Penang', 'startDate': '2026-11-01', 'endDate': '2026-11-05',
        'travellerCount': 1, 'budgetLimit': 500,
        'activities': [{'dayNo': 5, 'title': 'Keep this activity'}],
        'dailySchedule': [{'dayNo': 5, 'activities': [{'title': 'Keep this activity'}]}],
    }
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', return_value=itinerary), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.updateRecord') as update:
        response = client.put('/api/fr5/itineraries/schedule-trip', headers={'Authorization': 'Bearer valid_test_token'}, json={
            'endDate': '2026-11-03',
        })
    assert response.status_code == 409
    assert response.get_json()['conflicts'][0]['type'] == 'itinerary_schedule'
    update.assert_not_called()


def test_trip_date_update_rejects_attached_hotel_conflict(client, mock_traveller_auth):
    itinerary = {
        'id': 'hotel-trip', 'travellerId': 'test_traveller_uid', 'title': 'Penang',
        'destinationArea': 'Penang', 'startDate': '2026-11-01', 'endDate': '2026-11-05',
        'travellerCount': 1, 'budgetLimit': 500, 'hotelBookingId': 'hotel-1', 'activities': [],
    }
    booking = {'id': 'hotel-1', 'stayCriteria': {'checkin': '2026-11-02', 'checkout': '2026-11-05'}}
    def retrieve(collection, document_id=None, **_kwargs):
        return itinerary if collection == 'itineraries' else booking if collection == 'hotel_bookings' else None
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', side_effect=retrieve), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.updateRecord') as update:
        response = client.put('/api/fr5/itineraries/hotel-trip', headers={'Authorization': 'Bearer valid_test_token'}, json={
            'startDate': '2026-11-01', 'endDate': '2026-11-04',
        })
    assert response.status_code == 409
    assert response.get_json()['conflicts'][0]['type'] == 'hotel_dates'
    update.assert_not_called()


def test_itinerary_generation_uses_linked_destination_snapshot(client, mock_traveller_auth):
    itinerary = {
        'id': 'itin_snapshot',
        'travellerId': 'test_traveller_uid',
        'title': 'Penang Trip',
        'destinationArea': 'Penang, Malaysia',
        'startDate': '2026-11-01',
        'endDate': '2026-11-02',
        'travellerCount': 1,
        'budgetLimit': 500,
        'activities': [],
        'recommendationGenerationId': 'rec_penang',
    }
    snapshot = {
        'recommendationGenerationId': 'rec_penang',
        'travellerId': 'test_traveller_uid',
        'requestedDestination': 'Penang, Malaysia',
        'source': 'cache',
        'recommendationResults': [{
            'destinationId': 'penang_hill',
            'title': 'Penang Hill',
            'address': 'Air Itam, Penang, Malaysia',
            'category': 'Nature',
        }],
    }

    def fake_retrieve(collection, document_id=None, filters=None, limit=None):
        if collection == 'itineraries' and document_id == 'itin_snapshot':
            return itinerary
        if collection == 'recommendation_snapshots' and document_id == 'rec_penang':
            return snapshot
        return None

    identity = lambda value: value
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', side_effect=fake_retrieve), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveLocationAndTravelTime', return_value=[]), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes._forecast_for', return_value=({}, None)), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.generateItinerary', side_effect=lambda locations, forecast, current: current), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.groupNearbyActivities', side_effect=identity), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.checkOpeningHoursAndTravelTime', side_effect=identity), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.adjustWeatherSensitiveActivities', side_effect=identity), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.updateRecord') as mock_update:
        stored = dict(itinerary)
        def update_itinerary(collection, document_id, patch_data):
            stored.update(patch_data)
            return dict(stored)
        mock_update.side_effect = update_itinerary
        response = client.post(
            '/api/fr5/itineraries/itin_snapshot/generate',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'recommendationGenerationId': 'rec_penang'},
        )

    assert response.status_code == 200
    data = response.get_json()
    assert [item['destinationId'] for item in data['itinerary']['activities']] == ['penang_hill']
    assert data['smartFeatures']['recommendationGenerationId'] == 'rec_penang'
    assert data['smartFeatures']['destinationSource'] == 'cache'
    assert mock_update.call_args.args[0:2] == ('itineraries', 'itin_snapshot')


def test_itinerary_generation_rejects_snapshot_for_other_destination(client, mock_traveller_auth):
    itinerary = {
        'id': 'itin_penang',
        'travellerId': 'test_traveller_uid',
        'destinationArea': 'Penang, Malaysia',
        'activities': [],
        'recommendationGenerationId': 'rec_kl',
    }
    snapshot = {
        'recommendationGenerationId': 'rec_kl',
        'travellerId': 'test_traveller_uid',
        'requestedDestination': 'Kuala Lumpur, Malaysia',
        'items': [],
    }

    def fake_retrieve(collection, document_id=None, filters=None, limit=None):
        if collection == 'itineraries':
            return itinerary
        if collection == 'recommendation_snapshots':
            return snapshot
        return None

    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', side_effect=fake_retrieve):
        response = client.post(
            '/api/fr5/itineraries/itin_penang/generate',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'recommendationGenerationId': 'rec_kl'},
        )

    assert response.status_code == 409
    assert 'destination does not match' in response.get_json()['error']


def test_itinerary_generation_rejects_snapshot_other_than_trip_link(client, mock_traveller_auth):
    itinerary = {
        'id': 'itin_penang',
        'travellerId': 'test_traveller_uid',
        'destinationArea': 'Penang, Malaysia',
        'activities': [],
        'recommendationGenerationId': 'rec_original',
    }

    with patch(
        'modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord',
        return_value=itinerary,
    ):
        response = client.post(
            '/api/fr5/itineraries/itin_penang/generate',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'recommendationGenerationId': 'rec_other'},
        )

    assert response.status_code == 409
    assert 'linked to this trip' in response.get_json()['error']


def test_itinerary_generation_rejects_missing_or_foreign_snapshot(client, mock_traveller_auth):
    itinerary = {
        'id': 'itin_penang',
        'travellerId': 'test_traveller_uid',
        'destinationArea': 'Penang, Malaysia',
        'activities': [],
        'recommendationGenerationId': 'rec_missing',
    }

    def fake_retrieve(collection, document_id=None, filters=None, limit=None):
        if collection == 'itineraries':
            return itinerary
        if collection == 'recommendation_snapshots':
            return {
                'recommendationGenerationId': 'rec_missing',
                'travellerId': 'another_traveller',
                'requestedDestination': 'Penang, Malaysia',
            }
        return None

    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', side_effect=fake_retrieve):
        response = client.post(
            '/api/fr5/itineraries/itin_penang/generate',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'recommendationGenerationId': 'rec_missing'},
        )

    assert response.status_code == 409
    assert 'not found for this traveller' in response.get_json()['error']


def _personalised_payload():
    return {
        'title': 'Snapshot Penang Trip',
        'destinationArea': 'Penang, Malaysia',
        'destinationName': 'Penang, Malaysia',
        'startDate': '2026-11-01',
        'endDate': '2026-11-03',
        'travellerCount': 2,
        'budgetLimit': 1200,
        'recommendationGenerationId': 'rec_penang_flow',
        'generationRequestId': 'request_penang_flow_001',
    }


def _personalised_snapshot():
    return {
        'recommendationGenerationId': 'rec_penang_flow',
        'travellerId': 'test_traveller_uid',
        'requestedDestination': 'Penang, Malaysia',
        'source': 'cache',
        'recommendationResults': [{
            'destinationId': 'penang_hill',
            'title': 'Penang Hill',
            'address': 'Air Itam, Penang, Malaysia',
        }],
    }


def _memory_storage(snapshot=None):
    records = {
        'itineraries': {},
        'recommendation_snapshots': {
            'rec_penang_flow': snapshot or _personalised_snapshot(),
        },
    }

    def retrieve(collection, document_id=None, filters=None, limit=None):
        if document_id is not None:
            item = records.get(collection, {}).get(document_id)
            return dict(item) if item else None
        return [dict(item) for item in records.get(collection, {}).values()]

    def store(collection, data, document_id=None, merge=False):
        key = document_id or f'{collection}_{len(records.setdefault(collection, {})) + 1}'
        current = records.setdefault(collection, {}).get(key, {}) if merge else {}
        result = {'id': key, **current, **data}
        records[collection][key] = result
        return dict(result)

    def update(collection, document_id, data):
        if document_id not in records.setdefault(collection, {}):
            return None
        records[collection][document_id].update(data)
        return dict(records[collection][document_id])

    return records, retrieve, store, update


def _generated_itinerary(current, payload, snapshot):
    generation_id = snapshot['recommendationGenerationId'] if snapshot else None
    return {
        **current,
        'activities': [{
            'activityId': 'A1',
            'activityName': 'Penang Hill',
            'destinationId': 'penang_hill',
            'recommendationGenerationId': generation_id,
        }],
        'generationContext': {
            'recommendationGenerationId': generation_id,
            'destinationSource': snapshot.get('source') if snapshot else 'fallback',
        },
    }


def test_personalised_trip_reaches_planned_and_retains_snapshot_and_trip_id(
        client, mock_traveller_auth):
    records, retrieve, store, update = _memory_storage()
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', side_effect=retrieve), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.storeRecord', side_effect=store) as mock_store, \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.updateRecord', side_effect=update), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes._generate_itinerary_data', side_effect=_generated_itinerary), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.calculateBudget', return_value={'total': 350, 'limit': 1200}), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.compareBudget', return_value='Within budget'):
        first = client.post(
            '/api/fr5/personalised-trips/generate',
            headers={'Authorization': 'Bearer valid_test_token'},
            json=_personalised_payload(),
        )
        second = client.post(
            '/api/fr5/personalised-trips/generate',
            headers={'Authorization': 'Bearer valid_test_token'},
            json=_personalised_payload(),
        )

    assert first.status_code == 200
    data = first.get_json()
    assert data['status'] == 'planned'
    assert data['tripId'] == data['id']
    assert data['itinerary']['recommendationGenerationId'] == 'rec_penang_flow'
    assert data['itinerary']['activities'][0]['recommendationGenerationId'] == 'rec_penang_flow'
    assert records['itineraries'][data['tripId']]['status'] == 'planned'
    assert second.get_json()['tripId'] == data['tripId']
    assert second.get_json()['reused'] is True
    assert mock_store.call_count == 1


def test_itinerary_failure_is_recoverable_and_retry_reuses_trip(
        client, mock_traveller_auth):
    records, retrieve, store, update = _memory_storage()
    attempts = {'count': 0}

    def fail_then_generate(current, payload, snapshot):
        attempts['count'] += 1
        if attempts['count'] == 1:
            raise RuntimeError('Provider itinerary generation failed')
        return _generated_itinerary(current, payload, snapshot)

    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', side_effect=retrieve), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.storeRecord', side_effect=store) as mock_store, \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.updateRecord', side_effect=update), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes._generate_itinerary_data', side_effect=fail_then_generate), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.calculateBudget', return_value={'total': 350}), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.compareBudget', return_value='Within budget'):
        failed = client.post(
            '/api/fr5/personalised-trips/generate',
            headers={'Authorization': 'Bearer valid_test_token'},
            json=_personalised_payload(),
        )
        failed_data = failed.get_json()
        stored_failed_status = records['itineraries'][failed_data['tripId']]['status']
        recovered = client.post(
            '/api/fr5/personalised-trips/generate',
            headers={'Authorization': 'Bearer valid_test_token'},
            json=_personalised_payload(),
        )

    assert failed.status_code == 500
    assert failed_data['status'] == 'generation_failed'
    assert failed_data['stage'] == 'itinerary_generation'
    assert failed_data['retryable'] is True
    assert stored_failed_status == 'generation_failed'
    assert records['itineraries'][failed_data['tripId']]['status'] == 'planned'
    assert recovered.status_code == 200
    assert recovered.get_json()['status'] == 'planned'
    assert recovered.get_json()['tripId'] == failed_data['tripId']
    assert mock_store.call_count == 1


def test_budget_failure_never_marks_personalised_trip_planned(
        client, mock_traveller_auth):
    records, retrieve, store, update = _memory_storage()
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', side_effect=retrieve), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.storeRecord', side_effect=store), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.updateRecord', side_effect=update), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes._generate_itinerary_data', side_effect=_generated_itinerary), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.calculateBudget', side_effect=RuntimeError('Budget service failed')):
        response = client.post(
            '/api/fr5/personalised-trips/generate',
            headers={'Authorization': 'Bearer valid_test_token'},
            json=_personalised_payload(),
        )

    data = response.get_json()
    assert response.status_code == 500
    assert data['status'] == 'generation_failed'
    assert data['stage'] == 'budget_calculation'
    assert records['itineraries'][data['tripId']]['status'] == 'generation_failed'
    assert records['itineraries'][data['tripId']]['activities']


def test_personalised_trip_snapshot_destination_mismatch_returns_409(
        client, mock_traveller_auth):
    mismatched = {
        **_personalised_snapshot(),
        'requestedDestination': 'Kuala Lumpur, Malaysia',
    }
    records, retrieve, store, update = _memory_storage(mismatched)
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', side_effect=retrieve), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.storeRecord', side_effect=store) as mock_store, \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.updateRecord', side_effect=update):
        response = client.post(
            '/api/fr5/personalised-trips/generate',
            headers={'Authorization': 'Bearer valid_test_token'},
            json=_personalised_payload(),
        )

    assert response.status_code == 409
    assert response.get_json()['stage'] == 'snapshot_validation'
    assert 'destination does not match' in response.get_json()['error']
    assert records['itineraries'] == {}
    assert mock_store.call_count == 0


def test_manual_trip_still_works_without_recommendation_generation_id(
        client, mock_traveller_auth):
    captured = {}

    def store(collection, data, document_id=None, merge=False):
        captured.update(data)
        return {'id': 'manual_trip_1', **data}

    payload = _personalised_payload()
    payload.pop('recommendationGenerationId')
    payload.pop('generationRequestId')
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.storeRecord', side_effect=store), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.calculateBudget', return_value={'total': 0}):
        response = client.post(
            '/api/fr5/itineraries',
            headers={'Authorization': 'Bearer valid_test_token'},
            json=payload,
        )

    assert response.status_code == 201
    assert response.get_json()['id'] == 'manual_trip_1'
    assert captured['status'] == 'draft'
    assert 'recommendationGenerationId' not in captured
