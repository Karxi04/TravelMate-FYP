import pytest
from unittest.mock import patch, MagicMock
from modules.fr12_tourism_operator_management.analytics_service import generate_business_analytics


def _make_mock_doc(doc_id, data):
    doc = MagicMock()
    doc.id = doc_id
    doc.to_dict.return_value = dict(data)
    return doc


def _build_mock_db(packages=None, campaigns=None, orders=None):
    mock_db = MagicMock()

    pkg_docs = [_make_mock_doc(p.get("id", f"pkg_{i}"), p) for i, p in enumerate(packages or [])]
    camp_docs = [_make_mock_doc(c.get("id", f"camp_{i}"), c) for i, c in enumerate(campaigns or [])]
    order_docs = [_make_mock_doc(o.get("id", f"ord_{i}"), o) for i, o in enumerate(orders or [])]

    def mock_collection(name):
        coll_mock = MagicMock()
        if name == "tourism_packages":
            def where_pkg(field, op, val):
                w_mock = MagicMock()
                filtered = [d for d in pkg_docs if d.to_dict().get(field) == val]
                w_mock.stream.return_value = filtered
                return w_mock
            coll_mock.where.side_effect = where_pkg
            coll_mock.stream.return_value = pkg_docs
        elif name == "promotional_campaigns":
            def where_camp(field, op, val):
                w_mock = MagicMock()
                filtered = [d for d in camp_docs if d.to_dict().get(field) == val]
                w_mock.stream.return_value = filtered
                return w_mock
            coll_mock.where.side_effect = where_camp
            coll_mock.stream.return_value = camp_docs
        elif name == "checkout_orders":
            def where_orders(field, op, val):
                w_mock = MagicMock()
                filtered = [d for d in order_docs if d.to_dict().get(field) == val]
                w_mock.stream.return_value = filtered
                return w_mock
            coll_mock.where.side_effect = where_orders
            coll_mock.stream.return_value = order_docs
        else:
            coll_mock.stream.return_value = []
            coll_mock.where.return_value.stream.return_value = []
        return coll_mock

    mock_db.collection.side_effect = mock_collection
    return mock_db


# ==============================================================================
# UNIT TESTS: generate_business_analytics
# ==============================================================================

def test_analytics_empty_orders():
    """Empty checkout_orders returns 0 bookings and 0.0 totalPaidRevenue."""
    db = _build_mock_db(orders=[])
    report = generate_business_analytics(db, operator_id="op_1")

    assert report["summary"]["bookingRecords"] == 0
    assert report["summary"]["paidBookings"] == 0
    assert report["summary"]["expiredBookings"] == 0
    assert report["summary"]["totalPaidRevenue"] == 0.0
    assert report["bookingCount"] == 0
    assert report["paidBookingCount"] == 0
    assert report["bookings"] == []


def test_analytics_one_paid_order():
    """Single paid package order calculates correct metrics."""
    orders = [{
        "id": "ord_1",
        "quoteType": "package",
        "operatorId": "op_1",
        "amount": 899.0,
        "currency": "MYR",
        "status": "paid",
        "paymentStatus": "paid",
        "provider": "stripe_checkout_test",
    }]
    db = _build_mock_db(orders=orders)
    report = generate_business_analytics(db, operator_id="op_1")

    assert report["summary"]["bookingRecords"] == 1
    assert report["summary"]["paidBookings"] == 1
    assert report["summary"]["expiredBookings"] == 0
    assert report["summary"]["totalPaidRevenue"] == 899.0
    assert report["summary"]["testModeOrders"] == 1
    assert len(report["bookings"]) == 1
    assert report["bookings"][0]["id"] == "ord_1"


def test_analytics_multiple_paid_orders():
    """Multiple paid package orders correctly sum totalPaidRevenue without double counting."""
    orders = [
        {"id": "ord_1", "quoteType": "package", "operatorId": "op_1", "amount": 1000.0, "status": "paid", "paymentStatus": "paid"},
        {"id": "ord_2", "quoteType": "package", "operatorId": "op_1", "amount": 2500.50, "status": "paid", "paymentStatus": "paid"},
    ]
    db = _build_mock_db(orders=orders)
    report = generate_business_analytics(db, operator_id="op_1")

    assert report["summary"]["bookingRecords"] == 2
    assert report["summary"]["paidBookings"] == 2
    assert report["summary"]["totalPaidRevenue"] == 3500.50


def test_analytics_expired_and_unpaid_excluded_from_revenue():
    """Expired and unpaid checkout orders count as booking records but never add to paid revenue."""
    orders = [
        {"id": "ord_exp", "quoteType": "package", "operatorId": "op_1", "amount": 899.0, "status": "expired", "paymentStatus": "unpaid"},
        {"id": "ord_open", "quoteType": "package", "operatorId": "op_1", "amount": 1200.0, "status": "checkout_open", "paymentStatus": "unpaid"},
    ]
    db = _build_mock_db(orders=orders)
    report = generate_business_analytics(db, operator_id="op_1")

    assert report["summary"]["bookingRecords"] == 2
    assert report["summary"]["paidBookings"] == 0
    assert report["summary"]["expiredBookings"] == 1
    assert report["summary"]["pendingBookings"] == 1
    assert report["summary"]["totalPaidRevenue"] == 0.0


