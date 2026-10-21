from unittest.mock import patch

from services.serpapi_service import normalizeFlightResult, retrieveFlightReturns
from modules.fr07_flight_search.routes import reset_flight_quotes


def _leg(number, departure, arrival, departure_time, arrival_time):
    return {
        'airline': 'Demo Air',
        'flight_number': number,
        'departure_airport': {'id': departure, 'name': departure, 'time': departure_time},
        'arrival_airport': {'id': arrival, 'name': arrival, 'time': arrival_time},
        'duration': 60,
    }


def _outbound(number='DA101', token='private-departure-token', price=1139):
    return {
        'flights': [_leg(number, 'KUL', 'PEN', '2027-02-10 10:40', '2027-02-10 11:40')],
        'price': price,
        'currency': 'MYR',
        'departure_token': token,
    }


def _return(price=420, number='DA102'):
    return {'flights': [_leg(number, 'PEN', 'KUL', '2027-02-12 18:00', '2027-02-12 19:00')], 'price': price, 'currency': 'MYR'}


def test_provider_timestamps_become_explicit_local_dates_and_times():
    flight = normalizeFlightResult(_outbound(), traveller_count=2)
    assert flight['outboundDate'] == '2027-02-10'
    assert flight['departureTime'] == '10:40'
    assert flight['outboundSegments'][0]['departureLocalDateTime'] == '2027-02-10 10:40'
    assert flight['travellerCount'] == 2


def test_return_request_forwards_owner_criteria_token_and_adults():
    with patch('services.serpapi_service._request', return_value={'best_flights': []}) as request:
        retrieveFlightReturns('private-token', 'KUL', 'PEN', '2027-02-10', '2027-02-12', adults=2)
    params = request.call_args.args[0]
    assert params['departure_token'] == 'private-token'
    assert params['departure_id'] == 'KUL'
    assert params['arrival_id'] == 'PEN'
    assert params['outbound_date'] == '2027-02-10'
    assert params['return_date'] == '2027-02-12'
    assert params['adults'] == 2
    assert params['type'] == 1


def test_round_trip_requires_return_selection_and_selects_one_authoritative_total(client, mock_traveller_auth):
    reset_flight_quotes()
    with patch('modules.fr07_flight_search.routes.retrieveFlightOptions', return_value={'items': [_outbound()]}):
        searched = client.get('/api/fr7/flights/search?departure_id=KUL&arrival_id=PEN&outbound_date=2027-02-10&return_date=2027-02-12&traveller_count=2', headers={'Authorization': 'Bearer valid_test_token'})
    assert searched.status_code == 200
    data = searched.get_json()
    outbound = data['items'][0]
    assert data['quoteCompleteness'] == 'return_selection_pending'
    assert outbound['roundTripComplete'] is False
    assert 'departureToken' not in outbound

    with patch('modules.fr07_flight_search.routes.retrieveFlightReturns', return_value={'items': [_return(420), _return(550, 'DA202')]}):
        returns = client.post('/api/fr7/flights/returns', headers={'Authorization': 'Bearer valid_test_token'}, json={'searchId': data['searchId'], 'optionId': outbound['id']})
    assert returns.status_code == 200
    return_option = returns.get_json()['items'][1]
    assert return_option['returnSegments'][0]['departureDate'] == '2027-02-12'
    assert return_option['price'] == 550
    assert return_option['combinedPrice'] == 550

    itinerary = {
        'id': 'f2_trip', 'travellerId': 'test_traveller_uid', 'budgetLimit': 5000,
        'travellerCount': 2, 'activities': [], 'selectedHotel': {'name': 'Safe Hotel'},
        'hotelCost': 300, 'purchasedPackages': [{'id': 'package-safe'}],
    }
    with patch('modules.fr07_flight_search.routes.retrieveRecord', return_value=itinerary), patch('modules.fr07_flight_search.routes.updateRecord', side_effect=lambda c, i, p: {**itinerary, **p}):
        selected = client.post('/api/fr7/flights/select', headers={'Authorization': 'Bearer valid_test_token'}, json={
            'itineraryId': 'f2_trip', 'searchId': data['searchId'], 'optionId': outbound['id'],
            'returnOptionId': return_option['id'], 'flight': outbound,
        })
    assert selected.status_code == 200
    result = selected.get_json()
    assert result['selectedFlight']['roundTripComplete'] is True
    assert len(result['selectedFlight']['outboundSegments']) == 1
    assert len(result['selectedFlight']['returnSegments']) == 1
    assert result['itinerary']['flightCost'] == 550
    assert result['itinerary']['budgetEstimate']['flight'] == 550
    assert result['itinerary']['flightPriceBasis'] == 'provider_round_trip_ticket_price_requested_adults'
    assert result['itinerary']['flightOptionId'].startswith('flight_completed_')
    assert result['selectedFlight']['completedOptionId'] == result['itinerary']['flightOptionId']
    assert result['selectedFlight']['flightSearchId'] == data['searchId']
    assert 'departureToken' not in result['itinerary']['selectedFlight']
    assert 'bookingToken' not in result['itinerary']['selectedFlight']
    assert result['itinerary']['selectedHotel']['name'] == 'Safe Hotel'
    assert result['itinerary']['purchasedPackages'] == [{'id': 'package-safe'}]

    import modules.fr07_flight_search.routes as routes
    stored = routes._FLIGHT_QUOTES[data['searchId']]
    assert stored['items'][0]['departureToken'] == 'private-departure-token'
    assert stored['completedOptions'][result['itinerary']['flightOptionId']]['price'] == 550

    with patch('modules.fr07_flight_search.routes.retrieveRecord', return_value=itinerary), patch(
            'modules.fr07_flight_search.routes.updateRecord', side_effect=lambda c, i, p: {**itinerary, **p}):
        repeated = client.post('/api/fr7/flights/select', headers={'Authorization': 'Bearer valid_test_token'}, json={
            'itineraryId': 'f2_trip', 'searchId': data['searchId'], 'optionId': outbound['id'],
            'returnOptionId': return_option['id'], 'flight': outbound,
        })
    assert repeated.status_code == 200
    assert repeated.get_json()['itinerary']['flightOptionId'] == result['itinerary']['flightOptionId']
    assert len(stored['completedOptions']) == 1

    routes._FLIGHT_QUOTES.clear()
    with patch('modules.fr07_flight_search.routes.retrieveRecord', side_effect=lambda collection, key: stored if collection == 'flight_quotes' else itinerary):
        reloaded = client.post('/api/fr7/flights/details', headers={'Authorization': 'Bearer valid_test_token'}, json={
            'searchId': data['searchId'], 'optionId': result['itinerary']['flightOptionId'],
        })
    assert reloaded.status_code == 200
    assert reloaded.get_json()['flight']['price'] == 550


