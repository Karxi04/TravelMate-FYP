import pytest
from unittest.mock import patch

def test_destination_search_keyword_match(client, mock_traveller_auth):
    res = client.get(
        '/api/fr3/destinations/search?q=temple',
        headers={'Authorization': 'Bearer valid_test_token'}
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data['ok'] is True
    assert len(data['results']) >= 1
    assert any('temple' in r['title'].lower() for r in data['results'])

def test_destination_search_no_irrelevant_dump(client, mock_traveller_auth):
    with patch.dict('os.environ', {'FALLBACK_MODE': 'true'}):
        res = client.get(
            '/api/fr3/destinations/search?q=completely_nonexistent_destination_xyz',
            headers={'Authorization': 'Bearer valid_test_token'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert len(data['results']) == 0

def test_destination_search_includes_admin_destinations(client, mock_traveller_auth):
    custom_dest = {
        'destinationId': 'admin_d_99',
        'title': 'Batu Caves Spiritual Tour',
        'type': 'Culture',
        'status': 'active',
        'location': 'Selangor, Malaysia'
    }
    with patch.dict('os.environ', {'FALLBACK_MODE': 'true'}), \
         patch('modules.fr03_destination_search_information.routes.retrieveRecord') as mock_retrieve:
        mock_retrieve.return_value = [custom_dest]

        res = client.get(
            '/api/fr3/destinations/search?q=batu',
            headers={'Authorization': 'Bearer valid_test_token'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert any(r.get('destinationId') == 'admin_d_99' for r in data['results'])

def test_destination_details_unknown_returns_none(client, mock_traveller_auth):
    with patch.dict('os.environ', {'FALLBACK_MODE': 'true'}), \
         patch('modules.fr03_destination_search_information.routes.retrieveRecord') as mock_retrieve:
        mock_retrieve.return_value = None
        res = client.get(
            '/api/fr3/destinations/unknown_destination_id_9999',
            headers={'Authorization': 'Bearer valid_test_token'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert data['destination'] is None
        assert data['detailsAvailable'] is False
