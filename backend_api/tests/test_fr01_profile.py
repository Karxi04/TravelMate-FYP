import pytest
from unittest.mock import patch, MagicMock


def test_health(client):
    res = client.get('/api/health')
    assert res.status_code == 200
    data = res.get_json()
    assert data['ok'] is True


def test_create_profile_unauthorized(client):
    res = client.post('/api/fr1/profile', json={'name': 'Alice'})
    assert res.status_code == 401


def test_create_traveller_profile(client, mock_traveller_auth):
    with patch('modules.fr01_user_management.routes.retrieveRecord') as mock_retrieve, \
         patch('modules.fr01_user_management.routes.storeRecord') as mock_store:
        mock_retrieve.return_value = None
        mock_store.return_value = {
            'uid': 'test_traveller_uid',
            'email': 'traveller@test.com',
            'name': 'Test Traveller',
            'role': 'traveller',
            'status': 'active'
        }
        res = client.post(
            '/api/fr1/profile',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'name': 'Test Traveller', 'role': 'traveller'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert data['profile']['role'] == 'traveller'


def test_get_me_profile_reuses_authenticated_firestore_snapshot(client, mock_traveller_auth):
    with patch('auth_utils.get_db') as db, patch(
        'modules.fr01_user_management.routes.retrieveRecord'
    ) as duplicate_read:
        document = db.return_value.collection.return_value.document.return_value
        snapshot = document.get.return_value
        snapshot.exists = True
        snapshot.to_dict.return_value = {
            'uid': 'test_traveller_uid',
            'name': 'Stored Traveller',
            'email': 'traveller@test.com',
            'role': 'traveller',
            'dateOfBirth': '1995-05-15',
            'nationality': 'Malaysia',
            'currentCity': 'George Town',
            'gender': 'Female',
            'emergencyContactName': 'Jane Doe',
            'emergencyContact': '+60198765432',
            'emergencyRelationship': 'Family',
            'travelBio': 'I love Penang food and beach walks.'
        }
        response = client.get('/api/fr1/me', headers={'Authorization': 'Bearer valid_test_token'})
        assert response.status_code == 200
        assert response.json['profile'] == {'id': 'test_traveller_uid', **snapshot.to_dict.return_value}
        document.get.assert_called_once_with()
        duplicate_read.assert_not_called()


def test_profile_quota_error_fails_closed_without_exposing_details(client, mock_traveller_auth, caplog):
    from google.api_core.exceptions import ResourceExhausted

    with patch('auth_utils.get_db') as db, patch('auth_utils.rate_limit_response') as limiter:
        document = db.return_value.collection.return_value.document.return_value
        document.get.side_effect = ResourceExhausted('private-value')
        response = client.get('/api/fr1/me', headers={'Authorization': 'Bearer valid_test_token'})
    assert response.status_code == 503
    assert response.json['code'] == 'profile_storage_unavailable'
    assert response.headers['Cache-Control'] == 'no-store'
    assert 'profile' not in response.json
    assert 'ResourceExhausted status=429' in caplog.text
    assert 'private-value' not in caplog.text and 'private-value' not in response.text
    limiter.assert_not_called()


def test_missing_profile_remains_null(client, mock_traveller_auth):
    with patch('auth_utils.get_db') as db:
        db.return_value.collection.return_value.document.return_value.get.return_value.exists = False
        response = client.get('/api/fr1/me', headers={'Authorization': 'Bearer valid_test_token'})
    assert response.status_code == 200
    assert response.json == {'ok': True, 'profile': None}


def test_update_traveller_profile_all_fields(client, mock_traveller_auth):
    with patch('modules.fr01_user_management.routes.updateRecord') as mock_update:
        payload = {
            'name': 'Updated Traveller Name',
            'phoneNo': '+60123456789',
            'dateOfBirth': '1995-05-15',
            'nationality': 'Japan',
            'currentCity': 'Tokyo',
            'gender': 'Female',
            'emergencyContactName': 'Jane Doe',
            'emergencyContact': '+60198765432',
            'emergencyRelationship': 'Family',
            'travelBio': 'I enjoy local cultural exploration and foodie tours.'
        }
        mock_update.return_value = {
            'uid': 'test_traveller_uid',
            'role': 'traveller',
            **payload
        }
        res = client.put(
            '/api/fr1/me',
            headers={'Authorization': 'Bearer valid_test_token'},
            json=payload
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert data['profile']['name'] == 'Updated Traveller Name'
        assert data['profile']['nationality'] == 'Japan'
        assert data['profile']['currentCity'] == 'Tokyo'
        assert data['profile']['dateOfBirth'] == '1995-05-15'

        # Verify updateRecord was invoked with g.uid and all fields
        mock_update.assert_called_once()
        args, _ = mock_update.call_args
        assert args[0] == 'users'
        assert args[1] == 'test_traveller_uid'
        stored_dict = args[2]
        assert stored_dict['name'] == 'Updated Traveller Name'
        assert stored_dict['nationality'] == 'Japan'
        assert stored_dict['currentCity'] == 'Tokyo'
        assert stored_dict['dateOfBirth'] == '1995-05-15'
        assert stored_dict['gender'] == 'Female'
        assert stored_dict['emergencyContactName'] == 'Jane Doe'
        assert stored_dict['emergencyContact'] == '+60198765432'
        assert stored_dict['emergencyRelationship'] == 'Family'
        assert stored_dict['travelBio'] == payload['travelBio']
        assert 'updatedAt' in stored_dict


def test_update_profile_partial(client, mock_traveller_auth):
    with patch('modules.fr01_user_management.routes.updateRecord') as mock_update:
        payload = {'currentCity': 'Kyoto'}
        mock_update.return_value = {
            'uid': 'test_traveller_uid',
            'name': 'Existing Name',
            'currentCity': 'Kyoto'
        }
        res = client.put(
            '/api/fr1/me',
            headers={'Authorization': 'Bearer valid_test_token'},
            json=payload
        )
        assert res.status_code == 200
        args, _ = mock_update.call_args
        stored_dict = args[2]
        assert stored_dict['currentCity'] == 'Kyoto'
        assert 'name' not in stored_dict
        assert 'dateOfBirth' not in stored_dict


def test_update_profile_rejects_numeric_only_name(client, mock_traveller_auth):
    res = client.put(
        '/api/fr1/me',
        headers={'Authorization': 'Bearer valid_test_token'},
        json={'name': '123456'}
    )
    assert res.status_code == 400
    data = res.get_json()
    assert data['ok'] is False
    assert 'Name cannot consist only of digits' in data['error']


def test_update_profile_rejects_future_dob(client, mock_traveller_auth):
    res = client.put(
        '/api/fr1/me',
        headers={'Authorization': 'Bearer valid_test_token'},
        json={'dateOfBirth': '2099-01-01'}
    )
    assert res.status_code == 400
    data = res.get_json()
    assert data['ok'] is False
    assert 'Date of birth cannot be in the future' in data['error']


def test_update_profile_rejects_invalid_dob_format(client, mock_traveller_auth):
    res = client.put(
        '/api/fr1/me',
        headers={'Authorization': 'Bearer valid_test_token'},
        json={'dateOfBirth': '15/05/1995'}
    )
    assert res.status_code == 400
    data = res.get_json()
    assert data['ok'] is False
    assert 'YYYY-MM-DD' in data['error']


def test_update_profile_rejects_invalid_gender(client, mock_traveller_auth):
    res = client.put(
        '/api/fr1/me',
        headers={'Authorization': 'Bearer valid_test_token'},
        json={'gender': 'Martian'}
    )
    assert res.status_code == 400
    data = res.get_json()
    assert data['ok'] is False
    assert 'Invalid gender option' in data['error']


def test_update_profile_rejects_partial_emergency_contact(client, mock_traveller_auth):
    # Name without phone
    res1 = client.put(
        '/api/fr1/me',
        headers={'Authorization': 'Bearer valid_test_token'},
        json={'emergencyContactName': 'Jane Doe', 'emergencyContact': ''}
    )
    assert res1.status_code == 400
    assert 'Emergency contact phone is required' in res1.get_json()['error']

    # Phone without name
    res2 = client.put(
        '/api/fr1/me',
        headers={'Authorization': 'Bearer valid_test_token'},
        json={'emergencyContactName': '', 'emergencyContact': '+60123456789'}
    )
    assert res2.status_code == 400
    assert 'Emergency contact name is required' in res2.get_json()['error']


def test_update_profile_disallows_role_and_uid_tampering(client, mock_traveller_auth):
    with patch('modules.fr01_user_management.routes.updateRecord') as mock_update:
        mock_update.return_value = {
            'uid': 'test_traveller_uid',
            'role': 'traveller'
        }
        res = client.put(
            '/api/fr1/me',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={
                'name': 'Safe Name',
                'role': 'admin',
                'status': 'deactivated',
                'uid': 'target_victim_uid'
            }
        )
        assert res.status_code == 200
        args, _ = mock_update.call_args
        # Document updated MUST be authenticated user g.uid, not victim
        assert args[1] == 'test_traveller_uid'
        stored_dict = args[2]
        # role, status, uid MUST be omitted from update
        assert 'role' not in stored_dict
        assert 'status' not in stored_dict
        assert 'uid' not in stored_dict
        assert stored_dict['name'] == 'Safe Name'


def test_update_operator_profile_preserved(client, mock_operator_auth):
    with patch('modules.fr01_user_management.routes.updateRecord') as mock_update:
        mock_update.return_value = {
            'uid': 'test_operator_uid',
            'companyName': 'Updated Tours Sdn Bhd',
            'businessContact': '+60388889999'
        }
        res = client.put(
            '/api/fr1/me',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={
                'companyName': 'Updated Tours Sdn Bhd',
                'businessContact': '+60388889999'
            }
        )
        assert res.status_code == 200
        args, _ = mock_update.call_args
        stored_dict = args[2]
        assert stored_dict['companyName'] == 'Updated Tours Sdn Bhd'
        assert stored_dict['businessContact'] == '+60388889999'
