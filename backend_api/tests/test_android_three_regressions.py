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
        row = db[(collection, identity)]
        if collection == 'chat_sessions' and set(data) == {'planningState'}:
            row['planningState'].setdefault('savedPlans', {}).update(data['planningState']['savedPlans'])
        else:
            row.update(deepcopy(data))
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


def test_plan_a_trip_short_replies_complete_without_gemini(client, mock_traveller_auth, memory, monkeypatch):
    memory.pop(('travel_preferences', 'test_traveller_uid'))

    def unavailable(*args, **kwargs):
        pytest.fail('Guided questions and itinerary creation must not depend on Gemini.')

    monkeypatch.setattr(routes, 'generateChatbotResponse', unavailable)
    monkeypatch.setattr(routes, 'generateFollowUpResponse', unavailable)
    session = None
    for message, question in [('Plan a trip', 'destinationArea'), ('Penang', 'startDate'),
                              ('12 Dec until 16 Dec', 'travellerCount'), ('2', 'budgetLimit'),
                              ('700', 'interests')]:
        result = send(client, message, session)
        session = result['session']
        assert session['planningState']['guidedQuestion'] == question
        assert session['planningState']['planningGoal'] == 'itinerary'
        assert 'tripPlan' not in result['item']
        if question == 'travellerCount':
            assert '5 calendar days, 4 nights' in result['reply']
    result = send(client, 'A mix', session)
    plan = result['item']['tripPlan']
    assert plan['coverageStatus'] == 'complete'
    assert (plan['tripDays'], plan['nights'], plan['numberOfTravellers'], plan['budgetLimit']) == (5, 4, 2, 700)
    assert plan['interests'] == ['Food', 'Culture', 'Nature']
    revised = send(client, 'Actually make it 3 travellers.', result['session'])
    assert revised['item']['tripPlan']['numberOfTravellers'] == 3
    moved = send(client, 'Change it to Langkawi.', revised['session'])
    assert moved['session']['planningState']['destinationArea'] == 'Langkawi'
    assert moved['session']['planningState']['budgetLimit'] == 700
    assert moved['session']['planningState']['startDate'] == '2026-12-12'
    assert not any(key[0] == 'itineraries' for key in memory)


def test_explicit_upgrade_of_activity_suggestions_preserves_destination(client, mock_traveller_auth, memory):
    initial = send(client, 'Things to do in Penang for two days with food')
    assert initial['item']['placeSuggestions'] and 'tripPlan' not in initial['item']
    upgraded = send(client, 'Make this into a complete itinerary.', initial['session'])
    state = upgraded['session']['planningState']
    assert state['destinationArea'] == 'Penang'
    assert state['planningGoal'] == 'itinerary'
    assert state['guidedQuestion'] == 'startDate'


def test_activity_quick_prompt_and_short_replies_are_grounded(client, mock_traveller_auth, memory, monkeypatch):
    memory.pop(('travel_preferences', 'test_traveller_uid'))
    def unexpected(*args, **kwargs):
        pytest.fail('Guided activity planning must use the catalogue, not generated factual claims.')
    monkeypatch.setattr(routes, 'generateChatbotResponse', unexpected)
    monkeypatch.setattr(routes, 'generateFollowUpResponse', unexpected)
    first = send(client, 'Plan things to do')
    assert first['reply'] == 'Sure! Where in Malaysia would you like to explore?'
    assert 'placeSuggestions' not in first['item'] and 'packages' not in first['item']
    session = first['session']
    for message, question in [('Penang', 'tripDays'), ('maybe', 'tripDays'), ('Two days', 'interests')]:
        response = send(client, message, session)
        session = response['session']
        assert session['planningState']['guidedQuestion'] == question
    result = send(client, 'Food and culture', session)
    assert result['session']['planningState']['interests'] == ['Food', 'Culture']
    assert 'tripPlan' not in result['item']
    assert all('penang' in str(row.get('state', '')).lower() for row in result['item']['placeSuggestions'])
    changed = send(client, 'Actually, change to Ipoh.', result['session'])
    state = changed['session']['planningState']
    assert state['destinationArea'] == 'Ipoh' and state['tripDays'] == 2
    assert state['interests'] == ['Food', 'Culture']
    assert 'Ipoh' in changed['reply'] and not changed['item'].get('placeSuggestions')
    monkeypatch.setenv('SERPAPI_KEY', 'synthetic-test-only')
    monkeypatch.setattr(routes, 'retrieveDestinationResults', lambda query, area: {
        'local_results': [
            {'place_id': 'ipoh-test', 'title': 'Synthetic Ipoh food stop', 'address': 'Ipoh, Perak, Malaysia',
             'state': 'Perak', 'category': 'Food', 'recommendedDurationMinutes': 45},
            {'place_id': 'wrong-city', 'title': 'Synthetic Taiping food stop', 'address': 'Taiping, Perak, Malaysia',
             'state': 'Perak', 'category': 'Food'},
        ] if area == 'Ipoh' else [],
    })
    ipoh = send(client, 'Things to do in Ipoh for one day with food', changed['session'])
    assert ipoh['session']['planningState']['tripDays'] == 1
    assert [row['place_id'] for row in ipoh['item']['placeSuggestions']] == ['ipoh-test']
    assert ipoh['item']['placeSuggestions'][0]['matchedInterests'] == ['Food and local cuisine']
    assert ipoh['item']['placeSuggestions'][0]['recommendedDurationMinutes'] == 45
    shorter = send(client, 'I only have half a day.', ipoh['session'])
    assert 'half-day' in shorter['reply'] and len(shorter['item']['placeSuggestions']) <= 2
    assert 'tripPlan' not in shorter['item']
    assert 'tripDays' not in shorter['session']['planningState']
    reopened = client.get('/api/fr11/sessions/' + session['id'], headers=AUTH).json['session']
    assert reopened['planningState']['destinationArea'] == 'Ipoh'
    assert send(client, 'Plan things to do')['session']['planningState'].get('destinationArea') is None


