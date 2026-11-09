import pytest
from unittest.mock import patch

from modules.fr04_hybrid_recommendation.routes import (
    _filter_for_destination,
    _provider_destinations,
)
from services.malaysian_locality import (
    normalize_destination_scope,
    validate_candidate,
)
from services.serpapi_service import retrieveDestinationResults
from services.recommendation_taxonomy import concepts_for
from sequence_contract.domain_functions import (
    applyCollaborativeFiltering,
    applyContentBasedFiltering,
    calculateRecommendationScore,
    deduplicateRecommendations,
    diversifyRecommendations,
    prepareRecommendationInput,
    rankRecommendations,
)


PERSONALISATION_CANDIDATES = [
    {
        'destinationId': 'food_market',
        'title': 'Penang Street Food Market',
        'category': 'Hawker centre and local cuisine',
        'interests': ['Street Food', 'Cafe'],
        'budgetLevel': 'Budget',
        'pace': ['Relaxed', 'Moderate'],
        'purpose': ['Holiday', 'Solo travel'],
        'personality': ['Social', 'Relaxed'],
        'rating': 4.4,
        'reviews': 400,
    },
    {
        'destinationId': 'heritage_museum',
        'title': 'Penang Heritage Museum',
        'category': 'Historic museum and architecture',
        'interests': ['Culture', 'Heritage', 'History'],
        'budgetLevel': 'Moderate',
        'pace': ['Relaxed', 'Moderate'],
        'purpose': ['Educational trip', 'Holiday'],
        'personality': ['Planner', 'Explorer'],
        'rating': 4.4,
        'reviews': 400,
    },
    {
        'destinationId': 'nature_trail',
        'title': 'Penang Forest Adventure Trail',
        'category': 'Hiking and outdoor activity',
        'interests': ['Nature', 'Adventure', 'Hiking'],
        'budgetLevel': 'Moderate',
        'pace': ['Packed', 'Active'],
        'purpose': ['Holiday', 'Solo travel'],
        'personality': ['Explorer'],
        'rating': 4.4,
        'reviews': 400,
    },
    {
        'destinationId': 'shopping_mall',
        'title': 'Penang Leisure Mall',
        'category': 'Shopping retail and entertainment',
        'interests': ['Shopping', 'Leisure'],
        'budgetLevel': 'Moderate',
        'pace': ['Relaxed'],
        'purpose': ['Holiday', 'Family trip'],
        'personality': ['Social', 'Relaxed'],
        'rating': 4.4,
        'reviews': 400,
    },
]


def _rank_profile(interests, travel_type, pace='Moderate', purpose='Holiday',
                  personality='Balanced', budget='Moderate'):
    preference = {
        'interests': interests,
        'travelType': travel_type,
        'travelPace': pace,
        'travelPurpose': purpose,
        'travelPersonality': personality,
        'budgetRange': budget,
    }
    content = applyContentBasedFiltering(prepareRecommendationInput(
        preference, PERSONALISATION_CANDIDATES, []))
    collaborative = applyCollaborativeFiltering(
        content, [], peerPreferences={}, currentPreference=preference)
    return diversifyRecommendations(
        rankRecommendations(deduplicateRecommendations(
            calculateRecommendationScore(collaborative))),
        preference,
    )


def test_provider_destinations_assigns_raw_before_normalising():
    with patch(
        'modules.fr04_hybrid_recommendation.routes.retrieveDestinationResults',
        return_value={
            'local_results': [{
                'place_id': 'penang_1',
                'title': 'Penang Hill',
                'address': 'Air Itam, Penang, Malaysia',
                'type': 'Tourist attraction',
            }]
        },
    ):
        items = _provider_destinations('attractions', 'Penang')

    assert items == [{
        'place_id': 'penang_1',
        'title': 'Penang Hill',
        'address': 'Air Itam, Penang, Malaysia',
        'type': 'Tourist attraction',
        'destinationId': 'penang_1',
        'category': 'Tourist attraction',
        'description': 'Tourist attraction',
    }]


