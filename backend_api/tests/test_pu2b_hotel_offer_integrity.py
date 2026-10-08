from unittest.mock import patch

import pytest

from services.liteapi_service import (
    ProviderMutationBlocked,
    createBookingReference,
    normalizeHotelOffers,
    validateHotelOffer,
)


class MemoryPersistence:
    def __init__(self):
        self.collections = {}

    def claim(self, collection, document_id, data):
        records = self.collections.setdefault(collection, {})
        if document_id in records:
            return dict(records[document_id]), False
        records[document_id] = {'id': document_id, **data}
        return dict(records[document_id]), True

    def retrieve(self, collection, document_id=None, filters=None, limit=None):
        records = self.collections.setdefault(collection, {})
        if document_id:
            value = records.get(document_id)
            return dict(value) if value else None
        return [dict(value) for value in records.values()]

    def update(self, collection, document_id, data):
        records = self.collections.setdefault(collection, {})
        if document_id not in records:
            return None
        records[document_id] = {**records[document_id], **data}
        return dict(records[document_id])


def test_normalize_official_nested_offer_uses_offer_total_and_terms():
    result = {
        'hotels': [{'id': 'h1', 'name': 'Nested Hotel', 'address': 'Penang'}],
        'data': [{
            'hotelId': 'h1',
            'roomTypes': [{
                'offerId': 'offer_nested',
                'roomName': 'King room',
                'offerRetailRate': {
                    'total': [{'amount': 163.66}], 'currency': 'USD',
                },
                'rates': [{
                    'retailRate': {
                        'total': [{'amount': 163.66}], 'currency': 'USD',
                        'taxesAndFees': [{'included': True}],
                    },
                    'cancellationPolicies': {'refundableTag': 'RFN'},
                }],
            }],
        }],
    }

    [offer] = normalizeHotelOffers(result)
    assert offer['price'] == 163.66
    assert offer['priceBasis'] == 'stay_total'
    assert offer['currency'] == 'USD'
    assert offer['refundable'] is True
    assert offer['taxesAndFeesStatus'] == 'included'
    assert 'raw' not in offer


def test_normalize_missing_amount_or_currency_is_unknown_not_zero_or_myr():
    [offer] = normalizeHotelOffers({
        'data': [{
            'hotelId': 'h2',
            'roomTypes': [{
                'offerId': 'offer_unknown',
                'rates': [{'retailRate': {'total': [{'amount': 'n/a'}]}}],
            }],
        }],
    })
    assert offer['price'] is None
    assert offer['priceStatus'] == 'unknown'
    assert offer['currency'] is None
    assert offer['currencyStatus'] == 'unknown'


def test_external_hotel_mutations_fail_closed_without_confirmed_sandbox():
    with patch.dict('os.environ', {'TRAVELMATE_TESTING': 'false', 'LITEAPI_KEY': 'present'}), \
            patch('services.liteapi_service.requests.post') as request:
        with pytest.raises(ProviderMutationBlocked):
            validateHotelOffer('offer_live')
        with pytest.raises(ProviderMutationBlocked):
            createBookingReference({'prebookId': 'prebook_live'})
    request.assert_not_called()


def test_local_booking_uses_server_quote_when_client_amount_is_tampered(
    client, mock_traveller_auth
):
    memory = MemoryPersistence()
    with patch.dict('os.environ', {'FALLBACK_MODE': 'true', 'LITEAPI_KEY': ''}), \
            patch('modules.fr08_hotel_booking.routes.claimRecord', side_effect=memory.claim), \
            patch('modules.fr08_hotel_booking.routes.retrieveRecord', side_effect=memory.retrieve), \
            patch('modules.fr08_hotel_booking.routes.updateRecord', side_effect=memory.update):
        prebook = client.post('/api/fr8/hotels/prebook', headers={
            'Authorization': 'Bearer valid_test_token'}, json={
                'offerId': 'local_offer_test',
                'hotelBookingAttemptId': 'hotel_attempt_quote_bound',
            })
        assert prebook.status_code == 200
        booked = client.post('/api/fr8/hotels/book', headers={
            'Authorization': 'Bearer valid_test_token'}, json={
                'prebookId': prebook.get_json()['result']['prebookId'],
                'hotelBookingAttemptId': 'hotel_attempt_quote_bound',
                'selectedHotel': {'offerId': 'local_offer_test', 'price': 0, 'currency': 'USD'},
                'hotelCost': 0,
            })
    assert booked.status_code == 200
    booking = booked.get_json()['booking']
    assert booking['hotelCost'] == 120.0
    assert booking['hotelCurrency'] == 'MYR'
    assert booking['amountSource'] == 'validated_offer'


def test_quote_owned_by_another_traveller_is_rejected(client, mock_traveller_auth):
    memory = MemoryPersistence()
    memory.collections['hotel_offer_quotes'] = {
        'test_traveller_uid_foreign_quote': {
            'quoteId': 'foreign_quote', 'travellerId': 'other_uid',
            'offer': {'offerId': 'offer_foreign'},
        }
    }
    with patch('modules.fr08_hotel_booking.routes.retrieveRecord', side_effect=memory.retrieve):
        response = client.post('/api/fr8/hotels/prebook', headers={
            'Authorization': 'Bearer valid_test_token'}, json={
                'offerId': 'offer_foreign', 'quoteId': 'foreign_quote',
                'hotelBookingAttemptId': 'hotel_attempt_foreign_quote',
            })
    assert response.status_code == 400
    assert 'not found or is not owned' in response.get_json()['error']
