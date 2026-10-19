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


def _patch_operator_api(mock_fn):
    fn_globals = app.view_functions["operator_fr12.packages"].__globals__
    return patch.dict(fn_globals, {"call_api": mock_fn})


def test_scenario_13_operator_packages_filter_has_suspended(auth_client):
    """Scenario 13: Operator packages view includes 'suspended' filter option."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"ok": True, "items": []}

    with _patch_operator_api(MagicMock(return_value=mock_resp)):
        res = auth_client.get("/packages")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert '<option value="suspended"' in html
        assert "Suspended</option>" in html


def test_scenario_14_operator_packages_list_displays_suspended_badge_and_callout(auth_client):
    """Scenario 14: Operator packages list displays 'Suspended' badge and suspension callout with reason."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "ok": True,
        "items": [{
            "id": "pkg_op_susp",
            "title": "Penang Island Tour",
            "approvalStatus": "suspended",
            "suspensionReason": "Safety certification expired for van fleet",
            "adultPrice": 85.0,
            "availabilityStatus": "available",
        }],
    }

    with _patch_operator_api(MagicMock(return_value=mock_resp)):
        res = auth_client.get("/packages")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert 'class="status suspended"' in html
        assert "Suspended</span>" in html
        assert "Suspended by Administrator:" in html
        assert "Safety certification expired for van fleet" in html
        assert "This package is hidden from travellers" in html


def test_scenario_15_operator_packages_list_active_vs_paused(auth_client):
    """Scenario 15: Operator packages list displays 'Active in Catalog' vs 'Approved (Paused)'."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "ok": True,
        "items": [
            {
                "id": "pkg_active",
                "title": "Active Tour",
                "approvalStatus": "approved",
                "availabilityStatus": "available",
                "adultPrice": 100.0,
            },
            {
                "id": "pkg_paused",
                "title": "Paused Tour",
                "approvalStatus": "approved",
                "availabilityStatus": "unavailable",
                "adultPrice": 120.0,
            },
        ],
    }

    with _patch_operator_api(MagicMock(return_value=mock_resp)):
        res = auth_client.get("/packages")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert 'class="status approved"' in html
        assert "Active in Catalog</span>" in html
        assert 'class="status approved-unavailable"' in html
        assert "Approved (Paused)</span>" in html


def test_scenario_16_operator_packages_list_permits_edit_and_resubmit(auth_client):
    """Scenario 16: Operator packages list permits Edit and Resubmit for suspended packages."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "ok": True,
        "items": [{
            "id": "pkg_susp_actions",
            "title": "Suspended Expedition",
            "approvalStatus": "suspended",
            "adultPrice": 99.0,
        }],
    }

    with _patch_operator_api(MagicMock(return_value=mock_resp)):
        res = auth_client.get("/packages")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        # Edit link
        assert 'href="/packages/pkg_susp_actions/edit-page"' in html
        assert 'title="Edit package">Edit</a>' in html
        # Resubmit action
        assert 'action="/packages/pkg_susp_actions/submit"' in html
        assert 'type="submit">Resubmit</button>' in html