def test_destination_filter_rejects_other_areas():
    candidates = [
        {'destinationId': 'penang', 'title': 'Penang Hill', 'address': 'Penang, Malaysia'},
        {'destinationId': 'kl', 'title': 'KLCC Park', 'address': 'Kuala Lumpur, Malaysia'},
        {'destinationId': 'unknown', 'title': 'Popular Attraction', 'address': ''},
    ]

    filtered = _filter_for_destination(candidates, 'Penang, Malaysia')

    assert [item['destinationId'] for item in filtered] == ['penang']


@pytest.mark.parametrize('locality', [
    'George Town',
    'Batu Ferringhi',
    'Bayan Lepas',
    'Tanjung Bungah',
    'Butterworth',
    'Bukit Mertajam',
])
def test_penang_state_accepts_island_and_mainland_localities(locality):
    eligible, candidate = validate_candidate(
        {'destinationId': locality, 'address': f'{locality}, Malaysia'},
        normalize_destination_scope('Penang, Malaysia'),
    )

    assert eligible is True
    assert candidate['normalizedGeography']['state'] == 'Penang'


@pytest.mark.parametrize('locality,state', [
    ('Kuala Lumpur', 'Kuala Lumpur'),
    ('Petaling Jaya', 'Selangor'),
    ('Shah Alam', 'Selangor'),
    ('Ipoh', 'Perak'),
    ('Johor Bahru', 'Johor'),
    ('Alor Setar', 'Kedah'),
])
def test_penang_state_rejects_other_malaysian_localities(locality, state):
    eligible, candidate = validate_candidate(
        {'destinationId': locality, 'address': f'{locality}, {state}, Malaysia'},
        normalize_destination_scope('Pulau Pinang'),
    )

    assert eligible is False
    assert candidate['geographicEligibility']['reason'] == 'state_out_of_scope'


def test_penang_and_provider_aliases_normalize_canonically():
    penang = normalize_destination_scope('Pulau Pinang')
    georgetown = normalize_destination_scope('Georgetown')

    assert penang['scopeKey'] == 'my:penang'
    assert penang['canonicalName'] == 'Penang, Malaysia'
    assert georgetown['state'] == 'Penang'
    assert georgetown['city'] == 'George Town'


def test_missing_misleading_and_coordinate_conflict_are_rejected():
    scope = normalize_destination_scope('Penang')
    missing, missing_item = validate_candidate(
        {'title': 'Popular Attraction'}, scope)
    misleading, misleading_item = validate_candidate({
        'title': 'Penang Seafood Restaurant',
        'address': 'Kuala Lumpur, Malaysia',
    }, scope)
    conflict, conflict_item = validate_candidate({
        'title': 'Penang Museum',
        'address': 'George Town, Penang, Malaysia',
        'gps_coordinates': {'latitude': 3.1579, 'longitude': 101.7116},
    }, scope)

    assert missing is False
    assert missing_item['geographicEligibility']['reason'] == 'unresolved_candidate_geography'
    assert misleading is False
    assert misleading_item['normalizedGeography']['state'] == 'Kuala Lumpur'
    assert conflict is False
    assert conflict_item['normalizedGeography']['evidence'] == 'coordinates'
    assert conflict_item['normalizedGeography']['state'] == 'Kuala Lumpur'
    assert conflict_item['normalizedGeography']['conflict'] is True


def test_provider_query_uses_canonical_scope_and_coordinates():
    with patch('services.serpapi_service._request', return_value={'local_results': []}) as request_mock:
        retrieveDestinationResults(
            'food attractions',
            'Penang, Malaysia',
            {'latitude': 5.4141, 'longitude': 100.3288},
        )

    params = request_mock.call_args.args[0]
    assert params['q'] == 'food attractions in Penang, Malaysia'
    assert params['gl'] == 'my'
    assert params['ll'] == '@5.4141,100.3288,11z'

