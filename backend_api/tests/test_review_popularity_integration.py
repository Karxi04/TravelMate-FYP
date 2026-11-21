"""All review evidence is isolated fixture data; never initialize live Firebase."""
from copy import deepcopy
from unittest.mock import Mock
import pytest

from scripts.plan_penang_fyp_reviews import build_plan as base_plan
from scripts.plan_penang_fyp_expansion import build_plan as expansion_plan
from services import demonstration_recommendations as demo
from services.recommendation_review_evidence import approved_contributions, review_summaries
from services.review_destination import review_candidate_id
from sequence_contract import domain_functions as engine
from modules.fr04_hybrid_recommendation import routes
from test_penang_collaborative_evidence import generation


@pytest.fixture
def penang():
    base, expanded = base_plan(), expansion_plan()
    places = list(base['documents']['fyp_review_datasets/penang_v1']['destinations'].values())
    reviews = [row for row in [*base['documents'].values(), *expanded['documents'].values()] if 'rating' in row]
    return places, reviews


def genuine_review(uid='peer', identity='local_kek_lok_si', rating=4, **extras):
    # This models genuine eligibility only inside isolated tests, not real customers.
    return {'id': uid, 'travellerId': uid, 'destinationId': identity, 'rating': rating,
            'feedbackStatus': 'visible', 'moderationStatus': 'approved', **extras}


def score(candidate, rows=(), **kwargs):
    summary = review_summaries(approved_contributions(rows))
    return engine.calculateRecommendationScore([{'contentScore': 70, 'collaborativeScore': 50,
        **candidate}], summary, **kwargs)[0]


def test_provider_first_then_genuine_local_fallback_and_badge_is_not_evidence():
    rows = [genuine_review(f'p{i}', rating=rating) for i, rating in enumerate([5,5,4,4,4,4,3,3,3,3])]
    candidate = {'destinationId': 'kek_lok_si', 'ratingSource': 'unverified_local_catalog',
                 'rating': 5, 'reviews': 100000}
    local = score(candidate, rows)
    assert local['popularitySource'] == 'genuine_approved_local_reviews'
    assert local['popularityScore'] == 60.82
    assert local['popularityEvidence']['rating'] == 3.8
    assert local['popularityEvidence']['reviewCount'] == 10
    provider = score({**candidate, 'ratingSource': 'provider', 'rating': 4.5, 'reviews': 9000}, rows)
    assert provider['popularityScore'] == 90
    assert provider['popularitySource'] == 'provider_rating_review_count'
    unverified = score({'destinationId': 'demo_penang_street_art', 'rating': 4.5, 'reviews': 9000})
    assert unverified['popularityScore'] == 50
    private_badge = score({**candidate, 'localRatingSummary': {'rating': 3.8, 'reviews': 10,
        'ratingBasis': 'private_illustrative'}})
    assert private_badge['popularityScore'] == 50


def test_all104_definitions_keep_provenance_and_moderation_and_never_become_public_evidence(penang):
    candidates, rows = penang
    original = deepcopy(rows)
    assert len(rows) == 104 and all(row['synthetic'] is True for row in rows)
    assert sum(map(len, approved_contributions(rows, demonstration=True).values())) == 96
    assert not review_summaries(approved_contributions(rows))
    profile = demo.SIMULATED_PROFILES['culture']
    public = engine.calculateRecommendationScore(engine.applyCollaborativeFiltering(candidates, rows,
        demo.simulated_profiles(rows), profile), review_summaries(approved_contributions(rows)))
    assert {row['collaborativeScore'] for row in public} == {50}
    assert {row['popularityScore'] for row in public} == {50}
    results = demo.evaluate(profile, candidates, rows)
    assert len(results) == 12
    assert all(row['synthetic'] and row['recommendationEvidenceMode'] == 'demonstration' for row in results)
    assert all(row['popularitySource'] == 'demonstration_approved_reviews' for row in results)
    assert all(row['collaborativeConfidence'] > 0 for row in results)
    assert min(row['popularityScore'] for row in results) < 65
    assert rows == original