def test_scenario_17_operator_packages_list_excludes_delete_and_archive_for_suspended(auth_client):
    """Scenario 17: Operator packages list strictly EXCLUDES Delete, Archive, and direct publish for suspended."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "ok": True,
        "items": [{
            "id": "pkg_susp_nodelete",
            "title": "Suspended Expedition No Delete",
            "approvalStatus": "suspended",
            "adultPrice": 99.0,
        }],
    }

    with _patch_operator_api(MagicMock(return_value=mock_resp)):
        res = auth_client.get("/packages")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        # Delete action should NOT be present for suspended package
        assert 'action="/packages/pkg_susp_nodelete/delete"' not in html
        # Archive action should NOT be present for suspended package
        assert 'action="/packages/pkg_susp_nodelete/archive"' not in html


def test_scenario_18_operator_package_status_page_suspended(auth_client):
    """Scenario 18: Operator package status page displays suspended badge, reason notice, and Review & Edit."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "ok": True,
        "items": [{
            "id": "pkg_status_susp",
            "title": "Penang Food Trail",
            "approvalStatus": "suspended",
            "suspensionReason": "Hygiene inspection certificate update needed",
            "suspendedAt": "2026-10-18T12:00:00Z",
            "suspendedByName": "Compliance Admin",
        }],
    }

    with _patch_operator_api(MagicMock(return_value=mock_resp)):
        res = auth_client.get("/package-status")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert 'class="status suspended"' in html
        assert "Suspended</span>" in html
        assert "Administrator Suspension Notice:" in html
        assert "Hygiene inspection certificate update needed" in html
        assert "Suspended on 2026-10-18 by Compliance Admin" in html
        assert 'href="/packages/pkg_status_susp/edit-page"' in html
        assert "Review &amp; Edit" in html or "Review & Edit" in html


def test_scenario_19_operator_edit_package_page_suspension_banner(auth_client):
    """Scenario 19: Operator edit package page displays prominent red suspension warning banner."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "ok": True,
        "items": [{
            "id": "pkg_edit_susp",
            "title": "Bespoke Penang Escape",
            "approvalStatus": "suspended",
            "suspensionReason": "Missing licensed guide credentials",
            "suspendedAt": "2026-10-17T08:30:00Z",
            "suspendedByName": "Senior Admin Dave",
            "adultPrice": 300.0,
            "destination": "George Town",
        }],
    }

    with _patch_operator_api(MagicMock(return_value=mock_resp)):
        res = auth_client.get("/packages/pkg_edit_susp/edit-page")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "Package Suspended by Administrator" in html
        assert "Missing licensed guide credentials" in html
        assert "Suspended on 2026-10-17 by Senior Admin Dave" in html
        assert "This package is currently unpublished and inaccessible to travellers" in html
        # Step 2 explanatory card should also be present in the form
        assert "Catalog Availability vs Administrator Moderation" in html


def test_scenario_20_operator_dashboard_suspended_summary_and_attention(auth_client):
    """Scenario 20: Operator dashboard includes suspendedPackages count in summary and alert in attention panel."""
    mock_pkg_resp = MagicMock()
    mock_pkg_resp.ok = True
    mock_pkg_resp.json.return_value = {
        "ok": True,
        "items": [
            {
                "id": "pkg_dash_1",
                "title": "Suspended Trishaw Ride",
                "approvalStatus": "suspended",
                "suspensionReason": "Trishaw operator safety review pending",
            },
            {
                "id": "pkg_dash_2",
                "title": "Approved Street Art Walk",
                "approvalStatus": "approved",
            },
        ],
    }

    mock_camp_resp = MagicMock()
    mock_camp_resp.ok = True
    mock_camp_resp.json.return_value = {"ok": True, "items": []}

    mock_book_resp = MagicMock()
    mock_book_resp.ok = True
    mock_book_resp.json.return_value = {"ok": True, "items": []}

    mock_me_resp = MagicMock()
    mock_me_resp.ok = True
    mock_me_resp.json.return_value = {"ok": True, "profile": {"name": "Test Operator"}}

    def mock_call_api(method, path, *args, **kwargs):
        if "/packages" in path:
            return mock_pkg_resp
        if "/campaigns" in path:
            return mock_camp_resp
        if "/bookings" in path:
            return mock_book_resp
        if "/me" in path:
            return mock_me_resp
        m = MagicMock()
        m.ok = True
        m.json.return_value = {}
        return m

    with _patch_operator_api(mock_call_api):
        res = auth_client.get("/dashboard")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        # Attention item
        assert "Package suspended by Admin" in html
        assert "Trishaw operator safety review pending" in html
        assert 'href="/packages/pkg_dash_1/edit-page"' in html
        assert 'class="status suspended">Package suspended by Admin</span>' in html
