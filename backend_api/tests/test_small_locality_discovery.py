"""Sourced locality points, synthetic attractions, real isolated FR3/FR4 routes."""
from copy import deepcopy
import pytest
from test_shared_destination_discovery import discovery_route, place
from test_fr03_malaysia_search import isolated_destination_search
from services.malaysian_locality import resolve_destination_scope, validate_candidate

AUTH = {'Authorization': 'Bearer fixture'}


def attraction(key, area='Alma, Penang, Malaysia', **extra):
    scope = resolve_destination_scope(area)
    return {**place(key, title=f'Fixture {key}', city=scope['city'], state=scope['state'],
                   gps_coordinates={'latitude': scope['latitude'], 'longitude': scope['longitude']}), **extra}


@pytest.mark.parametrize('area', ['Alma, Penang, Malaysia', 'Machang Bubok, Penang, Malaysia',
    'Bukit Mertajam, Penang, Malaysia', 'Kulim, Kedah, Malaysia', 'George Town, Penang, Malaysia'])
def test_baseline_comparison_reports_locality_and_postal_city_filtering(area):
    scope = resolve_destination_scope(area)
    direct = attraction('in-area', area)
    postal = {**direct, 'destinationId': 'postal', 'city': 'Bukit Mertajam',
              'neighborhood': scope['city'], 'address': f"{scope['city']}, Bukit Mertajam, {scope['state']}, Malaysia"}
    nearby_only = {**postal, 'destinationId': 'nearby-only', 'neighborhood': None,
                   'address': f"Bukit Mertajam, {scope['state']}, Malaysia"}
    checked = [validate_candidate(row, scope) for row in (direct, postal, nearby_only)]
    print({'area': scope['canonicalName'], 'raw': 3, 'valid': sum(ok for ok, _ in checked),
           'reasons': [r['geographicEligibility']['reason'] for ok, r in checked if not ok]})
    assert checked[0][0]
    if area.startswith('Alma'):
        assert checked[1][0], 'Explicit Alma neighbourhood evidence must not be discarded because of its postal city'
        assert not checked[2][0], 'Coordinates near Alma alone cannot establish locality membership'


def test_explicit_nearby_is_separate_from_strict_results(discovery_route, client, monkeypatch):
    from modules.fr04_hybrid_recommendation import routes
    records, _, _ = discovery_route
    row = {**attraction('postal-nearby'), 'city': 'Bukit Mertajam', 'address': 'Bukit Mertajam, Penang, Malaysia'}
    monkeypatch.setattr(routes, 'retrieveDestinationResults', lambda *a, **kw: {'local_results': [deepcopy(row)]})
    payload = {'destinationArea': 'Alma, Penang, Malaysia', 'discoveryMode': 'relevant_v1'}
    strict = client.post('/api/fr4/recommendations/generate', headers=AUTH, json=payload)
    assert strict.status_code == 200 and not strict.json['recommendations']
    before = deepcopy(records['recommendation_snapshots'])
    nearby = client.post('/api/fr4/recommendations/generate', headers=AUTH,
                         json={**payload, 'geographicMode': 'nearby'})
    assert nearby.status_code == 200 and len(nearby.json['recommendations']) == 1
    assert nearby.json['recommendations'][0]['city'] == 'Bukit Mertajam'
    assert nearby.json['recommendations'][0]['nearbyDistanceKm'] == 0
    for key, value in before.items():
        assert records['recommendation_snapshots'][key] == value
    strict_id = strict.json['recommendationGenerationId']
    nearby_id = nearby.json['recommendationGenerationId']
    assert strict_id != nearby_id
    assert nearby.json['snapshot']['canonicalDestinationScope']['originScopeKey'] == strict.json['snapshot']['canonicalDestinationScope']['scopeKey']
    for identity, count in ((strict_id, 0), (nearby_id, 1)):
        saved = client.get('/api/fr4/recommendations', headers=AUTH,
                           query_string={'generationId': identity, 'destinationArea': payload['destinationArea'], 'discoveryMode': 'relevant_v1'})
        assert saved.status_code == 200 and len(saved.json['recommendations']) == count
    wrong = client.get('/api/fr4/recommendations', headers=AUTH, query_string={
        'generationId': nearby_id, 'destinationArea': payload['destinationArea'], 'geographicMode': 'strict'})
    assert wrong.status_code == 404
    latest = client.get('/api/fr4/recommendations', headers=AUTH, query_string={'discoveryMode': 'relevant_v1'})
    assert latest.json['recommendationGenerationId'] == strict_id