def test_analytics_cancelled_and_failed_orders_excluded():
    """Cancelled or failed orders are excluded from paid revenue."""
    orders = [
        {"id": "ord_canc", "quoteType": "package", "operatorId": "op_1", "amount": 500.0, "status": "cancelled", "paymentStatus": "paid"},
        {"id": "ord_fail", "quoteType": "package", "operatorId": "op_1", "amount": 600.0, "status": "failed", "paymentStatus": "failed"},
    ]
    db = _build_mock_db(orders=orders)
    report = generate_business_analytics(db, operator_id="op_1")

    assert report["summary"]["bookingRecords"] == 2
    assert report["summary"]["paidBookings"] == 0
    assert report["summary"]["totalPaidRevenue"] == 0.0


def test_analytics_mixture_paid_and_expired():
    """Mixture of paid and expired orders calculates correct counts and financial totals."""
    orders = [
        {"id": "ord_p1", "quoteType": "package", "operatorId": "op_1", "amount": 1200.0, "status": "paid", "paymentStatus": "paid"},
        {"id": "ord_p2", "quoteType": "package", "operatorId": "op_1", "amount": 800.0, "status": "paid", "paymentStatus": "paid"},
        {"id": "ord_e1", "quoteType": "package", "operatorId": "op_1", "amount": 800.0, "status": "expired", "paymentStatus": "unpaid"},
    ]
    db = _build_mock_db(orders=orders)
    report = generate_business_analytics(db, operator_id="op_1")

    assert report["summary"]["bookingRecords"] == 3
    assert report["summary"]["paidBookings"] == 2
    assert report["summary"]["expiredBookings"] == 1
    assert report["summary"]["totalPaidRevenue"] == 2000.0


def test_analytics_excludes_hotel_and_flight_orders():
    """Hotel bookings and flight checkouts are strictly excluded from package analytics."""
    orders = [
        {"id": "ord_hotel", "quoteType": "hotel", "operatorId": "op_1", "amount": 250.0, "status": "paid", "paymentStatus": "paid"},
        {"id": "ord_flight", "quoteType": "flight", "operatorId": "op_1", "amount": 401.0, "status": "paid", "paymentStatus": "paid"},
        {"id": "ord_pkg", "quoteType": "package", "operatorId": "op_1", "amount": 999.0, "status": "paid", "paymentStatus": "paid"},
    ]
    db = _build_mock_db(orders=orders)
    report = generate_business_analytics(db, operator_id="op_1")

    assert report["summary"]["bookingRecords"] == 1
    assert report["summary"]["paidBookings"] == 1
    assert report["summary"]["totalPaidRevenue"] == 999.0
    assert [b["id"] for b in report["bookings"]] == ["ord_pkg"]


def test_analytics_cross_operator_isolation():
    """Operator A must never see Operator B's package orders or revenue, and vice versa."""
    orders = [
        {"id": "ord_a1", "quoteType": "package", "operatorId": "op_A", "amount": 500.0, "status": "paid", "paymentStatus": "paid"},
        {"id": "ord_a2", "quoteType": "package", "operatorId": "op_A", "amount": 300.0, "status": "paid", "paymentStatus": "paid"},
        {"id": "ord_b1", "quoteType": "package", "operatorId": "op_B", "amount": 1500.0, "status": "paid", "paymentStatus": "paid"},
    ]
    db = _build_mock_db(orders=orders)

    report_a = generate_business_analytics(db, operator_id="op_A")
    assert report_a["summary"]["bookingRecords"] == 2
    assert report_a["summary"]["paidBookings"] == 2
    assert report_a["summary"]["totalPaidRevenue"] == 800.0
    assert [b["id"] for b in report_a["bookings"]] == ["ord_a1", "ord_a2"]

    report_b = generate_business_analytics(db, operator_id="op_B")
    assert report_b["summary"]["bookingRecords"] == 1
    assert report_b["summary"]["paidBookings"] == 1
    assert report_b["summary"]["totalPaidRevenue"] == 1500.0
    assert [b["id"] for b in report_b["bookings"]] == ["ord_b1"]


def test_analytics_strips_sensitive_payment_tokens():
    """Sensitive provider tokens like paymentIntent or clientSecret must not leak in report."""
    orders = [{
        "id": "ord_sec",
        "quoteType": "package",
        "operatorId": "op_1",
        "amount": 500.0,
        "status": "paid",
        "paymentStatus": "paid",
        "stripePaymentIntentId": "pi_live_secret_123",
        "stripeSessionId": "cs_live_secret_456",
        "clientSecret": "secret_token_789",
    }]
    db = _build_mock_db(orders=orders)
    report = generate_business_analytics(db, operator_id="op_1")

    assert len(report["bookings"]) == 1
    booking = report["bookings"][0]
    assert "stripePaymentIntentId" not in booking
    assert "stripeSessionId" not in booking
    assert "clientSecret" not in booking
    assert booking["id"] == "ord_sec"


def test_analytics_missing_and_malformed_amounts():
    """Missing, None, or string amounts are safely handled without exception."""
    orders = [
        {"id": "ord_1", "quoteType": "package", "operatorId": "op_1", "amount": None, "status": "paid", "paymentStatus": "paid"},
        {"id": "ord_2", "quoteType": "package", "operatorId": "op_1", "amount": "invalid", "status": "paid", "paymentStatus": "paid"},
        {"id": "ord_3", "quoteType": "package", "operatorId": "op_1", "amount": "500.50", "status": "paid", "paymentStatus": "paid"},
    ]
    db = _build_mock_db(orders=orders)
    report = generate_business_analytics(db, operator_id="op_1")

    assert report["summary"]["bookingRecords"] == 3
    assert report["summary"]["paidBookings"] == 3
    assert report["summary"]["totalPaidRevenue"] == 500.50


