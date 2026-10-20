from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import pytest

from services.liteapi_service import (
    ProviderMutationBlocked,
    createBookingReference,
    provider_mutations_allowed,
)
from services.transaction_reliability import operation_document_id
from test_fr08_fr09_hotels_payments import MemoryPersistence


AUTH = {'Authorization': 'Bearer valid_test_token'}
FUTURE = '2099-01-01T00:00:00+00:00'


def _payment_patches(memory):
    return (
        patch('modules.fr09_payment.routes.claimRecord', side_effect=memory.claim),
        patch('modules.fr09_payment.routes.retrieveRecord', side_effect=memory.retrieve),
        patch('modules.fr09_payment.routes.updateRecord', side_effect=memory.update),
    )


def _hotel_patches(memory):
    return (
        patch('modules.fr08_hotel_booking.routes.claimRecord', side_effect=memory.claim),
        patch('modules.fr08_hotel_booking.routes.retrieveRecord', side_effect=memory.retrieve),
        patch('modules.fr08_hotel_booking.routes.updateRecord', side_effect=memory.update),
    )


def _seed_hotel_prebook(memory, attempt_id='hotel_attempt_18c', owner='test_traveller_uid', expires_at=FUTURE, amount=350.0):
    op_id = operation_document_id('hotel_prebook', owner, attempt_id)
    snapshot = {
        'id': op_id,
        'status': 'accepted',
        'travellerId': owner,
        'provider': 'liteapi',
        'transactionMode': 'provider_sandbox',
        'supplierBookingStatus': 'not_created',
        'hotelBookingAttemptId': attempt_id,
        'quoteId': 'quote_18c',
        'hotelId': 'hotel_18c',
        'name': 'Penang Luxury Hotel',
        'roomName': 'Deluxe Sea View',
        'offerId': 'offer_18c',
        'prebookId': 'prebook_18c',
        'checkin': '2026-12-01',
        'checkout': '2026-12-05',
        'roomQuantity': 1,
        'occupancies': [{'adults': 2}],
        'guestCount': 2,
        'amount': amount,
        'currency': 'MYR',
        'priceBasis': 'stay_total',
        'taxesAndFeesStatus': 'included',
        'cancellation': {'tag': 'RFN', 'status': 'known'},
        'expiresAt': expires_at,
    }
    record = {
        'id': op_id,
        'travellerId': owner,
        'hotelBookingAttemptId': attempt_id,
        'quoteId': 'quote_18c',
        'offerId': 'offer_18c',
        'status': 'succeeded',
        'criteria': {
            'checkin': '2026-12-01',
            'checkout': '2026-12-05',
            'roomQuantity': 1,
            'occupancies': [{'adults': 2}],
            'guestCount': 2,
        },
        'validatedOffer': {
            'offerId': 'offer_18c',
            'price': amount,
            'currency': 'MYR',
        },
        'acceptedPrebookSnapshot': snapshot,
    }
    memory.seed('hotel_prebook_attempts', op_id, record)
    return op_id, snapshot


def _checkout_payload(attempt='checkout_18c', snapshot_id=''):
    return {
        'orderAttemptId': attempt,
        'quoteType': 'hotel',
        'quoteId': 'quote_18c',
        'offerId': 'offer_18c',
        'acceptedPrebookSnapshotId': snapshot_id,
    }


def _stripe_session(session_id='cs_test_18c', payment_status='paid', amount_total=35000, currency='myr', order_id=''):
    return SimpleNamespace(
        id=session_id,
        url=f'https://checkout.stripe.test/{session_id}',
        status='complete' if payment_status == 'paid' else 'open',
        payment_status=payment_status,
        amount_total=amount_total,
        currency=currency,
        payment_intent='pi_test_18c' if payment_status == 'paid' else None,
        metadata={'orderId': order_id},
    )


