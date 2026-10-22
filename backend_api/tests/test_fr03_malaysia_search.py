import pytest
from unittest.mock import patch


@pytest.fixture
def isolated_destination_search():
    with patch('modules.fr03_destination_search_information.routes.retrieveDestinationResults') as mock_provider, \
         patch('modules.fr03_destination_search_information.routes.retrieveRecord') as mock_db_read, \
         patch('modules.fr03_destination_search_information.routes.storeRecord') as mock_db_write:
        mock_db_read.return_value = None
        yield mock_provider, mock_db_read, mock_db_write


MALAYSIAN_DIVISIONS = [
    ('Johor', 'Johor', 'Johor, Malaysia'),
    ('Kedah', 'Kedah', 'Kedah, Malaysia'),
    ('Kelantan', 'Kelantan', 'Kelantan, Malaysia'),
    ('Melaka', 'Melaka', 'Melaka City, Melaka, Malaysia'),
    ('Negeri Sembilan', 'Negeri Sembilan', 'Negeri Sembilan, Malaysia'),
    ('Pahang', 'Pahang', 'Pahang, Malaysia'),
    ('Penang', 'Penang', 'Penang, Malaysia'),
    ('Perak', 'Perak', 'Perak, Malaysia'),
    ('Perlis', 'Perlis', 'Perlis, Malaysia'),
    ('Sabah', 'Sabah', 'Sabah, Malaysia'),
    ('Sarawak', 'Sarawak', 'Sarawak, Malaysia'),
    ('Selangor', 'Selangor', 'Selangor, Malaysia'),
    ('Terengganu', 'Terengganu', 'Terengganu, Malaysia'),
    ('Kuala Lumpur', 'Kuala Lumpur', 'Kuala Lumpur, Kuala Lumpur, Malaysia'),
    ('Putrajaya', 'Putrajaya', 'Putrajaya, Putrajaya, Malaysia'),
    ('Labuan', 'Labuan', 'Labuan, Labuan, Malaysia'),
]


