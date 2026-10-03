import pytest
from unittest.mock import patch

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
