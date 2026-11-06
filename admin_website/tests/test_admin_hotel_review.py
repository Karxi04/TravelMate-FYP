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
def auth_client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["id_token"] = "valid_admin_token"
            sess["portal_role"] = "admin"
            sess["admin_id"] = "admin_test_1"
        yield c


def _mock_pkg_response(pkg, ok=True, status_code=200):
    mock = MagicMock()
    mock.ok = ok
    mock.status_code = status_code
    mock.json.return_value = {"package": pkg, "item": pkg}
    return mock


def _patch_admin_api(mock_fn):
    fn_globals = app.view_functions["admin_fr13.packages"].__globals__
    return patch.dict(fn_globals, {"call_api": mock_fn})


def test_admin_package_review_with_verified_hotel(auth_client):
    pkg_data = {
        "id": "pkg_admin_hotel_001",
        "title": "Penang Heritage Tour",
        "destination": "Penang",
        "approvalStatus": "pending",
        "accommodationName": "Eastern & Oriental Hotel",
        "accommodationCategory": "5-Star",
        "roomType": "Deluxe Heritage Suite",
        "accommodationNotes": "Early check-in upon request",
        "accommodationHotel": {
            "provider": "liteapi",
            "hotelId": "lp_e_and_o",
            "name": "Eastern & Oriental Hotel",
            "address": "10 Farquhar Street",
            "city": "George Town",
            "country": "MY",
            "stars": 5.0,
            "guestRating": 9.2,
            "mainPhoto": "https://example.com/e_and_o.jpg",
            "amenities": ["Free Wi-Fi", "Swimming Pool"],
            "reservationStatus": "not_created",
        },
    }

    mock_api = MagicMock(return_value=_mock_pkg_response(pkg_data))
    with _patch_admin_api(mock_api):
        response = auth_client.get("/admin/packages/pkg_admin_hotel_001")
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        assert "Accommodation Details" in html
        assert "Hotel Information from LiteAPI" in html
        assert ("Eastern &amp; Oriental Hotel" in html) or ("Eastern & Oriental Hotel" in html)
        assert "10 Farquhar Street, George Town, MY" in html
        assert "⭐ 5.0-Star" in html
        assert "Guest Rating: 9.2/10" in html
        assert "Free Wi-Fi" in html
        assert "Operator Arrangement Details:" in html
        assert "Deluxe Heritage Suite" in html
        assert "Early check-in upon request" in html
        assert "Hotel information is provided for package planning. Selecting a property does not create or confirm a room reservation." in html


def test_admin_package_review_with_null_stars_hotel(auth_client):
    pkg_data = {
        "id": "pkg_admin_null_stars",
        "title": "Boutique Getaway",
        "destination": "Penang",
        "approvalStatus": "pending",
        "accommodationHotel": {
            "provider": "liteapi",
            "hotelId": "lp_boutique",
            "name": "Muntri Heritage Villa",
            "address": "Muntri Street",
            "city": "George Town",
            "country": "MY",
            "stars": None,
            "guestRating": 8.7,
            "amenities": ["Wi-Fi"],
            "reservationStatus": "not_created",
        },
    }

    mock_api = MagicMock(return_value=_mock_pkg_response(pkg_data))
    with _patch_admin_api(mock_api):
        response = auth_client.get("/admin/packages/pkg_admin_null_stars")
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        assert "Accommodation Details" in html
        assert "Star classification not supplied" in html
        assert "Guest Rating: 8.7/10" in html
        assert "Standard Hotel" not in html


def test_admin_package_review_legacy_package_without_hotel(auth_client):
    pkg_data = {
        "id": "pkg_admin_legacy",
        "title": "Country Tour",
        "destination": "Cameron Highlands",
        "approvalStatus": "pending",
        "accommodationName": "Strawberry Park Resort",
        "accommodationCategory": "4-Star Resort",
        "roomType": "Standard Chalet",
        "accommodationNotes": "Breakfast included",
    }

    mock_api = MagicMock(return_value=_mock_pkg_response(pkg_data))
    with _patch_admin_api(mock_api):
        response = auth_client.get("/admin/packages/pkg_admin_legacy")
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        assert "Strawberry Park Resort" in html
        assert "4-Star Resort" in html
        assert "Standard Chalet" in html
        assert "Hotel Information from LiteAPI" not in html
