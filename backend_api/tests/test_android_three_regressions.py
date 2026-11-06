"""Real FR11 route conversations; only auth/storage/provider boundaries are replaced."""
import json
import os
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest

from modules.fr11_chatbot_travel_assistant import routes, travel_dates, guided_planning
from modules.fr11_chatbot_travel_assistant.nlp_extractor import extract_duration
from services.flight_airports import MALAYSIAN_AIRPORT_CATALOG, MALAYSIAN_AIRPORTS, AIRPORT_CATALOG

AUTH = {'Authorization': 'Bearer valid_test_token'}


@pytest.fixture
def memory(monkeypatch):
    db = {('travel_preferences', 'test_traveller_uid'): {'interests': ['Culture'], 'travelPace': 'relaxed', 'travelPersonality': 'Explorer'}}
    def read(collection, identity=None, filters=None, limit=None):
        if identity:
            return deepcopy(db.get((collection, str(identity))))
        result = [dict(value, id=key) for (coll, key), value in db.items() if coll == collection]
        for field, operator, value in filters or []:
            assert operator == '=='
            result = [item for item in result if item.get(field) == value]
        return deepcopy(result[:limit] if limit else result)
    def store(collection, data, documentId=None, **kwargs):
        identity = documentId or data.get('id') or f'{collection}_{len(db)}'
        db[(collection, identity)] = deepcopy(dict(data, id=identity))
        return deepcopy(db[(collection, identity)])
    def update(collection, identity, data, **kwargs):
        db[(collection, identity)].update(deepcopy(data))
        return read(collection, identity)
    def claim(collection, identity, data):
        existing = read(collection, identity)
        return (existing, False) if existing else (store(collection, data, identity), True)
    monkeypatch.setattr(routes, 'retrieveRecord', read)
    monkeypatch.setattr(routes, 'storeRecord', store)
    monkeypatch.setattr(routes, 'updateRecord', update)
    monkeypatch.setattr(routes, 'claimRecord', claim)
    monkeypatch.setattr(travel_dates, 'malaysian_today', lambda: date(2026, 11, 5))
    monkeypatch.setattr(guided_planning, 'malaysian_today', lambda: date(2026, 11, 5))
    monkeypatch.setattr(routes, 'generateFollowUpResponse', lambda *a, **k: {'reply': 'Travel guidance.', 'source': 'test'})
    monkeypatch.setattr(routes, 'generateChatbotResponse', lambda *a, **k: {'reply': 'Travel guidance.', 'source': 'test'})
    return db


def send(client, message, session=None):
    response = client.post('/api/fr11/chat', headers=AUTH, json={'message': message, 'guidedPlanning': True, **({'sessionId': session['id']} if session else {})})
    assert response.status_code == 200, response.json
    return response.json


def johor_provider(monkeypatch):
    # Synthetic provider records, never production catalogue entries.
    records = [{'place_id': f'johor_test_{i}', 'title': f'Johor test attraction {i}', 'address': 'Johor Bahru, Johor, Malaysia',
                'state': 'Johor', 'city': 'Johor Bahru', 'category': 'Culture', 'description': 'Provider-returned test detail.'} for i in range(15)]
    records.append({'place_id': 'wrong_state', 'title': 'KL test attraction', 'state': 'Kuala Lumpur', 'address': 'Kuala Lumpur, Malaysia'})
    monkeypatch.setenv('SERPAPI_KEY', 'synthetic-test-only')
    monkeypatch.setattr(routes, 'retrieveDestinationResults', lambda *a: {'local_results': records})


@pytest.mark.parametrize('wording', ['12 Dec until 16 Dec', '12 Dec to 16 Dec', '12 December until 16 December',
    '12/12/2026 to 16/12/2026', '2026-12-12 to 2026-12-16', '12 to 16 December', '12–16 Dec', 'from 12 Dec to 16 Dec', '12 Dec until 16 Dec, 2 days'])
