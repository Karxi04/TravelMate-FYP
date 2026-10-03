import pytest
from unittest.mock import patch

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
