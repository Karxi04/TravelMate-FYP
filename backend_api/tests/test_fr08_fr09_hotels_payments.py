import pytest
from unittest.mock import MagicMock, patch
from requests import Timeout
from google.api_core.exceptions import AlreadyExists

from services.stripe_service import (
    SimulatedPaymentIntent,
    createPaymentSession,
    normalizePaymentStatus,
    processPaymentAttempt,
    stripePaymentMode,
)


def test_hotel_search_empty_inventory_is_no_results_not_provider_failure(
        client, mock_traveller_auth):
    with patch(
        'modules.fr08_hotel_booking.routes.retrieveHotelOffers',
        return_value={'data': [], 'sandbox': True},
    ), patch(
        'modules.fr08_hotel_booking.routes.normalizeHotelOffers',
        return_value=[],
    ), patch(
        'modules.fr08_hotel_booking.routes._persist_quotes',
        return_value=[],
    ):
        response = client.post(
            '/api/fr8/hotels/search',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={
                'destination': 'Penang',
                'checkin': '2026-11-10',
                'checkout': '2026-11-12',
                'adults': 2,
                'roomQuantity': 1,
            },
        )

    assert response.status_code == 200
    data = response.get_json()
    assert data['ok'] is True
    assert data['items'] == []
    assert data['noResults'] is True
    assert data['source'] == 'liteapi'


class MemoryPersistence:
    def __init__(self):
        self.collections = {}

    def seed(self, collection, document_id, data):
        self.collections.setdefault(collection, {})[document_id] = {
            'id': document_id,
            **data,
        }

    def claim(self, collection, document_id, data):
        records = self.collections.setdefault(collection, {})
        if document_id in records:
            return dict(records[document_id]), False
        records[document_id] = {'id': document_id, **data}
        return dict(records[document_id]), True

    def retrieve(self, collection, document_id=None, filters=None, limit=None):
        records = self.collections.setdefault(collection, {})
        if document_id:
            value = records.get(str(document_id))
            return dict(value) if value else None
        values = [dict(value) for value in records.values()]
        for field, operator, expected in filters or []:
            assert operator == '=='
            values = [value for value in values if value.get(field) == expected]
        return values[:limit] if limit else values

    def update(self, collection, document_id, data):
        records = self.collections.setdefault(collection, {})
        if document_id not in records:
            return None
        records[document_id] = {**records[document_id], **data}
        return dict(records[document_id])


def persistence_patches(memory, module):
    return (
        patch(f'{module}.claimRecord', side_effect=memory.claim),
        patch(f'{module}.retrieveRecord', side_effect=memory.retrieve),
        patch(f'{module}.updateRecord', side_effect=memory.update),
    )


@pytest.mark.parametrize('raw,expected', [
    ('succeeded', 'succeeded'),
    ('successful', 'succeeded'),
    ('failed', 'failed'),
    ('pending', 'pending'),
    ('cancelled', 'cancelled'),
    ('canceled', 'cancelled'),
])
def test_payment_status_normalization(raw, expected):
    assert normalizePaymentStatus(raw) == expected


def test_stripe_test_secret_is_accepted_for_sandbox_mutation():
    intent = SimulatedPaymentIntent('pi_test_mock', 1000)
    with patch.dict('os.environ', {
        'STRIPE_SECRET_KEY': 'sk_test_example_not_real',
        'FALLBACK_MODE': 'false',
    }), patch(
        'services.stripe_service.stripe.PaymentIntent.create',
        return_value=intent,
    ) as create:
        result = createPaymentSession({'amount': 10}, 'traveller', 'booking')
    assert result is intent
    create.assert_called_once()


def test_stripe_live_secret_never_performs_mutation():
    with patch.dict('os.environ', {
        'STRIPE_SECRET_KEY': 'sk_live_must_never_be_used',
        'FALLBACK_MODE': 'true',
    }), patch('services.stripe_service.stripe.PaymentIntent.create') as create:
        result = createPaymentSession({'amount': 10}, 'traveller', 'booking')
        assert isinstance(result, SimulatedPaymentIntent)
        assert stripePaymentMode() == 'simulation'
    create.assert_not_called()


