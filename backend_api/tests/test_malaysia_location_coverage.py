"""Sourced Malaysia location resolution and exact multi-turn T07 regression."""
from copy import deepcopy
from unittest.mock import Mock
import pytest

from test_chatbot_saved_preview import conversation
from test_location_chat_reliability import delivery
from test_shared_destination_discovery import place
from test_shared_destination_discovery import discovery_route
from modules.fr11_chatbot_travel_assistant import routes as chat
from services import malaysia_locations as catalogue
from services.malaysian_locality import resolve_destination_scope, resolve_area_query, location_scope, destination_locations, validate_candidate, STATE_ALIASES
from services.malaysia_boundary import coordinate_state

AUTH = {'Authorization': 'Bearer fixture'}

SAMPLES = {
    'Penang': ['George Town', 'Butterworth', 'Bukit Mertajam', 'Alma', 'Machang Bubok', 'Batu Kawan',
               'Seberang Jaya', 'Kepala Batas', 'Nibong Tebal', 'Balik Pulau', 'Bayan Lepas', 'Batu Ferringhi'],
    'Kedah': ['Kulim', 'Sungai Petani', 'Alor Setar', 'Langkawi', 'Jitra', 'Baling', 'Sik', 'Yan', 'Bandar Baharu'],
    'Perak': ['Ipoh', 'Taiping', 'Kampar', 'Batu Gajah', 'Kuala Kangsar', 'Teluk Intan', 'Lumut', 'Pangkor Island'],
    'Kuala Lumpur': ['Bukit Bintang'],
    'Selangor': ['Petaling Jaya', 'Shah Alam', 'Subang Jaya', 'Klang', 'Kajang', 'Ampang', 'Sepang', 'Kuala Selangor'],
    'Johor': ['Johor Bahru', 'Batu Pahat'], 'Melaka': ['Melaka City'], 'Negeri Sembilan': ['Seremban'],
    'Pahang': ['Kuantan', 'Cameron Highlands'], 'Kelantan': ['Kota Bharu'], 'Terengganu': ['Kuala Terengganu'],
    'Perlis': ['Kangar'], 'Sabah': ['Kota Kinabalu', 'Sandakan'], 'Sarawak': ['Kuching', 'Miri'],
    'Putrajaya': ['Putrajaya'], 'Labuan': ['Labuan'],
}


@pytest.mark.parametrize('name,state', [(name, state) for state, names in SAMPLES.items() for name in names])
def test_sourced_example_resolves_to_its_correct_state(name, state):
    label = f'{name}, {state}, Malaysia' if name != state else f'{state}, Malaysia'
    scope = resolve_destination_scope(label)
    assert scope['resolved'] and scope['country'] == 'Malaysia' and scope['state'] == state


def test_every_included_point_is_in_its_sourced_state_and_all_territories_exist():
    data = catalogue.dataset()
    assert set(data['counts']['byState']) == set(STATE_ALIASES)
    assert len(data['places']) > 20_000 and len({r['id'] for r in data['places']}) == len(data['places'])
    assert len(data['archiveSha256']) == 64 and data['license'].endswith('/by/4.0/')
    assert all(coordinate_state(r['latitude'], r['longitude']) == r['state'] for r in data['places'])
    instant = destination_locations()
    assert len({row['scopeKey'] for row in instant}) == len(instant)
    assert sum(row['kind'] == 'state' for row in instant) == 16
    assert {'Alma, Penang, Malaysia', 'Machang Bubok, Penang, Malaysia', 'Kulim, Kedah, Malaysia'} <= {r['canonicalName'] for r in instant}


def test_aliases_prefixes_confident_typo_and_ambiguous_names():
    assert resolve_area_query('georgetwon')['city'] == 'George Town'
    assert resolve_area_query('Macang Bubuk, Penang')['city'] == 'Machang Bubok'
    for query in ('bukit', 'bukit mer', 'sungai', 'kota'):
        found = catalogue.search(query)
        assert found and len({r['id'] for r in found}) == len(found)
    assert len(catalogue.exact('Kampung Baru')) > 1
    ambiguous = resolve_area_query('Kampung Baru')
    assert not ambiguous['resolved'] and len(ambiguous['clarificationChoices']) > 1
    assert not resolve_destination_scope('Kulim, Thailand')['resolved']
    assert not resolve_destination_scope('Kek Lok Si Temple')['resolved']


