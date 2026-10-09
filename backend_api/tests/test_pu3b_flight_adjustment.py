from copy import deepcopy
from unittest.mock import patch

from services.flight_itinerary_adjustment import (
    apply_preview,
    create_preview,
    flight_boundaries,
    reset_flight_adjustment_previews,
)


def _flight(arrival_date='2026-11-01', arrival_time='15:00', departure_date='2026-11-03', departure_time='10:00'):
    return {
        'id': 'flight_pu3b', 'departureAirport': 'KUL', 'arrivalAirport': 'PEN',
        'price': 180, 'currency': 'MYR', 'priceBasis': 'itinerary_total',
        'outboundSegments': [{'departureAirportCode': 'KUL', 'arrivalAirportCode': 'PEN', 'departureDate': arrival_date, 'arrivalDate': arrival_date, 'departureTime': '13:30', 'arrivalTime': arrival_time, 'durationMinutes': 90}],
        'returnSegments': [{'departureAirportCode': 'PEN', 'arrivalAirportCode': 'KUL', 'departureDate': departure_date, 'arrivalDate': departure_date, 'departureTime': departure_time, 'arrivalTime': '11:30', 'durationMinutes': 90}],
    }


def _trip():
    return {
        'id': 'pu3b_trip', 'travellerId': 'test_traveller_uid', 'title': 'Penang',
        'destinationArea': 'Penang, Malaysia', 'startDate': '2026-11-01', 'endDate': '2026-11-03',
        'travellerCount': 1, 'budgetLimit': 2000, 'selectedFlight': _flight(),
        'flightCost': 180, 'flightCurrency': 'MYR', 'flightPriceBasis': 'itinerary_total',
        'hotelCost': 240, 'hotelCurrency': 'MYR', 'selectedHotel': {'name': 'Hotel'},
        'activities': [
            {'activityId': 'morning', 'activityName': 'Morning museum', 'dayNo': 1, 'scheduledStartTime': '10:00', 'scheduledEndTime': '11:00', 'recommendedDurationMinutes': 60, 'openingHours': '08:00-20:00', 'estimatedCost': 20},
            {'activityId': 'flexible', 'activityName': 'Flexible market', 'dayNo': 1, 'scheduledStartTime': '17:00', 'scheduledEndTime': '18:00', 'recommendedDurationMinutes': 60, 'openingHours': '08:00-20:00', 'estimatedCost': 30},
        ],
        'unscheduledSuggestions': [],
    }


def test_preview_is_read_only_and_reports_arrival_window(client, mock_traveller_auth):
    reset_flight_adjustment_previews()
    trip = _trip()
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', return_value=trip), patch('modules.fr05_smart_itinerary_budget_planner.routes.updateRecord') as update:
        response = client.post('/api/fr5/itineraries/pu3b_trip/flight-adjustment/preview', headers={'Authorization': 'Bearer valid_test_token'})
    assert response.status_code == 200
    preview = response.get_json()['preview']
    assert preview['assumptions']['arrivalClearanceMinutes'] == 90
    assert preview['availability']['days']['2026-11-01']['startMinutes'] == 990
    assert preview['before']['activities'] == trip['activities']
    assert preview['changes']
    update.assert_not_called()


def test_protected_activity_stays_unchanged_and_conflict_is_visible(client, mock_traveller_auth):
    reset_flight_adjustment_previews()
    trip = _trip()
    trip['activities'][0]['userFixed'] = True
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', return_value=trip):
        response = client.post('/api/fr5/itineraries/pu3b_trip/flight-adjustment/preview', headers={'Authorization': 'Bearer valid_test_token'})
    preview = response.get_json()['preview']
    after = {x['activityId']: x for x in preview['after']['activities']}
    assert after['morning']['scheduledStartTime'] == '10:00'
    assert any(x['activityId'] == 'morning' for x in preview['remainingConflicts'])


def test_apply_requires_fresh_trip_and_is_idempotent(client, mock_traveller_auth):
    reset_flight_adjustment_previews()
    original = _trip()
    saved = deepcopy(original)
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', side_effect=lambda collection, document_id=None, **_: deepcopy(saved)), patch('modules.fr05_smart_itinerary_budget_planner.routes.updateRecord', side_effect=lambda collection, document_id, patch_data: saved.update(patch_data) or deepcopy(saved)):
        preview_response = client.post('/api/fr5/itineraries/pu3b_trip/flight-adjustment/preview', headers={'Authorization': 'Bearer valid_test_token'})
        preview_id = preview_response.get_json()['preview']['previewId']
        first = client.post('/api/fr5/itineraries/pu3b_trip/flight-adjustment/apply', headers={'Authorization': 'Bearer valid_test_token'}, json={'previewId': preview_id})
        second = client.post('/api/fr5/itineraries/pu3b_trip/flight-adjustment/apply', headers={'Authorization': 'Bearer valid_test_token'}, json={'previewId': preview_id})
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.get_json()['idempotent'] is True