def test_invalid_stripe_key_is_unavailable_without_fallback():
    with patch.dict('os.environ', {
        'STRIPE_SECRET_KEY': 'pk_test_publishable_only',
        'FALLBACK_MODE': 'false',
    }), patch('services.stripe_service.stripe.PaymentIntent.create') as create:
        with pytest.raises(RuntimeError, match='sandbox is unavailable'):
            createPaymentSession({'amount': 10}, 'traveller', 'booking')
        assert stripePaymentMode() == 'unavailable'
    create.assert_not_called()


def test_shared_fallback_does_not_enable_payment_simulation_in_production():
    with patch.dict('os.environ', {
        'TRAVELMATE_TESTING': 'false',
        'STRIPE_SECRET_KEY': 'pk_test_publishable_only',
        'FALLBACK_MODE': 'true',
    }), patch('services.stripe_service.stripe.PaymentIntent.create') as create:
        with pytest.raises(RuntimeError, match='sandbox is unavailable'):
            createPaymentSession({'amount': 10}, 'traveller', 'booking')
        assert stripePaymentMode() == 'unavailable'
    create.assert_not_called()

def test_payment_process_authoritative_amount_and_booking_update(client, mock_traveller_auth):
    memory = MemoryPersistence()
    sample_booking = {
        'id': 'booking_doc_101',
        'bookingReference': 'TM-BK-8899AABB',
        'travellerId': 'test_traveller_uid',
        'hotelCost': 450.0,
        'bookingStatus': 'confirmed',
        'hotelCurrency': 'MYR',
        'amountSource': 'legacy_verified_myr',
    }
    memory.seed('hotel_bookings', 'booking_doc_101', sample_booking)

    with patch.dict('os.environ', {'FALLBACK_MODE': 'true'}), \
         patch('modules.fr09_payment.routes.claimRecord', side_effect=memory.claim), \
         patch('modules.fr09_payment.routes.retrieveRecord', side_effect=memory.retrieve), \
         patch('modules.fr09_payment.routes.updateRecord', side_effect=memory.update):

        # Client attempts to tamper with amount to RM 0.01
        res = client.post(
            '/api/fr9/payments/process',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={
                'bookingId': 'TM-BK-8899AABB',
                'paymentAttemptId': 'payment_attempt_authoritative',
                'amount': 0.01,
                'cardholderName': 'Test Traveller',
                'billingEmail': 'traveller@test.com',
                'cardBrand': 'Visa',
                'cardLast4': '4242'
            }
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        # Verify server derived authoritative booking cost RM 450.00 instead of client's RM 0.01!
        assert data['payment']['amount'] == 450.0
        # Verify hotel_bookings was updated using the document ID
        updated_booking = memory.retrieve('hotel_bookings', 'booking_doc_101')
        assert updated_booking['bookingStatus'] == 'confirmed'
        assert updated_booking['demoPaymentStatus'] == 'succeeded'

def test_payment_process_rejects_unauthorized_booking(client, mock_traveller_auth):
    sample_booking_other_user = {
        'id': 'booking_doc_202',
        'bookingReference': 'TM-BK-VICTIM',
        'travellerId': 'other_traveller_uid',
        'hotelCost': 600.0,
        'bookingStatus': 'confirmed',
    }

    with patch.dict('os.environ', {'FALLBACK_MODE': 'true'}), \
         patch('modules.fr09_payment.routes.retrieveRecord') as mock_retrieve:

        def fake_retrieve(coll, doc_id=None, filters=None):
            if coll == 'hotel_bookings':
                return [sample_booking_other_user]
            return None

        mock_retrieve.side_effect = fake_retrieve

        res = client.post(
            '/api/fr9/payments/process',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={
                'bookingId': 'TM-BK-VICTIM',
                'amount': 600.0,
            }
        )
        assert res.status_code == 403
        assert 'Unauthorized' in res.get_json()['error']


def test_payment_list_normalizes_legacy_success(client, mock_traveller_auth):
    records = [
        {
            'id': 'legacy', 'travellerId': 'test_traveller_uid',
            'paymentStatus': 'successful',
        },
        {
            'id': 'current', 'travellerId': 'test_traveller_uid',
            'paymentStatus': 'succeeded',
        },
    ]
    def retrieve(collection, document_id=None, filters=None):
        return records if collection == 'payment_records' else []

    with patch('modules.fr09_payment.routes.retrieveRecord', side_effect=retrieve):
        response = client.get(
            '/api/fr9/payments',
            headers={'Authorization': 'Bearer valid_test_token'},
        )
    assert response.status_code == 200
    assert [item['paymentStatus'] for item in response.get_json()['items']] == [
        'succeeded',
        'succeeded',
    ]


def test_successful_payment_cannot_be_retried(client, mock_traveller_auth):
    with patch(
        'modules.fr09_payment.routes.retrieveRecord',
        return_value={'id': 'paid', 'travellerId': 'test_traveller_uid', 'paymentStatus': 'successful'},
    ):
        response = client.post(
            '/api/fr9/payments/paid/retry',
            headers={'Authorization': 'Bearer valid_test_token'},
        )
    assert response.status_code == 409


def test_one_payment_process_request_creates_exactly_one_stripe_intent(
    client, mock_traveller_auth
):
    memory = MemoryPersistence()
    intent = SimulatedPaymentIntent('pi_test_single', 2500, status='succeeded')
    with patch.dict('os.environ', {
        'STRIPE_SECRET_KEY': 'sk_test_example_not_real',
        'FALLBACK_MODE': 'false',
    }), patch('modules.fr09_payment.routes.claimRecord', side_effect=memory.claim), \
         patch('modules.fr09_payment.routes.retrieveRecord', side_effect=memory.retrieve), \
         patch('modules.fr09_payment.routes.updateRecord', side_effect=memory.update), \
         patch('services.stripe_service.stripe.PaymentIntent.create', return_value=intent) as create:
        response = client.post(
            '/api/fr9/payments/process',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'paymentAttemptId': 'payment_attempt_single', 'amount': 25},
        )
    assert response.status_code == 200
    assert create.call_count == 1


