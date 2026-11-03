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
def auth_client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    if "request_rate_limiter" in app.extensions:
        app.extensions["request_rate_limiter"].reset()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["id_token"] = "valid_test_op_token"
            sess["portal_role"] = "operator"
            sess["verification_status"] = "approved"
            sess["operator_id"] = "op_test_1"
        yield client


@pytest.fixture
def unauth_client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


@pytest.fixture
def unverified_client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["id_token"] = "valid_test_op_token"
            sess["portal_role"] = "operator"
            sess["verification_status"] = "pending"
            sess["operator_id"] = "op_test_pending"
        yield client


def _patch_op_api(mock_fn):
    fn_globals = app.view_functions["operator_fr12.packages"].__globals__
    return patch.dict(fn_globals, {"call_api": mock_fn})


def _mock_res(json_data, status_code=200, headers=None):
    res = MagicMock()
    res.ok = 200 <= status_code < 300
    res.status_code = status_code
    res.json.return_value = json_data
    res.headers = headers or {}
    return res


# -------------------------------------------------------------------------
# PROXY TESTS
# -------------------------------------------------------------------------

def test_search_hotels_proxy_unauthorized(unauth_client):
    response = unauth_client.get("/hotels/search?countryCode=MY&cityName=George%20Town")
    assert response.status_code == 401
    assert response.get_json()["ok"] is False
    assert response.get_json()["error"] == "Unauthorized"


def test_search_hotels_proxy_unverified(unverified_client):
    response = unverified_client.get("/hotels/search?countryCode=MY&cityName=George%20Town")
    assert response.status_code == 403
    assert response.get_json()["ok"] is False


def test_search_hotels_proxy_success(auth_client):
    backend_payload = {
        "ok": True,
        "items": [
            {
                "hotelId": "lp_e_and_o",
                "name": "Eastern & Oriental Hotel",
                "address": "10 Farquhar Street",
                "city": "George Town",
                "country": "MY",
                "stars": 5.0,
                "guestRating": 9.2,
                "mainPhoto": "https://example.com/e_and_o.jpg",
                "amenities": ["Free Wi-Fi", "Swimming Pool"],
            }
        ],
        "limit": 10,
        "offset": 0,
        "hasMore": False,
        "source": "liteapi_property_content",
    }
    mock_api = MagicMock(return_value=_mock_res(backend_payload))
    with _patch_op_api(mock_api):
        response = auth_client.get("/hotels/search?countryCode=MY&cityName=George%20Town&limit=10&offset=0")
        assert response.status_code == 200
        data = response.get_json()
        assert data["ok"] is True
        assert len(data["items"]) == 1
        assert data["items"][0]["hotelId"] == "lp_e_and_o"

        # Verify call_api forwarded args
        mock_api.assert_called_once()
        args, kwargs = mock_api.call_args
        assert args[0] == "GET"
        assert args[1] == "/api/fr12/hotels/search"
        assert kwargs["params"].get("countryCode") == "MY"
        assert kwargs["params"].get("cityName") == "George Town"


def test_search_hotels_proxy_rate_limited(auth_client):
    mock_api = MagicMock(return_value=_mock_res(
        {"ok": False, "error": "Rate limit exceeded. Please wait.", "code": "hotel_provider_rate_limit"},
        status_code=429,
        headers={"Retry-After": "60"},
    ))
    with _patch_op_api(mock_api):
        response = auth_client.get("/hotels/search?countryCode=MY&cityName=George%20Town")
        assert response.status_code == 429
        assert response.headers.get("Retry-After") == "60"
        data = response.get_json()
        assert data["ok"] is False


def test_search_hotels_proxy_upstream_error(auth_client):
    mock_api = MagicMock(return_value=_mock_res(
        {"ok": False, "error": "Hotel provider is temporarily unavailable.", "code": "hotel_provider_unavailable"},
        status_code=502,
    ))
    with _patch_op_api(mock_api):
        response = auth_client.get("/hotels/search?countryCode=MY&cityName=George%20Town")
        assert response.status_code == 502
        data = response.get_json()
        assert data["ok"] is False


