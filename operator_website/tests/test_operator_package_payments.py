import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

ROOT = Path(__file__).resolve().parents[2]
ADMIN_DIR = ROOT / "admin_website"
OP_DIR = ROOT / "operator_website"

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


@pytest.fixture
def unverified_client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["id_token"] = "unverified_token"
            sess["portal_role"] = "operator"
            sess["verification_status"] = "pending"
        yield c


def _mock_response(data, ok=True, status_code=200):
    mock = MagicMock()
    mock.ok = ok
    mock.status_code = status_code
    mock.json.return_value = data
    return mock


def _patch_view_api(view_name, mock_fn):
    fn_globals = app.view_functions[view_name].__globals__
    return patch.dict(fn_globals, {"call_api": mock_fn})


SAMPLE_PAYMENTS = [
    {
        "id": "ord_101",
        "orderReference": "TM-ORD-101",
        "packageId": "pkg_penang_escape",
        "packageTitle": "Penang Heritage & Coastal Escape",
        "groupTotal": 1250.00,
        "amount": 1250.00,
        "currency": "MYR",
        "groupSize": 2,
        "paymentStatus": "paid",
        "isPaid": True,
        "testMode": True,
        "orderStatus": "paid",
        "paidAt": "2026-11-01T10:15:00Z",
        "createdAt": "2026-11-01T10:00:00Z",
        "fulfillmentStatus": "trip_ready",
        "supplierReservationStatus": "operator_attested",
    },
    {
        "id": "ord_102",
        "orderReference": "TM-ORD-102",
        "packageId": "pkg_foodie_trail",
        "packageTitle": "George Town Foodie Discovery",
        "groupTotal": 450.00,
        "amount": 450.00,
        "currency": "MYR",
        "groupSize": 1,
        "paymentStatus": "paid",
        "isPaid": True,
        "testMode": True,
        "orderStatus": "paid",
        "paidAt": None,  # Explicitly null paidAt
        "createdAt": "2026-11-02T08:30:00Z",
        "fulfillmentStatus": "awaiting_operator_fulfillment",
        "supplierReservationStatus": "not_created",
    },
    {
        "id": "ord_103",
        "orderReference": "TM-ORD-103",
        "packageId": "pkg_island_adventure",
        "packageTitle": "Island Explorer Cruise",
        "groupTotal": 320.00,
        "amount": 320.00,
        "currency": "USD",  # Different currency for multi-currency test
        "groupSize": 3,
        "paymentStatus": "paid",
        "isPaid": True,
        "testMode": True,
        "orderStatus": "paid",
        "paidAt": "2026-11-02T16:45:00Z",
        "createdAt": "2026-11-02T16:00:00Z",
        "fulfillmentStatus": "partially_fulfilled",
        "supplierReservationStatus": "unconfirmed",
    },
    {
        "id": "ord_104",
        "orderReference": "TM-ORD-104",
        "packageId": "pkg_penang_escape",
        "packageTitle": "Penang Heritage & Coastal Escape",
        "groupTotal": 1250.00,
        "amount": 1250.00,
        "currency": "MYR",
        "groupSize": 2,
        "paymentStatus": "pending",
        "isPaid": False,
        "testMode": True,
        "orderStatus": "pending",
        "paidAt": None,
        "createdAt": "2026-11-03T09:00:00Z",
        "fulfillmentStatus": "awaiting_operator_fulfillment",
        "supplierReservationStatus": "not_created",
    },
]


def test_package_payments_auth_guard(client):
    """Unauthenticated access redirects to operator login."""
    resp = client.get("/payments")
    assert resp.status_code == 302
    assert resp.headers.get("Location") in ["/", "/login"]


def test_package_payments_unverified_operator_gate(unverified_client):
    """Unverified operators are redirected to verification page."""
    resp = unverified_client.get("/payments")
    assert resp.status_code == 302
    assert "/verification" in resp.headers.get("Location", "")


def test_package_payments_renders_successfully(auth_client):
    """Authenticated operator sees package payments with order refs, packages, and statuses."""
    payload = {"ok": True, "items": SAMPLE_PAYMENTS, "dataLimited": False, "recordLimit": 500}
    with _patch_view_api("operator_fr12.payments", MagicMock(return_value=_mock_response(payload))):
        resp = auth_client.get("/payments")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "Package Payments &amp; Settlements" in html
        assert "TM-ORD-101" in html
        assert "Penang Heritage &amp; Coastal Escape" in html
        assert "MYR 1250.00" in html
        assert "Test Paid" in html
        assert "Stripe Test Mode" in html
        assert "Trip Ready" in html


def test_package_payments_alias_route(auth_client):
    """The /package-payments alias route resolves to the same page."""
    payload = {"ok": True, "items": SAMPLE_PAYMENTS, "dataLimited": False, "recordLimit": 500}
    with _patch_view_api("operator_fr12.payments", MagicMock(return_value=_mock_response(payload))):
        resp = auth_client.get("/package-payments")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "Package Payments &amp; Settlements" in html
        assert "TM-ORD-101" in html


def test_package_payments_paid_at_accurate_rendering(auth_client):
    """Non-null paidAt renders timestamp; null paidAt explicitly renders 'Payment date unavailable'."""
    payload = {"ok": True, "items": SAMPLE_PAYMENTS, "dataLimited": False, "recordLimit": 500}
    with _patch_view_api("operator_fr12.payments", MagicMock(return_value=_mock_response(payload))):
        resp = auth_client.get("/payments")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        # ord_101 has valid paidAt
        assert "2026-11-01 10:15:00 UTC" in html
        # ord_102 has null paidAt -> shows 'Payment date unavailable'
        assert "Payment date unavailable" in html
        # Ensure createdAt (2026-11-02 08:30:00) is NOT substituted as paidAt
        assert "2026-11-02 08:30:00 UTC" not in html