def test_same_payment_attempt_converges_and_different_attempt_is_separate(
    client, mock_traveller_auth
):
    memory = MemoryPersistence()
    with patch.dict('os.environ', {'FALLBACK_MODE': 'true', 'STRIPE_SECRET_KEY': ''}), \
         patch('modules.fr09_payment.routes.claimRecord', side_effect=memory.claim), \
         patch('modules.fr09_payment.routes.retrieveRecord', side_effect=memory.retrieve), \
         patch('modules.fr09_payment.routes.updateRecord', side_effect=memory.update), \
         patch('modules.fr09_payment.routes.processPaymentAttempt', wraps=processPaymentAttempt) as process:
        first = client.post(
            '/api/fr9/payments/process',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'paymentAttemptId': 'payment_attempt_same', 'amount': 30},
        )
        duplicate = client.post(
            '/api/fr9/payments/process',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'paymentAttemptId': 'payment_attempt_same', 'amount': 30},
        )
        separate = client.post(
            '/api/fr9/payments/process',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'paymentAttemptId': 'payment_attempt_different', 'amount': 30},
        )
    assert first.status_code == duplicate.status_code == separate.status_code == 200
    assert first.get_json()['payment']['id'] == duplicate.get_json()['payment']['id']
    assert first.get_json()['payment']['id'] != separate.get_json()['payment']['id']
    assert process.call_count == 2


def test_ambiguous_payment_retry_reuses_same_stripe_key(
    client, mock_traveller_auth
):
    memory = MemoryPersistence()
    intent = SimulatedPaymentIntent('pi_test_reconciled', 4000, status='succeeded')
    with patch.dict('os.environ', {
        'STRIPE_SECRET_KEY': 'sk_test_example_not_real',
        'FALLBACK_MODE': 'false',
    }), patch('modules.fr09_payment.routes.claimRecord', side_effect=memory.claim), \
         patch('modules.fr09_payment.routes.retrieveRecord', side_effect=memory.retrieve), \
         patch('modules.fr09_payment.routes.updateRecord', side_effect=memory.update), \
         patch(
             'services.stripe_service.stripe.PaymentIntent.create',
             side_effect=[Timeout('provider outcome unknown'), intent],
         ) as create:
        first = client.post(
            '/api/fr9/payments/process',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'paymentAttemptId': 'payment_attempt_ambiguous', 'amount': 40},
        )
        second = client.post(
            '/api/fr9/payments/process',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'paymentAttemptId': 'payment_attempt_ambiguous', 'amount': 40},
        )
    assert first.status_code == 202
    assert first.get_json()['payment']['paymentStatus'] == 'pending'
    assert second.status_code == 200
    assert second.get_json()['payment']['paymentStatus'] == 'succeeded'
    assert create.call_count == 2
    assert create.call_args_list[0].kwargs['idempotency_key'] == create.call_args_list[1].kwargs['idempotency_key']