def test_undated_and_dated_complete_requests_use_different_paths(client, mock_traveller_auth, memory):
    melaka = send(client, 'Plan a 2-day food trip to Melaka.')
    state = melaka['session']['planningState']
    assert state['destinationArea'] == 'Melaka City' and state['tripDays'] == 2
    assert state['interests'] == ['Food'] and state['guidedQuestion'] == 'startDate'
    assert 'tripPlan' not in melaka['item'] and melaka['item']['placeSuggestions']
    revised = send(client, 'No museums, more nature.', melaka['session'])
    assert revised['session']['planningState']['interests'] == ['Nature']
    assert revised['session']['planningState']['excludedActivityTypes'] == ['Museum']
    assert all('museum' not in row['title'].lower() for row in revised['item'].get('placeSuggestions', []))
    langkawi = send(client, 'Plan a relaxed 3-day Langkawi trip from 12 December to 14 December for two people, RM1,500 budget.')
    plan = langkawi['item']['tripPlan']
    assert (plan['destinationArea'], plan['startDate'], plan['endDate']) == ('Langkawi', '2026-12-12', '2026-12-14')
    assert (plan['numberOfTravellers'], plan['budgetLimit'], plan['travelPace']) == (2, 1500, 'relaxed')
    assert all('langkawi' in a['address'].lower() for a in plan['activities'])
    changed = send(client, 'Change our budget to RM900 and make the pace busy', langkawi['session'])
    newer = changed['item']['tripPlan']
    assert newer['budgetLimit'] == 900 and newer['travelPace'] == 'active'
    assert newer['draftId'] != plan['draftId']


def test_single_date_waits_for_duration_and_allows_optional_skips(client, mock_traveller_auth, memory):
    first = send(client, 'Plan Langkawi starting 12 December 2026')
    state = first['session']['planningState']
    assert state['startDate'] == '2026-12-12' and 'endDate' not in state and 'tripDays' not in state
    assert state['guidedQuestion'] == 'tripDays'
    duration = send(client, 'Two days', first['session'])
    assert duration['session']['planningState']['guidedQuestion'] == 'budgetLimit'
    skipped_budget = send(client, 'Skip', duration['session'])
    ready = send(client, 'Skip', skipped_budget['session'])
    plan = ready['item']['tripPlan']
    assert (plan['startDate'], plan['endDate'], plan['tripDays']) == ('2026-12-12', '2026-12-13', 2)
    assert len(plan['planningLimitations']) == 2