def test_analytics_mixed_currencies():
    """Non-MYR orders are counted in booking records but excluded from the MYR revenue sum."""
    orders = [
        {"id": "ord_myr", "quoteType": "package", "operatorId": "op_1", "amount": 100.0, "currency": "MYR", "status": "paid", "paymentStatus": "paid"},
        {"id": "ord_usd", "quoteType": "package", "operatorId": "op_1", "amount": 200.0, "currency": "USD", "status": "paid", "paymentStatus": "paid"},
    ]
    db = _build_mock_db(orders=orders)
    report = generate_business_analytics(db, operator_id="op_1")

    assert report["summary"]["bookingRecords"] == 2
    assert report["summary"]["paidBookings"] == 2
    assert report["summary"]["totalPaidRevenue"] == 100.0


def test_analytics_historical_baseline_fixture():
    """
    Test against a synthetic replica of the exact historical baseline verified in Batch 19C-V:
    8 package Orders for TravelMate Holidays (5 paid, 3 expired), MYR 15,932.00 paid test total.
    """
    operator_id = "YV6pgiBS0PhfJjMMk3RVNCU6zht1"
    orders = [
        {"id": "pkg_ord_1", "quoteType": "package", "operatorId": operator_id, "amount": 3596.0, "status": "paid", "paymentStatus": "paid", "provider": "stripe_checkout_test"},
        {"id": "pkg_ord_2", "quoteType": "package", "operatorId": operator_id, "amount": 3596.0, "status": "paid", "paymentStatus": "paid", "provider": "stripe_checkout_test"},
        {"id": "pkg_ord_3", "quoteType": "package", "operatorId": operator_id, "amount": 899.0, "status": "expired", "paymentStatus": "unpaid", "provider": "stripe_checkout_test"},
        {"id": "pkg_ord_4", "quoteType": "package", "operatorId": operator_id, "amount": 899.0, "status": "expired", "paymentStatus": "unpaid", "provider": "stripe_checkout_test"},
        {"id": "pkg_ord_5", "quoteType": "package", "operatorId": operator_id, "amount": 899.0, "status": "expired", "paymentStatus": "unpaid", "provider": "stripe_checkout_test"},
        {"id": "pkg_ord_6", "quoteType": "package", "operatorId": operator_id, "amount": 899.0, "status": "paid", "paymentStatus": "paid", "provider": "stripe_checkout_test"},
        {"id": "pkg_ord_7", "quoteType": "package", "operatorId": operator_id, "amount": 3346.0, "status": "paid", "paymentStatus": "paid", "provider": "stripe_checkout_test"},
        {"id": "pkg_ord_8", "quoteType": "package", "operatorId": operator_id, "amount": 4495.0, "status": "paid", "paymentStatus": "paid", "provider": "stripe_checkout_test"},
    ]
    packages = [
        {"id": "pkg_penang", "operatorId": operator_id, "packageTitle": "Penang Heritage & Hills Escape – 3D2N", "price": 899.0, "approvalStatus": "approved"},
        {"id": "pkg_bp", "operatorId": operator_id, "packageTitle": "Balik Pulau Countryside & Nature Escape", "price": 588.98, "approvalStatus": "approved"},
        {"id": "pkg_bw", "operatorId": operator_id, "packageTitle": "Butterworth Heritage & Wildlife Discovery", "price": 229.0, "approvalStatus": "approved"},
    ]
    db = _build_mock_db(packages=packages, orders=orders)
    report = generate_business_analytics(db, operator_id=operator_id)

    # 1. Verification of Package Counts and Valuation
    assert report["summary"]["totalPackages"] == 3
    assert report["summary"]["approvedPackages"] == 3
    assert report["summary"]["totalPackageValue"] == 1716.98

    # 2. Verification of Authoritative Package Orders
    assert report["summary"]["bookingRecords"] == 8
    assert report["summary"]["paidBookings"] == 5
    assert report["summary"]["expiredBookings"] == 3
    assert report["summary"]["testModeOrders"] == 8
    assert report["summary"]["totalPaidRevenue"] == 15932.0

    # 3. Verification of Top-Level Summary Compatibility
    assert report["bookingCount"] == 8
    assert report["paidBookingCount"] == 5
    assert report["expiredBookingCount"] == 3
    assert report["totalPaidRevenue"] == 15932.0
    assert len(report["bookings"]) == 8


