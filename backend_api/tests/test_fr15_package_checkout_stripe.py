from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from test_fr15_package_checkout_api import AtomicMemory


class PaymentMemory(AtomicMemory):
    def update(self, collection, document_id, data, expected=None):
        with self._lock:
            records = self.collections.setdefault(collection, {})
            if document_id not in records:
                return None
            if expected is not None and records[document_id] != expected:
                from services.review_service import ReviewConflict
                raise ReviewConflict('Changed')
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

    monkeypatch.setattr('auth_utils.auth.verify_id_token', lambda token, *a, **k: {'uid': token})
    monkeypatch.setattr('auth_utils.get_db', database)
    monkeypatch.setattr('modules.fr09_payment.routes.retrieveRecord', memory.retrieve)
    monkeypatch.setattr('modules.fr09_payment.routes.claimRecord', memory.claim)
    monkeypatch.setattr('modules.fr09_payment.routes.updateRecord', memory.update)
    memory.seed('tourism_packages','package-1',{'operatorId':'operator-1','approvalStatus':'approved','availabilityStatus':'available'})
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


def seed_group_attempt(memory, **extra):
    snapshot = {
        'contractVersion': 2,
        'packageId': 'package-1', 'operatorId': 'operator-1',
        'title': 'Penang Weekend', 'destination': 'Penang',
        'durationDays': 2, 'selectedDepartureDate': '2027-02-10',
        'priceBasis': 'per_person', 'adultUnitPrice': 450.25,
        'childUnitPrice': 175, 'price': 1075.50, 'amountMinor': 107550,
        'currency': 'MYR', 'taxIncluded': True,
        'participants': {'adults': 2, 'children': 1, 'total': 3}, 'groupSize': 3,
        'itineraryDays': [{
            'dayNumber': 1, 'title': 'Heritage day',
            'description': 'Approved package itinerary.',
            'activities': ['Heritage walk'],
        }],
    }
    memory.seed('package_checkout_attempts', 'attempt-1', {
        'travellerId': 'traveller-1', 'packageSnapshot': snapshot,
        'checkoutStatus': 'checkout_pending', 'paymentStatus': 'payment_pending',
        'participants': snapshot['participants'], 'groupSize': 3,
        'selectedDepartureDate': '2027-02-10',
        'fulfillmentMode': 'independent_package_trip', **extra,
    })
    return snapshot


def session_response():
    return SimpleNamespace(
        id='cs_package_1', url='https://checkout.stripe.test/cs_package_1',
        status='open', payment_status='unpaid', amount_total=45025,
        currency='myr', payment_intent=None,
    )


def start_checkout(client, headers):
    return client.post('/api/fr9/package-checkout-attempts/attempt-1/checkout/session', headers=headers, json={})


def test_package_checkout_session_is_owned_immutable_and_idempotent(client, package_payment):
    memory, headers = package_payment
    snapshot = seed_attempt(memory)
    with patch.dict('os.environ', {
             'APP_ENV': 'development',
             'LOCAL_LAN_DEMO': 'true',
             'TRUSTED_LAN_CIDR': '172.20.10.0/24',
             'STRIPE_CHECKOUT_RETURN_ORIGIN': 'http://172.20.10.5:5000',
         }), patch('modules.fr09_payment.routes.createCheckoutSession', return_value=session_response()) as create, \
            patch('modules.fr09_payment.routes.retrieveCheckoutSession', return_value=session_response()):
        first = start_checkout(client, headers)
        repeat = start_checkout(client, headers)
    assert first.status_code == repeat.status_code == 200
    order = first.get_json()['order']
    assert order['quoteType'] == 'package' and order['amountMinor'] == 45025
    assert order['packageSnapshot'] == snapshot and repeat.get_json()['reused'] is True
    assert create.call_count == 1
    assert create.call_args.kwargs['idempotency_key']
    assert create.call_args.args[4].startswith(
        'http://172.20.10.5:5000/api/fr9/checkout/return/success?')
    assert create.call_args.args[5].startswith(
        'http://172.20.10.5:5000/api/fr9/checkout/return/cancel?')
    assert first.get_json()['order']['checkoutAction'] == 'continue_payment'
    assert repeat.get_json()['order']['checkoutUrl'].endswith('/cs_package_1')
    listed = client.get('/api/fr9/orders', headers=headers).get_json()['items'][0]
    assert listed['checkoutAction'] == 'continue_payment'
    assert 'checkoutUrl' not in listed


