"""Batch D facts, request budget, provenance and geography; no live provider/storage."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path

import pytest
from google.api_core.exceptions import DataLoss

from services import serpapi_service as maps
from services import destination_candidates as candidates
from services.recommendation_discovery import discovery_queries, QUERY_TEMPLATES
from services.recommendation_taxonomy import candidate_concepts, experience_types
from services.malaysian_locality import normalize_destination_scope, validate_candidate, LOCALITY_CENTRES, STATE_CENTERS
from services.recommendation_snapshot_storage import latest_snapshot
from sequence_contract.domain_functions import diversifyRecommendations


def place(key='p', **extra):
    return {'destinationId': key, 'title': f'Recorded {key}', 'state': 'Penang',
            'city': 'George Town', 'type_id': 'museum', **extra}


@pytest.mark.parametrize('start', [0, 20, 40, 200])
def test_mocked_http_parameters_and_normalized_next_link(monkeypatch, start):
    calls = []
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {'local_results': [place()], 'serpapi_pagination': {
                'next': f'https://serpapi.com/search.json?start={start+20}&api_key=do-not-expose'}}
    monkeypatch.setenv('SERPAPI_KEY', 'mock-only-key')
    monkeypatch.setattr(maps.requests, 'get', lambda url, **kw: calls.append(kw) or Response())
    result = maps.retrieveDestinationResults('heritage', 'Penang', {'latitude': 5.41123, 'longitude': 100.33543}, start)
    params = calls[0]['params']
    assert params['engine'] == 'google_maps' and params['type'] == 'search'
    assert params['q'] == 'heritage in Penang' and params['hl'] == 'en' and params['gl'] == 'my'
    assert params.get('start', 0) == start and params['ll'] == '@5.41123,100.33543,11z'
    assert result['pagination'] == {'hasMore': start < 200, 'nextOffset': start + 20 if start < 200 else None}
    assert 'do-not-expose' not in str(result) and 'mock-only-key' not in str(result)


@pytest.mark.parametrize('data', [[], {'local_results': None}, {'local_results': {}}, {'error': 'private error'}])
def test_malformed_search_response_is_safe(monkeypatch, data):
    monkeypatch.setattr(maps, '_request', lambda *_: data)
    with pytest.raises(RuntimeError, match='temporarily unavailable'):
        maps.retrieveDestinationResults('museums')


def test_absent_pagination_does_not_infer_another_page_from_twenty_results(monkeypatch):
    monkeypatch.setattr(maps, '_request', lambda *_: {'local_results': [place(str(i)) for i in range(20)]})
    assert maps.retrieveDestinationResults('museums')['pagination']['nextOffset'] is None
    monkeypatch.setattr(maps, '_request', lambda *_: {'local_results': []})
    assert maps.retrieveDestinationResults('museums')['local_results'] == []


@pytest.mark.parametrize('url', ['https://untrusted.test/search?start=20', 'http://serpapi.com/search?start=20',
    'https://serpapi.com/search?start=40', 'https://serpapi.com/search?start=20&start=40', 'not a URL'])
def test_provider_url_is_not_executed_or_treated_as_valid_cursor(url):
    assert maps.destination_pagination({'serpapi_pagination': {'next': url}}, 0)['hasMore'] is False


def test_missing_key_and_http_failure_never_leak_details(monkeypatch):
    monkeypatch.delenv('SERPAPI_KEY', raising=False)
    with pytest.raises(RuntimeError) as error:
        maps.retrieveDestinationResults('nature')
    assert 'temporarily unavailable' in str(error.value)
    monkeypatch.setenv('SERPAPI_KEY', 'secret-fixture')
    monkeypatch.setattr(maps.requests, 'get', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('url?api_key=secret-fixture')))
    with pytest.raises(RuntimeError) as error:
        maps.retrieveDestinationResults('nature')
    assert 'secret-fixture' not in str(error.value) and error.value.__suppress_context__


@pytest.mark.parametrize('concept', list(QUERY_TEMPLATES))
def test_all_nine_interests_have_specific_bounded_discovery(concept):
    queries = discovery_queries({'interests': [concept]}, [place('only', type_id='', category=concept)])
    assert queries and queries[0] in QUERY_TEMPLATES[concept] and 'tourist attractions' not in queries


def test_query_coverage_counts_unique_eligible_unrejected_experiences():
    pref = {'interests': ['Photography', 'Food', 'Shopping', 'Social'], 'destinationFeedback': {'rejected': 'not_for_me'}}
    rows = [place('rejected', type_id='restaurant'), place('photo', type_id='observation_deck')]
    queries = discovery_queries(pref, rows)
    assert len(queries) == 3 and queries == discovery_queries(pref, list(reversed(rows)))
    assert 'hawker centres' in queries and 'shopping districts' in queries and 'night markets' in queries
    assert discovery_queries({'interests': ['Unverifiable hobby']}, rows) == []
    assert discovery_queries({'interests': ['Food']}, [place(str(i), type_id='', category='Food',
        title='Same venue') for i in range(4)])


@pytest.mark.parametrize('city', ['George Town', 'Butterworth', 'Bukit Mertajam', 'Ipoh', 'Taiping',
    'Johor Bahru', 'Langkawi', 'Alor Setar', 'Melaka City', 'Kota Kinabalu', 'Kuching', 'Miri',
    'Cameron Highlands', 'Kuantan', 'Semporna', 'Sibu', 'Kuala Selangor', 'Kuala Kangsar', 'Muar', 'Sungai Petani'])
def test_verified_city_centres_and_coordinate_state(city):
    scope = normalize_destination_scope(city)
    source = LOCALITY_CENTRES[city]
    if city == 'Semporna':
        assert scope['latitude'] is None and scope['longitude'] is None
        assert scope['coordinateStatus'] == 'unavailable_or_boundary_conflict'
        assert not validate_candidate({'gps_coordinates': source}, 'Malaysia')[0]
        return  # Gazetteer coastal point lies outside this pinned land polygon; no guessed replacement.
    assert (scope['latitude'], scope['longitude']) == (source['latitude'], source['longitude'])
    ok, row = validate_candidate({'title': city, 'gps_coordinates': source}, 'Malaysia')
    assert ok and row['normalizedGeography']['state'] == scope['state']
    assert scope['coordinateSource'].startswith('https://www.geonames.org/')


@pytest.mark.parametrize('state', list(STATE_CENTERS))
def test_every_state_or_federal_territory_has_geographical_validation(state):
    coords = STATE_CENTERS[state]
    ok, row = validate_candidate({'state': state, 'gps_coordinates': {'latitude': coords[0], 'longitude': coords[1]}},
        {'resolved': True, 'scopeKey': 'state-fixture', 'state': state, 'city': None})
    assert ok and row['normalizedGeography']['state'] == state


def test_newly_sourced_city_centre_is_not_its_state_capital_and_foreign_coords_are_rejected():
    from services.malaysia_locations import by_id
    scope = normalize_destination_scope('Kundasang')
    sourced = by_id('1736633')
    assert scope['resolved'] and scope['coordinateStatus'] == 'verified_locality'
    assert (scope['latitude'], scope['longitude']) == (sourced['latitude'], sourced['longitude'])
    assert (scope['latitude'], scope['longitude']) != STATE_CENTERS['Sabah']
    ok, _ = validate_candidate({'state': 'Penang', 'gps_coordinates': {'latitude': 1.3, 'longitude': 103.85}}, 'Penang')
    assert not ok
    assert not validate_candidate({'gps_coordinates': {'latitude': 13.75, 'longitude': 100.5}}, 'Malaysia')[0]


def test_provider_ids_are_evidence_not_invented_personality_or_cost():
    row = place(type_id='botanical_garden')
    normalized = candidates.normalise([row], normalize_destination_scope('Penang'), source='live_provider')[0]
    assert 'nature' in candidate_concepts(normalized) and experience_types(normalized) == ['botanical_garden']
    assert not any(field in normalized for field in ('budgetLevel', 'pace', 'personality', 'familyFriendly', 'openingHours'))
    assert normalized['metadataEvidence']['providerCategoryIds'] == ['botanical_garden']


def test_freshness_merge_preserves_live_metadata_and_stable_identity():
    scope = normalize_destination_scope('Penang')
    old = place(cachedAt='2020-01-01T00:00:00Z', description='Old', rating=1)
    stale = candidates.normalise([old], scope, source='cache')
    fresh = candidates.normalise([place('google-id', title=old['title'], description='New', rating=4)], scope, source='live_provider')
    result = candidates.merge_candidates(fresh, stale)
    assert len(result) == 1 and result[0]['description'] == 'New' and result[0]['rating'] == 4
    assert result[0]['destinationId'] == 'p' and result[0]['ratingSource'] == 'provider'
    assert stale[0]['cacheFreshness'] == 'stale'
    assert candidates.normalise([place()], scope, source='cache')[0]['cacheFreshness'] == 'unknown'
    assert len(candidates.merge_candidates([place(title='Same')], [place('other', title='Same', state='Perak', city='Ipoh')])) == 2


def test_cache_queries_are_ordered_before_limiting_and_keep_legacy_fallback():
    calls = []
    def read(name, **kw):
        calls.append((name, kw))
        return [place(cachedAt=datetime.now(timezone.utc))] if kw['orderBy'][0][0] == 'cachedAt' else [place('legacy')]
    pool = candidates.cached_candidates(read, normalize_destination_scope('Penang'))
    assert len(pool) == 2 and len(calls) == 3
    assert all(call[1]['orderBy'] for call in calls)
    assert any(r['cacheFreshness'] == 'unknown' for r in pool)
    assert all(isinstance(r.get('cachedAt', ''), str) for r in pool)


def test_provider_budget_is_three_per_generation_six_per_chain():
    calls = []
    def provider(query, scope, offset):
        calls.append((query, offset))
        return {'items': [place(f'{query}-{offset}')], 'hasMore': True, 'nextOffset': offset + 20}
    previous = candidates.discovery_pool(None, provider, normalize_destination_scope('Penang'), {}, cached=[],
        queries=['food', 'art', 'parks'], allow_provider=True)
    assert len(calls) == 3 and previous['providerHasMore']
    later = candidates.discovery_pool(None, provider, normalize_destination_scope('Penang'), {}, cached=[],
        previous=previous['items'], cursors=previous['cursors'], used=3, queries=['food', 'art', 'parks'], allow_provider=True)
    assert len(calls) == 6 and later['providerRequestsUsed'] == 6 and not later['providerHasMore']
    candidates.discovery_pool(None, provider, normalize_destination_scope('Penang'), {}, cached=[],
        used=6, queries=['food'], allow_provider=True)
    assert len(calls) == 6


def test_latest_snapshot_uses_ordered_owner_headers_then_hydrates_newest_valid():
    calls, hydrated = [], []
    def read(collection, **kw):
        calls.append(kw)
        return [{'id': 'broken', 'travellerId': 'owner', 'generatedAt': '2026-11-16T10:00:00Z'},
                {'id': 'valid', 'travellerId': 'owner', 'generatedAt': '2026-11-15T10:00:00Z'},
                {'id': 'foreign', 'travellerId': 'other', 'generatedAt': '2027-01-01'}]
    def hydrate(header):
        hydrated.append(header['id'])
        if header['id'] == 'broken': raise DataLoss('Fixture corrupt payload')
        return {**header, 'recommendationResults': []}
    result = latest_snapshot(read, hydrate, 'owner')
    assert result['id'] == 'valid' and hydrated == ['broken', 'valid']
    assert calls[0]['orderBy'] == [('generatedAt', 'DESCENDING')]
    assert calls[0]['filters'] == [('travellerId', '==', 'owner')]


def test_diversity_is_bounded_deterministic_and_keeps_hybrid_score():
    rows = [place(str(i), score=90 - i / 10, type_id='botanical_garden' if i < 4 else 'hiking_area',
                  normalizedGeography={'state': 'Penang' if i < 4 else 'Perak', 'city': 'George Town' if i < 4 else 'Ipoh'}) for i in range(6)]
    before = deepcopy(rows)
    ranked = diversifyRecommendations(rows, {'interests': ['Nature']})
    assert [r['destinationId'] for r in ranked] == [r['destinationId'] for r in diversifyRecommendations(list(reversed(rows)), {'interests': ['Nature']})]
    assert any(r['destinationId'] == '4' for r in ranked[:3])
    assert all(0 <= r['diversityPenalty'] <= 7 and r['score'] == before[int(r['destinationId'])]['score'] for r in ranked)
    assert rows == before


@pytest.fixture
def discovery_route(client, mock_traveller_auth, monkeypatch):
    from modules.fr04_hybrid_recommendation import routes
    records = {'travel_preferences': {'test_traveller_uid': {'travellerId': 'test_traveller_uid', 'interests': ['Culture']}}}
    requests, writes = [], []
    def read(collection, documentId=None, filters=None, limit=None, orderBy=None):
        data = records.get(collection, {})
        if documentId:
            return deepcopy(data.get(documentId))
        rows = list(data.values())
        def field(row, name):
            for key in name.split('.'):
                row = row.get(key) if isinstance(row, dict) else None
            return row
        for name, operator, value in filters or []:
            assert operator == '=='
            rows = [r for r in rows if field(r, name) == value]
        for name, direction in reversed(orderBy or []):
            rows.sort(key=lambda r: str(r.get('id') if name == '__name__' else field(r, name) or ''), reverse=direction == 'DESCENDING')
        return deepcopy(rows[:limit] if limit else rows)
    def store(collection, row, identity, merge=False):
        writes.append(collection)
        table = records.setdefault(collection, {})
        table[identity] = {**(table.get(identity, {}) if merge else {}), **deepcopy(row), 'id': identity}
    def provider(query, location, coords, **kw):
        offset = kw.get('start', 0)
        requests.append((query, offset))
        items = [place(f'{query}_{i}', type_id='museum', title=f'{query} museum {i}') for i in range(offset, offset + 20)]
        return {'local_results': items, 'pagination': {'hasMore': offset < 40, 'nextOffset': offset + 20 if offset < 40 else None}}
    monkeypatch.setenv('SERPAPI_KEY', 'mock-only')
    monkeypatch.setattr(routes, 'retrieveRecord', read)
    monkeypatch.setattr(routes, 'storeRecord', store)
    monkeypatch.setattr(routes, 'retrieveDestinationResults', provider)
    return records, requests, writes


def test_api_load_more_reads_snapshot_and_discover_appends_immutable_pool(discovery_route, client):
    records, calls, writes = discovery_route
    auth = {'Authorization': 'Bearer fixture'}
    options = {'destinationArea': 'Penang', 'discoveryMode': 'relevant_v1'}
    initial = client.post('/api/fr4/recommendations/generate', headers=auth, json=options)
    assert initial.status_code == 200, initial.json
    first = initial.json
    generation = first['recommendationGenerationId']
    before = deepcopy(records['recommendation_snapshots'][generation])
    write_count = len(writes)
    page = client.get('/api/fr4/recommendations', headers=auth, query_string={
        'generationId': generation, 'discoveryMode': 'relevant_v1', 'offset': 12})
    assert page.status_code == 200 and len(page.json['recommendations']) == 8
    assert len(calls) == 1 and len(writes) == write_count
    shown = [r['destinationId'] for r in first['recommendations'] + page.json['recommendations']]
    expanded = client.post('/api/fr4/recommendations/generate', headers=auth, json={**options,
        'previousGenerationId': generation, 'expandCandidates': True, 'displayedDestinationIds': shown})
    assert expanded.status_code == 200, expanded.json
    next_id = expanded.json['recommendationGenerationId']
    assert next_id != generation and records['recommendation_snapshots'][generation] == before
    added = [r['destinationId'] for r in expanded.json['recommendations']]
    assert added and not set(added) & set(shown)
    new_pool = records['recommendation_snapshots'][next_id]['recommendationResults']
    assert [r['destinationId'] for r in new_pool[:len(shown)]] == shown
    assert expanded.json['pagination']['offset'] == len(shown)
    assert len(calls) <= 4 and records['recommendation_snapshots'][next_id]['providerRequestsUsed'] <= 6


def test_expansion_owner_and_displayed_id_checks_precede_provider(discovery_route, client):
    records, calls, writes = discovery_route
    auth = {'Authorization': 'Bearer fixture'}
    initial = client.post('/api/fr4/recommendations/generate', headers=auth,
                          json={'destinationArea': 'Penang', 'discoveryMode': 'relevant_v1'}).json
    generation = initial['recommendationGenerationId']
    before = (len(calls), len(writes))
    invalid = client.post('/api/fr4/recommendations/generate', headers=auth, json={
        'destinationArea': 'Penang', 'previousGenerationId': generation, 'displayedDestinationIds': ['unrelated']})
    assert invalid.status_code == 400 and (len(calls), len(writes)) == before
    records['recommendation_snapshots'][generation]['travellerId'] = 'other-account'
    invalid = client.post('/api/fr4/recommendations/generate', headers=auth,
                          json={'destinationArea': 'Penang', 'previousGenerationId': generation})
    assert invalid.status_code == 404 and (len(calls), len(writes)) == before


def test_nonfinite_provider_numbers_remain_unknown_and_json_safe():
    rows = candidates.normalise([place(rating=float('nan'), reviews=float('inf'),
                                      extra={'score': float('-inf')})], normalize_destination_scope('Penang'), source='live_provider')
    assert rows[0]['rating'] is None and rows[0]['reviews'] is None
    assert rows[0]['extra']['score'] is None
    json.dumps(rows, allow_nan=False)


def test_failed_provider_attempts_stay_bounded_across_expansions():
    calls = []
    def provider(*args):
        calls.append(args)
        raise RuntimeError('Do not expose provider details')
    pool = {'items': [place()], 'cursors': {}, 'providerRequestsUsed': 0}
    for _ in range(4):
        pool = candidates.discovery_pool(None, provider, normalize_destination_scope('Penang'), {}, cached=[],
            previous=pool['items'], cursors=pool['cursors'], used=pool['providerRequestsUsed'],
            queries=['food', 'parks', 'art'], allow_provider=True)
        assert pool['items'] and pool['source'] == 'cache'
        assert 'Do not expose' not in str(pool)
    assert len(calls) == 6 and pool['providerRequestsUsed'] == 6


def test_personal_recommendations_skip_corrupt_payload_without_other_account_reads():
    from modules.fr11_chatbot_travel_assistant.personal_questions import respond
    headers = [{'id': 'broken', 'travellerId': 'owner', 'generatedAt': '2026-11-16'},
               {'id': 'valid', 'travellerId': 'owner', 'generatedAt': '2026-11-15'}]
    reads = []
    def read(collection, key=None, **options):
        reads.append((collection, key, options))
        if collection != 'recommendation_snapshots': return None
        if key == 'broken': raise DataLoss('Fixture corrupt payload')
        if key == 'valid': return {**headers[1], 'recommendationResults': [place(title='Retained museum')]}
        return headers
    result = respond('Show my recommendations', {}, read, 'owner')
    assert result['savedRecommendations'][0]['title'] == 'Retained museum'
    assert [key for collection, key, _ in reads if collection == 'recommendation_snapshots' and key] == ['broken', 'valid']


def test_exhausted_provider_can_expand_from_new_cache_without_replacing_visible_rows(discovery_route, client, monkeypatch):
    records, calls, writes = discovery_route
    auth = {'Authorization': 'Bearer fixture'}
    initial = client.post('/api/fr4/recommendations/generate', headers=auth,
                          json={'destinationArea': 'Penang', 'discoveryMode': 'relevant_v1'}).json
    generation = initial['recommendationGenerationId']
    shown = [r['destinationId'] for r in records['recommendation_snapshots'][generation]['recommendationResults']]
    records['destination_cache'] = {}
    monkeypatch.setenv('SERPAPI_KEY', '')
    before = len(writes), len(calls)
    options = {'destinationArea': 'Penang', 'discoveryMode': 'relevant_v1', 'previousGenerationId': generation,
               'expandCandidates': True, 'displayedDestinationIds': shown}
    unchanged = client.post('/api/fr4/recommendations/generate', headers=auth, json=options)
    assert unchanged.status_code == 200, unchanged.json
    assert unchanged.json['recommendationGenerationId'] == generation and not unchanged.json['expanded']
    assert (len(writes), len(calls)) == before
    records['destination_cache']['new-cache'] = place('new-cache', title='New recorded museum', cachedAt='2026-11-16T00:00:00Z')
    expanded = client.post('/api/fr4/recommendations/generate', headers=auth, json=options)
    assert expanded.status_code == 200, expanded.json
    assert expanded.json['recommendationGenerationId'] != generation and len(calls) == before[1]
    assert [r['destinationId'] for r in expanded.json['recommendations']] == ['new-cache']
    pool = records['recommendation_snapshots'][expanded.json['recommendationGenerationId']]['recommendationResults']
    assert [r['destinationId'] for r in pool[:len(shown)]] == shown


def test_firestore_ordering_precedes_limit_and_stream(monkeypatch):
    from sequence_contract import firebase_firestore as storage
    steps = []
    class Query:
        def collection(self, name): steps.append(('collection', name)); return self
        def where(self, *args): steps.append(('where', args)); return self
        def order_by(self, field, direction): steps.append(('order', field, direction)); return self
        def limit(self, value): steps.append(('limit', value)); return self
        def stream(self): steps.append(('stream',)); return []
    monkeypatch.setattr(storage, 'get_db', lambda: Query())
    assert storage.retrieveRecord('destination_cache', filters=[('canonicalDestinationScope', '==', 'my:penang')],
        orderBy=[('cachedAt', 'DESCENDING')], limit=150) == []
    assert steps[-3:] == [('order', 'cachedAt', 'DESCENDING'), ('limit', 150), ('stream',)]
