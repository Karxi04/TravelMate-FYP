import pytest
from unittest.mock import patch

def test_flight_search_with_iata_codes(client, mock_traveller_auth):
    with patch.dict('os.environ', {'FALLBACK_MODE': 'true'}):
        res = client.get(
            '/api/fr7/flights/search?departure_id=KUL&arrival_id=PEN&outbound_date=2026-10-01',
            headers={'Authorization': 'Bearer valid_test_token'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert len(data['items']) > 0
        assert data['items'][0]['departureAirport'] == 'KUL'
        assert data['items'][0]['arrivalAirport'] == 'PEN'

def test_flight_search_resolves_city_names(client, mock_traveller_auth):
    with patch.dict('os.environ', {'FALLBACK_MODE': 'true'}):
        res = client.get(
            '/api/fr7/flights/search?departure_id=Kuala Lumpur&arrival_id=Penang&outbound_date=2026-10-01',
            headers={'Authorization': 'Bearer valid_test_token'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert len(data['items']) > 0
        assert data['items'][0]['departureAirport'] == 'KUL'
        assert data['items'][0]['arrivalAirport'] == 'PEN'

def test_flight_select_updates_itinerary(client, mock_traveller_auth):
    sample_itinerary = {
        'id': 'itin_flight_1',
        'travellerId': 'test_traveller_uid',
        'title': 'Penang Flight Test',
        'startDate': '2026-10-01',
        'endDate': '2026-10-04',
        'travellerCount': 1,
        'budgetLimit': 1000,
        'flightCost': 0,
        'hotelCost': 0,
        'activities': []
    }
    flight_to_select = {
        'flightNumber': 'MH1140',
        'airline': 'Malaysia Airlines',
        'price': 180.0,
        'departureAirport': 'KUL',
        'arrivalAirport': 'PEN'
    }

    with patch('modules.fr07_flight_search.routes.retrieveRecord') as mock_retrieve, \
         patch('modules.fr07_flight_search.routes.updateRecord') as mock_update:
        mock_retrieve.return_value = sample_itinerary
        mock_update.side_effect = lambda coll, doc_id, patch_data: {**sample_itinerary, **patch_data}

        res = client.post(
            '/api/fr7/flights/select',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={
                'itineraryId': 'itin_flight_1',
                'flight': flight_to_select
            }
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert data['itinerary']['flightCost'] == 180.0
        assert data['selectedFlight']['flightNumber'] == 'MH1140'