# Test 1: New Hotel Checkout Order begins with correct payment and fulfillment states
def test_01_new_hotel_checkout_order_initial_states(client, mock_traveller_auth):
    memory = MemoryPersistence()
    op_id, _ = _seed_hotel_prebook(memory)
    patches = _payment_patches(memory)
    session = _stripe_session(order_id='order_18c')
    with patch.dict('os.environ', {'STRIPE_SECRET_KEY': 'sk_test_mock'}), \
            patches[0], patches[1], patches[2], \
            patch('modules.fr09_payment.routes.createCheckoutSession', return_value=session):
        response = client.post('/api/fr9/checkout/session', headers=AUTH,
                               json=_checkout_payload(snapshot_id=op_id))

    assert response.status_code == 200
    order = response.get_json()['order']
    assert order['quoteType'] == 'hotel'
    assert order['status'] == 'checkout_open'
    assert order['paymentStatus'] == 'unpaid'
    assert order['fulfillmentStatus'] == 'not_started'
    assert order['supplierBookingStatus'] == 'not_created'
    assert order['isSimulated'] is True
    assert order['fulfillmentMode'] == 'demo_only'
    assert order['bookingReference'] is None
    assert 'no supplier room has been reserved' in order['demoDisclosure']

    # Prebook attempt record is back-linked to orderId and checkoutSessionId
    prebook = memory.retrieve('hotel_prebook_attempts', op_id)
    assert prebook.get('orderId') == order['id']
    assert prebook.get('checkoutSessionId') == 'cs_test_18c'


# Test 2: Verified Stripe Test payment marks payment paid
def test_02_verified_stripe_test_payment_marks_payment_paid(client, mock_traveller_auth):
    memory = MemoryPersistence()
    op_id, _ = _seed_hotel_prebook(memory)
    order_id = operation_document_id('checkout_order', 'test_traveller_uid', 'order_02')
    memory.seed('checkout_orders', order_id, {
        'id': order_id,
        'travellerId': 'test_traveller_uid',
        'quoteType': 'hotel',
        'status': 'checkout_open',
        'paymentStatus': 'unpaid',
        'amount': 350.0,
        'currency': 'MYR',
        'checkoutSessionId': 'cs_test_02',
        'acceptedPrebookSnapshotId': op_id,
    })
    session = _stripe_session('cs_test_02', payment_status='paid', order_id=order_id)
    patches = _payment_patches(memory)
    with patches[0], patches[1], patches[2], \
            patch('modules.fr09_payment.routes.retrieveCheckoutSession', return_value=session):
        response = client.get(f'/api/fr9/orders/{order_id}/reconcile', headers=AUTH)

    assert response.status_code == 200
    order = response.get_json()['order']
    assert order['status'] == 'paid'
    assert order['paymentStatus'] == 'paid'
    assert order['stripePaymentIntentId'] == 'pi_test_18c'


# Test 3: Verified test payment marks fulfillment demo_only
def test_03_verified_test_payment_marks_fulfillment_demo_only(client, mock_traveller_auth):
    memory = MemoryPersistence()
    op_id, _ = _seed_hotel_prebook(memory)
    order_id = operation_document_id('checkout_order', 'test_traveller_uid', 'order_03')
    memory.seed('checkout_orders', order_id, {
        'id': order_id,
        'travellerId': 'test_traveller_uid',
        'quoteType': 'hotel',
        'status': 'checkout_open',
        'paymentStatus': 'unpaid',
        'amount': 350.0,
        'currency': 'MYR',
        'checkoutSessionId': 'cs_test_03',
        'acceptedPrebookSnapshotId': op_id,
    })
    session = _stripe_session('cs_test_03', payment_status='paid', order_id=order_id)
    patches = _payment_patches(memory)
    with patches[0], patches[1], patches[2], \
            patch('modules.fr09_payment.routes.retrieveCheckoutSession', return_value=session):
        response = client.get(f'/api/fr9/orders/{order_id}/reconcile', headers=AUTH)

    assert response.status_code == 200
    order = response.get_json()['order']
    assert order['fulfillmentStatus'] == 'demo_only'
    assert order['fulfillmentMode'] == 'demo_only'


# Test 4: SupplierBookingStatus remains not_created
def test_04_supplier_booking_status_remains_not_created(client, mock_traveller_auth):
    memory = MemoryPersistence()
    op_id, _ = _seed_hotel_prebook(memory)
    order_id = operation_document_id('checkout_order', 'test_traveller_uid', 'order_04')
    memory.seed('checkout_orders', order_id, {
        'id': order_id,
        'travellerId': 'test_traveller_uid',
        'quoteType': 'hotel',
        'status': 'checkout_open',
        'paymentStatus': 'unpaid',
        'amount': 350.0,
        'currency': 'MYR',
        'checkoutSessionId': 'cs_test_04',
        'acceptedPrebookSnapshotId': op_id,
    })
    session = _stripe_session('cs_test_04', payment_status='paid', order_id=order_id)
    patches = _payment_patches(memory)
    with patches[0], patches[1], patches[2], \
            patch('modules.fr09_payment.routes.retrieveCheckoutSession', return_value=session):
        response = client.get(f'/api/fr9/orders/{order_id}/reconcile', headers=AUTH)

    assert response.status_code == 200
    order = response.get_json()['order']
    assert order['supplierBookingStatus'] == 'not_created'
    # Also check persisted records in Firestore
    persisted_order = memory.retrieve('checkout_orders', order_id)
    assert persisted_order['supplierBookingStatus'] == 'not_created'
    persisted_prebook = memory.retrieve('hotel_prebook_attempts', op_id)
    assert persisted_prebook['supplierBookingStatus'] == 'not_created'