def test_simulated_payment_is_deterministic_for_same_provider_key():
    with patch.dict('os.environ', {
        'STRIPE_SECRET_KEY': '',
        'FALLBACK_MODE': 'true',
    }):
        first = processPaymentAttempt({'amount': 12}, 'traveller', '', 'opaque_key')
        second = processPaymentAttempt({'amount': 12}, 'traveller', '', 'opaque_key')
    assert first.id == second.id
    assert first.status == second.status == 'succeeded'


def test_pending_payment_lookup_does_not_mark_timeout_failed(
    client, mock_traveller_auth
):
    memory = MemoryPersistence()
    with patch.dict('os.environ', {
        'STRIPE_SECRET_KEY': 'sk_test_example_not_real',
        'FALLBACK_MODE': 'false',
    }), patch('modules.fr09_payment.routes.claimRecord', side_effect=memory.claim), \
         patch('modules.fr09_payment.routes.retrieveRecord', side_effect=memory.retrieve), \
         patch('modules.fr09_payment.routes.updateRecord', side_effect=memory.update), \
         patch('services.stripe_service.stripe.PaymentIntent.create', side_effect=Timeout('slow')):
        started = client.post(
            '/api/fr9/payments/process',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'paymentAttemptId': 'payment_attempt_pending', 'amount': 50},
        )
        lookup = client.get(
            '/api/fr9/payments/attempts/payment_attempt_pending',
            headers={'Authorization': 'Bearer valid_test_token'},
        )
    assert started.status_code == lookup.status_code == 202
    assert lookup.get_json()['payment']['paymentStatus'] == 'pending'


def test_hotel_prebook_and_book_have_distinct_stage_keys(
    client, mock_traveller_auth
):
    memory = MemoryPersistence()
    memory.seed('hotel_offer_quotes', 'test_traveller_uid_quote_live_1', {
        'quoteId': 'quote_live_1',
        'travellerId': 'test_traveller_uid',
        'offer': {
            'offerId': 'offer_live_1', 'name': 'Hotel', 'price': 200,
            'priceStatus': 'available', 'priceBasis': 'stay_total',
            'currency': 'MYR', 'currencyStatus': 'known',
            'taxesAndFeesStatus': 'included',
            'cancellation': {'tag': 'RFN', 'status': 'known'},
        },
        'criteria': {},
    })
    with patch.dict('os.environ', {'LITEAPI_KEY': 'test-key', 'FALLBACK_MODE': 'false'}), \
         patch('modules.fr08_hotel_booking.routes.claimRecord', side_effect=memory.claim), \
         patch('modules.fr08_hotel_booking.routes.retrieveRecord', side_effect=memory.retrieve), \
         patch('modules.fr08_hotel_booking.routes.updateRecord', side_effect=memory.update), \
         patch('modules.fr08_hotel_booking.routes.validateHotelOffer', return_value={
             'prebookId': 'prebook_live_1', 'offerId': 'offer_live_1',
             'status': 'prebooked', 'price': 200, 'currency': 'MYR',
             'priceBasis': 'stay_total', 'taxesAndFeesStatus': 'included',
             'cancellation': {'tag': 'RFN', 'status': 'known'},
         }), patch('modules.fr08_hotel_booking.routes.createBookingReference', return_value={
             'bookingId': 'LIVE-BOOK-1', 'status': 'confirmed'
         }) as book:
        prebook = client.post(
            '/api/fr8/hotels/prebook',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'offerId': 'offer_live_1', 'quoteId': 'quote_live_1', 'hotelBookingAttemptId': 'hotel_attempt_stage_keys'},
        )
        booking = client.post(
            '/api/fr8/hotels/book',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={
                'prebookId': 'prebook_live_1',
                'hotelBookingAttemptId': 'hotel_attempt_stage_keys',
                'selectedHotel': {'name': 'Hotel', 'price': 200},
            },
        )
        duplicate = client.post(
            '/api/fr8/hotels/book',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={
                'prebookId': 'prebook_live_1',
                'hotelBookingAttemptId': 'hotel_attempt_stage_keys',
                'selectedHotel': {'name': 'Hotel', 'price': 200},
            },
        )
    assert prebook.status_code == booking.status_code == duplicate.status_code == 200
    assert book.call_count == 1
    prebook_record = next(iter(memory.collections['hotel_prebook_attempts'].values()))
    booking_record = next(iter(memory.collections['hotel_bookings'].values()))
    assert prebook_record['providerRequestKey'] != booking_record['providerRequestKey']
    assert booking.get_json()['booking']['id'] == duplicate.get_json()['booking']['id']