def test_analytics_package_valuation_only_counts_approved_packages():
    """Only approved packages contribute to totalPackageValue; draft, pending and rejected are excluded."""
    operator_id = "op_test_val"
    packages = [
        {"id": "pkg_app", "operatorId": operator_id, "packageTitle": "Approved Package", "price": 899.0, "approvalStatus": "approved"},
        {"id": "pkg_draft", "operatorId": operator_id, "packageTitle": "Draft Package", "price": 500.0, "approvalStatus": "draft"},
        {"id": "pkg_pend", "operatorId": operator_id, "packageTitle": "Pending Package", "price": 350.0, "approvalStatus": "pending"},
        {"id": "pkg_rej", "operatorId": operator_id, "packageTitle": "Rejected Package", "price": 200.0, "approvalStatus": "rejected"},
    ]
    db = _build_mock_db(packages=packages, orders=[])
    report = generate_business_analytics(db, operator_id=operator_id)

    assert report["summary"]["totalPackages"] == 4
    assert report["summary"]["approvedPackages"] == 1
    assert report["summary"]["pendingPackages"] == 1
    assert report["summary"]["rejectedPackages"] == 1
    assert report["summary"]["draftPackages"] == 1
    # Only the approved package (899.0) is included in inventory valuation
    assert report["summary"]["totalPackageValue"] == 899.0


def test_analytics_payment_status_edge_cases():
    """Verifies payment classification edge cases (succeeded vs failed/payment_failed)."""
    orders = [
        # Succeeded status counts as paid
        {"id": "ord_succ", "quoteType": "package", "operatorId": "op_edge", "amount": 250.0, "status": "paid", "paymentStatus": "succeeded"},
        # Payment failed must not count as paid even if status is paid
        {"id": "ord_pfail", "quoteType": "package", "operatorId": "op_edge", "amount": 300.0, "status": "paid", "paymentStatus": "payment_failed"},
        # Status payment_failed must not count as paid
        {"id": "ord_sfail", "quoteType": "package", "operatorId": "op_edge", "amount": 400.0, "status": "payment_failed", "paymentStatus": "paid"},
        # Standard paid
        {"id": "ord_paid", "quoteType": "package", "operatorId": "op_edge", "amount": 500.0, "status": "paid", "paymentStatus": "paid"},
    ]
    db = _build_mock_db(orders=orders)
    report = generate_business_analytics(db, operator_id="op_edge")

    assert report["summary"]["bookingRecords"] == 4
    assert report["summary"]["paidBookings"] == 2
    assert report["summary"]["totalPaidRevenue"] == 750.0
    assert {b["id"] for b in report["bookings"]} == {"ord_succ", "ord_pfail", "ord_sfail", "ord_paid"}


def test_analytics_authoritative_settlement_matrix():
    """
    Comprehensive verification of settlement semantics across conflict states:
    1. Explicit unpaid paymentStatus never produces paid revenue (even if status=paid).
    2. Explicit pending/payment_pending never produces paid revenue.
    3. Failed and cancelled payments are excluded.
    4. Legitimate settled orders are included once.
    5. Expired attempts are excluded from revenue.
    6. Missing legacy paymentStatus falls back to server order status.
    11. Totals agree with Operator Bookings semantics under supported order states.
    """
    operator_id = "op_matrix"
    orders = [
        # 1. Paid / paid -> Settled
        {"id": "o_paid", "quoteType": "package", "operatorId": operator_id, "amount": 1000.0, "status": "paid", "paymentStatus": "paid"},
        # 2. Succeeded / succeeded -> Settled
        {"id": "o_succ", "quoteType": "package", "operatorId": operator_id, "amount": 500.0, "status": "succeeded", "paymentStatus": "succeeded"},
        # 3. Pending / paid -> Settled (payment arrived before order fulfillment complete)
        {"id": "o_pend_paid", "quoteType": "package", "operatorId": operator_id, "amount": 300.0, "status": "pending", "paymentStatus": "paid"},
        # 4. Paid / unpaid -> Disqualified (unpaid settlement is authoritative over general status)
        {"id": "o_paid_unpaid", "quoteType": "package", "operatorId": operator_id, "amount": 700.0, "status": "paid", "paymentStatus": "unpaid"},
        # 5. Paid / pending -> Disqualified (pending settlement is uncollected)
        {"id": "o_paid_pend", "quoteType": "package", "operatorId": operator_id, "amount": 400.0, "status": "paid", "paymentStatus": "pending"},
        # 6. Paid / payment_pending -> Disqualified
        {"id": "o_paid_ppend", "quoteType": "package", "operatorId": operator_id, "amount": 450.0, "status": "paid", "paymentStatus": "payment_pending"},
        # 7. Expired / paid -> Disqualified (expired session cannot be fulfilled)
        {"id": "o_exp_paid", "quoteType": "package", "operatorId": operator_id, "amount": 800.0, "status": "expired", "paymentStatus": "paid"},
        # 8. Cancelled / paid -> Disqualified
        {"id": "o_canc_paid", "quoteType": "package", "operatorId": operator_id, "amount": 900.0, "status": "cancelled", "paymentStatus": "paid"},
        # 9. Paid / failed -> Disqualified
        {"id": "o_paid_fail", "quoteType": "package", "operatorId": operator_id, "amount": 600.0, "status": "paid", "paymentStatus": "failed"},
        # 10. Legacy paid with None/missing paymentStatus -> Settled (server fallback)
        {"id": "o_legacy_none", "quoteType": "package", "operatorId": operator_id, "amount": 200.0, "status": "paid", "paymentStatus": None},
        # 11. Legacy succeeded with empty string paymentStatus -> Settled (server fallback)
        {"id": "o_legacy_empty", "quoteType": "package", "operatorId": operator_id, "amount": 150.0, "status": "succeeded", "paymentStatus": ""},
        # 12. Checkout open / unpaid -> Disqualified (standard unpaid attempt)
        {"id": "o_open_unpaid", "quoteType": "package", "operatorId": operator_id, "amount": 350.0, "status": "checkout_open", "paymentStatus": "unpaid"},
    ]
    db = _build_mock_db(orders=orders)
    report = generate_business_analytics(db, operator_id=operator_id)

    # Total recorded orders = 12
    assert report["summary"]["bookingRecords"] == 12

    # Settled orders = 5:
    # o_paid (1000) + o_succ (500) + o_pend_paid (300) + o_legacy_none (200) + o_legacy_empty (150) = 2150.0
    assert report["summary"]["paidBookings"] == 5
    assert report["summary"]["totalPaidRevenue"] == 2150.0