def test_full_guided_date_conversation(client, mock_traveller_auth, memory, monkeypatch, wording):
    johor_provider(monkeypatch)
    first = send(client, 'I want to travel to Johor')
    assert first['session']['planningState']['guidedQuestion'] == 'tripDays'
    dates = send(client, wording, first['session'])
    state = dates['session']['planningState']
    assert (state['startDate'], state['endDate'], state['tripDays']) == ('2026-12-12', '2026-12-16', 5)
    assert state['guidedQuestion'] == 'budgetLimit'
    assert '4 nights' in dates['reply']
    budget = send(client, 'RM1000', dates['session'])
    assert budget['session']['planningState']['guidedQuestion'] == 'travellerCount'
    final = send(client, '2 travellers', budget['session'])
    plan = final['item']['tripPlan']
    assert plan['coverageStatus'] == 'complete'
    assert plan['startDate'] == '2026-12-12' and plan['endDate'] == '2026-12-16'
    assert plan['nights'] == 4 and plan['tripDays'] == 5
    assert plan['budgetLimit'] == 1000 and plan['numberOfTravellers'] == 2
    assert plan['travelPersonality'] == 'Explorer' and plan['interests'] == ['Culture']
    assert {a['dayNo'] for a in plan['activities']} == {1, 2, 3, 4, 5}
    assert len({a['destinationId'] for a in plan['activities']}) == len(plan['activities'])
    assert all(a['state'] == 'Johor' and a['travelBufferMinutes'] == 0 for a in plan['activities'])
    assert not [key for key in memory if key[0] == 'itineraries']
    fixture = Path(__file__).resolve().parents[2]/'traveller_mobile/test/fixtures/fr11_guided_contract.json'
    if wording == '12 Dec until 16 Dec':
        assert json.loads(fixture.read_text(encoding='utf-8'))['item']['tripPlan'] == plan
    if wording == '12 Dec until 16 Dec' and os.getenv('TRAVELMATE_FR11_CONTRACT_OUTPUT'):
        Path(os.environ['TRAVELMATE_FR11_CONTRACT_OUTPUT']).write_text(json.dumps(final, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')


def complete(client, monkeypatch):
    johor_provider(monkeypatch)
    return send(client, 'Plan Johor 12 Dec until 16 Dec for 2 travellers, RM1000')


def test_followups_save_reopen_duplicate_and_correction(client, mock_traveller_auth, memory, monkeypatch):
    response = complete(client, monkeypatch)
    original = response['item']['tripPlan']
    for wording in ['where is my trip?', 'show my plan', 'show the itinerary', 'where the trips', 'can I see my trip?']:
        response = send(client, wording, response['session'])
        assert response['item']['tripPlan'] == original
    payload = {'sessionId': response['session']['id'], 'plan': original, 'confirmed': True}
    assert client.post('/api/fr11/save-plan', headers=AUTH, json={**payload, 'confirmed': False}).status_code == 400
    saved = client.post('/api/fr11/save-plan', headers=AUTH, json=payload)
    assert saved.status_code == 201
    again = client.post('/api/fr11/save-plan', headers=AUTH, json=payload)
    assert again.status_code == 200 and again.json['id'] == saved.json['id']
    assert len([key for key in memory if key[0] == 'itineraries']) == 1
    # FR5 uses the same persistence boundary; patch its read for the reopen assertion.
    from modules.fr05_smart_itinerary_budget_planner import routes as trip_routes
    monkeypatch.setattr(trip_routes, 'retrieveRecord', lambda collection, identity=None, **k: deepcopy(memory.get((collection, identity))))
    trip = client.get('/api/fr5/itineraries/'+saved.json['id'], headers=AUTH)
    assert trip.status_code == 200
    assert trip.json['itinerary']['startDate'] == '2026-12-12'
    assert trip.json['itinerary']['endDate'] == '2026-12-16'
    assert len(trip.json['itinerary']['activities']) == len(original['activities'])
    shown = send(client, 'where the trips', response['session'])
    assert shown['item']['savedTripId'] == saved.json['id']
    corrected = send(client, 'Actually change to 14 Dec until 18 Dec', shown['session'])
    assert corrected['item']['tripPlan']['startDate'] == '2026-12-14'
    assert corrected['item']['tripPlan']['draftId'] != original['draftId']
    assert client.post('/api/fr11/save-plan', headers=AUTH, json=payload).status_code == 409


def test_invalid_dates_block_old_draft_and_unrelated_followup(client, mock_traveller_auth, memory, monkeypatch):
    response = complete(client, monkeypatch)
    response = send(client, '31 Feb 2030 to 3 Mar 2030', response['session'])
    assert 'tripPlan' not in response['item']
    assert 'activePlan' not in response['session']['planningState']
    response = send(client, 'RM2000', response['session'])
    assert 'tripPlan' not in response['item'] and 'invalid' in response['reply'].lower()


@pytest.mark.parametrize('question', ['What is the weather?', 'What is the weather for my trip?'])
def test_weather_question_keeps_draft_without_restarting_planning(client, mock_traveller_auth, memory, monkeypatch, question):
    response = complete(client, monkeypatch)
    plan = response['item']['tripPlan']
    answer = send(client, question, response['session'])
    assert 'tripPlan' not in answer['item']
    assert answer['session']['planningState']['activePlan'] == plan
    assert send(client, 'show my plan', answer['session'])['item']['tripPlan'] == plan


def test_foreign_chat_cannot_save_or_expose_another_travellers_draft(client, mock_traveller_auth, memory, monkeypatch):
    response = complete(client, monkeypatch)
    session_id = response['session']['id']
    memory[('chat_sessions', session_id)]['travellerId'] = 'another-traveller'
    result = client.post('/api/fr11/save-plan', headers=AUTH, json={'sessionId': session_id, 'plan': response['item']['tripPlan'], 'confirmed': True})
    assert result.status_code == 404
    assert not [key for key in memory if key[0] == 'itineraries']


def test_failed_persistence_does_not_mark_draft_saved(client, mock_traveller_auth, memory, monkeypatch):
    response = complete(client, monkeypatch)
    def fail(*args, **kwargs):
        raise RuntimeError('Synthetic storage failure')
    monkeypatch.setattr(routes, 'claimRecord', fail)
    with pytest.raises(RuntimeError, match='Synthetic storage failure'):
        client.post('/api/fr11/save-plan', headers=AUTH, json={'sessionId': response['session']['id'], 'plan': response['item']['tripPlan'], 'confirmed': True})
    assert not memory[('chat_sessions', response['session']['id'])]['planningState'].get('savedPlans')
    assert not [key for key in memory if key[0] == 'itineraries']


def test_coverage_gap_never_announces_a_generated_draft(client, mock_traveller_auth, memory):
    result = send(client, 'Plan Johor 12 Dec until 16 Dec for 2 travellers, RM1000')
    assert 'tripPlan' not in result['item']
    assert 'not have enough verified' in result['reply']
    assert not [key for key in memory if key[0] == 'itineraries']


@pytest.mark.parametrize('duration', ['5 days', '4 nights'])
def test_duration_alone_does_not_invent_selected_dates(client, mock_traveller_auth, memory, duration):
    response = send(client, 'Plan Johor '+duration)
    state = response['session']['planningState']
    assert state['tripDays'] == 5 and state['guidedQuestion'] == 'startDate'
    assert 'startDate' not in state and 'tripPlan' not in response['item']
    assert extract_duration(duration) == 5


def test_malaysia_only_selection_parity():
    assert len(MALAYSIAN_AIRPORTS) == 34
    required = set('KUL SZB PEN LGK JHB BKI KCH KBR TGG KUA IPH AOR MYY SBW BTU TWU SDK LBU'.split())
    assert required <= MALAYSIAN_AIRPORTS
    assert all(row['country'] == 'MY' and row['state'] for row in MALAYSIAN_AIRPORT_CATALOG.values())
    assert {'LHR', 'NRT', 'JFK'}.isdisjoint(MALAYSIAN_AIRPORTS)
    assert 'LHR' in AIRPORT_CATALOG  # Shared worldwide identities preserved.
    dart = Path(__file__).resolve().parents[2]/'traveller_mobile/lib/modules/fr07_flight_search/flight_airport_catalog.dart'
    import re
    labels = {json.loads(k): json.loads(v) for k,v in re.findall(r'^  ("[A-Z]{3}"): (".*"),$', dart.read_text(encoding='utf-8').split('const Map<String, String> flightAirportAliases')[0], re.M)}
    assert set(labels) == MALAYSIAN_AIRPORTS
    assert all(MALAYSIAN_AIRPORT_CATALOG[code]['state'] in value for code,value in labels.items())


@pytest.mark.parametrize('code', ['LHR', 'NRT', 'JFK', 'SIN', 'ZZZ'])
def test_international_and_unknown_routes_rejected_at_api_boundary(client, mock_traveller_auth, code, monkeypatch):
    monkeypatch.setattr(routes, 'retrieveDestinationResults', lambda *a: pytest.fail('Not a destination lookup'))
    response = client.get('/api/fr7/flights/search', headers=AUTH, query_string={'departure_id': 'KUL', 'arrival_id': code, 'outbound_date': '2030-12-12'})
    assert response.status_code == 400 and 'Malaysian' in response.json['error']