def test_hotel_detail_proxy_unauthorized_and_success(unauth_client, auth_client):
    # Unauth
    unauth_res = unauth_client.get("/hotels/lp_e_and_o")
    assert unauth_res.status_code == 401

    # Auth
    mock_hotel = {
        "ok": True,
        "hotel": {
            "hotelId": "lp_e_and_o",
            "name": "Eastern & Oriental Hotel",
            "stars": 5.0,
            "guestRating": 9.2,
        },
        "availabilityChecked": False,
    }
    mock_api = MagicMock(return_value=_mock_res(mock_hotel))
    with _patch_op_api(mock_api):
        res = auth_client.get("/hotels/lp_e_and_o")
        assert res.status_code == 200
        assert res.get_json()["hotel"]["name"] == "Eastern & Oriental Hotel"
        mock_api.assert_called_once_with("GET", "/api/fr12/hotels/lp_e_and_o")


# -------------------------------------------------------------------------
# PACKAGE HOTEL PERSISTENCE TESTS (SELECT, DETACH, KEEP)
# -------------------------------------------------------------------------

def test_package_create_with_hotel_selection_select(auth_client):
    form_data = {
        "title": "Penang Heritage Tour",
        "shortDescription": "UNESCO George Town exploration",
        "fullDescription": "A guided cultural and culinary excursion.",
        "destination": "George Town, Penang",
        "durationDays": "3",
        "durationNights": "2",
        "adultPrice": "450.0",
        "hotelSelectionAction": "select",
        "hotelSelectionId": "lp_e_and_o",
        "hotelSelectionProvider": "liteapi",
        "accommodationName": "Eastern & Oriental Hotel",
        "accommodationCategory": "5-Star",
        "roomType": "Heritage Suite",
        "accommodationNotes": "Late check-out on request",
    }

    created_pkg = {"id": "pkg_new_123", "approvalStatus": "draft"}
    mock_api = MagicMock(return_value=_mock_res({"ok": True, "id": "pkg_new_123", "package": created_pkg}, status_code=201))
    with _patch_op_api(mock_api):
        response = auth_client.post("/packages/new", data=form_data, follow_redirects=True)
        assert response.status_code == 200

        assert mock_api.call_count >= 1
        method, endpoint = mock_api.call_args_list[0][0][:2]
        payload = mock_api.call_args_list[0][1]["json"]

        assert method == "POST"
        assert endpoint == "/api/fr12/packages"
        # Must have hotelSelection
        assert payload.get("hotelSelection") == {"provider": "liteapi", "hotelId": "lp_e_and_o"}
        # Must NOT submit accommodationHotel
        assert "accommodationHotel" not in payload
        assert payload.get("accommodationName") == "Eastern & Oriental Hotel"


def test_package_edit_with_hotel_selection_detach(auth_client):
    form_data = {
        "title": "Penang Heritage Tour Edited",
        "shortDescription": "UNESCO George Town exploration",
        "fullDescription": "A guided cultural and culinary excursion.",
        "destination": "George Town, Penang",
        "durationDays": "3",
        "adultPrice": "450.0",
        "hotelSelectionAction": "detach",
        "hotelSelectionId": "",
        "accommodationName": "Local Heritage Homestay",
        "accommodationCategory": "Homestay",
        "roomType": "Double Room",
    }

    updated_pkg = {"id": "pkg_edit_123", "approvalStatus": "draft"}
    mock_api = MagicMock(return_value=_mock_res({"ok": True, "package": updated_pkg}))
    with _patch_op_api(mock_api):
        response = auth_client.post("/packages/pkg_edit_123/edit", data=form_data, follow_redirects=True)
        assert response.status_code == 200

        assert mock_api.call_count >= 1
        method, endpoint = mock_api.call_args_list[0][0][:2]
        payload = mock_api.call_args_list[0][1]["json"]

        assert method == "PUT"
        assert endpoint == "/api/fr12/packages/pkg_edit_123"
        # Must submit explicit null hotelSelection to detach
        assert "hotelSelection" in payload
        assert payload["hotelSelection"] is None
        assert "accommodationHotel" not in payload
        assert payload.get("accommodationName") == "Local Heritage Homestay"


