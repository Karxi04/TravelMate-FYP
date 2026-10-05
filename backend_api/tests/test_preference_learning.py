from copy import deepcopy
from unittest.mock import patch

from services.preference_learning import (
    AFFINITY_MAX,
    AFFINITY_MIN,
    apply_explicit_feedback,
    effective_preference_profile,
    effective_profile_version,
    empty_learning_profile,
    reset_learning_profile,
)
from sequence_contract.domain_functions import (
    applyCollaborativeFiltering,
    applyContentBasedFiltering,
    calculateRecommendationScore,
    prepareRecommendationInput,
)


BASE_PROFILE = {
    'interests': ['Culture'],
    'travelType': 'Culture',
    'travelPace': 'Moderate',
    'travelPurpose': 'Holiday',
    'travelPersonality': 'Explorer',
    'budgetRange': 'Moderate',
    'updatedAt': 'base-v1',
}

FOOD = {
    'destinationId': 'food-market',
    'title': 'Penang Street Food Market',
    'category': 'Street food and hawker centre',
    'rating': 4.5,
    'reviews': 300,
}

SHOPPING = {
    'destinationId': 'shopping-mall',
    'title': 'Penang Shopping Mall',
    'category': 'Shopping retail mall',
    'rating': 4.5,
    'reviews': 300,
}


def _score(candidate, learned=None):
    effective = effective_preference_profile(BASE_PROFILE, learned)
    content = applyContentBasedFiltering(prepareRecommendationInput(
        effective, [candidate], []))
    collaborative = applyCollaborativeFiltering(
        content, [], peerPreferences={}, currentPreference=BASE_PROFILE)
    return calculateRecommendationScore(collaborative)[0]


def test_new_user_has_no_learned_preference_and_base_is_unchanged():
    original = deepcopy(BASE_PROFILE)
    effective = effective_preference_profile(BASE_PROFILE, None)

    assert effective['learnedAffinities'] == {}
    assert effective['learnedEvidence'] == {}
    assert BASE_PROFILE == original
    assert effective_profile_version('base-v1', None) == 'base-v1'


def test_positive_negative_and_reversal_are_deterministic():
    profile = empty_learning_profile('traveller-1', now='t0')
    profile, first, changed = apply_explicit_feedback(
        profile,
        user_id='traveller-1',
        destination_id='food-market',
        feedback_type='more_like_this',
        destination_concepts=['food'],
        now='t1',
        event_id='event-1',
    )
    assert changed is True
    assert profile['affinities']['food'] == 0.15
    assert first['previousFeedbackType'] == ''

    unchanged, duplicate_event, changed = apply_explicit_feedback(
        profile,
        user_id='traveller-1',
        destination_id='food-market',
        feedback_type='more_like_this',
        destination_concepts=['food'],
        now='t2',
        event_id='event-duplicate',
    )
    assert changed is False
    assert duplicate_event is None
    assert unchanged == profile

    reversed_profile, reversal, changed = apply_explicit_feedback(
        profile,
        user_id='traveller-1',
        destination_id='food-market',
        feedback_type='not_for_me',
        destination_concepts=['food'],
        now='t3',
        event_id='event-2',
    )
    assert changed is True
    assert reversed_profile['affinities']['food'] == -0.12
    assert reversal['previousFeedbackType'] == 'more_like_this'
    assert reversal['supersedesEventId'] == 'event-1'


def test_repeated_feedback_across_destinations_remains_bounded():
    positive = empty_learning_profile('traveller-1', now='t0')
    negative = empty_learning_profile('traveller-1', now='t0')
    for index in range(20):
        positive, _, _ = apply_explicit_feedback(
            positive,
            user_id='traveller-1',
            destination_id=f'food-{index}',
            feedback_type='more_like_this',
            destination_concepts=['food'],
            now=f'p{index}',
            event_id=f'positive-{index}',
        )
        negative, _, _ = apply_explicit_feedback(
            negative,
            user_id='traveller-1',
            destination_id=f'shop-{index}',
            feedback_type='not_for_me',
            destination_concepts=['shopping'],
            now=f'n{index}',
            event_id=f'negative-{index}',
        )

    assert positive['affinities']['food'] == AFFINITY_MAX
    assert negative['affinities']['shopping'] == AFFINITY_MIN


def test_learning_adjusts_interest_component_without_changing_60_30_10():
    baseline_food = _score(FOOD)
    baseline_shopping = _score(SHOPPING)
    learned = {
        'affinities': {'food': 0.75, 'shopping': -0.60},
        'evidence': {
            'food': {'positiveCount': 5, 'negativeCount': 0},
            'shopping': {'positiveCount': 0, 'negativeCount': 5},
        },
        'learnedPreferenceVersion': 'learned-v1',
    }
    learned_food = _score(FOOD, learned)
    learned_shopping = _score(SHOPPING, learned)

    assert learned_food['contentScore'] > baseline_food['contentScore']
    assert learned_food['finalScore'] > baseline_food['finalScore']
    assert learned_shopping['contentScore'] < baseline_shopping['contentScore']
    assert learned_shopping['finalScore'] < baseline_shopping['finalScore']
    assert learned_shopping['finalScore'] > 0
    assert learned_food['scoreBreakdown']['contentWeight'] == 0.60
    assert learned_food['scoreBreakdown']['collaborativeWeight'] == 0.30
    assert learned_food['scoreBreakdown']['popularityWeight'] == 0.10
    assert any('recent interest in food' in reason.lower()
               for reason in learned_food['matchReasons'])