@pytest.mark.parametrize('variation,allowed', [
    ({'city': 'Bukit Mertajam'}, True),
    ({'city': None, 'address': None}, True),
    ({'gps_coordinates': None}, False),
    ({'gps_coordinates': {'latitude': float('nan'), 'longitude': 100.47}}, False),
    ({'state': 'Kedah'}, False),
    ({'country': 'Singapore'}, False),
    ({'gps_coordinates': {'latitude': 1.3, 'longitude': 103.85}}, False),
])
def test_nearby_requires_verified_coordinates_and_preserves_original_fields(variation, allowed):
    from services.malaysian_locality import discovery_scope
    scope = discovery_scope(resolve_destination_scope('Alma, Penang, Malaysia'), 'nearby')
    row = attraction('coordinates-fixture', **variation)
    original = deepcopy(row)
    ok, result = validate_candidate(row, scope)
    assert ok is allowed and row == original
    assert result.get('city') == row.get('city')
    assert result.get('address') == row.get('address')
    if allowed:
        assert result['nearbyDistanceKm'] == 0


def test_nearby_distance_is_bounded_and_not_a_locality_boundary():
    from services.malaysian_locality import discovery_scope
    base = resolve_destination_scope('Alma, Penang, Malaysia')
    scope = discovery_scope(base, 'nearby')
    row = attraction('one-km', city='Bukit Mertajam', gps_coordinates={
        'latitude': base['latitude'] + .009, 'longitude': base['longitude']})
    ok, result = validate_candidate(row, scope)
    assert ok and result['nearbyDistanceKm'] == pytest.approx(1, abs=.02)
    assert not validate_candidate(row, base)[0]
    far = attraction('georgetown-far', area='George Town, Penang, Malaysia')
    assert validate_candidate(far, scope)[1]['geographicEligibility']['reason'] == 'nearby_distance_out_of_scope'
    assert 'nearbyDistanceKm' not in validate_candidate(attraction('strict', nearbyDistanceKm=999), base)[1]


def test_strict_locality_needs_explicit_neighbourhood_not_a_street_name():
    scope = resolve_destination_scope('Alma, Penang, Malaysia')
    row = attraction('postal', city='Bukit Mertajam', address='Alma, Bukit Mertajam, Penang, Malaysia')
    ok, result = validate_candidate(row, scope)
    assert ok and result['city'] == 'Bukit Mertajam' and result['geographicEligibility']['reason'] == 'explicit_locality_evidence'
    assert not validate_candidate({**row, 'address': 'Jalan Alma, Bukit Mertajam, Penang, Malaysia'}, scope)[0]


