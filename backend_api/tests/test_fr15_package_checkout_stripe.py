from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from test_fr15_package_checkout_api import AtomicMemory


class PaymentMemory(AtomicMemory):
    def update(self, collection, document_id, data):
        with self._lock:
            records = self.collections.setdefault(collection, {})
            if document_id not in records:
                return None
            records[document_id] = {**records[document_id], **deepcopy(data)}
            return deepcopy(records[document_id])


@pytest.fixture
def package_payment(client, monkeypatch):
    memory = PaymentMemory()
    uid = 'traveller-1'
    memory.seed('users', uid, {'role': 'traveller', 'status': 'active'})

    def database():
        def document(document_id):
            profile = memory.retrieve('users', document_id)
            return SimpleNamespace(get=lambda: SimpleNamespace(
                exists=bool(profile), to_dict=lambda: deepcopy(profile)
            ))
        return SimpleNamespace(collection=lambda _name: SimpleNamespace(document=document))

    monkeypatch.setattr('auth_utils.auth.verify_id_token', lambda token: {'uid': token})
    monkeypatch.setattr('auth_utils.get_db', database)
    monkeypatch.setattr('modules.fr09_payment.routes.retrieveRecord', memory.retrieve)
    monkeypatch.setattr('modules.fr09_payment.routes.claimRecord', memory.claim)
    monkeypatch.setattr('modules.fr09_payment.routes.updateRecord', memory.update)
    return memory, {'Authorization': f'Bearer {uid}'}


def seed_attempt(memory, trip_id='trip-1', **extra):
    snapshot = {
        'packageId': 'package-1', 'operatorId': 'operator-1', 'title': 'Penang Weekend',
        'destination': 'Penang', 'price': 450.25, 'currency': 'MYR', 'taxIncluded': True,
        'itineraryDays': [{'dayNumber': 1, 'activities': ['Heritage walk']}],
    }
    memory.seed('package_checkout_attempts', 'attempt-1', {
        'travellerId': 'traveller-1', 'packageSnapshot': snapshot,
        'checkoutStatus': 'checkout_pending', 'paymentStatus': 'payment_pending',
        'intendedTripId': trip_id, **extra,
    })
    return snapshot


def session_response():
    return SimpleNamespace(id='cs_package_1', url='https://checkout.stripe.test/cs_package_1')


def start_checkout(client, headers):
    return client.post('/api/fr9/package-checkout-attempts/attempt-1/checkout/session', headers=headers, json={})


def test_package_checkout_session_is_owned_immutable_and_idempotent(client, package_payment):
    memory, headers = package_payment
    snapshot = seed_attempt(memory)
    with patch('modules.fr09_payment.routes.createCheckoutSession', return_value=session_response()) as create:
        first = start_checkout(client, headers)
        repeat = start_checkout(client, headers)
    assert first.status_code == repeat.status_code == 200
    order = first.get_json()['order']
    assert order['quoteType'] == 'package' and order['amountMinor'] == 45025
    assert order['packageSnapshot'] == snapshot and repeat.get_json()['reused'] is True
    assert create.call_count == 1
    assert create.call_args.kwargs['idempotency_key']


def test_package_checkout_rejects_unowned_or_invalid_attempt(client, package_payment):
    memory, headers = package_payment
    seed_attempt(memory, travellerId='another-traveller')
    assert start_checkout(client, headers).status_code == 404
    memory.seed('package_checkout_attempts', 'attempt-1', {
        'travellerId': 'traveller-1', 'packageSnapshot': {'price': 0, 'currency': 'MYR'},
    })
    assert start_checkout(client, headers).status_code == 409


def test_package_checkout_timeout_is_pending_not_false_success(client, package_payment):
    memory, headers = package_payment
    seed_attempt(memory)
    with patch('modules.fr09_payment.routes.createCheckoutSession', side_effect=TimeoutError()):
        response = start_checkout(client, headers)
    assert response.status_code == 202
    order = next(iter(memory.collections['checkout_orders'].values()))
    assert order.get('checkoutSessionId') is None and order['reconciliationRequired'] is True


def _event(order, **extra):
    return {'type': 'checkout.session.completed', 'data': {'object': {
        'id': order['checkoutSessionId'],
        'metadata': {'orderId': order['id'], 'packageAttemptId': 'attempt-1'},
        'status': 'complete', 'payment_status': 'paid', 'amount_total': order['amountMinor'],
        'currency': 'myr', 'payment_intent': 'pi_package_1', **extra,
    }}}


def test_signed_paid_webhook_fulfills_trip_once_without_supplier_booking(client, package_payment):
    memory, headers = package_payment
    seed_attempt(memory)
    memory.seed('itineraries', 'trip-1', {'travellerId': 'traveller-1', 'destinationArea': 'Penang'})
    with patch('modules.fr09_payment.routes.createCheckoutSession', return_value=session_response()):
        order = start_checkout(client, headers).get_json()['order']
    event = _event(order)
    with patch('modules.fr09_payment.routes.constructStripeWebhookEvent', return_value=event):
        first = client.post('/api/fr9/webhooks/stripe', data=b'{}', headers={'Stripe-Signature': 'fixture'})
        duplicate = client.post('/api/fr9/webhooks/stripe', data=b'{}', headers={'Stripe-Signature': 'fixture'})
    assert first.status_code == duplicate.status_code == 200
    assert memory.retrieve('checkout_orders', order['id'])['status'] == 'paid'
    assert memory.retrieve('package_checkout_attempts', 'attempt-1')['fulfillmentStatus'] == 'fulfilled'
    assert len(memory.retrieve('itineraries', 'trip-1')['purchasedPackages']) == 1
    assert 'hotel_bookings' not in memory.collections and 'flight_bookings' not in memory.collections