def test_learning_changes_effective_version_and_reset_preserves_base():
    base_copy = deepcopy(BASE_PROFILE)
    learned = {
        'learnedPreferenceVersion': 'learned-v1',
        'affinities': {'food': 0.15},
        'feedbackByDestination': {'food': {'feedbackType': 'more_like_this'}},
    }
    version = effective_profile_version('base-v1', learned)
    reset, event, changed = reset_learning_profile(
        learned, user_id='traveller-1', now='reset-time', event_id='reset-1')

    assert version != 'base-v1'
    assert reset['affinities'] == {}
    assert reset['feedbackByDestination'] == {}
    assert effective_profile_version('base-v1', reset) != version
    assert event['feedbackType'] == 'reset'
    assert changed is True
    assert BASE_PROFILE == base_copy


def test_feedback_route_uses_snapshot_concepts_without_mutating_snapshot(
        client, mock_traveller_auth):
    snapshot = {
        'recommendationGenerationId': 'snapshot-1',
        'travellerId': 'test_traveller_uid',
        'recommendationResults': [{
            'destinationId': 'food-market',
            'destinationConcepts': ['food', 'social'],
            'title': 'Food Market',
        }],
    }
    original_snapshot = deepcopy(snapshot)

    with patch(
        'modules.fr04_hybrid_recommendation.routes.retrieveRecord'
    ) as retrieve, patch(
        'modules.fr04_hybrid_recommendation.routes.storeRecord'
    ) as store:
        def fake_retrieve(collection, document_id=None, **_):
            if collection == 'recommendation_snapshots':
                return snapshot
            if collection == 'learned_preference_profiles':
                return None
            return None

        retrieve.side_effect = fake_retrieve
        response = client.post(
            '/api/fr4/preference-feedback',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={
                'destinationId': 'food-market',
                'recommendationGenerationId': 'snapshot-1',
                'feedbackType': 'more_like_this',
                'sourceContext': 'for_you',
            },
        )

    assert response.status_code == 200
    data = response.get_json()
    assert data['learning']['currentFeedback']['food-market'] == 'more_like_this'
    assert 'affinities' not in data['learning']
    assert snapshot == original_snapshot
    collections = [call.args[0] for call in store.call_args_list]
    assert collections == [
        'learned_preference_profiles',
        'recommendation_feedback_events',
    ]
    saved_profile = store.call_args_list[0].args[1]
    assert saved_profile['affinities']['food'] == 0.15


def test_feedback_snapshot_mismatch_remains_protected(
        client, mock_traveller_auth):
    with patch(
        'modules.fr04_hybrid_recommendation.routes.retrieveRecord',
        return_value={
            'travellerId': 'test_traveller_uid',
            'recommendationResults': [],
        },
    ):
        response = client.post(
            '/api/fr4/preference-feedback',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={
                'destinationId': 'other-place',
                'recommendationGenerationId': 'snapshot-1',
                'feedbackType': 'not_for_me',
            },
        )

    assert response.status_code == 409


def test_reset_route_only_writes_learning_collections(
        client, mock_traveller_auth):
    current = {
        'travellerId': 'test_traveller_uid',
        'affinities': {'food': 0.3},
        'feedbackByDestination': {
            'food-market': {'feedbackType': 'more_like_this'}
        },
        'learnedPreferenceVersion': 'learned-v1',
    }
    with patch(
        'modules.fr04_hybrid_recommendation.routes.retrieveRecord',
        return_value=current,
    ), patch(
        'modules.fr04_hybrid_recommendation.routes.storeRecord'
    ) as store:
        response = client.delete(
            '/api/fr4/preference-feedback',
            headers={'Authorization': 'Bearer valid_test_token'},
        )

    assert response.status_code == 200
    assert response.get_json()['learning']['hasLearnedPreferences'] is False
    assert {call.args[0] for call in store.call_args_list} == {
        'learned_preference_profiles',
        'recommendation_feedback_events',
    }


def test_next_generation_uses_learned_version_and_keeps_old_snapshot_immutable(
        client, mock_traveller_auth):
    base = deepcopy(BASE_PROFILE)
    learned = {
        'travellerId': 'test_traveller_uid',
        'affinities': {'food': 0.45},
        'evidence': {'food': {'positiveCount': 3, 'negativeCount': 0}},
        'learnedPreferenceVersion': 'learned-v-next',
    }
    old_snapshot = {
        'recommendationGenerationId': 'old-snapshot',
        'preferenceProfileVersion': 'base-v1',
        'recommendationResults': [{'destinationId': 'old-place'}],
    }
    original_old_snapshot = deepcopy(old_snapshot)

    def fake_retrieve(collection, document_id=None, **_):
        if collection == 'travel_preferences' and document_id:
            return base
        if collection == 'travel_preferences':
            return [base]
        if collection == 'learned_preference_profiles':
            return learned
        if collection == 'feedback':
            return []
        if collection in {'destination_cache', 'admin_destinations'}:
            return []
        return None

    with patch.dict('os.environ', {'FALLBACK_MODE': 'true'}), patch(
        'modules.fr04_hybrid_recommendation.routes.retrieveRecord',
        side_effect=fake_retrieve,
    ), patch(
        'modules.fr04_hybrid_recommendation.routes.storeRecord',
    ) as store:
        response = client.post(
            '/api/fr4/recommendations/generate',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'destinationArea': 'Penang, Malaysia'},
        )

    assert response.status_code == 200
    snapshot = next(
        call.args[1] for call in store.call_args_list
        if call.args[0] == 'recommendation_snapshots'
    )
    assert snapshot['preferenceProfileVersion'] == effective_profile_version(
        'base-v1', learned)
    assert snapshot['preferenceProfileVersion'] != old_snapshot[
        'preferenceProfileVersion']
    assert any(
        'recent interest in food' in reason.lower()
        for item in snapshot['recommendationResults']
        for reason in item.get('matchReasons', [])
    )
    assert old_snapshot == original_old_snapshot
    assert base == BASE_PROFILE
