"""Real FR4/FR5 requests with existing isolated evaluation evidence and in-memory Trips."""
from copy import deepcopy
import pytest
from test_pr93_continuation import integrated, generated, build, HEADERS
from modules.fr05_smart_itinerary_budget_planner import routes as r
from test_flexible_planning import planning, saved, preview as settings_preview
from test_pu3b_flight_adjustment import _flight


def command(trip, **extra):
    return {'planningChanges': {}, 'action': 'regenerate', 'scope': 'day', 'dayNo': 2,
            'expectedItineraryRevision': trip.get('itineraryRevision', 1), **extra}


def trip_fixture(client, integrated):
    memory, _ = integrated
    generation = generated(client)
    trip = build(client, generation).json['itinerary']
    trip['planningBlocks'] = [{'blockId': 'personal-lunch', 'label': 'Lunch break', 'dayNo': 2,
        'type': 'meal', 'boundary': 'personal', 'startTime': '12:00', 'endTime': '13:00', 'locked': True}]
    trip['itineraryRevision'] = 1
    memory.seed('itineraries', trip['id'], trip)
    return memory, trip, generation, '/api/fr5/itineraries/' + trip['id'] + '/flight-adjustment'


def test_expired_generation_is_not_reported_as_stale_trip(client, integrated):
    memory, trip, generation, path = trip_fixture(client, integrated)
    session = client.application.extensions['recommendation_evaluation']
    session.snapshots[generation] = (0, session.snapshots[generation][1])
    response = client.post(path + '/preview', headers=HEADERS, json=command(trip))
    assert response.status_code == 409
    assert response.json['code'] == 'RECOMMENDATION_EXPIRED'
    assert response.json['stage'] == 'recommendation_validation'
    assert response.json['nextAction'] == 'refresh_suggestions'
    assert memory.retrieve('itineraries', trip['id']) == trip


@pytest.mark.parametrize('scope', ['day', 'full'])
def test_explicit_new_generation_preview_cancel_apply_reopen_retains_blocks(client, integrated, scope):
    memory, trip, old, path = trip_fixture(client, integrated)
    session = client.application.extensions['recommendation_evaluation']
    session.snapshots[old] = (0, session.snapshots[old][1])
    new = generated(client)
    payload = command(trip, scope=scope, recommendationGenerationId=new,
                      refreshSuggestions=True, expectedLinkedGenerationId=old)
    response = client.post(path + '/preview', headers=HEADERS, json=payload)
    assert response.status_code == 200, response.json
    preview = response.json['preview']
    assert preview['canApply'], preview['reason']
    assert preview['after']['recommendationGenerationId'] == new
    assert preview['after']['planningBlocks'] == trip['planningBlocks']
    assert memory.retrieve('itineraries', trip['id']) == trip  # Cancel.
    applied = client.post(path + '/apply', headers=HEADERS, json={'previewId': preview['previewId']})
    assert applied.status_code == 200, applied.json
    saved = client.get('/api/fr5/itineraries/' + trip['id'], headers=HEADERS).json['itinerary']
    assert saved['recommendationGenerationId'] == new and saved['planningBlocks'] == trip['planningBlocks']
    assert saved['planningMode'] == trip['planningMode']
    assert client.post(path + '/apply', headers=HEADERS, json={'previewId': preview['previewId']}).json['idempotent']
    if scope == 'day':
        assert [row for row in saved['activities'] if row['dayNo'] != 2] == [row for row in trip['activities'] if row['dayNo'] != 2]


@pytest.mark.parametrize('fault', ['implicit', 'old_link', 'foreign', 'scope', 'stale', 'context'])
def test_generation_substitution_requires_explicit_matching_owner_scope_and_revision(client, integrated, fault):
    memory, trip, old, path = trip_fixture(client, integrated)
    new = generated(client)
    payload = command(trip, recommendationGenerationId=new, refreshSuggestions=True, expectedLinkedGenerationId=old)
    headers = HEADERS
    session = client.application.extensions['recommendation_evaluation']
    if fault == 'implicit': payload.pop('refreshSuggestions')
    elif fault == 'old_link': payload['expectedLinkedGenerationId'] = 'fyp-evaluation-unrelated'
    elif fault == 'foreign': session.snapshots[new][1]['travellerId'] = 'other-test-owner'
    elif fault == 'scope': memory.update('itineraries', trip['id'], {'destinationArea': 'Melaka'})
    elif fault == 'stale': payload['expectedItineraryRevision'] = 99
    elif fault == 'context': headers = {'Authorization': HEADERS['Authorization']}
    before = deepcopy(memory.retrieve('itineraries', trip['id']))
    response = client.post(path + '/preview', headers=headers, json=payload)
    assert response.status_code == 409, response.json
    assert response.json['code'] and response.json['stage']
    assert memory.retrieve('itineraries', trip['id']) == before


