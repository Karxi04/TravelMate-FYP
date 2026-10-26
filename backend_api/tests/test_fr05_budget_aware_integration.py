"""Offline Flask generation acceptance. Every price/reference/user is synthetic."""
from contextlib import contextmanager
from copy import deepcopy
import json
from statistics import median
from time import perf_counter
from unittest.mock import patch

import pytest

from modules.fr05_smart_itinerary_budget_planner import routes
from services import budget_aware_generation as adapter
from sequence_contract.domain_functions import calculateBudget, generateItinerary
from test_budget_aware_selection import activity, trip, unknown


FLAG = 'TRAVELMATE_BUDGET_AWARE_SELECTION_ENABLED'
HEADERS = {'Authorization': 'Bearer valid_test_token'}
PATH = '/api/fr5/itineraries/integration/generate'
NOW = '2026-10-26T00:00:00+00:00'


def candidates():
    return [activity('A', 100, 90, 'per_group'), activity('B', 50, 65, 'per_group', category='heritage'),
            activity('C', 50, 64, 'per_group', category='gallery')]


@contextmanager
def fixture(items=None, **changes):
    current = trip(**{'id': 'integration', 'travellerId': 'test_traveller_uid', 'activities': [],
                   'budgetLimit': 255, 'recommendationGenerationId': 'rec-integration', **changes})
    source = [{**item, 'title': item['activityName']} for item in (items if items is not None else candidates())]
    snapshot = {'recommendationGenerationId': 'rec-integration', 'travellerId': 'test_traveller_uid',
                'requestedDestination': 'Penang', 'source': 'offline_fixture', 'recommendationResults': source,
                'engine': {'weightedScoring': {'content': .60, 'collaborative': .30, 'popularity': .10}}}
    initial, original_snapshot = deepcopy(current), deepcopy(snapshot)

    def retrieve(collection, document_id=None, **kwargs):
        if collection == 'itineraries':
            return deepcopy(current)
        if collection == 'recommendation_snapshots':
            return deepcopy(snapshot)
        raise AssertionError('Unexpected read outside isolated generation fixtures')

    def persist(collection, document_id, values):
        assert collection == 'itineraries' and document_id == 'integration'
        current.update(deepcopy(values))
        return deepcopy(current)

    def forbidden(*args, **kwargs):
        raise AssertionError('No provider request or new record is authorized')

    with patch.object(routes, 'retrieveRecord', side_effect=retrieve), \
         patch.object(routes, 'updateRecord', side_effect=persist) as writes, \
         patch.object(routes, 'storeRecord', side_effect=forbidden), \
         patch.object(routes, 'retrieveDestinationResults', side_effect=forbidden), \
         patch.object(routes, 'geocode', side_effect=forbidden), \
         patch.object(routes, 'retrieveSevenDayForecast', side_effect=forbidden), \
         patch.object(routes, '_forecast_for', return_value=({}, None)), \
         patch.object(routes, 'utc_now_iso', return_value=NOW), \
         patch('sequence_contract.domain_functions.utc_now_iso', return_value=NOW):
        yield current, snapshot, initial, writes
    assert snapshot == original_snapshot


