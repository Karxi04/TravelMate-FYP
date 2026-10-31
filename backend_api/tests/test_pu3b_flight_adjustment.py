from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sequence_contract.domain_functions import calculateBudget
from services.flight_itinerary_adjustment import (
    apply_preview,
    create_preview,
    flight_boundaries,
    fingerprint,
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


@pytest.fixture
def lifecycle_store(monkeypatch):
    """Exercise the real Firestore wrapper with isolated snapshot/merge semantics."""
    reset_flight_adjustment_previews()
    trip = _trip()
    trip.update({
        'travelMode': 'flight', 'accommodationChoice': 'paid_hotel',
        'carRentalChoice': 'selected', 'carRentalCost': 150,
        'selectedCarRental': {'id': 'synthetic-rental'}, 'hotelBookingId': 'synthetic-hotel',
        'transportCost': 70, 'foodCost': 90,
    })
    trip['activities'][0]['userFixed'] = True
    trip['budgetEstimate'] = calculateBudget(trip)
    records, writes = {trip['id']: trip}, []

    def merge_fields(target, values):
        for key, value in values.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                merge_fields(target[key], value)
            else:
                target[key] = deepcopy(value)

    def document(key):
        def get():
            snapshot = deepcopy(records.get(key))
            return SimpleNamespace(id=key, exists=snapshot is not None,
                                   to_dict=lambda: deepcopy(snapshot))

        def save(values, merge=False):
            assert merge is True
            writes.append(deepcopy(values))
            merge_fields(records.setdefault(key, {}), values)

        return SimpleNamespace(get=get, set=save)

    def collection(name):
        assert name == 'itineraries'
        return SimpleNamespace(document=document)

    monkeypatch.setattr('sequence_contract.firebase_firestore.get_db',
                        lambda: SimpleNamespace(collection=collection))
    yield SimpleNamespace(records=records, writes=writes)
    reset_flight_adjustment_previews()


_HEADERS = {'Authorization': 'Bearer valid_test_token'}
_TRIP_URL = '/api/fr5/itineraries/pu3b_trip'
_REMOVE_URL = '/api/fr7/itineraries/pu3b_trip/flight-selection/remove'


def _preview_http(client):
    response = client.post(_TRIP_URL + '/flight-adjustment/preview', headers=_HEADERS)
    assert response.status_code == 200, response.get_json()
    return response.get_json()['preview']['previewId']


def _apply_http(client, preview_id, trip_url=_TRIP_URL):
    return client.post(trip_url + '/flight-adjustment/apply', headers=_HEADERS,
                       json={'previewId': preview_id})


def _apply_current(client):
    preview_id = _preview_http(client)
    response = _apply_http(client, preview_id)
    assert response.status_code == 200, response.get_json()
    return preview_id


def _select_http(client, option=None):
    option = deepcopy(option or {**_flight(arrival_time='18:00'), 'id': 'flight_b', 'price': 360})
    option.update({'quoteCompleteness': 'complete', 'budgetEligible': True})
    quote = {'id': 'synthetic-owned-search', 'criteria': {}, 'source': 'serpapi'}
    with patch('modules.fr07_flight_search.routes._quote_item', return_value=(quote, option, None)):
        return client.post('/api/fr7/flights/select', headers=_HEADERS, json={
            'itineraryId': 'pu3b_trip', 'searchId': quote['id'],
            'optionId': option['id'], 'acknowledgeConflicts': True,
        })


def _reopened(client):
    response = client.get(_TRIP_URL, headers=_HEADERS)
    assert response.status_code == 200
    return response.get_json()['itinerary']


def _assert_nonflight_preserved(before, after):
    for key in ('activities', 'unscheduledSuggestions', 'selectedHotel', 'hotelBookingId',
                'hotelCost', 'selectedCarRental', 'carRentalCost'):
        assert after[key] == before[key]
    for key in ('hotel', 'carRental', 'transport', 'food', 'activities'):
        assert after['budgetEstimate']['categoryTotals'][key] == before['budgetEstimate']['categoryTotals'][key]


def test_replacement_invalidates_applied_metadata_and_reopens_consistently(client, mock_traveller_auth, lifecycle_store):
    _apply_current(client)
    before = _reopened(client)
    response = _select_http(client)
    assert response.status_code == 200
    after = _reopened(client)
    assert after == response.get_json()['itinerary']
    assert after['selectedFlight']['id'] == 'flight_b'
    assert after['flightAdjustmentStatus'] == 'review_required'
    assert after['flightAdjustmentReviewReason'] == 'flight_replaced'
    assert after['flightAdjustmentFlightFingerprint'] == fingerprint(before['selectedFlight'])
    for key in ('flightAdjustmentPreviewId', 'flightAdjustmentAppliedAt', 'flightAdjustmentAssumptions'):
        assert after[key] == before[key]
    assert after['revision'] == before['revision'] + 1
    assert after['budgetEstimate']['flight'] == 360
    assert after['budgetEstimate']['total'] == before['budgetEstimate']['total'] + 180
    _assert_nonflight_preserved(before, after)
    assert lifecycle_store.writes[-1]['flightAdjustmentStatus'] == 'review_required'
    assert lifecycle_store.writes[-1]['selectedFlight']['id'] == 'flight_b'


def test_removal_keeps_manual_edits_protected_activities_and_adjustment_history(client, mock_traveller_auth, lifecycle_store):
    _apply_current(client)
    activity = lifecycle_store.records['pu3b_trip']['activities'][1]
    activity.update({'userEdited': True, 'userNote': 'Keep my manual change',
                     'scheduledStartTime': '19:00', 'scheduledEndTime': '20:00'})
    before = _reopened(client)
    response = client.post(_REMOVE_URL, headers=_HEADERS)
    assert response.status_code == 200
    after = _reopened(client)
    assert after == response.get_json()['itinerary']
    assert after['selectedFlight'] is None
    assert after['flightCost'] == after['budgetEstimate']['flight'] == 0
    assert after['flightAdjustmentStatus'] == 'review_required'
    assert after['flightAdjustmentReviewReason'] == 'flight_removed'
    assert after['budgetEstimate']['total'] == before['budgetEstimate']['total'] - 180
    for key in ('flightAdjustmentPreviewId', 'flightAdjustmentAppliedAt',
                'flightAdjustmentAssumptions', 'flightAdjustmentFlightFingerprint'):
        assert after[key] == before[key]
    _assert_nonflight_preserved(before, after)


@pytest.mark.parametrize('already_applied', [False, True])
@pytest.mark.parametrize('mutation', ['replace', 'remove', 'activity_edit'])
def test_preview_cannot_replay_over_changed_flight_or_activity(client, mock_traveller_auth, lifecycle_store, already_applied, mutation):
    preview_id = _preview_http(client)
    if already_applied:
        assert _apply_http(client, preview_id).status_code == 200
    if mutation == 'replace':
        assert _select_http(client).status_code == 200
    elif mutation == 'remove':
        assert client.post(_REMOVE_URL, headers=_HEADERS).status_code == 200
        assert client.post(_TRIP_URL + '/flight-adjustment/preview', headers=_HEADERS).status_code == 409
    else:
        lifecycle_store.records['pu3b_trip']['activities'][0]['userNote'] = 'Edited after preview'
    before = _reopened(client)
    writes = len(lifecycle_store.writes)
    response = _apply_http(client, preview_id)
    assert response.status_code == 409
    assert 'stale' in response.get_json()['error'].lower()
    assert _reopened(client) == before
    assert len(lifecycle_store.writes) == writes


def test_preview_loss_returns_404_and_refresh_can_apply_without_duplicate_writes(client, mock_traveller_auth, lifecycle_store):
    preview_id = _preview_http(client)
    reset_flight_adjustment_previews()  # Restart loses process-local previews, not persisted trips.
    assert _apply_http(client, preview_id).status_code == 404
    assert lifecycle_store.writes == []
    refreshed = _preview_http(client)
    assert _apply_http(client, refreshed).status_code == 200
    first = _reopened(client)
    assert _apply_http(client, refreshed).get_json()['idempotent'] is True
    assert _reopened(client) == first
    assert len(lifecycle_store.writes) == 1


def test_repeated_removal_does_not_restore_or_duplicate_schedule(client, mock_traveller_auth, lifecycle_store):
    preview_id = _apply_current(client)
    assert client.post(_REMOVE_URL, headers=_HEADERS).status_code == 200
    first = _reopened(client)
    assert client.post(_REMOVE_URL, headers=_HEADERS).status_code == 200
    second = _reopened(client)
    assert second['activities'] == first['activities']
    assert second['budgetEstimate'] == first['budgetEstimate']
    assert second['revision'] == first['revision']
    assert second['flightAdjustmentStatus'] == 'review_required'
    assert second['flightAdjustmentReviewReason'] == 'flight_removed'
    assert _apply_http(client, preview_id).status_code == 409


@pytest.mark.parametrize('action', ['replace', 'remove', 'preview', 'apply', 'reopen'])
def test_lifecycle_routes_enforce_trip_ownership(client, mock_traveller_auth, lifecycle_store, action):
    preview_id = _preview_http(client)
    lifecycle_store.records['pu3b_trip']['travellerId'] = 'another-traveller'
    if action == 'replace':
        response = _select_http(client)
    elif action == 'remove':
        response = client.post(_REMOVE_URL, headers=_HEADERS)
    elif action == 'preview':
        response = client.post(_TRIP_URL + '/flight-adjustment/preview', headers=_HEADERS)
    elif action == 'apply':
        response = _apply_http(client, preview_id)
    else:
        response = client.get(_TRIP_URL, headers=_HEADERS)
    assert response.status_code == 404
    assert lifecycle_store.writes == []


@pytest.mark.parametrize('package_fields', [{'tripType': 'package'}, {'packageTrip': True}])
@pytest.mark.parametrize('action', ['replace', 'remove'])
def test_package_trip_cannot_change_flight_selection(client, mock_traveller_auth, lifecycle_store, package_fields, action):
    lifecycle_store.records['pu3b_trip'].update(package_fields)
    before = deepcopy(lifecycle_store.records)
    response = (_select_http(client) if action == 'replace'
                else client.post(_REMOVE_URL, headers=_HEADERS))
    assert response.status_code == 409
    assert lifecycle_store.records == before
    assert lifecycle_store.writes == []


def test_legacy_applied_metadata_is_bound_to_previous_flight_on_replacement(client, mock_traveller_auth, lifecycle_store):
    trip = lifecycle_store.records['pu3b_trip']
    trip.update({'flightAdjustmentStatus': 'applied', 'flightAdjustmentPreviewId': 'legacy-preview',
                 'flightAdjustmentAppliedAt': '2026-10-01T12:00:00+08:00'})
    old_fingerprint = fingerprint(trip['selectedFlight'])
    assert _select_http(client).status_code == 200
    reopened = _reopened(client)
    assert reopened['flightAdjustmentStatus'] == 'review_required'
    assert reopened['flightAdjustmentFlightFingerprint'] == old_fingerprint
    assert reopened['flightAdjustmentPreviewId'] == 'legacy-preview'


def test_fresh_adjustment_clears_review_requirement_and_binds_new_flight(client, mock_traveller_auth, lifecycle_store):
    _apply_current(client)
    assert _select_http(client).status_code == 200
    _apply_current(client)
    reopened = _reopened(client)
    assert reopened['flightAdjustmentStatus'] == 'applied'
    assert reopened['flightAdjustmentReviewReason'] is None
    assert reopened['flightAdjustmentFlightFingerprint'] == fingerprint(reopened['selectedFlight'])


def test_same_selection_keeps_valid_adjustment_state(client, mock_traveller_auth, lifecycle_store):
    assert _select_http(client).status_code == 200
    _apply_current(client)
    before = _reopened(client)
    assert _select_http(client).status_code == 200
    after = _reopened(client)
    assert after['flightAdjustmentStatus'] == 'applied'
    assert after['revision'] == before['revision']


def test_never_adjusted_flight_change_does_not_fabricate_applied_history(client, mock_traveller_auth, lifecycle_store):
    assert _select_http(client).status_code == 200
    assert client.post(_REMOVE_URL, headers=_HEADERS).status_code == 200
    after = _reopened(client)
    assert 'flightAdjustmentStatus' not in after
    assert 'flightAdjustmentAppliedAt' not in after


def test_applied_preview_cannot_be_replayed_on_another_owned_trip(client, mock_traveller_auth, lifecycle_store):
    preview_id = _apply_current(client)
    other = deepcopy(lifecycle_store.records['pu3b_trip'])
    other['id'] = 'other_owned_trip'
    lifecycle_store.records[other['id']] = other
    response = _apply_http(client, preview_id, '/api/fr5/itineraries/other_owned_trip')
    assert response.status_code == 409
    assert len(lifecycle_store.writes) == 1


def test_preview_stays_stale_after_flight_changes_back_with_identical_timestamps(client, mock_traveller_auth, lifecycle_store):
    with patch('modules.fr07_flight_search.routes._now', return_value='2026-10-30T00:00:00Z'):
        original_flight = _flight()
        assert _select_http(client, original_flight).status_code == 200
        preview_id = _preview_http(client)
        assert _select_http(client).status_code == 200
        assert _select_http(client, original_flight).status_code == 200
    writes = len(lifecycle_store.writes)
    assert _apply_http(client, preview_id).status_code == 409
    assert len(lifecycle_store.writes) == writes