@pytest.mark.parametrize('bad', [
    {'country_code': 'SG'}, {'admin1': 'Penang'}, {'latitude': float('nan')},
    {'longitude': 999}, {'latitude': True}, {'id': True}, {'id': -1},
    {'name': {'invalid': 'object'}}, {'feature_code': 'MUS'}, {'id': 2**31},
    {'id': 1.5}, {'name': '   '}, {'population': 'unknown'}, {'admin2': {'invalid': 'object'}},
])
def test_remote_lookup_rejects_invalid_or_foreign_metadata(bad):
    point = catalogue.by_id('1734393')
    item = {'id': 999991001, 'name': 'Isolated location fixture', 'country_code': 'MY', 'admin1': 'Kedah',
            'latitude': point['latitude'], 'longitude': point['longitude'], 'feature_code': 'PPL', **bad}
    assert catalogue.verified_provider_row(item) is None


def test_missing_fast_list_entry_uses_full_local_index_without_geocoder(client, mock_traveller_auth, monkeypatch):
    row = next(r for r in catalogue.dataset()['places'] if not r['fast'] and len(catalogue.exact(r['name'])) == 1)
    remote = Mock(side_effect=AssertionError('Known extended entry must not call a provider'))
    monkeypatch.setattr(catalogue, 'online_search', remote)
    response = client.get('/api/fr4/locations/search', headers=AUTH, query_string={'q': row['name'], 'remote': 'true'})
    assert response.status_code == 200 and any(r['locationId'] == f"geonames:{row['id']}" for r in response.json['locations'])
    remote.assert_not_called()


def test_explicit_missing_location_lookup_is_bounded_and_does_not_persist(discovery_route, client, monkeypatch):
    from services import open_meteo_service
    _, _, writes = discovery_route
    point = catalogue.by_id('1734393')
    remote = Mock(return_value=[{'id': 999991002, 'name': 'Isolated remote fixture', 'country_code': 'MY',
        'admin1': 'Kedah', 'latitude': point['latitude'], 'longitude': point['longitude'], 'feature_code': 'PPL'}])
    monkeypatch.setattr(open_meteo_service, 'geocode', remote)
    first = client.get('/api/fr4/locations/search', headers=AUTH, query_string={'q': 'Isolated remote fixture'})
    assert first.status_code == 200 and not first.json['locations']
    remote.assert_not_called()
    response = client.get('/api/fr4/locations/search', headers=AUTH,
                          query_string={'q': 'Isolated remote fixture', 'remote': 'true'})
    assert response.status_code == 200 and response.json['locations'][0]['state'] == 'Kedah'
    remote.assert_called_once_with('Isolated remote fixture', timeout=8, country_code='MY', count=10)
    assert not writes
    with catalogue._remote_lock:
        catalogue._remote.pop('999991002', None)


def test_kulim_generation_is_strict_and_saved_read_never_resolves_again(discovery_route, client, monkeypatch):
    from modules.fr04_hybrid_recommendation import routes
    point = catalogue.by_id('1734393')
    calls = []
    def provider(query, area, coordinates):
        calls.append((area, coordinates))
        return {'local_results': [
            place('kulim-fixture', city='Kulim', state='Kedah', type_id='museum',
                  gps_coordinates={'latitude': point['latitude'], 'longitude': point['longitude']}),
            place('outside-fixture', city='Sungai Petani', state='Kedah', type_id='museum',
                  gps_coordinates={'latitude': 5.647, 'longitude': 100.4877})]}
    monkeypatch.setattr(routes, 'retrieveDestinationResults', provider)
    scope = resolve_destination_scope('Kulim, Kedah, Malaysia')
    generated = client.post('/api/fr4/recommendations/generate', headers=AUTH, json={
        'destinationArea': scope['canonicalName'], 'destinationScopeKey': scope['scopeKey'],
        'destinationLocationId': scope['locationId'], 'discoveryMode': 'relevant_v1'})
    assert generated.status_code == 200, generated.json
    assert {row['destinationId'] for row in generated.json['recommendations']} == {'kulim-fixture'}
    assert generated.json['snapshot']['canonicalDestinationScope']['scopeKey'] == scope['scopeKey']
    assert calls and all(area == 'Kulim, Kedah, Malaysia' for area, _ in calls)
    identity = generated.json['recommendationGenerationId']
    original = routes.resolve_destination_scope
    monkeypatch.setattr(routes, 'resolve_destination_scope', lambda name: {'resolved': False} if name == scope['canonicalName'] else original(name))
    monkeypatch.setattr(catalogue, 'online_id', Mock(side_effect=AssertionError('Saved reads must not geocode')))
    saved = client.get('/api/fr4/recommendations', headers=AUTH,
                       query_string={'generationId': identity, 'destinationArea': scope['canonicalName']})
    assert saved.status_code == 200 and saved.json['recommendationGenerationId'] == identity
    assert client.get('/api/fr4/recommendations', headers=AUTH, query_string={
        'generationId': identity, 'destinationArea': 'Alma, Penang, Malaysia'}).status_code == 404
    assert not validate_candidate({'city': 'Sungai Petani', 'state': 'Kedah'}, scope)[0]