def test_round_trip_conflict_refers_to_the_actual_segment_date(client, mock_traveller_auth):
    from modules.fr07_flight_search.routes import _flight_conflicts
    flight = {
        'outboundSegments': [{'arrivalDate': '2027-02-11'}],
        'returnSegments': [{'departureDate': '2027-02-12'}],
    }
    itinerary = {
        'startDate': '2027-02-10', 'endDate': '2027-02-12',
        'activities': [{'dayNo': 1, 'timeSlot': 'morning'}],
    }
    assert _flight_conflicts(itinerary, flight) == []


def test_round_trip_conflict_requires_one_explicit_acknowledgement(client, mock_traveller_auth):
    reset_flight_quotes()
    with patch('modules.fr07_flight_search.routes.retrieveFlightOptions', return_value={'items': [_outbound()]}):
        searched = client.get('/api/fr7/flights/search?departure_id=KUL&arrival_id=PEN&outbound_date=2027-02-10&return_date=2027-02-12', headers={'Authorization': 'Bearer valid_test_token'})
    outbound = searched.get_json()['items'][0]
    with patch('modules.fr07_flight_search.routes.retrieveFlightReturns', return_value={'items': [_return()]}):
        returns = client.post('/api/fr7/flights/returns', headers={'Authorization': 'Bearer valid_test_token'}, json={'searchId': searched.get_json()['searchId'], 'optionId': outbound['id']})
    itinerary = {
        'id': 'timing-trip', 'travellerId': 'test_traveller_uid', 'budgetLimit': 5000,
        'travellerCount': 2, 'startDate': '2027-02-10', 'endDate': '2027-02-12',
        'activities': [{'dayNo': 1, 'timeSlot': 'morning'}],
    }
    request = {
        'itineraryId': 'timing-trip', 'searchId': searched.get_json()['searchId'],
        'optionId': outbound['id'], 'returnOptionId': returns.get_json()['items'][0]['id'],
        'flight': outbound,
    }
    with patch('modules.fr07_flight_search.routes.retrieveRecord', return_value=itinerary), \
         patch('modules.fr07_flight_search.routes.updateRecord', side_effect=lambda _c, _i, data: {**itinerary, **data}):
        blocked = client.post('/api/fr7/flights/select', headers={'Authorization': 'Bearer valid_test_token'}, json=request)
        accepted = client.post('/api/fr7/flights/select', headers={'Authorization': 'Bearer valid_test_token'}, json={**request, 'acknowledgeConflicts': True})
    assert blocked.status_code == 409
    assert blocked.get_json()['status'] == 'conflicts_require_acknowledgement'
    assert accepted.status_code == 200
    assert accepted.get_json()['itinerary']['flightConflictStatus'] == 'acknowledged'


