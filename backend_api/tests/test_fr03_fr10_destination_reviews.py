import pytest
from unittest.mock import patch

def test_submit_and_retrieve_ratings_reviews(client, mock_traveller_auth):
    sample_feedback = {
        'id': 'fb_101',
        'destinationId': 'D1',
        'destinationName': 'Kek Lok Si Temple',
        'travellerId': 'test_traveller_uid',
        'travellerName': 'Test Traveller',
        'rating': 5,
        'comment': 'Magnificent temple and panoramic view.',
        'feedbackStatus': 'visible',
        'moderationStatus': 'pending_review'
    }

    with patch('modules.fr10_feedback_rating.routes.retrieveRecord') as mock_retrieve_fr10, \
         patch('modules.fr10_feedback_rating.routes.storeRecord') as mock_store_fr10:
        mock_retrieve_fr10.return_value = {'uid': 'test_traveller_uid', 'name': 'Test Traveller'}
        mock_store_fr10.return_value = sample_feedback

        res = client.post(
            '/api/fr10/feedback',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={
                'destinationId': 'D1',
                'destinationName': 'Kek Lok Si Temple',
                'rating': 5,
                'comment': 'Magnificent temple and panoramic view.'
            }
        )
        assert res.status_code == 201
        data = res.get_json()
        assert data['ok'] is True
        assert data['feedback']['destinationId'] == 'D1'

    with patch('modules.fr03_destination_search_information.routes.retrieveRecord') as mock_retrieve_fr03:
        mock_retrieve_fr03.return_value = [sample_feedback]

        res = client.get(
            '/api/fr3/destinations/D1/ratings-reviews',
            headers={'Authorization': 'Bearer valid_test_token'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert data['result']['rating'] == 5.0
        assert data['result']['reviews'] == 1
        assert len(data['result']['user_reviews']) == 1
        assert data['result']['user_reviews'][0]['description'] == 'Magnificent temple and panoramic view.'
