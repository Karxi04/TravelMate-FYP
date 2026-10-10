from unittest.mock import patch

from modules.fr07_flight_search.routes import reset_flight_quotes


def _provider_item():
    return {
        'flights': [{
            'airline': 'Demo Air',
            'flight_number': 'DA101',
            'departure_airport': {'id': 'KUL', 'name': 'Kuala Lumpur', 'date': '2026-11-01', 'time': '08:00'},
            'arrival_airport': {'id': 'PEN', 'name': 'Penang', 'date': '2026-11-01', 'time': '09:00'},
            'duration': 60,
        }],
        'price': 180,
        'currency': 'MYR',
    }


def test_provider_result_is_allowlisted_and_select_requires_owned_search(client, mock_traveller_auth):
    reset_flight_quotes()
    with patch('modules.fr07_flight_search.routes.retrieveFlightOptions', return_value={'items': [_provider_item()]}):
        response = client.get('/api/fr7/flights/search?departure_id=KUL&arrival_id=PEN&outbound_date=2026-11-01', headers={'Authorization': 'Bearer valid_test_token'})
    assert response.status_code == 200
    data = response.get_json()
    assert data['source'] == 'serpapi'
    assert data['items'][0]['priceBasis'] == 'provider_price_reference_unverified'
    assert 'raw' not in data['items'][0]
    assert data['items'][0]['outboundSegments'][0]['departureDate'] == '2026-11-01'

    itinerary = {'id': 'pu3a_trip', 'travellerId': 'test_traveller_uid', 'budgetLimit': 1000, 'travellerCount': 1, 'activities': []}
    with patch('modules.fr07_flight_search.routes.retrieveRecord', return_value=itinerary), patch('modules.fr07_flight_search.routes.updateRecord', side_effect=lambda c, i, p: {**itinerary, **p}):
        selected = client.post('/api/fr7/flights/select', headers={'Authorization': 'Bearer valid_test_token'}, json={'itineraryId': 'pu3a_trip', 'searchId': data['searchId'], 'optionId': data['items'][0]['id']})
    assert selected.status_code == 200
    assert selected.get_json()['itinerary']['flightCurrency'] == 'MYR'


def test_provider_failure_does_not_silently_use_sample_in_normal_mode(client, mock_traveller_auth, monkeypatch):
    monkeypatch.setenv('TRAVELMATE_TESTING', 'false')
    monkeypatch.setenv('FALLBACK_MODE', 'true')
    with patch('modules.fr07_flight_search.routes.retrieveFlightOptions', side_effect=RuntimeError('provider down')):
        response = client.get('/api/fr7/flights/search?departure_id=KUL&arrival_id=PEN&outbound_date=2026-11-01', headers={'Authorization': 'Bearer valid_test_token'})
    assert response.status_code == 502
    assert 'provider down' not in response.get_json()['error']


def test_round_trip_segments_remain_separate(client, mock_traveller_auth):
    item = _provider_item()
    item['outbound_flights'] = item.pop('flights')
    item['return_flights'] = [{
        'airline': 'Demo Air', 'flight_number': 'DA102',
        'departure_airport': {'id': 'PEN', 'name': 'Penang', 'date': '2026-11-05', 'time': '18:00'},
        'arrival_airport': {'id': 'KUL', 'name': 'Kuala Lumpur', 'date': '2026-11-05', 'time': '19:00'}, 'duration': 60,
    }]
    with patch('modules.fr07_flight_search.routes.retrieveFlightOptions', return_value={'items': [item]}):
        response = client.get('/api/fr7/flights/search?departure_id=KUL&arrival_id=PEN&outbound_date=2026-11-01&return_date=2026-11-05', headers={'Authorization': 'Bearer valid_test_token'})
    flight = response.get_json()['items'][0]
    assert flight['tripType'] == 'round_trip'
    assert flight['roundTripComplete'] is True
    assert flight['outboundSegments'][0]['arrivalAirportCode'] == 'PEN'
    assert flight['returnSegments'][0]['arrivalAirportCode'] == 'KUL'


def test_flight_remove_preserves_other_trip_content(client, mock_traveller_auth):
    itinerary = {'id': 'pu3a_remove', 'travellerId': 'test_traveller_uid', 'selectedFlight': {'id': 'x'}, 'flightCost': 180, 'hotelCost': 200, 'selectedHotel': {'name': 'Hotel'}, 'activities': []}
    with patch('modules.fr07_flight_search.routes.retrieveRecord', return_value=itinerary), patch('modules.fr07_flight_search.routes.updateRecord', side_effect=lambda c, i, p: {**itinerary, **p}):
        response = client.post('/api/fr7/itineraries/pu3a_remove/flight-selection/remove', headers={'Authorization': 'Bearer valid_test_token'})
    assert response.status_code == 200
    updated = response.get_json()['itinerary']
    assert updated['selectedFlight'] is None
    assert updated['selectedHotel']['name'] == 'Hotel'


def test_unknown_currency_cannot_enter_myr_budget(client, mock_traveller_auth, monkeypatch):
    monkeypatch.setenv('TRAVELMATE_TESTING', 'false')
    itinerary = {'id': 'pu3a_currency', 'travellerId': 'test_traveller_uid', 'activities': []}
    with patch('modules.fr07_flight_search.routes.retrieveRecord', return_value=itinerary):
        response = client.post('/api/fr7/flights/select', headers={'Authorization': 'Bearer valid_test_token'}, json={
            'itineraryId': 'pu3a_currency',
            'flight': {'id': 'legacy', 'price': 180, 'currency': 'USD', 'priceBasis': 'itinerary_total'},
        })
    assert response.status_code == 409