# Test 5: No hotel supplier booking function is called
def test_05_no_hotel_supplier_booking_function_is_called(client, mock_traveller_auth):
    memory = MemoryPersistence()
    op_id, _ = _seed_hotel_prebook(memory)
    order_id = operation_document_id('checkout_order', 'test_traveller_uid', 'order_05')
    memory.seed('checkout_orders', order_id, {
        'id': order_id,
        'travellerId': 'test_traveller_uid',
        'quoteType': 'hotel',
        'status': 'checkout_open',
        'paymentStatus': 'unpaid',
        'amount': 350.0,
        'currency': 'MYR',
        'checkoutSessionId': 'cs_test_05',
        'acceptedPrebookSnapshotId': op_id,
    })
    session = _stripe_session('cs_test_05', payment_status='paid', order_id=order_id)
    patches = _payment_patches(memory)
    with patches[0], patches[1], patches[2], \
            patch('modules.fr09_payment.routes.retrieveCheckoutSession', return_value=session), \
            patch('services.liteapi_service.createBookingReference') as mock_book:
        response = client.get(f'/api/fr9/orders/{order_id}/reconcile', headers=AUTH)

    assert response.status_code == 200
    mock_book.assert_not_called()


# Test 6: No fake booking confirmation is created
def test_06_no_fake_booking_confirmation_is_created(client, mock_traveller_auth):
    memory = MemoryPersistence()
    op_id, _ = _seed_hotel_prebook(memory)
    order_id = operation_document_id('checkout_order', 'test_traveller_uid', 'order_06')
    memory.seed('checkout_orders', order_id, {
        'id': order_id,
        'travellerId': 'test_traveller_uid',
        'quoteType': 'hotel',
        'status': 'checkout_open',
        'paymentStatus': 'unpaid',
        'amount': 350.0,
        'currency': 'MYR',
        'checkoutSessionId': 'cs_test_06',
        'acceptedPrebookSnapshotId': op_id,
    })
    session = _stripe_session('cs_test_06', payment_status='paid', order_id=order_id)
    patches = _payment_patches(memory)
    with patches[0], patches[1], patches[2], \
            patch('modules.fr09_payment.routes.retrieveCheckoutSession', return_value=session):
        response = client.get(f'/api/fr9/orders/{order_id}/reconcile', headers=AUTH)

    assert response.status_code == 200
    order = response.get_json()['order']
    assert order['bookingReference'] is None
    assert 'hotel_bookings' not in memory.collections


# Test 7: An unpaid Order cannot enter a supplier-confirmed state
def test_07_unpaid_order_cannot_enter_supplier_confirmed_state(client, mock_traveller_auth):
    memory = MemoryPersistence()
    op_id, _ = _seed_hotel_prebook(memory)
    order_id = operation_document_id('checkout_order', 'test_traveller_uid', 'order_07')
    memory.seed('checkout_orders', order_id, {
        'id': order_id,
        'travellerId': 'test_traveller_uid',
        'quoteType': 'hotel',
        'status': 'checkout_open',
        'paymentStatus': 'unpaid',
        'amount': 350.0,
        'currency': 'MYR',
        'checkoutSessionId': 'cs_test_07',
        'acceptedPrebookSnapshotId': op_id,
    })
    session = _stripe_session('cs_test_07', payment_status='unpaid', order_id=order_id)
    patches = _payment_patches(memory)
    with patches[0], patches[1], patches[2], \
            patch('modules.fr09_payment.routes.retrieveCheckoutSession', return_value=session):
        response = client.get(f'/api/fr9/orders/{order_id}/reconcile', headers=AUTH)

    assert response.status_code == 202
    order = response.get_json()['order']
    assert order['paymentStatus'] == 'unpaid'
    assert order['fulfillmentStatus'] == 'not_started'
    assert order['supplierBookingStatus'] == 'not_created'
    assert order['bookingReference'] is None


