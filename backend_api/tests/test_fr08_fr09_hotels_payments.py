import pytest
from unittest.mock import patch

from services.stripe_service import (
    SimulatedPaymentIntent,
    createPaymentSession,
    normalizePaymentStatus,
    stripePaymentMode,
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

def test_payment_process_authoritative_amount_and_booking_update(client, mock_traveller_auth):
    sample_booking = {
        'id': 'booking_doc_101',
        'bookingReference': 'TM-BK-8899AABB',
        'travellerId': 'test_traveller_uid',
        'hotelCost': 450.0,
        'bookingStatus': 'confirmed',
    }

    with patch.dict('os.environ', {'FALLBACK_MODE': 'true'}), \
         patch('modules.fr09_payment.routes.retrieveRecord') as mock_retrieve, \
         patch('modules.fr09_payment.routes.storeRecord') as mock_store, \
         patch('modules.fr09_payment.routes.updateRecord') as mock_update:

        def fake_retrieve(coll, doc_id=None, filters=None):
            if coll == 'hotel_bookings':
                if doc_id == 'booking_doc_101':
                    return sample_booking
                if filters and filters == [('bookingReference', '==', 'TM-BK-8899AABB')]:
                    return [sample_booking]
            return None

        mock_retrieve.side_effect = fake_retrieve
        mock_store.return_value = {'id': 'pi_sim_12345'}
        mock_update.return_value = {**sample_booking, 'bookingStatus': 'paid'}

        # Client attempts to tamper with amount to RM 0.01
        res = client.post(
            '/api/fr9/payments/process',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={
                'bookingId': 'TM-BK-8899AABB',
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
        assert mock_update.called
        call_args = mock_update.call_args[0]
        assert call_args[0] == 'hotel_bookings'
        assert call_args[1] == 'booking_doc_101'
        assert call_args[2]['bookingStatus'] == 'paid'

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
        {'id': 'legacy', 'paymentStatus': 'successful'},
        {'id': 'current', 'paymentStatus': 'succeeded'},
    ]
    with patch(
        'modules.fr09_payment.routes.retrieveRecord',
        return_value=records,
    ):
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
    ), patch('modules.fr09_payment.routes.processSandboxPayment') as process:
        response = client.post(
            '/api/fr9/payments/paid/retry',
            headers={'Authorization': 'Bearer valid_test_token'},
        )
    assert response.status_code == 409
    process.assert_not_called()
