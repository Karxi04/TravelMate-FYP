"""Real Flask routes with isolated storage/provider doubles; no cloud operations."""
from copy import deepcopy
import pytest

from test_shared_destination_discovery import discovery_route
from test_chatbot_saved_preview import conversation
from services.malaysian_locality import resolve_destination_scope, destination_locations, validate_candidate
from modules.fr11_chatbot_travel_assistant import routes as chat

AUTH = {'Authorization': 'Bearer fixture'}


@pytest.mark.parametrize('area,key', [('Malaysia', 'my'), ('Penang, Malaysia', 'my:penang'),
    ('Pulau Pinang', 'my:penang'), ('George Town, Penang, Malaysia', 'my:penang:george_town'),
    ('Butterworth, Penang, Malaysia', 'my:penang:butterworth'),
    ('Bukit Bintang, Kuala Lumpur, Malaysia', 'my:kuala_lumpur:bukit_bintang')])
def test_scope_labels_and_aliases_resolve_without_broadening(area, key):
    assert resolve_destination_scope(area)['scopeKey'] == key


def test_catalogue_is_authenticated_and_needs_no_records_or_provider(discovery_route, client):
    records, calls, writes = discovery_route
    response = client.get('/api/fr4/locations', headers=AUTH)
    assert response.status_code == 200
    rows = response.json['locations']
    assert len({r['scopeKey'] for r in rows}) == len(rows)
    assert sum(r['kind'] == 'state' for r in rows) == 16
    assert {'Bukit Mertajam, Penang, Malaysia', 'Bukit Bintang, Kuala Lumpur, Malaysia'} <= {r['canonicalName'] for r in rows}
    assert not calls and not writes
    assert client.get('/api/fr4/locations').status_code == 401


def test_malaysia_and_penang_generate_and_reopen_correct_owned_scope(discovery_route, client):
    records, calls, _ = discovery_route
    results = {}
    for area in ('Malaysia', 'Penang, Malaysia'):
        response = client.post('/api/fr4/recommendations/generate', headers=AUTH,
                               json={'destinationArea': area, 'discoveryMode': 'relevant_v1'})
        assert response.status_code == 200, response.json
        data = response.json
        assert data['recommendations'] and data['snapshot']['searchStatus'] == 'matches'
        key = 'my' if area == 'Malaysia' else 'my:penang'
        assert data['snapshot']['canonicalDestinationScope']['scopeKey'] == key
        assert all(validate_candidate(row, resolve_destination_scope(area))[0] for row in data['recommendations'])
        results[area] = data['recommendationGenerationId']
        saved = client.get('/api/fr4/recommendations', headers=AUTH,
                           query_string={'generationId': results[area], 'destinationArea': area})
        assert saved.status_code == 200
    wrong = client.get('/api/fr4/recommendations', headers=AUTH, query_string={
        'generationId': results['Malaysia'], 'destinationArea': 'Penang, Malaysia'})
    assert wrong.status_code == 404
    assert client.get('/api/fr4/recommendations', headers=AUTH,
                      query_string={'destinationArea': 'unrecognised place'}).status_code == 400


def test_catalogue_selection_cannot_forge_state_or_promote_attraction_to_city(discovery_route, client):
    _, calls, writes = discovery_route
    response = client.post('/api/fr4/recommendations/generate', headers=AUTH, json={
        'destinationArea': 'Penang, Malaysia', 'destinationScopeKey': 'my:perak'})
    assert response.status_code == 400 and not calls and not writes
    assert not resolve_destination_scope('Kek Lok Si Temple')['resolved']
    assert not resolve_destination_scope('Penang Hill')['resolved']
    assert not resolve_destination_scope('Penang, Thailand')['resolved']


@pytest.mark.parametrize('area', ['Butterworth, Penang, Malaysia', 'Bukit Mertajam, Penang, Malaysia',
                                  'Bukit Bintang, Kuala Lumpur, Malaysia', 'Melaka, Malaysia'])