@pytest.mark.parametrize(('session_status', 'payment_status', 'expected_action', 'expected_code'), [
    ('complete', 'paid', 'view_booking', 200),
    ('complete', 'unpaid', 'check_status', 202),
    ('expired', 'unpaid', 'restart_payment', 200),
])
def test_stored_package_session_is_reconciled_before_url_reuse(
        client, package_payment, session_status, payment_status, expected_action, expected_code):
    memory, headers = package_payment
    seed_attempt(memory)
    with patch('modules.fr09_payment.routes.createCheckoutSession', return_value=session_response()):
        first = start_checkout(client, headers)
    assert first.status_code == 200
    provider = SimpleNamespace(
        id='cs_package_1', url='https://checkout.stripe.test/cs_package_1',
        status=session_status, payment_status=payment_status,
        amount_total=45025, currency='myr', payment_intent='pi_package_1',
    )
    with patch('modules.fr09_payment.routes.retrieveCheckoutSession', return_value=provider):
        retry = start_checkout(client, headers)
    body = retry.get_json()
    assert retry.status_code == expected_code
    assert body['order']['checkoutAction'] == expected_action
    assert 'checkoutUrl' not in body['order']
    saved = next(iter(memory.collections['checkout_orders'].values()))
    assert saved['checkoutSessionStatus'] == session_status
    assert memory.retrieve('package_checkout_attempts', 'attempt-1')['checkoutStatus'] == saved['status']


def test_stored_package_session_verification_failure_never_returns_stale_url(
        client, package_payment):
    memory, headers = package_payment
    seed_attempt(memory)
    with patch('modules.fr09_payment.routes.createCheckoutSession', return_value=session_response()):
        assert start_checkout(client, headers).status_code == 200
    with patch('modules.fr09_payment.routes.retrieveCheckoutSession', side_effect=TimeoutError()):
        retry = start_checkout(client, headers)
    assert retry.status_code == 202
    assert retry.get_json()['order']['checkoutAction'] == 'check_status'
    assert 'checkoutUrl' not in retry.get_json()['order']


def test_package_checkout_rejects_unowned_or_invalid_attempt(client, package_payment):
    memory, headers = package_payment
    seed_attempt(memory, travellerId='another-traveller')
    assert start_checkout(client, headers).status_code == 404
    memory.seed('package_checkout_attempts', 'attempt-1', {
        'travellerId': 'traveller-1', 'packageSnapshot': {'price': 0, 'currency': 'MYR'},
    })
    assert start_checkout(client, headers).status_code == 409
    seed_attempt(memory, paymentStatus='paid')
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


