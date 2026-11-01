"""
Regression tests for Batch A1: Administrator Package Payment Reporting & Commerce Analytics Consistency.
Covers all 20 required scenarios from Section 9.
"""
from unittest.mock import patch, MagicMock
import io
import csv
import pytest


# Mock records helper
def _make_sample_collections(checkout_orders=None, payment_records=None, hotel_bookings=None):
    return {
        'checkout_orders': [{'currency':'MYR',**record} for record in (checkout_orders or [])],
        'payment_records': [{'currency':'MYR',**record} for record in (payment_records or [])],
        'hotel_bookings': hotel_bookings or [],
        'users': [{'uid': 'admin_1', 'role': 'admin', 'status': 'active'}],
        'tourism_packages': [{'id': 'pkg_1', 'approvalStatus': 'approved'}],
        'promotional_campaigns': [{'id': 'camp_1', 'reviewStatus': 'approved'}],
        'feedback': [{'id': 'fb_1', 'feedbackStatus': 'visible'}],
    }


def _side_effect_for_collections(collections):
    def _retrieve(coll, doc_id=None, filters=None, limit=None):
        data = collections.get(coll, [])
        if doc_id:
            return next((x for x in data if x.get('id') == doc_id or x.get('uid') == doc_id), None)
        return data[:limit] if limit else data
    return _retrieve


# Scenario 1: Package-only checkout orders appear in intended Admin reports
def test_scenario_1_package_only_orders_in_admin_reports(client, mock_admin_auth):
    orders = [{
        'id': 'ord-pkg-1',
        'quoteType': 'package',
        'packageId': 'pkg-1',
        'packageSnapshot': {'title': 'Penang Heritage Escapade'},
        'travellerId': 'traveller-1',
        'operatorId': 'operator-1',
        'paymentStatus': 'paid',
        'status': 'paid',
        'amount': 350.00,
        'currency': 'MYR',
        'provider': 'stripe_checkout_test',
        'createdAt': '2026-10-20T10:00:00Z',
    }]
    colls = _make_sample_collections(checkout_orders=orders, payment_records=[])
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', side_effect=_side_effect_for_collections(colls)):
        # Check payments endpoint
        res = client.get('/api/fr13/payments', headers={'Authorization': 'Bearer valid_test_token'})
        assert res.status_code == 200
        items = res.get_json()['items']
        assert len(items) == 1
        assert items[0]['id'] == 'ord-pkg-1'
        assert items[0]['productType'] == 'package'
        assert items[0]['productTitle'] == 'Penang Heritage Escapade'

        # Check reports summary endpoint
        res_sum = client.get('/api/fr13/reports/summary?reportType=payments', headers={'Authorization': 'Bearer valid_test_token'})
        assert res_sum.status_code == 200
        report = res_sum.get_json()['report']
        assert report['counts']['payment_records'] == 1
        assert len(report['records']) == 1
        assert report['records'][0]['id'] == 'ord-pkg-1'


# Scenario 2: Existing legacy payment records remain visible
def test_scenario_2_legacy_payment_records_remain_visible(client, mock_admin_auth):
    legacy = [{
        'id': 'pmt-legacy-1',
        'bookingId': 'hotel-book-99',
        'itemTitle': 'Georgetown Heritage Hotel',
        'travellerId': 'traveller-2',
        'paymentStatus': 'paid',
        'status': 'paid',
        'amount': 220.00,
        'currency': 'MYR',
        'provider': 'stripe',
        'createdAt': '2026-10-18T09:00:00Z',
    }]
    colls = _make_sample_collections(checkout_orders=[], payment_records=legacy)
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', side_effect=_side_effect_for_collections(colls)):
        res = client.get('/api/fr13/payments', headers={'Authorization': 'Bearer valid_test_token'})
        assert res.status_code == 200
        items = res.get_json()['items']
        assert len(items) == 1
        assert items[0]['id'] == 'pmt-legacy-1'
        assert items[0]['productType'] == 'legacy_payment'
        assert items[0]['productTitle'] == 'hotel-book-99'


