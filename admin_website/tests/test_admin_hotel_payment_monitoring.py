import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

ROOT = Path(__file__).resolve().parents[2]
ADMIN_DIR = ROOT / "admin_website"
OP_DIR = ROOT / "operator_website"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
while str(OP_DIR) in sys.path:
    sys.path.remove(str(OP_DIR))
if str(ADMIN_DIR) not in sys.path:
    sys.path.insert(0, str(ADMIN_DIR))

for k in list(sys.modules.keys()):
    if k == "modules" or k.startswith("modules."):
        del sys.modules[k]

from admin_website.app import app


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
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["id_token"] = "valid_admin_token"
            sess["portal_role"] = "admin"
            sess["admin_id"] = "admin_test_1"
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


SAMPLE_HOTEL_PAYMENTS = [
    {
        "id": "pay_hotel_01",
        "transactionReference": "pi_sim_hotel_001",
        "bookingId": "bk_hotel_001",
        "productType": "hotel",
        "productTitle": "bk_hotel_001",
        "quoteType": "hotel",
        "travellerId": "traveller_alpha",
        "amount": 450.00,
        "currency": "MYR",
        "paymentStatus": "paid",
        "isPaid": True,
        "testMode": True,
        "paidAt": "2026-11-01T12:00:00Z",
        "createdAt": "2026-11-01T11:50:00Z",
        "quoteSnapshot": {
            "hotelId": "hotel_penang_eo",
            "name": "Eastern & Oriental Luxury Suite",
            "checkIn": "2026-12-01",
            "checkOut": "2026-12-03",
        },
        "fulfillmentStatus": "demo_only",
        "supplierBookingStatus": "not_created",
    },
    {
        "id": "pay_hotel_02",
        "transactionReference": "pi_sim_hotel_002",
        "bookingId": "bk_hotel_002",
        "productType": "hotel",
        "productTitle": "bk_hotel_002",
        "quoteType": "hotel",
        "travellerId": "traveller_beta",
        "amount": 280.00,
        "currency": "MYR",
        "paymentStatus": "paid",
        "isPaid": True,
        "testMode": True,
        "paidAt": "2026-11-02T14:20:00Z",
        "createdAt": "2026-11-02T14:00:00Z",
        "quoteSnapshot": {},  # Missing quoteSnapshot data
        "fulfillmentStatus": "demo_only",
        "supplierBookingStatus": "not_created",
    },
]

SAMPLE_ALL_PAYMENTS = [
    SAMPLE_HOTEL_PAYMENTS[0],
    {
        "id": "pay_pkg_01",
        "transactionReference": "pi_sim_pkg_001",
        "productType": "package",
        "productTitle": "Heritage Island Discovery",
        "travellerId": "traveller_gamma",
        "amount": 1200.00,
        "currency": "MYR",
        "paymentStatus": "paid",
        "isPaid": True,
        "testMode": True,
        "createdAt": "2026-11-02T10:00:00Z",
        "fulfillmentStatus": "trip_ready",
        "supplierBookingStatus": "operator_attested",
    },
    {
        "id": "pay_flight_01",
        "transactionReference": "pi_sim_flt_001",
        "productType": "flight",
        "productTitle": "KUL-PEN Flight",
        "travellerId": "traveller_delta",
        "amount": 350.00,
        "currency": "MYR",
        "paymentStatus": "pending",
        "isPaid": False,
        "testMode": True,
        "createdAt": "2026-11-03T07:00:00Z",
        "fulfillmentStatus": "unconfirmed",
        "supplierBookingStatus": "not_created",
    },
]


def test_admin_payments_auth_guard(client):
    """Unauthenticated access to /admin/payments redirects to login."""
    resp = client.get("/admin/payments")
    assert resp.status_code == 302
    assert resp.headers.get("Location") in ["/", "/login", "/admin/login"]


def test_admin_hotel_payments_audit_banner_and_tabs(auth_client):
    """Accessing /admin/payments?product=hotel displays quick filter tabs and Hotel Audit banner."""
    payload = {"ok": True, "items": SAMPLE_HOTEL_PAYMENTS, "dataLimited": False, "recordLimit": 500}
    with _patch_view_api("admin_fr13.payments", MagicMock(return_value=_mock_response(payload))):
        resp = auth_client.get("/admin/payments?product=hotel")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        # Quick tabs
        assert "Hotel Payments" in html
        assert "Package Payments" in html
        assert "Flight Payments" in html
        assert "All Products" in html
        # Hotel Audit Banner
        assert "Hotel Payment Audit &amp; Third-Party Logistics Decoupling" not in html
        assert ">Environment<" not in html
        assert "Copy reference" in html
        assert "Hotel Reservation" in html