@pytest.mark.skipif(not os.getenv('TRAVELMATE_FR11_TEST_EMULATOR'), reason='requires disposable Firestore emulator')
def test_firestore_chat_turn_replaces_removed_draft_fields(monkeypatch):
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import firestore
    from sequence_contract import firebase_firestore

    host = os.environ['TRAVELMATE_FR11_TEST_EMULATOR']
    assert host.startswith('127.0.0.1:')
    monkeypatch.setenv('FIRESTORE_EMULATOR_HOST', host)
    db = firestore.Client(project='demo-travelmate-chat-state', credentials=AnonymousCredentials())
    monkeypatch.setattr(firebase_firestore, 'get_db', lambda: db)
    ref = db.collection('chat_sessions').document('half-day-test')
    ref.create({'travellerId': 'synthetic', 'messages': [], 'planningState': {
        'tripDays': 3, 'startDate': '2026-12-12', 'endDate': '2026-12-14',
        'activePlan': {'draftId': 'old-draft'}, 'guidedQuestion': 'startDate',
        'savedPlans': {'older': 'trip-one'},
    }})
    next_state = {'activityWindow': 'half_day', 'destinationArea': 'Ipoh',
                  'savedPlans': {'older': 'trip-one'}}
    updated = firebase_firestore.updateRecord('chat_sessions', ref.id, {
        'messages': [{'message': 'Half day'}], 'planningState': next_state,
    })
    assert updated['planningState'] == next_state
    firebase_firestore.updateRecord('chat_sessions', ref.id, {
        'planningState': {'savedPlans': {'confirmed': 'trip-two'}},
    })
    assert ref.get().to_dict()['planningState'] == {
        **next_state, 'savedPlans': {'older': 'trip-one', 'confirmed': 'trip-two'},
    }


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
    assert all(a['state'] == 'Johor' for a in plan['activities'])
    assert all(a['travelDistanceKm'] is None for a in plan['activities'] if a['travelTimeSource'] == 'estimated_default')
    assert not [key for key in memory if key[0] == 'itineraries']
    fixture = Path(__file__).resolve().parents[2]/'traveller_mobile/test/fixtures/fr11_guided_contract.json'
    if wording == '12 Dec until 16 Dec':
        previous = json.loads(fixture.read_text(encoding='utf-8'))['item']['tripPlan']
        assert (plan['destinationArea'], plan['startDate'], plan['endDate']) == (
            previous['destinationArea'], previous['startDate'], previous['endDate'])
        assert {a['destinationId'] for a in plan['activities']} <= {a['destinationId'] for a in previous['activities']}
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


def test_explanation_and_contextual_follow_up_preserve_pending_setup(client, mock_traveller_auth, memory, monkeypatch):
    initial = send(client, 'I want to travel to Langkawi')
    state = initial['session']['planningState']
    calls = []
    def answer(question, context, **kwargs):
        calls.append((question, context))
        return {'reply':'Brief travel explanation.', 'source':'gemini'}
    monkeypatch.setattr(routes, 'generateFollowUpResponse', answer)
    question = 'Explain why Ipoh is known for white coffee.'
    explanation = send(client, question, initial['session'])
    followup = send(client, 'What was my previous question?', explanation['session'])
    assert len(calls) == 2 and question in calls[-1][1]
    assert all(turn['source'] == 'gemini' and not {'tripPlan', 'placeSuggestions'} & turn['item'].keys() and
               turn['session']['planningState'] == state for turn in (explanation, followup))


def test_budget_advice_preserves_a_pending_itinerary(client, mock_traveller_auth, memory):
    initial = send(client, 'I want to travel to Langkawi')
    state = initial['session']['planningState']
    answer = send(client, 'How much budget should I prepare for a 3-day holiday in Melaka?', initial['session'])
    assert answer['session']['planningState'] == state
    assert answer['source'] == 'test'
    assert not {'tripPlan', 'placeSuggestions'} & answer['item'].keys()


def test_regenerate_uses_active_dates_and_does_not_create_trip(client, mock_traveller_auth, memory, monkeypatch):
    response = complete(client, monkeypatch)
    draft = response['item']['tripPlan']
    rebuilt = send(client, 'Regenerate itinerary', response['session'])
    assert rebuilt['source'] == 'travelmate-assistant'
    new_draft = rebuilt['item']['tripPlan']
    assert rebuilt['session']['planningState']['activePlan'] == new_draft
    assert all(new_draft[key] == draft[key] for key in ('startDate', 'endDate', 'destinationArea', 'budgetLimit'))
    assert not any(key[0] == 'itineraries' for key in memory)


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
    assert len(MALAYSIAN_AIRPORTS) == 36
    assert {'LKH', 'TGC'} <= MALAYSIAN_AIRPORTS
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


def test_cultural_template_preserves_duration_theme_and_context(client, mock_traveller_auth, memory):
    first = send(client, 'Plan a 3-day cultural trip')
    assert first['session']['planningState']['guidedQuestion'] == 'destinationArea'
    assert first['session']['planningState']['tripDays'] == 3
    second = send(client, 'Melaka', first['session'])
    assert second['session']['planningState']['guidedQuestion'] == 'startDate'
    assert second['session']['planningState']['destinationArea'] == 'Melaka City'
    dates = send(client, '12 Dec 2030', second['session'])
    assert dates['session']['planningState']['tripDays'] == 3
    budget = send(client, 'RM700 for two people', dates['session'])
    plan = budget['item']['tripPlan']
    assert plan['destinationArea'] == 'Melaka City'
    assert plan['tripDays'] == 3 and plan['budgetLimit'] == 700
    assert plan['numberOfTravellers'] == 2 and plan['interests'] == ['Culture']
    assert (plan['startDate'], plan['endDate']) == ('2030-12-12', '2030-12-14')
    assert plan['activities']
    assert not [key for key in memory if key[0] == 'itineraries']
