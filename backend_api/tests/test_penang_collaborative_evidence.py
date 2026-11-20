"""Penang CF regressions: synthetic authentication/storage, no live services."""
from copy import deepcopy

import pytest

from sequence_contract.domain_functions import applyCollaborativeFiltering
from services.local_catalog import DESTINATIONS
from services.review_destination import review_destination_ids
from modules.fr04_hybrid_recommendation import routes
from scripts.evaluate_penang_collaborative import evaluate, load_fixture, qualifying_projection
from sequence_contract import firebase_firestore as persistence
from types import SimpleNamespace

PROFILE = {'interests': ['Culture', 'Photography'], 'travelType': 'Culture',
           'travelPace': 'Relaxed', 'travelPurpose': 'Holiday', 'travelPersonality': 'Planner'}
PLACES = ['local_kek_lok_si', 'local_penang_hill', 'demo_penang_street_art',
          'local_peranakan_mansion', 'local_chew_jetty', 'local_botanical_gardens']


@pytest.mark.parametrize('identity', PLACES)
def test_confirmed_review_aliases_join_the_candidate_in_both_directions(identity):
    alias = review_destination_ids(identity)[-1]
    for candidate, review in [(identity, alias), (alias, identity)]:
        result = applyCollaborativeFiltering([{'destinationId': candidate}],
            [{'travellerId': 'peer', 'destinationId': review, 'rating': 5}],
            {'peer': PROFILE}, PROFILE, 'viewer')[0]
        assert result['collaborativeRatingCount'] == 1
        assert result['collaborativeConfidence'] == pytest.approx(1 / 3, abs=.001)
        assert result['collaborativeScore'] == pytest.approx(66.67)


def test_alias_duplicates_use_only_the_latest_contribution_from_one_peer():
    rows = [{'id': 'old', 'travellerId': 'peer', 'destinationId': 'penang_hill',
             'rating': 5, 'updatedAt': '2026-01-01'},
            {'id': 'new', 'travellerId': 'peer', 'destinationId': 'local_penang_hill',
             'rating': 1, 'updatedAt': '2026-02-01'}]
    before = deepcopy(rows)
    result = applyCollaborativeFiltering([{'destinationId': 'penang_hill'}], rows,
        {'peer': PROFILE}, PROFILE, 'viewer')[0]
    assert result['collaborativeRatingCount'] == 1
    assert result['rawCollaborativeScore'] == 20
    assert result['collaborativeScore'] == 40
    assert rows == before


def test_missing_peer_profile_is_explained_without_fabricating_preferences():
    result = applyCollaborativeFiltering([{'destinationId': 'local_penang_hill'}],
        [{'travellerId': 'peer', 'destinationId': 'local_penang_hill', 'rating': 5}],
        {}, PROFILE, 'viewer')[0]
    assert result['collaborativeScore'] == 50 and result['collaborativeConfidence'] == 0
    assert result['collaborativeFallbackReason'] == 'missing_peer_preferences'
    assert result['collaborativeMissingProfileCount'] == 1


@pytest.fixture
def generation(client, mock_traveller_auth, monkeypatch):
    state = {'feedback': [], 'snapshots': {}, 'calls': [], 'scanProfiles': []}
    def retrieve(collection, identity=None, **kwargs):
        state['calls'].append((collection, identity, kwargs))
        if collection == 'travel_preferences':
            return deepcopy(PROFILE) if identity else state['scanProfiles']
        if collection == 'feedback':
            return deepcopy(state['feedback'])
        if collection == 'recommendation_snapshots':
            return deepcopy(state['snapshots'].get(identity))
        return None if identity else []
    def store(collection, record, identity=None, **kwargs):
        assert collection == 'recommendation_snapshots'
        state['snapshots'][identity] = deepcopy(record)
        return {'id': identity, **deepcopy(record)}
    monkeypatch.setenv('FALLBACK_MODE', 'true')
    monkeypatch.setenv('SERPAPI_KEY', '')
    monkeypatch.setattr(routes, 'retrieveRecord', retrieve)
    def retrieve_profiles(collection, identities):
        return [{'id': uid, **routes.retrieveRecord(collection, uid)} for uid in sorted(identities)]
    monkeypatch.setattr(routes, 'retrieveRecordsById', retrieve_profiles)
    monkeypatch.setattr(routes, 'storeRecord', store)
    monkeypatch.setattr(routes, 'DESTINATIONS', [x for x in DESTINATIONS
        if x['destinationId'] == 'local_penang_hill'])
    def generate():
        response = client.post('/api/fr4/recommendations/generate',
            headers={'Authorization': 'Bearer isolated-token'},
            json={'destinationArea': 'Penang'})
        assert response.status_code == 200, response.json
        return response.json
    return state, generate


