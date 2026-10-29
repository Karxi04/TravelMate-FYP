from unittest.mock import patch


def test_fb2_sample_hotel_total_includes_nights_rooms_and_persists(client, mock_traveller_auth):
    from tests.test_pu2b_hotel_offer_integrity import MemoryPersistence
    memory = MemoryPersistence()
    memory.collections['itineraries'] = {'fb2-trip': {
        'id': 'fb2-trip', 'travellerId': 'test_traveller_uid', 'destinationArea': 'Penang',
        'startDate': '2030-01-01', 'endDate': '2030-01-04', 'travellerCount': 4,
        'selectedFlight': {'price': 300, 'currency': 'MYR', 'priceBasis': 'itinerary_total'},
        'flightCost': 300, 'flightCurrency': 'MYR', 'travelMode': 'flight',
        'activities': [], 'budgetLimit': 3000,
    }}
    headers = {'Authorization': 'Bearer valid_test_token'}
    with patch.dict('os.environ', {'HOTEL_SAMPLE_MODE': 'true', 'HOTEL_TRANSACTION_MODE': 'local_demo'}), \
         patch('modules.fr08_hotel_booking.routes.retrieveHotelOffers', side_effect=RuntimeError('offline fixture')), \
         patch('modules.fr08_hotel_booking.routes.claimRecord', side_effect=memory.claim), \
         patch('modules.fr08_hotel_booking.routes.retrieveRecord', side_effect=memory.retrieve), \
         patch('modules.fr08_hotel_booking.routes.updateRecord', side_effect=memory.update), \
         patch('modules.fr08_hotel_booking.routes.validateHotelOffer') as provider_prebook, \
         patch('modules.fr08_hotel_booking.routes.createBookingReference') as provider_book:
        response = client.post('/api/fr8/hotels/search', headers=headers, json={
            'destination': 'Penang', 'checkin': '2030-01-01', 'checkout': '2030-01-04',
            'adults': 4, 'roomQuantity': 2, 'occupancies': [{'adults': 2}, {'adults': 2}],
        })
        assert response.status_code == 200
        offer = response.get_json()['items'][0]
        expected = offer['nightlyRoomRate'] * 3 * 2
        assert offer['price'] == expected
        validation = client.post('/api/fr8/hotels/prebook', headers=headers, json={
            'quoteId': offer['quoteId'], 'offerId': offer['offerId'], 'hotelBookingAttemptId': 'fb2-hotel-attempt',
        }).get_json()
        request = {'validationId': validation['result']['validationId'],
                   'hotelBookingAttemptId': 'fb2-hotel-attempt', 'itineraryId': 'fb2-trip'}
        for _ in range(2):
            saved = client.post('/api/fr8/hotels/book', headers=headers, json=request)
            assert saved.status_code == 200
            body = saved.get_json()
            assert body['booking']['hotelCost'] == expected
            assert body['itinerary']['budgetEstimate']['hotel'] == expected
            assert body['itinerary']['budgetEstimate']['flight'] == 300
            assert body['itinerary']['selectedFlight']['price'] == 300
        assert len(memory.collections['hotel_bookings']) == 1
        provider_prebook.assert_not_called()
        provider_book.assert_not_called()


def test_hotel_content_projection_is_allowlisted():
    from services.liteapi_service import normalizeHotelContent

    content = normalizeHotelContent({
        'data': {
            'id': 'provider-h1',
            'name': 'Real Penang Hotel',
            'description': 'Provider description',
            'address': 'Mainland Penang',
            'images': [{'url': 'https://img.example/h1.jpg'}],
            'amenities': ['Wi-Fi'],
            'coordinates': {'latitude': 5.4, 'longitude': 100.3},
            'secretInternalField': 'must not escape',
        }
    })
    assert content['hotelId'] == 'provider-h1'
    assert content['imageUrls'] == ['https://img.example/h1.jpg']
    assert 'secretInternalField' not in content


def test_local_demo_validation_and_booking_never_call_provider(
    client, mock_traveller_auth
):
    from tests.test_pu2b_hotel_offer_integrity import MemoryPersistence

    memory = MemoryPersistence()
    with patch.dict('os.environ', {
        'TRAVELMATE_TESTING': 'true', 'FALLBACK_MODE': 'true',
        'LITEAPI_KEY': '', 'HOTEL_TRANSACTION_MODE': 'local_demo',
    }), patch('modules.fr08_hotel_booking.routes.claimRecord', side_effect=memory.claim), \
         patch('modules.fr08_hotel_booking.routes.retrieveRecord', side_effect=memory.retrieve), \
         patch('modules.fr08_hotel_booking.routes.updateRecord', side_effect=memory.update), \
         patch('modules.fr08_hotel_booking.routes.validateHotelOffer') as prebook, \
         patch('modules.fr08_hotel_booking.routes.createBookingReference') as book:
        validated = client.post('/api/fr8/hotels/prebook', headers={
            'Authorization': 'Bearer valid_test_token'}, json={
                'offerId': 'local_offer_demo',
                'hotelBookingAttemptId': 'pu2c_demo_attempt',
        })
        assert validated.status_code == 200
        result = validated.get_json()['result']
        assert result['validationId'].startswith('demo_validation_')
        assert result['validationMode'] == 'local_demo'
        booked = client.post('/api/fr8/hotels/book', headers={
            'Authorization': 'Bearer valid_test_token'}, json={
                'validationId': result['validationId'],
                'hotelBookingAttemptId': 'pu2c_demo_attempt',
        })
    assert booked.status_code == 200
    record = booked.get_json()['booking']
    assert record['bookingMode'] == 'simulation'
    assert record['providerMutationCalled'] is False
    assert record['demoDisclosure']
    prebook.assert_not_called()
    book.assert_not_called()


