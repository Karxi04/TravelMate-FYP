from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Lock, Event
from time import sleep

import pytest

from test_fr05_itinerary import _memory_storage, _personalised_payload, _generated_itinerary
from test_fr11_destination_intent_integrity import offline_chat
from modules.fr05_smart_itinerary_budget_planner import routes as fr5
from modules.fr11_chatbot_travel_assistant import routes as fr11


@pytest.fixture
def generation(monkeypatch):
    records, read, store, update = _memory_storage()
    lock = Lock()
    def claim(collection, identity, data):
        with lock:
            current = read(collection, identity)
            return (current, False) if current else (store(collection, data, identity), True)
    monkeypatch.setattr(fr5, 'retrieveRecord', read)
    monkeypatch.setattr(fr5, 'claimRecord', claim)
    monkeypatch.setattr(fr5, 'updateRecord', update)
    monkeypatch.setattr(fr5, 'calculateBudget', lambda _: {'total': 350, 'limit': 1200})
    monkeypatch.setattr(fr5, 'compareBudget', lambda _: 'Within budget')
    return records


def test_completion_after_timeout_status_and_retry_do_not_regenerate(app, client, mock_traveller_auth, generation, monkeypatch):
    started, release = Event(), Event()
    calls = []
    def delayed(current, payload, snapshot):
        calls.append('generate'); started.set()
        assert release.wait(3)
        return _generated_itinerary(current, payload, snapshot)
    monkeypatch.setattr(fr5, '_generate_itinerary_data', delayed)
    auth = {'Authorization': 'Bearer valid_test_token'}
    body = _personalised_payload()
    def send():
        with app.test_client() as connection:
            return connection.post('/api/fr5/personalised-trips/generate', headers=auth, json=body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(send)
        assert started.wait(3)
        second = send()
        assert second.status_code == 202
        status_url = '/api/fr5/personalised-trips/status?generationRequestId=' + body['generationRequestId']
        before = deepcopy(generation)
        assert client.get(status_url, headers=auth).json['status'] == 'generating'
        assert generation == before
        release.set()
        completed = first.result(timeout=3)
    generation['recommendation_snapshots'].clear()
    assert completed.json['status'] == 'planned'
    assert client.get(status_url, headers=auth).json['tripId'] == completed.json['tripId']
    assert send().json['reused'] is True  # Completed recovery needs no expired/deleted snapshot.
    assert len(generation['itineraries']) == 1 and calls == ['generate']
    monkeypatch.setattr(fr5, '_personalised_trip_id', lambda *args: completed.json['tripId'])
    generation['itineraries'][completed.json['tripId']]['travellerId'] = 'another-owner'
    assert client.get(status_url, headers=auth).status_code == 404


def test_future_trip_skips_unusable_forecast_and_records_stage_timings(monkeypatch):
    monkeypatch.setattr(fr5, 'geocode', lambda *args: pytest.fail('No forecast exists for 2030 yet'))
    assert fr5._forecast_for({'startDate': '2030-12-12'}, {}) == ({}, None)


def rich_catalog():
    return [{'destinationId': f'i-place-{i}', 'title': f'Verified Garden {i}',
             'address': 'Johor Bahru, Johor, Malaysia', 'city': 'Johor Bahru', 'state': 'Johor',
             'category': 'Nature', 'type': 'Botanical garden',
             'gps_coordinates': {'latitude': 1.46 + i * .0003, 'longitude': 103.75},
             'recommendedDurationMinutes': 90, 'estimatedCost': 0, 'unitPrice': 0,
             'pricingUnit': 'per_person', 'currency': 'MYR', 'costCategory': 'activity',
             'costProvenance': 'verified_free', 'openingHours': 'Daily 08:00-20:00'} for i in range(30)]


def test_three_deliberate_regenerations_keep_constraints_and_prior_drafts(offline_chat, monkeypatch):
    talk, database = offline_chat
    monkeypatch.setattr(fr11, '_planning_catalog', lambda *args: rich_catalog())
    first = talk('Plan a 2-day nature trip to Johor Bahru from 12 Dec 2030 to 13 Dec 2030 for 2 people with RM1200')
    sid = first['session']['id']
    plans = [first['item']['tripPlan']]
    for _ in range(3):
        result = talk('Regenerate itinerary', sid)
        assert 'different itinerary' in result['reply']
        plan = result['item']['tripPlan']
        assert plan['draftId'] not in {old['draftId'] for old in plans}
        ids = {row['destinationId'] for row in plan['activities']}
        assert ids.isdisjoint({row['destinationId'] for row in plans[-1]['activities']})
        for key in ('destinationArea', 'startDate', 'endDate', 'numberOfTravellers', 'budgetLimit', 'interests'):
            assert plan[key] == plans[0][key]
        assert plan['coverageStatus'] == 'complete'
        plans.append(deepcopy(plan))
    persisted = database['chat_sessions'][sid]
    assert [row['tripPlan']['draftId'] for row in persisted['messages']] == [row['draftId'] for row in plans]
    assert not database.get('itineraries')
    monkeypatch.setattr(fr11, '_planning_catalog', lambda *args: [])
    unchanged = talk('Regenerate itinerary', sid)
    assert 'previous draft is unchanged' in unchanged['reply']
    assert unchanged['item']['tripPlan']['draftId'] == plans[-1]['draftId']
