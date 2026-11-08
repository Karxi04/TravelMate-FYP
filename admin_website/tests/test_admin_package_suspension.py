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


def test_scenario_01_admin_packages_filter_has_suspended(auth_client):
    """Scenario 1: Admin packages view includes 'suspended' filter option."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"ok": True, "items": []}

    with _patch_admin_api(MagicMock(return_value=mock_resp)):
        res = auth_client.get("/admin/packages")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert '<option value="suspended"' in html
        assert 'Suspended</option>' in html
        assert '<option value="draft"' not in html
        assert '<option value="archived"' not in html


def test_scenario_02_admin_packages_list_displays_suspended_badge(auth_client):
    """Scenario 2: Admin packages list displays 'Suspended' status badge for suspended packages."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "ok": True,
        "items": [{
            "id": "pkg_susp_1",
            "title": "Georgetown Heritage Walk",
            "approvalStatus": "suspended",
            "suspensionReason": "Safety concern raised regarding guide accreditation",
            "suspendedAt": "2026-10-18T10:00:00Z",
            "adultPrice": 120.0,
        }],
    }

    with _patch_admin_api(MagicMock(return_value=mock_resp)):
        res = auth_client.get("/admin/packages")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert 'class="status suspended"' in html
        assert "Suspended</span>" in html


def test_scenario_03_admin_packages_list_displays_approved_unavailable(auth_client):
    """Scenario 3: Admin packages list displays 'Approved (Unavailable)' when approved but unavailable."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "ok": True,
        "items": [{
            "id": "pkg_appr_unavail",
            "title": "Penang Hill Nature Trek",
            "approvalStatus": "approved",
            "availabilityStatus": "unavailable",
            "adultPrice": 150.0,
        }],
    }

    with _patch_admin_api(MagicMock(return_value=mock_resp)):
        res = auth_client.get("/admin/packages")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert 'class="status approved-unavailable"' in html
        assert "Approved (Unavailable)</span>" in html


def test_scenario_04_admin_packages_list_displays_published_when_available(auth_client):
    """Scenario 4: Admin packages list displays 'Published' when approved and available."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "ok": True,
        "items": [{
            "id": "pkg_appr_avail",
            "title": "Batu Ferringhi Water Sports",
            "approvalStatus": "approved",
            "availabilityStatus": "available",
            "adultPrice": 200.0,
        }],
    }

    with _patch_admin_api(MagicMock(return_value=mock_resp)):
        res = auth_client.get("/admin/packages")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert 'class="status approved"' in html
        assert "Published</span>" in html