def test_round_trip_quote_survives_local_cache_reset(client, mock_traveller_auth):
    reset_flight_quotes()
    with patch('modules.fr07_flight_search.routes.retrieveFlightOptions', return_value={'items': [_outbound()]}):
        searched = client.get('/api/fr7/flights/search?departure_id=KUL&arrival_id=PEN&outbound_date=2027-02-10&return_date=2027-02-12', headers={'Authorization': 'Bearer valid_test_token'})
    search_id = searched.get_json()['searchId']
    import modules.fr07_flight_search.routes as routes
    routes._FLIGHT_QUOTES.clear()
    with patch('modules.fr07_flight_search.routes.retrieveFlightReturns', return_value={'items': [_return()]}):
        response = client.post('/api/fr7/flights/returns', headers={'Authorization': 'Bearer valid_test_token'}, json={'searchId': search_id, 'optionId': searched.get_json()['items'][0]['id']})
    assert response.status_code == 200


def test_provider_return_failure_does_not_fallback(client, mock_traveller_auth):
    reset_flight_quotes()
    with patch('modules.fr07_flight_search.routes.retrieveFlightOptions', return_value={'items': [_outbound()]}):
        searched = client.get('/api/fr7/flights/search?departure_id=KUL&arrival_id=PEN&outbound_date=2027-02-10&return_date=2027-02-12', headers={'Authorization': 'Bearer valid_test_token'})
    with patch('modules.fr07_flight_search.routes.retrieveFlightReturns', side_effect=TimeoutError('provider timeout')):
        response = client.post('/api/fr7/flights/returns', headers={'Authorization': 'Bearer valid_test_token'}, json={'searchId': searched.get_json()['searchId'], 'optionId': searched.get_json()['items'][0]['id']})
    assert response.status_code == 502
    assert 'provider timeout' not in response.get_json()['error']


def test_client_segment_tamper_is_rejected(client, mock_traveller_auth):
    reset_flight_quotes()
    with patch('modules.fr07_flight_search.routes.retrieveFlightOptions', return_value={'items': [_outbound()]}):
        searched = client.get('/api/fr7/flights/search?departure_id=KUL&arrival_id=PEN&outbound_date=2027-02-10', headers={'Authorization': 'Bearer valid_test_token'})
    itinerary = {'id': 'f2_tamper', 'travellerId': 'test_traveller_uid', 'activities': []}
    flight = dict(searched.get_json()['items'][0])
    flight['outboundSegments'] = [{'departureAirportCode': 'XXX'}]
    with patch('modules.fr07_flight_search.routes.retrieveRecord', return_value=itinerary):
        response = client.post('/api/fr7/flights/select', headers={'Authorization': 'Bearer valid_test_token'}, json={
            'itineraryId': 'f2_tamper', 'searchId': searched.get_json()['searchId'], 'optionId': flight['id'], 'flight': flight,
        })
    assert response.status_code == 409


def test_empty_return_result_stays_explicitly_unavailable(client, mock_traveller_auth):
    reset_flight_quotes()
    with patch('modules.fr07_flight_search.routes.retrieveFlightOptions', return_value={'items': [_outbound()]}):
        searched = client.get('/api/fr7/flights/search?departure_id=KUL&arrival_id=PEN&outbound_date=2027-02-10&return_date=2027-02-12', headers={'Authorization': 'Bearer valid_test_token'})
    with patch('modules.fr07_flight_search.routes.retrieveFlightReturns', return_value={'items': []}):
        response = client.post('/api/fr7/flights/returns', headers={'Authorization': 'Bearer valid_test_token'}, json={'searchId': searched.get_json()['searchId'], 'optionId': searched.get_json()['items'][0]['id']})
    assert response.status_code == 200
    assert response.get_json()['quoteCompleteness'] == 'return_unavailable'
    assert response.get_json()['items'] == []