def test_admin_hotel_payments_property_and_stay_dates(auth_client):
    """Hotel property name and stay dates from quoteSnapshot render correctly."""
    payload = {"ok": True, "items": SAMPLE_HOTEL_PAYMENTS, "dataLimited": False, "recordLimit": 500}
    with _patch_view_api("admin_fr13.payments", MagicMock(return_value=_mock_response(payload))):
        resp = auth_client.get("/admin/payments?product=hotel")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        # First hotel
        assert "Eastern &amp; Oriental Luxury Suite" in html or "Eastern & Oriental Luxury Suite" in html
        assert "ID: hotel_penang_eo" in html
        assert "2026-12-01 to 2026-12-03" in html


def test_admin_hotel_payments_missing_info_fallbacks(auth_client):
    """Missing hotel name or stay dates fall back cleanly without inventing data."""
    payload = {"ok": True, "items": SAMPLE_HOTEL_PAYMENTS, "dataLimited": False, "recordLimit": 500}
    with _patch_view_api("admin_fr13.payments", MagicMock(return_value=_mock_response(payload))):
        resp = auth_client.get("/admin/payments?product=hotel")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        # Second hotel has empty quoteSnapshot
        assert "Hotel information unavailable" in html
        assert "Stay dates not recorded" in html


def test_admin_hotel_payments_payment_vs_reservation_separation(auth_client):
    """Payment status and Hotel Reservation status are kept strictly separate."""
    payload = {"ok": True, "items": SAMPLE_HOTEL_PAYMENTS, "dataLimited": False, "recordLimit": 500}
    with _patch_view_api("admin_fr13.payments", MagicMock(return_value=_mock_response(payload))):
        resp = auth_client.get("/admin/payments?product=hotel")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        # Paid status
        assert "Paid" in html
        assert "Stripe Test Mode" in html
        # Reservation status is unconfirmed
        assert "⚠️ Not Confirmed" in html
        # Must not claim confirmed hotel reservation
        assert "Confirmed Hotel Reservation" not in html


def test_admin_hotel_payments_read_only_modal(auth_client):
    """Each row includes a View Details button opening a read-only modal dialog."""
    payload = {"ok": True, "items": SAMPLE_HOTEL_PAYMENTS, "dataLimited": False, "recordLimit": 500}
    with _patch_view_api("admin_fr13.payments", MagicMock(return_value=_mock_response(payload))):
        resp = auth_client.get("/admin/payments?product=hotel")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "View Details" in html
        assert "<dialog" in html
        assert "Payment Transaction Details" in html
        assert "Read-Only Audit Interface" in html
        assert "No payment alterations, refunds, or external hotel reservations can be created" in html


def test_admin_all_products_payments_preserved(auth_client):
    """The default /admin/payments view preserves all products without regressions."""
    payload = {"ok": True, "items": SAMPLE_ALL_PAYMENTS, "dataLimited": False, "recordLimit": 500}
    with _patch_view_api("admin_fr13.payments", MagicMock(return_value=_mock_response(payload))):
        resp = auth_client.get("/admin/payments")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        # All products present
        assert "Hotel" in html
        assert "Package" in html
        assert "Flight" in html
        assert "pi_sim_hotel_001" in html
        assert "pi_sim_pkg_001" in html
        assert "pi_sim_flt_001" in html
        # Audit banner should NOT show on all products view
        assert "Hotel Payment Audit &amp; Third-Party Logistics Decoupling" not in html


def test_admin_payments_data_limited_notice(auth_client):
    """When dataLimited=True, _admin_data_state notice banner is rendered."""
    payload = {"ok": True, "items": SAMPLE_HOTEL_PAYMENTS, "dataLimited": True, "recordLimit": 500}
    with _patch_view_api("admin_fr13.payments", MagicMock(return_value=_mock_response(payload))):
        resp = auth_client.get("/admin/payments?product=hotel")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "Partial results: up to 500 records per source category are loaded" in html


def test_admin_payments_backend_outage(auth_client):
    """When backend API is unavailable, service-unavailable-card is displayed cleanly."""
    with _patch_view_api("admin_fr13.payments", MagicMock(return_value=_mock_response({}, ok=False, status_code=503))):
        resp = auth_client.get("/admin/payments")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "Administrator data is temporarily unavailable" in html