def test_provider_failure_does_not_silently_substitute_sample_catalog(
    client, mock_traveller_auth
):
    with patch.dict('os.environ', {
        'TRAVELMATE_TESTING': 'false', 'FALLBACK_MODE': 'true',
        'HOTEL_SAMPLE_MODE': 'false', 'LITEAPI_KEY': 'configured',
    }), patch('modules.fr08_hotel_booking.routes.retrieveHotelOffers',
               side_effect=RuntimeError('provider unavailable')):
        response = client.post('/api/fr8/hotels/search', headers={
            'Authorization': 'Bearer valid_test_token'}, json={
                'destination': 'Penang', 'checkin': '2030-01-01',
                'checkout': '2030-01-03', 'adults': 2,
        })
    assert response.status_code == 502
    assert 'Ink Wash' not in response.get_data(as_text=True)


def test_explicit_provider_sandbox_quote_is_not_labelled_live(
    client, mock_traveller_auth
):
    from tests.test_pu2b_hotel_offer_integrity import MemoryPersistence

    memory = MemoryPersistence()
    with patch.dict('os.environ', {
        'TRAVELMATE_TESTING': 'false', 'FALLBACK_MODE': 'false',
        'HOTEL_SAMPLE_MODE': 'false', 'LITEAPI_KEY': 'configured',
    }), patch('modules.fr08_hotel_booking.routes.retrieveHotelOffers', return_value={
        'sandbox': True,
        'hotels': [{'id': 'provider-h1', 'name': 'Sandbox Hotel'}],
        'data': [{
            'hotelId': 'provider-h1',
            'roomTypes': [{
                'offerId': 'sandbox-offer-1',
                'rates': [{
                    'retailRate': {'total': [{'amount': 220}], 'currency': 'MYR'},
                }],
            }],
        }],
    }), patch('modules.fr08_hotel_booking.routes.retrieveHotelContent', return_value={
        'data': {'id': 'provider-h1', 'name': 'Sandbox Hotel'},
    }), patch('modules.fr08_hotel_booking.routes.claimRecord', side_effect=memory.claim):
        response = client.post('/api/fr8/hotels/search', headers={
            'Authorization': 'Bearer valid_test_token'}, json={
                'destination': 'Penang', 'checkin': '2030-01-01',
                'checkout': '2030-01-03', 'adults': 2,
        })
    assert response.status_code == 200
    item = response.get_json()['items'][0]
    assert item['rateSource'] == 'liteapi_sandbox_quote'
    assert item['rateProvenance'] == 'sandbox_provider_quote'
    assert item['transactionMode'] == 'provider_sandbox'
    assert 'not live inventory' in item['demoDisclosure']
    assert item['checkin'] == '2030-01-01'
    assert item['checkout'] == '2030-01-03'


def test_explicit_sample_mode_is_labelled(client, mock_traveller_auth):
    from tests.test_pu2b_hotel_offer_integrity import MemoryPersistence

    memory = MemoryPersistence()
    with patch.dict('os.environ', {
        'TRAVELMATE_TESTING': 'false', 'FALLBACK_MODE': 'true',
        'HOTEL_SAMPLE_MODE': 'true', 'LITEAPI_KEY': 'configured',
    }), patch('modules.fr08_hotel_booking.routes.retrieveHotelOffers',
               side_effect=RuntimeError('provider unavailable')), \
        patch('modules.fr08_hotel_booking.routes.claimRecord', side_effect=memory.claim):
        response = client.post('/api/fr8/hotels/search', headers={
            'Authorization': 'Bearer valid_test_token'}, json={
                'destination': 'Penang', 'checkin': '2030-01-01',
                'checkout': '2030-01-03', 'adults': 2,
        })
    assert response.status_code == 200
    item = response.get_json()['items'][0]
    assert item['rateSource'] == 'sample_fixture'
    assert item['contentSource'] == 'sample_fixture'
    assert 'not live availability' in item['demoDisclosure']


def test_hotel_selection_removal_keeps_booking_history(client, mock_traveller_auth):
    from tests.test_pu2b_hotel_offer_integrity import MemoryPersistence

    memory = MemoryPersistence()
    memory.collections['itineraries'] = {
        'trip_1': {
            'id': 'trip_1', 'travellerId': 'test_traveller_uid',
            'destinationArea': 'Penang', 'startDate': '2030-01-01',
            'endDate': '2030-01-03', 'travellerCount': 2, 'budgetLimit': 1000,
            'selectedHotel': {'name': 'Hotel'}, 'hotelCost': 300,
            'hotelCurrency': 'MYR', 'hotelBookingId': 'booking_1',
        }
    }
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', side_effect=memory.retrieve), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.updateRecord', side_effect=memory.update):
        response = client.post('/api/fr5/itineraries/trip_1/hotel-selection/remove', headers={
            'Authorization': 'Bearer valid_test_token'})
    assert response.status_code == 200
    itinerary = response.get_json()['itinerary']
    assert itinerary['selectedHotel'] is None
    assert itinerary['hotelSelectionStatus'] == 'removed'