def test_simulation_profile_assignment_is_independent_of_rating_and_moderation_changes_apply(penang):
    candidates, rows = penang
    changed = deepcopy(rows)
    for row in changed:
        row['rating'] = 1
    assert demo.simulated_profiles(rows) == demo.simulated_profiles(changed)
    first = demo.evaluate(demo.SIMULATED_PROFILES['culture'], candidates, rows)
    assert demo.evaluate(demo.SIMULATED_PROFILES['nature'], candidates, rows) != first
    hidden = deepcopy(rows)
    for row in hidden:
        if row['destinationId'] == 'local_kek_lok_si':
            row['feedbackStatus'] = 'hidden'
    result = next(row for row in demo.evaluate(demo.SIMULATED_PROFILES['culture'], candidates, hidden)
                  if row['destinationId'] == 'local_kek_lok_si')
    assert result['collaborativeRatingCount'] == 0
    assert result['popularityScore'] == 50


def test_all12_verified_review_identities_support_server_resolved_provider_ids(penang):
    candidates, _ = penang
    for place in candidates:
        identity = place['destinationId']
        candidate = {'destinationId': 'isolated-provider-reference', 'reviewDestinationId': identity}
        assert review_candidate_id(candidate) == identity
        row = score(candidate, [genuine_review(identity=identity, rating=2)])
        assert row['popularitySource'] == 'genuine_approved_local_reviews'
        assert row['popularityScore'] == 32.0
        peer = engine.applyCollaborativeFiltering([candidate], [genuine_review(identity=identity, rating=2)],
            {'peer': demo.SIMULATED_PROFILES['culture']}, demo.SIMULATED_PROFILES['culture'])[0]
        assert peer['collaborativeRatingCount'] == 1
        assert peer['collaborativeScore'] < 50


def test_readonly_demo_route_is_local_authorized_and_never_saves_or_reads_genuine_snapshots(client, mock_traveller_auth, monkeypatch, penang):
    monkeypatch.setattr(demo, 'load_sources', lambda area: deepcopy(penang))
    blocked = Mock(side_effect=AssertionError('No records may be read/written for a selected simulated profile'))
    for name in ('storeRecord', 'retrieveRecord', 'retrieveRecordsById', 'transactPreferenceLearning'):
        monkeypatch.setattr(routes, name, blocked)
    url = '/api/fr4/recommendations/demonstration?profileKey=culture'
    headers = {'Authorization': 'Bearer isolated-token'}
    client.application.config['LOCAL_FYP_SAMPLE_REVIEWS'] = True
    assert client.get(url, headers=headers).status_code == 403
    headers['X-TravelMate-Review-Context'] = 'fyp-v1'
    response = client.get(url, headers=headers)
    assert response.status_code == 200
    assert response.json['synthetic'] and response.json['recommendationEvidenceMode'] == 'demonstration'
    assert len(response.json['recommendations']) == 12
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert not blocked.called
    client.application.config['LOCAL_FYP_SAMPLE_REVIEWS'] = False
    assert client.get(url, headers=headers).status_code == 403


def test_simulation_cannot_treat_genuine_rows_as_demo_or_unmoderated_samples_as_approved(penang):
    candidates, _ = penang
    rows = [genuine_review(), {**genuine_review(), 'synthetic': True, 'moderationStatus': 'pending_review'}]
    result = demo.evaluate(demo.SIMULATED_PROFILES['culture'], candidates, rows)
    assert all(row['collaborativeRatingCount'] == 0 and row['popularityScore'] == 50 for row in result)