@pytest.mark.parametrize('action,scope', [('improve', 'day'), ('improve', 'remaining'), ('regenerate', 'day'), ('regenerate', 'full')])
def test_penang_travel_day_lunch_context_and_all_four_actions(client, integrated, action, scope):
    memory, _ = integrated
    generation = generated(client)
    trip = build(client, generation, startDate='2026-11-25', endDate='2026-11-27').json['itinerary']
    trip['selectedFlight'] = _flight('2026-11-25', '14:50', '2026-11-27', '10:55')
    trip['travelMode'] = 'flight'
    trip['planningBlocks'] = [{'blockId': 'transit-lunch', 'label': 'Lunch break', 'type': 'meal', 'dayNo': 1,
        'boundary': 'personal', 'startTime': '12:00', 'endTime': '13:00', 'locked': True}]
    memory.seed('itineraries', trip['id'], trip)
    path = '/api/fr5/itineraries/' + trip['id'] + '/flight-adjustment'
    result = client.post(path + '/preview', headers=HEADERS, json=command(trip, action=action, scope=scope, dayNo=1))
    assert result.status_code == 200, result.json
    p = result.json['preview']
    assert p['canApply'], p['reason']
    assert p['after']['planningBlocks'] == trip['planningBlocks']
    assert p['availability']['days']['2026-11-25']['earliestStartMinutes'] == 17 * 60 + 50
    assert p['availability']['days']['2026-11-27']['latestEndMinutes'] == 7 * 60 + 25
    assert all(row['scheduledStartTime'] >= '17:50' for row in p['after']['activities'] if row['dayNo'] == 1)
    if scope != 'day':
        assert all(row['scheduledEndTime'] <= '07:25' for row in p['after']['activities'] if row['dayNo'] == 3)
    else:
        assert [row for row in p['after']['activities'] if row['dayNo'] != 1] == [row for row in trip['activities'] if row['dayNo'] != 1]
    assert memory.retrieve('itineraries', trip['id']) == trip
    assert client.post(path + '/apply', headers=HEADERS, json={'previewId': p['previewId']}).status_code == 200
    reopened = client.get('/api/fr5/itineraries/' + trip['id'], headers=HEADERS).json['itinerary']
    assert reopened['planningBlocks'] == trip['planningBlocks'] and reopened['selectedFlight'] == trip['selectedFlight']


@pytest.mark.parametrize('fault', ['preferences', 'review', 'restart', 'candidate', 'no_candidates'])
def test_recommendation_failures_have_specific_actions_and_no_writes(client, integrated, fault):
    memory, trip, generation, path = trip_fixture(client, integrated)
    session = client.application.extensions['recommendation_evaluation']
    if fault == 'preferences': memory.update('travel_preferences', 'test_traveller_uid', {'interests': ['Nature']})
    elif fault == 'review': session.mark_evidence_changed()
    elif fault == 'restart': client.application.extensions.pop('recommendation_evaluation')
    elif fault == 'candidate': session.snapshots[generation][1]['recommendationResults'][0]['recommendationGenerationId'] = 'wrong'
    else: session.snapshots[generation][1]['recommendationResults'] = []
    result = client.post(path + '/preview', headers=HEADERS, json=command(trip))
    assert result.status_code == 409, result.json
    assert result.json['code'] == ('NO_REGENERATION_CANDIDATES' if fault == 'no_candidates' else 'RECOMMENDATION_EXPIRED' if fault == 'restart' else 'RECOMMENDATION_REFRESH_REQUIRED')
    assert result.json['nextAction'] == ('keep_current' if fault == 'no_candidates' else 'refresh_suggestions')
    assert memory.retrieve('itineraries', trip['id']) == trip


def test_new_generation_preview_stales_after_trip_edit(client, integrated):
    memory, trip, old, path = trip_fixture(client, integrated)
    new = generated(client)
    p = client.post(path + '/preview', headers=HEADERS, json=command(trip, recommendationGenerationId=new,
        refreshSuggestions=True, expectedLinkedGenerationId=old)).json['preview']
    memory.update('itineraries', trip['id'], {'notes': 'Changed while preview open'})
    result = client.post(path + '/apply', headers=HEADERS, json={'previewId': p['previewId']})
    assert result.status_code == 409 and result.json['code'] == 'STALE_PREVIEW'
    assert memory.retrieve('itineraries', trip['id'])['recommendationGenerationId'] == old


@pytest.mark.parametrize('mode', ['smart', 'manual', 'assisted', None])
def test_settings_preserve_mode_including_legacy(client, planning, mode):
    memory, writes = planning
    trip = saved(memory, flight=False)
    if mode is None: trip.pop('planningMode', None)
    else: trip['planningMode'] = mode
    memory.seed('itineraries', 'flex', trip)
    p = settings_preview(client, {'travelDayPreferences': {'days': [{'dayNo': 2, 'startTime': '10:00', 'endTime': '17:00'}]}}).json['preview']
    assert p['canApply'] and p['after'].get('planningMode') == mode
    assert client.post('/api/fr5/itineraries/flex/flight-adjustment/apply', headers=HEADERS, json={'previewId': p['previewId']}).status_code == 200
    assert memory.retrieve('itineraries', 'flex').get('planningMode') == mode and len(writes) == 1