def test_stale_preview_rejected_after_activity_edit(client, mock_traveller_auth):
    reset_flight_adjustment_previews()
    original = _trip()
    changed = deepcopy(original)
    changed['activities'][1]['userNote'] = 'Changed after preview'
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', side_effect=[original, changed]), patch('modules.fr05_smart_itinerary_budget_planner.routes.updateRecord'):
        preview_response = client.post('/api/fr5/itineraries/pu3b_trip/flight-adjustment/preview', headers={'Authorization': 'Bearer valid_test_token'})
        preview_id = preview_response.get_json()['preview']['previewId']
        response = client.post('/api/fr5/itineraries/pu3b_trip/flight-adjustment/apply', headers={'Authorization': 'Bearer valid_test_token'}, json={'previewId': preview_id})
    assert response.status_code == 409
    assert 'stale' in response.get_json()['error'].lower()


def test_missing_flight_time_disables_adjustment(client, mock_traveller_auth):
    reset_flight_adjustment_previews()
    trip = _trip()
    trip['selectedFlight']['outboundSegments'][0].pop('arrivalTime')
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', return_value=trip):
        response = client.post('/api/fr5/itineraries/pu3b_trip/flight-adjustment/preview', headers={'Authorization': 'Bearer valid_test_token'})
    preview = response.get_json()['preview']
    assert preview['canApply'] is False
    assert preview['status'] == 'no_flight_boundary'


def test_departure_buffers_reduce_last_day_without_double_counting(client, mock_traveller_auth, monkeypatch):
    reset_flight_adjustment_previews()
    monkeypatch.setenv('FLIGHT_DEPARTURE_TRANSFER_MINUTES', '90')
    monkeypatch.setenv('FLIGHT_DEPARTURE_CHECKIN_MINUTES', '120')
    trip = _trip()
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', return_value=trip):
        response = client.post('/api/fr5/itineraries/pu3b_trip/flight-adjustment/preview', headers={'Authorization': 'Bearer valid_test_token'})
    preview = response.get_json()['preview']
    assert preview['availability']['days']['2026-11-03']['endMinutes'] == 390
    assert preview['assumptions']['departureTransferMinutes'] + preview['assumptions']['departureCheckinMinutes'] == 210


def test_overnight_arrival_uses_explicit_destination_local_date():
    flight = _flight(arrival_date='2026-11-02', arrival_time='00:30')
    boundaries = flight_boundaries(_trip(), flight)
    assert boundaries['arrivalLocal'].startswith('2026-11-02T00:30')


def test_intermediate_transit_does_not_become_inbound_boundary():
    flight = _flight()
    flight['outboundSegments'] = [
        {'arrivalAirportCode': 'KUL', 'arrivalDate': '2026-11-01', 'arrivalTime': '14:00'},
        {'arrivalAirportCode': 'PEN', 'arrivalDate': '2026-11-01', 'arrivalTime': '15:00'},
    ]
    boundaries = flight_boundaries(_trip(), flight)
    assert boundaries['arrivalLocal'].startswith('2026-11-01T15:00')


def test_infeasible_day_keeps_activity_identity_and_reason(client, mock_traveller_auth):
    reset_flight_adjustment_previews()
    trip = _trip()
    trip['activities'][1]['recommendedDurationMinutes'] = 480
    trip['activities'][1]['userNote'] = 'Keep this note'
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', return_value=trip):
        response = client.post('/api/fr5/itineraries/pu3b_trip/flight-adjustment/preview', headers={'Authorization': 'Bearer valid_test_token'})
    preview = response.get_json()['preview']
    item = preview['newlyUnscheduled'][0]
    assert item['activityId'] == 'flexible'
    assert item['userNote'] == 'Keep this note'
    assert item['unscheduledReason']


def test_preview_owner_is_required_for_apply():
    reset_flight_adjustment_previews()
    trip = _trip()
    preview = create_preview(trip, trip['selectedFlight'], 'owner-a')
    result, error = apply_preview(
        preview['previewId'], trip, trip['selectedFlight'], 'owner-b', lambda *_: trip,
    )
    assert result is None
    assert error == 'Preview not found'


def test_arrival_and_departure_day_changes_are_both_retained(client, mock_traveller_auth):
    reset_flight_adjustment_previews()
    trip = _trip()
    trip['activities'].append({
        'activityId': 'last-day', 'activityName': 'Last-day gallery', 'dayNo': 3,
        'scheduledStartTime': '08:00', 'scheduledEndTime': '09:00',
        'recommendedDurationMinutes': 60, 'openingHours': '08:00-20:00',
        'estimatedCost': 15, 'userFixed': True,
    })
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', return_value=trip):
        response = client.post('/api/fr5/itineraries/pu3b_trip/flight-adjustment/preview', headers={'Authorization': 'Bearer valid_test_token'})
    preview = response.get_json()['preview']
    after = {item['activityId']: item for item in preview['after']['activities']}
    assert 'morning' in after
    assert 'last-day' in after

