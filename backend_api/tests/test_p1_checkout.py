import hashlib
import hmac
import json
import time
import pytest
from types import SimpleNamespace
from unittest.mock import patch

from services.stripe_service import constructStripeWebhookEvent
from test_fr08_fr09_hotels_payments import MemoryPersistence


def test_liteapi_offer_total_and_currency_are_preserved_without_defaults():
    from services.liteapi_service import normalizeHotelOffers

    items = normalizeHotelOffers({
        'data': [{
            'hotelId': 'hotel_p1',
            'roomTypes': [{
                'offerId': 'offer_p1',
                'offerRetailRate': {'amount': 220, 'currency': 'MYR'},
                'rates': [{
                    'adultCount': 2,
                    'retailRate': {
                        'total': [{'amount': 220, 'currency': 'MYR'}],
                        'taxesAndFees': [{'included': True}],
                    },
                }],
            }],
        }],
        'sandbox': True,
    })
    assert items[0]['price'] == 220
    assert items[0]['priceBasis'] == 'stay_total'
    assert items[0]['priceScope'] == 'provider_offer_total'
    assert items[0]['taxesAndFeesStatus'] == 'included'
    assert items[0]['currency'] == 'MYR'

    missing_currency = normalizeHotelOffers({
        'data': [{
            'hotelId': 'hotel_p1',
            'roomTypes': [{
                'offerId': 'offer_missing_currency',
                'rates': [{'retailRate': {'total': [{'amount': 220}]}}],
            }],
        }],
    })
    assert missing_currency[0]['currency'] is None
    assert missing_currency[0]['currencyStatus'] == 'unknown'


def _hotel_quote():
    return {
        'quoteId': 'quote_hotel_p1',
        'travellerId': 'test_traveller_uid',
        'offer': {
            'offerId': 'offer_hotel_p1',
            'hotelId': 'hotel_p1',
            'name': 'Sandbox Penang Hotel',
            'price': 220.0,
            'priceStatus': 'available',
            'priceBasis': 'stay_total',
            'priceScope': 'provider_offer_total',
            'priceSemanticsStatus': 'provider_offer_total_includes_base_and_included_taxes_fees',
            'currency': 'MYR',
            'currencyStatus': 'known',
            'taxesAndFeesStatus': 'included',
            'rateProvenance': 'sandbox_provider_quote',
        },
        'criteria': {'roomQuantity': 1, 'occupancies': [{'adults': 2}]},
    }


def _patch_persistence(memory):
    return (
        patch('modules.fr09_payment.routes.claimRecord', side_effect=memory.claim),
        patch('modules.fr09_payment.routes.retrieveRecord', side_effect=memory.retrieve),
        patch('modules.fr09_payment.routes.updateRecord', side_effect=memory.update),
    )


def test_checkout_claims_owned_hotel_quote_and_reuses_session(client, mock_traveller_auth):
    memory = MemoryPersistence()
    memory.seed('hotel_offer_quotes', 'test_traveller_uid_quote_hotel_p1', _hotel_quote())
    session = SimpleNamespace(id='cs_test_p1', url='https://checkout.stripe.test/cs_test_p1')
    with patch.dict('os.environ', {'STRIPE_SECRET_KEY': 'sk_test_fixture'}), \
         _patch_persistence(memory)[0], _patch_persistence(memory)[1], _patch_persistence(memory)[2], \
         patch('modules.fr09_payment.routes.createCheckoutSession', return_value=session) as create:
        payload = {
            'orderAttemptId': 'order_attempt_p1',
            'quoteType': 'hotel',
            'quoteId': 'quote_hotel_p1',
            'offerId': 'offer_hotel_p1',
        }
        first = client.post('/api/fr9/checkout/session', headers={
            'Authorization': 'Bearer valid_test_token'}, json=payload)
        duplicate = client.post('/api/fr9/checkout/session', headers={
            'Authorization': 'Bearer valid_test_token'}, json=payload)
    assert first.status_code == duplicate.status_code == 200
    assert first.get_json()['order']['amount'] == 220.0
    assert first.get_json()['order']['checkoutUrl'].startswith('https://checkout')
    assert duplicate.get_json()['reused'] is True
    assert create.call_count == 1
    assert '/api/fr9/checkout/return/success' in create.call_args.args[4]
    assert 'example.com' not in create.call_args.args[4]