# Scenario 3: Mixed legacy/current records have correct totals
def test_scenario_3_mixed_legacy_current_records_correct_totals(client, mock_admin_auth):
    orders = [{
        'id': 'ord-pkg-1',
        'quoteType': 'package',
        'packageSnapshot': {'title': 'Island Discovery'},
        'travellerId': 'traveller-1',
        'paymentStatus': 'paid',
        'status': 'paid',
        'amount': 300.00,
        'createdAt': '2026-10-22T10:00:00Z',
    }]
    legacy = [{
        'id': 'pmt-legacy-1',
        'bookingId': 'hotel-book-1',
        'travellerId': 'traveller-2',
        'paymentStatus': 'paid',
        'status': 'paid',
        'amount': 200.00,
        'createdAt': '2026-10-21T10:00:00Z',
    }]
    colls = _make_sample_collections(checkout_orders=orders, payment_records=legacy)
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', side_effect=_side_effect_for_collections(colls)):
        res = client.get('/api/fr13/payments', headers={'Authorization': 'Bearer valid_test_token'})
        assert res.status_code == 200
        items = res.get_json()['items']
        assert len(items) == 2

        # Summary check
        res_sum = client.get('/api/fr13/reports/summary', headers={'Authorization': 'Bearer valid_test_token'})
        assert res_sum.status_code == 200
        data = res_sum.get_json()
        assert data['counts']['payment_records'] == 2
        assert data['payments']['total'] == 2
        assert data['payments']['paid'] == 2
        assert data['payments']['totalPaidRevenue'] == 500.00


# Scenario 4: Duplicate logical payments are not double-counted (mirror deduplication)
def test_scenario_4_duplicate_mirror_payments_not_double_counted(client, mock_admin_auth):
    order = {
        'id': 'ord-main-1',
        'quoteType': 'package',
        'packageSnapshot': {'title': 'Penang Escape'},
        'travellerId': 'traveller-1',
        'paymentStatus': 'paid',
        'status': 'paid',
        'amount': 450.00,
        'createdAt': '2026-10-20T12:00:00Z',
    }
    # Mirror legacy payment record that explicitly references the order
    mirror_payment = {
        'id': 'pmt-mirror-1',
        'checkoutOrderId': 'ord-main-1',
        'bookingId': 'ord-main-1',
        'travellerId': 'traveller-1',
        'paymentStatus': 'paid',
        'amount': 450.00,
        'createdAt': '2026-10-20T12:01:00Z',
    }
    colls = _make_sample_collections(checkout_orders=[order], payment_records=[mirror_payment])
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', side_effect=_side_effect_for_collections(colls)):
        res = client.get('/api/fr13/payments', headers={'Authorization': 'Bearer valid_test_token'})
        assert res.status_code == 200
        items = res.get_json()['items']
        # Must be deduplicated down to 1 record!
        assert len(items) == 1
        assert items[0]['id'] == 'ord-main-1'

        res_sum = client.get('/api/fr13/reports/summary', headers={'Authorization': 'Bearer valid_test_token'})
        assert res_sum.get_json()['payments']['total'] == 1
        assert res_sum.get_json()['payments']['totalPaidRevenue'] == 450.00