@pytest.mark.parametrize('location_input,expected_state,expected_canonical', MALAYSIAN_DIVISIONS)
def test_all_13_states_and_3_federal_territories_search(
        client, mock_traveller_auth, isolated_destination_search,
        location_input, expected_state, expected_canonical):
    provider, _cache_read, _cache_write = isolated_destination_search
    provider.return_value = {'local_results': [
        {
            'place_id': f'poi_{expected_state.lower().replace(" ", "_")}',
            'title': f'Attraction in {expected_state}',
            'address': f'City Centre, {expected_state}, Malaysia',
        }
    ]}

    response = client.get(
        f'/api/fr3/destinations/search?q=attractions&location={location_input}',
        headers={'Authorization': 'Bearer valid_test_token'},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data['ok'] is True
    assert data['locationUsed'] == expected_canonical
    assert len(data['results']) == 1
    assert data['results'][0]['normalizedGeography']['state'] == expected_state


# 30 Representative Scenarios from Section 8
SECTION_8_SCENARIOS = [
    (1, "Penang", "Penang", True, False),
    (2, "George Town", "Penang", True, False),
    (3, "Butterworth", "Penang", True, False),
    (4, "Kuala Lumpur", "Kuala Lumpur", True, False),
    (5, "Bukit Bintang", "Kuala Lumpur", True, False),
    (6, "Petaling Jaya", "Selangor", True, False),
    (7, "Shah Alam", "Selangor", True, False),
    (8, "Putrajaya", "Putrajaya", True, False),
    (9, "Melaka", "Melaka", True, False),
    (10, "Ipoh", "Perak", True, False),
    (11, "Langkawi", "Kedah", True, False),
    (12, "Alor Setar", "Kedah", True, False),
    (13, "Johor Bahru", "Johor", True, False),
    (14, "Kota Bharu", "Kelantan", True, False),
    (15, "Kuantan", "Pahang", True, False),
    (16, "Cameron Highlands", "Pahang", True, False),
    (17, "Kuala Terengganu", "Terengganu", True, False),
    (18, "Kangar", "Perlis", True, False),
    (19, "Seremban", "Negeri Sembilan", True, False),
    (20, "Kota Kinabalu", "Sabah", True, False),
    (21, "Kundasang", "Sabah", True, False),
    (22, "Kuching", "Sarawak", True, False),
    (23, "Miri", "Sarawak", True, False),
    (24, "Labuan", "Labuan", True, False),
    (25, "Singapore", None, False, True),
    (26, "Bangkok", None, False, True),
    (27, "Tokyo", None, False, True),
    (28, "Tanjung", None, False, False),  # Ambiguous locality
    (29, "CompletelyUnknownXyz123", None, False, False),  # Unknown
    (30, "", "Penang", True, False),  # No location supplied -> defaults to Penang
]


@pytest.mark.parametrize('idx,location_input,expected_state,is_malaysia,is_foreign', SECTION_8_SCENARIOS)
def test_section_8_representative_scenarios(
        client, mock_traveller_auth, isolated_destination_search,
        idx, location_input, expected_state, is_malaysia, is_foreign):
    provider, _cache_read, _cache_write = isolated_destination_search

    if is_malaysia:
        provider.return_value = {'local_results': [
            {
                'place_id': f'place_{idx}',
                'title': f'Place in {location_input or "Penang"}',
                'address': f'{location_input or "Penang"}, Malaysia',
            }
        ]}
        url = f'/api/fr3/destinations/search?q=place&location={location_input}' if location_input else '/api/fr3/destinations/search?q=place'
        response = client.get(url, headers={'Authorization': 'Bearer valid_test_token'})
        assert response.status_code == 200
        data = response.get_json()
        assert data['ok'] is True
        assert len(data['results']) == 1
        assert data['results'][0]['normalizedGeography']['state'] == expected_state
    elif is_foreign:
        response = client.get(
            f'/api/fr3/destinations/search?q=place&location={location_input}',
            headers={'Authorization': 'Bearer valid_test_token'},
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data['ok'] is False
        assert "TravelMate is dedicated exclusively to travel planning within Malaysia" in data['error']
    else:
        # Ambiguous or unresolvable
        response = client.get(
            f'/api/fr3/destinations/search?q=place&location={location_input}',
            headers={'Authorization': 'Bearer valid_test_token'},
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data['ok'] is False
        assert "could not be resolved as a Malaysian destination" in data['error']


def test_geographic_filtering_prevents_cross_state_contamination(
        client, mock_traveller_auth, isolated_destination_search):
    provider, _cache_read, _cache_write = isolated_destination_search
    provider.return_value = {'local_results': [
        {
            'place_id': 'kl_tower',
            'title': 'Kuala Lumpur Tower',
            'address': 'Bukit Nanas, Kuala Lumpur, Malaysia',
        },
        {
            'place_id': 'penang_hill',
            'title': 'Penang Hill',
            'address': 'Air Itam, Penang, Malaysia',
        },
        {
            'place_id': 'melaka_famosa',
            'title': 'A Famosa',
            'address': 'Bandar Hilir, Melaka, Malaysia',
        },
        {
            'place_id': 'kk_mosque',
            'title': 'Kota Kinabalu City Mosque',
            'address': 'Likas Bay, Kota Kinabalu, Sabah, Malaysia',
        },
    ]}

    # Query 1: Kuala Lumpur -> only KL returned
    res_kl = client.get(
        '/api/fr3/destinations/search?q=landmark&location=Kuala+Lumpur',
        headers={'Authorization': 'Bearer valid_test_token'},
    )
    assert res_kl.status_code == 200
    ids_kl = [x['place_id'] for x in res_kl.get_json()['results']]
    assert ids_kl == ['kl_tower']

    # Query 2: Melaka -> only Melaka returned
    res_mel = client.get(
        '/api/fr3/destinations/search?q=landmark&location=Melaka',
        headers={'Authorization': 'Bearer valid_test_token'},
    )
    assert res_mel.status_code == 200
    ids_mel = [x['place_id'] for x in res_mel.get_json()['results']]
    assert ids_mel == ['melaka_famosa']

    # Query 3: Sabah -> only Sabah returned
    res_sab = client.get(
        '/api/fr3/destinations/search?q=landmark&location=Sabah',
        headers={'Authorization': 'Bearer valid_test_token'},
    )
    assert res_sab.status_code == 200
    ids_sab = [x['place_id'] for x in res_sab.get_json()['results']]
    assert ids_sab == ['kk_mosque']

    # Query 4: Penang -> only Penang returned
    res_pen = client.get(
        '/api/fr3/destinations/search?q=landmark&location=Penang',
        headers={'Authorization': 'Bearer valid_test_token'},
    )
    assert res_pen.status_code == 200
    ids_pen = [x['place_id'] for x in res_pen.get_json()['results']]
    assert ids_pen == ['penang_hill']

    # Query 5: Malaysia (nationwide) -> all 4 Malaysian landmarks returned
    res_my = client.get(
        '/api/fr3/destinations/search?q=landmark&location=Malaysia',
        headers={'Authorization': 'Bearer valid_test_token'},
    )
    assert res_my.status_code == 200
    ids_my = [x['place_id'] for x in res_my.get_json()['results']]
    assert set(ids_my) == {'kl_tower', 'penang_hill', 'melaka_famosa', 'kk_mosque'}


def test_fallback_search_across_multiple_malaysian_regions(
        client, mock_traveller_auth):
    # Simulate SerpApi failure to trigger offline fallback mode
    with patch('modules.fr03_destination_search_information.routes.retrieveDestinationResults', side_effect=RuntimeError('Provider offline')), \
         patch('modules.fr03_destination_search_information.routes._fallback_mode', return_value=True), \
         patch('modules.fr03_destination_search_information.routes.retrieveRecord', return_value=None), \
         patch('modules.fr03_destination_search_information.routes.storeRecord') as _mock_write:

        # 1. Kuala Lumpur fallback match
        res_kl = client.get(
            '/api/fr3/destinations/search?q=Petronas&location=Kuala+Lumpur',
            headers={'Authorization': 'Bearer valid_test_token'},
        )
        assert res_kl.status_code == 200
        data_kl = res_kl.get_json()
        assert data_kl['source'] == 'local'
        assert any('Petronas' in x['title'] for x in data_kl['results'])
        assert all(x['normalizedGeography']['state'] == 'Kuala Lumpur' for x in data_kl['results'])

        # 2. Melaka fallback match
        res_mel = client.get(
            '/api/fr3/destinations/search?q=Jonker&location=Melaka',
            headers={'Authorization': 'Bearer valid_test_token'},
        )
        assert res_mel.status_code == 200
        data_mel = res_mel.get_json()
        assert data_mel['source'] == 'local'
        assert any('Jonker' in x['title'] for x in data_mel['results'])
        assert all(x['normalizedGeography']['state'] == 'Melaka' for x in data_mel['results'])

        # 3. Langkawi fallback match
        res_lkw = client.get(
            '/api/fr3/destinations/search?q=SkyCab&location=Langkawi',
            headers={'Authorization': 'Bearer valid_test_token'},
        )
        assert res_lkw.status_code == 200
        data_lkw = res_lkw.get_json()
        assert data_lkw['source'] == 'local'
        assert any('SkyCab' in x['title'] for x in data_lkw['results'])
        assert all(x['normalizedGeography']['state'] == 'Kedah' for x in data_lkw['results'])

        # 4. Sabah fallback match
        res_sab = client.get(
            '/api/fr3/destinations/search?q=Kinabalu&location=Sabah',
            headers={'Authorization': 'Bearer valid_test_token'},
        )
        assert res_sab.status_code == 200
        data_sab = res_sab.get_json()
        assert data_sab['source'] == 'local'
        assert any('Kinabalu' in x['title'] for x in data_sab['results'])
        assert all(x['normalizedGeography']['state'] == 'Sabah' for x in data_sab['results'])

        # 5. Sarawak fallback match
        res_srw = client.get(
            '/api/fr3/destinations/search?q=Bako&location=Sarawak',
            headers={'Authorization': 'Bearer valid_test_token'},
        )
        assert res_srw.status_code == 200
        data_srw = res_srw.get_json()
        assert data_srw['source'] == 'local'
        assert any('Bako' in x['title'] for x in data_srw['results'])
        assert all(x['normalizedGeography']['state'] == 'Sarawak' for x in data_srw['results'])

        # 6. Penang fallback match
        res_pen = client.get(
            '/api/fr3/destinations/search?q=Kek+Lok+Si&location=Penang',
            headers={'Authorization': 'Bearer valid_test_token'},
        )
        assert res_pen.status_code == 200
        data_pen = res_pen.get_json()
        assert data_pen['source'] == 'local'
        assert any('Kek Lok Si' in x['title'] for x in data_pen['results'])
        assert all(x['normalizedGeography']['state'] == 'Penang' for x in data_pen['results'])
