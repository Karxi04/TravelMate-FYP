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
    if "request_rate_limiter" in app.extensions:
        app.extensions["request_rate_limiter"].reset()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["id_token"] = "valid_admin_token"
            sess["portal_role"] = "admin"
            sess["admin_id"] = "admin_test_1"
        yield client


@pytest.fixture
def unauth_client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def _patch_admin_api(mock_fn):
    fn_globals = app.view_functions["admin_fr13.packages"].__globals__
    return patch.dict(fn_globals, {"call_api": mock_fn})


def test_01_admin_review_available_package_shows_approve_and_publish(auth_client):
    """Point 8: Admin approves an available package with 'Approve and publish' button and no unavailable warning."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "ok": True,
        "package": {
            "id": "pkg_rev_avail",
            "title": "Available Penang Discovery",
            "approvalStatus": "pending",
            "availabilityStatus": "available",
            "adultPrice": 180.0,
            "operatorName": "Penang Tours",
        },
    }

    with _patch_admin_api(MagicMock(return_value=mock_resp)):
        res = auth_client.get("/admin/packages/pkg_rev_avail")
        assert res.status_code == 200
        html = res.get_data(as_text=True)

        assert "Approve and publish" in html
        assert "This package will be approved but will remain hidden from travellers" not in html


def test_02_admin_review_unavailable_package_shows_approve_package_and_warning(auth_client):
    """Point 9: Admin approval of unavailable packages shows 'Approve package' button and warning notice."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "ok": True,
        "package": {
            "id": "pkg_rev_unavail",
            "title": "Unavailable Penang Excursion",
            "approvalStatus": "pending",
            "availabilityStatus": "unavailable",
            "adultPrice": 220.0,
            "operatorName": "Penang Tours",
        },
    }

    with _patch_admin_api(MagicMock(return_value=mock_resp)):
        res = auth_client.get("/admin/packages/pkg_rev_unavail")
        assert res.status_code == 200
        html = res.get_data(as_text=True)

        # Button must say 'Approve package', NOT 'Approve and publish'
        assert "Approve package" in html
        assert "Approve and publish" not in html

        # Warning notice must be prominently displayed
        assert "This package will be approved but will remain hidden from travellers because its availability is currently set to Unavailable. The operator must activate availability before it can appear in public discovery." in html


def test_03_admin_approval_endpoint_call(auth_client):
    """Point 8 & 13: Admin approval proxies decision='approved' to backend API."""
    mock_api = MagicMock()
    mock_api.return_value.ok = True
    mock_api.return_value.json.return_value = {
        "ok": True,
        "package": {"id": "pkg_rev_avail", "approvalStatus": "approved"},
    }

    with _patch_admin_api(mock_api):
        res = auth_client.post(
            "/admin/packages/pkg_rev_avail/review",
            data={"decision": "approved", "comment": "All criteria verified."},
        )
        assert res.status_code == 302
        call_kwargs = mock_api.call_args[1]
        sent_json = call_kwargs.get("json", {})
        assert sent_json.get("decision") == "approved"
        assert sent_json.get("comment") == "All criteria verified."


def test_04_admin_rejection_flow_intact(auth_client):
    """Point 13: Existing rejection flow remains intact."""
    mock_api = MagicMock()
    mock_api.return_value.ok = True
    mock_api.return_value.json.return_value = {
        "ok": True,
        "package": {"id": "pkg_rev_avail", "approvalStatus": "rejected"},
    }

    with _patch_admin_api(mock_api):
        res = auth_client.post(
            "/admin/packages/pkg_rev_avail/review",
            data={"decision": "rejected", "comment": "Please add full day 2 itinerary."},
        )
        assert res.status_code == 302
        call_kwargs = mock_api.call_args[1]
        sent_json = call_kwargs.get("json", {})
        assert sent_json.get("decision") == "rejected"
        assert sent_json.get("comment") == "Please add full day 2 itinerary."


def test_05_approved_unavailable_displays_approved_unavailable_in_queue_and_details(auth_client):
    """Point 10: Approved + unavailable displays 'Approved (Unavailable)' in queue and review."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "ok": True,
        "items": [{
            "id": "pkg_app_unavail",
            "title": "Approved But Paused Tour",
            "approvalStatus": "approved",
            "availabilityStatus": "unavailable",
            "adultPrice": 190.0,
            "operatorName": "Heritage Guides",
        }],
        "package": {
            "id": "pkg_app_unavail",
            "title": "Approved But Paused Tour",
            "approvalStatus": "approved",
            "availabilityStatus": "unavailable",
            "adultPrice": 190.0,
            "operatorName": "Heritage Guides",
        },
    }

    with _patch_admin_api(MagicMock(return_value=mock_resp)):
        # Check queue
        res_list = auth_client.get("/admin/packages")
        assert res_list.status_code == 200
        html_list = res_list.get_data(as_text=True)
        assert "Approved (Unavailable)" in html_list

        # Check details
        res_det = auth_client.get("/admin/packages/pkg_app_unavail")
        assert res_det.status_code == 200
        html_det = res_det.get_data(as_text=True)
        assert "Approved (Unavailable)" in html_det


def test_06_approved_unavailable_never_labeled_suspended(auth_client):
    """Point 11: Approved + unavailable is never labeled Suspended."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "ok": True,
        "items": [{
            "id": "pkg_app_unavail",
            "title": "Approved But Paused Tour",
            "approvalStatus": "approved",
            "availabilityStatus": "unavailable",
            "adultPrice": 190.0,
            "operatorName": "Heritage Guides",
        }],
        "package": {
            "id": "pkg_app_unavail",
            "title": "Approved But Paused Tour",
            "approvalStatus": "approved",
            "availabilityStatus": "unavailable",
            "adultPrice": 190.0,
            "operatorName": "Heritage Guides",
        },
    }

    with _patch_admin_api(MagicMock(return_value=mock_resp)):
        res = auth_client.get("/admin/packages/pkg_app_unavail")
        assert res.status_code == 200
        html = res.get_data(as_text=True)

        assert '<span class="status suspended">Suspended</span>' not in html
        assert "Package Suspended &amp; Unpublished" not in html
        assert "Package Suspended & Unpublished" not in html


def test_07_actual_suspended_packages_remain_labeled_suspended(auth_client):
    """Point 12: Actual suspended packages remain labeled Suspended."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "ok": True,
        "package": {
            "id": "pkg_susp",
            "title": "Suspended Heritage Tour",
            "approvalStatus": "suspended",
            "suspensionReason": "Safety violation reported by guests.",
            "suspendedAt": "2026-10-18T10:00:00Z",
            "suspendedByName": "Admin Chief",
            "adultPrice": 250.0,
            "operatorName": "Heritage Guides",
        },
    }

    with _patch_admin_api(MagicMock(return_value=mock_resp)):
        res = auth_client.get("/admin/packages/pkg_susp")
        assert res.status_code == 200
        html = res.get_data(as_text=True)

        assert '<span class="status suspended">Suspended</span>' in html
        assert "Safety violation reported by guests." in html
        assert "Suspended by Admin Chief on 2026-10-18" in html


def test_08_admin_auth_guard_intact(unauth_client):
    """Point 15: Admin authentication guard is intact."""
    res = unauth_client.get("/admin/packages")
    assert res.status_code == 302
    assert res.location in {"/", "/login", "http://localhost/", "http://localhost/login"}
