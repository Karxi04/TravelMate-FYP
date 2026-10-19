from unittest.mock import patch


AUTH = {'Authorization': 'Bearer valid_test_token'}
OWNER = 'test_traveller_uid'


def _history_store(legacy=None, orders=None):
    legacy = list(legacy or [])
    orders = list(orders or [])

    def retrieve(collection, document_id=None, filters=None):
        assert document_id is None
        assert filters == [('travellerId', '==', OWNER)]
        if collection == 'payment_records':
            return legacy
        if collection == 'checkout_orders':
            return orders
        raise AssertionError(f'Unexpected collection: {collection}')

    return retrieve


def test_history_merges_paid_checkout_types_and_legacy_records(
    client, mock_traveller_auth
):
    legacy = {
        'id': 'legacy-payment',
        'travellerId': OWNER,
        'bookingId': 'legacy-booking',
        'amount': 80,
        'currency': 'myr',
        'paymentStatus': 'successful',
        'transactionReference': 'pi_sim_private_reference',
        'cardBrand': 'Visa',
        'cardLast4': '4242',
        'billingEmail': 'private@example.test',
        'providerIdempotencyKey': 'never-return-this',
        'updatedAt': '2026-09-01T10:00:00+00:00',
    }
    orders = [
        {
            'id': 'package-order',
            'travellerId': OWNER,
            'quoteType': 'package',
            'amount': 1075.50,
            'currency': 'MYR',
            'paymentStatus': 'paid',
            'status': 'paid',
            'provider': 'stripe_checkout_test',
            'packageSnapshot': {'title': 'Penang Weekend'},
            'fulfilledTripId': 'package-trip',
            'checkoutSessionId': 'cs_test_private',
            'stripePaymentIntentId': 'pi_private',
            'updatedAt': '2026-10-03T10:00:00+00:00',
        },
        {
            'id': 'flight-order',
            'travellerId': OWNER,
            'quoteType': 'flight',
            'amount': 320,
            'currency': 'MYR',
            'paymentStatus': 'paid',
            'status': 'paid',
            'provider': 'stripe_checkout_test',
            'updatedAt': '2026-10-02T10:00:00+00:00',
        },
        {
            'id': 'hotel-order',
            'travellerId': OWNER,
            'quoteType': 'hotel',
            'amount': 240,
            'currency': 'MYR',
            'paymentStatus': 'unpaid',
            'status': 'checkout_open',
            'provider': 'stripe_checkout_test',
            'quoteSnapshot': {'name': 'Heritage Hotel'},
            'updatedAt': '2026-10-01T10:00:00+00:00',
        },
    ]
    with patch(
        'modules.fr09_payment.routes.retrieveRecord',
        side_effect=_history_store([legacy], orders),
    ):
        response = client.get('/api/fr9/payments', headers=AUTH)

    assert response.status_code == 200
    items = response.get_json()['items']
    assert [item['orderReference'] for item in items] == [
        'package-order', 'flight-order', 'hotel-order', 'legacy-payment'
    ]
    package, flight, hotel, old = items
    assert package == {
        'id': 'package-order',
        'orderReference': 'package-order',
        'bookingType': 'package',
        'timestamp': '2026-10-03T10:00:00+00:00',
        'amount': 1075.50,
        'currency': 'MYR',
        'paymentStatus': 'paid',
        'orderStatus': 'paid',
        'testMode': True,
        'paymentProvider': 'stripe',
        'relatedTripId': 'package-trip',
        'relatedBookingId': None,
        'productTitle': 'Penang Weekend',
        'source': 'checkout_order',
            'checkoutAction': 'view_booking',
    }
    assert flight['bookingType'] == 'flight'
    assert flight['productTitle'] is None
    assert hotel['bookingType'] == 'hotel'
    assert hotel['paymentStatus'] == 'unpaid'
    assert hotel['orderStatus'] == 'checkout_open'
    assert hotel['productTitle'] == 'Heritage Hotel'
    assert old['paymentStatus'] == 'succeeded'
    assert old['testMode'] is True
    assert old['paymentProvider'] == 'travelmate_simulation'
    assert old['relatedBookingId'] == 'legacy-booking'
    assert old['cardBrand'] == 'Visa' and old['cardLast4'] == '4242'
    serialized = response.get_data(as_text=True)
    for secret in (
        'private@example.test', 'never-return-this', 'cs_test_private',
        'pi_private', 'pi_sim_private_reference',
    ):
        assert secret not in serialized