@pytest.mark.parametrize('extra', [
    {'amount_total': 1}, {'currency': 'usd'},
])
def test_paid_webhook_rejects_amount_or_currency_mismatch(client, package_payment, extra):
    memory, headers = package_payment
    seed_attempt(memory)
    memory.seed('itineraries', 'trip-1', {'travellerId': 'traveller-1', 'destinationArea': 'Penang'})
    with patch('modules.fr09_payment.routes.createCheckoutSession', return_value=session_response()):
        order = start_checkout(client, headers).get_json()['order']
    with patch('modules.fr09_payment.routes.constructStripeWebhookEvent', return_value=_event(order, **extra)):
        assert client.post('/api/fr9/webhooks/stripe', data=b'{}', headers={'Stripe-Signature': 'fixture'}).status_code == 200
    assert memory.retrieve('checkout_orders', order['id'])['status'] == 'payment_mismatch'
    assert 'purchasedPackages' not in memory.retrieve('itineraries', 'trip-1')


def test_paid_webhook_keeps_payment_when_trip_is_missing_or_incompatible(client, package_payment):
    memory, headers = package_payment
    seed_attempt(memory, trip_id='missing-trip')
    with patch('modules.fr09_payment.routes.createCheckoutSession', return_value=session_response()):
        order = start_checkout(client, headers).get_json()['order']
    with patch('modules.fr09_payment.routes.constructStripeWebhookEvent', return_value=_event(order)):
        assert client.post('/api/fr9/webhooks/stripe', data=b'{}', headers={'Stripe-Signature': 'fixture'}).status_code == 200
    saved = memory.retrieve('checkout_orders', order['id'])
    assert saved['status'] == 'paid' and saved['fulfillmentStatus'] == 'fulfillment_pending'


def test_paid_package_fulfillment_retries_after_trip_recovery(client, package_payment):
    memory, headers = package_payment
    seed_attempt(memory, trip_id='recovered-trip')
    with patch('modules.fr09_payment.routes.createCheckoutSession', return_value=session_response()):
        order = start_checkout(client, headers).get_json()['order']
    event = _event(order)
    with patch('modules.fr09_payment.routes.constructStripeWebhookEvent', return_value=event):
        client.post('/api/fr9/webhooks/stripe', data=b'{}', headers={'Stripe-Signature': 'fixture'})
    memory.seed('itineraries', 'recovered-trip', {
        'travellerId': 'traveller-1', 'destinationArea': 'Penang',
    })
    session = event['data']['object']
    with patch('modules.fr09_payment.routes.retrieveCheckoutSession', return_value=session):
        reconciled = client.get(f"/api/fr9/orders/{order['id']}/reconcile", headers=headers)
    assert reconciled.status_code == 200
    assert memory.retrieve('checkout_orders', order['id'])['fulfillmentStatus'] == 'fulfilled'
    assert len(memory.retrieve('itineraries', 'recovered-trip')['purchasedPackages']) == 1


def test_webhook_rejects_invalid_signature_or_wrong_session(client, package_payment):
    memory, headers = package_payment
    seed_attempt(memory)
    with patch('modules.fr09_payment.routes.createCheckoutSession', return_value=session_response()):
        order = start_checkout(client, headers).get_json()['order']
    with patch('modules.fr09_payment.routes.constructStripeWebhookEvent', side_effect=ValueError()):
        assert client.post('/api/fr9/webhooks/stripe', data=b'{}').status_code == 400
    bad = _event(order, id='cs_other')
    with patch('modules.fr09_payment.routes.constructStripeWebhookEvent', return_value=bad):
        assert client.post('/api/fr9/webhooks/stripe', data=b'{}', headers={'Stripe-Signature': 'fixture'}).status_code == 400


def test_late_paid_event_supersedes_earlier_async_failure(client, package_payment):
    memory, headers = package_payment
    seed_attempt(memory)
    memory.seed('itineraries', 'trip-1', {'travellerId': 'traveller-1', 'destinationArea': 'Penang'})
    with patch('modules.fr09_payment.routes.createCheckoutSession', return_value=session_response()):
        order = start_checkout(client, headers).get_json()['order']
    failed = {'type': 'checkout.session.async_payment_failed', 'data': {'object': {
        'id': order['checkoutSessionId'],
        'metadata': {'orderId': order['id'], 'packageAttemptId': 'attempt-1'},
    }}}
    with patch('modules.fr09_payment.routes.constructStripeWebhookEvent', return_value=failed):
        assert client.post('/api/fr9/webhooks/stripe', data=b'{}', headers={'Stripe-Signature': 'fixture'}).status_code == 200
    with patch('modules.fr09_payment.routes.constructStripeWebhookEvent', return_value=_event(order)):
        assert client.post('/api/fr9/webhooks/stripe', data=b'{}', headers={'Stripe-Signature': 'fixture'}).status_code == 200
    assert memory.retrieve('checkout_orders', order['id'])['status'] == 'paid'
    assert memory.retrieve('package_checkout_attempts', 'attempt-1')['fulfillmentStatus'] == 'fulfilled'
