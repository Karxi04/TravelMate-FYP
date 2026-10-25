from copy import deepcopy
from math import isfinite
from unittest.mock import patch

import pytest

from modules.fr04_hybrid_recommendation.routes import _filter_for_destination
from modules.fr11_chatbot_travel_assistant.nlp_extractor import filter_constraint_candidates
from services.local_catalog import DESTINATIONS
from services.recommendation_taxonomy import candidate_concepts, concepts_for
from sequence_contract.domain_functions import (
    applyCollaborativeFiltering,
    applyContentBasedFiltering,
    calculateRecommendationScore,
    prepareRecommendationInput,
)


CANDIDATES = [
    {'destinationId': 'temple', 'title': 'Kek Lok Si Temple', 'type': 'Temple'},
    {'destinationId': 'food', 'title': 'Local Cuisine', 'type': 'Restaurant'},
    {'destinationId': 'sport', 'title': 'Cycling Centre', 'type': 'Cycling'},
    {'destinationId': 'mixed', 'title': 'Culture and Food', 'type': 'Culture Food'},
    {'destinationId': 'trail', 'title': 'Hiking Trail', 'type': 'Nature Adventure'},
    {'destinationId': 'museum', 'title': 'Heritage Museum', 'type': 'Museum'},
    {'destinationId': 'mall', 'title': 'Shopping Centre', 'type': 'Shopping'},
]


def _scores(interests, candidates=None, **context):
    profile = {'interests': interests, **context}
    content = applyContentBasedFiltering(prepareRecommendationInput(
        profile, deepcopy(CANDIDATES if candidates is None else candidates)))
    combined = applyCollaborativeFiltering(
        content, [], currentPreference=profile, currentTravellerId='offline-user')
    return {item['destinationId']: item for item in calculateRecommendationScore(combined)}


@pytest.mark.parametrize('interests,relevant,unrelated', [
    (['Culture', 'Food'], ['temple', 'food'], ['sport']),
    (['Culture', 'Food', 'Nature', 'Shopping'], ['temple', 'mixed'], ['sport']),
    (['Nature', 'Adventure'], ['trail'], ['museum', 'mall']),
])
def test_controlled_relevance_bounds_hybrid_formula_and_explanations(
        interests, relevant, unrelated):
    output = _scores(interests)
    assert output == _scores(interests)
    for matched in relevant:
        for missed in unrelated:
            assert output[matched]['score'] > output[missed]['score']
    for item in output.values():
        for field in ('contentScore', 'collaborativeScore', 'popularityScore', 'finalScore'):
            assert isfinite(item[field]) and 0 <= item[field] <= 100
        assert item['finalScore'] == pytest.approx(
            .60 * item['contentScore'] + .30 * item['collaborativeScore']
            + .10 * item['popularityScore'], abs=.01)
        for label in item['matchedInterests']:
            assert label in item['recommendationReason']
        if item['destinationId'] in unrelated:
            assert not item['matchedInterests']
            assert 'Matches your' not in item['recommendationReason']


def test_specialist_does_not_require_every_selected_interest():
    narrow = _scores(['Culture'])['temple']
    broad = _scores(['Culture', 'Food', 'Nature', 'Shopping'])['temple']
    assert narrow['contentScore'] == broad['contentScore']
    assert narrow['contentSignals']['interests']['baseScore'] == broad['contentSignals']['interests']['baseScore']
    assert broad['score'] > _scores(['Food'])['temple']['score']


def test_additional_relevant_evidence_is_rewarded_not_unconditional_diversity():
    single = _scores(['Culture'])
    both = _scores(['Culture', 'Food'])
    assert both['mixed']['contentScore'] > single['mixed']['contentScore']
    # A fully compatible specialist need not lose to a broader attraction.
    assert both['mixed']['contentScore'] == both['temple']['contentScore']
    assert single['mixed']['contentScore'] < single['temple']['contentScore']


def test_aliases_duplicates_and_interest_order_cannot_change_scores():
    clean = _scores(['Culture', 'Food'])
    aliases = _scores(['Food', 'Culture', 'Heritage', 'Culture', 'Local Cuisine', 'History'])
    assert clean == aliases


def test_missing_candidate_metadata_is_not_positive_interest_evidence():
    unknown = _scores(['Culture'], [{'destinationId': 'unknown'}])['unknown']
    assert unknown['contentSignals']['interests']['baseScore'] == 0
    assert unknown['matchedInterests'] == []
    assert 'Matches your' not in unknown['recommendationReason']
    no_profile = _scores([], [{'destinationId': 'unknown'}])['unknown']
    assert no_profile['contentSignals']['interests']['applied'] is False


def test_secondary_metadata_remains_weaker_than_primary_evidence():
    output = _scores(['Culture'], [
        {'destinationId': 'direct', 'title': 'Temple'},
        {'destinationId': 'secondary', 'title': 'Visitor Centre', 'tags': ['Temple']},
    ])
    assert output['direct']['contentScore'] > output['secondary']['contentScore']


