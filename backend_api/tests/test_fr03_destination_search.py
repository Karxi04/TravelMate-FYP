import pytest
from unittest.mock import patch

from modules.fr03_destination_search_information.routes import (
    _deduplicate_results,
    _provider_results,
    _result_kind,
)


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
    provider.assert_called_once_with(
        'temple',
        'Penang, Malaysia',
        {'latitude': 5.4141, 'longitude': 100.3288},
    )
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
        assert res.status_code == 502
        data = res.get_json()
        assert data['ok'] is False
        assert 'try again' in data['error'].lower()
        cache_write.assert_not_called()

def test_destination_search_includes_admin_destinations(
        client, mock_traveller_auth, isolated_destination_search):
    custom_dest = {
        'destinationId': 'admin_d_99',
        'title': 'Batu Ferringhi Spiritual Tour',
        'type': 'Culture',
        'status': 'active',
        'location': 'Batu Ferringhi, Penang, Malaysia'
    }
    provider, _cache_read, _cache_write = isolated_destination_search
    provider.side_effect = RuntimeError('provider unavailable in test')
    with patch.dict('os.environ', {'FALLBACK_MODE': 'true'}), \
         patch('modules.fr03_destination_search_information.routes.retrieveRecord') as mock_retrieve:
        mock_retrieve.return_value = [custom_dest]

        res = client.get(
            '/api/fr3/destinations/search?q=batu&location=Penang',
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


def test_provider_results_preserves_standard_local_result_contract():
    item = _provider_results({'local_results': [{
        'title': 'Chew Jetty',
        'place_id': 'local_place_id',
        'data_id': 'local_data_id',
        'type': 'Tourist attraction',
        'address': 'George Town, Penang, Malaysia',
    }]})[0]

    assert item['place_id'] == 'local_place_id'
    assert item['data_id'] == 'local_data_id'
    assert item['resultKind'] == 'attraction'
    assert item['source'] == 'serpapi'


def test_destination_search_normalizes_official_place_results_shape_for_penang_hill(
        client, mock_traveller_auth, isolated_destination_search):
    provider, _cache_read, _cache_write = isolated_destination_search
    # Mirrors documented SerpApi Google Maps place_results fields. The live
    # response body was not retained, so this fixture contains no copied data.
    provider.return_value = {'place_results': {
        'title': 'Penang Hill',
        'place_id': 'penang_hill_place_id',
        'data_id': 'penang_hill_data_id',
        'data_cid': '123456789',
        'type': 'Tourist attraction',
        'types': ['tourist_attraction', 'point_of_interest'],
        'address': 'Jalan Stesen Bukit Bendera, Air Itam, Penang, Malaysia',
        'gps_coordinates': {'latitude': 5.4085, 'longitude': 100.2771},
        'rating': 4.6,
        'reviews': 12000,
        'thumbnail': 'https://example.invalid/provider-thumbnail.jpg',
    }}

    response = client.get(
        '/api/fr3/destinations/search?q=Penang+Hill&location=Penang',
        headers={'Authorization': 'Bearer valid_test_token'},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['source'] == 'serpapi'
    assert payload['providerUnavailable'] is False
    assert len(payload['results']) == 1
    result = payload['results'][0]
    assert result['title'] == 'Penang Hill'
    assert result['place_id'] == 'penang_hill_place_id'
    assert result['data_id'] == 'penang_hill_data_id'
    assert result['data_cid'] == '123456789'
    assert result['gps_coordinates'] == {
        'latitude': 5.4085, 'longitude': 100.2771,
    }
    assert result['rating'] == 4.6
    assert result['reviews'] == 12000
    assert result['thumbnail'] == 'https://example.invalid/provider-thumbnail.jpg'
    assert result['resultKind'] == 'attraction'
    assert result['source'] == 'serpapi'


def test_destination_search_rejects_out_of_penang_direct_place_result(
        client, mock_traveller_auth, isolated_destination_search):
    provider, _cache_read, _cache_write = isolated_destination_search
    provider.return_value = {'place_results': {
        'title': 'Penang Hill Restaurant Kuala Lumpur',
        'place_id': 'outside_penang_place',
        'type': 'Restaurant',
        'address': 'Kuala Lumpur, Malaysia',
        'gps_coordinates': {'latitude': 3.1390, 'longitude': 101.6869},
    }}

    response = client.get(
        '/api/fr3/destinations/search?q=Penang+Hill&location=Penang',
        headers={'Authorization': 'Bearer valid_test_token'},
    )

    assert response.status_code == 200
    assert response.get_json()['results'] == []


def test_primary_provider_type_wins_over_food_related_secondary_labels():
    assert _result_kind({
        'type': 'Tourist attraction',
        'types': ['food', 'restaurant', 'point_of_interest'],
    }) == 'attraction'


def test_genuine_restaurant_primary_type_remains_a_restaurant():
    assert _result_kind({
        'type': 'Hawker stall',
        'types': ['food', 'point_of_interest'],
    }) == 'restaurant'


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


@pytest.mark.parametrize(('query', 'provider_title', 'provider_type', 'address'), [
    ('Georgetown', 'Chew Jetty', 'Tourist attraction',
     'George Town, Penang, Malaysia'),
    ('George Town', 'Pinang Peranakan Mansion', 'Museum',
     'George Town, Penang, Malaysia'),
    ('Penang Hill', 'Penang Hill', 'Tourist attraction',
     'Air Itam, Penang, Malaysia'),
    ('Bukit Mertajam', "St. Anne's Church", 'Church',
     'Bukit Mertajam, Penang, Malaysia'),
    ('Air Itam', 'Kek Lok Si Temple', 'Buddhist temple',
     'Air Itam, Penang, Malaysia'),
    ('curry me', 'Sister Curry Mee', 'Restaurant',
     'Air Itam, Penang, Malaysia'),
    ('curry mee', 'Sister Curry Mee', 'Restaurant',
     'Air Itam, Penang, Malaysia'),
    ('char koay teow', 'Siam Road Charcoal Char Koay Teow', 'Restaurant',
     'George Town, Penang, Malaysia'),
    ('temple', 'Dhammikarama Burmese Temple', 'Buddhist temple',
     'George Town, Penang, Malaysia'),
    ('Kek Lok Si', 'Kek Lok Si Temple', 'Buddhist temple',
     'Air Itam, Penang, Malaysia'),
    ('Penang attractions', 'Penang Hill', 'Tourist attraction',
     'Air Itam, Penang, Malaysia'),
    ('merta', 'Icon City', 'Shopping mall',
     'Bukit Mertajam, Penang, Malaysia'),
    ('georgetwn', 'Cheong Fatt Tze Mansion', 'Tourist attraction',
     'George Town, Penang, Malaysia'),
])
def test_general_penang_search_keeps_verified_provider_places(
        client, mock_traveller_auth, isolated_destination_search,
        query, provider_title, provider_type, address):
    provider, _cache_read, _cache_write = isolated_destination_search
    provider.return_value = {'local_results': [{
        'place_id': f'provider_{abs(hash(query))}',
        'title': provider_title,
        'type': provider_type,
        'address': address,
        'rating': 4.5,
    }]}

    response = client.get(
        '/api/fr3/destinations/search',
        query_string={'q': query, 'location': 'Penang'},
        headers={'Authorization': 'Bearer valid_test_token'},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert [item['title'] for item in payload['results']] == [provider_title]
    assert payload['results'][0]['normalizedGeography']['state'] == 'Penang'
    assert '_providerOrder' not in payload['results'][0]


def test_area_query_uses_broad_provider_discovery_without_returning_fake_area(
        client, mock_traveller_auth, isolated_destination_search):
    provider, _cache_read, _cache_write = isolated_destination_search
    provider.return_value = {'local_results': [{
        'place_id': 'provider_chew_jetty',
        'title': 'Chew Jetty',
        'type': 'Tourist attraction',
        'position': {'lat': 5.4110, 'lng': 100.3408},
    }]}

    response = client.get(
        '/api/fr3/destinations/search?q=Georgetown&location=Penang',
        headers={'Authorization': 'Bearer valid_test_token'},
    )

    assert response.status_code == 200
    provider.assert_called_once_with(
        'places to visit George Town',
        'Penang, Malaysia',
        {'latitude': 5.4141, 'longitude': 100.3288},
    )
    assert response.get_json()['results'][0]['title'] == 'Chew Jetty'


def test_mainland_penang_coordinates_are_in_scope(
        client, mock_traveller_auth, isolated_destination_search):
    provider, _cache_read, _cache_write = isolated_destination_search
    provider.return_value = {'local_results': [{
        'place_id': 'mainland_poi',
        'title': 'Bukit Mertajam Recreational Forest',
        'type': 'Park',
        'gps_coordinates': {'latitude': 5.356, 'longitude': 100.474},
    }]}

    response = client.get(
        '/api/fr3/destinations/search?q=forest&location=Bukit+Mertajam',
        headers={'Authorization': 'Bearer valid_test_token'},
    )

    assert response.status_code == 200
    result = response.get_json()['results'][0]
    assert result['normalizedGeography']['state'] == 'Penang'
    assert result['normalizedGeography']['evidence'] == 'coordinates'


def test_food_filter_keeps_restaurants_and_excludes_attractions(
        client, mock_traveller_auth, isolated_destination_search):
    provider, _cache_read, _cache_write = isolated_destination_search
    provider.return_value = {'local_results': [
        {
            'place_id': 'food_1', 'title': 'Sister Curry Mee',
            'type': 'Restaurant', 'address': 'Air Itam, Penang, Malaysia',
        },
        {
            'place_id': 'attraction_1', 'title': 'Penang Hill',
            'type': 'Tourist attraction',
            'address': 'Air Itam, Penang, Malaysia',
        },
    ]}

    response = client.get(
        '/api/fr3/destinations/search?q=curry+mee&location=Penang&filter=food',
        headers={'Authorization': 'Bearer valid_test_token'},
    )

    assert response.status_code == 200
    assert [item['place_id'] for item in response.get_json()['results']] == [
        'food_1'
    ]


def test_provider_relevance_precedes_rating_for_dish_results(
        client, mock_traveller_auth, isolated_destination_search):
    provider, _cache_read, _cache_write = isolated_destination_search
    provider.return_value = {'local_results': [
        {
            'place_id': 'provider_food', 'title': 'Local Food Corner',
            'type': 'Restaurant', 'rating': 4.0,
            'address': 'Air Itam, Penang, Malaysia',
        },
        {
            'place_id': 'unrelated_high_rating', 'title': 'Scenic Viewpoint',
            'type': 'Tourist attraction', 'rating': 5.0,
            'address': 'Air Itam, Penang, Malaysia',
        },
    ]}

    response = client.get(
        '/api/fr3/destinations/search?q=curry+mee&location=Penang',
        headers={'Authorization': 'Bearer valid_test_token'},
    )

    assert response.status_code == 200
    assert [item['place_id'] for item in response.get_json()['results']] == [
        'provider_food', 'unrelated_high_rating'
    ]


def test_search_rejects_non_penang_and_preserves_same_name_elsewhere(
        client, mock_traveller_auth, isolated_destination_search):
    provider, _cache_read, _cache_write = isolated_destination_search
    provider.return_value = {'local_results': [
        {
            'place_id': 'penang_cafe', 'title': 'Heritage Cafe',
            'type': 'Cafe', 'address': 'George Town, Penang, Malaysia',
        },
        {
            'place_id': 'kl_cafe', 'title': 'Heritage Cafe',
            'type': 'Cafe', 'address': 'Kuala Lumpur, Malaysia',
        },
    ]}

    response = client.get(
        '/api/fr3/destinations/search?q=heritage+cafe&location=Malaysia',
        headers={'Authorization': 'Bearer valid_test_token'},
    )

    assert response.status_code == 200
    assert [item['place_id'] for item in response.get_json()['results']] == [
        'penang_cafe'
    ]


def test_malformed_provider_response_is_retryable_not_false_empty(
        client, mock_traveller_auth, isolated_destination_search):
    provider, _cache_read, _cache_write = isolated_destination_search
    provider.return_value = {'unexpected': []}

    with patch.dict('os.environ', {'FALLBACK_MODE': 'true'}):
        response = client.get(
            '/api/fr3/destinations/search?q=restaurant&location=Penang',
            headers={'Authorization': 'Bearer valid_test_token'},
        )

    assert response.status_code == 502
    assert response.get_json()['ok'] is False


def test_provider_reported_error_is_not_catalogue_fallback(
        client, mock_traveller_auth, isolated_destination_search):
    provider, _cache_read, cache_write = isolated_destination_search
    provider.return_value = {'error': 'provider diagnostic must stay private'}

    with patch.dict('os.environ', {'FALLBACK_MODE': 'true'}):
        response = client.get(
            '/api/fr3/destinations/search?q=Penang+Hill&location=Penang',
            headers={'Authorization': 'Bearer valid_test_token'},
        )

    assert response.status_code == 502
    payload = response.get_json()
    assert payload['ok'] is False
    assert 'unsupported response' in payload['error'].lower()
    assert 'provider diagnostic' not in payload['error']
    cache_write.assert_not_called()


def test_provider_failure_without_matching_fallback_is_not_false_no_results(
        client, mock_traveller_auth, isolated_destination_search):
    provider, _cache_read, _cache_write = isolated_destination_search
    provider.side_effect = RuntimeError('provider unavailable')

    with patch.dict('os.environ', {'FALLBACK_MODE': 'true'}):
        response = client.get(
            '/api/fr3/destinations/search?q=curry+mee&location=Penang',
            headers={'Authorization': 'Bearer valid_test_token'},
        )

    assert response.status_code == 502
    assert response.get_json()['ok'] is False


def test_empty_query_is_rejected(client, mock_traveller_auth):
    response = client.get(
        '/api/fr3/destinations/search?q=',
        headers={'Authorization': 'Bearer valid_test_token'},
    )

    assert response.status_code == 400