@pytest.mark.parametrize('matching', [True, False])
def test_authoritative_stage_counts_and_preference_empty_state(discovery_route, client, monkeypatch, matching):
    from modules.fr04_hybrid_recommendation import routes
    rows = [attraction('first', type_id='museum' if matching else 'park'),
            attraction('nature', type_id='park'),
            attraction('trade', category='Manufacturer'),
            attraction('postal', city='Bukit Mertajam'),
            attraction('no-locality', city=None),
            attraction('foreign', country='SG')]
    monkeypatch.setattr(routes, 'retrieveDestinationResults', lambda *a, **kw: {'local_results': deepcopy(rows)})
    response = client.post('/api/fr4/recommendations/generate', headers=AUTH, json={
        'destinationArea': 'Alma, Penang, Malaysia', 'discoveryMode': 'relevant_v1'})
    assert response.status_code == 200
    snapshot = response.json['snapshot']; counts = snapshot['discoveryDiagnostics']
    assert counts['rawProviderCount'] == 6 and counts['geographicallyValidCount'] == 3
    assert sum(counts['geographicRejections'].values()) == 3
    assert counts['tourismCandidateCount'] == counts['uniqueEligiblePoolCount'] == 2
    assert counts['preferenceMatchCount'] == counts['displayedCount'] == (1 if matching else 0)
    assert response.json['engine']['weightedScoring'] == {'content': .6, 'collaborative': .3, 'popularity': .1}
    if not matching:
        assert snapshot['searchStatus'] == 'no_relevant_matches' and 'interests' in snapshot['searchMessage']
    else:
        nearby = client.post('/api/fr4/recommendations/generate', headers=AUTH, json={
            'destinationArea': 'Alma, Penang, Malaysia', 'discoveryMode': 'relevant_v1', 'geographicMode': 'nearby'})
        assert nearby.status_code == 200
        counts = nearby.json['snapshot']['discoveryDiagnostics']
        assert counts['rawProviderCount'] == 6 and counts['geographicallyValidCount'] == 5
        assert counts['tourismCandidateCount'] == counts['uniqueEligiblePoolCount'] == 4
        assert counts['preferenceMatchCount'] == counts['displayedCount'] == 3


@pytest.mark.parametrize('query,location,interpretation,provider_query', [
    ('Alma', 'Malaysia', 'locality', 'tourist attractions'),
    ('Alma', 'Alma, Penang, Malaysia', 'keyword', 'places to visit Alma'),
    ('tourist attractions', 'Alma, Penang, Malaysia', 'keyword', 'tourist attraction'),
])
def test_explore_keyword_versus_locality_semantics(client, mock_traveller_auth, isolated_destination_search,
                                                query, location, interpretation, provider_query):
    provider, _, _ = isolated_destination_search
    provider.return_value = {'local_results': [attraction('in-alma')]}
    response = client.get('/api/fr3/destinations/search', headers=AUTH, query_string={'q': query, 'location': location})
    assert response.status_code == 200 and response.json['results']
    assert response.json['queryInterpretation'] == interpretation
    assert provider.call_args.args[:2] == (provider_query, 'Alma, Penang, Malaysia')


def test_explore_nearby_deduplicates_and_preserves_postal_location(client, mock_traveller_auth, isolated_destination_search):
    provider, _, _ = isolated_destination_search
    row = attraction('nearby', city='Bukit Mertajam', address='Bukit Mertajam, Penang, Malaysia')
    provider.return_value = {'local_results': [row, deepcopy(row), attraction('foreign', country='SG')]}
    response = client.get('/api/fr3/destinations/search', headers=AUTH, query_string={
        'q': 'tourist attractions', 'location': 'Alma, Penang, Malaysia', 'geographicMode': 'nearby'})
    assert response.status_code == 200 and len(response.json['results']) == 1
    result = response.json['results'][0]
    assert result['city'] == 'Bukit Mertajam' and result['address'] == row['address'] and result['nearbyDistanceKm'] == 0
    assert response.json['canonicalDestinationScope']['geographicMode'] == 'nearby'
    assert provider.call_args.args[0] == 'tourist attraction near Alma, Penang, Malaysia'


def test_explore_provider_empty_and_unavailable_are_distinct(client, mock_traveller_auth, isolated_destination_search, monkeypatch):
    provider, _, _ = isolated_destination_search
    monkeypatch.setenv('FALLBACK_MODE', 'false')
    provider.return_value = {'local_results': []}
    params = {'q': 'tourist attractions', 'location': 'Alma, Penang, Malaysia'}
    empty = client.get('/api/fr3/destinations/search', headers=AUTH, query_string=params)
    assert empty.status_code == 200 and empty.json['searchStatus'] == 'no_candidates'
    assert empty.json['discoveryDiagnostics']['rawProviderCount'] == 0
    provider.side_effect = TimeoutError('Isolated provider failure')
    error = client.get('/api/fr3/destinations/search', headers=AUTH, query_string=params)
    assert error.status_code == 502 and 'temporarily unavailable' in error.json['error']