def test_expired_quote_cannot_be_used(client, mock_traveller_auth, monkeypatch):
    reset_flight_quotes()
    with patch('modules.fr07_flight_search.routes.retrieveFlightOptions', return_value={'items': [_outbound()]}):
        searched = client.get('/api/fr7/flights/search?departure_id=KUL&arrival_id=PEN&outbound_date=2027-02-10', headers={'Authorization': 'Bearer valid_test_token'})
    import modules.fr07_flight_search.routes as routes
    routes._FLIGHT_QUOTES[searched.get_json()['searchId']]['expiresAt'] = '2000-01-01T00:00:00+00:00'
    monkeypatch.setenv('TRAVELMATE_TESTING', 'false')
    with patch('modules.fr07_flight_search.routes.retrieveRecord', return_value=None):
        response = client.post('/api/fr7/flights/details', headers={'Authorization': 'Bearer valid_test_token'}, json={'searchId': searched.get_json()['searchId'], 'optionId': searched.get_json()['items'][0]['id']})
    assert response.status_code == 409
    assert response.get_json()['code'] == 'flight_quote_expired'
    itinerary = {'id': 'expired-trip', 'travellerId': 'test_traveller_uid', 'activities': []}
    with patch('modules.fr07_flight_search.routes.retrieveRecord', return_value=itinerary):
        selected = client.post('/api/fr7/flights/select', headers={'Authorization': 'Bearer valid_test_token'}, json={
            'itineraryId': 'expired-trip', 'searchId': searched.get_json()['searchId'],
            'optionId': searched.get_json()['items'][0]['id'],
        })
    assert selected.status_code == 409
    assert selected.get_json()['code'] == 'flight_quote_expired'


def test_search_rejects_invalid_passengers_cabin_and_past_dates(client, mock_traveller_auth):
    headers = {'Authorization': 'Bearer valid_test_token'}
    base = '/api/fr7/flights/search?departure_id=KUL&arrival_id=PEN&outbound_date=2030-02-10'
    invalid_passengers = client.get(f'{base}&traveller_count=not-a-number', headers=headers)
    invalid_cabin = client.get(f'{base}&travel_class=9', headers=headers)
    past = client.get('/api/fr7/flights/search?departure_id=KUL&arrival_id=PEN&outbound_date=2020-01-01', headers=headers)
    assert invalid_passengers.status_code == 400
    assert invalid_passengers.get_json()['code'] == 'invalid_passenger_count'
    assert invalid_cabin.status_code == 400
    assert invalid_cabin.get_json()['code'] == 'invalid_cabin_class'
    assert past.status_code == 400
    assert past.get_json()['code'] == 'invalid_flight_search'


def test_missing_and_malformed_quote_expiry_fail_closed(client, mock_traveller_auth):
    import modules.fr07_flight_search.routes as routes
    itinerary = {'id': 'expiry-trip', 'travellerId': 'test_traveller_uid', 'activities': []}
    headers = {'Authorization': 'Bearer valid_test_token'}
    for expiry in (None, 'not-a-time'):
        reset_flight_quotes()
        routes._FLIGHT_QUOTES['bad-expiry'] = {
            'id': 'bad-expiry', 'travellerId': 'test_traveller_uid',
            'expiresAt': expiry, 'items': [{'id': 'option', 'optionId': 'option'}],
        }
        with patch('modules.fr07_flight_search.routes.retrieveRecord', return_value=itinerary):
            response = client.post('/api/fr7/flights/select', headers=headers, json={
                'itineraryId': 'expiry-trip', 'searchId': 'bad-expiry', 'optionId': 'option',
            })
        assert response.status_code == 409
        assert response.get_json()['code'] == 'invalid_flight_quote'


def test_provider_cache_is_reported_conservatively(client, mock_traveller_auth):
    reset_flight_quotes()
    with patch('modules.fr07_flight_search.routes.retrieveFlightOptions', return_value={'items': [_outbound()]}):
        response = client.get('/api/fr7/flights/search?departure_id=KUL&arrival_id=PEN&outbound_date=2027-02-10', headers={
            'Authorization': 'Bearer valid_test_token'})
    data = response.get_json()
    assert data['freshnessStatus'] == 'provider_cache_possible'
    assert data['planningOnly'] is True
    assert data['expiresAt'] > data['retrievedAt']
    assert data['items'][0]['cacheStatus'] == 'provider_cache_possible'


