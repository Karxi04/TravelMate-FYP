from unittest.mock import patch, MagicMock

def test_admin_rbac_forbidden_for_traveller(client, mock_traveller_auth):
    res = client.get(
        '/api/fr13/users',
        headers={'Authorization': 'Bearer valid_test_token'}
    )
    assert res.status_code == 403
    assert 'Insufficient role permission' in res.get_json()['error']

def test_admin_users_access(client, mock_admin_auth):
    with patch('modules.fr13_administrator_management.routes.retrieveRecord') as mock_retrieve:
        mock_retrieve.return_value = [
            {'uid': 'u1', 'role': 'traveller', 'email': 't@t.com'},
            {'uid': 'u2', 'role': 'operator', 'email': 'o@t.com'},
        ]
        res = client.get(
            '/api/fr13/users',
            headers={'Authorization': 'Bearer valid_test_token'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert len(data['items']) == 2

def test_admin_review_package(client, mock_admin_auth):
    sample_pkg = {
        'id': 'pkg_pending_1',
        'packageTitle': 'Penang Sunset Cruise',
        'approvalStatus': 'pending'
    }
    with patch('modules.fr13_administrator_management.routes.retrieveRecord') as mock_retrieve, \
         patch('modules.fr13_administrator_management.routes.updateRecord') as mock_update:
        mock_retrieve.return_value = sample_pkg
        mock_update.side_effect = lambda coll, doc_id, data: {**sample_pkg, **data}

        # Approve package
        res = client.post(
            '/api/fr13/packages/pkg_pending_1/review',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'decision': 'approved', 'comment': 'Looks great!'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert data['package']['approvalStatus'] == 'approved'
        assert data['package']['reviewedBy'] == 'test_admin_uid'


def test_admin_rejection_requires_reason_and_completed_review_is_immutable(client, mock_admin_auth):
    pending = {'id': 'pkg_pending', 'packageTitle': 'Penang Tour', 'approvalStatus': 'pending'}
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', return_value=pending):
        missing = client.post('/api/fr13/packages/pkg_pending/review',
                              headers={'Authorization': 'Bearer valid_test_token'},
                              json={'decision': 'rejected', 'comment': ''})
    assert missing.status_code == 400
    assert missing.get_json()['error'] == 'A rejection reason is required'

    approved = {**pending, 'approvalStatus': 'approved'}
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', return_value=approved):
        duplicate = client.post('/api/fr13/packages/pkg_pending/review',
                                headers={'Authorization': 'Bearer valid_test_token'},
                                json={'decision': 'rejected', 'comment': 'Changed mind'})
    assert duplicate.status_code == 409

def test_admin_moderate_feedback(client, mock_admin_auth):
    sample_fb = {
        'id': 'fb_spam_1',
        'comment': 'Buy cheap sunglasses here!',
        'rating': 1,
        'feedbackStatus': 'visible'
    }
    with patch('modules.fr13_administrator_management.routes.retrieveRecord') as mock_retrieve, \
         patch('modules.fr13_administrator_management.routes.updateRecord') as mock_update:
        mock_retrieve.return_value = sample_fb
        mock_update.side_effect = lambda coll, doc_id, data: {**sample_fb, **data}

        # Remove spam feedback
        res = client.post(
            '/api/fr13/feedback/fb_spam_1/review',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'decision': 'remove', 'comment': 'Spam review'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert data['decision'] == 'remove'
        assert data['feedback']['feedbackStatus'] == 'removed'

def test_admin_destination_management(client, mock_admin_auth):
    with patch('modules.fr13_administrator_management.routes.storeRecord') as mock_store:
        mock_store.side_effect = lambda coll, data: {'id': 'dest_new_1', **data}

        res = client.post(
            '/api/fr13/destinations',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={
                'title': 'New Heritage Museum',
                'address': 'George Town, Penang',
                'category': 'Culture',
                'estimatedCost': 25.0,
                'rating': 4.7
            }
        )
        assert res.status_code == 201
        data = res.get_json()
        assert data['ok'] is True
        assert data['destination']['title'] == 'New Heritage Museum'

def test_admin_cannot_demote_or_disable_self(client, mock_admin_auth):
    res = client.put('/api/fr13/users/test_admin_uid',
                     headers={'Authorization': 'Bearer valid_test_token'},
                     json={'role': 'traveller'})
    assert res.status_code == 409
    assert 'cannot' in res.get_json()['error'].lower()

def test_campaign_queue_filters_and_rejection_requires_reason(client, mock_admin_auth):
    records = [
        {'id': 'camp-1', 'campaignTitle': 'Island offer', 'reviewStatus': 'pending', 'packageId': 'pkg-1'},
        {'id': 'camp-2', 'campaignTitle': 'Old offer', 'reviewStatus': 'approved', 'packageId': 'pkg-2'},
    ]
    def retrieve(collection, doc_id=None, filters=None):
        if collection == 'promotional_campaigns':
            if doc_id: return next((x for x in records if x['id'] == doc_id), None)
            return records
        return {'packageTitle': 'Package'}
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', side_effect=retrieve):
        queued = client.get('/api/fr13/campaigns?status=pending', headers={'Authorization': 'Bearer valid_test_token'})
        assert queued.status_code == 200
        assert [x['id'] for x in queued.get_json()['items']] == ['camp-1']
        missing = client.post('/api/fr13/campaigns/camp-1/review', headers={'Authorization': 'Bearer valid_test_token'}, json={'decision': 'rejected'})
    assert missing.status_code == 400
    assert missing.get_json()['error'] == 'A rejection reason is required'