def test_locality_and_state_provider_scope_stays_specific(discovery_route, client, monkeypatch, area):
    from modules.fr04_hybrid_recommendation import routes
    scope = resolve_destination_scope(area)
    calls = []
    def provider(query, location, coordinates):
        calls.append((location, coordinates))
        return {'local_results': [
            {'place_id': 'local', 'title': 'Recorded museum', 'type_id': 'museum',
             'city': scope['city'], 'state': scope['state']},
            {'place_id': 'foreign-state', 'title': 'Unrelated museum', 'type_id': 'museum', 'state': 'Sarawak'},
        ]}
    monkeypatch.setattr(routes, 'retrieveDestinationResults', provider)
    response = client.post('/api/fr4/recommendations/generate', headers=AUTH, json={
        'destinationArea': area, 'destinationScopeKey': scope['scopeKey'], 'discoveryMode': 'relevant_v1'})
    assert response.status_code == 200, response.json
    assert [r['destinationId'] for r in response.json['recommendations']] == ['local']
    assert all(location == scope['canonicalName'] for location, _ in calls)
    assert all(coords == {'latitude': scope['latitude'], 'longitude': scope['longitude']} for _, coords in calls)


@pytest.fixture
def delivery(conversation, monkeypatch):
    records, writes, providers, talk = conversation
    def claim(collection, key, value):
        table = records.setdefault(collection, {})
        if key in table: return deepcopy(table[key]), False
        table[key] = {'id': key, **deepcopy(value)}
        writes.append(collection)
        return deepcopy(table[key]), True
    monkeypatch.setattr(chat, 'claimRecord', claim)
    monkeypatch.setattr(chat, 'interpretChatbotIntent', lambda *_: None)
    return conversation


def test_same_chat_id_replays_receipt_not_provider_or_new_session(delivery, client):
    records, writes, providers, _ = delivery
    payload = {'message': 'Explain Malaysian travel etiquette', 'clientRequestId': 'chat_test_request_001'}
    first = client.post('/api/fr11/chat', headers=AUTH, json=payload)
    assert first.status_code == 200, first.json
    before = len(writes), len(providers), len(records['chat_sessions'])
    replay = client.post('/api/fr11/chat', headers=AUTH, json=payload)
    assert replay.status_code == 200 and replay.json['item']['id'] == first.json['item']['id']
    assert (len(writes), len(providers), len(records['chat_sessions'])) == before
    receipt = client.get('/api/fr11/chat-requests/chat_test_request_001', headers=AUTH)
    assert receipt.status_code == 200 and receipt.json['status'] == 'completed'
    assert len(writes) == before[0]
    changed = client.post('/api/fr11/chat', headers=AUTH, json={**payload, 'message': 'Different question'})
    assert changed.status_code == 409 and len(providers) == before[1]


def test_duplicate_while_processing_is_blocked_before_provider(delivery, client, monkeypatch):
    records, _, _, _ = delivery
    payload = {'message': 'Explain Malaysian travel etiquette', 'clientRequestId': 'chat_test_request_002'}
    nested, attempts = [], []
    original = chat._chat_turn
    def turn(body):
        attempts.append(1)
        assert len(attempts) == 1
        with client.application.test_client() as second:
            response = second.post('/api/fr11/chat', headers=AUTH, json=payload)
            nested.append(response.status_code)
        return original(body)
    monkeypatch.setattr(chat, '_chat_turn', turn)
    response = client.post('/api/fr11/chat', headers=AUTH, json=payload)
    assert response.status_code == 200, response.json
    assert attempts == [1] and nested == [409]
    assert len(records['chat_messages']) == 1


def test_pending_receipt_and_cross_owner_session_do_not_write(delivery, client):
    records, writes, _, _ = delivery
    from modules.fr11_chatbot_travel_assistant.chat_delivery import request_key
    identity = 'chat_test_request_003'
    records['chat_requests'] = {request_key('test_traveller_uid', identity): {
        'travellerId': 'other_owner', 'sessionId': 'secret-session', 'state': 'pending'}}
    before = len(writes)
    result = client.get('/api/fr11/chat-requests/' + identity, headers=AUTH)
    assert result.status_code == 200 and result.json == {'ok': True, 'status': 'unknown'}
    records['chat_sessions']['foreign'] = {'travellerId': 'other_owner'}
    result = client.post('/api/fr11/chat', headers=AUTH, json={
        'message': 'Explain Malaysia', 'sessionId': 'foreign', 'clientRequestId': identity})
    assert result.status_code == 404 and len(writes) == before