def test_explore_uses_the_same_kulim_scope_without_changing_its_ranking():
    from modules.fr03_destination_search_information.routes import _search_scope
    requested, _, provider = _search_scope('Kulim, Kedah, Malaysia')
    assert requested['scopeKey'] == resolve_destination_scope('Kulim, Kedah, Malaysia')['scopeKey']
    assert provider == 'Kulim, Kedah, Malaysia'


def test_t07_browses_culture_after_typo_and_clarification_without_planning(delivery, client, monkeypatch):
    records, _, _, _ = delivery
    catalogue = [place(f'culture-{i}', type_id='museum', category='Culture') for i in range(3)]
    monkeypatch.setattr(chat, '_planning_catalog', lambda *args, **kwargs: deepcopy(catalogue))
    monkeypatch.setattr(chat, 'interpretChatbotIntent', lambda *_: None)
    sid = None
    for turn, message in enumerate(('suggest some cultural attractions in georgetwon',
                                     'georgetown penang', 'I want to view the place first')):
        response = client.post('/api/fr11/chat', headers=AUTH, json={
            'message': message, 'sessionId': sid, 'guidedPlanning': True,
            'clientRequestId': f't07_location_fixture_{turn:03}'})
        assert response.status_code == 200, response.json
        sid = response.json['session']['id']
        state = response.json['session']['planningState']
        assert state.get('planningGoal') != 'itinerary'
        assert not any(word in response.json['reply'].lower() for word in ('how much time', 'what dates', 'budget'))
        receipt = client.get(f'/api/fr11/chat-requests/t07_location_fixture_{turn:03}', headers=AUTH)
        assert receipt.json['status'] == 'completed'
    assert len(response.json['item']['placeSuggestions']) == 3
    assert {p['destinationId'] for p in response.json['item']['placeSuggestions']} == {p['destinationId'] for p in catalogue}
    assert len(records['chat_sessions'][sid]['messages']) == len(records['chat_messages']) == 3


def test_ambiguous_labels_preserve_identity_and_reject_another_same_named_locality():
    from services.malaysian_locality import resolve_selected_scope
    from modules.fr11_chatbot_travel_assistant.nlp_extractor import extract_geographic_entities
    first, other = catalogue.by_id('1346796'), catalogue.by_id('1769048')
    scope = location_scope(first)
    assert resolve_area_query('Kampung Huma')['resolved'] is False
    assert resolve_selected_scope(catalogue.label(first), scope['scopeKey'], scope['locationId']) == scope
    assert not validate_candidate({'city': other['name'], 'district': other['district'], 'state': other['state']}, scope)[0]
    marked = location_scope(catalogue.by_id('1732544'))
    legacy_label = marked['canonicalName'].replace('Sengkuang', 'Sengkuang [GeoNames 1732544]')
    assert resolve_destination_scope(legacy_label)['scopeKey'] == marked['scopeKey']
    assert extract_geographic_entities('Show places in ' + legacy_label)['destination_area'] == marked['canonicalName']
    assert not resolve_destination_scope(legacy_label.replace('Sengkuang', 'Kulim'))['resolved']
    assert not any('GeoNames ' in row['canonicalName'] for row in destination_locations())
    assert all(row['locationId'] not in {'geonames:1732544', 'geonames:1736883'} for row in destination_locations() if row.get('locationId'))


@pytest.mark.parametrize('message,expected,state', [
    ('This one boring', None, None), ('Plan a trip to Kangar', 'Kangar', 'Perlis'),
    ('Show places in Pulau Pinang', 'Penang', 'Penang'),
    ('Visit Sepilok in Sandakan', 'Sandakan', 'Sabah'),
    ('Recommend places in Kulim', 'Kulim', 'Kedah'),
])
def test_expanded_aliases_do_not_override_conversational_or_curated_meanings(message, expected, state):
    from modules.fr11_chatbot_travel_assistant.nlp_extractor import extract_geographic_entities
    geo = extract_geographic_entities(message)
    assert geo.get('destination_area') == expected
    assert geo.get('destination_state') == state