def test_scenario_05_admin_packages_list_shows_suspended_date(auth_client):
    """Scenario 5: Admin packages list shows suspended date in submitted/reviewed column."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "ok": True,
        "items": [{
            "id": "pkg_susp_date",
            "title": "Balik Pulau Cycling Tour",
            "approvalStatus": "suspended",
            "suspendedAt": "2026-10-18T14:30:00Z",
            "adultPrice": 90.0,
        }],
    }

    with _patch_admin_api(MagicMock(return_value=mock_resp)):
        res = auth_client.get("/admin/packages")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "Suspended 2026-10-18" in html


def test_scenario_06_suspend_button_only_on_approved_packages(auth_client):
    """Scenario 6: Admin review page shows 'Suspend / Unpublish Package' button ONLY for approved packages."""
    mock_api = MagicMock()

    # Case A: Approved package -> button is visible
    mock_api.return_value.ok = True
    mock_api.return_value.json.return_value = {
        "ok": True,
        "package": {
            "id": "pkg_approved_100",
            "title": "Approved Penang Discovery",
            "approvalStatus": "approved",
            "availabilityStatus": "available",
            "adultPrice": 100.0,
        },
    }
    with _patch_admin_api(mock_api):
        res = auth_client.get("/admin/packages/pkg_approved_100")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "Suspend / Unpublish Package" in html
        assert 'id="openSuspendModalBtn"' in html

    # Case B: Pending package -> no suspend button
    mock_api.return_value.json.return_value = {
        "ok": True,
        "package": {
            "id": "pkg_pending_100",
            "title": "Pending Penang Discovery",
            "approvalStatus": "pending",
            "adultPrice": 100.0,
        },
    }
    with _patch_admin_api(mock_api):
        res = auth_client.get("/admin/packages/pkg_pending_100")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "Suspend / Unpublish Package" not in html
        assert 'id="openSuspendModalBtn"' not in html

    # Case C: Suspended package -> no suspend button, but suspension alert box
    mock_api.return_value.json.return_value = {
        "ok": True,
        "package": {
            "id": "pkg_suspended_100",
            "title": "Suspended Tour",
            "approvalStatus": "suspended",
            "suspensionReason": "Safety equipment check failed",
            "suspendedByName": "Admin Sarah",
            "suspendedAt": "2026-10-17T09:00:00Z",
            "adultPrice": 100.0,
        },
    }
    with _patch_admin_api(mock_api):
        res = auth_client.get("/admin/packages/pkg_suspended_100")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "Suspend / Unpublish Package" not in html
        assert "Package Suspended &amp; Unpublished" in html
        assert "Safety equipment check failed" in html
        assert "Admin Sarah" in html


def test_scenario_07_suspend_modal_contains_required_fields(auth_client):
    """Scenario 7: Admin suspend modal contains required form fields and notices."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "ok": True,
        "package": {
            "id": "pkg_modal_test",
            "title": "Penang Sunset Cruise",
            "approvalStatus": "approved",
            "adultPrice": 250.0,
        },
    }
    with _patch_admin_api(MagicMock(return_value=mock_resp)):
        res = auth_client.get("/admin/packages/pkg_modal_test")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert 'id="suspendModal"' in html
        assert 'role="dialog"' in html
        assert "Impact Notice:" in html
        assert "Existing paid bookings, confirmed itineraries, and traveller trips will <strong>NOT</strong> be cancelled" in html
        assert 'name="reason"' in html
        assert 'minlength="10"' in html
        assert 'maxlength="500"' in html
        assert 'id="suspendCharCounter"' in html
        assert 'id="suspendConfirmCheckbox"' in html
        assert 'id="confirmSuspendSubmitBtn"' in html


def test_scenario_08_reapproval_shows_resolved_audit_record(auth_client):
    """Scenario 8: Re-approved package shows suspension resolution audit in review record."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "ok": True,
        "package": {
            "id": "pkg_reapproved",
            "title": "Reapproved Heritage Tour",
            "approvalStatus": "approved",
            "reviewedAt": "2026-10-19T10:00:00Z",
            "reviewedByName": "Admin Chief",
            "suspensionResolvedAt": "2026-10-19T10:00:00Z",
            "suspensionResolvedByName": "Admin Chief",
            "adultPrice": 120.0,
        },
    }
    with _patch_admin_api(MagicMock(return_value=mock_resp)):
        res = auth_client.get("/admin/packages/pkg_reapproved")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "Suspension Resolved:" in html
        assert "Re-approved on 2026-10-19 by Admin Chief" in html


def test_scenario_09_suspend_route_requires_auth(unauth_client):
    """Scenario 9: Admin suspend route requires authentication guard."""
    res = unauth_client.post("/admin/packages/pkg_123/suspend", data={"reason": "Valid suspension reason here"})
    assert res.status_code == 302
    assert res.headers["Location"] == "/" or "login" in res.headers["Location"].lower()


def test_scenario_10_suspend_route_validates_reason_length(auth_client):
    """Scenario 10: Admin suspend route validates reason length (10-500 chars)."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"ok": True, "package": {"id": "pkg_123", "approvalStatus": "approved"}}
    mock_api = MagicMock(return_value=mock_resp)

    with _patch_admin_api(mock_api):
        # Too short (< 10 chars)
        res_short = auth_client.post("/admin/packages/pkg_123/suspend", data={"reason": "too short"}, follow_redirects=False)
        assert res_short.status_code == 302
        assert "/admin/packages/pkg_123" in res_short.headers["Location"]
        with auth_client.session_transaction() as sess:
            flashes = sess.get("_flashes", [])
            assert any("at least 10 characters" in msg for cat, msg in flashes)

        # Ensure no POST to suspend endpoint was made
        suspend_calls = [c for c in mock_api.call_args_list if c[0][0] == "POST" and "suspend" in c[0][1]]
        assert len(suspend_calls) == 0

        # Too long (> 500 chars)
        res_long = auth_client.post("/admin/packages/pkg_123/suspend", data={"reason": "x" * 501}, follow_redirects=False)
        assert res_long.status_code == 302
        assert "/admin/packages/pkg_123" in res_long.headers["Location"]
        with auth_client.session_transaction() as sess:
            flashes = sess.get("_flashes", [])
            assert any("cannot exceed 500 characters" in msg for cat, msg in flashes)

        suspend_calls = [c for c in mock_api.call_args_list if c[0][0] == "POST" and "suspend" in c[0][1]]
        assert len(suspend_calls) == 0