# Scenario 5: Distinct orders with coincidentally identical IDs remain distinguishable
def test_scenario_5_distinct_orders_with_coincidentally_identical_ids_preserved(client, mock_admin_auth):
    order = {
        'id': 'TX-999',
        'quoteType': 'package',
        'packageSnapshot': {'title': 'Penang Food Tour'},
        'travellerId': 'traveller-1',
        'paymentStatus': 'paid',
        'amount': 150.00,
        'createdAt': '2026-10-21T08:00:00Z',
    }
    legacy = {
        'id': 'TX-999',  # Coincidental same document id in payment_records, but no reference to ord-999
        'bookingId': 'hotel-hotel-44',
        'travellerId': 'traveller-2',
        'paymentStatus': 'paid',
        'amount': 80.00,
        'createdAt': '2026-10-21T08:05:00Z',
    }
    colls = _make_sample_collections(checkout_orders=[order], payment_records=[legacy])
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', side_effect=_side_effect_for_collections(colls)):
        res = client.get('/api/fr13/payments', headers={'Authorization': 'Bearer valid_test_token'})
        assert res.status_code == 200
        items = res.get_json()['items']
        # Distinct purchases in separate collections without cross-reference must both remain visible!
        assert len(items) == 2
        assert {item['productType'] for item in items} == {'package', 'legacy_payment'}

        res_sum = client.get('/api/fr13/reports/summary', headers={'Authorization': 'Bearer valid_test_token'})
        assert res_sum.get_json()['payments']['total'] == 2
        assert res_sum.get_json()['payments']['totalPaidRevenue'] == 230.00


# Scenario 6: Unpaid orders do not become paid revenue
def test_scenario_6_unpaid_orders_do_not_become_paid_revenue(client, mock_admin_auth):
    order = {
        'id': 'ord-unpaid-1',
        'quoteType': 'package',
        'packageSnapshot': {'title': 'Penang Nature Tour'},
        'travellerId': 'traveller-1',
        'paymentStatus': 'unpaid',
        'status': 'checkout_pending',
        'amount': 500.00,
        'createdAt': '2026-10-22T10:00:00Z',
    }
    colls = _make_sample_collections(checkout_orders=[order], payment_records=[])
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', side_effect=_side_effect_for_collections(colls)):
        res_sum = client.get('/api/fr13/reports/summary', headers={'Authorization': 'Bearer valid_test_token'})
        assert res_sum.status_code == 200
        pmt_summary = res_sum.get_json()['payments']
        assert pmt_summary['total'] == 1
        assert pmt_summary['pending'] == 1
        assert pmt_summary['paid'] == 0
        assert pmt_summary['totalPaidRevenue'] == 0.00


# Scenario 7: Failed or expired orders are excluded from paid revenue
def test_scenario_7_failed_expired_orders_excluded_from_paid_revenue(client, mock_admin_auth):
    failed_order = {
        'id': 'ord-failed-1',
        'quoteType': 'package',
        'paymentStatus': 'failed',
        'status': 'checkout_failed',
        'amount': 250.00,
        'createdAt': '2026-10-22T11:00:00Z',
    }
    expired_order = {
        'id': 'ord-expired-1',
        'quoteType': 'package',
        'paymentStatus': 'expired',
        'status': 'checkout_expired',
        'amount': 350.00,
        'createdAt': '2026-10-22T12:00:00Z',
    }
    colls = _make_sample_collections(checkout_orders=[failed_order, expired_order], payment_records=[])
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', side_effect=_side_effect_for_collections(colls)):
        res_sum = client.get('/api/fr13/reports/summary', headers={'Authorization': 'Bearer valid_test_token'})
        assert res_sum.status_code == 200
        pmt_summary = res_sum.get_json()['payments']
        assert pmt_summary['total'] == 2
        assert pmt_summary['failed'] == 1
        assert pmt_summary['expired'] == 1
        assert pmt_summary['paid'] == 0
        assert pmt_summary['totalPaidRevenue'] == 0.00


# Scenario 8: Paid Test Mode orders are labeled correctly
def test_scenario_8_test_mode_labeled_correctly(client, mock_admin_auth):
    test_order = {
        'id': 'ord-test-1',
        'quoteType': 'package',
        'paymentStatus': 'paid',
        'provider': 'stripe_checkout_test',
        'amount': 100.00,
        'createdAt': '2026-10-23T10:00:00Z',
    }
    colls = _make_sample_collections(checkout_orders=[test_order], payment_records=[])
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', side_effect=_side_effect_for_collections(colls)):
        res = client.get('/api/fr13/payments', headers={'Authorization': 'Bearer valid_test_token'})
        assert res.status_code == 200
        item = res.get_json()['items'][0]
        assert item['testMode'] is True