def test_generate_recommendations_without_preferences(client, mock_traveller_auth):
    with patch('modules.fr04_hybrid_recommendation.routes.retrieveRecord') as mock_retrieve:
        mock_retrieve.return_value = None
        res = client.post(
            '/api/fr4/recommendations/generate',
            headers={'Authorization': 'Bearer valid_test_token'}
        )
        assert res.status_code == 400
        assert 'Complete travel preferences first' in res.get_json()['error']

def test_generate_recommendations_success(client, mock_traveller_auth):
    sample_pref = {
        'interests': ['Culture', 'Heritage'],
        'travelType': 'Culture',
        'travelPurpose': 'Holiday',
        'travelPersonality': 'Explorer',
        'travelPace': 'Moderate',
        'budgetRange': 'Moderate'
    }
    with patch.dict('os.environ', {'FALLBACK_MODE': 'true'}), \
         patch('modules.fr04_hybrid_recommendation.routes.retrieveRecord') as mock_retrieve, \
         patch('modules.fr04_hybrid_recommendation.routes.storeRecord') as mock_store:
        def fake_retrieve(coll, doc_id=None, limit=None, filters=None):
            if coll == 'travel_preferences' and doc_id == 'test_traveller_uid':
                return sample_pref
            if coll == 'travel_preferences':
                return [sample_pref]
            if coll == 'destination_cache':
                return None
            if coll == 'admin_destinations':
                return []
            if coll == 'feedback':
                return []
            return None

        mock_retrieve.side_effect = fake_retrieve
        mock_store.return_value = {'id': 'test_traveller_uid'}

        res = client.post(
            '/api/fr4/recommendations/generate',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'destinationArea': 'Penang, Malaysia'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert len(data['recommendations']) > 0
        assert data['recommendations'][0]['rankNo'] == 1
        assert 'scoreBreakdown' in data['recommendations'][0]
        assert data['source'] == 'fallback'
        assert data['recommendationGenerationId']
        assert all(
            item['normalizedGeography']['state'] == 'Penang'
            for item in data['recommendations']
        )
        assert data['engine']['weightedScoring'] == {
            'content': 0.60,
            'collaborative': 0.30,
            'popularity': 0.10,
        }

        snapshot_calls = [
            call for call in mock_store.call_args_list
            if call.args and call.args[0] == 'recommendation_snapshots'
        ]
        assert len(snapshot_calls) == 1
        snapshot = snapshot_calls[0].args[1]
        assert snapshot_calls[0].args[2] == data['recommendationGenerationId']
        assert snapshot['recommendationGenerationId'] == data['recommendationGenerationId']
        assert snapshot['userId'] == 'test_traveller_uid'
        assert snapshot['travellerId'] == 'test_traveller_uid'
        assert snapshot['requestedDestination'] == 'Penang, Malaysia'
        assert snapshot['preferenceProfileVersion']
        assert snapshot['generatedAt']
        assert snapshot['recommendationResults'] == data['recommendations']
        first = snapshot['recommendationResults'][0]
        assert first['recommendationSource'] == 'fallback'
        assert first['contentScore'] == first['scoreBreakdown']['content']
        assert first['collaborativeScore'] == first['scoreBreakdown']['collaborative']
        assert first['popularityScore'] == first['scoreBreakdown']['popularity']
        assert first['finalScore'] == first['score']
        assert first['recommendationReason'] == first['reason']
        assert all(
            not call.args or call.args[0] != 'recommendations'
            for call in mock_store.call_args_list
        )


def test_live_provider_results_are_scoped_and_marked(client, mock_traveller_auth):
    sample_pref = {
        'interests': ['Nature'],
        'travelType': 'Nature',
        'travelPurpose': 'Holiday',
        'travelPersonality': 'Explorer',
        'travelPace': 'Moderate',
        'budgetRange': 'Moderate',
        'updatedAt': '2026-10-03T10:00:00+00:00',
    }

    def fake_retrieve(collection, document_id=None, limit=None, filters=None):
        if collection == 'travel_preferences' and document_id:
            return sample_pref
        if collection == 'travel_preferences':
            return [sample_pref]
        if collection == 'feedback':
            return []
        if collection == 'destination_cache':
            return []
        return []

    provider_result = {
        'local_results': [
            {
                'place_id': 'penang_hill',
                'title': 'Penang Hill',
                'address': 'Air Itam, Penang, Malaysia',
                'type': 'Nature',
                'rating': 4.7,
                'reviews': 1000,
            },
            {
                'place_id': 'klcc',
                'title': 'KLCC Park',
                'address': 'Kuala Lumpur, Malaysia',
                'type': 'Nature',
                'rating': 4.7,
                'reviews': 1000,
            },
        ]
    }
    with patch.dict('os.environ', {'SERPAPI_KEY': 'configured', 'FALLBACK_MODE': 'true'}), \
         patch('modules.fr04_hybrid_recommendation.routes.retrieveRecord', side_effect=fake_retrieve), \
         patch('modules.fr04_hybrid_recommendation.routes.retrieveDestinationResults', return_value=provider_result), \
         patch('modules.fr04_hybrid_recommendation.routes.storeRecord') as mock_store:
        response = client.post(
            '/api/fr4/recommendations/generate',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'destinationArea': 'Penang, Malaysia'},
        )

    assert response.status_code == 200
    data = response.get_json()
    assert data['source'] == 'live_provider'
    assert [item['destinationId'] for item in data['recommendations']] == ['penang_hill']
    assert data['recommendations'][0]['recommendationSource'] == 'live_provider'
    cached_ids = [
        call.args[2] for call in mock_store.call_args_list
        if call.args and call.args[0] == 'destination_cache'
    ]
    assert cached_ids == ['penang_hill']
    cache_write = next(
        call.args[1] for call in mock_store.call_args_list
        if call.args and call.args[0] == 'destination_cache'
    )
    assert cache_write['canonicalDestinationScope'] == 'my:penang'
    assert cache_write['canonicalDestinationName'] == 'Penang, Malaysia'


