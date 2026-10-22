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
    assert report["summary"]["expiredBookings"] == 2
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