def test_simulation_cannot_overwrite_genuine_snapshots_or_route_through_normal_generation(generation, client, monkeypatch, penang):
    state, generate = generation
    state['feedback'] = [genuine_review(identity='local_penang_hill', rating=4)]
    original = generate()
    assert original['recommendations'][0]['popularitySource'] == 'genuine_approved_local_reviews'
    saved = deepcopy(state['snapshots'])
    monkeypatch.setattr(demo, 'load_sources', lambda area: deepcopy(penang))
    client.application.config['LOCAL_FYP_SAMPLE_REVIEWS'] = True
    headers = {'Authorization': 'Bearer isolated-token', 'X-TravelMate-Review-Context': 'fyp-v1'}
    response = client.get('/api/fr4/recommendations/demonstration?profileKey=culture', headers=headers)
    assert response.status_code == 200
    assert state['snapshots'] == saved
    generation_id = response.json['recommendationGenerationId']
    assert client.get('/api/fr4/recommendations', query_string={'generationId': generation_id}, headers=headers).status_code == 404
    assert client.post('/api/fr4/recommendations/generate', headers=headers,
                       json={'evidenceMode': 'demonstration'}).status_code == 400
    assert state['snapshots'] == saved
    result = client.get('/api/fr4/recommendations', headers=headers,
                        query_string={'generationId': original['recommendationGenerationId']})
    assert result.status_code == 200 and result.json['demonstrationAvailable']
    assert result.json['recommendations'][0]['popularitySource'] == 'genuine_approved_local_reviews'


def test_missing_demo_data_never_falls_back_to_unmoderated_definition_plan(client, mock_traveller_auth, monkeypatch):
    client.application.config['LOCAL_FYP_SAMPLE_REVIEWS'] = True
    def fail(area):
        raise ValueError('Existing overlay unavailable')
    monkeypatch.setattr(demo, 'load_sources', fail)
    response = client.get('/api/fr4/recommendations/demonstration?profileKey=culture',
        headers={'Authorization': 'Bearer isolated-token', 'X-TravelMate-Review-Context': 'fyp-v1'})
    assert response.status_code == 503
    assert 'No saved recommendations were changed' in response.json['error']


def test_demo_load_uses_existing_moderation_overlay_and_canonical_ids(monkeypatch, penang):
    candidates, rows = penang
    source = {row['destinationId']: row for row in candidates}
    changed = deepcopy(rows)
    for row in changed:
        if row['destinationId'] == 'local_penang_hill':
            row['feedbackStatus'] = 'hidden'
    monkeypatch.setattr(demo, 'private_dataset', lambda: ('isolated-ref', source))
    reader = Mock(return_value=changed)
    monkeypatch.setattr(demo, 'dataset_reviews', reader)
    places, loaded = demo.load_sources('Penang')
    assert {row['destinationId'] for row in places} == set(source)
    assert reader.call_args.args == ('isolated-ref', source)
    approved=approved_contributions(loaded, demonstration=True)['local_penang_hill']
    assert not {row['travellerId'] for row in changed if row['destinationId']=='local_penang_hill'} & {row['travellerId'] for row in approved}
    assert len(approved)==6  # New independently screened contributions do not resurrect hidden old rows.


def test_synthetic_preference_documents_do_not_become_genuine_peer_profiles(generation, monkeypatch):
    state, generate = generation
    state['feedback'] = [genuine_review(identity='local_penang_hill')]
    monkeypatch.setattr(routes, 'retrieveRecordsById', lambda *a: [
        {'id': 'peer', 'synthetic': True, **demo.SIMULATED_PROFILES['culture']}])
    row = generate()['recommendations'][0]
    assert row['collaborativeRatingCount'] == 0
    assert row['collaborativeFallbackReason'] == 'missing_peer_preferences'
    assert row['popularitySource'] == 'genuine_approved_local_reviews'


@pytest.mark.parametrize('rating,count', [(True,10),(float('nan'),10),(6,10),(0,10)])
def test_invalid_provider_ratings_cannot_supply_popularity(rating, count):
    row = score({'destinationId': 'local_kek_lok_si', 'ratingSource': 'provider',
                 'rating': rating, 'reviews': count})
    assert row['popularityScore'] == 50


