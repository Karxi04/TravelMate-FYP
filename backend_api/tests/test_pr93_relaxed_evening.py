"""Controlled scheduling evidence, not live venue availability."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from test_pr93_continuation import integrated, generated, build, HEADERS

from sequence_contract.domain_functions import generateItinerary


def attraction(identity, hours, **extra):
    return {'activityId': identity, 'destinationId': identity, 'activityName': identity,
            'category': 'museum', 'openingHours': hours,
            'providerDurationMinutes': 60, 'estimatedCost': 10,
            'gps_coordinates': {'latitude': 5.4, 'longitude': 100.3}, **extra}


def trip(**extra):
    return {'startDate': '2026-11-25', 'endDate': '2026-11-25',
            'planningMode': 'smart', 'travelPace': 'relaxed',
            'planningPreferences': {'interests': ['Culture']},
            'activities': [attraction('evening', '18:00-20:00'),
                           attraction('morning', '10:00-12:00'),
                           attraction('lower-priority', '10:00-17:00')], **extra}


def test_relaxed_considers_high_priority_evening_without_losing_morning():
    source = trip()
    before = deepcopy(source)
    result = generateItinerary([], {}, source)
    assert [row['activityId'] for row in result['activities']] == ['morning', 'evening']
    assert result['activities'][1]['scheduledStartTime'] == '18:00'
    assert result['dailySchedule'][0]['planningWindow']['endTime'] == '20:00'
    assert len(result['activities']) == 2
    assert source == before


def test_relaxed_does_not_force_evening_over_better_daytime_options():
    source = trip()
    source['activities'] = [source['activities'][1], source['activities'][2], source['activities'][0]]
    result = generateItinerary([], {}, source)
    assert [row['activityId'] for row in result['activities']] == ['morning', 'lower-priority']


CASES = json.loads((Path(__file__).parent / 'fixtures/pr93_relaxed_scheduling.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['name'])
def test_shared_relaxed_schedule_contract(case):
    source, expected = deepcopy(case['trip']), case['expected']
    before = deepcopy(source)
    result = generateItinerary([], {}, source)
    rows = result['activities']
    assert [row['activityId'] for row in rows] == expected['ids']
    for field, name in [('starts', 'scheduledStartTime'), ('ends', 'scheduledEndTime')]:
        if field in expected:
            assert [row[name] for row in rows] == expected[field]
    if 'window' in expected:
        window = result['dailySchedule'][0]['planningWindow']
        assert [window['startTime'], window['endTime']] == expected['window']
    for row in rows:
        if row['activityId'] in expected.get('provisional', []):
            assert row['scheduleFeasibility'] == 'provisional'
        assert row['scheduledEndTime'] <= result['dailySchedule'][0]['planningWindow']['endTime']
    assert len(rows) <= 2
    assert {row['activityId'] for row in rows + result['unscheduledSuggestions']} == {row['activityId'] for row in source['activities']}
    assert source == before


@pytest.mark.parametrize('scope', ['day', 'remaining'])
def test_real_smart_create_improve_cancel_apply_reopen(client, integrated, scope):
    memory, blocked = integrated
    memory.update('travel_preferences', 'test_traveller_uid', {'travelPace': 'relaxed'})
    generation = generated(client)
    snapshot = client.application.extensions['recommendation_evaluation'].snapshots[generation][1]
    snapshot['planningPreferences']['travelPace'] = 'relaxed'
    snapshot['recommendationResults'] = [
        {**row, 'title': row['activityName'], 'address': 'Penang, Malaysia',
         'city': 'George Town', 'state': 'Penang', 'country': 'Malaysia',
         'recommendationGenerationId': generation, 'score': 95 - index * 20}
        for index, row in enumerate(trip()['activities'])]
    prefs = {'days': [{'dayNo': 1, 'startTime': '10:00', 'endTime': '20:00'}]}
    response = build(client, generation, startDate='2026-11-25', endDate='2026-11-25',
                     travelDayPreferences=prefs)
    assert response.status_code == 200, response.json
    created = response.json['itinerary']
    assert [row['destinationId'] for row in created['activities']] == ['morning', 'evening']
    assert created['activities'][-1]['scheduledStartTime'] == '18:00'
    created['planningBlocks'] = [{'blockId': 'personal-rest', 'dayNo': 1, 'type': 'rest',
                                  'label': 'Personal rest', 'startTime': '14:00', 'endTime': '15:00'}]
    created['activities'][0].update(fixed=True, notes='Preserve my morning visit')
    memory.seed('itineraries', created['id'], created)
    before = deepcopy(memory.retrieve('itineraries', created['id']))
    path = '/api/fr5/itineraries/' + created['id']
    request = {'planningChanges': {}, 'action': 'improve', 'scope': scope,
               'dayNo': 1, 'expectedItineraryRevision': int(before.get('itineraryRevision') or 1)}
    preview = client.post(path + '/flight-adjustment/preview', headers=HEADERS, json=request)
    assert preview.status_code == 200, preview.json
    proposal = preview.json['preview']
    assert proposal['canApply'], proposal['reason']
    assert memory.retrieve('itineraries', created['id']) == before  # Cancel means no Apply request.
    assert proposal['after']['activities'][0]['notes'] == 'Preserve my morning visit'
    applied = client.post(path + '/flight-adjustment/apply', headers=HEADERS,
                          json={'previewId': proposal['previewId']})
    assert applied.status_code == 200, applied.json
    reopened = client.get(path, headers=HEADERS).json['itinerary']
    assert reopened['travelDayPreferences']['days'] == prefs['days']
    assert reopened['travelDayPreferences'].get('confirmedFor')
    assert reopened['planningBlocks'] == created['planningBlocks']
    assert [row['destinationId'] for row in reopened['activities']] == (
        ['morning', 'lower-priority', 'evening'] if scope == 'day' else ['morning', 'evening'])
    assert reopened['activities'][-1]['scheduledEndTime'] <= '20:00'
    assert not blocked.called