def test_scenario_11_suspend_route_successful_call(auth_client):
    """Scenario 11: Admin suspend route proxies to backend API and flashes success on 200."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "ok": True,
        "status": "suspended",
        "idempotent": False,
        "package": {"id": "pkg_123", "approvalStatus": "suspended"},
    }
    mock_api = MagicMock(return_value=mock_resp)

    with _patch_admin_api(mock_api):
        res = auth_client.post(
            "/admin/packages/pkg_123/suspend",
            data={"reason": "Misleading pricing details reported by multiple users"},
            follow_redirects=False,
        )
        assert res.status_code == 302
        assert "/admin/packages/pkg_123" in res.headers["Location"]
        mock_api.assert_called_once_with(
            "POST",
            "/api/fr13/packages/pkg_123/suspend",
            json={"reason": "Misleading pricing details reported by multiple users"},
        )

        with auth_client.session_transaction() as sess:
            flashes = sess.get("_flashes", [])
            assert any("suspended and unpublished successfully" in msg for cat, msg in flashes)


def test_scenario_12_suspend_route_handles_idempotent_and_error(auth_client):
    """Scenario 12: Admin suspend route handles idempotent retry and error responses."""
    # Subcase A: Idempotent 200 (same reason)
    mock_resp_idem = MagicMock()
    mock_resp_idem.ok = True
    mock_resp_idem.status_code = 200
    mock_resp_idem.json.return_value = {
        "ok": True,
        "status": "suspended",
        "idempotent": True,
    }
    with _patch_admin_api(MagicMock(return_value=mock_resp_idem)):
        res = auth_client.post(
            "/admin/packages/pkg_123/suspend",
            data={"reason": "Safety equipment check required"},
            follow_redirects=False,
        )
        assert res.status_code == 302
        with auth_client.session_transaction() as sess:
            flashes = sess.get("_flashes", [])
            assert any("already suspended with this reason" in msg for cat, msg in flashes)

    # Subcase B: 409 Conflict (different reason or invalid state)
    mock_resp_err = MagicMock()
    mock_resp_err.ok = False
    mock_resp_err.status_code = 409
    mock_resp_err.json.return_value = {
        "ok": False,
        "error": "Package is already suspended with a different reason",
    }
    with _patch_admin_api(MagicMock(return_value=mock_resp_err)):
        res = auth_client.post(
            "/admin/packages/pkg_123/suspend",
            data={"reason": "Different reason provided here"},
            follow_redirects=False,
        )
        assert res.status_code == 302
        with auth_client.session_transaction() as sess:
            flashes = sess.get("_flashes", [])
            assert any("already suspended with a different reason" in msg for cat, msg in flashes)