def test_fallback_hotel_attempt_reuses_simulated_confirmation(
    client, mock_traveller_auth
):
    memory = MemoryPersistence()
    payload = {'hotelBookingAttemptId': 'hotel_attempt_demo_same'}
    with patch.dict('os.environ', {'LITEAPI_KEY': '', 'FALLBACK_MODE': 'true'}), \
         patch('modules.fr08_hotel_booking.routes.claimRecord', side_effect=memory.claim), \
         patch('modules.fr08_hotel_booking.routes.retrieveRecord', side_effect=memory.retrieve), \
         patch('modules.fr08_hotel_booking.routes.updateRecord', side_effect=memory.update):
        prebook = client.post('/api/fr8/hotels/prebook', headers={
            'Authorization': 'Bearer valid_test_token'}, json={
                'offerId': 'local_offer_test',
                'hotelBookingAttemptId': payload['hotelBookingAttemptId'],
            })
        assert prebook.status_code == 200
        payload['validationId'] = prebook.get_json()['result']['validationId']
        first = client.post('/api/fr8/hotels/book', headers={
            'Authorization': 'Bearer valid_test_token'}, json=payload)
        second = client.post('/api/fr8/hotels/book', headers={
            'Authorization': 'Bearer valid_test_token'}, json=payload)
    first_booking = first.get_json()['booking']
    second_booking = second.get_json()['booking']
    assert first_booking['bookingReference'] == second_booking['bookingReference']
    assert first_booking['confirmationLabel'] == 'Simulated confirmation'
    assert first_booking['isSimulated'] is True


def test_ambiguous_hotel_booking_is_not_resubmitted(
    client, mock_traveller_auth
):
    memory = MemoryPersistence()
    payload = {
        'prebookId': 'prebook_live_timeout',
        'hotelBookingAttemptId': 'hotel_attempt_timeout',
        'selectedHotel': {'name': 'Hotel', 'price': 180},
    }
    memory.seed('hotel_offer_quotes', 'test_traveller_uid_quote_live_timeout', {
        'quoteId': 'quote_live_timeout', 'travellerId': 'test_traveller_uid',
        'offer': {'offerId': 'offer_live_timeout', 'name': 'Hotel', 'price': 180,
                  'priceStatus': 'available', 'priceBasis': 'stay_total',
                  'currency': 'MYR', 'currencyStatus': 'known',
                  'taxesAndFeesStatus': 'included',
                  'cancellation': {'tag': 'RFN', 'status': 'known'}},
        'criteria': {},
    })
    with patch.dict('os.environ', {'LITEAPI_KEY': 'test-key', 'FALLBACK_MODE': 'false'}), \
         patch('modules.fr08_hotel_booking.routes.claimRecord', side_effect=memory.claim), \
         patch('modules.fr08_hotel_booking.routes.retrieveRecord', side_effect=memory.retrieve), \
         patch('modules.fr08_hotel_booking.routes.updateRecord', side_effect=memory.update), \
         patch('modules.fr08_hotel_booking.routes.validateHotelOffer', return_value={
             'prebookId': 'prebook_live_timeout', 'offerId': 'offer_live_timeout',
             'status': 'prebooked', 'price': 180, 'currency': 'MYR',
             'priceBasis': 'stay_total', 'taxesAndFeesStatus': 'included',
             'cancellation': {'tag': 'RFN', 'status': 'known'},
         }), patch('modules.fr08_hotel_booking.routes.createBookingReference', side_effect=Timeout('unknown')) as book:
        prebook = client.post('/api/fr8/hotels/prebook', headers={
            'Authorization': 'Bearer valid_test_token'}, json={
                'offerId': 'offer_live_timeout', 'quoteId': 'quote_live_timeout',
                'hotelBookingAttemptId': payload['hotelBookingAttemptId'],
            })
        assert prebook.status_code == 200
        first = client.post('/api/fr8/hotels/book', headers={
            'Authorization': 'Bearer valid_test_token'}, json=payload)
        second = client.post('/api/fr8/hotels/book', headers={
            'Authorization': 'Bearer valid_test_token'}, json=payload)
    assert first.status_code == second.status_code == 202
    assert first.get_json()['booking']['bookingStatus'] == 'pending'
    assert book.call_count == 1