def approved(**patch):
    return {'id': 'review', 'travellerId': 'peer', 'destinationId': 'penang_hill',
            'rating': 5, 'feedbackStatus': 'visible', 'moderationStatus': 'approved', **patch}


def test_generation_loads_the_actual_reviewers_profile_without_a_truncated_profile_scan(generation):
    state, generate = generation
    state['feedback'] = [approved()]
    result = generate()['recommendations'][0]
    assert result['collaborativeRatingCount'] == 1
    assert result['collaborativeScore'] > 50
    assert ('travel_preferences', 'peer', {}) in state['calls']
    assert ('feedback', None, {'limit': 500}) in state['calls']
    assert not any(c == 'travel_preferences' and identity is None for c, identity, _ in state['calls'])


def test_new_hidden_review_cannot_resurrect_older_approved_alias(generation):
    state, generate = generation
    state['scanProfiles'] = [{'id': 'peer', **PROFILE}]
    state['feedback'] = [approved(destinationId='local_penang_hill', updatedAt='2026-01-01'),
        approved(id='latest', destinationId='penang_hill',
                 updatedAt='2026-02-01', feedbackStatus='hidden')]
    before = deepcopy(state['feedback'])
    result = generate()['recommendations'][0]
    assert result['collaborativeRatingCount'] == 0
    assert result['collaborativeConfidence'] == 0
    assert state['feedback'] == before


def test_existing_generation_is_immutable_and_get_does_not_recompute_peer_scores(generation, client):
    state, generate = generation
    first = generate()
    generation_id = first['recommendationGenerationId']
    saved = deepcopy(state['snapshots'][generation_id])
    state['feedback'] = [approved()]
    second = generate()
    assert second['recommendations'][0]['collaborativeScore'] > 50
    state['calls'].clear()
    response = client.get('/api/fr4/recommendations',
        query_string={'generationId': generation_id},
        headers={'Authorization': 'Bearer isolated-token'})
    assert response.status_code == 200
    assert response.json['snapshot']['recommendationResults'][0]['collaborativeScore'] == 50
    assert state['snapshots'][generation_id] == saved
    assert not any(c == 'feedback' for c, _, _ in state['calls'])
    assert all(identity == 'test_traveller_uid' for c, identity, _ in state['calls']
               if c == 'travel_preferences')  # Own profile is read only to flag stale preferences.


@pytest.mark.parametrize('marker', [{'synthetic': True}, {'source': 'fyp_private'},
                                   {'source': ' SAMPLE '}, {'fypPreview': True}])
def test_private_or_synthetic_markers_never_become_peer_evidence(marker):
    result = applyCollaborativeFiltering([{'destinationId': 'local_penang_hill'}],
        [approved(destinationId='local_penang_hill', **marker)], {'peer': PROFILE}, PROFILE, 'viewer')[0]
    assert result['collaborativeScore'] == 50 and result['collaborativeRatingCount'] == 0


def test_true_evidence_backed_fifty_has_nonzero_confidence():
    rows = [approved(travellerId='p1', rating=2), approved(travellerId='p2', rating=3)]
    result = applyCollaborativeFiltering([{'destinationId': 'penang_hill'}], rows,
        {'p1': PROFILE, 'p2': PROFILE}, PROFILE, 'viewer')[0]
    assert result['rawCollaborativeScore'] == result['collaborativeScore'] == 50
    assert result['collaborativeRatingCount'] == 2 and result['collaborativeConfidence'] == .667
    assert result['collaborativeEvidenceStatus'] == 'peer_ratings'
    assert result['collaborativeFallbackReason'] is None


