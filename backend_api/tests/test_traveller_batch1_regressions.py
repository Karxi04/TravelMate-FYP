from copy import deepcopy
from datetime import date, timedelta
from unittest.mock import patch
import pytest
from flask import g
from sequence_contract.validators import validateFlightSearchCriteria
from modules.fr08_hotel_booking.routes import _attach_booking_to_itinerary

HEADERS = {'Authorization': 'Bearer valid_test_token'}
DAY = (date.today() + timedelta(days=30)).isoformat()

@pytest.mark.parametrize('change,message', [
    ({'departure_id': ''}, 'origin'),
    ({'arrival_id': ''}, 'destination'),
    ({'departure_id': 'ZZZ'}, 'supported'),
    ({'departure_id': '123'}, 'supported'),
    ({'departure_id': 'KU'}, 'supported'),
    ({'departure_id': 'random Penang text'}, 'supported'),
    ({'arrival_id': 'KUL'}, 'different'),
    ({'outbound_date': '2000-01-01'}, 'departure date'),
    ({'outbound_date': '2030-02-30'}, 'departure date'),
    ({'return_date': '2000-01-01'}, 'Return date'),
    ({'return_date': 'not-a-date'}, 'Return date'),
    ({'traveller_count': '0'}, 'positive whole'),
    ({'traveller_count': '1.5'}, 'positive whole'),
    ({'travel_class': '5'}, 'travel_class'),
])
def test_invalid_search_never_calls_provider(client, mock_traveller_auth, change, message):
    query = dict(departure_id='KUL', arrival_id='PEN', outbound_date=DAY, **{})
    query.update(change)
    with patch('modules.fr07_flight_search.routes.retrieveFlightOptions') as provider:
        response = client.get('/api/fr7/flights/search', query_string=query, headers=HEADERS)
    assert response.status_code == 400
    assert message in response.json['error']
    provider.assert_not_called()

@pytest.mark.parametrize('return_date', [None, DAY])
def test_valid_search_keeps_provider_contract(client, mock_traveller_auth, return_date):
    query = dict(departure_id='Kuala Lumpur', arrival_id='Penang', outbound_date=DAY,
                 traveller_count='2', currency='MYR')
    if return_date:
        query['return_date'] = return_date
    with patch('modules.fr07_flight_search.routes.retrieveFlightOptions', return_value={'items': []}) as provider, patch('modules.fr07_flight_search.routes.storeRecord'):
        response = client.get('/api/fr7/flights/search', query_string=query, headers=HEADERS)
    assert response.status_code == 200
    provider.assert_called_once_with('KUL', 'PEN', DAY, return_date, currency='MYR', travelClass=1, stops=None, adults=2)
    assert response.json['criteria']['currency'] == 'MYR'
    assert response.json['items'] == []

def test_validator_rejects_malformed_return_date():
    assert not validateFlightSearchCriteria(dict(departure_id='KUL', arrival_id='PEN', outbound_date=DAY, return_date='bad'))


def test_favourite_add_remove_add_and_legacy_ids(client, mock_traveller_auth):
    records = {}
    def read(collection, documentId=None, filters=None, **kwargs):
        if collection != 'favourites':
            return None
        if documentId:
            return deepcopy(records.get(documentId))
        assert filters == [('travellerId', '==', 'test_traveller_uid')]
        return [deepcopy(x) for x in records.values() if x['travellerId'] == 'test_traveller_uid']
    def save(collection, data, documentId, **kwargs):
        if collection == 'favourites':
            records[documentId] = deepcopy(data)
        return {'id': documentId, **data}
    with patch('modules.fr03_destination_search_information.routes.retrieveRecord', side_effect=read), patch('modules.fr03_destination_search_information.routes.storeRecord', side_effect=save), patch('modules.fr03_destination_search_information.routes.deleteRecord', side_effect=lambda c, i: records.pop(i)), patch('modules.fr03_destination_search_information.routes._cache'):
        payload = {'destinationId': 'place_1', 'id': 'provider-id', 'title': 'Temple', 'travellerId': 'forged'}
        for _ in range(2):
            assert client.post('/api/fr3/favourites', json=payload, headers=HEADERS).status_code == 201
        assert len(records) == 1
        key = 'test_traveller_uid_place_1'
        assert records[key]['travellerId'] == 'test_traveller_uid'
        records[key]['id'] = 'legacy-provider-id'
        listing = client.get('/api/fr3/favourites', headers=HEADERS).json['items']
        assert listing[0]['id'] == key
        assert client.delete('/api/fr3/favourites/' + key, headers=HEADERS).status_code == 200
        assert not records
        assert client.post('/api/fr3/favourites', json=payload, headers=HEADERS).status_code == 201
        assert len(records) == 1


def test_foreign_favourite_cannot_be_removed(client, mock_traveller_auth):
    with patch('modules.fr03_destination_search_information.routes.retrieveRecord', return_value={'travellerId': 'other'}), patch('modules.fr03_destination_search_information.routes.deleteRecord') as delete:
        response = client.delete('/api/fr3/favourites/other_place', headers=HEADERS)
    assert response.status_code == 404
    delete.assert_not_called()

@pytest.mark.parametrize('path', ['/api/fr3/favourites', '/api/fr7/flights/search'])
def test_auth_required(client, path):
    assert client.get(path).status_code == 401

@pytest.mark.parametrize('owner', ['test_traveller_uid', 'foreign'])
def test_hotel_replace_preserves_trip_and_owner_boundary(app, owner):
    trip = {'id': 'trip', 'travellerId': owner, 'destinationArea': 'Penang', 'startDate': DAY,
            'endDate': (date.fromisoformat(DAY) + timedelta(days=2)).isoformat(),
            'selectedHotel': {'name': 'Old'}, 'hotelBookingId': 'old-record',
            'activities': [{'name': 'Temple'}], 'selectedFlight': {'id': 'flight'}, 'carRentalCost': 75}
    original = deepcopy(trip)
    booking = {'id': 'new-record', 'travellerId': 'test_traveller_uid', 'selectedHotel': {'name': 'New', 'currency': 'MYR'},
               'hotelCost': 200, 'stayCriteria': {'destination': 'Penang', 'checkin': trip['startDate'], 'checkout': trip['endDate']}}
    writes = []
    def update(collection, id, data):
        writes.append(collection)
        if collection == 'itineraries':
            trip.update(data)
            return deepcopy(trip)
        return {**booking, **data}
    with app.test_request_context('/'), patch('modules.fr08_hotel_booking.routes.retrieveRecord', return_value=trip), patch('modules.fr08_hotel_booking.routes.updateRecord', side_effect=update):
        g.uid = 'test_traveller_uid'
        result, attached = _attach_booking_to_itinerary('new-record', booking, {'itineraryId': 'trip'})
    if owner == 'foreign':
        assert attached is None
        assert 'itineraries' not in writes
        assert trip == original
    else:
        assert attached['selectedHotel']['name'] == 'New'
        assert attached['hotelBookingId'] == 'new-record'
        for key in ['activities', 'selectedFlight', 'carRentalCost']:
            assert attached[key] == original[key]


def test_flutter_and_backend_supported_airports_match():
    from pathlib import Path
    import re
    from services.flight_airports import CITY_TO_IATA
    source = (Path(__file__).resolve().parents[2] / 'traveller_mobile/lib/modules/fr07_flight_search/flight_screen.dart').read_text(encoding='utf-8')
    catalogue = source.split('cityToIata = {', 1)[1].split('};', 1)[0]
    assert dict(re.findall(r"'([^']+)': '([A-Z]{3})'", catalogue)) == CITY_TO_IATA
