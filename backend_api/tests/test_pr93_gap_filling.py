"""Controlled candidate evidence only: no providers or production persistence."""
from copy import deepcopy
import pytest
from services.flexible_planning import fill_available_time
from sequence_contract.domain_functions import generateItinerary
from test_pr93_relaxed_evening import attraction
from test_flexible_planning import planning
from test_fr05_advisory_apply import HEADERS
from modules.fr05_smart_itinerary_budget_planner import routes as routes
from test_pr93_continuation import integrated, generated, build


def saved():
    return {'id': 'gaps', 'travellerId': 'test_traveller_uid', 'title': 'Controlled Penang trip',
            'destinationArea': 'Penang', 'startDate': '2026-11-25', 'endDate': '2026-11-29',
            'travelPace': 'active', 'planningMode': 'smart', 'travellerCount': 2, 'budgetLimit': 5000,
            'planningPreferences': {'interests': ['Culture']}, 'itineraryRevision': 1,
            'travelDayPreferences': {}, 'activities': [
                attraction('fixed', '08:00-17:00', dayNo=2, fixed=True,
                           scheduledStartTime='14:00', scheduledEndTime='15:00', notes='Keep')],
            'dailySchedule': [{'dayNo': day, 'activities': [], 'planningBlocks': []} for day in range(1, 6)]}


def evening(identity='late', **extra):
    return attraction(identity, '18:00-22:00', city='George Town', state='Penang',
                      country='Malaysia', address='Penang, Malaysia', pricingUnit='per_group', costProvenance='catalog_estimate', **extra)


def test_fills_real_evening_gap_without_moving_fixed_visit():
    trip = saved(); before = deepcopy(trip)
    result, evidence = fill_available_time(trip, [evening()], {2})
    assert evidence['addedCount'] == 1, evidence
    assert result['activities'][0] == trip['activities'][0]
    assert result['activities'][1]['scheduledStartTime'] == '18:00'
    assert result['activities'][1]['scheduledEndTime'] == '19:00'
    assert result['activities'][1]['dayNo'] == 2
    assert trip == before


@pytest.mark.parametrize('case', ['closed', 'block', 'far', 'budget', 'duplicate', 'unknown_price', 'rest'])
def test_rejects_infeasible_additions(case):
    trip, candidate = saved(), evening()
    if case == 'closed': candidate['openingHours'] = 'Closed'
    if case == 'block': trip['planningBlocks'] = [{'dayNo': 2, 'type': 'rest', 'startTime': '17:00', 'endTime': '21:30'}]
    if case == 'far': candidate['gps_coordinates'] = {'latitude': 6, 'longitude': 116}
    if case == 'budget': trip['budgetLimit'] = 11
    if case == 'duplicate': candidate['destinationId'] = 'fixed'
    if case == 'unknown_price': candidate.pop('estimatedCost')
    if case == 'rest': trip['travelDayPreferences'] = {'days': [{'dayNo': 2, 'restDay': True}]}
    result, evidence = fill_available_time(trip, [candidate], {2})
    assert evidence['addedCount'] == 0
    assert result['activities'] == trip['activities']
    assert evidence['message'].startswith('No suitable')


def test_balances_additions_across_remaining_days_and_deduplicates():
    trip = saved()
    candidates = [evening(str(index)) for index in range(8)]
    result, evidence = fill_available_time(trip, candidates + candidates, {2, 3, 4, 5})
    rows = result['activities']
    assert evidence['addedCount'] == 8, evidence
    assert {row['dayNo'] for row in rows} == {2, 3, 4, 5}
    assert len({row['destinationId'] for row in rows}) == len(rows)
    assert all(row['scheduledEndTime'] <= '21:30' for row in rows)


