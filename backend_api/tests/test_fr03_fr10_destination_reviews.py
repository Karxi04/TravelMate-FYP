import pytest
from unittest.mock import patch
from pathlib import Path
import re

from services.review_destination import _ALIASES, review_destination_id
from test_local_reviews import headers, memory


def test_flutter_uses_same_penang_review_identity_groups():
    contract = Path(__file__).resolve().parents[2] / 'traveller_mobile/lib/services/review_contract.dart'
    body = contract.read_text(encoding='utf-8').split('static const _aliases', 1)[1].split('};', 1)[0]
    groups = {identity: tuple(re.findall(r"'([^']+)'", aliases))
              for identity, aliases in re.findall(r"'([^']+)':\s*\[([^\]]+)\]", body)}
    assert groups == _ALIASES
    for distinct in ('penang_clan_jetties', 'clan_jetties', 'demo_penang_street_art',
                     'gurney_plaza', 'penang_armenian_street'):
        assert review_destination_id(distinct) == distinct


def test_penang_alias_review_reuses_legacy_source_and_aggregates_approved_owners(client, memory):
    comment = 'Beautiful scenery and a wonderful visit.'
    base = {'feedbackStatus': 'visible', 'moderationStatus': 'reviewed',
            'submittedAt': '2026-01-01', 'comment': comment}
    memory['feedback', 'old'] = {**base, 'id': 'old', 'travellerId': 'owner',
                                 'destinationId': 'penang_hill', 'rating': 5}
    memory['feedback', 'old_duplicate'] = {**base, 'id': 'old_duplicate', 'travellerId': 'owner',
                                           'submittedAt': '2025-01-01',
                                           'destinationId': 'local_penang_hill', 'rating': 2}
    memory['feedback', 'other'] = {**base, 'id': 'other', 'travellerId': 'other',
                                   'destinationId': 'local_penang_hill', 'rating': 1}
    response = client.post('/api/fr10/feedback', headers=headers(), json={
        'destinationId': 'local_penang_hill', 'rating': 5, 'comment': comment,
    })
    assert response.status_code == 200 and response.json['id'] == 'old'
    assert len(memory) == 3 and memory['feedback', 'old']['destinationId'] == 'penang_hill'
    batch = client.get('/api/fr3/local-ratings', headers=headers()).json['items']
    for identity in ('local_penang_hill', 'penang_hill'):
        details = client.get(f'/api/fr3/destinations/{identity}/ratings-reviews',
                             headers=headers()).json['result']
        assert batch[identity] == {'rating': 3.0, 'reviews': 2}
        assert (details['rating'], details['reviews']) == (3.0, 2)
        assert {row['id'] for row in details['user_reviews']} == {'old', 'other'}


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
