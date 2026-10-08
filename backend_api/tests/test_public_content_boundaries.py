from copy import deepcopy
from unittest.mock import patch

from services.public_content_projection import (
    PUBLIC_PACKAGE_COLLECTION,
    PUBLIC_REVIEW_COLLECTION,
    public_campaign,
    public_package,
    public_review,
    sync_package,
    sync_review,
)


def test_package_projection_allowlists_v2_nested_fields_without_mutating_source():
    source = {
        'id': 'pkg-1', 'operatorId': 'private-operator', 'approvalStatus': 'approved',
        'title': 'Penang Heritage', 'destination': 'Penang', 'durationDays': 2,
        'adultPrice': 100, 'currency': 'MYR',
        'itineraryDays': [{'title': 'Day 1', 'description': 'Walk', 'activities': ['Art'], 'secret': 'no'}],
        'privateNested': {'token': 'no'}, 'reviewedBy': 'private-admin',
    }
    original = deepcopy(source)
    result = public_package(source, {'name': 'Demo operator', 'email': 'private@example.test'})
    assert result['operatorName'] == 'Demo operator'
    assert result['itineraryDays'][0] == {
        'dayNumber': 1, 'title': 'Day 1', 'description': 'Walk',
        'activities': ['Art'], 'meals': [], 'accommodation': '', 'transportNotes': '',
    }
    assert 'operatorId' not in result and 'reviewedBy' not in result
    assert 'privateNested' not in result and 'operatorEmail' not in result
    assert source == original


def test_campaign_projection_requires_explicit_public_fields():
    result = public_campaign({
        'id': 'camp-1', 'campaignTitle': 'Early bird', 'packageId': 'pkg-1',
        'reviewStatus': 'approved', 'reviewedBy': 'admin',
        'discountValue': 10, 'secretPayload': {'accessToken': 'no'},
    }, package={'id': 'pkg-1', 'title': 'Penang', 'destination': 'Penang', 'adultPrice': 100})
    assert result['campaignTitle'] == 'Early bird'
    assert result['packagePrice'] == 100
    assert 'reviewStatus' not in result and 'reviewedBy' not in result
    assert 'secretPayload' not in result


def test_review_projection_excludes_identity_and_moderation_fields():
    result = public_review({
        'id': 'review-1', 'destinationId': 'penang', 'rating': 5,
        'comment': 'Great', 'travellerId': 'private-traveller',
        'travellerName': 'A Traveller', 'moderationStatus': 'pending_review',
        'reviewedBy': 'private-admin', 'feedbackStatus': 'visible',
    })
    assert result['username'] == 'A Traveller'
    assert result['source'] == 'travelmate'
    assert 'travellerId' not in result
    assert 'moderationStatus' not in result
    assert 'reviewedBy' not in result


def test_cloud_public_routes_drop_ineligible_campaign_and_private_fields(client, mock_traveller_auth):
    package = {
        'id': 'pkg-1', 'approvalStatus': 'approved', 'availabilityStatus': 'available',
        'title': 'Penang', 'destination': 'Penang', 'durationDays': 1, 'adultPrice': 10,
        'operatorId': 'op-1', 'privateField': 'no',
    }
    campaign = {
        'id': 'camp-1', 'packageId': 'pkg-1', 'reviewStatus': 'approved',
        'campaignStatus': 'active', 'campaignTitle': 'Offer', 'reviewedBy': 'admin',
    }
    profile = {'id': 'op-1', 'name': 'Operator', 'email': 'private@example.test'}
    with patch('modules.shared_public_content.routes.retrieveRecord') as retrieve:
        def records(collection, document_id=None, filters=None, limit=None):
            if collection == 'tourism_packages': return [package] if document_id is None else package
            if collection == 'promotional_campaigns': return [campaign]
            if collection == 'users': return profile
            return []
        retrieve.side_effect = records
        response = client.get('/api/public/tourism-packages', headers={'Authorization': 'Bearer token'})
    assert response.status_code == 200
    item = response.get_json()['items'][0]
    assert item['title'] == 'Penang'
    assert 'privateField' not in item and 'operatorId' not in item
    assert 'operatorEmail' not in item


def test_cloud_review_response_does_not_spread_feedback_record(client, mock_traveller_auth):
    review = {
        'id': 'review-1', 'destinationId': 'D1', 'rating': 5, 'comment': 'Good',
        'travellerId': 'private', 'travellerName': 'Traveller',
        'feedbackStatus': 'visible', 'moderationStatus': 'pending_review',
        'reviewComment': 'internal', 'reviewedBy': 'admin',
    }
    with patch('modules.fr03_destination_search_information.routes.retrieveRecord', return_value=[review]):
        response = client.get('/api/fr3/destinations/D1/ratings-reviews', headers={'Authorization': 'Bearer token'})
    assert response.status_code == 200
    result = response.get_json()['result']['user_reviews'][0]
    assert result['description'] == 'Good'
    assert 'travellerId' not in result
    assert 'moderationStatus' not in result
    assert 'reviewComment' not in result


def test_projection_sync_removes_rejected_package_and_hidden_review(monkeypatch):
    monkeypatch.delenv('TRAVELMATE_TESTING', raising=False)
    deleted = []
    monkeypatch.setattr('services.public_content_projection.deleteRecord', lambda collection, key: deleted.append((collection, key)))
    monkeypatch.setattr('services.public_content_projection.retrieveRecord', lambda *args, **kwargs: [])
    sync_package('pkg-1', {'id': 'pkg-1', 'approvalStatus': 'rejected'})
    sync_review('review-1', {'id': 'review-1', 'feedbackStatus': 'removed'})
    assert (PUBLIC_PACKAGE_COLLECTION, 'pkg-1') in deleted
    assert (PUBLIC_REVIEW_COLLECTION, 'review-1') in deleted
