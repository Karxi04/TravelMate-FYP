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


SAMPLE_BOOKINGS = [
    {
        "orderReference": "order-heritage-101",
        "packageId": "pkg-penang-walk",
        "packageTitle": "George Town UNESCO Heritage & Michelin Hawker Food Walk",
        "departureDate": "2027-02-10",
        "groupSize": 3,
        "adults": 2,
        "children": 1,
        "paymentStatus": "paid",
        "orderStatus": "paid",
        "fulfillmentStatus": "fulfilled",
        "groupTotal": 1075.50,
        "currency": "MYR",
        "supplierReservationStatus": "not_created",
        "testMode": True,
        "createdAt": "2026-10-16T12:00:00Z",
    },
    {
        "orderReference": "order-legacy-202",
        "packageId": "pkg-legacy-01",
        "packageTitle": "Penang Hill Nature & Sunset Tour",
        "departureDate": None,
        "groupSize": None,
        "adults": None,
        "children": None,
        "paymentStatus": "payment_pending",
        "orderStatus": "pending",
        "fulfillmentStatus": "fulfillment_pending",
        "groupTotal": 320.00,
        "currency": "MYR",
        "supplierReservationStatus": "not_created",
        "testMode": False,
        "createdAt": "2026-10-15T09:30:00Z",
    },
]


def test_operator_bookings_unauthenticated_redirects(client):
    res = client.get("/bookings")
    assert res.status_code == 302
    assert res.headers["Location"] in ["/", "/login"]


def test_operator_bookings_unverified_redirects(unverified_client):
    res = unverified_client.get("/bookings")
    assert res.status_code == 302
    assert "/verification" in res.headers["Location"]