def test_cache_is_queried_by_canonical_destination_scope(client, mock_traveller_auth):
    sample_pref = {'interests': ['Culture'], 'travelType': 'Culture'}
    observed_filters = []

    def fake_retrieve(collection, document_id=None, limit=None, filters=None):
        if collection == 'travel_preferences' and document_id:
            return sample_pref
        if collection == 'travel_preferences':
            return [sample_pref]
        if collection == 'feedback':
            return []
        if collection == 'destination_cache':
            observed_filters.extend(filters or [])
            return [{
                'destinationId': 'cached_georgetown',
                'title': 'Khoo Kongsi',
                'address': 'George Town, Malaysia',
                'type': 'Culture',
                'rating': 4.6,
                'reviews': 500,
                'canonicalDestinationScope': 'my:penang',
            }]
        return []

    with patch.dict('os.environ', {'SERPAPI_KEY': '', 'FALLBACK_MODE': 'false'}), \
         patch('modules.fr04_hybrid_recommendation.routes.retrieveRecord', side_effect=fake_retrieve), \
         patch('modules.fr04_hybrid_recommendation.routes.storeRecord'):
        response = client.post(
            '/api/fr4/recommendations/generate',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'destinationArea': 'Pulau Pinang'},
        )

    assert response.status_code == 200
    assert response.get_json()['source'] == 'cache'
    assert observed_filters == [('canonicalDestinationScope', '==', 'my:penang')]
    assert response.get_json()['recommendations'][0]['destinationId'] == 'cached_georgetown'


