import pytest
from unittest.mock import patch


@pytest.fixture
def isolated_destination_search():
    """Keep FR03 deterministic and prevent provider/cache writes."""
    provider_result = {
        'local_results': [
            {
                'place_id': 'test_kek_lok_si',
                'title': 'Kek Lok Si Temple',
                'type': 'Tourist attraction',
                'address': 'Air Itam, Penang, Malaysia',
            }
        ]
    }
    with patch(
        'modules.fr03_destination_search_information.routes.retrieveDestinationResults',
        return_value=provider_result,
    ) as provider, patch(
        'modules.fr03_destination_search_information.routes.retrieveRecord',
        return_value=[],
    ) as cache_read, patch(
        'modules.fr03_destination_search_information.routes.storeRecord',
        side_effect=lambda _collection, data, *_args, **_kwargs: dict(data),
    ) as cache_write:
        yield provider, cache_read, cache_write


def test_destination_search_keyword_match(
        client, mock_traveller_auth, isolated_destination_search):
    provider, _cache_read, cache_write = isolated_destination_search
    res = client.get(
        '/api/fr3/destinations/search?q=temple',
        headers={'Authorization': 'Bearer valid_test_token'}
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data['ok'] is True
    assert data['source'] == 'serpapi'
    assert len(data['results']) == 1
    assert data['results'][0]['destinationId'] == 'test_kek_lok_si'
    assert 'temple' in data['results'][0]['title'].lower()
    provider.assert_called_once_with('temple', 'Malaysia')
    cache_write.assert_called_once()

def test_destination_search_no_irrelevant_dump(
        client, mock_traveller_auth, isolated_destination_search):
    provider, _cache_read, cache_write = isolated_destination_search
    provider.side_effect = RuntimeError('provider unavailable in test')
    with patch.dict('os.environ', {'FALLBACK_MODE': 'true'}):
        res = client.get(
            '/api/fr3/destinations/search?q=completely_nonexistent_destination_xyz',
            headers={'Authorization': 'Bearer valid_test_token'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert len(data['results']) == 0
        cache_write.assert_not_called()

def test_destination_search_includes_admin_destinations(
        client, mock_traveller_auth, isolated_destination_search):
    custom_dest = {
        'destinationId': 'admin_d_99',
        'title': 'Batu Caves Spiritual Tour',
        'type': 'Culture',
        'status': 'active',
        'location': 'Selangor, Malaysia'
    }
    provider, _cache_read, _cache_write = isolated_destination_search
    provider.side_effect = RuntimeError('provider unavailable in test')
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