def test_completed_session_is_receipt_even_if_acknowledgement_was_lost(delivery, client):
    records, writes, _, _ = delivery
    identity = 'chat_test_request_004'
    response = client.post('/api/fr11/chat', headers=AUTH, json={
        'message': 'Explain Malaysian travel etiquette', 'clientRequestId': identity})
    assert response.status_code == 200
    from modules.fr11_chatbot_travel_assistant.chat_delivery import request_key
    records['chat_requests'][request_key('test_traveller_uid', identity)]['state'] = 'pending'
    before = len(writes)
    result = client.get('/api/fr11/chat-requests/' + identity, headers=AUTH)
    assert result.json['status'] == 'completed' and result.json['item']['id'] == response.json['item']['id']
    assert len(writes) == before


def test_empty_provider_and_unavailable_provider_are_distinct(discovery_route, client, monkeypatch):
    from modules.fr04_hybrid_recommendation import routes
    records, _, _ = discovery_route
    records['destination_cache'] = {}
    monkeypatch.setenv('FALLBACK_MODE', 'false')
    monkeypatch.setattr(routes, 'retrieveDestinationResults', lambda *_: {'local_results': []})
    response = client.post('/api/fr4/recommendations/generate', headers=AUTH, json={
        'destinationArea': 'Penang, Malaysia', 'discoveryMode': 'relevant_v1'})
    assert response.status_code == 200, response.json
    assert response.json['recommendations'] == [] and response.json['snapshot']['searchStatus'] == 'no_candidates'
    def unavailable(*args): raise RuntimeError('Provider unavailable')
    monkeypatch.setattr(routes, 'retrieveDestinationResults', unavailable)
    failed = client.post('/api/fr4/recommendations/generate', headers=AUTH, json={
        'destinationArea': 'Penang, Malaysia', 'discoveryMode': 'relevant_v1'})
    assert failed.status_code == 502 and failed.json['code'] == 'destination_provider_unavailable'


def test_same_nonce_in_two_accounts_keeps_receipts_and_sessions_isolated(delivery, client, mock_traveller_auth):
    records, _, _, _ = delivery
    payload = {'message': 'Explain Malaysian travel etiquette', 'clientRequestId': 'chat_test_request_005'}
    first = client.post('/api/fr11/chat', headers=AUTH, json=payload)
    assert first.status_code == 200
    original = deepcopy(first.json['session'])
    mock_traveller_auth.return_value = {**mock_traveller_auth.return_value, 'uid': 'second_fixture_owner'}
    second = client.post('/api/fr11/chat', headers=AUTH, json=payload)
    assert second.status_code == 200, second.json
    assert second.json['session']['travellerId'] == 'second_fixture_owner'
    assert second.json['session']['id'] != original['id']
    assert records['chat_sessions'][original['id']] == original
    receipt = client.get('/api/fr11/chat-requests/' + payload['clientRequestId'], headers=AUTH)
    assert receipt.json['session']['id'] == second.json['session']['id']


def test_late_turn_cannot_overwrite_an_external_session_change(delivery, client, monkeypatch):
    records, _, _, _ = delivery
    first = client.post('/api/fr11/chat', headers=AUTH, json={
        'message': 'Explain Malaysian travel etiquette', 'clientRequestId': 'chat_test_request_006'}).json
    original_update = chat._update_chat_session
    external = []
    def changed(session, updates, expected, **options):
        records['chat_sessions'][session['id']]['planningState'] = {'externalChange': True}
        external.append(deepcopy(records['chat_sessions'][session['id']]))
        return original_update(session, updates, expected, **options)
    monkeypatch.setattr(chat, '_update_chat_session', changed)
    response = client.post('/api/fr11/chat', headers=AUTH, json={
        'message': 'Explain travel safety', 'sessionId': first['session']['id'], 'clientRequestId': 'chat_test_request_007'})
    assert response.status_code in (409, 503)
    assert records['chat_sessions'][first['session']['id']] == external[0]
    receipt = client.get('/api/fr11/chat-requests/chat_test_request_007', headers=AUTH)
    assert receipt.json['status'] != 'completed'


def test_chat_correlation_logs_timing_not_private_content(delivery, client, caplog):
    import logging
    message = 'Explain Malaysian travel etiquette'
    with caplog.at_level(logging.INFO):
        response = client.post('/api/fr11/chat', headers=AUTH, json={
            'message': message, 'clientRequestId': 'chat_test_request_008'})
    assert response.status_code == 200 and len(response.headers['X-Request-ID']) == 16
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith('chat_http_')]
    assert len(lines) == 2 and 'elapsed_ms=' in lines[-1]
    assert all(message not in line and 'test_traveller_uid' not in line for line in lines)