def test_rejected_provider_candidate_never_enters_scoring(client, mock_traveller_auth):
    sample_pref = {'interests': ['Nature'], 'travelType': 'Nature'}
    captured_candidates = []

    def fake_retrieve(collection, document_id=None, limit=None, filters=None):
        if collection == 'travel_preferences' and document_id:
            return sample_pref
        if collection == 'travel_preferences':
            return [sample_pref]
        if collection in {'feedback', 'destination_cache'}:
            return []
        return []

    from sequence_contract.domain_functions import prepareRecommendationInput as real_prepare

    def capture_prepare(preference, candidates, collaborative):
        captured_candidates.extend(candidates)
        return real_prepare(preference, candidates, collaborative)

    provider_result = {'local_results': [
        {
            'place_id': 'valid_bayan_lepas',
            'title': 'Penang War Museum',
            'address': 'Bayan Lepas, Malaysia',
            'type': 'Nature',
            'rating': 4.0,
        },
        {
            'place_id': 'misleading_kl',
            'title': 'Penang Seafood Restaurant',
            'address': 'Kuala Lumpur, Malaysia',
            'type': 'Nature',
            'rating': 5.0,
        },
    ]}
    with patch.dict('os.environ', {'SERPAPI_KEY': 'configured'}), \
         patch('modules.fr04_hybrid_recommendation.routes.retrieveRecord', side_effect=fake_retrieve), \
         patch('modules.fr04_hybrid_recommendation.routes.retrieveDestinationResults', return_value=provider_result), \
         patch('modules.fr04_hybrid_recommendation.routes.prepareRecommendationInput', side_effect=capture_prepare), \
         patch('modules.fr04_hybrid_recommendation.routes.storeRecord'):
        response = client.post(
            '/api/fr4/recommendations/generate',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'destinationArea': 'Penang, Malaysia'},
        )

    assert response.status_code == 200
    assert [item['destinationId'] for item in captured_candidates] == ['valid_bayan_lepas']
    assert [item['destinationId'] for item in response.get_json()['recommendations']] == ['valid_bayan_lepas']


def test_final_guard_removes_out_of_scope_ranked_candidate(client, mock_traveller_auth):
    sample_pref = {'interests': ['Food'], 'travelType': 'Food'}

    def fake_retrieve(collection, document_id=None, limit=None, filters=None):
        if collection == 'travel_preferences' and document_id:
            return sample_pref
        if collection == 'travel_preferences':
            return [sample_pref]
        if collection in {'feedback', 'destination_cache'}:
            return []
        return []

    provider_result = {'local_results': [{
        'place_id': 'valid_butterworth',
        'title': 'Butterworth Food Court',
        'address': 'Butterworth, Malaysia',
        'type': 'Food',
        'rating': 4.2,
    }]}

    def inject_invalid(items):
        return list(items) + [{
            'destinationId': 'injected_kl',
            'title': 'Injected KL Result',
            'address': 'Kuala Lumpur, Malaysia',
            'score': 100,
        }]

    with patch.dict('os.environ', {'SERPAPI_KEY': 'configured'}), \
         patch('modules.fr04_hybrid_recommendation.routes.retrieveRecord', side_effect=fake_retrieve), \
         patch('modules.fr04_hybrid_recommendation.routes.retrieveDestinationResults', return_value=provider_result), \
         patch('modules.fr04_hybrid_recommendation.routes.rankRecommendations', side_effect=inject_invalid), \
         patch('modules.fr04_hybrid_recommendation.routes.storeRecord'):
        response = client.post(
            '/api/fr4/recommendations/generate',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'destinationArea': 'Penang'},
        )

    assert response.status_code == 200
    assert [item['destinationId'] for item in response.get_json()['recommendations']] == ['valid_butterworth']


def test_get_snapshot_returns_safe_view_without_mutating_stored_snapshot(
        client, mock_traveller_auth):
    stored = {
        'recommendationGenerationId': 'legacy_snapshot',
        'travellerId': 'test_traveller_uid',
        'requestedDestination': 'Penang, Malaysia',
        'recommendationResults': [
            {'destinationId': 'valid', 'address': 'George Town, Malaysia'},
            {'destinationId': 'invalid', 'address': 'Kuala Lumpur, Malaysia'},
        ],
    }
    original_count = len(stored['recommendationResults'])
    with patch(
        'modules.fr04_hybrid_recommendation.routes.retrieveRecord',
        return_value=stored,
    ):
        response = client.get(
            '/api/fr4/recommendations?generationId=legacy_snapshot',
            headers={'Authorization': 'Bearer valid_test_token'},
        )

    assert response.status_code == 200
    assert [item['destinationId'] for item in response.get_json()['recommendations']] == ['valid']
    assert len(stored['recommendationResults']) == original_count