def test_single_peer_is_enough_but_dissimilar_peers_are_not_filler():
    dissimilar = {'interests': ['Shopping'], 'travelType': 'Shopping', 'travelPace': 'Packed',
                  'travelPurpose': 'Business', 'travelPersonality': 'Social'}
    result = applyCollaborativeFiltering([{'destinationId': 'penang_hill'}], [approved()],
        {'peer': dissimilar}, PROFILE, 'viewer')[0]
    assert result['collaborativeRatingCount'] == 0
    assert result['collaborativeDissimilarPeerCount'] == 1
    assert result['collaborativeFallbackReason'] == 'no_similar_peers'


def test_frozen_benchmark_has_fifty_distinct_marked_contributions_and_no_import_path():
    fixture = load_fixture()
    assert fixture['synthetic'] and len(fixture['ratingContributions']) == 50
    assert len(fixture['peerPreferences']) == 10
    assert len({(r['travellerId'], r['destinationId']) for r in fixture['ratingContributions']}) == 50
    before = deepcopy(fixture)
    assert len(qualifying_projection(fixture)) == 50
    result = evaluate()
    assert fixture == before
    assert result['fixtureSha256'] == 'ad9e3be07193dec08a56ded40ddbc91feba9850636e674920523423b4db14c0e'
    for row in result['results']:
        if row['mode'] in {'cold_start', 'synthetic_as_stored'}:
            assert row['eligiblePeers'] == 0 and row['confidence'] == 0
            assert row['collaborativeScore'] == 50
        else:
            assert row['eligiblePeers'] > 0 and row['confidence'] > 0
            assert abs(row['hybridScore'] - (.6*70 + .3*row['collaborativeScore'] + .1*50)) < .02
    culture = {r['destinationId']: r for r in result['results'] if
        r['mode'] == 'qualifying_counterfactual' and r['profile'] == 'culture_photography'}
    assert culture['local_penang_hill']['collaborativeScore'] == 68.33
    assert culture['local_botanical_gardens']['collaborativeScore'] == 47.5
    assert culture['demo_penang_street_art']['eligiblePeers'] == 3
    nature = {r['destinationId']: r['collaborativeScore'] for r in result['results'] if
        r['mode'] == 'qualifying_counterfactual' and r['profile'] == 'nature_adventure'}
    assert nature['local_botanical_gardens'] > culture['local_botanical_gardens']['collaborativeScore']
    assert nature['local_peranakan_mansion'] < culture['local_peranakan_mansion']['collaborativeScore']


def test_foreign_profile_identity_cannot_be_attached_to_a_reviewer(generation, monkeypatch):
    state, generate = generation
    state['feedback'] = [approved()]
    retrieve = routes.retrieveRecord
    def foreign(collection, identity=None, **kwargs):
        if collection == 'travel_preferences' and identity == 'peer':
            return {'travellerId': 'foreign', **PROFILE}
        return retrieve(collection, identity, **kwargs)
    monkeypatch.setattr(routes, 'retrieveRecord', foreign)
    row = generate()['recommendations'][0]
    assert row['collaborativeRatingCount'] == 0
    assert row['collaborativeFallbackReason'] == 'missing_peer_preferences'


def test_profile_batch_is_scoped_deduplicated_and_skips_missing_documents(monkeypatch):
    calls = []
    class Database:
        def collection(self, name):
            assert name == 'travel_preferences'
            return SimpleNamespace(document=lambda identity: identity)
        def get_all(self, references):
            calls.append(references)
            return [SimpleNamespace(id='peer', exists=True, to_dict=lambda: {'interests': ['Culture']}),
                    SimpleNamespace(id='missing', exists=False)]
    monkeypatch.setattr(persistence, 'get_db', lambda: Database())
    assert persistence.retrieveRecordsById('travel_preferences', []) == []
    assert not calls
    records = persistence.retrieveRecordsById('travel_preferences', ['peer', 'missing', 'peer'])
    assert calls == [['missing', 'peer']]
    assert records == [{'id': 'peer', 'interests': ['Culture']}]