# ==============================================================================
# INTEGRATION / ROUTE TESTS: /api/fr12/analytics
# ==============================================================================

def test_analytics_api_endpoint_success(client, mock_operator_auth):
    """Authenticated operator calling /api/fr12/analytics receives 200 with structured report."""
    orders = [
        {"id": "ord_1", "quoteType": "package", "operatorId": "test_operator_uid", "amount": 899.0, "status": "paid", "paymentStatus": "paid"},
    ]
    db = _build_mock_db(orders=orders)
    with patch("modules.fr12_tourism_operator_management.routes.get_db", return_value=db):
        res = client.get("/api/fr12/analytics", headers={"Authorization": "Bearer valid_test_token"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert "analytics" in data
    assert data["analytics"]["summary"]["bookingRecords"] == 1
    assert data["analytics"]["summary"]["paidBookings"] == 1
    assert data["analytics"]["summary"]["totalPaidRevenue"] == 899.0


def test_analytics_api_endpoint_rejects_traveller(client, mock_traveller_auth):
    """Traveller role is denied access to /api/fr12/analytics with 403 Forbidden."""
    res = client.get("/api/fr12/analytics", headers={"Authorization": "Bearer valid_test_token"})
    assert res.status_code == 403


def test_analytics_admin_operator_override(client, mock_admin_auth):
    """Admin calling /api/fr12/analytics falls back to all packages/orders if operator has 0 packages."""
    orders = [
        {"id": "ord_1", "quoteType": "package", "operatorId": "other_op", "amount": 500.0, "status": "paid", "paymentStatus": "paid"},
    ]
    db = _build_mock_db(packages=[], orders=orders)
    with patch("modules.fr12_tourism_operator_management.routes.get_db", return_value=db):
        res = client.get("/api/fr12/analytics", headers={"Authorization": "Bearer valid_test_token"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    # Global admin sees the other operator's order when operator_id=None
    assert data["analytics"]["summary"]["bookingRecords"] == 1
    assert data["analytics"]["summary"]["totalPaidRevenue"] == 500.0


def test_analytics_strips_sensitive_payment_metadata_vulnerability():
    """
    VULNERABILITY PROOF TEST:
    Verifies that sensitive payment and checkout metadata (checkoutUrl, checkoutSessionId,
    providerIdempotencyKey, travellerId, clientSecret, packageAttemptId, etc.) are strictly
    excluded from analytics booking records.
    """
    orders = [{
        "id": "ord_sensitive_leak",
        "quoteType": "package",
        "operatorId": "op_test_sec",
        "amount": 999.0,
        "currency": "MYR",
        "status": "paid",
        "paymentStatus": "paid",
        "provider": "stripe_checkout_test",
        # Sensitive payment and session fields:
        "checkoutUrl": "https://checkout.stripe.com/c/pay/cs_test_sensitive_url_12345",
        "checkoutSessionId": "cs_test_sensitive_session_67890",
        "providerIdempotencyKey": "package_checkout:idemp_key_abcde",
        "stripePaymentIntentId": "pi_secret_intent_123",
        "stripeSessionId": "cs_test_sensitive_session_67890",
        "clientSecret": "pi_secret_intent_123_secret_xyz",
        "paymentMethodId": "pm_secret_card_456",
        "travellerId": "usr_traveller_confidential_999",
        "packageAttemptId": "att_attempt_uuid_111",
        "orderAttemptId": "att_order_uuid_222",
        "arbitraryLeakKey": "unforeseen_private_token_333",
        "packageSnapshot": {
            "title": "Historical Penang Walk",
            "packageId": "pkg_penang_walk",
            "internalAdminNotes": "Confidential margin details",
        },
    }]
    db = _build_mock_db(orders=orders)
    report = generate_business_analytics(db, operator_id="op_test_sec")

    assert len(report["bookings"]) == 1
    booking = report["bookings"][0]

    # Sensitive fields that MUST NOT exist in the projection:
    assert "checkoutUrl" not in booking
    assert "checkoutSessionId" not in booking
    assert "providerIdempotencyKey" not in booking
    assert "travellerId" not in booking
    assert "packageAttemptId" not in booking
    assert "orderAttemptId" not in booking
    assert "arbitraryLeakKey" not in booking
    assert "packageSnapshot" not in booking
    assert "stripePaymentIntentId" not in booking
    assert "stripeSessionId" not in booking
    assert "clientSecret" not in booking
    assert "paymentMethodId" not in booking


# ==============================================================================
# BATCH P-S1: 14 MANDATORY TEST SCENARIOS
# ==============================================================================

def test_scenario_1_checkout_url_not_exposed():
    """Scenario 1: Checkout URL is never exposed in analytics bookings."""
    orders = [{
        "id": "ord_s1",
        "quoteType": "package",
        "operatorId": "op_test",
        "amount": 500.0,
        "status": "paid",
        "paymentStatus": "paid",
        "checkoutUrl": "https://checkout.stripe.com/c/pay/cs_test_secret_link_111",
    }]
    db = _build_mock_db(orders=orders)
    report = generate_business_analytics(db, operator_id="op_test")
    assert len(report["bookings"]) == 1
    assert "checkoutUrl" not in report["bookings"][0]


def test_scenario_2_checkout_session_id_not_exposed():
    """Scenario 2: Checkout Session ID is never exposed in analytics bookings."""
    orders = [{
        "id": "ord_s2",
        "quoteType": "package",
        "operatorId": "op_test",
        "amount": 500.0,
        "status": "paid",
        "paymentStatus": "paid",
        "checkoutSessionId": "cs_test_session_id_222",
    }]
    db = _build_mock_db(orders=orders)
    report = generate_business_analytics(db, operator_id="op_test")
    assert len(report["bookings"]) == 1
    assert "checkoutSessionId" not in report["bookings"][0]


def test_scenario_3_provider_idempotency_key_not_exposed():
    """Scenario 3: Provider Idempotency Key is never exposed in analytics bookings."""
    orders = [{
        "id": "ord_s3",
        "quoteType": "package",
        "operatorId": "op_test",
        "amount": 500.0,
        "status": "paid",
        "paymentStatus": "paid",
        "providerIdempotencyKey": "package_checkout:idemp_uuid_333",
    }]
    db = _build_mock_db(orders=orders)
    report = generate_business_analytics(db, operator_id="op_test")
    assert len(report["bookings"]) == 1
    assert "providerIdempotencyKey" not in report["bookings"][0]


def test_scenario_4_unexpected_sensitive_fields_cannot_leak():
    """Scenario 4: Unexpected or future sensitive fields cannot leak through allowlist projection."""
    orders = [{
        "id": "ord_s4",
        "quoteType": "package",
        "operatorId": "op_test",
        "amount": 500.0,
        "status": "paid",
        "paymentStatus": "paid",
        "clientSecret": "secret_abc",
        "stripePaymentIntentId": "pi_123",
        "stripeSessionId": "cs_456",
        "paymentMethodId": "pm_789",
        "travellerId": "usr_traveller_secret",
        "packageAttemptId": "att_123",
        "orderAttemptId": "ord_att_456",
        "unforeseenToken": "token_future_xyz",
        "rawCustomerCard": "4242-4242-4242-4242",
        "internalAuditTrail": {"superAdminReview": True},
        "packageSnapshot": {
            "title": "Heritage Walk",
            "packageId": "pkg_1",
            "internalMargin": 0.45,
            "privateSupplierNotes": "DO NOT SHARE WITH OPERATOR",
        },
    }]
    db = _build_mock_db(orders=orders)
    report = generate_business_analytics(db, operator_id="op_test")
    booking = report["bookings"][0]

    forbidden_keys = {
        "clientSecret", "stripePaymentIntentId", "stripeSessionId", "paymentMethodId",
        "travellerId", "packageAttemptId", "orderAttemptId", "unforeseenToken",
        "rawCustomerCard", "internalAuditTrail", "packageSnapshot",
        "checkoutUrl", "checkoutSessionId", "providerIdempotencyKey",
    }
    for key in forbidden_keys:
        assert key not in booking, f"Forbidden key {key} leaked into analytics booking projection"

    # Verify booking has only allowlisted keys
    allowed_keys = {
        "id", "orderReference", "packageId", "packageTitle", "operatorId", "quoteType",
        "departureDate", "groupSize", "adults", "children", "paymentStatus", "orderStatus",
        "status", "fulfillmentStatus", "amount", "groupTotal", "currency",
        "supplierReservationStatus", "testMode", "createdAt", "updatedAt",
    }
    assert set(booking.keys()).issubset(allowed_keys)


def test_scenario_5_safe_business_fields_remain_present():
    """Scenario 5: Safe business fields remain present and accurately populated."""
    orders = [{
        "id": "ord_s5",
        "quoteType": "package",
        "operatorId": "op_test",
        "amount": 1250.00,
        "currency": "MYR",
        "status": "paid",
        "paymentStatus": "paid",
        "fulfillmentStatus": "fulfilled",
        "provider": "stripe_checkout_test",
        "supplierReservationStatus": "not_created",
        "createdAt": "2026-10-20T10:00:00Z",
        "updatedAt": "2026-10-20T10:05:00Z",
        "packageSnapshot": {
            "packageId": "pkg_penang_5",
            "title": "Penang Hill Nature & Sunset Tour",
            "selectedDepartureDate": "2027-03-15",
            "groupSize": 4,
            "participants": {"adults": 2, "children": 2, "total": 4},
        },
    }]
    db = _build_mock_db(orders=orders)
    report = generate_business_analytics(db, operator_id="op_test")
    assert len(report["bookings"]) == 1
    b = report["bookings"][0]

    assert b["id"] == "ord_s5"
    assert b["orderReference"] == "ord_s5"
    assert b["packageId"] == "pkg_penang_5"
    assert b["packageTitle"] == "Penang Hill Nature & Sunset Tour"
    assert b["operatorId"] == "op_test"
    assert b["quoteType"] == "package"
    assert b["departureDate"] == "2027-03-15"
    assert b["groupSize"] == 4
    assert b["adults"] == 2
    assert b["children"] == 2
    assert b["amount"] == 1250.00
    assert b["groupTotal"] == 1250.00
    assert b["currency"] == "MYR"
    assert b["status"] == "paid"
    assert b["orderStatus"] == "paid"
    assert b["paymentStatus"] == "paid"
    assert b["fulfillmentStatus"] == "fulfilled"
    assert b["supplierReservationStatus"] == "not_created"
    assert b["testMode"] is True
    assert b["createdAt"] == "2026-10-20T10:00:00Z"
    assert b["updatedAt"] == "2026-10-20T10:05:00Z"


def test_scenario_6_paid_test_revenue_calculations():
    """Scenario 6: Paid Test revenue calculations remain strictly correct."""
    orders = [
        {"id": "ord_t1", "quoteType": "package", "operatorId": "op_test", "amount": 800.0, "status": "paid", "paymentStatus": "paid", "provider": "stripe_checkout_test"},
        {"id": "ord_t2", "quoteType": "package", "operatorId": "op_test", "amount": 1200.0, "status": "paid", "paymentStatus": "paid", "testMode": True},
    ]
    db = _build_mock_db(orders=orders)
    report = generate_business_analytics(db, operator_id="op_test")

    assert report["summary"]["bookingRecords"] == 2
    assert report["summary"]["paidBookings"] == 2
    assert report["summary"]["testModeOrders"] == 2
    assert report["summary"]["totalPaidRevenue"] == 2000.0
    assert report["totalPaidRevenue"] == 2000.0


def test_scenario_7_unpaid_failed_orders_do_not_become_revenue():
    """Scenario 7: Unpaid, expired, failed, and cancelled orders do not count as revenue."""
    orders = [
        {"id": "o_unpaid", "quoteType": "package", "operatorId": "op_test", "amount": 500.0, "status": "checkout_open", "paymentStatus": "unpaid"},
        {"id": "o_expired", "quoteType": "package", "operatorId": "op_test", "amount": 600.0, "status": "expired", "paymentStatus": "unpaid"},
        {"id": "o_failed", "quoteType": "package", "operatorId": "op_test", "amount": 700.0, "status": "failed", "paymentStatus": "failed"},
        {"id": "o_cancelled", "quoteType": "package", "operatorId": "op_test", "amount": 800.0, "status": "cancelled", "paymentStatus": "paid"},
    ]
    db = _build_mock_db(orders=orders)
    report = generate_business_analytics(db, operator_id="op_test")

    assert report["summary"]["bookingRecords"] == 4
    assert report["summary"]["paidBookings"] == 0
    assert report["summary"]["pendingBookings"] == 1
    assert report["summary"]["expiredBookings"] == 1
    assert report["summary"]["failedBookings"] == 1
    assert report["summary"]["cancelledBookings"] == 1
    assert report["summary"]["totalPaidRevenue"] == 0.0


def test_scenario_8_operator_ownership_isolation():
    """Scenario 8: Operator ownership isolation strictly enforced."""
    orders = [
        {"id": "ord_mine", "quoteType": "package", "operatorId": "op_alpha", "amount": 1000.0, "status": "paid", "paymentStatus": "paid"},
        {"id": "ord_other", "quoteType": "package", "operatorId": "op_beta", "amount": 5000.0, "status": "paid", "paymentStatus": "paid"},
    ]
    db = _build_mock_db(orders=orders)
    report = generate_business_analytics(db, operator_id="op_alpha")

    assert report["summary"]["bookingRecords"] == 1
    assert report["summary"]["paidBookings"] == 1
    assert report["summary"]["totalPaidRevenue"] == 1000.0
    assert [b["id"] for b in report["bookings"]] == ["ord_mine"]


def test_scenario_9_unauthorized_access_rejection(client, mock_traveller_auth):
    """Scenario 9: Unauthorized access (traveller role) is rejected with 403 Forbidden."""
    res = client.get("/api/fr12/analytics", headers={"Authorization": "Bearer valid_test_token"})
    assert res.status_code == 403


def test_scenario_10_json_analytics_endpoint_safety(client, mock_operator_auth):
    """Scenario 10: JSON Analytics API response returns HTTP 200 with sanitized bookings."""
    orders = [{
        "id": "ord_api_test",
        "quoteType": "package",
        "operatorId": "test_operator_uid",
        "amount": 750.0,
        "status": "paid",
        "paymentStatus": "paid",
        "checkoutUrl": "https://checkout.stripe.com/pay/cs_live_leak",
        "checkoutSessionId": "cs_live_leak",
        "providerIdempotencyKey": "pkg_leak_idemp",
        "clientSecret": "sec_leak_123",
        "travellerId": "traveller_leak_456",
    }]
    db = _build_mock_db(orders=orders)
    with patch("modules.fr12_tourism_operator_management.routes.get_db", return_value=db):
        res = client.get("/api/fr12/analytics", headers={"Authorization": "Bearer valid_test_token"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert "analytics" in data
    bookings = data["analytics"]["bookings"]
    assert len(bookings) == 1
    b = bookings[0]
    assert "checkoutUrl" not in b
    assert "checkoutSessionId" not in b
    assert "providerIdempotencyKey" not in b
    assert "clientSecret" not in b
    assert "travellerId" not in b
    assert b["id"] == "ord_api_test"
    assert b["orderReference"] == "ord_api_test"


def test_scenario_11_report_export_safety(client, mock_operator_auth):
    """Scenario 11: PDF report export succeeds cleanly without leaking sensitive payment metadata."""
    orders = [{
        "id": "ord_export_test",
        "quoteType": "package",
        "operatorId": "test_operator_uid",
        "amount": 899.0,
        "status": "paid",
        "paymentStatus": "paid",
        "checkoutUrl": "https://checkout.stripe.com/c/pay/cs_leak",
        "travellerId": "traveller_uid_export",
    }]
    db = _build_mock_db(orders=orders)
    with patch("modules.fr12_tourism_operator_management.routes.get_db", return_value=db), \
         patch("modules.fr12_tourism_operator_management.routes.retrieveRecord", return_value={"name": "Test Agency"}):
        res = client.get("/api/fr12/reports/export", headers={"Authorization": "Bearer valid_test_token"})
    assert res.status_code == 200
    assert res.headers["Content-Type"] == "application/pdf"
    assert res.data.startswith(b"%PDF")
    # Verify raw sensitive URLs or secrets are not dumped into the PDF binary
    assert b"cs_leak" not in res.data
    assert b"traveller_uid_export" not in res.data


def test_scenario_12_operator_analytics_template_compatibility():
    """Scenario 12: Existing Operator Analytics template compatibility verified."""
    orders = [{
        "id": "ord_tpl",
        "quoteType": "package",
        "operatorId": "op_tpl",
        "amount": 999.0,
        "status": "paid",
        "paymentStatus": "paid",
    }]
    packages = [{
        "id": "pkg_tpl",
        "operatorId": "op_tpl",
        "packageTitle": "Sample Package",
        "price": 999.0,
        "approvalStatus": "approved",
    }]
    campaigns = [{
        "id": "camp_tpl",
        "operatorId": "op_tpl",
        "reviewStatus": "approved",
        "campaignStatus": "active",
    }]
    db = _build_mock_db(packages=packages, campaigns=campaigns, orders=orders)
    report = generate_business_analytics(db, operator_id="op_tpl")

    summary = report.get("summary", {})
    # Check all keys required by analytics.html template:
    assert "totalPackages" in summary
    assert "approvedPackages" in summary
    assert "pendingPackages" in summary
    assert "rejectedPackages" in summary
    assert "draftPackages" in summary
    assert "totalCampaigns" in summary
    assert "activeCampaigns" in summary
    assert "approvedCampaigns" in summary
    assert "pendingCampaigns" in summary
    assert "rejectedCampaigns" in summary
    assert "bookingRecords" in summary
    assert "totalPackageValue" in summary
    assert summary["bookingRecords"] == 1
    assert summary["totalPackageValue"] == 999.0


def test_scenario_13_operator_bookings_api_compatibility(client, mock_operator_auth):
    """Scenario 13: Existing Operator Bookings API (/api/fr12/bookings) retains clean projection."""
    orders = [{
        "id": "ord_bkg_api",
        "quoteType": "package",
        "operatorId": "test_operator_uid",
        "amount": 650.0,
        "status": "paid",
        "paymentStatus": "paid",
        "packageSnapshot": {"title": "Penang Food Walk"},
    }]
    with patch("modules.fr12_tourism_operator_management.routes.retrieveRecord", return_value=orders):
        res = client.get("/api/fr12/bookings", headers={"Authorization": "Bearer valid_test_token"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    items = data["items"]
    assert len(items) == 1
    item = items[0]
    assert item["orderReference"] == "ord_bkg_api"
    assert item["packageTitle"] == "Penang Food Walk"
    assert "checkoutUrl" not in item
    assert "checkoutSessionId" not in item


def test_scenario_14_admin_reporting_preserves_safety(client, mock_admin_auth):
    """Scenario 14: Admin reporting fallback (operator_id=None) sees global orders without leaking secrets."""
    orders = [
        {
            "id": "ord_adm_1",
            "quoteType": "package",
            "operatorId": "op_any_1",
            "amount": 1000.0,
            "status": "paid",
            "paymentStatus": "paid",
            "checkoutUrl": "https://checkout.stripe.com/c/pay/cs_admin_leak_1",
            "travellerId": "traveller_secret_adm_1",
        },
        {
            "id": "ord_adm_2",
            "quoteType": "package",
            "operatorId": "op_any_2",
            "amount": 2000.0,
            "status": "paid",
            "paymentStatus": "paid",
            "checkoutUrl": "https://checkout.stripe.com/c/pay/cs_admin_leak_2",
            "travellerId": "traveller_secret_adm_2",
        },
    ]
    db = _build_mock_db(packages=[], orders=orders)
    with patch("modules.fr12_tourism_operator_management.routes.get_db", return_value=db):
        res = client.get("/api/fr12/analytics", headers={"Authorization": "Bearer valid_test_token"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    bookings = data["analytics"]["bookings"]
    assert len(bookings) == 2
    for b in bookings:
        assert "checkoutUrl" not in b
        assert "travellerId" not in b
        assert "checkoutSessionId" not in b
        assert "orderReference" in b