@pytest.mark.parametrize('interests,travel_type,pace,purpose,personality,expected', [
    (['Food', 'Local Cuisine', 'Cafe'], 'Food', 'Relaxed', 'Holiday',
     'Social', 'food_market'),
    (['Culture', 'Heritage', 'History'], 'Culture', 'Moderate',
     'Educational trip', 'Planner', 'heritage_museum'),
    (['Nature', 'Outdoor', 'Adventure'], 'Nature', 'Active', 'Holiday',
     'Explorer', 'nature_trail'),
    (['Shopping', 'Leisure', 'Entertainment'], 'Shopping', 'Relaxed',
     'Holiday', 'Relaxed', 'shopping_mall'),
])
def test_controlled_profiles_rank_the_matching_concept_first(
        interests, travel_type, pace, purpose, personality, expected):
    ranked = _rank_profile(
        interests, travel_type, pace=pace, purpose=purpose,
        personality=personality)

    assert ranked[0]['destinationId'] == expected
    assert ranked[0]['matchedInterests']
    assert ranked[0]['recommendationReason'].startswith(
        f"{round(ranked[0]['score'])}/100 hybrid ranking")


def test_taxonomy_maps_multi_word_and_related_interest_phrases():
    assert concepts_for(['Local Cuisine', 'Cafe', 'Street Food Market']) >= {
        'food', 'shopping'
    }
    assert concepts_for(['Local Culture', 'Historic Site']) == {'culture'}
    assert concepts_for(['Outdoor Activity', 'Hiking']) == {
        'adventure', 'nature'
    }


def test_cold_start_is_neutral_and_does_not_reuse_provider_rating():
    preference = {'interests': ['Food'], 'travelType': 'Food'}
    content = applyContentBasedFiltering(prepareRecommendationInput(
        preference, PERSONALISATION_CANDIDATES, []))
    output = applyCollaborativeFiltering(
        content, [], peerPreferences={}, currentPreference=preference)

    assert {item['collaborativeScore'] for item in output} == {50.0}
    assert {item['collaborativeConfidence'] for item in output} == {0.0}
    assert all('neutral cold-start' in item['collaborativeSource']
               for item in output)


def test_similar_peer_feedback_is_confidence_aware_and_explained():
    preference = {
        'interests': ['Culture', 'Heritage'],
        'travelType': 'Culture',
        'travelPace': 'Moderate',
        'travelPurpose': 'Educational trip',
        'travelPersonality': 'Planner',
    }
    peer = {**preference, 'travellerId': 'peer_1'}
    candidate = [PERSONALISATION_CANDIDATES[1]]
    content = applyContentBasedFiltering(prepareRecommendationInput(
        preference, candidate, []))
    collaborative = applyCollaborativeFiltering(
        content,
        [{'destinationId': 'heritage_museum', 'travellerId': 'peer_1',
          'rating': 5}],
        peerPreferences={'peer_1': peer},
        currentPreference=preference,
        currentTravellerId='current_user',
    )
    scored = calculateRecommendationScore(collaborative)[0]

    assert 0 < scored['collaborativeConfidence'] < 1
    assert 50 < scored['collaborativeScore'] < 100
    assert scored['collaborativeRatingCount'] == 1
    assert 'Highly rated by similar travellers' in scored['matchReasons']


def test_hybrid_weighting_and_snapshot_components_remain_60_30_10():
    item = {
        'destinationId': 'weighted',
        'contentScore': 80,
        'collaborativeScore': 70,
        'rating': 5,
        'reviews': 0,
    }
    scored = calculateRecommendationScore([item])[0]

    assert scored['scoreBreakdown']['contentWeight'] == 0.60
    assert scored['scoreBreakdown']['collaborativeWeight'] == 0.30
    assert scored['scoreBreakdown']['popularityWeight'] == 0.10
    assert scored['score'] == pytest.approx(
        scored['contentScore'] * .60
        + scored['collaborativeScore'] * .30
        + scored['popularityScore'] * .10,
        abs=.02,
    )