def test_checkout_rejects_missing_hotel_currency_and_ambiguous_basis(client, mock_traveller_auth):
    memory = MemoryPersistence()
    quote = _hotel_quote()
    quote['offer']['currency'] = ''
    quote['offer']['currencyStatus'] = 'unknown'
    memory.seed('hotel_offer_quotes', 'test_traveller_uid_quote_hotel_p1', quote)
    with _patch_persistence(memory)[0], _patch_persistence(memory)[1], _patch_persistence(memory)[2]:
        response = client.post('/api/fr9/checkout/session', headers={
            'Authorization': 'Bearer valid_test_token'}, json={
                'orderAttemptId': 'order_attempt_p1', 'quoteType': 'hotel',
                'quoteId': 'quote_hotel_p1', 'offerId': 'offer_hotel_p1',
            })
    assert response.status_code == 409
    assert 'validated MYR currency' in response.get_json()['error']


def test_checkout_requires_complete_adult_party_flight_quote(client, mock_traveller_auth):
    memory = MemoryPersistence()
    memory.seed('flight_quotes', 'test_traveller_uid_search_p1', {
        'id': 'search_p1', 'travellerId': 'test_traveller_uid', 'source': 'serpapi',
        'criteria': {'currency': 'MYR', 'traveller_count': 2, 'return_date': None},
        'items': [{
            'optionId': 'flight_option_p1', 'price': 400.0, 'currency': 'MYR',
            'currencyStatus': 'known', 'priceStatus': 'available',
            'priceBasis': 'itinerary_total', 'priceScope': 'provider_ticket_price',
            'priceSemanticsStatus': 'provider_response_requested_adults',
            'travellerCount': 1, 'passengerComposition': {'adults': 1},
            'quoteCompleteness': 'complete', 'budgetEligible': True,
        }],
    })
    with _patch_persistence(memory)[0], _patch_persistence(memory)[1], _patch_persistence(memory)[2]:
        response = client.post('/api/fr9/checkout/session', headers={
            'Authorization': 'Bearer valid_test_token'}, json={
                'orderAttemptId': 'order_attempt_flight', 'quoteType': 'flight',
                'searchId': 'search_p1', 'optionId': 'flight_option_p1',
            })
    assert response.status_code == 409
    assert 'adult party' in response.get_json()['error']


def test_checkout_accepts_provider_flight_quote_for_requested_adults(client, mock_traveller_auth):
    memory = MemoryPersistence()
    memory.seed('flight_quotes', 'test_traveller_uid_search_p1', {
        'id': 'search_p1', 'travellerId': 'test_traveller_uid', 'source': 'serpapi',
        'criteria': {'currency': 'MYR', 'traveller_count': 2, 'return_date': None},
        'items': [{
            'optionId': 'flight_option_p1', 'price': 800.0, 'currency': 'MYR',
            'currencyStatus': 'known', 'priceStatus': 'available',
            'priceBasis': 'itinerary_total', 'priceScope': 'provider_ticket_price',
            'priceSemanticsStatus': 'provider_response_requested_adults',
            'travellerCount': 2, 'passengerComposition': {'adults': 2},
            'quoteCompleteness': 'complete', 'budgetEligible': True,
        }],
    })
    session = SimpleNamespace(id='cs_test_flight_p1', url='https://checkout.stripe.test/cs_test_flight_p1')
    with patch.dict('os.environ', {'STRIPE_SECRET_KEY': 'sk_test_fixture'}), \
         _patch_persistence(memory)[0], _patch_persistence(memory)[1], _patch_persistence(memory)[2], \
         patch('modules.fr09_payment.routes.createCheckoutSession', return_value=session):
        response = client.post('/api/fr9/checkout/session', headers={
            'Authorization': 'Bearer valid_test_token'}, json={
                'orderAttemptId': 'order_attempt_flight', 'quoteType': 'flight',
                'searchId': 'search_p1', 'optionId': 'flight_option_p1',
            })
    assert response.status_code == 200
    assert response.get_json()['order']['amount'] == 800.0


