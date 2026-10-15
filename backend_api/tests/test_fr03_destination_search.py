import pytest
from unittest.mock import patch

from modules.fr03_destination_search_information.routes import _deduplicate_results


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


def test_destination_search_exact_alias_outranks_more_popular_partial(
        client, mock_traveller_auth, isolated_destination_search):
    provider, _cache_read, _cache_write = isolated_destination_search
    provider.return_value = {'local_results': [
        {
            'place_id': 'food_trail', 'title': 'George Town Food Trail',
            'rating': 4.9, 'address': 'George Town, Penang, Malaysia',
        },
        {
            'place_id': 'george_town', 'title': 'George Town',
            'rating': 4.2, 'address': 'Penang, Malaysia',
        },
    ]}

    response = client.get(
        '/api/fr3/destinations/search?q=georgetown&location=Penang',
        headers={'Authorization': 'Bearer valid_test_token'},
    )

    assert response.status_code == 200
    results = response.get_json()['results']
    assert [item['place_id'] for item in results] == ['george_town', 'food_trail']


def test_destination_search_deduplicates_provider_identity_and_rejects_wrong_state(
        client, mock_traveller_auth, isolated_destination_search):
    provider, _cache_read, _cache_write = isolated_destination_search
    provider.return_value = {'local_results': [
        {
            'place_id': 'shared_place', 'title': 'Penang Hill',
            'address': 'Air Itam, Penang, Malaysia',
        },
        {
            'place_id': 'shared_place', 'title': 'Penang Hill duplicate',
            'address': 'Air Itam, Penang, Malaysia',
        },
        {
            'place_id': 'wrong_state', 'title': 'Hill View',
            'address': 'Johor Bahru, Johor, Malaysia',
        },
    ]}

    response = client.get(
        '/api/fr3/destinations/search?q=hill&location=Penang',
        headers={'Authorization': 'Bearer valid_test_token'},
    )

    assert response.status_code == 200
    results = response.get_json()['results']
    assert [item['place_id'] for item in results] == ['shared_place']
    assert response.get_json()['locationUsed'] == 'Penang, Malaysia'


def test_destination_search_alias_is_normalized_inside_partial_names(
        client, mock_traveller_auth, isolated_destination_search):
    provider, _cache_read, _cache_write = isolated_destination_search
    provider.return_value = {'local_results': [
        {
            'place_id': 'heritage_walk',
            'title': 'George Town Heritage Walk',
            'address': 'George Town, Penang, Malaysia',
        },
        {
            'place_id': 'generic_walk',
            'title': 'Malaysian Heritage Walk',
            'address': 'George Town, Penang, Malaysia',
        },
    ]}

    response = client.get(
        '/api/fr3/destinations/search?q=georgetown heritage&location=Penang',
        headers={'Authorization': 'Bearer valid_test_token'},
    )

    assert response.status_code == 200
    assert response.get_json()['results'][0]['place_id'] == 'heritage_walk'


@pytest.mark.parametrize(('query', 'title', 'expected_id'), [
    ('georgetown', 'George Town', 'provider_george_town'),
    ('George Town', 'George Town', 'provider_george_town'),
    ('Penang Hill', 'Penang Hill', 'provider_penang_hill'),
])
def test_destination_search_supplements_missing_provider_geography_from_known_place(
        client, mock_traveller_auth, isolated_destination_search,
        query, title, expected_id):
    provider, _cache_read, _cache_write = isolated_destination_search
    provider.return_value = {'local_results': [{
        'place_id': expected_id,
        'title': title,
        'rating': 4.7,
    }]}

    response = client.get(
        f'/api/fr3/destinations/search?q={query}&location=Penang',
        headers={'Authorization': 'Bearer valid_test_token'},
    )

    assert response.status_code == 200
    results = response.get_json()['results']
    assert len(results) == 1
    assert results[0]['place_id'] == expected_id
    assert results[0]['normalizedGeography']['state'] == 'Penang'


def test_destination_search_deduplicates_kek_lok_si_across_provider_ids_and_addresses(
        client, mock_traveller_auth, isolated_destination_search):
    provider, _cache_read, _cache_write = isolated_destination_search
    provider.return_value = {'local_results': [
        {
            'place_id': 'provider_kek_1',
            'title': 'Kek Lok Si Temple',
            'address': 'Air Itam, Penang, Malaysia',
        },
        {
            'data_id': 'provider_kek_2',
            'title': 'Kek Lok Si',
            'address': 'Ayer Itam, Pulau Pinang',
        },
    ]}

    response = client.get(
        '/api/fr3/destinations/search?q=Kek+Lok+Si&location=Penang',
        headers={'Authorization': 'Bearer valid_test_token'},
    )

    assert response.status_code == 200
    assert len(response.get_json()['results']) == 1