# Test 8: Browser return alone cannot forge payment success
def test_08_browser_return_alone_cannot_forge_payment_success(client):
    memory = MemoryPersistence()
    order_id = 'order_08'
    memory.seed('checkout_orders', order_id, {
        'id': order_id,
        'travellerId': 'test_traveller_uid',
        'quoteType': 'hotel',
        'status': 'checkout_open',
        'paymentStatus': 'unpaid',
        'amount': 350.0,
        'currency': 'MYR',
        'checkoutSessionId': 'cs_test_08',
    })
    # Browser returns to success URL, but Stripe API reports unpaid
    unpaid_session = _stripe_session('cs_test_08', payment_status='unpaid', order_id=order_id)
    patches = _payment_patches(memory)
    with patches[0], patches[1], patches[2], \
            patch('modules.fr09_payment.routes.retrieveCheckoutSession', return_value=unpaid_session):
        response = client.get('/api/fr9/checkout/return/success?session_id=cs_test_08')

    assert response.status_code == 200
    assert 'Payment Processing' in response.get_data(as_text=True)
    persisted = memory.retrieve('checkout_orders', order_id)
    assert persisted['status'] != 'paid'
    assert persisted['paymentStatus'] != 'paid'


# Test 9: Invalid webhook signatures are rejected
def test_09_invalid_webhook_signatures_are_rejected(client):
    with patch.dict('os.environ', {'STRIPE_WEBHOOK_SECRET': 'whsec_test'}):
        response = client.post('/api/fr9/webhooks/stripe', data=b'invalid_payload',
                               headers={'Stripe-Signature': 'invalid_sig'})
    assert response.status_code == 400
    assert 'Invalid Stripe webhook' in response.get_json()['error']


# Test 10: Duplicate webhooks do not duplicate records or actions
def test_10_duplicate_webhooks_do_not_duplicate_records_or_actions(client):
    memory = MemoryPersistence()
    op_id, _ = _seed_hotel_prebook(memory)
    order_id = 'order_10'
    memory.seed('checkout_orders', order_id, {
        'id': order_id,
        'travellerId': 'test_traveller_uid',
        'quoteType': 'hotel',
        'status': 'checkout_open',
        'paymentStatus': 'unpaid',
        'amount': 350.0,
        'amountMinor': 35000,
        'currency': 'MYR',
        'checkoutSessionId': 'cs_test_10',
        'acceptedPrebookSnapshotId': op_id,
    })
    event = {
        'type': 'checkout.session.completed',
        'data': {'object': {
            'id': 'cs_test_10',
            'metadata': {'orderId': order_id},
            'status': 'complete',
            'payment_status': 'paid',
            'amount_total': 35000,
            'currency': 'myr',
            'payment_intent': 'pi_test_10',
        }},
    }
    patches = _payment_patches(memory)
    with patches[0], patches[1], patches[2], \
            patch('modules.fr09_payment.routes.constructStripeWebhookEvent', return_value=event):
        first = client.post('/api/fr9/webhooks/stripe', data=b'{}', headers={'Stripe-Signature': 'fixture'})
        second = client.post('/api/fr9/webhooks/stripe', data=b'{}', headers={'Stripe-Signature': 'fixture'})

    assert first.status_code == second.status_code == 200
    assert second.get_json().get('ignored') is True
    assert len(memory.collections['checkout_orders']) == 1