def test_signed_checkout_webhook_marks_owned_order_paid(client, mock_traveller_auth):
    memory = MemoryPersistence()
    memory.seed('checkout_orders', 'order_doc_p1', {
        'travellerId': 'test_traveller_uid', 'amount': 220.0, 'currency': 'MYR',
        'status': 'checkout_open', 'paymentStatus': 'unpaid',
        'checkoutSessionId': 'cs_test_p1',
    })
    event = {
        'type': 'checkout.session.completed',
        'data': {'object': {
            'metadata': {'orderId': 'order_doc_p1'},
            'status': 'complete', 'payment_status': 'paid',
            'amount_total': 22000, 'currency': 'myr',
            'payment_intent': 'pi_test_p1',
        }},
    }
    with patch('modules.fr09_payment.routes.constructStripeWebhookEvent', return_value=event), \
         _patch_persistence(memory)[1], _patch_persistence(memory)[2]:
        response = client.post('/api/fr9/webhooks/stripe', data=b'{}', headers={
            'Stripe-Signature': 'fixture'})
    assert response.status_code == 200
    assert memory.retrieve('checkout_orders', 'order_doc_p1')['status'] == 'paid'
    assert memory.retrieve('checkout_orders', 'order_doc_p1')['stripePaymentIntentId'] == 'pi_test_p1'

    failed_event = {
        'type': 'checkout.session.async_payment_failed',
        'data': {'object': {'metadata': {'orderId': 'order_doc_p1'}}},
    }
    with patch('modules.fr09_payment.routes.constructStripeWebhookEvent', return_value=failed_event), \
         _patch_persistence(memory)[1], _patch_persistence(memory)[2]:
        later_failure = client.post('/api/fr9/webhooks/stripe', data=b'{}', headers={
            'Stripe-Signature': 'fixture'})
    assert later_failure.status_code == 200
    assert memory.retrieve('checkout_orders', 'order_doc_p1')['status'] == 'paid'


def test_webhook_without_verification_secret_is_safe(client):
    with patch.dict('os.environ', {'STRIPE_WEBHOOK_SECRET': ''}):
        response = client.post('/api/fr9/webhooks/stripe', data=b'{}', headers={
            'Stripe-Signature': 'fixture'})
    assert response.status_code == 503
    assert 'secret' not in response.get_data(as_text=True).lower()


def test_stripe_webhook_signature_verifies_offline():
    payload = json.dumps({'id': 'evt_fixture', 'type': 'checkout.session.completed'}).encode()
    timestamp = int(time.time())
    digest = hmac.new(
        b'whsec_fixture', f'{timestamp}.'.encode() + payload, hashlib.sha256
    ).hexdigest()
    signature = f't={timestamp},v1={digest}'
    with patch.dict('os.environ', {'STRIPE_WEBHOOK_SECRET': 'whsec_fixture'}):
        event = constructStripeWebhookEvent(payload, signature)
    assert event['id'] == 'evt_fixture'


def test_checkout_reconcile_is_safe_when_provider_is_still_open(client, mock_traveller_auth):
    memory = MemoryPersistence()
    memory.seed('checkout_orders', 'order_doc_p1', {
        'travellerId': 'test_traveller_uid', 'amount': 220.0, 'currency': 'MYR',
        'status': 'checkout_open', 'paymentStatus': 'unpaid',
        'checkoutSessionId': 'cs_test_p1',
    })
    session = SimpleNamespace(status='open', payment_status='unpaid', amount_total=22000, currency='myr')
    with patch('modules.fr09_payment.routes.retrieveCheckoutSession', return_value=session), \
         _patch_persistence(memory)[1], _patch_persistence(memory)[2]:
        response = client.get('/api/fr9/orders/order_doc_p1/reconcile', headers={
            'Authorization': 'Bearer valid_test_token'})
    assert response.status_code == 202
    assert response.get_json()['order']['status'] == 'checkout_open'


