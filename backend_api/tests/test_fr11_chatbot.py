import pytest
from unittest.mock import patch

def test_fr11_chat_and_planning(client, mock_traveller_auth):
    with patch('modules.fr11_chatbot_travel_assistant.routes.retrieveRecord') as mock_retrieve, \
         patch('modules.fr11_chatbot_travel_assistant.routes.storeRecord') as mock_store, \
         patch('modules.fr11_chatbot_travel_assistant.routes.updateRecord') as mock_update:
        
        mock_retrieve.return_value = []
        mock_store.side_effect = lambda coll, data: {'id': f'mock_{coll}_id', **data}
        mock_update.side_effect = lambda coll, doc_id, data: {'id': doc_id, **data}

        res = client.post(
            '/api/fr11/chat',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'message': 'Plan a 3-day Penang trip'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert 'reply' in data
        assert 'tripPlan' in data['item']
        plan = data['item']['tripPlan']
        assert plan['destinationArea'] == 'Penang'
        assert len(plan['activities']) > 0

def test_fr11_save_plan(client, mock_traveller_auth):
    sample_plan = {
        'title': '3-Day Penang Heritage Trip',
        'destinationArea': 'Penang',
        'startDate': '2026-09-01',
        'endDate': '2026-09-03',
        'budgetLimit': 1200.0,
        'activities': [
            {
                'activityName': 'George Town Heritage Walk',
                'destinationId': 'local_george_town',
                'estimatedCost': 30.0,
                'dayNo': 1,
                'timeSlot': 'Morning',
            }
        ]
    }
    with patch('modules.fr11_chatbot_travel_assistant.routes.storeRecord') as mock_store:
        mock_store.side_effect = lambda coll, data: {'id': 'itin_from_chat_1', **data}

        res = client.post(
            '/api/fr11/save-plan',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'plan': sample_plan}
        )
        assert res.status_code == 201
        data = res.get_json()
        assert data['ok'] is True
        assert data['itinerary']['title'] == '3-Day Penang Heritage Trip'
        assert data['itinerary']['travellerId'] == 'test_traveller_uid'
        assert len(data['itinerary']['activities']) == 1
        assert 'budget' in data

def test_fr11_save_plan_missing_payload(client, mock_traveller_auth):
    res = client.post(
        '/api/fr11/save-plan',
        headers={'Authorization': 'Bearer valid_test_token'},
        json={}
    )
    assert res.status_code == 400
    assert 'No trip plan is available to save' in res.get_json()['error']

def test_gemini_service_fallback(monkeypatch):
    from services import gemini_service
    monkeypatch.setenv('FALLBACK_MODE', 'true')
    monkeypatch.setenv('GEMINI_API_KEY', 'fake_key')
    
    with patch('services.gemini_service._generate', side_effect=RuntimeError('API quota exceeded')):
        reply = gemini_service.generateChatbotResponse('what is the budget advice?')
        assert 'TravelMate budget' in reply or 'budget' in reply.lower()


def test_saved_trip_adjustment_selects_owned_trip_and_requires_confirmation(client, mock_traveller_auth):
    from copy import deepcopy
    from modules.fr11_chatbot_travel_assistant import routes

    uid = 'test_traveller_uid'
    a = {'id': 'a', 'travellerId': uid, 'title': 'First trip', 'destinationArea': 'Penang',
         'startDate': '2027-02-10', 'endDate': '2027-02-12', 'budgetLimit': 1000, 'activities': [],
         'notes': 'Keep this content'}
    b = {**a, 'id': 'b', 'title': 'Second trip'}
    records = {'itineraries': {'a': deepcopy(a), 'b': deepcopy(b)}, 'chat_sessions': {}}
    headers = {'Authorization': 'Bearer valid_test_token'}

    def read(collection, id=None, **kwargs):
        rows = records.get(collection, {})
        return deepcopy(rows.get(id) if id else list(rows.values()))

    def store(collection, data):
        rows = records.setdefault(collection, {})
        id = f'{collection}_{len(rows) + 1}'
        rows[id] = {'id': id, **deepcopy(data)}
        return deepcopy(rows[id])

    def update(collection, id, data, expected=None):
        row = records[collection][id]
        assert expected is None or row == expected
        if collection == 'chat_sessions' and set(data) == {'planningState'}:
            row['planningState'].update(deepcopy(data['planningState']))
        else:
            row.update(deepcopy(data))
        return deepcopy(row)

    def talk(message, session_id=None):
        res = client.post('/api/fr11/chat', headers=headers, json={'message': message,
                          'sessionId': session_id, 'guidedPlanning': True})
        assert res.status_code == 200, res.get_json()
        return res.get_json()

    with patch.object(routes, 'retrieveRecord', side_effect=read), patch.object(routes, 'storeRecord', side_effect=store), patch.object(routes, 'updateRecord', side_effect=update):
        first = talk('Adjust my itinerary')
        sid = first['session']['id']
        assert first['item']['suggestedReplies'] == ['Adjust trip 1', 'Adjust trip 2']
        assert 'Second trip' in talk('Adjust trip 2', sid)['reply']
        assert 'MYR' in talk('Can make it cheaper?', sid)['reply']
        preview = talk('700', sid)['item']['tripPlan']
        assert preview['adjustmentTripId'] == 'b'
        assert preview['budgetLimit'] == 700
        assert records['itineraries']['b'] == b
        attempt = {'sessionId': sid, 'plan': preview}
        assert client.post('/api/fr11/save-plan', headers=headers, json=attempt).status_code == 400
        attempt['confirmed'] = True
        result = client.post('/api/fr11/save-plan', headers=headers, json=attempt)
        assert result.status_code == 200 and result.json['id'] == 'b'
        assert records['itineraries']['a'] == a
        assert records['itineraries']['b']['notes'] == b['notes']
        assert records['itineraries']['b']['startDate'] == b['startDate']
        assert records['itineraries']['b']['budgetLimit'] == 700
        repeat = client.post('/api/fr11/save-plan', headers=headers, json=attempt)
        assert repeat.status_code == 200 and repeat.json['alreadySaved']


def test_natural_language_preserves_the_travellers_intent():
    from modules.fr11_chatbot_travel_assistant.nlp_extractor import classify_detailed_intent, extract_interests
    from services.recommendation_taxonomy import preference_concepts

    assert 'Photography' in extract_interests('I like taking photos.')
    assert 'Family' in extract_interests('I want something suitable for children.')
    assert 'Culture' in extract_interests('I prefer historical places.')
    assert preference_concepts(['I like taking photos', 'somewhere peaceful', 'suitable for children',
                                'I do not like shopping']) == {'photography', 'leisure', 'family'}
    assert classify_detailed_intent('I want somewhere nice for couple') == 'DESTINATION_RECOMMENDATION'
    assert classify_detailed_intent('Vacation on RM1,500 budget') == 'ITINERARY_PLANNING'