@pytest.mark.parametrize('times', [('15:00', '14:00'), ('10:00', '10:00'), ('23:00', '01:00'), ('10:00', None), (None, '11:00')])
def test_bad_personal_intervals_never_persist(client, planning, times):
    memory, writes = planning
    trip = saved(memory, flight=False)
    row = {'blockId': 'bad-block', 'label': 'Break', 'type': 'rest', 'dayNo': 1}
    for key, value in zip(('startTime', 'endTime'), times):
        if value is not None: row[key] = value
    response = settings_preview(client, {'planningBlocks': [row]})
    assert response.status_code == 400 and response.json['code'] == 'PLANNING_TIME_CONFLICT'
    assert memory.retrieve('itineraries', 'flex') == trip and not writes


def test_expired_genuine_snapshot_and_new_owned_genuine_evidence(client, planning):
    memory, writes = planning
    trip = saved(memory, flight=False)
    trip.update(recommendationGenerationId='old-genuine', itineraryRevision=1)
    memory.seed('itineraries', 'flex', trip)
    row = {'destinationId': 'local_new', 'title': 'Heritage museum', 'address': 'George Town, Penang', 'openingHours': '08:00-20:00'}
    memory.seed('recommendation_snapshots', 'old-genuine', {'travellerId': trip['travellerId'], 'destinationArea': 'Penang', 'expiresAt': '2000-01-01T00:00:00Z', 'items': [row]})
    result = settings_preview(client, {}, action='regenerate', scope='day', dayNo=2)
    assert result.status_code == 409 and result.json['nextAction'] == 'refresh_suggestions'
    memory.seed('recommendation_snapshots', 'new-genuine', {'recommendationGenerationId': 'new-genuine', 'travellerId': trip['travellerId'], 'destinationArea': 'Penang', 'items': [row]})
    result = settings_preview(client, {}, action='regenerate', scope='day', dayNo=2, recommendationGenerationId='new-genuine',
                              refreshSuggestions=True, expectedLinkedGenerationId='old-genuine', expectedItineraryRevision=1)
    assert result.status_code == 200, result.json
    assert result.json['preview']['after']['recommendationGenerationId'] == 'new-genuine' and not writes


def test_rest_day_regeneration_is_no_change_not_silent_deletion(client, integrated):
    memory, trip, _, path = trip_fixture(client, integrated)
    trip['travelDayPreferences'] = {'days': [{'dayNo': 2, 'restDay': True}]}
    memory.seed('itineraries', trip['id'], trip)
    response = client.post(path + '/preview', headers=HEADERS, json=command(trip))
    assert response.status_code == 409, response.json
    assert response.json['code'] == 'NO_REGENERATION_CANDIDATES'
    assert memory.retrieve('itineraries', trip['id']) == trip


@pytest.mark.parametrize('change', ['block_edit', 'daily_hours', 'fixed', 'paid'])
def test_regeneration_rechecks_changed_constraints_and_preserves_protected_rows(client, integrated, change):
    memory, trip, _, path = trip_fixture(client, integrated)
    if change == 'block_edit': trip['planningBlocks'][0].update(startTime='13:00', endTime='14:00')
    elif change == 'daily_hours': trip['travelDayPreferences'] = {'days': [{'dayNo': 2, 'startTime': '10:00', 'endTime': '17:00'}]}
    else:
        # Protect a visit outside the selected scope and verify exact preservation.
        trip['activities'][0]['fixed' if change == 'fixed' else 'paymentId'] = True if change == 'fixed' else 'isolated-payment-reference'
    memory.seed('itineraries', trip['id'], trip)
    p = client.post(path + '/preview', headers=HEADERS, json=command(trip)).json['preview']
    assert p['after']['planningBlocks'] == trip['planningBlocks']
    if change in {'fixed', 'paid'}:
        assert next(row for row in p['after']['activities'] if row['activityId'] == trip['activities'][0]['activityId']) == trip['activities'][0]
    assert memory.retrieve('itineraries', trip['id']) == trip


@pytest.mark.parametrize('start,end', [('15:00', '14:00'), ('10:00', '10:00')])
def test_same_day_arrival_departure_preference_conflict_cannot_apply(client, planning, start, end):
    memory, writes = planning
    trip = saved(memory, flight=False)
    trip['endDate'] = trip['startDate']
    memory.seed('itineraries', 'flex', trip)
    p = settings_preview(client, {'travelDayPreferences': {'arrival': {'choice': 'custom', 'startTime': start},
        'departure': {'choice': 'custom', 'endTime': end}}}).json['preview']
    assert not p['canApply'] and p['code'] == 'PLANNING_TIME_CONFLICT'
    assert client.post('/api/fr5/itineraries/flex/flight-adjustment/apply', headers=HEADERS, json={'previewId': p['previewId']}).status_code == 409
    assert not writes
