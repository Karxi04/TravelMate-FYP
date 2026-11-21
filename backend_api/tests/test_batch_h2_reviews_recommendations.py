"""Batch H.2: isolated owner/auth fixtures, never production records or providers."""
from copy import deepcopy
from unittest.mock import patch

import pytest

from test_local_reviews import memory, headers
from services.fyp_reviews import regional_demo_reviews, regional_demo_destinations
from services import national_evaluation_reviews
from services.review_service import approved_reviews, genuine_review
from services.recommendation_discovery import is_planning_candidate
from services.recommendation_taxonomy import experience_types


def test_local_demo_has_one_illustrative_list_and_separate_genuine_rating(client, memory):
    from modules.fr03_destination_search_information import routes
    client.application.config['LOCAL_FYP_SAMPLE_REVIEWS'] = True
    real = {'id': 'real', 'travellerId': 'owner', 'travellerName': 'Visitor',
            'destinationId': 'local_penang_hill', 'rating': 4, 'comment': 'Beautiful scenery.',
            'feedbackStatus': 'visible', 'moderationStatus': 'reviewed'}
    memory['feedback', 'real'] = deepcopy(real)
    examples = [dict(real, id='example', travellerId='fixture', synthetic=True, rating=2),
                dict(real, id='pending', travellerId='pending', synthetic=True, moderationStatus='pending_review')]
    url = '/api/fr3/destinations/penang_hill/ratings-reviews?view=unified'
    context = {'X-TravelMate-Review-Context': 'fyp-v1'}
    with patch.object(routes, '_private_review_dataset', return_value=('ref', {'local_penang_hill': {}})), \
         patch.object(routes, 'dataset_reviews', return_value=examples), \
         patch.object(routes, 'regional_demo_reviews', return_value=[]):
        for account in ['first', 'second', 'new-registration']:
            response = client.get(url, headers={**headers(account), **context})
            body = response.json
            assert body['reviewEnvironment'] == 'private_demo'
            assert body['result']['rating'] == 3 and body['result']['reviews'] == 2
            assert body['result']['genuineSummary'] == {'rating': 4, 'reviews': 1}
            assert [row['id'] for row in body['result']['user_reviews']] == ['real', 'example']
            assert body['result']['user_reviews'][1]['synthetic'] is True
            assert body['result']['user_reviews'][1]['source'] == 'fyp_private'
            assert body['result']['sampleSummary'] == {'rating': 2.0, 'reviews': 1}
            assert response.headers['Cache-Control'] == 'private, no-store'
        ordinary = client.get(url, headers=headers('second')).json
        assert [row['id'] for row in ordinary['result']['user_reviews']] == ['real']
        assert 'reviewEnvironment' not in ordinary
    assert memory['feedback', 'real'] == real and len(memory) == 1


def test_example_failure_does_not_hide_genuine_reviews(client, memory):
    from modules.fr03_destination_search_information import routes
    client.application.config['LOCAL_FYP_SAMPLE_REVIEWS'] = True
    with patch.object(routes, '_private_review_dataset', side_effect=ValueError('Invalid fixture state')), \
         patch.object(routes, 'regional_demo_reviews', return_value=[]):
        response = client.get('/api/fr3/destinations/penang_hill/ratings-reviews?view=unified',
                              headers={**headers(), 'X-TravelMate-Review-Context': 'fyp-v1'})
    assert response.status_code == 200
    assert response.json['exampleReviewStatus'] == 'unavailable'
    assert response.json['result']['user_reviews'] == []
    assert response.json['result']['rating'] is None


@pytest.mark.parametrize('identity', list(regional_demo_destinations()))
def test_regional_fixtures_are_screened_canonical_private_and_not_seeded(client, memory, identity):
    from modules.fr03_destination_search_information import routes
    rows = regional_demo_reviews(identity)
    before = deepcopy(rows)
    original = [row for row in rows if row['dataset'] == 'fyp-regional-v1']
    assert len(original) == 3 and len(rows)==3+len(national_evaluation_reviews.sources(identity))
    assert all(row['synthetic'] and not genuine_review(row) for row in rows)
    assert all(row['destinationId'] == identity for row in rows)
    visible = approved_reviews(rows)
    assert len(visible)==3+len(approved_reviews(national_evaluation_reviews.sources(identity)))
    client.application.config['LOCAL_FYP_SAMPLE_REVIEWS'] = True
    with patch.object(routes, '_private_review_dataset') as firestore:
        body = client.get(f'/api/fr3/destinations/{identity}/ratings-reviews?view=unified',
                          headers={**headers(), 'X-TravelMate-Review-Context': 'fyp-v1'}).json
    firestore.assert_not_called()
    assert body['result']['reviews'] == len(visible)
    assert body['result']['rating'] == round(sum(row['rating'] for row in visible) / len(visible), 1)
    assert body['result']['genuineSummary'] == {'rating': None, 'reviews': 0}
    assert len(body['result']['user_reviews']) == len(visible)
    assert rows == before and not memory


@pytest.mark.parametrize('provider_id', ['local_government_office', 'government_office', 'immigration_department'])
def test_provider_function_cannot_hide_behind_a_generic_attraction_type(provider_id):
    assert not is_planning_candidate({'title': 'Nature Service Centre', 'type': 'Tourist attraction',
                                      'type_ids': [provider_id]})
    assert is_planning_candidate({'title': 'Government Heritage Museum', 'type': 'Museum',
                                 'type_ids': ['museum']})


@pytest.mark.parametrize('provider_id', ['bank', 'car_repair', 'real_estate_agency'])
def test_ordinary_service_businesses_cannot_become_nature_attractions_from_branding(provider_id):
    assert not is_planning_candidate({'title': 'Nature Service', 'type': 'Establishment', 'type_ids': [provider_id]})
    assert is_planning_candidate({'title': 'Old Bank Museum', 'type': 'Museum', 'type_ids': ['museum']})


def test_broad_categories_still_expose_specific_experience_variety():
    assert experience_types({'title': 'Hiking Trail', 'category': 'Nature'}) == ['hiking']
    assert experience_types({'title': 'Botanic Garden', 'category': 'Nature'}) == ['botanical_garden']
    assert experience_types({'title': 'Shopping Mall', 'category': 'Shopping'}) == ['shopping']
    # A brand name must not override a specific provider type.
    assert experience_types({'title': 'Hiking Trail Cafe', 'type_id': 'cafe', 'type': 'Cafe'}) == ['cafe']


def test_batu_caves_has_sourced_selangor_identity_without_moving_the_pin():
    from services.local_catalog import DESTINATIONS
    from services.malaysian_locality import normalize_candidate_geography
    record = next(row for row in DESTINATIONS if row['destinationId'] == 'local_batu_caves')
    assert record['gps_coordinates'] == {'latitude': 3.2379, 'longitude': 101.6840}
    result = normalize_candidate_geography(record)
    assert result['state'] == 'Selangor' and not result.get('conflict')
    assert record['geographicSourceUrl'] == 'https://www.malaysia.travel/explore/batu-caves'