def test_simulated_summary_cannot_be_used_for_genuine_popularity():
    summary = {'local_kek_lok_si': {'rating': 5, 'reviews': 10000, 'synthetic': True,
                                   'source': 'demonstration_approved_reviews'}}
    row = engine.calculateRecommendationScore([{'destinationId': 'local_kek_lok_si'}], summary)[0]
    assert row['popularityScore'] == 50


def test_demonstration_route_requires_authentication_and_traveller_role(client, mock_operator_auth):
    url = '/api/fr4/recommendations/demonstration'
    assert client.get(url).status_code == 401
    assert client.get(url, headers={'Authorization': 'Bearer isolated-token',
        'X-TravelMate-Review-Context': 'fyp-v1'}).status_code == 403


def test_demo_rejects_unknown_profile_and_area_before_private_reads(client, mock_traveller_auth, monkeypatch):
    client.application.config['LOCAL_FYP_SAMPLE_REVIEWS'] = True
    reader = Mock(side_effect=AssertionError('No data read for invalid request'))
    monkeypatch.setattr(demo, 'load_sources', reader)
    headers = {'Authorization': 'Bearer isolated-token', 'X-TravelMate-Review-Context': 'fyp-v1'}
    for query in ({'profileKey': 'invented'}, {'destinationArea': 'Unverified area'}):
        assert client.get('/api/fr4/recommendations/demonstration', headers=headers, query_string=query).status_code == 400
    assert not reader.called


def test_regional_demo_reuses_existing_identities_and_moderation_reader(monkeypatch):
    identity = 'isolated_johor_attraction'
    place = {'destinationId': identity, 'title': 'Isolated attraction', 'state': 'Johor'}
    monkeypatch.setattr(demo, 'regional_demo_destinations', lambda: {identity: place})
    rows = [{**genuine_review(identity=identity), 'synthetic': True, 'feedbackStatus': 'hidden'}]
    reader = Mock(return_value=rows)
    monkeypatch.setattr(demo, 'regional_demo_reviews', reader)
    monkeypatch.setattr(demo, 'private_dataset', Mock(side_effect=AssertionError('Penang data not needed')))
    places, loaded = demo.load_sources('Johor')
    assert reader.call_args.args == (identity,)
    assert places[0]['destinationId'] == identity
    assert loaded == rows and not approved_contributions(loaded, demonstration=True)[identity]


def test_frozen72_case_mobile_oracle_matches_backend_and_source_definitions():
    import json
    from pathlib import Path
    from scripts.evaluate_penang_review_integration import inputs, evaluate
    fixture = json.loads((Path(__file__).parent / 'fixtures/penang_review_integration_parity.json').read_text(encoding='utf-8'))
    assert fixture['synthetic'] and fixture['input'] == inputs()
    assert fixture['expected'] == evaluate(fixture['input'])['results']
    assert len(fixture['expected']) == 72


def test_provider_popularity_keeps_full_precision_until_final_hybrid_rounding():
    row = score({'destinationId': 'isolated', 'contentScore': 70.02, 'collaborativeScore': 50,
                 'ratingSource': 'provider', 'rating': 4.12345, 'reviews': 67})
    raw_popularity = 4.12345 / 5 * 80 + 67 / 500
    assert row['popularityScore'] == round(raw_popularity, 2)
    assert row['score'] == round(.6 * 70.02 + .3 * 50 + .1 * raw_popularity, 2)


def test_purchase_independent_genuine_snapshot_roundtrip_preserves_exact_review_evidence():
    from services.recommendation_snapshot_storage import write_snapshot, load_snapshot
    row = score({'destinationId': 'local_kek_lok_si'}, [genuine_review()])
    record = {'recommendationGenerationId': 'isolated-generation', 'travellerId': 'isolated-viewer',
              'recommendationEvidenceMode': 'genuine', 'recommendationResults': [row]}
    original = deepcopy(record)
    ref = Mock()
    write_snapshot(None, ref, record)
    stored = ref.set.call_args.args[0]
    assert 'recommendationResults' not in stored  # Existing lossless compressed format.
    assert load_snapshot(ref, stored) == original
    assert record == original