def test_itinerary_attachment_retry_does_not_rebook_provider(
    client, mock_traveller_auth
):
    memory = MemoryPersistence()
    memory.seed('itineraries', 'trip_1', {
        'travellerId': 'test_traveller_uid',
        'destinationArea': 'Penang',
        'startDate': '2026-11-01',
        'endDate': '2026-11-03',
        'budgetEstimate': {},
    })
    payload = {
        'prebookId': 'prebook_live_attach',
        'hotelBookingAttemptId': 'hotel_attempt_attach',
        'selectedHotel': {'name': 'Hotel', 'price': 220},
        'itineraryId': 'trip_1',
    }
    original_update = memory.update
    failed_once = {'value': False}

    def flaky_update(collection, document_id, data):
        if collection == 'itineraries' and not failed_once['value']:
            failed_once['value'] = True
            raise RuntimeError('temporary itinerary write failure')
        return original_update(collection, document_id, data)

    memory.seed('hotel_offer_quotes', 'test_traveller_uid_quote_live_attach', {
        'quoteId': 'quote_live_attach', 'travellerId': 'test_traveller_uid',
        'offer': {'offerId': 'offer_live_attach', 'name': 'Hotel', 'price': 220,
                  'priceStatus': 'available', 'priceBasis': 'stay_total',
                  'currency': 'MYR', 'currencyStatus': 'known',
                  'taxesAndFeesStatus': 'included',
                  'cancellation': {'tag': 'RFN', 'status': 'known'}},
        'criteria': {
            'destination': 'Penang', 'checkin': '2026-11-01',
            'checkout': '2026-11-03', 'adults': 1, 'roomQuantity': 1,
            'occupancies': [{'adults': 1}],
        },
    })
    with patch.dict('os.environ', {'LITEAPI_KEY': 'test-key', 'FALLBACK_MODE': 'false'}), \
         patch('modules.fr08_hotel_booking.routes.claimRecord', side_effect=memory.claim), \
         patch('modules.fr08_hotel_booking.routes.retrieveRecord', side_effect=memory.retrieve), \
         patch('modules.fr08_hotel_booking.routes.updateRecord', side_effect=flaky_update), \
         patch('modules.fr08_hotel_booking.routes.validateHotelOffer', return_value={
             'prebookId': 'prebook_live_attach', 'offerId': 'offer_live_attach',
             'status': 'prebooked', 'price': 220, 'currency': 'MYR',
             'priceBasis': 'stay_total', 'taxesAndFeesStatus': 'included',
             'cancellation': {'tag': 'RFN', 'status': 'known'},
         }), patch('modules.fr08_hotel_booking.routes.createBookingReference', return_value={
             'bookingId': 'LIVE-ATTACH-1', 'status': 'confirmed'
         }) as book:
        prebook = client.post('/api/fr8/hotels/prebook', headers={
            'Authorization': 'Bearer valid_test_token'}, json={
                'offerId': 'offer_live_attach', 'quoteId': 'quote_live_attach',
                'hotelBookingAttemptId': payload['hotelBookingAttemptId'],
            })
        assert prebook.status_code == 200
        first = client.post('/api/fr8/hotels/book', headers={
            'Authorization': 'Bearer valid_test_token'}, json=payload)
        second = client.post('/api/fr8/hotels/book', headers={
            'Authorization': 'Bearer valid_test_token'}, json=payload)
    assert first.status_code == second.status_code == 200
    assert first.get_json()['booking']['itineraryAttachmentStatus'] == 'failed'
    assert second.get_json()['booking']['itineraryAttachmentStatus'] == 'succeeded'
    assert book.call_count == 1


def test_firestore_claim_uses_atomic_create_and_returns_existing_record():
    from sequence_contract.firebase_firestore import claimRecord

    ref = MagicMock()
    ref.id = 'operation_1'
    ref.create.side_effect = AlreadyExists('already claimed')
    snapshot = MagicMock()
    snapshot.id = 'operation_1'
    snapshot.to_dict.return_value = {'status': 'pending'}
    ref.get.return_value = snapshot
    db = MagicMock()
    db.collection.return_value.document.return_value = ref

    with patch('sequence_contract.firebase_firestore.get_db', return_value=db):
        record, created = claimRecord(
            'payment_records', 'operation_1', {'status': 'pending'}
        )
    ref.create.assert_called_once_with({'status': 'pending'})
    assert created is False
    assert record == {'id': 'operation_1', 'status': 'pending'}