def test_history_represents_pending_failed_and_missing_legacy_fields(
    client, mock_traveller_auth
):
    legacy = [{
        'id': 'minimal-legacy',
        'travellerId': OWNER,
        'paymentStatus': 'failed',
        'createdAt': '2026-08-01T00:00:00+00:00',
    }]
    orders = [
        {
            'id': 'pending-order',
            'travellerId': OWNER,
            'quoteType': 'package',
            'paymentStatus': 'unpaid',
            'status': 'payment_pending',
            'createdAt': '2026-08-03T00:00:00+00:00',
        },
        {
            'id': 'legacy-paid-order',
            'travellerId': OWNER,
            'quoteType': 'package',
            'status': 'paid',
            'createdAt': '2026-08-02T00:00:00+00:00',
        },
    ]
    with patch(
        'modules.fr09_payment.routes.retrieveRecord',
        side_effect=_history_store(legacy, orders),
    ):
        response = client.get('/api/fr9/payments', headers=AUTH)

    assert response.status_code == 200
    pending, legacy_paid, failed = response.get_json()['items']
    assert pending['paymentStatus'] == 'unpaid'
    assert pending['orderStatus'] == 'payment_pending'
    assert pending['amount'] is None and pending['currency'] is None
    assert legacy_paid['paymentStatus'] == 'paid'
    assert legacy_paid['orderStatus'] == 'paid'
    assert failed['paymentStatus'] == 'failed'
    assert failed['bookingType'] == 'legacy_payment'
    assert failed['productTitle'] is None and failed['testMode'] is None


def test_history_empty_result(client, mock_traveller_auth):
    with patch(
        'modules.fr09_payment.routes.retrieveRecord',
        side_effect=_history_store(),
    ):
        response = client.get('/api/fr9/payments', headers=AUTH)
    assert response.status_code == 200
    assert response.get_json() == {'ok': True, 'items': []}


def test_history_enforces_owner_ignores_query_uid_and_deduplicates_source_records(
    client, mock_traveller_auth
):
    owned = {
        'id': 'owned-order', 'travellerId': OWNER, 'quoteType': 'package',
        'status': 'paid', 'paymentStatus': 'paid',
    }
    records = [
        owned,
        dict(owned),
        {'id': 'foreign', 'travellerId': 'other-user', 'status': 'paid'},
        {'id': 'missing-owner', 'status': 'paid'},
    ]
    duplicate_legacy = {
        'id': 'owned-order', 'travellerId': OWNER, 'paymentStatus': 'succeeded',
    }
    with patch(
        'modules.fr09_payment.routes.retrieveRecord',
        side_effect=_history_store(legacy=[duplicate_legacy], orders=records),
    ):
        response = client.get(
            '/api/fr9/payments?travellerId=other-user', headers=AUTH
        )

    assert response.status_code == 200
    items = response.get_json()['items']
    assert [item['id'] for item in items] == ['owned-order']


def test_history_rejects_unauthenticated_request(client):
    response = client.get('/api/fr9/payments')
    assert response.status_code == 401


def test_history_rejects_operator_role(client, mock_operator_auth):
    response = client.get('/api/fr9/payments', headers=AUTH)
    assert response.status_code == 403


def test_history_rejects_admin_role(client, mock_admin_auth):
    response = client.get('/api/fr9/payments', headers=AUTH)
    assert response.status_code == 403


def test_history_restart_read_is_repeatable_and_has_no_side_effects(
    client, mock_traveller_auth
):
    order = {
        'id': 'recoverable-order',
        'travellerId': OWNER,
        'quoteType': 'package',
        'status': 'paid',
        'paymentStatus': 'paid',
        'amount': 450,
        'currency': 'MYR',
        'updatedAt': '2026-10-04T00:00:00+00:00',
    }
    with patch(
        'modules.fr09_payment.routes.retrieveRecord',
        side_effect=_history_store(orders=[order]),
    ), patch('modules.fr09_payment.routes.updateRecord') as update, patch(
        'modules.fr09_payment.routes.claimRecord'
    ) as claim, patch(
        'modules.fr09_payment.routes.retrieveCheckoutSession'
    ) as provider:
        first = client.get('/api/fr9/payments', headers=AUTH)
        second = client.get('/api/fr9/payments', headers=AUTH)

    assert first.status_code == 200 and second.status_code == 200
    assert first.get_json() == second.get_json()
    update.assert_not_called()
    claim.assert_not_called()
    provider.assert_not_called()