def test_group_checkout_creates_one_independent_package_trip_and_preserves_personal_trip(
        client, package_payment):
    memory, headers = package_payment
    snapshot = seed_group_attempt(memory)
    personal = {
        'travellerId': 'traveller-1', 'title': 'My personal trip',
        'destinationArea': 'Penang', 'activities': [{'activityName': 'Personal plan'}],
    }
    memory.seed('itineraries', 'personal-trip', personal)
    with patch(
        'modules.fr09_payment.routes.createCheckoutSession', return_value=session_response()
    ) as create:
        order = start_checkout(client, headers).get_json()['order']
    assert order['amountMinor'] == 107550
    assert order['groupSize'] == 3
    assert create.call_args.args[0] == 1075.50
    assert create.call_args.args[1] == 'MYR'
    event = _event(order)
    with patch('modules.fr09_payment.routes.constructStripeWebhookEvent', return_value=event):
        first = client.post('/api/fr9/webhooks/stripe', data=b'{}', headers={'Stripe-Signature': 'fixture'})
        duplicate = client.post('/api/fr9/webhooks/stripe', data=b'{}', headers={'Stripe-Signature': 'fixture'})
    assert first.status_code == duplicate.status_code == 200
    saved_personal = memory.retrieve('itineraries', 'personal-trip')
    assert saved_personal == {'id': 'personal-trip', **personal}
    package_trips = [
        item for key, item in memory.collections['itineraries'].items()
        if key != 'personal-trip'
    ]
    assert len(package_trips) == 1
    trip = package_trips[0]
    assert trip['tripType'] == 'package' and trip['packageTrip'] is True
    assert trip['travellerCount'] == 3 and trip['participants'] == snapshot['participants']
    assert trip['startDate'] == '2027-02-10' and trip['endDate'] == '2027-02-11'
    assert trip['packageSnapshot'] == snapshot
    assert trip['dailySchedule'][0]['activities'][0]['activityName'] == 'Heritage walk'
    assert trip['supplierReservationStatus'] == 'not_created'
    assert len(memory.collections['package_fulfillments']) == 1
    assert 'hotel_bookings' not in memory.collections and 'flight_bookings' not in memory.collections


def test_unverified_group_payment_cannot_create_package_trip(client, package_payment):
    memory, headers = package_payment
    seed_group_attempt(memory)
    with patch('modules.fr09_payment.routes.createCheckoutSession', return_value=session_response()):
        order = start_checkout(client, headers).get_json()['order']
    with patch(
        'modules.fr09_payment.routes.constructStripeWebhookEvent',
        return_value=_event(order, amount_total=1),
    ):
        response = client.post(
            '/api/fr9/webhooks/stripe', data=b'{}', headers={'Stripe-Signature': 'fixture'}
        )
    assert response.status_code == 200
    assert memory.retrieve('checkout_orders', order['id'])['status'] == 'payment_mismatch'
    assert not memory.collections.get('itineraries')


def test_paid_group_trip_creation_recovers_after_transient_persistence_failure(
        client, package_payment, monkeypatch):
    memory, headers = package_payment
    seed_group_attempt(memory)
    with patch('modules.fr09_payment.routes.createCheckoutSession', return_value=session_response()):
        order = start_checkout(client, headers).get_json()['order']
    original_claim = memory.claim
    failed = {'value': False}

    def fail_trip_once(collection, document_id, data):
        if collection == 'itineraries' and not failed['value']:
            failed['value'] = True
            raise RuntimeError('temporary persistence failure')
        return original_claim(collection, document_id, data)

    monkeypatch.setattr('modules.fr09_payment.routes.claimRecord', fail_trip_once)
    event = _event(order)
    with patch('modules.fr09_payment.routes.constructStripeWebhookEvent', return_value=event):
        response = client.post('/api/fr9/webhooks/stripe', data=b'{}', headers={'Stripe-Signature': 'fixture'})
    assert response.status_code == 200
    saved = memory.retrieve('checkout_orders', order['id'])
    assert saved['status'] == 'paid' and saved['fulfillmentStatus'] == 'fulfillment_pending'
    monkeypatch.setattr('modules.fr09_payment.routes.claimRecord', original_claim)
    with patch('modules.fr09_payment.routes.retrieveCheckoutSession', return_value=event['data']['object']):
        reconciled = client.get(f"/api/fr9/orders/{order['id']}/reconcile", headers=headers)
    assert reconciled.status_code == 200
    assert len(memory.collections['itineraries']) == 1
    assert memory.retrieve('checkout_orders', order['id'])['fulfillmentStatus'] == 'awaiting_operator_fulfillment'


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