def test_destination_search_keeps_penang_attractions_and_rejects_other_states(
        client, mock_traveller_auth, isolated_destination_search):
    provider, _cache_read, _cache_write = isolated_destination_search
    provider.return_value = {'local_results': [
        {
            'place_id': 'penang_hill_provider',
            'title': 'Penang Hill',
        },
        {
            'place_id': 'johor_attraction',
            'title': 'Johor Heritage Attraction',
            'address': 'Johor Bahru, Johor, Malaysia',
        },
    ]}

    response = client.get(
        '/api/fr3/destinations/search?q=Penang+attraction&location=Penang',
        headers={'Authorization': 'Bearer valid_test_token'},
    )

    assert response.status_code == 200
    assert [item['place_id'] for item in response.get_json()['results']] == [
        'penang_hill_provider'
    ]


def test_destination_search_provider_failure_is_retryable_without_raw_exception(
        client, mock_traveller_auth, isolated_destination_search):
    provider, _cache_read, _cache_write = isolated_destination_search
    provider.side_effect = RuntimeError('secret provider diagnostics')

    with patch.dict('os.environ', {'FALLBACK_MODE': 'false'}):
        response = client.get(
            '/api/fr3/destinations/search?q=Penang+Hill&location=Penang',
            headers={'Authorization': 'Bearer valid_test_token'},
        )

    assert response.status_code == 502
    payload = response.get_json()
    assert payload['ok'] is False
    assert 'try again' in payload['error'].lower()
    assert 'secret provider diagnostics' not in payload['error']


def test_destination_search_empty_provider_result_is_not_fabricated(
        client, mock_traveller_auth, isolated_destination_search):
    provider, _cache_read, _cache_write = isolated_destination_search
    provider.return_value = {'local_results': []}

    response = client.get(
        '/api/fr3/destinations/search?q=Penang+Hill&location=Penang',
        headers={'Authorization': 'Bearer valid_test_token'},
    )

    assert response.status_code == 200
    assert response.get_json()['results'] == []


def test_nearby_excludes_same_kek_lok_si_identity_but_keeps_distinct_places(
        client, mock_traveller_auth):
    cached_base = {
        'place_id': 'provider_kek_lok_si',
        'title': 'Kek Lok Si',
        'address': 'Ayer Itam, Pulau Pinang',
        'gps_coordinates': {'latitude': 5.3995, 'longitude': 100.2730},
    }

    def retrieve(collection, *_args, **_kwargs):
        if collection == 'destination_cache':
            return cached_base
        return []

    with patch(
        'modules.fr03_destination_search_information.routes.retrieveRecord',
        side_effect=retrieve,
    ), patch(
        'modules.fr03_destination_search_information.routes.storeRecord',
        side_effect=lambda _collection, data, *_args, **_kwargs: dict(data),
    ):
        response = client.get(
            '/api/fr3/destinations/provider_kek_lok_si/nearby?radiusKm=12',
            headers={'Authorization': 'Bearer valid_test_token'},
        )

    assert response.status_code == 200
    items = response.get_json()['items']
    titles = [item['title'] for item in items]
    assert 'Kek Lok Si Temple' not in titles
    assert 'Penang Hill' in titles
    assert len(items) > 1


def test_deduplication_preserves_same_named_places_with_verified_distant_coordinates():
    items = _deduplicate_results([
        {
            'place_id': 'penang_viewpoint',
            'title': 'Central Viewpoint',
            'gps_coordinates': {'latitude': 5.4, 'longitude': 100.3},
        },
        {
            'place_id': 'kl_viewpoint',
            'title': 'Central Viewpoint',
            'gps_coordinates': {'latitude': 3.1, 'longitude': 101.7},
        },
    ])

    assert [item['place_id'] for item in items] == [
        'penang_viewpoint', 'kl_viewpoint'
    ]


def test_deduplication_preserves_distinct_places_inside_kek_lok_si_complex():
    items = _deduplicate_results([
        {
            'place_id': 'kek_lok_si_temple',
            'title': 'Kek Lok Si Temple',
            'gps_coordinates': {'latitude': 5.3995, 'longitude': 100.2730},
        },
        {
            'place_id': 'pagoda_ten_thousand_buddhas',
            'title': 'Pagoda of Ten Thousand Buddhas',
            'gps_coordinates': {'latitude': 5.3993, 'longitude': 100.2734},
        },
    ])

    assert [item['place_id'] for item in items] == [
        'kek_lok_si_temple', 'pagoda_ten_thousand_buddhas'
    ]