def test_legacy_payment_mutations_are_blocked_outside_test_harness(client, mock_traveller_auth):
    with patch.dict('os.environ', {'TRAVELMATE_TESTING': 'false'}), \
         patch('modules.fr09_payment.routes.processPaymentAttempt') as process:
        legacy = client.post('/api/fr9/payments/process', headers={
            'Authorization': 'Bearer valid_test_token'}, json={
                'paymentAttemptId': 'legacy_bypass', 'amount': 0.01,
            })
        intent = client.post('/api/fr9/payments/create-intent', headers={
            'Authorization': 'Bearer valid_test_token'}, json={
                'paymentAttemptId': 'legacy_intent_bypass', 'amount': 0.01,
            })
    assert legacy.status_code == intent.status_code == 409
    assert legacy.get_json()['error'] == 'Use a validated Checkout order for payment.'
    assert intent.get_json()['error'] == 'Use a validated Checkout order for payment.'
    process.assert_not_called()


def test_paid_checkout_order_cannot_be_reused(client, mock_traveller_auth):
    from services.transaction_reliability import operation_document_id

    memory = MemoryPersistence()
    memory.seed('hotel_offer_quotes', 'test_traveller_uid_quote_hotel_p1', _hotel_quote())
    order_id = operation_document_id('checkout_order', 'test_traveller_uid', 'paid_attempt')
    memory.seed('checkout_orders', order_id, {
        'id': order_id,
        'travellerId': 'test_traveller_uid',
        'orderAttemptId': 'paid_attempt',
        'quoteType': 'hotel',
        'quoteId': 'quote_hotel_p1',
        'offerId': 'offer_hotel_p1',
        'amount': 220.0,
        'currency': 'MYR',
        'status': 'paid',
        'paymentStatus': 'paid',
        'checkoutSessionId': 'cs_paid_p1',
        'checkoutUrl': 'https://checkout.stripe.test/cs_paid_p1',
    })
    with _patch_persistence(memory)[0], _patch_persistence(memory)[1], _patch_persistence(memory)[2], \
         patch('modules.fr09_payment.routes.createCheckoutSession') as create:
        response = client.post('/api/fr9/checkout/session', headers={
            'Authorization': 'Bearer valid_test_token'}, json={
                'orderAttemptId': 'paid_attempt', 'quoteType': 'hotel',
                'quoteId': 'quote_hotel_p1', 'offerId': 'offer_hotel_p1',
            })
    assert response.status_code == 409
    assert 'already been paid' in response.get_json()['error']
    create.assert_not_called()


def test_checkout_return_reconciles_and_keeps_order_details_private(client):
    memory = MemoryPersistence()
    memory.seed('checkout_orders', 'order_return_p1', {
        'id': 'order_return_p1', 'travellerId': 'test_traveller_uid',
        'amount': 220.0, 'currency': 'MYR', 'status': 'checkout_open',
        'paymentStatus': 'unpaid', 'checkoutSessionId': 'cs_return_p1',
    })
    session = SimpleNamespace(
        id='cs_return_p1', metadata={'orderId': 'order_return_p1'},
        status='complete', payment_status='paid', amount_total=22000,
        currency='myr', payment_intent='pi_return_p1',
    )
    with patch('modules.fr09_payment.routes.retrieveCheckoutSession', return_value=session), \
         _patch_persistence(memory)[1], _patch_persistence(memory)[2]:
        response = client.get('/api/fr9/checkout/return/success?session_id=cs_return_p1')
    assert response.status_code == 200
    assert 'Payment verified' in response.get_data(as_text=True)
    assert 'order_return_p1' not in response.get_data(as_text=True)
    assert memory.retrieve('checkout_orders', 'order_return_p1')['status'] == 'paid'
    assert memory.retrieve('checkout_orders', 'order_return_p1')['stripePaymentIntentId'] == 'pi_return_p1'


def test_placeholder_checkout_return_url_is_rejected():
    from modules.fr09_payment.routes import _configured_checkout_url

    with patch.dict('os.environ', {'STRIPE_CHECKOUT_SUCCESS_URL': 'https://example.com/travelmate/success'}):
        with pytest.raises(RuntimeError, match='explicit TravelMate return URL'):
            _configured_checkout_url('STRIPE_CHECKOUT_SUCCESS_URL', 'http://127.0.0.1:5000/return')