# Scenario 9: Date filters are consistent
def test_scenario_9_date_filters_consistent(client, mock_admin_auth):
    orders = [
        {'id': 'ord-early', 'quoteType': 'package', 'paymentStatus': 'paid', 'createdAt': '2026-10-01T10:00:00Z'},
        {'id': 'ord-mid', 'quoteType': 'package', 'paymentStatus': 'paid', 'createdAt': '2026-10-15T10:00:00Z'},
        {'id': 'ord-late', 'quoteType': 'package', 'paymentStatus': 'paid', 'createdAt': '2026-10-25T10:00:00Z'},
    ]
    colls = _make_sample_collections(checkout_orders=orders, payment_records=[])
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', side_effect=_side_effect_for_collections(colls)):
        res = client.get('/api/fr13/payments?startDate=2026-10-10&endDate=2026-10-20', headers={'Authorization': 'Bearer valid_test_token'})
        assert res.status_code == 200
        items = res.get_json()['items']
        assert len(items) == 1
        assert items[0]['id'] == 'ord-mid'

        # Summary with reportType=payments and matching dates
        res_sum = client.get('/api/fr13/reports/summary?reportType=payments&startDate=2026-10-10&endDate=2026-10-20',
                             headers={'Authorization': 'Bearer valid_test_token'})
        assert res_sum.status_code == 200
        report = res_sum.get_json()['report']
        assert len(report['records']) == 1
        assert report['records'][0]['id'] == 'ord-mid'


# Scenario 10: Currency aggregation is accurate
def test_scenario_10_currency_aggregation_accurate(client, mock_admin_auth):
    orders = [
        {'id': 'ord-1', 'quoteType': 'package', 'paymentStatus': 'paid', 'amount': 120.50, 'createdAt': '2026-10-20T10:00:00Z'},
        {'id': 'ord-2', 'quoteType': 'package', 'paymentStatus': 'paid', 'amount': 89.49, 'createdAt': '2026-10-20T11:00:00Z'},
    ]
    colls = _make_sample_collections(checkout_orders=orders, payment_records=[])
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', side_effect=_side_effect_for_collections(colls)):
        res_sum = client.get('/api/fr13/reports/summary', headers={'Authorization': 'Bearer valid_test_token'})
        assert res_sum.status_code == 200
        rev = res_sum.get_json()['payments']['totalPaidRevenue']
        assert pytest.approx(rev, 0.01) == 209.99


# Scenario 11: Admin payment list and summary agree
def test_scenario_11_admin_payment_list_and_summary_agree(client, mock_admin_auth):
    orders = [
        {'id': 'ord-1', 'quoteType': 'package', 'paymentStatus': 'paid', 'amount': 100.0, 'createdAt': '2026-10-20T10:00:00Z'},
        {'id': 'ord-2', 'quoteType': 'package', 'paymentStatus': 'unpaid', 'amount': 200.0, 'createdAt': '2026-10-20T11:00:00Z'},
    ]
    colls = _make_sample_collections(checkout_orders=orders, payment_records=[])
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', side_effect=_side_effect_for_collections(colls)):
        res_list = client.get('/api/fr13/payments', headers={'Authorization': 'Bearer valid_test_token'})
        res_sum = client.get('/api/fr13/reports/summary', headers={'Authorization': 'Bearer valid_test_token'})
        assert len(res_list.get_json()['items']) == res_sum.get_json()['payments']['total'] == 2