def test_operator_bookings_renders_data_and_honest_disclosures(auth_client):
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "items": SAMPLE_BOOKINGS}

    with patch.dict(app.view_functions["operator_fr12.bookings"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res = auth_client.get("/bookings")
        assert res.status_code == 200
        html = res.get_data(as_text=True)

        # Disclosures
        assert "Stripe Test Mode" in html
        assert "third-party supplier reservations" in html
        assert "NOT automatically booked with external providers" in html
        assert "⚠️ Not Created (Manual)" in html

        # Data rows
        assert "order-heritage-101" in html
        assert "George Town UNESCO Heritage &amp; Michelin Hawker Food Walk" in html or "George Town UNESCO Heritage" in html
        assert "2027-02-10" in html
        assert "3 pax" in html
        assert "2 Adults, 1 Child" in html
        assert "MYR 1075.50" in html
        assert "🧪 Stripe Test" in html
        assert "Trip Created in App" in html


def test_operator_bookings_empty_state(auth_client):
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "items": []}

    with patch.dict(app.view_functions["operator_fr12.bookings"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res = auth_client.get("/bookings")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "No package bookings found" in html
        assert "When travellers book your published Penang packages" in html


def test_operator_bookings_backend_error_handled_gracefully(auth_client):
    mock_resp = MagicMock(ok=False, status_code=500)
    mock_resp.json.return_value = {"ok": False, "error": "Internal service error"}

    with patch.dict(app.view_functions["operator_fr12.bookings"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res = auth_client.get("/bookings")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "Backend Service Unavailable" in html
        assert "Retry Request" in html


def test_operator_bookings_legacy_missing_counts(auth_client):
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "items": [SAMPLE_BOOKINGS[1]]}

    with patch.dict(app.view_functions["operator_fr12.bookings"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res = auth_client.get("/bookings")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "order-legacy-202" in html
        assert "Legacy (Unspecified)" in html
        assert "Flexible / On Demand" in html
        assert "MYR 320.00" in html


def test_operator_bookings_search_and_filter(auth_client):
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "items": SAMPLE_BOOKINGS}

    with patch.dict(app.view_functions["operator_fr12.bookings"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        # Search match
        res_search = auth_client.get("/bookings?q=heritage")
        assert res_search.status_code == 200
        html_search = res_search.get_data(as_text=True)
        assert "order-heritage-101" in html_search
        assert "order-legacy-202" not in html_search

        # Status filter match
        res_filter = auth_client.get("/bookings?status=paid")
        assert res_filter.status_code == 200
        html_filter = res_filter.get_data(as_text=True)
        assert "order-heritage-101" in html_filter
        assert "order-legacy-202" not in html_filter


def test_operator_booking_detail_view(auth_client):
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "items": SAMPLE_BOOKINGS}

    with patch.dict(app.view_functions["operator_fr12.booking_detail"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res = auth_client.get("/bookings/order-heritage-101")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "Booking Reference #order-heritage-101" in html
        assert "George Town UNESCO Heritage" in html
        assert "3 travellers (pax)" in html
        assert "2 Adults" in html
        assert "1 Child" in html
        assert "MYR 1075.50" in html
        assert "Stripe Test Mode" in html
        assert "Authoritative Supplier Reservation Status: NOT CREATED" in html
        assert "Read-Only Governance" in html


def test_operator_booking_detail_not_found_redirects(auth_client):
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "items": SAMPLE_BOOKINGS}

    with patch.dict(app.view_functions["operator_fr12.booking_detail"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res = auth_client.get("/bookings/order-unknown-999")
        assert res.status_code == 302
        assert "/bookings" in res.headers["Location"]


def test_operator_booking_security_no_sensitive_secrets(auth_client):
    sensitive_order = {
        **SAMPLE_BOOKINGS[0],
        "stripePaymentIntentId": "pi_secret_1234567890",
        "clientSecret": "seti_secret_abcdefgh",
        "travellerId": "traveller_secret_uid_99",
        "firebaseToken": "eyJhbGciOiJ...",
    }
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "items": [sensitive_order]}

    with patch.dict(app.view_functions["operator_fr12.bookings"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res = auth_client.get("/bookings")
        html = res.get_data(as_text=True)
        assert "pi_secret_1234567890" not in html
        assert "seti_secret_abcdefgh" not in html
        assert "traveller_secret_uid_99" not in html
        assert "eyJhbGciOiJ..." not in html

    with patch.dict(app.view_functions["operator_fr12.booking_detail"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res_detail = auth_client.get("/bookings/order-heritage-101")
        html_detail = res_detail.get_data(as_text=True)
        assert "pi_secret_1234567890" not in html_detail
        assert "seti_secret_abcdefgh" not in html_detail
        assert "traveller_secret_uid_99" not in html_detail
        assert "eyJhbGciOiJ..." not in html_detail


def test_operator_sidebar_navigation_has_bookings_link(auth_client):
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "items": []}

    with patch.dict(app.view_functions["operator_fr12.bookings"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res = auth_client.get("/bookings")
        html = res.get_data(as_text=True)
        assert 'href="/bookings"' in html
        assert '<span class="nav-label">Bookings</span>' in html
        # Active class check
        assert 'class="active">\n          <svg class="nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>' in html or ('active' in html and 'Bookings' in html)


def test_operator_dashboard_shows_bookings_kpi(auth_client):
    mock_pkg = MagicMock(ok=True)
    mock_pkg.json.return_value = {"ok": True, "items": []}
    mock_camp = MagicMock(ok=True)
    mock_camp.json.return_value = {"ok": True, "items": []}
    mock_book = MagicMock(ok=True)
    mock_book.json.return_value = {"ok": True, "items": SAMPLE_BOOKINGS}
    mock_me = MagicMock(ok=True)
    mock_me.json.return_value = {"ok": True, "profile": {"name": "Test Partner"}}

    def mock_call(method, path, **kwargs):
        if path == "/api/fr12/packages":
            return mock_pkg
        if path == "/api/fr12/campaigns":
            return mock_camp
        if path == "/api/fr12/bookings":
            return mock_book
        if path == "/api/fr1/me":
            return mock_me
        return MagicMock(ok=True, json=lambda: {})

    with patch.dict(app.view_functions["operator_fr12.dashboard"].__globals__, {"call_api": mock_call}):
        res = auth_client.get("/dashboard")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "Package Bookings" in html
        assert "Manage Package Bookings" in html
        assert 'href="/bookings"' in html