def test_unavailable_provider_with_only_out_of_area_fallback_is_not_an_empty_success(client, mock_traveller_auth, isolated_destination_search, monkeypatch):
    from modules.fr03_destination_search_information import routes
    provider, _, _ = isolated_destination_search
    monkeypatch.setenv('FALLBACK_MODE', 'true')
    monkeypatch.setattr(routes, '_all_destinations', lambda: [attraction('outside', city='Bukit Mertajam', category='Tourist attraction')])
    provider.side_effect = TimeoutError('Isolated provider failure')
    response = client.get('/api/fr3/destinations/search', headers=AUTH, query_string={
        'q': 'tourist attractions', 'location': 'Alma, Penang, Malaysia'})
    assert response.status_code == 502 and response.json['code'] == 'destination_provider_unavailable'


def test_nearby_can_cross_a_malaysian_state_border_without_relabelling():
    from services.malaysian_locality import discovery_scope
    scope = discovery_scope(resolve_destination_scope('Alma, Penang, Malaysia'), 'nearby')
    row = attraction('kulim-fixture', area='Kulim, Kedah, Malaysia')
    ok, result = validate_candidate(row, scope)
    assert ok and 0 < result['nearbyDistanceKm'] <= 10
    assert result['city'] == 'Kulim' and result['state'] == 'Kedah'


def test_nearby_provider_query_explicitly_changes_search_semantics():
    from unittest.mock import Mock
    from services.destination_candidates import provider_page
    from services.malaysian_locality import discovery_scope
    scope = discovery_scope(resolve_destination_scope('Alma, Penang, Malaysia'), 'nearby')
    provider = Mock(return_value={'local_results': []})
    provider_page(provider, 'museums', scope)
    assert provider.call_args.args[:2] == ('museums near Alma, Penang, Malaysia', 'Alma, Penang, Malaysia')
    assert provider.call_args.args[2] == {'latitude': scope['latitude'], 'longitude': scope['longitude']}


@pytest.mark.parametrize('module', ['for_you', 'explore'])
def test_nearby_equal_relevance_prefers_closer_coordinates(discovery_route, client, mock_traveller_auth, isolated_destination_search, monkeypatch, module):
    from modules.fr04_hybrid_recommendation import routes
    scope = resolve_destination_scope('Alma, Penang, Malaysia')
    rows = [attraction(key, city='Bukit Mertajam', gps_coordinates={
        'latitude': scope['latitude'] + offset, 'longitude': scope['longitude']})
        for key, offset in (('farther', .02), ('closer', .005))]
    if module == 'for_you':
        monkeypatch.setattr(routes, 'retrieveDestinationResults', lambda *a, **kw: {'local_results': deepcopy(rows)})
        response = client.post('/api/fr4/recommendations/generate', headers=AUTH, json={
            'destinationArea': scope['canonicalName'], 'geographicMode': 'nearby', 'discoveryMode': 'relevant_v1'})
        assert response.status_code == 200
        results = response.json['recommendations']
        assert results[0]['finalScore'] == results[1]['finalScore']
    else:
        isolated_destination_search[0].return_value = {'local_results': deepcopy(rows)}
        response = client.get('/api/fr3/destinations/search', headers=AUTH, query_string={
            'q': 'tourist attractions', 'location': scope['canonicalName'], 'geographicMode': 'nearby'})
        assert response.status_code == 200
        results = response.json['results']
    assert [r['destinationId'] for r in results] == ['closer', 'farther']


def test_explore_reports_rejected_geography_instead_of_generic_empty(client, mock_traveller_auth, isolated_destination_search):
    provider, _, _ = isolated_destination_search
    provider.return_value = {'local_results': [{**attraction('postal-only'), 'city': 'Bukit Mertajam'}]}
    result = client.get('/api/fr3/destinations/search', headers=AUTH,
                        query_string={'q': 'tourist attractions', 'location': 'Alma, Penang, Malaysia'})
    assert result.status_code == 200 and not result.json['results']
    assert result.json['searchStatus'] == 'no_exact_locality_matches'
    assert result.json['discoveryDiagnostics']['rawProviderCount'] == 1