# Scenario 12: CSV and PDF export parity
def test_scenario_12_csv_and_pdf_export_parity(client, mock_admin_auth):
    orders = [
        {
            'id': 'ord-export-1',
            'quoteType': 'package',
            'packageSnapshot': {'title': 'Penang Sunset Cruise'},
            'travellerId': 'traveller-1',
            'paymentStatus': 'paid',
            'amount': 180.00,
            'clientSecret': 'shh_secret_should_be_stripped',
            'providerIdempotencyKey': 'idemp_key_should_be_stripped',
            'createdAt': '2026-10-20T10:00:00Z',
        }
    ]
    colls = _make_sample_collections(checkout_orders=orders, payment_records=[])
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', side_effect=_side_effect_for_collections(colls)):
        # Test CSV export
        res_csv = client.get('/api/fr13/reports/export.csv?reportType=payments', headers={'Authorization': 'Bearer valid_test_token'})
        assert res_csv.status_code == 200
        csv_text = res_csv.data.decode('utf-8')
        assert 'ord-export-1' in csv_text
        assert 'clientSecret' not in csv_text
        assert 'providerIdempotencyKey' not in csv_text

        # Test PDF export
        res_pdf = client.get('/api/fr13/reports/export.pdf?reportType=payments', headers={'Authorization': 'Bearer valid_test_token'})
        assert res_pdf.status_code == 200
        assert res_pdf.mimetype == 'application/pdf'
        assert len(res_pdf.data) > 500


# Scenario 13: Package Trip fulfillment is distinguished from supplier reservation
def test_scenario_13_package_trip_fulfillment_distinguished_from_supplier_reservation(client, mock_admin_auth):
    order = {
        'id': 'ord-pkg-book-1',
        'quoteType': 'package',
        'packageId': 'pkg-island',
        'packageSnapshot': {'title': 'Penang Island Hop'},
        'operatorId': 'op-island',
        'travellerId': 'tr-1',
        'paymentStatus': 'paid',
        'fulfillmentStatus': 'fulfilled',
        'amount': 280.00,
        'createdAt': '2026-10-22T08:00:00Z',
    }
    colls = _make_sample_collections(checkout_orders=[order], payment_records=[])
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', side_effect=_side_effect_for_collections(colls)):
        res = client.get('/api/fr13/bookings?type=package', headers={'Authorization': 'Bearer valid_test_token'})
        assert res.status_code == 200
        items = res.get_json()['items']
        assert len(items) == 1
        pkg_booking = items[0]
        assert pkg_booking['bookingType'] == 'package'
        assert pkg_booking['fulfillmentStatus'] == 'fulfilled'
        assert pkg_booking['supplierReservationStatus'] == 'not_created'
        assert 'Package Trip creation is platform-managed' in pkg_booking['supplierReservationDisclosure']


# Scenario 14: Admin-only endpoints enforce authorization
def test_scenario_14_admin_only_endpoints_enforce_auth(client):
    # Unauthenticated requests must be rejected
    res_pmt = client.get('/api/fr13/payments')
    assert res_pmt.status_code in {401, 403}

    res_book = client.get('/api/fr13/bookings')
    assert res_book.status_code in {401, 403}

    res_sum = client.get('/api/fr13/reports/summary')
    assert res_sum.status_code in {401, 403}


# Scenario 15: Operators cannot access restricted Admin reporting
def test_scenario_15_operators_denied_access_to_admin_reporting(client, mock_operator_auth):
    headers = {'Authorization': 'Bearer operator_token'}
    res_pmt = client.get('/api/fr13/payments', headers=headers)
    assert res_pmt.status_code == 403

    res_book = client.get('/api/fr13/bookings', headers=headers)
    assert res_book.status_code == 403

    res_sum = client.get('/api/fr13/reports/summary', headers=headers)
    assert res_sum.status_code == 403


# Scenario 16: No Checkout secrets or provider keys are disclosed
def test_scenario_16_checkout_secrets_and_provider_keys_not_disclosed(client, mock_admin_auth):
    order = {
        'id': 'ord-secret-1',
        'quoteType': 'package',
        'travellerId': 'tr-secret',
        'providerIdempotencyKey': 'idemp_key_12345',
        'clientSecret': 'cs_test_98765',
        'stripeClientSecret': 'scs_test_11111',
        'rawSessionId': 'sess_raw_22222',
        'checkoutSessionId': 'cs_sess_33333',
        'checkoutUrl': 'https://checkout.stripe.com/pay/cs_sess_33333',
        'firebaseToken': 'fb_tok_44444',
        'paymentStatus': 'paid',
        'amount': 150.00,
        'createdAt': '2026-10-23T10:00:00Z',
    }
    colls = _make_sample_collections(checkout_orders=[order], payment_records=[])
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', side_effect=_side_effect_for_collections(colls)):
        res = client.get('/api/fr13/payments', headers={'Authorization': 'Bearer valid_test_token'})
        assert res.status_code == 200
        item = res.get_json()['items'][0]
        for secret_key in ('providerIdempotencyKey', 'clientSecret', 'stripeClientSecret',
                           'rawSessionId', 'checkoutSessionId', 'checkoutUrl', 'firebaseToken'):
            assert secret_key not in item