def test_explicit_lookup_unavailable_or_empty_never_writes_a_snapshot(discovery_route, client, monkeypatch):
    _, _, writes = discovery_route
    remote = Mock(side_effect=TimeoutError('Synthetic geocoder failure'))
    monkeypatch.setattr(catalogue, 'online_search', remote)
    response = client.get('/api/fr4/locations/search', headers=AUTH,
                          query_string={'q': 'NotAPlaceFixtureXyz', 'remote': 'true'})
    assert response.status_code == 502 and response.json['code'] == 'location_lookup_unavailable'
    remote.side_effect, remote.return_value = None, []
    empty = client.get('/api/fr4/locations/search', headers=AUTH,
                       query_string={'q': 'NotAPlaceFixtureXyz', 'remote': 'true'})
    assert empty.status_code == 200 and not empty.json['locations'] and not writes


def test_selected_remote_id_revalidation_uses_one_bounded_get(monkeypatch):
    from services import open_meteo_service
    from services.malaysian_locality import resolve_selected_scope
    point = catalogue.by_id('1734393')
    provider = Mock(return_value={'id': 999991003, 'name': 'Isolated revalidation fixture',
        'country_code': 'MY', 'admin1': 'Kedah', 'latitude': point['latitude'],
        'longitude': point['longitude'], 'feature_code': 'PPL'})
    monkeypatch.setattr(open_meteo_service, 'geocode_id', provider)
    try:
        scope = resolve_selected_scope('Isolated revalidation fixture, Kedah, Malaysia',
                                       'my:geonames:999991003', 'geonames:999991003')
        assert scope['state'] == 'Kedah' and scope['dataLicense'] == 'CC BY-NC 4.0'
        provider.assert_called_once_with('999991003', timeout=8)
        assert resolve_selected_scope(scope['canonicalName'], scope['scopeKey'], scope['locationId']) == scope
        assert provider.call_count == 1
        with pytest.raises(ValueError):
            resolve_selected_scope('Unverified fixture', location_id=str(2**31))
        assert provider.call_count == 1
    finally:
        with catalogue._remote_lock:
            catalogue._remote.pop('999991003', None)


def test_destination_clarification_preserves_culture_without_requiring_a_trip(delivery, client, monkeypatch):
    monkeypatch.setattr(chat, '_planning_catalog', lambda *args, **kwargs: [])
    monkeypatch.setattr(chat, 'interpretChatbotIntent', lambda *_: None)
    first = client.post('/api/fr11/chat', headers=AUTH, json={
        'message': 'Suggest cultural attractions in Kampung Baru', 'guidedPlanning': True,
        'clientRequestId': 'location_ambiguous_fixture_000'})
    assert first.status_code == 200 and first.json['item']['suggestedReplies']
    sid = first.json['session']['id']
    second = client.post('/api/fr11/chat', headers=AUTH, json={
        'message': 'georgetown penang', 'sessionId': sid, 'guidedPlanning': True,
        'clientRequestId': 'location_ambiguous_fixture_001'})
    assert second.status_code == 200
    state = second.json['session']['planningState']
    assert 'Culture' in state['placeSearch']['interests'] and state.get('planningGoal') != 'itinerary'
    assert 'how much time' not in second.json['reply'].lower()


def test_geographic_resolution_preserves_preferences_written_after_the_area(delivery, client, monkeypatch):
    candidates = [place('kulim-culture', city='Kulim', state='Kedah', type_id='museum', category='Culture'),
                  place('kulim-nature', city='Kulim', state='Kedah', type_id='park', category='Nature')]
    monkeypatch.setattr(chat, '_planning_catalog', lambda *args, **kwargs: deepcopy(candidates))
    monkeypatch.setattr(chat, 'interpretChatbotIntent', lambda *_: None)
    response = client.post('/api/fr11/chat', headers=AUTH, json={
        'message': 'Show places in Kulim with cultural attractions', 'guidedPlanning': True,
        'clientRequestId': 'location_tail_interest_fixture_000'})
    assert response.status_code == 200
    assert 'Culture' in response.json['session']['planningState']['placeSearch']['interests']
    assert {r['destinationId'] for r in response.json['item']['placeSuggestions']} == {'kulim-culture'}