def test_cold_start_is_distinct_from_actual_negative_peer_feedback():
    profile = {'interests': ['Culture']}
    content = applyContentBasedFiltering(prepareRecommendationInput(profile, CANDIDATES[:1]))
    neutral = applyCollaborativeFiltering(content, [], currentPreference=profile)[0]
    negative = applyCollaborativeFiltering(content, [
        {'destinationId': 'temple', 'travellerId': 'peer', 'rating': 1},
    ], peerPreferences={'peer': profile}, currentPreference=profile)[0]
    assert neutral['collaborativeScore'] == 50
    assert neutral['collaborativeConfidence'] == 0
    assert neutral['collaborativeRatingCount'] == 0
    assert 'no similar traveller evidence' in neutral['collaborativeSource']
    assert negative['collaborativeScore'] < neutral['collaborativeScore']
    assert negative['collaborativeRatingCount'] == 1


def test_explicit_broad_exclusion_cannot_be_overridden_by_interest_or_learning():
    output = _scores(['Culture', 'Food'], excludedInterests=['Culture'],
                     learnedAffinities={'culture': 1})
    assert 'temple' not in output and 'museum' not in output and 'mixed' not in output
    assert 'food' in output


def test_existing_specific_activity_exclusion_keeps_other_culture_candidates():
    candidates = filter_constraint_candidates(CANDIDATES, excluded_activity_types=['Museum'])
    output = _scores(['Culture'], candidates)
    assert 'museum' not in output
    assert 'temple' in output
    assert output['temple']['matchedInterests'] == ['Culture and heritage']


def test_geography_ids_and_source_snapshots_are_unchanged():
    candidates = [
        {**CANDIDATES[0], 'address': 'George Town, Penang, Malaysia'},
        {**CANDIDATES[1], 'address': 'Kuala Lumpur, Malaysia'},
    ]
    original = deepcopy(candidates)
    penang = _scores(['Culture'], _filter_for_destination(candidates, 'Penang'))
    kl = _scores(['Food'], _filter_for_destination(candidates, 'Kuala Lumpur'))
    assert list(penang) == ['temple']
    assert list(kl) == ['food']
    assert penang['temple']['contentSignals']['interests']['baseScore'] == kl['food']['contentSignals']['interests']['baseScore']
    assert candidates == original


def test_representative_catalog_comparison():
    interests = ['Culture', 'Food', 'Nature', 'Shopping']
    requested = concepts_for(interests)
    samples = [item for item in DESTINATIONS if item['destinationId'] in {
        'local_kek_lok_si', 'local_george_town', 'local_penang_hill'}]
    original = deepcopy(samples)
    current = _scores(interests, samples)
    for item in samples:
        supported = candidate_concepts(item)
        coverage = sum(bool(concepts_for(label) & supported) for label in interests) / len(interests)
        primary = bool(concepts_for([item.get('title'), item.get('name'), item.get('type')]) & requested)
        old_base = coverage * (1 if primary else .8)
        scored = current[item['destinationId']]
        new_base = scored['contentSignals']['interests']['baseScore'] / 100
        old_content = round(scored['contentScore'] - 55 * (new_base - old_base), 2)
        old_hybrid = round(.6 * old_content + .3 * scored['collaborativeScore'] + .1 * scored['popularityScore'], 2)
        print(item['destinationId'], 'interest', round(old_base * 100, 2), '->', round(new_base * 100, 2),
              'content', old_content, '->', scored['contentScore'], 'hybrid', old_hybrid, '->', scored['score'])
    assert samples == original
    assert len(samples) == 3


def test_fr04_route_filters_explicit_broad_exclusion_before_snapshot(client, mock_traveller_auth):
    prefix = 'modules.fr04_hybrid_recommendation.routes.'
    pref = {'interests': ['Culture', 'Food'], 'excludedInterests': ['Culture']}
    candidates = [{**item, 'address': 'George Town, Penang, Malaysia'}
                  for item in CANDIDATES[:2]]
    original = deepcopy(candidates)

    def retrieve(collection, document_id=None, **kwargs):
        if collection == 'travel_preferences':
            return pref if document_id else []
        if collection == 'destination_cache':
            return candidates
        return []

    with patch(prefix + 'retrieveRecord', side_effect=retrieve), \
         patch(prefix + 'storeRecord') as store, \
         patch(prefix + 'retrieveDestinationResults', side_effect=AssertionError('No provider calls')):
        response = client.post('/api/fr4/recommendations/generate',
                               headers={'Authorization': 'Bearer valid_test_token'},
                               json={'destinationArea': 'Penang'})
    assert response.status_code == 200
    assert [item['destinationId'] for item in response.json['recommendations']] == ['food']
    snapshots = [call.args[1] for call in store.call_args_list
                 if call.args[0] == 'recommendation_snapshots']
    assert len(snapshots) == 1
    assert [item['destinationId'] for item in snapshots[0]['recommendationResults']] == ['food']
    assert candidates == original