def test_round_trip_without_provider_completed_price_is_rejected(client, mock_traveller_auth):
    reset_flight_quotes()
    with patch('modules.fr07_flight_search.routes.retrieveFlightOptions', return_value={'items': [_outbound()]}):
        searched = client.get('/api/fr7/flights/search?departure_id=KUL&arrival_id=PEN&outbound_date=2027-02-10&return_date=2027-02-12', headers={
            'Authorization': 'Bearer valid_test_token'}).get_json()
    with patch('modules.fr07_flight_search.routes.retrieveFlightReturns', return_value={'items': [_return(None)]}):
        returned = client.post('/api/fr7/flights/returns', headers={'Authorization': 'Bearer valid_test_token'}, json={
            'searchId': searched['searchId'], 'optionId': searched['items'][0]['id'],
        }).get_json()
    itinerary = {'id': 'no-price-trip', 'travellerId': 'test_traveller_uid', 'activities': []}
    with patch('modules.fr07_flight_search.routes.retrieveRecord', return_value=itinerary):
        response = client.post('/api/fr7/flights/select', headers={'Authorization': 'Bearer valid_test_token'}, json={
            'itineraryId': 'no-price-trip', 'searchId': searched['searchId'],
            'optionId': searched['items'][0]['id'], 'returnOptionId': returned['items'][0]['id'],
        })
    assert response.status_code == 409
    assert response.get_json()['code'] == 'flight_price_unavailable'


def test_unconfirmed_airport_code_is_not_marked_verified(client, mock_traveller_auth):
    reset_flight_quotes()
    with patch('modules.fr07_flight_search.routes.retrieveFlightOptions', return_value={'items': [_outbound()]}):
        response = client.get('/api/fr7/flights/search?departure_id=AAA&arrival_id=PEN&outbound_date=2027-02-10', headers={
            'Authorization': 'Bearer valid_test_token'})
    data = response.get_json()
    assert response.status_code == 200
    assert data['items'] == []
    assert data['criteria']['airportValidationStatus'] == 'unverified_no_provider_result'


def test_airplane_field_and_recursive_token_sanitization():
    from modules.fr07_flight_search.routes import _sanitize_flight_snapshot
    item = normalizeFlightResult({
        'flights': [{**_leg('DA101', 'KUL', 'PEN', '2027-02-10 10:40', '2027-02-10 11:40'),
                     'airplane': 'Airbus A320'}],
        'price': 200, 'currency': 'MYR',
    })
    assert item['outboundSegments'][0]['aircraft'] == 'Airbus A320'
    safe = _sanitize_flight_snapshot({'nested': {'bookingToken': 'private', 'departure_token': 'private'}, 'id': 'safe'})
    assert safe == {'nested': {}, 'id': 'safe'}


def test_return_choice_cannot_move_to_another_outbound(client, mock_traveller_auth):
    reset_flight_quotes()
    with patch('modules.fr07_flight_search.routes.retrieveFlightOptions', return_value={
            'items': [_outbound(), _outbound('DA201', 'other-private-token', 1200)]}):
        searched = client.get('/api/fr7/flights/search?departure_id=KUL&arrival_id=PEN&outbound_date=2027-02-10&return_date=2027-02-12', headers={
            'Authorization': 'Bearer valid_test_token'}).get_json()
    first, second = searched['items']
    with patch('modules.fr07_flight_search.routes.retrieveFlightReturns', return_value={'items': [_return()]}):
        returned = client.post('/api/fr7/flights/returns', headers={'Authorization': 'Bearer valid_test_token'}, json={
            'searchId': searched['searchId'], 'optionId': first['id'],
        }).get_json()
    itinerary = {'id': 'stale-return-trip', 'travellerId': 'test_traveller_uid', 'activities': []}
    with patch('modules.fr07_flight_search.routes.retrieveRecord', return_value=itinerary):
        response = client.post('/api/fr7/flights/select', headers={'Authorization': 'Bearer valid_test_token'}, json={
            'itineraryId': 'stale-return-trip', 'searchId': searched['searchId'],
            'optionId': second['id'], 'returnOptionId': returned['items'][0]['id'],
        })
    assert response.status_code == 409
    assert response.get_json()['code'] == 'invalid_return_selection'


def test_quote_owned_by_another_traveller_is_not_selectable(client, mock_traveller_auth):
    import modules.fr07_flight_search.routes as routes
    reset_flight_quotes()
    routes._FLIGHT_QUOTES['other-search'] = {
        'id': 'other-search', 'travellerId': 'other-traveller',
        'expiresAt': '2099-01-01T00:00:00+00:00',
        'items': [{'id': 'other-option', 'optionId': 'other-option'}],
    }
    itinerary = {'id': 'owned-trip', 'travellerId': 'test_traveller_uid', 'activities': []}
    with patch('modules.fr07_flight_search.routes.retrieveRecord', side_effect=lambda collection, key: itinerary if collection == 'itineraries' else None):
        response = client.post('/api/fr7/flights/select', headers={'Authorization': 'Bearer valid_test_token'}, json={
            'itineraryId': 'owned-trip', 'searchId': 'other-search', 'optionId': 'other-option',
        })
    assert response.status_code == 409
    assert response.get_json()['code'] == 'invalid_flight_quote'