@pytest.mark.parametrize('value', [None, 'false', '0', 'invalid'])
def test_disabled_flag_has_exact_legacy_generation_parity(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(FLAG, raising=False)
    else:
        monkeypatch.setenv(FLAG, value)
    with fixture() as (current, snapshot, _, _), patch.object(routes, 'generate_with_budget_selection') as selector:
        generated = routes._generate_itinerary_data(current, {}, snapshot)
        mapped = [{**item, 'recommendationGenerationId': 'rec-integration'} for item in snapshot['recommendationResults']]
        working = {**current, 'activities': [routes._activity_from_destination(item, index) for index, item in enumerate(mapped)]}
        locations = routes.retrieveLocationAndTravelTime(working['activities'])
        expected = generateItinerary(locations, {}, working)
        expected['generationContext'].update({'destinationSource': 'offline_fixture',
            'destinationCoordinates': None, 'recommendationGenerationId': 'rec-integration'})
        assert generated == expected
        selector.assert_not_called()


def test_request_body_query_and_headers_cannot_enable_flag(client, mock_traveller_auth, monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    with fixture(), patch.object(routes, 'generate_with_budget_selection') as selector:
        response = client.post(PATH + '?budgetAwareSelection=true',
            headers={**HEADERS, FLAG: 'true'}, json={FLAG: True, 'budgetAwareSelectionEnabled': True})
        assert response.status_code == 200
        assert len(response.json['itinerary']['activities']) == 3
        assert 'budgetAwareSelection' not in response.json['itinerary']
        selector.assert_not_called()


def test_enabled_real_http_path_preserves_scores_repair_and_persistence(client, mock_traveller_auth, monkeypatch):
    monkeypatch.setenv(FLAG, 'true')
    with fixture() as (current, snapshot, _, writes), \
         patch.object(adapter, 'select_budget_aware_activities', wraps=adapter.select_budget_aware_activities) as selector, \
         patch.object(routes, 'generateItinerary', wraps=generateItinerary) as legacy_scheduler:
        response = client.post(PATH, headers=HEADERS, json={FLAG: False})
        assert response.status_code == 200, response.json
        assert response.json['ok'] is True and response.json['status'] == 'planned'
        saved = response.json['itinerary']
        assert selector.call_count == 1
        assert [item['score'] for item in selector.call_args.args[0]] == [90, 65, 64]
        legacy_scheduler.assert_not_called()  # Reuse the selector's already validated schedule.
        assert {item['destinationId'] for item in saved['activities']} == {'synthetic-B', 'synthetic-C'}
        assert [item['score'] for item in saved['activities']] == [65, 64]
        assert saved['budgetAwareSelection']['localRepairImproved'] is True
        assert saved['budgetEstimate']['totalEstimatedCost'] == 255
        assert saved['budgetEstimate']['activities'] == 100
        assert saved['budgetEstimate']['completenessStatus'] == 'complete'
        assert writes.call_count == 2  # Existing generating -> planned persistence boundaries.
        assert current == saved
        assert snapshot['engine']['weightedScoring'] == {'content': .6, 'collaborative': .3, 'popularity': .1}
        assert set(response.json) == {'ok', 'id', 'tripId', 'status', 'itinerary', 'smartFeatures'}


@pytest.mark.parametrize('items', [[unknown('u1'), unknown('u2')],
    [activity('conditional', pricingEvidence={'applicability': 'conditional', 'eligibility': 'MyKad_or_adult'})]])
def test_unknown_or_conditional_http_generation_is_provisional_not_free(client, mock_traveller_auth, monkeypatch, items):
    monkeypatch.setenv(FLAG, 'true')
    with fixture(items) as (current, _, _, _):
        response = client.post(PATH, headers=HEADERS, json={})
        assert response.status_code == 200, response.json
        saved = response.json['itinerary']
        assert len(saved['activities']) == len(items)
        selection = saved['budgetAwareSelection']
        assert selection['selectionMode'] == 'provisional_unpriced_fallback'
        assert selection['budget']['categoryTotals']['activities'] is None
        assert all(item['selectionGroupCost'] is None for item in saved['activities'])
        assert saved['dailySchedule'][0]['applicableActivityCost'] is None
        assert isinstance(saved['dailySchedule'][0]['estimatedCost'], (int, float))
        assert saved['budgetEstimate']['affordabilityStatus'] == 'incomplete'
        assert saved['budgetEstimate']['completenessStatus'] == 'incomplete'
        assert 'activities' in saved['budgetEstimate']['pendingExpenseCategories']
        assert 'incomplete' in saved['budgetEstimate']['comparison'].lower()
        assert 'estimatedSavings' not in selection
        assert current['budgetEstimate'] == saved['budgetEstimate']
        assert calculateBudget(saved)['completenessStatus'] == 'incomplete'


def test_mixed_pool_and_pending_flight_remain_incomplete(client, mock_traveller_auth, monkeypatch):
    monkeypatch.setenv(FLAG, 'true')
    with fixture([activity('known', 20), unknown('u')], travelMode='flight'):
        response = client.post(PATH, headers=HEADERS, json={})
        saved = response.json['itinerary']
        assert response.status_code == 200
        assert len(saved['activities']) == 1
        assert saved['budgetEstimate']['activities'] == 40
        assert set(saved['budgetEstimate']['pendingExpenseCategories']) == {'flight', 'activities'}
        assert saved['budgetEstimate']['affordabilityStatus'] == 'incomplete'


def test_four_person_group_budget_is_not_multiplied_twice(client, mock_traveller_auth, monkeypatch):
    monkeypatch.setenv(FLAG, 'true')
    with fixture([activity('person', 20), activity('group', 25, 70, 'per_group')],
                 travellerCount=4, budgetLimit=400):
        response = client.post(PATH, headers=HEADERS, json={})
        assert response.status_code == 200
        assert response.json['itinerary']['budgetEstimate']['activities'] == 105
        assert response.json['itinerary']['budgetEstimate']['totalEstimatedCost'] == 380


@pytest.mark.parametrize('budget,count', [(255, 2), (500, 3)])
def test_low_and_high_budget_route_results(client, mock_traveller_auth, monkeypatch, budget, count):
    monkeypatch.setenv(FLAG, 'true')
    with fixture(budgetLimit=budget):
        response = client.post(PATH, headers=HEADERS, json={})
        assert response.status_code == 200
        assert len(response.json['itinerary']['activities']) == count


@pytest.mark.parametrize('problem', ['closed', 'travel', 'geography'])
def test_integration_rejects_infeasible_replacements(client, mock_traveller_auth, monkeypatch, problem):
    monkeypatch.setenv(FLAG, 'true')
    items = candidates()
    if problem == 'closed':
        items[2]['openingHours'] = 'Closed'
    elif problem == 'travel':
        for item in items:
            item['openingHours'] = '09:00-10:00'
        items[2].update({'providerTravelDurationMinutes': 90, 'travelTimeSource': 'provider'})
    else:
        items[2]['gps_coordinates'] = {'latitude': 3.14, 'longitude': 101.69}
    with fixture(items):
        response = client.post(PATH, headers=HEADERS, json={})
        assert response.status_code == 200
        assert [item['destinationId'] for item in response.json['itinerary']['activities']] == ['synthetic-A']


def test_unknown_hours_weather_and_density_safeguards_survive(client, mock_traveller_auth, monkeypatch):
    monkeypatch.setenv(FLAG, 'true')
    items = [activity('indoor', 0, openingHours='Closed now', indoor=True, recommendedDurationMinutes=180)]
    with fixture(items), patch.object(routes, '_forecast_for', return_value=({'daily': {
            'time': ['2026-11-01'], 'precipitation_probability_max': [90], 'weather_code': [61]}}, None)):
        response = client.post(PATH, headers=HEADERS, json={})
        assert response.status_code == 200
        saved = response.json['itinerary']
        assert saved['budgetAwareSelection']['schedulingStatus'] == 'provisional'
        assert saved['activities'][0]['weather']['heavyRainLikely'] is True
        assert saved['activities'][0]['scheduleFeasibility'] == 'provisional'


def test_fixed_overrun_returns_truthful_empty_selection(client, mock_traveller_auth, monkeypatch):
    monkeypatch.setenv(FLAG, 'true')
    with fixture([unknown()], foodCost=300):
        response = client.post(PATH, headers=HEADERS, json={})
        assert response.status_code == 200
        saved = response.json['itinerary']
        assert saved['activities'] == []
        assert saved['budgetEstimate']['affordabilityStatus'] == 'over_budget'
        assert saved['budgetAwareSelection']['schedulingStatus'] == 'no_activities_selected'


def test_existing_snapshot_reads_and_existing_activities_are_not_reselected(client, mock_traveller_auth, monkeypatch):
    monkeypatch.setenv(FLAG, 'true')
    with fixture() as (current, snapshot, _, writes), patch.object(routes, 'generate_with_budget_selection') as selector:
        current['activities'] = [routes._activity_from_destination(snapshot['recommendationResults'][0], 0)]
        before = deepcopy(current)
        response = client.get('/api/fr5/itineraries/integration', headers=HEADERS)
        assert response.status_code == 200 and response.json['itinerary'] == before
        writes.assert_not_called()
        response = client.post(PATH, headers=HEADERS, json={})
        assert response.status_code == 200
        assert response.json['itinerary']['budgetAwareSelection']['reason'] == 'existing_activities_preserved'
        selector.assert_not_called()


def test_missing_scores_does_not_invent_personality_scores(client, mock_traveller_auth, monkeypatch):
    monkeypatch.setenv(FLAG, 'true')
    items = candidates()
    for item in items:
        item.pop('score')
    with fixture(items), patch.object(routes, 'generate_with_budget_selection') as selector:
        response = client.post(PATH, headers=HEADERS, json={})
        assert response.status_code == 200
        assert response.json['itinerary']['budgetAwareSelection']['applied'] is False
        assert len(response.json['itinerary']['activities']) == 3
        selector.assert_not_called()


def test_enabled_generation_is_repeatable_and_failure_keeps_existing_error_contract(client, mock_traveller_auth, monkeypatch):
    monkeypatch.setenv(FLAG, 'true')
    with fixture() as (current, snapshot, _, _):
        assert routes._generate_itinerary_data(current, {}, snapshot) == routes._generate_itinerary_data(current, {}, snapshot)
        with patch.object(adapter, 'select_budget_aware_activities', side_effect=ValueError('Invalid offline candidate score')):
            response = client.post(PATH, headers=HEADERS, json={})
            assert response.status_code == 500
            assert response.json['status'] == 'generation_failed'
            assert current['status'] == 'generation_failed'


def test_personalised_planned_retry_is_reused_without_recalculation(client, mock_traveller_auth, monkeypatch):
    monkeypatch.setenv(FLAG, 'true')
    with fixture() as (current, _, _, writes), patch.object(routes, 'generate_with_budget_selection') as selector:
        current.update({'status': 'planned', 'budgetEstimate': {'historical': 'preserve exactly'}})
        before = deepcopy(current)
        response = client.post('/api/fr5/personalised-trips/generate', headers=HEADERS,
            json={**trip(), 'generationRequestId': 'offline-retry-request', 'recommendationGenerationId': 'rec-integration'})
        assert response.status_code == 200 and response.json['reused'] is True
        assert response.json['itinerary'] == before
        writes.assert_not_called()
        selector.assert_not_called()


def test_generation_integration_benchmark(monkeypatch, capsys):
    rows = []
    fixtures = {'repair': candidates(), 'unknown': [unknown('u1'), unknown('u2')],
                'pool20': [activity(f'p{i}', i % 5, 100-i*2, 'per_group') for i in range(20)]}
    for name, items in fixtures.items():
        for enabled in (False, True):
            monkeypatch.setenv(FLAG, str(enabled).lower())
            with fixture(items, **({'endDate': '2026-11-03', 'budgetLimit': 2000} if name == 'pool20' else {})) as (current, snapshot, _, _):
                times = []
                for _ in range(3):
                    start = perf_counter()
                    generated = routes._generate_itinerary_data(current, {}, snapshot)
                    times.append((perf_counter()-start)*1000)
                selected = generated['activities']
                scores = {item['destinationId']: item['score'] for item in snapshot['recommendationResults']}
                total = sum(scores[item['destinationId']] for item in selected)
                rows.append({'fixture': name, 'enabled': enabled, 'count': len(selected), 'scoreSum': total,
                    'averageScore': round(total/len(selected), 2) if selected else None,
                    'variety': len({item['category'] for item in selected}),
                    'travelMinutes': sum(item['travelDurationMinutes'] for item in selected),
                    'legacyEstimateTotal': calculateBudget(generated)['totalEstimatedCost'],
                    'selectionBudget': generated.get('budgetAwareSelection', {}).get('budget'),
                    'medianMs': round(median(times), 3), 'maxMs': round(max(times), 3)})
                assert max(times) < 5000
    with capsys.disabled():
        print('\nFR05_FLAGGED_INTEGRATION_BENCHMARK=' + json.dumps(rows, sort_keys=True))