def test_package_edit_with_hotel_selection_keep(auth_client):
    form_data = {
        "title": "Penang Heritage Tour Untouched Hotel",
        "shortDescription": "UNESCO George Town exploration",
        "fullDescription": "A guided cultural and culinary excursion.",
        "destination": "George Town, Penang",
        "durationDays": "3",
        "adultPrice": "450.0",
        "hotelSelectionAction": "",  # Empty action = keep existing
        "hotelSelectionId": "lp_e_and_o",
        "accommodationName": "Eastern & Oriental Hotel",
        "accommodationCategory": "5-Star",
    }

    updated_pkg = {"id": "pkg_edit_456", "approvalStatus": "draft"}
    mock_api = MagicMock(return_value=_mock_res({"ok": True, "package": updated_pkg}))
    with _patch_op_api(mock_api):
        response = auth_client.post("/packages/pkg_edit_456/edit", data=form_data, follow_redirects=True)
        assert response.status_code == 200

        assert mock_api.call_count >= 1
        payload = mock_api.call_args_list[0][1]["json"]
        # hotelSelection must be omitted
        assert "hotelSelection" not in payload
        assert "accommodationHotel" not in payload


def test_package_edit_409_conflict_and_rereview_flash(auth_client):
    # 1. 409 Conflict
    mock_api_409 = MagicMock(return_value=_mock_res(
        {"ok": False, "error": "This package was modified by another user or review action. Please reload and review changes."},
        status_code=409,
    ))
    with _patch_op_api(mock_api_409):
        # Package edit page loads listing first then posts
        with patch.dict(app.view_functions["operator_fr12.packages"].__globals__, {
            "call_api": MagicMock(side_effect=[
                _mock_res({"items": [{"id": "pkg_conf", "approvalStatus": "approved"}]}),
                _mock_res({"ok": False, "error": "This package was modified by another user or review action. Please reload and review changes."}, status_code=409),
            ])
        }):
            res = auth_client.post("/packages/pkg_conf/edit-page", data={"title": "Test"}, follow_redirects=True)
            assert res.status_code == 200
            html = res.get_data(as_text=True)
            assert "This package was modified by another review action or user" in html

    # 2. Approved package reverts to draft on content update
    with patch.dict(app.view_functions["operator_fr12.packages"].__globals__, {
        "call_api": MagicMock(side_effect=[
            _mock_res({"items": [{"id": "pkg_app", "approvalStatus": "approved"}]}),
            _mock_res({"ok": True, "package": {"id": "pkg_app", "approvalStatus": "draft"}}),
            _mock_res({"items": [{"id": "pkg_app", "approvalStatus": "draft"}]}),
        ])
    }):
        res2 = auth_client.post("/packages/pkg_app/edit-page", data={"title": "Test Approved Reverted"}, follow_redirects=True)
        assert res2.status_code == 200
        html2 = res2.get_data(as_text=True)
        assert "require administrator re-approval" in html2 or "returned to Draft status" in html2


# -------------------------------------------------------------------------
# TEMPLATE RENDERING TESTS
# -------------------------------------------------------------------------

def test_package_form_template_rendering_modes_and_preview(auth_client):
    # 1. New package form renders Mode A and Mode B
    res_new = auth_client.get("/packages/new")
    assert res_new.status_code == 200
    html_new = res_new.get_data(as_text=True)
    assert "Search Hotel API (LiteAPI)" in html_new
    assert "Manual Accommodation" in html_new
    assert "hotelSelectionAction" in html_new
    assert "hotelSelectionId" in html_new
    assert "hotelSelectionProvider" in html_new

    # 2. Edit package form with verified hotel (null stars) renders "Star classification not supplied"
    pkg_item = {
        "id": "pkg_edit_tmpl",
        "title": "Boutique Tour",
        "destination": "Penang",
        "approvalStatus": "draft",
        "durationNights": 2,
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
    with patch.dict(app.view_functions["operator_fr12.packages"].__globals__, {
        "call_api": MagicMock(return_value=_mock_res({"items": [pkg_item]}))
    }):
        res_edit = auth_client.get("/packages/pkg_edit_tmpl/edit-page")
        assert res_edit.status_code == 200
        html_edit = res_edit.get_data(as_text=True)

        assert "Muntri Heritage Villa" in html_edit
        assert "Star classification not supplied" in html_edit
        assert "Guest Rating: 8.7/10" in html_edit
        assert "Specifies package partner hotel. Does not constitute a room reservation." in html_edit
        # Must not show legacy "Standard" fallback for category
        assert "Standard Hotel" not in html_edit
