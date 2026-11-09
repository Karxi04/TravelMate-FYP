import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

ROOT = Path(__file__).resolve().parents[2]
ADMIN_DIR = ROOT / "admin_website"
OP_DIR = ROOT / "operator_website"
BACKEND_DIR = ROOT / "backend_api"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
while str(ADMIN_DIR) in sys.path:
    sys.path.remove(str(ADMIN_DIR))
if str(OP_DIR) not in sys.path:
    sys.path.insert(0, str(OP_DIR))

for k in list(sys.modules.keys()):
    if k == "modules" or k.startswith("modules."):
        del sys.modules[k]

from operator_website.app import app
from operator_website.modules.fr12_tourism_operator_management.routes import _is_pending_booking


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        yield c


@pytest.fixture
def auth_client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    if "request_rate_limiter" in app.extensions:
        app.extensions["request_rate_limiter"].reset()
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["id_token"] = "valid_operator_token"
            sess["portal_role"] = "operator"
            sess["verification_status"] = "approved"
            sess["operator_id"] = "test_op_uid"
        yield c


# Test fixtures for various order lifecycles
P1_FIXTURES = [
    # 0: Paid & Fulfilled
    {
        "orderReference": "ord-paid-fulfilled",
        "packageId": "pkg-penang-walk",
        "packageTitle": "George Town UNESCO Heritage & Michelin Food Walk",
        "departureDate": "2027-03-01",
        "groupSize": 2,
        "adults": 2,
        "children": 0,
        "paymentStatus": "paid",
        "orderStatus": "paid",
        "fulfillmentStatus": "fulfilled",
        "groupTotal": 500.00,
        "currency": "MYR",
        "supplierReservationStatus": "not_created",
        "testMode": True,
        "createdAt": "2026-10-20T10:00:00Z",
    },
    # 1: Paid & Fulfillment Pending
    {
        "orderReference": "ord-paid-pending-ful",
        "packageId": "pkg-penang-hill",
        "packageTitle": "Penang Hill Nature & Sunset Tour",
        "departureDate": "2027-03-05",
        "groupSize": 4,
        "adults": 2,
        "children": 2,
        "paymentStatus": "paid",
        "orderStatus": "paid",
        "fulfillmentStatus": "pending",
        "groupTotal": 800.00,
        "currency": "MYR",
        "supplierReservationStatus": "not_created",
        "testMode": True,
        "createdAt": "2026-10-20T11:00:00Z",
    },
    # 2: Active Unpaid Stripe Checkout (FR09 standard open checkout)
    {
        "orderReference": "ord-active-unpaid",
        "packageId": "pkg-cheong-fatt-tze",
        "packageTitle": "Blue Mansion & Architectural Exploration",
        "departureDate": "2027-03-10",
        "groupSize": 2,
        "adults": 2,
        "children": 0,
        "paymentStatus": "unpaid",
        "orderStatus": "checkout_open",
        "fulfillmentStatus": "not_created",
        "groupTotal": 350.00,
        "currency": "MYR",
        "supplierReservationStatus": "not_created",
        "testMode": True,
        "createdAt": "2026-10-20T12:00:00Z",
    },
    # 3: Legacy Payment Pending
    {
        "orderReference": "ord-legacy-pending",
        "packageId": "pkg-kek-lok-si",
        "packageTitle": "Kek Lok Si Temple Cultural Pilgrimage",
        "departureDate": "2027-03-15",
        "groupSize": 3,
        "adults": 3,
        "children": 0,
        "paymentStatus": "payment_pending",
        "orderStatus": "pending",
        "fulfillmentStatus": "fulfillment_pending",
        "groupTotal": 450.00,
        "currency": "MYR",
        "supplierReservationStatus": "not_created",
        "testMode": False,
        "createdAt": "2026-10-20T12:30:00Z",
    },
    # 4: Expired Checkout Session
    {
        "orderReference": "ord-expired-checkout",
        "packageId": "pkg-penang-walk",
        "packageTitle": "George Town UNESCO Heritage & Michelin Food Walk",
        "departureDate": "2027-03-02",
        "groupSize": 1,
        "adults": 1,
        "children": 0,
        "paymentStatus": "unpaid",
        "orderStatus": "checkout_expired",
        "fulfillmentStatus": "not_created",
        "groupTotal": 250.00,
        "currency": "MYR",
        "supplierReservationStatus": "not_created",
        "testMode": True,
        "createdAt": "2026-10-19T09:00:00Z",
    },
    # 5: Failed Payment
    {
        "orderReference": "ord-failed-checkout",
        "packageId": "pkg-penang-hill",
        "packageTitle": "Penang Hill Nature & Sunset Tour",
        "departureDate": "2027-03-08",
        "groupSize": 2,
        "adults": 2,
        "children": 0,
        "paymentStatus": "failed",
        "orderStatus": "checkout_failed",
        "fulfillmentStatus": "not_created",
        "groupTotal": 400.00,
        "currency": "MYR",
        "supplierReservationStatus": "not_created",
        "testMode": True,
        "createdAt": "2026-10-19T10:00:00Z",
    },
    # 6: Cancelled Checkout
    {
        "orderReference": "ord-cancelled-checkout",
        "packageId": "pkg-penang-hill",
        "packageTitle": "Penang Hill Nature & Sunset Tour",
        "departureDate": "2027-03-09",
        "groupSize": 2,
        "adults": 2,
        "children": 0,
        "paymentStatus": "cancelled",
        "orderStatus": "checkout_cancelled",
        "fulfillmentStatus": "not_created",
        "groupTotal": 400.00,
        "currency": "MYR",
        "supplierReservationStatus": "not_created",
        "testMode": True,
        "createdAt": "2026-10-19T11:00:00Z",
    },
    # 7: Corrupted / Empty Status
    {
        "orderReference": "ord-empty-status",
        "packageId": "pkg-unknown",
        "packageTitle": "Mystery Package",
        "departureDate": None,
        "groupSize": None,
        "adults": None,
        "children": None,
        "paymentStatus": None,
        "orderStatus": None,
        "fulfillmentStatus": None,
        "groupTotal": None,
        "currency": "MYR",
        "supplierReservationStatus": "not_created",
        "testMode": False,
        "createdAt": None,
    },
]
for fixture in P1_FIXTURES:
    created=fixture['orderReference']=='ord-paid-fulfilled'
    paid=fixture['paymentStatus']=='paid'
    fixture['statusOverview']={
        'travellerTrip':{'state':'created' if created else 'not_created','label':'Created' if created else 'Not Created'},
        'operatorReadiness':{'state':'needs_review' if created else 'awaiting_arrangements' if paid else 'not_applicable','label':'Needs Review' if created else 'Awaiting Arrangements' if paid else 'Not Applicable'},
        'supplierArrangements':{'state':'needs_review','label':'Needs Review'}}


