"""Combined chat/inbox recovery with synthetic storage; no live Firebase calls."""
from copy import deepcopy
from unittest.mock import Mock, patch

import pytest
from google.api_core.exceptions import ResourceExhausted

from modules.fr11_chatbot_travel_assistant import routes as chat
from modules import traveller_notifications as notifications
from test_location_chat_reliability import delivery
from test_chatbot_saved_preview import conversation

AUTH = {'Authorization': 'Bearer fixture'}


@pytest.mark.parametrize('method,path,body', [
    ('POST', '/api/fr11/chat', {'message': 'Recommend 3 nature places in Penang',
                              'clientRequestId': 'chat_outage_fixture_001'}),
    ('GET', '/api/fr11/sessions', None),
    ('POST', '/api/fr11/sessions', {'title': 'New travel chat'}),
    ('GET', '/api/fr11/sessions/owned-fixture', None),
    ('GET', '/api/fr11/chat-requests/chat_outage_fixture_001', None),
    ('GET', '/api/traveller/notifications', None),
])
def test_profile_exhaustion_stops_each_route_before_receipts_or_reconciliation(
        client, mock_traveller_auth, monkeypatch, caplog, method, path, body):
    blocked = Mock(side_effect=AssertionError('A rejected request must not reach business logic'))
    for name in ('_new_session', '_session_ref', '_sorted_sessions'):
        monkeypatch.setattr(chat, name, blocked)
    monkeypatch.setattr(chat.chat_delivery, 'run', blocked)
    monkeypatch.setattr(chat.chat_delivery, 'status', blocked)
    monkeypatch.setattr(notifications, 'reconcile', blocked)
    with patch('auth_utils.get_db') as db, patch('auth_utils.rate_limit_response') as limiter:
        document = db.return_value.collection.return_value.document.return_value
        document.get.side_effect = ResourceExhausted('private quota detail')
        response = client.open(path, method=method, headers=AUTH, json=body)
    assert response.status_code == 503
    assert response.json == {'ok': False, 'code': 'profile_storage_unavailable',
                             'error': 'TravelMate account storage is temporarily unavailable.'}
    assert response.headers['Cache-Control'] == 'no-store'
    document.get.assert_called_once_with()
    limiter.assert_not_called()
    blocked.assert_not_called()
    assert 'ResourceExhausted status=429' in caplog.text
    assert 'private quota detail' not in caplog.text + response.text


def test_nature_reply_new_chat_history_and_inbox_share_one_owned_flow(delivery, client, monkeypatch):
    records, writes, providers, _ = delivery
    catalogue = [{'destinationId': f'nature-fixture-{i}', 'title': f'Fixture nature stop {i}',
                  'category': 'Nature', 'destinationConcepts': ['nature'], 'state': 'Penang',
                  'city': 'George Town', 'address': 'George Town, Penang, Malaysia',
                  'gps_coordinates': {'latitude': 5.4141, 'longitude': 100.3288}}
                 for i in range(3)]
    monkeypatch.setattr(chat, '_planning_catalog', lambda *args, **kwargs: deepcopy(catalogue))
    for name in ('retrieveRecord', 'claimRecord', 'storeRecord', 'updateRecord'):
        monkeypatch.setattr(notifications, name, getattr(chat, name))
    monkeypatch.setattr(notifications, 'queue_notification', Mock())
    records['checkout_orders'] = {'paid-fixture': {
        'id': 'paid-fixture', 'travellerId': 'test_traveller_uid',
        'status': 'paid', 'paymentStatus': 'paid', 'createdAt': '2026-11-01T00:00:00Z'}}
    purchased = deepcopy(records['checkout_orders'])
    trips = deepcopy(records['itineraries'])
    payload = {'message': 'Recommend 3 nature places in Penang',
               'clientRequestId': 'chat_combined_fixture_001', 'guidedPlanning': True}
    sent = client.post('/api/fr11/chat', headers=AUTH, json=payload)
    assert sent.status_code == 200, sent.json
    assert len(sent.json['item']['placeSuggestions']) == 3
    sid, mid = sent.json['session']['id'], sent.json['item']['id']
    created = client.post('/api/fr11/sessions', headers=AUTH, json={'title': 'Next fixture chat'})
    assert created.status_code == 201 and created.json['session']['id'] != sid
    listed = client.get('/api/fr11/sessions', headers=AUTH)
    assert listed.status_code == 200 and len(listed.json['items']) == 2
    for selected in (sid, created.json['session']['id'], sid):
        opened = client.get('/api/fr11/sessions/' + selected, headers=AUTH)
        assert opened.status_code == 200 and opened.json['session']['id'] == selected
    before_chat = deepcopy({key: records[key] for key in ('chat_sessions', 'chat_messages', 'chat_requests')})
    receipt = client.get('/api/fr11/chat-requests/' + payload['clientRequestId'], headers=AUTH)
    assert receipt.status_code == 200 and receipt.json['status'] == 'completed'
    replay = client.post('/api/fr11/chat', headers=AUTH, json=payload)
    assert replay.status_code == 200 and replay.json['item']['id'] == mid
    for _ in range(2):
        inbox = client.get('/api/traveller/notifications', headers=AUTH)
        assert inbox.status_code == 200 and len(inbox.json['items']) == 1
        assert inbox.json['unreadCount'] == 1
    assert {key: records[key] for key in before_chat} == before_chat
    assert len(records['chat_sessions'][sid]['messages']) == len(records['chat_messages']) == 1
    assert records['checkout_orders'] == purchased and records['itineraries'] == trips
    assert not providers and 'itineraries' not in writes