def test_package_payments_multi_currency_safety(auth_client):
    """Mixed currencies (MYR and USD) are not aggregated into a single combined sum."""
    payload = {"ok": True, "items": SAMPLE_PAYMENTS, "dataLimited": False, "recordLimit": 500}
    with _patch_view_api("operator_fr12.payments", MagicMock(return_value=_mock_response(payload))):
        resp = auth_client.get("/payments")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        # Should display multi-currency breakdown
        assert "Multi-currency:" in html
        assert "MYR 1700.00" in html
        assert "USD 320.00" in html
        # Must NOT sum differing currencies (e.g. 1700 + 320 = 2020) as MYR or USD!
        assert "MYR 2020.00" not in html
        assert "USD 2020.00" not in html


def test_package_payments_single_currency_display(auth_client):
    """Single currency items display standard total without multi-currency tag."""
    myr_only = [p for p in SAMPLE_PAYMENTS if p["currency"] == "MYR"]
    payload = {"ok": True, "items": myr_only, "dataLimited": False, "recordLimit": 500}
    with _patch_view_api("operator_fr12.payments", MagicMock(return_value=_mock_response(payload))):
        resp = auth_client.get("/payments")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "MYR 1700.00 settled" in html
        assert "Multi-currency:" not in html


def test_package_payments_status_filter(auth_client):
    """Status filtering isolates matching payment states."""
    payload = {"ok": True, "items": SAMPLE_PAYMENTS, "dataLimited": False, "recordLimit": 500}
    with _patch_view_api("operator_fr12.payments", MagicMock(return_value=_mock_response(payload))):
        # Filter for paid
        resp_paid = auth_client.get("/payments?status=paid")
        html_paid = resp_paid.data.decode("utf-8")
        assert "TM-ORD-101" in html_paid
        assert "TM-ORD-104" not in html_paid

        # Filter for pending
        resp_pending = auth_client.get("/payments?status=pending")
        html_pending = resp_pending.data.decode("utf-8")
        assert "TM-ORD-104" in html_pending
        assert "TM-ORD-101" not in html_pending


def test_package_payments_search_query(auth_client):
    """Search query matches against orderReference and packageTitle."""
    payload = {"ok": True, "items": SAMPLE_PAYMENTS, "dataLimited": False, "recordLimit": 500}
    with _patch_view_api("operator_fr12.payments", MagicMock(return_value=_mock_response(payload))):
        resp = auth_client.get("/payments?q=foodie")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "TM-ORD-102" in html
        assert "TM-ORD-101" not in html


def test_package_payments_data_limited_disclosure(auth_client):
    """When dataLimited=True, the system displays the bounded scope notice."""
    payload = {"ok": True, "items": SAMPLE_PAYMENTS, "dataLimited": True, "recordLimit": 500}
    with _patch_view_api("operator_fr12.payments", MagicMock(return_value=_mock_response(payload))):
        resp = auth_client.get("/payments")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "Showing up to 500 records" in html
        assert "Totals cover loaded records only" in html


def test_package_payments_safe_booking_link(auth_client):
    """Each payment row contains a safe link to the booking details page."""
    payload = {"ok": True, "items": SAMPLE_PAYMENTS, "dataLimited": False, "recordLimit": 500}
    with _patch_view_api("operator_fr12.payments", MagicMock(return_value=_mock_response(payload))):
        resp = auth_client.get("/payments")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert 'href="/bookings/TM-ORD-101"' in html
        assert "View Booking" in html


def test_package_payments_empty_state(auth_client):
    """Empty result set renders clear empty state."""
    payload = {"ok": True, "items": [], "dataLimited": False, "recordLimit": 500}
    with _patch_view_api("operator_fr12.payments", MagicMock(return_value=_mock_response(payload))):
        resp = auth_client.get("/payments")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "No package payments found" in html


def test_package_payments_backend_outage(auth_client):
    """Backend service error displays honest error card without crashing."""
    with _patch_view_api("operator_fr12.payments", MagicMock(return_value=_mock_response({}, ok=False, status_code=503))):
        resp = auth_client.get("/payments")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "Payment Service Unavailable" in html
        assert "Retry Request" in html


def test_booking_detail_renders_paid_at(auth_client):
    """Booking detail page displays paidAt timestamp when present, and fallback when absent."""
    booking_with_paid = {
        "orderReference": "TM-ORD-101",
        "packageTitle": "Penang Escape",
        "groupTotal": 1250.00,
        "currency": "MYR",
        "paymentStatus": "paid",
        "isPaid": True,
        "testMode": True,
        "paidAt": "2026-11-01T10:15:00Z",
        "fulfillmentStatus": "trip_ready",
    }
    with _patch_view_api("operator_fr12.booking_detail", MagicMock(return_value=_mock_response({"ok": True, "booking": booking_with_paid}))):
        resp = auth_client.get("/bookings/TM-ORD-101")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "Paid At" in html
        assert "2026-11-01 10:15:00 UTC" in html

    booking_no_paid = {
        "orderReference": "TM-ORD-102",
        "packageTitle": "Foodie Trail",
        "groupTotal": 450.00,
        "currency": "MYR",
        "paymentStatus": "pending",
        "isPaid": False,
        "testMode": True,
        "paidAt": None,
        "fulfillmentStatus": "awaiting_operator_fulfillment",
    }
    with _patch_view_api("operator_fr12.booking_detail", MagicMock(return_value=_mock_response({"ok": True, "booking": booking_no_paid}))):
        resp = auth_client.get("/bookings/TM-ORD-102")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "Paid At" in html
        assert "Payment date unavailable" in html