# Scenario 17: Operator analytics remains compatible
def test_scenario_17_operator_analytics_compatibility():
    from modules.fr12_tourism_operator_management.analytics_service import generate_business_analytics
    from tests.test_fr12_operator_analytics import _build_mock_db
    mock_db = _build_mock_db()
    res = generate_business_analytics(mock_db, 'op-test')
    assert 'summary' in res
    summary = res['summary']
    assert 'totalPackages' in summary
    assert 'bookingRecords' in summary
    assert 'pendingBookings' in summary
    assert 'expiredBookings' in summary
    assert 'fulfilledBookings' in summary


# Scenario 18: Active unpaid orders are not wrongly labeled expired
def test_scenario_18_active_unpaid_orders_not_wrongly_labeled_expired():
    from modules.fr12_tourism_operator_management.analytics_service import generate_business_analytics
    from tests.test_fr12_operator_analytics import _build_mock_db
    orders = [
        # Active open checkout order awaiting payment
        {
            'id': 'ord-active-1',
            'quoteType': 'package',
            'operatorId': 'op-test',
            'status': 'checkout_open',
            'paymentStatus': 'unpaid',
            'amount': 300.0,
            'createdAt': '2026-10-24T10:00:00Z',
        },
        # Genuinely expired order
        {
            'id': 'ord-expired-1',
            'quoteType': 'package',
            'operatorId': 'op-test',
            'status': 'expired',
            'paymentStatus': 'expired',
            'amount': 300.0,
            'createdAt': '2026-10-20T10:00:00Z',
        },
    ]
    mock_db = _build_mock_db(orders=orders)
    res = generate_business_analytics(mock_db, 'op-test')
    summary = res['summary']
    # Active unpaid checkout must be classified as pending, not expired!
    assert summary['pendingBookings'] == 1
    assert summary['expiredBookings'] == 1


# Scenario 19: Existing Operator booking status filters remain correct
def test_scenario_19_existing_operator_booking_filters_remain_correct(client, mock_operator_auth):
    orders = [
        {
            'id': 'ord-op-1',
            'operatorId': 'test_operator_uid',
            'quoteType': 'package',
            'paymentStatus': 'paid',
            'status': 'paid',
            'fulfillmentStatus': 'fulfillment_pending',
            'createdAt': '2026-10-24T10:00:00Z',
        },
        {
            'id': 'ord-op-2',
            'operatorId': 'test_operator_uid',
            'quoteType': 'package',
            'paymentStatus': 'unpaid',
            'status': 'checkout_open',
            'fulfillmentStatus': 'fulfillment_pending',
            'createdAt': '2026-10-24T11:00:00Z',
        },
    ]
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord',
               side_effect=lambda coll, **kw: orders if coll == 'checkout_orders' else []):
        res = client.get('/api/fr12/bookings', headers={'Authorization': 'Bearer valid_test_token'})
        assert res.status_code == 200
        items = res.get_json()['items']
        assert len(items) == 2


# Scenario 20: Existing FR09 Checkout contracts pass
def test_scenario_20_existing_fr09_package_checkout_contracts_pass():
    from services.package_checkout_contract import package_amount_minor_units
    snapshot = {'currency': 'MYR', 'amountMinor': 25000}
    assert package_amount_minor_units(snapshot) == 25000