# Test 11: Reconciliation and webhook racing remain safe
def test_11_reconciliation_and_webhook_racing_remain_safe(client, mock_traveller_auth):
    memory = MemoryPersistence()
    op_id, _ = _seed_hotel_prebook(memory)
    order_id = operation_document_id('checkout_order', 'test_traveller_uid', 'order_11')
    memory.seed('checkout_orders', order_id, {
        'id': order_id,
        'travellerId': 'test_traveller_uid',
        'quoteType': 'hotel',
        'status': 'checkout_open',
        'paymentStatus': 'unpaid',
        'amount': 350.0,
        'amountMinor': 35000,
        'currency': 'MYR',
        'checkoutSessionId': 'cs_test_11',
        'acceptedPrebookSnapshotId': op_id,
    })
    session = _stripe_session('cs_test_11', payment_status='paid', amount_total=35000, order_id=order_id)
    event = {
        'type': 'checkout.session.completed',
        'data': {'object': {
            'id': 'cs_test_11',
            'metadata': {'orderId': order_id},
            'status': 'complete',
            'payment_status': 'paid',
            'amount_total': 35000,
            'currency': 'myr',
            'payment_intent': 'pi_test_11',
        }},
    }
    patches = _payment_patches(memory)
    with patches[0], patches[1], patches[2], \
            patch('modules.fr09_payment.routes.retrieveCheckoutSession', return_value=session), \
            patch('modules.fr09_payment.routes.constructStripeWebhookEvent', return_value=event):
        # Reconcile happens first
        r1 = client.get(f'/api/fr9/orders/{order_id}/reconcile', headers=AUTH)
        # Webhook arrives immediately after
        r2 = client.post('/api/fr9/webhooks/stripe', data=b'{}', headers={'Stripe-Signature': 'fixture'})

    assert r1.status_code == 200
    assert r2.status_code == 200
    order = memory.retrieve('checkout_orders', order_id)
    assert order['status'] == 'paid'
    assert order['paymentStatus'] == 'paid'
    assert order['fulfillmentStatus'] == 'demo_only'
    assert order['supplierBookingStatus'] == 'not_created'


# Test 12: Repeated Order reads have no side effects
def test_12_repeated_order_reads_have_no_side_effects(client, mock_traveller_auth):
    memory = MemoryPersistence()
    order_id = operation_document_id('checkout_order', 'test_traveller_uid', 'order_12')
    initial_record = {
        'id': order_id,
        'travellerId': 'test_traveller_uid',
        'quoteType': 'hotel',
        'status': 'paid',
        'paymentStatus': 'paid',
        'fulfillmentStatus': 'demo_only',
        'supplierBookingStatus': 'not_created',
        'amount': 350.0,
        'currency': 'MYR',
    }
    memory.seed('checkout_orders', order_id, deepcopy(initial_record))
    patches = _payment_patches(memory)
    with patches[0], patches[1], patches[2]:
        for _ in range(3):
            resp = client.get(f'/api/fr9/orders/{order_id}', headers=AUTH)
            assert resp.status_code == 200
            data = resp.get_json()['order']
            assert data['status'] == 'paid'
            assert data['fulfillmentStatus'] == 'demo_only'

    assert memory.retrieve('checkout_orders', order_id) == initial_record


# Test 13: Payment state survives simulated application restart
def test_13_payment_state_survives_simulated_application_restart(client, mock_traveller_auth):
    memory = MemoryPersistence()
    order_id = operation_document_id('checkout_order', 'test_traveller_uid', 'order_13')
    memory.seed('checkout_orders', order_id, {
        'id': order_id,
        'travellerId': 'test_traveller_uid',
        'quoteType': 'hotel',
        'status': 'paid',
        'paymentStatus': 'paid',
        'fulfillmentStatus': 'demo_only',
        'supplierBookingStatus': 'not_created',
        'amount': 350.0,
        'currency': 'MYR',
    })
    # Query via list_payments (used by PaymentHistoryScreen upon app startup)
    patches = _payment_patches(memory)
    with patches[0], patches[1], patches[2]:
        response = client.get('/api/fr9/payments', headers=AUTH)

    assert response.status_code == 200
    items = response.get_json()['items']
    match = next(it for it in items if it['id'] == order_id)
    assert match['paymentStatus'] == 'paid'
    assert match['fulfillmentStatus'] == 'demo_only'
    assert match['supplierBookingStatus'] == 'not_created'


# Test 14: Cross-user Order access is denied
def test_14_cross_user_order_access_is_denied(client, mock_traveller_auth):
    memory = MemoryPersistence()
    order_id = 'foreign_order_14'
    memory.seed('checkout_orders', order_id, {
        'id': order_id,
        'travellerId': 'different_traveller',
        'quoteType': 'hotel',
        'status': 'paid',
        'paymentStatus': 'paid',
        'amount': 350.0,
        'currency': 'MYR',
    })
    patches = _payment_patches(memory)
    with patches[0], patches[1], patches[2]:
        r1 = client.get(f'/api/fr9/orders/{order_id}', headers=AUTH)
        r2 = client.get(f'/api/fr9/orders/{order_id}/reconcile', headers=AUTH)

    assert r1.status_code == 404
    assert r2.status_code == 404