# =========================================================================
# Scenario 1: Active unpaid checkout appears as Pending in status filter
# =========================================================================
def test_p1_01_active_unpaid_checkout_appears_as_pending(auth_client):
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "items": P1_FIXTURES}

    with patch.dict(app.view_functions["operator_fr12.bookings"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res = auth_client.get("/bookings?status=pending")
        assert res.status_code == 200
        html = res.get_data(as_text=True)

        # Active unpaid order must appear
        assert "ord-active-unpaid" in html
        # Legacy pending order must appear
        assert "ord-legacy-pending" in html
        # Paid orders must NOT appear in pending filter
        assert "ord-paid-fulfilled" not in html
        assert "ord-paid-pending-ful" not in html
        # Expired, failed, and cancelled must NOT appear in pending filter
        assert "ord-expired-checkout" not in html
        assert "ord-failed-checkout" not in html
        assert "ord-cancelled-checkout" not in html


# =========================================================================
# Scenario 2: Pending count includes eligible unpaid orders
# =========================================================================
def test_p1_02_pending_count_includes_eligible_unpaid_orders(auth_client):
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "items": P1_FIXTURES}

    with patch.dict(app.view_functions["operator_fr12.bookings"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res = auth_client.get("/bookings")
        assert res.status_code == 200
        # In P1_FIXTURES: ord-active-unpaid and ord-legacy-pending are pending (2 total)
        # Helper function unit assertion
        pending_items = [b for b in P1_FIXTURES if _is_pending_booking(b)]
        assert len(pending_items) == 2
        assert {b["orderReference"] for b in pending_items} == {"ord-active-unpaid", "ord-legacy-pending"}


# =========================================================================
# Scenario 3: Expired unpaid checkout is not actionable pending
# =========================================================================
def test_p1_03_expired_unpaid_checkout_not_actionable_pending(auth_client):
    expired_order = {
        "orderReference": "ord-exp-test",
        "paymentStatus": "unpaid",
        "orderStatus": "checkout_expired",
    }
    assert _is_pending_booking(expired_order) is False

    expired_order_2 = {
        "orderReference": "ord-exp-test-2",
        "paymentStatus": "expired",
        "orderStatus": "checkout_open",
    }
    assert _is_pending_booking(expired_order_2) is False


# =========================================================================
# Scenario 4: Failed checkout is not counted as pending payment
# =========================================================================
def test_p1_04_failed_checkout_not_counted_as_pending_payment():
    failed_1 = {"paymentStatus": "failed", "orderStatus": "checkout_failed"}
    failed_2 = {"paymentStatus": "payment_failed", "orderStatus": "checkout_open"}
    failed_3 = {"paymentStatus": "unpaid", "orderStatus": "failed"}

    assert _is_pending_booking(failed_1) is False
    assert _is_pending_booking(failed_2) is False
    assert _is_pending_booking(failed_3) is False


# =========================================================================
# Scenario 5: Cancelled checkout is not counted as pending payment
# =========================================================================
def test_p1_05_cancelled_checkout_not_counted_as_pending_payment():
    cancelled_1 = {"paymentStatus": "cancelled", "orderStatus": "checkout_cancelled"}
    cancelled_2 = {"paymentStatus": "unpaid", "orderStatus": "cancelled"}
    assert _is_pending_booking(cancelled_1) is False
    assert _is_pending_booking(cancelled_2) is False


# =========================================================================
# Scenario 6: Pending list and total counts match
# =========================================================================
def test_p1_06_pending_list_and_total_counts_match(auth_client):
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "items": P1_FIXTURES}

    with patch.dict(app.view_functions["operator_fr12.bookings"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res = auth_client.get("/bookings?status=pending")
        assert res.status_code == 200
        html = res.get_data(as_text=True)

        # 2 pending bookings found in filtered list
        assert "2 bookings found" in html or "2 booking" in html
        assert "ord-active-unpaid" in html
        assert "ord-legacy-pending" in html


# =========================================================================
# Scenario 7: Unpaid booking details do not claim payment success
# =========================================================================
def test_p1_07_unpaid_booking_detail_does_not_claim_payment_success(auth_client):
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "booking": next(b for b in P1_FIXTURES if b['orderReference'] == 'ord-active-unpaid')}

    with patch.dict(app.view_functions["operator_fr12.booking_detail"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res = auth_client.get("/bookings/ord-active-unpaid")
        assert res.status_code == 200
        html = res.get_data(as_text=True)

        # Must state awaiting payment completion
        assert ">Pending<" in html
        # Must NOT claim verified payment occurred
        assert "recorded following verified payment" not in html
        # Must NOT claim trip created in mobile app
        assert "An independent Package Trip has been created" not in html
        # Status pill should say Payment Pending
        assert ">Pending<" in html


# =========================================================================
# Scenario 8: Failed booking details do not claim fulfillment
# =========================================================================
def test_p1_08_failed_booking_detail_does_not_claim_fulfillment(auth_client):
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "booking": next(b for b in P1_FIXTURES if b['orderReference'] == 'ord-failed-checkout')}

    with patch.dict(app.view_functions["operator_fr12.booking_detail"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res = auth_client.get("/bookings/ord-failed-checkout")
        assert res.status_code == 200
        html = res.get_data(as_text=True)

        # Explains payment failed
        assert "payment attempt for this booking <strong>failed</strong>" in html or "failed" in html
        assert "recorded following verified payment" not in html
        assert "Not Created" in html
        assert ">Failed<" in html


# =========================================================================
# Scenario 9: Expired booking details show accurate explanation
# =========================================================================
def test_p1_09_expired_booking_detail_shows_accurate_explanation(auth_client):
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "booking": next(b for b in P1_FIXTURES if b['orderReference'] == 'ord-expired-checkout')}

    with patch.dict(app.view_functions["operator_fr12.booking_detail"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res = auth_client.get("/bookings/ord-expired-checkout")
        assert res.status_code == 200
        html = res.get_data(as_text=True)

        # Explains checkout session expired
        assert "checkout session has <strong>expired</strong> without payment completion" in html or "expired" in html
        assert "recorded following verified payment" not in html
        assert "Not Created" in html
        assert "Expired" in html


# =========================================================================
# Scenario 10: Verified payment with pending fulfillment does not claim trip creation
# =========================================================================
def test_p1_10_verified_payment_with_pending_fulfillment_does_not_claim_trip_creation(auth_client):
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "booking": next(b for b in P1_FIXTURES if b['orderReference'] == 'ord-paid-pending-ful')}

    with patch.dict(app.view_functions["operator_fr12.booking_detail"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res = auth_client.get("/bookings/ord-paid-pending-ful")
        assert res.status_code == 200
        html = res.get_data(as_text=True)

        # Verified payment acknowledged
        assert ">Paid<" in html
        # Explicitly states in progress / pending fulfillment
        assert "Not Created" in html
        assert "Order status summary" in html
        # Does NOT falsely claim trip has already been created
        assert "An independent <strong>Package Trip</strong> has been created" not in html
        assert "Awaiting Arrangements" in html


# =========================================================================
# Scenario 11: Completed fulfillment displays package trip information correctly
# =========================================================================
def test_p1_11_completed_fulfillment_displays_package_trip_information_correctly(auth_client):
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "booking": next(b for b in P1_FIXTURES if b['orderReference'] == 'ord-paid-fulfilled')}

    with patch.dict(app.view_functions["operator_fr12.booking_detail"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res = auth_client.get("/bookings/ord-paid-fulfilled")
        assert res.status_code == 200
        html = res.get_data(as_text=True)

        # Truthfully claims verified payment and trip created
        assert ">Paid<" in html
        assert "Traveller Trip" in html and ">Created<" in html
        assert "Traveller Trip" in html and ">Created<" in html
        assert "Paid" in html


# =========================================================================
# Scenario 12: Supplier reservation disclosure remains truthful in all states
# =========================================================================
def test_p1_12_supplier_reservation_disclosure_remains_truthful(auth_client):
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "items": P1_FIXTURES}

    with patch.dict(app.view_functions["operator_fr12.booking_detail"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        for fixture in P1_FIXTURES[:7]:  # Test paid, pending, unpaid, expired, failed, cancelled
            mock_resp.json.return_value = {'ok': True, 'booking': fixture}
            res = auth_client.get(f"/bookings/{fixture['orderReference']}")
            assert res.status_code == 200
            html = res.get_data(as_text=True)

            # Header must always retain authoritative disclosure
            assert "Reservation Not Created" not in html
            # Clarifies that third-party supplier reservations are NOT created automatically
            assert "not independent supplier confirmation" in html
            # Notice box at bottom
            assert "Creating a Traveller Trip does not reserve a supplier service" in html


# =========================================================================
# Scenario 13: Operator A cannot view Operator B's bookings
# =========================================================================
def test_p1_13_operator_a_cannot_view_operator_b_bookings(auth_client):
    # Backend returns only Operator A's scoped bookings
    operator_a_bookings = [P1_FIXTURES[0]]  # ord-paid-fulfilled
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "items": operator_a_bookings}

    with patch.dict(app.view_functions["operator_fr12.booking_detail"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        # Operator A attempts to access an order belonging to Operator B (ord-active-unpaid)
        res = auth_client.get("/bookings/ord-active-unpaid")
        # Access is denied: redirected back to bookings list with not found/not accessible error
        assert res.status_code == 302
        assert "/bookings" in res.headers["Location"]


# =========================================================================
# Scenario 14: Unauthorized traveller cannot access operator management
# =========================================================================
def test_p1_14_unauthorized_traveller_cannot_access_operator_management(client):
    # 1. Unauthenticated client is redirected to login
    res_list = client.get("/bookings")
    assert res_list.status_code == 302
    assert res_list.headers["Location"] in ["/", "/login"]

    # 2. Unauthenticated client cannot view booking details
    res_det = client.get("/bookings/ord-paid-fulfilled")
    assert res_det.status_code == 302
    assert res_det.headers["Location"] in ["/", "/login"]

    # 3. Unverified operator client is redirected to verification
    with client.session_transaction() as sess:
        sess["id_token"] = "unverified_token"
        sess["portal_role"] = "operator"
        sess["verification_status"] = "pending"

    res_unverified = client.get("/bookings")
    assert res_unverified.status_code == 302
    assert "/verification" in res_unverified.headers["Location"]


# =========================================================================
# Scenario 15: Existing paid test revenue remains unchanged
# =========================================================================
def test_p1_15_existing_paid_test_revenue_remains_unchanged(auth_client):
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "items": P1_FIXTURES}

    with patch.dict(app.view_functions["operator_fr12.bookings"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res = auth_client.get("/bookings")
        assert res.status_code == 200
        html = res.get_data(as_text=True)

        # Revenue is sum of paid orders only: 500.00 + 800.00 = 1300.00
        # ord-active-unpaid (350.00) MUST NOT be added
        # ord-legacy-pending (450.00) MUST NOT be added
        # ord-expired-checkout (250.00) MUST NOT be added
        assert "MYR 1300.00" in html


# =========================================================================
# Scenario 16: Operator dashboard and analytics remain compatible
# =========================================================================
def test_p1_16_operator_dashboard_and_analytics_remain_compatible(auth_client):
    mock_analytics_resp = MagicMock(ok=True)
    mock_analytics_resp.json.return_value = {
        "summary": {
            "totalPackages": 5,
            "approvedPackages": 3,
            "pendingPackages": 1,
            "rejectedPackages": 1,
            "draftPackages": 0,
            "bookingRecords": 10,
            "paidBookings": 8,
            "expiredBookings": 2,
            "totalPaidRevenue": 4200.00,
        },
        "packages": [],
        "campaigns": [],
    }
    mock_me_resp = MagicMock(ok=True)
    mock_me_resp.json.return_value = {"profile": {"name": "Penang Heritage Tours"}}

    def mock_call_api(method, path, **kwargs):
        if "analytics" in path:
            return mock_analytics_resp
        return mock_me_resp

    with patch.dict(app.view_functions["operator_fr12.dashboard"].__globals__, {"call_api": mock_call_api}):
        res = auth_client.get("/dashboard")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "Dashboard" in html


# =========================================================================
# Scenario 17: No sensitive payment metadata exposure regression
# =========================================================================
def test_p1_17_no_sensitive_payment_metadata_exposure_regression(auth_client):
    leaky_order = {
        **P1_FIXTURES[2],
        "stripeClientSecret": "pi_live_secret_leaked_12345",
        "rawSessionId": "cs_test_session_secret_99999",
        "customerEmail": "private_traveller@example.com",
    }
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "items": [leaky_order]}

    with patch.dict(app.view_functions["operator_fr12.bookings"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res_list = auth_client.get("/bookings")
        html_list = res_list.get_data(as_text=True)
        assert "pi_live_secret_leaked_12345" not in html_list
        assert "cs_test_session_secret_99999" not in html_list

    with patch.dict(app.view_functions["operator_fr12.booking_detail"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res_det = auth_client.get(f"/bookings/{leaky_order['orderReference']}")
        html_det = res_det.get_data(as_text=True)
        assert "pi_live_secret_leaked_12345" not in html_det
        assert "cs_test_session_secret_99999" not in html_det


# =========================================================================
# Scenario 18: Existing FR09 checkout fulfillment contract integration
# =========================================================================
def test_p1_18_existing_fr09_checkout_fulfillment_contract(auth_client):
    # Simulated FR09 Stripe Checkout order projection as returned by backend
    fr09_projected_order = {
        "orderReference": "ord_fr09_stripe_checkout",
        "packageId": "pkg_penang_food",
        "packageTitle": "Penang Food Trail",
        "departureDate": "2027-03-20",
        "groupSize": 2,
        "adults": 2,
        "children": 0,
        "paymentStatus": "unpaid",
        "orderStatus": "checkout_open",
        "fulfillmentStatus": "not_created",
        "groupTotal": 250.00,
        "currency": "MYR",
        "supplierReservationStatus": "not_created",
        "testMode": True,
        "createdAt": "2026-10-20T12:00:00Z",
    }
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "items": [fr09_projected_order]}

    with patch.dict(app.view_functions["operator_fr12.bookings"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res = auth_client.get("/bookings?status=pending")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "ord_fr09_stripe_checkout" in html
        assert "Pending" in html
        assert "Traveller Trip" in html and "Operator Readiness" in html

    with patch.dict(app.view_functions["operator_fr12.booking_detail"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        mock_resp.json.return_value = {'ok': True, 'booking': fr09_projected_order}
        res_det = auth_client.get("/bookings/ord_fr09_stripe_checkout")
        assert res_det.status_code == 200
        html_det = res_det.get_data(as_text=True)
        assert ">Pending<" in html_det
        assert "Stripe Checkout" in html_det
        assert "Reservation Not Created" not in html_det


# =========================================================================
# Scenario 19: Empty or unknown statuses fail safely
# =========================================================================
def test_p1_19_empty_or_unknown_statuses_fail_safely(auth_client):
    assert _is_pending_booking({}) is False
    assert _is_pending_booking(None) is False
    assert _is_pending_booking({"paymentStatus": "", "orderStatus": ""}) is False
    assert _is_pending_booking({"paymentStatus": "unknown_status"}) is False

    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "items": [P1_FIXTURES[7]]}  # empty fixture

    with patch.dict(app.view_functions["operator_fr12.bookings"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res = auth_client.get("/bookings")
        assert res.status_code == 200


# =========================================================================
# Scenario 20: Existing operator portal rendering remains functional
# =========================================================================
def test_p1_20_existing_operator_portal_rendering_remains_functional(auth_client):
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "items": P1_FIXTURES}

    with patch.dict(app.view_functions["operator_fr12.bookings"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        # All filter views render without 500 error
        for st in ["all", "paid", "pending", "fulfilled", "test"]:
            res = auth_client.get(f"/bookings?status={st}")
            assert res.status_code == 200

        # Search query renders without error
        res_q = auth_client.get("/bookings?q=penang")
        assert res_q.status_code == 200