def test_recommendation_reason_only_claims_evidence_that_was_applied():
    candidate = {
        'destinationId': 'food_without_metadata',
        'title': 'Penang Hawker Centre',
        'category': 'Street food',
        'rating': 4.2,
        'reviews': 50,
    }
    preference = {
        'interests': ['Local Cuisine'],
        'travelType': 'Food',
        'travelPace': 'Relaxed',
        'budgetRange': 'Moderate',
        'travelPurpose': 'Holiday',
        'travelPersonality': 'Social',
    }
    content = applyContentBasedFiltering(prepareRecommendationInput(
        preference, [candidate], []))
    scored = calculateRecommendationScore(applyCollaborativeFiltering(
        content, [], peerPreferences={}, currentPreference=preference))[0]

    assert 'Food and local cuisine' in scored['recommendationReason']
    assert 'budget preference' not in scored['recommendationReason']
    assert 'travel pace' not in scored['recommendationReason']
    assert scored['contentSignals']['budget']['applied'] is False


def test_duplicate_destination_id_or_name_is_returned_once():
    duplicate = {
        **PERSONALISATION_CANDIDATES[0],
        'destinationId': 'provider_duplicate_id',
        'rating': 4.9,
    }
    preference = {'interests': ['Food'], 'travelType': 'Food'}
    content = applyContentBasedFiltering(prepareRecommendationInput(
        preference, PERSONALISATION_CANDIDATES + [duplicate], []))
    scored = calculateRecommendationScore(applyCollaborativeFiltering(
        content, [], peerPreferences={}, currentPreference=preference))
    unique = deduplicateRecommendations(scored)

    names = [item['title'] for item in unique]
    assert names.count('Penang Street Food Market') == 1


def test_diversity_reranking_avoids_repeating_an_unpreferred_category():
    ranked = diversifyRecommendations([
        {'destinationId': 'food_1', 'title': 'Food One', 'score': 100,
         'destinationConcepts': ['food']},
        {'destinationId': 'food_2', 'title': 'Food Two', 'score': 99,
         'destinationConcepts': ['food']},
        {'destinationId': 'culture_1', 'title': 'Museum', 'score': 97,
         'destinationConcepts': ['culture']},
    ], {'interests': ['Shopping']}, limit=3)

    assert [item['destinationId'] for item in ranked[:2]] == [
        'food_1', 'culture_1'
    ]
    assert ranked[1]['rankNo'] == 2


def test_supported_questionnaire_suitability_fields_change_content_score():
    preference = {
        'interests': ['Nature'],
        'travelType': 'Nature',
        'travelPace': 'Relaxed',
        'budgetRange': 'Budget',
        'travelPurpose': 'Family trip',
        'travelPersonality': 'Relaxed',
    }
    matching = {
        'destinationId': 'matching',
        'title': 'Nature Park',
        'type': 'Nature',
        'budgetLevel': 'Budget',
        'pace': ['Relaxed'],
        'purpose': ['Family trip'],
        'personality': ['Relaxed'],
    }
    conflicting = {
        **matching,
        'destinationId': 'conflicting',
        'budgetLevel': 'Premium',
        'pace': ['Packed'],
        'purpose': ['Business trip'],
        'personality': ['Social'],
    }
    output = applyContentBasedFiltering(prepareRecommendationInput(
        preference, [matching, conflicting], []))

    assert output[0]['contentScore'] > output[1]['contentScore']
    for field in ('pace', 'budget', 'travelPurpose', 'travelPersonality'):
        assert output[0]['contentSignals'][field]['applied'] is True
        assert output[0]['contentSignals'][field]['score'] >= 80