# Test 15: Legacy paid Hotel Orders remain readable
def test_15_legacy_paid_hotel_orders_remain_readable(client, mock_traveller_auth):
    memory = MemoryPersistence()
    order_id = operation_document_id('checkout_order', 'test_traveller_uid', 'order_15')
    # Historical record with no fulfillmentStatus
    historical_record = {
        'id': order_id,
        'travellerId': 'test_traveller_uid',
        'quoteType': 'hotel',
        'status': 'paid',
        'paymentStatus': 'paid',
        'amount': 350.0,
        'currency': 'MYR',
    }
    memory.seed('checkout_orders', order_id, deepcopy(historical_record))
    patches = _payment_patches(memory)
    with patches[0], patches[1], patches[2]:
        resp = client.get(f'/api/fr9/orders/{order_id}', headers=AUTH)
        payments_resp = client.get('/api/fr9/payments', headers=AUTH)

    assert resp.status_code == 200
    order = resp.get_json()['order']
    assert order['status'] == 'paid'
    assert order['fulfillmentStatus'] == 'demo_only'
    assert order['supplierBookingStatus'] == 'not_created'
    assert order['bookingReference'] is None

    # Original record was not modified on disk
    assert 'fulfillmentStatus' not in memory.retrieve('checkout_orders', order_id)

    item = next(it for it in payments_resp.get_json()['items'] if it['id'] == order_id)
    assert item['fulfillmentStatus'] == 'demo_only'
    assert item['supplierBookingStatus'] == 'not_created'


# Test 16: Historical Order amount remains unchanged
def test_16_historical_order_amount_remains_unchanged(client, mock_traveller_auth):
    memory = MemoryPersistence()
    order_id = operation_document_id('checkout_order', 'test_traveller_uid', 'order_16')
    memory.seed('checkout_orders', order_id, {
        'id': order_id,
        'travellerId': 'test_traveller_uid',
        'quoteType': 'hotel',
        'status': 'paid',
        'paymentStatus': 'paid',
        'amount': 888.50,
        'currency': 'MYR',
    })
    patches = _payment_patches(memory)
    with patches[0], patches[1], patches[2]:
        resp = client.get(f'/api/fr9/orders/{order_id}', headers=AUTH)

    assert resp.status_code == 200
    assert resp.get_json()['order']['amount'] == 888.50
    assert resp.get_json()['order']['currency'] == 'MYR'


# Test 17: Accepted-prebook snapshot binding remains enforced
def test_17_accepted_prebook_snapshot_binding_remains_enforced(client, mock_traveller_auth):
    memory = MemoryPersistence()
    patches = _payment_patches(memory)
    with patches[0], patches[1], patches[2]:
        response = client.post('/api/fr9/checkout/session', headers=AUTH,
                               json=_checkout_payload(snapshot_id='nonexistent_snapshot'))
    assert response.status_code == 409
    assert 'The accepted hotel prebook was not found' in response.get_json()['error']


# Test 18: Expired or mismatched snapshots remain rejected
def test_18_expired_or_mismatched_snapshots_remain_rejected(client, mock_traveller_auth):
    memory = MemoryPersistence()
    op_id, _ = _seed_hotel_prebook(memory, expires_at='2020-01-01T00:00:00+00:00')
    patches = _payment_patches(memory)
    with patches[0], patches[1], patches[2]:
        response = client.post('/api/fr9/checkout/session', headers=AUTH,
                               json=_checkout_payload(snapshot_id=op_id))
    assert response.status_code == 409
    assert 'expired' in response.get_json()['error']


