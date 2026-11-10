from unittest.mock import patch

import pytest


AUTH = {'Authorization': 'Bearer valid_test_token'}
OWNED_FEEDBACK = {
    'id': 'feedback-1',
    'travellerId': 'test_traveller_uid',
    'travellerName': 'Test Traveller',
    'destinationId': 'destination-1',
    'destinationName': 'Original destination',
    'destinationAddress': 'Original address',
    'rating': 4,
    'comment': 'Original comment',
    'feedbackStatus': 'visible',
    'moderationStatus': 'reviewed',
    'submittedAt': '2026-10-01T00:00:00Z',
}


def test_owner_can_update_flutter_rating_and_comment_only(client, mock_traveller_auth):
    updated = {**OWNED_FEEDBACK, 'rating': 5, 'comment': 'Updated comment'}
    with patch('modules.fr10_feedback_rating.routes.retrieveRecord', return_value=OWNED_FEEDBACK), \
         patch('modules.fr10_feedback_rating.routes.updateRecord', return_value=updated) as update:
        response = client.put('/api/fr10/feedback/feedback-1', headers=AUTH, json={
            'rating': 5,
            'comment': 'Updated comment',
        })

    assert response.status_code == 200
    updates = update.call_args.args[2]
    assert updates['rating'] == 5
    assert updates['comment'] == 'Updated comment'
    assert updates['feedbackStatus'] == 'visible'
    assert updates['moderationStatus'] == 'pending_review'
    assert set(updates) == {'rating', 'comment', 'feedbackStatus', 'moderationStatus', 'updatedAt', 'screening'}
    assert updates['screening']['method'] == 'local_rules_v2_rating_sentiment'


def test_non_owner_cannot_update_feedback(client, mock_traveller_auth):
    other = {**OWNED_FEEDBACK, 'travellerId': 'another-traveller'}
    with patch('modules.fr10_feedback_rating.routes.retrieveRecord', return_value=other), \
         patch('modules.fr10_feedback_rating.routes.updateRecord') as update:
        response = client.put('/api/fr10/feedback/feedback-1', headers=AUTH, json={'rating': 5})

    assert response.status_code == 404
    update.assert_not_called()


@pytest.mark.parametrize('protected_update', [
    {'travellerId': 'another-traveller'},
    {'travellerName': 'Administrator'},
    {'destinationId': 'other-destination'},
    {'destinationName': 'Other destination'},
    {'destinationAddress': 'Other address'},
    {'submittedAt': '2020-01-01T00:00:00Z'},
    {'feedbackStatus': 'removed'},
    {'moderationStatus': 'reviewed'},
    {'reviewedBy': 'admin-1'},
    {'removedBy': 'admin-1'},
    {'approvalStatus': 'approved'},
])
def test_protected_feedback_fields_are_rejected(client, mock_traveller_auth, protected_update):
    with patch('modules.fr10_feedback_rating.routes.retrieveRecord', return_value=OWNED_FEEDBACK), \
         patch('modules.fr10_feedback_rating.routes.updateRecord') as update:
        response = client.put('/api/fr10/feedback/feedback-1', headers=AUTH, json={
            'rating': 5,
            **protected_update,
        })

    assert response.status_code == 400
    update.assert_not_called()


@pytest.mark.parametrize('payload', [{}, {'rating': 0}, {'rating': 6}, {'rating': 'bad'}])
def test_empty_or_invalid_feedback_updates_are_rejected(client, mock_traveller_auth, payload):
    with patch('modules.fr10_feedback_rating.routes.retrieveRecord', return_value=OWNED_FEEDBACK), \
         patch('modules.fr10_feedback_rating.routes.updateRecord') as update:
        response = client.put('/api/fr10/feedback/feedback-1', headers=AUTH, json=payload)

    assert response.status_code == 400
    update.assert_not_called()


def test_removed_feedback_cannot_be_updated(client, mock_traveller_auth):
    removed = {**OWNED_FEEDBACK, 'feedbackStatus': 'removed', 'moderationStatus': 'removed'}
    with patch('modules.fr10_feedback_rating.routes.retrieveRecord', return_value=removed), \
         patch('modules.fr10_feedback_rating.routes.updateRecord') as update:
        response = client.put('/api/fr10/feedback/feedback-1', headers=AUTH, json={'comment': 'Please restore'})

    assert response.status_code == 409
    update.assert_not_called()