@pytest.mark.parametrize('scope', ['day', 'remaining'])
def test_real_preview_cancel_apply_reopen_with_owned_extra_candidates(client, planning, monkeypatch, scope):
    memory, writes = planning
    trip = saved(); memory.seed('itineraries', 'gaps', trip)
    snapshot = {'recommendationGenerationId': 'owned', 'recommendationResults': [
        {**evening(), 'title': 'Evening museum', 'recommendationGenerationId': 'owned'}]}
    monkeypatch.setattr(routes, '_regeneration_snapshot', lambda *_: (snapshot, None))
    path = '/api/fr5/itineraries/gaps/flight-adjustment'
    command = {'action': 'improve', 'scope': scope, 'dayNo': 2, 'planningChanges': {}, 'expectedItineraryRevision': 1}
    response = client.post(path + '/preview', headers=HEADERS, json=command)
    assert response.status_code == 200, response.json
    p = response.json['preview']; assert p['canApply'], p['reason']
    assert p['gapFilling']['addedCount'] == 1, p['gapFilling']
    assert any(row['kind'] == 'added' for row in p['changes'])
    assert memory.retrieve('itineraries', 'gaps') == trip and not writes
    # Cancel by retaining the current plan; another preview must remain side-effect free.
    p = client.post(path + '/preview', headers=HEADERS, json=command).json['preview']
    assert not writes
    applied = client.post(path + '/apply', headers=HEADERS, json={'previewId': p['previewId']})
    assert applied.status_code == 200, applied.json
    reopened = client.get('/api/fr5/itineraries/gaps', headers=HEADERS).json['itinerary']
    assert len(reopened['activities']) == 2
    assert reopened['activities'][0]['notes'] == 'Keep'
    assert reopened['dailySchedule'][0] == trip['dailySchedule'][0]
    assert client.post(path + '/apply', headers=HEADERS, json={'previewId': p['previewId']}).json['idempotent']


def test_expired_evidence_does_not_disable_improve(client, planning, monkeypatch):
    memory, _ = planning; trip = saved(); memory.seed('itineraries', 'gaps', trip)
    monkeypatch.setattr(routes, '_regeneration_snapshot', lambda *_: (None, 'expired'))
    response = client.post('/api/fr5/itineraries/gaps/flight-adjustment/preview', headers=HEADERS,
                           json={'action': 'improve', 'scope': 'day', 'dayNo': 2, 'planningChanges': {}})
    assert response.status_code == 200
    assert response.json['preview']['additionalEvidenceStatus'] == 'unavailable'
    assert memory.retrieve('itineraries', 'gaps') == trip


def test_packed_five_days_uses_more_than_twenty_candidates_and_skips_rest_day():
    trip = saved(); trip.update(activities=[attraction(str(i), '08:00-21:30') for i in range(30)],
        geographyPlanningPolicy='local-days-v1', travelDayPreferences={'days': [{'dayNo': 3, 'restDay': True}]})
    trip['activities'][0].update(openingHours='Closed')
    result = generateItinerary([], {}, trip)
    counts = [len(day['activities']) for day in result['dailySchedule']]
    assert counts == [5, 5, 0, 5, 5]
    assert len({row['destinationId'] for row in result['activities']}) == 20


def test_actual_smart_route_expands_owned_pool_beyond_twenty(client, integrated):
    memory, blocked = integrated
    memory.update('travel_preferences', 'test_traveller_uid', {'travelPace': 'active'})
    generation = generated(client)
    snapshot = client.application.extensions['recommendation_evaluation'].snapshots[generation][1]
    snapshot['planningPreferences']['travelPace'] = 'active'
    snapshot['recommendationResults'] = [
        {**evening(str(index)), 'openingHours': '08:00-21:30', 'title': f'Controlled museum {index}',
         'score': 100 - index, 'recommendationGenerationId': generation} for index in range(35)]
    result = build(client, generation, startDate='2026-11-25', endDate='2026-11-29', budgetLimit=5000)
    assert result.status_code == 200, result.json
    trip = result.json['itinerary']
    assert len(trip['activities']) == 25
    assert len(trip['activities']) + len(trip['unscheduledSuggestions']) == 35
    assert [len(day['activities']) for day in trip['dailySchedule']] == [5] * 5
    assert not blocked.called


def test_unknown_hours_provisional_and_flight_arrival_restricts_gap():
    trip = saved()
    trip.update(selectedFlight={'outboundSegments': [{'arrivalAirportCode': 'PEN',
        'arrivalDate': '2026-11-25', 'arrivalTime': '14:50'}]})
    candidate = evening(); candidate['openingHours'] = ''
    result, evidence = fill_available_time(trip, [candidate], {1})
    assert evidence['addedCount'] == 1
    row = result['activities'][-1]
    assert row['scheduledStartTime'] >= '17:50'
    assert row['scheduleFeasibility'] == 'provisional'


@pytest.mark.parametrize('days', [1, 5, 14])
def test_candidate_and_activity_counts_remain_bounded(days):
    trip = saved(); trip.update(endDate=f'2026-12-{days - 6:02d}' if days > 6 else f'2026-11-{24+days}',
        activities=[], dailySchedule=[])
    result, evidence = fill_available_time(trip, [evening(str(i)) for i in range(80)], set(range(1, days + 1)))
    assert evidence['addedCount'] <= min(70, days * 5)
    assert len(result['activities']) <= min(70, days * 5)