# Test 19: Package Checkout remains unchanged
def test_19_package_checkout_remains_unchanged(client, mock_traveller_auth):
    memory = MemoryPersistence()
    # Seed package attempt
    memory.seed('package_checkout_attempts', 'pkg_att_19', {
        'id': 'pkg_att_19',
        'travellerId': 'test_traveller_uid',
        'packageId': 'pkg_19',
        'packageSnapshot': {
            'packageId': 'pkg_19',
            'title': 'Penang Package',
            'pricing': {'price': 500.0, 'currency': 'MYR'},
        },
        'checkoutStatus': 'checkout_pending',
        'paymentStatus': 'unpaid',
        'fulfillmentStatus': 'fulfillment_pending',
        'fulfillmentMode': 'legacy',
    })
    patches = _payment_patches(memory)
    session = _stripe_session(order_id='order_pkg_19', payment_status='paid', amount_total=50000)
    with patches[0], patches[1], patches[2], \
            patch('modules.fr09_payment.routes.retrieveCheckoutSession', return_value=session):
        order_id = operation_document_id('checkout_order', 'test_traveller_uid', 'pkg_att_19')
        memory.seed('checkout_orders', order_id, {
            'id': order_id,
            'travellerId': 'test_traveller_uid',
            'quoteType': 'package',
            'packageAttemptId': 'pkg_att_19',
            'status': 'checkout_open',
            'paymentStatus': 'unpaid',
            'amount': 500.0,
            'currency': 'MYR',
            'checkoutSessionId': 'cs_pkg_19',
        })
        resp = client.get(f'/api/fr9/orders/{order_id}/reconcile', headers=AUTH)

    assert resp.status_code == 200
    order = resp.get_json()['order']
    assert order['status'] == 'paid'
    assert order['quoteType'] == 'package'


# Test 20: Flight Checkout remains unchanged
def test_20_flight_checkout_remains_unchanged(client, mock_traveller_auth):
    memory = MemoryPersistence()
    memory.seed('flight_quotes', 'flight_quote_20', {
        'quoteId': 'flight_quote_20',
        'travellerId': 'test_traveller_uid',
        'price': 450.0,
        'currency': 'MYR',
        'expiresAt': FUTURE,
    })
    order_id = operation_document_id('checkout_order', 'test_traveller_uid', 'flight_order_20')
    memory.seed('checkout_orders', order_id, {
        'id': order_id,
        'travellerId': 'test_traveller_uid',
        'quoteType': 'flight',
        'status': 'checkout_open',
        'paymentStatus': 'unpaid',
        'amount': 450.0,
        'currency': 'MYR',
        'checkoutSessionId': 'cs_flight_20',
    })
    session = _stripe_session('cs_flight_20', payment_status='paid', amount_total=45000, order_id=order_id)
    patches = _payment_patches(memory)
    with patches[0], patches[1], patches[2], \
            patch('modules.fr09_payment.routes.retrieveCheckoutSession', return_value=session):
        resp = client.get(f'/api/fr9/orders/{order_id}/reconcile', headers=AUTH)

    assert resp.status_code == 200
    order = resp.get_json()['order']
    assert order['status'] == 'paid'
    assert order['quoteType'] == 'flight'


# Test 21: Failed Stripe payments cannot be presented as paid
def test_21_failed_stripe_payments_cannot_be_presented_as_paid(client, mock_traveller_auth):
    memory = MemoryPersistence()
    op_id, _ = _seed_hotel_prebook(memory)
    order_id = 'order_21'
    memory.seed('checkout_orders', order_id, {
        'id': order_id,
        'travellerId': 'test_traveller_uid',
        'quoteType': 'hotel',
        'status': 'checkout_open',
        'paymentStatus': 'unpaid',
        'amount': 350.0,
        'currency': 'MYR',
        'checkoutSessionId': 'cs_test_21',
        'acceptedPrebookSnapshotId': op_id,
    })
    failed_event = {
        'type': 'checkout.session.async_payment_failed',
        'data': {'object': {
            'id': 'cs_test_21',
            'metadata': {'orderId': order_id},
        }},
    }
    patches = _payment_patches(memory)
    with patches[0], patches[1], patches[2], \
            patch('modules.fr09_payment.routes.constructStripeWebhookEvent', return_value=failed_event):
        client.post('/api/fr9/webhooks/stripe', data=b'{}', headers={'Stripe-Signature': 'fixture'})

    persisted = memory.retrieve('checkout_orders', order_id)
    assert persisted['status'] == 'payment_failed'
    assert persisted['paymentStatus'] == 'failed'
    assert persisted['fulfillmentStatus'] == 'not_started'
    assert persisted['supplierBookingStatus'] == 'not_created'


# Test 22: No real LiteAPI mutation occurs in any test
def test_22_no_real_liteapi_mutation_occurs_in_any_test():
    with patch.dict('os.environ', {'TRAVELMATE_TESTING': 'false'}, clear=False):
        assert provider_mutations_allowed() is False
        with pytest.raises(ProviderMutationBlocked):
            createBookingReference({'prebookId': 'test_prebook'})
