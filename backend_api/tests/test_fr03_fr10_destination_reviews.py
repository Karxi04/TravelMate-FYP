import pytest
from unittest.mock import patch


def test_local_rating_batch_uses_only_approved_owner_contributions(client, mock_traveller_auth):
    base = {'destinationId':'place', 'rating':5, 'travellerId':'owner',
            'feedbackStatus':'visible','moderationStatus':'reviewed','updatedAt':'2026-02-01'}
    records = [base, {**base,'travellerId':'other','rating':3},
               {**base,'rating':1,'updatedAt':'2026-01-01'},
               {**base,'travellerId':'pending','moderationStatus':'pending_review'},
               {**base,'travellerId':'removed','feedbackStatus':'removed'},
               {**base,'destinationId':'unrated','moderationStatus':'pending_review'}]
    with patch('modules.fr03_destination_search_information.routes.retrieveRecord', return_value=records):
        response=client.get('/api/fr3/local-ratings',headers={'Authorization':'Bearer test_token'})
    assert response.status_code==200
    assert response.json=={'ok':True,'items':{'place':{'rating':4.0,'reviews':2}}}


def test_local_rating_batch_requires_auth(client):
    assert client.get('/api/fr3/local-ratings').status_code==401

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
         patch('modules.fr10_feedback_rating.routes.claimRecord') as mock_claim:
        mock_retrieve_fr10.side_effect = lambda collection, *args, **kwargs: [] if collection == 'feedback' else {'uid': 'test_traveller_uid', 'name': 'Test Traveller'}
        mock_claim.return_value = (sample_feedback, True)

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

    # Only the affirmative legacy Admin decision may publish this review.
    sample_feedback['moderationStatus'] = 'reviewed'
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
