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
