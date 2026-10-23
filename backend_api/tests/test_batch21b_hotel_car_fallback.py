import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def _enable_hotel_sample_mode(monkeypatch):
    monkeypatch.setenv('FALLBACK_MODE', 'true')
    monkeypatch.setenv('HOTEL_SAMPLE_MODE', 'true')
    monkeypatch.setenv('TRAVELMATE_TESTING', 'true')


def test_places_search_fallback_generates_geographically_correct_slug(client, mock_traveller_auth):
    """Fallback places search must generate a state-specific placeId, never hardcode local_penang."""
    # Test Kuala Lumpur
    res_kl = client.get(
        '/api/fr8/places/search?q=Kuala+Lumpur',
        headers={'Authorization': 'Bearer test_token'},
    )
    assert res_kl.status_code == 200
    data_kl = res_kl.get_json()
    assert data_kl['ok'] is True
    assert data_kl['source'] == 'local'
    assert len(data_kl['result']['data']) >= 1
    place_kl = data_kl['result']['data'][0]
    assert place_kl['placeId'] == 'local_kuala_lumpur'
    assert place_kl['displayName'] == 'Kuala Lumpur'
    assert 'local_penang' not in place_kl['placeId']

    # Test Melaka
    res_melaka = client.get(
        '/api/fr8/places/search?q=Melaka',
        headers={'Authorization': 'Bearer test_token'},
    )
    assert res_melaka.status_code == 200
    data_melaka = res_melaka.get_json()
    place_melaka = data_melaka['result']['data'][0]
    assert place_melaka['placeId'] == 'local_melaka'

    # Test Penang
    res_penang = client.get(
        '/api/fr8/places/search?q=George+Town',
        headers={'Authorization': 'Bearer test_token'},
    )
    assert res_penang.status_code == 200
    place_penang = res_penang.get_json()['result']['data'][0]
    assert place_penang['placeId'] == 'local_penang'


def test_penang_hotel_search_returns_sample_hotels(client, mock_traveller_auth):
    """Searching Penang in sample fallback mode returns valid local sample hotels."""
    with patch(
        'modules.fr08_hotel_booking.routes.retrieveHotelOffers',
        side_effect=RuntimeError('Provider offline in test fallback'),
    ), patch(
        'modules.fr08_hotel_booking.routes._persist_quotes',
        side_effect=lambda items, *_: items,
    ):
        res = client.post(
            '/api/fr8/hotels/search',
            headers={'Authorization': 'Bearer test_token'},
            json={
                'destination': 'George Town, Penang',
                'checkin': '2026-11-10',
                'checkout': '2026-11-12',
                'adults': 2,
                'roomQuantity': 1,
            },
        )
    assert res.status_code == 200
    data = res.get_json()
    assert data['ok'] is True
    assert data['source'] == 'local'
    assert len(data['items']) > 0
    assert data['noResults'] is False
    assert data['sampleContentLimited'] is False
    # All returned properties must actually be in Penang
    for hotel in data['items']:
        assert any(term in hotel.get('address', '').lower() for term in ['penang', 'george town', 'weld quay', 'air itam', 'batu ferringhi'])


@pytest.mark.parametrize('destination_name', [
    'Kuala Lumpur',
    'Melaka',
    'Johor Bahru',
    'Ipoh',
    'Kota Kinabalu',
    'Kuching',
    'Langkawi',
])
def test_non_penang_hotel_search_never_leaks_penang_hotels(client, mock_traveller_auth, destination_name):
    """Fallback hotel search outside Penang must reject Penang inventory and report sample limitation."""
    with patch(
        'modules.fr08_hotel_booking.routes.retrieveHotelOffers',
        side_effect=RuntimeError('Provider offline in test fallback'),
    ):
        res = client.post(
            '/api/fr8/hotels/search',
            headers={'Authorization': 'Bearer test_token'},
            json={
                'destination': destination_name,
                'checkin': '2026-11-10',
                'checkout': '2026-11-12',
                'adults': 2,
                'roomQuantity': 1,
            },
        )
    assert res.status_code == 200
    data = res.get_json()
    assert data['ok'] is True
    assert data['source'] == 'local'
    # Zero items: Penang hotels must NEVER be presented as KL / Melaka / Sabah hotels!
    assert data['items'] == []
    assert data['noResults'] is True
    assert data['sampleContentLimited'] is True
    assert data['destination'] == destination_name


def test_hotel_search_with_non_penang_place_id_does_not_redirect_to_penang(client, mock_traveller_auth):
    """Passing placeId: 'local_kuala_lumpur' without destination must resolve to KL, not Penang."""
    with patch(
        'modules.fr08_hotel_booking.routes.retrieveHotelOffers',
        side_effect=RuntimeError('Provider offline in test fallback'),
    ):
        res = client.post(
            '/api/fr8/hotels/search',
            headers={'Authorization': 'Bearer test_token'},
            json={
                'placeId': 'local_kuala_lumpur',
                'checkin': '2026-11-10',
                'checkout': '2026-11-12',
                'adults': 2,
                'roomQuantity': 1,
            },
        )
    assert res.status_code == 200
    data = res.get_json()
    assert data['ok'] is True
    assert data['items'] == []
    assert data['noResults'] is True
    assert data['sampleContentLimited'] is True
    assert data['destination'] == 'Kuala Lumpur'


def test_car_rental_search_nationwide_pickup_locations(client, mock_traveller_auth):
    """Car rental search preserves requested Malaysian pickup locations without hardcoded Penang assumption."""
    for loc in ['Kuala Lumpur City Centre', 'Kota Kinabalu Airport', 'Kuching', 'Johor Bahru']:
        res = client.post(
            '/api/fr8/car-rentals/search',
            headers={'Authorization': 'Bearer test_token'},
            json={
                'pickupLocation': loc,
                'dropoffLocation': loc,
                'pickupDate': '2026-11-15',
                'dropoffDate': '2026-11-17',
                'driverCount': 1,
                'vehicleType': 'All',
            },
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert len(data['items']) == 3
        for item in data['items']:
            assert item['pickupLocation'] == loc
            assert item['rentalDays'] == 3
            assert item['sandbox'] is True


def test_car_rental_search_validation_fails_on_empty_location(client, mock_traveller_auth):
    """Car rental search rejects empty or missing pickup location."""
    res = client.post(
        '/api/fr8/car-rentals/search',
        headers={'Authorization': 'Bearer test_token'},
        json={
            'pickupLocation': '   ',
            'pickupDate': '2026-11-15',
            'dropoffDate': '2026-11-17',
            'driverCount': 1,
        },
    )
    assert res.status_code == 400
    data = res.get_json()
    assert data['ok'] is False
    assert 'required' in data['error'].lower()
