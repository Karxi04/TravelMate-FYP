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


def test_sidebar_navigation_omits_catalog_section(auth_client):
    """The Catalog section and Destinations / Activities links are completely removed from sidebar."""
    mock_api = MagicMock(return_value=_mock_response({"items": []}))
    with _patch_view_api("admin_fr13.payments", mock_api):
        resp = auth_client.get("/admin/payments")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        # Sidebar checks
        assert '<span class="sidebar-nav-title">Catalog</span>' not in html
        assert 'href="/admin/destinations"' not in html
        assert 'href="/admin/activities"' not in html


def test_reports_page_presents_packages_badge_instead_of_catalog(auth_client):
    """Reports metrics card replaces obsolete 'Catalog' badge with 'Packages'."""
    report_data = {
        "report": {
            "generatedAt": "2026-11-01T10:30:00Z",
            "criteria": {"reportType": "system_summary", "startDate": "2026-10-01", "endDate": "2026-10-31"},
            "counts": {"filtered_records": 10},
            "summary": {
                "users": {"total": 5, "travellers": 4, "operators": 1, "administrators": 1, "active": 5, "deactivated": 0},
                "packages": {"total": 3, "approved": 2, "pending": 1, "rejected": 0, "draft": 0},
                "campaigns": {"total": 1, "approved": 1, "pending": 0, "active": 1, "rejected": 0},
                "feedback": {"total": 2, "visible": 2, "pending": 0, "removed": 0},
            },
        }
    }
    with _patch_view_api("admin_fr13.reports", MagicMock(return_value=_mock_response(report_data))):
        resp = auth_client.get("/admin/reports")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert '<span class="badge neutral">Packages</span>' in html
        assert '<span class="badge neutral">Catalog</span>' not in html


def test_direct_get_destinations_retired_notice_and_read_only(auth_client):
    """Direct bookmarked visit to /admin/destinations renders retired notice and disables mutations."""
    dest_data = {
        "items": [
            {
                "id": "dest_penang_hill",
                "title": "Penang Hill",
                "address": "Air Itam, Penang",
                "category": "Nature",
                "type": "Attraction",
                "openingHours": "06:30 - 23:00",
                "estimatedCost": 30.0,
                "status": "active",
            }
        ]
    }
    with _patch_view_api("admin_fr13.destinations", MagicMock(return_value=_mock_response(dest_data))):
        resp = auth_client.get("/admin/destinations")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        # Notice banner
        assert "Catalog Management Interface Retired" in html
        assert "Direct destination catalog management has been retired" in html
        assert "Destination Directory (Read-Only)" in html
        # Preserved record data
        assert "Penang Hill" in html
        assert "Air Itam, Penang" in html
        assert "Read-Only" in html
        # Mutation controls removed
        assert "Add Destination" not in html
        assert "Edit / Update" not in html
        assert "Delete Destination" not in html


def test_direct_get_activities_retired_notice_and_read_only(auth_client):
    """Direct bookmarked visit to /admin/activities renders retired notice and disables mutations."""
    act_data = {
        "items": [
            {
                "id": "act_funicular",
                "activityName": "Funicular Railway Ride",
                "destinationName": "Penang Hill",
                "category": "Sightseeing",
                "estimatedCost": 30.0,
                "recommendedDurationMinutes": 60,
                "status": "active",
            }
        ]
    }
    with _patch_view_api("admin_fr13.activities", MagicMock(return_value=_mock_response(act_data))):
        resp = auth_client.get("/admin/activities")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        # Notice banner
        assert "Catalog Management Interface Retired" in html
        assert "Direct activity catalog management has been retired" in html
        assert "Activity Directory (Read-Only)" in html
        # Preserved record data
        assert "Funicular Railway Ride" in html
        assert "60 min" in html
        assert "Read-Only" in html
        # Mutation controls removed
        assert "Add Activity" not in html
        assert "Edit / Update" not in html
        assert "Delete Activity" not in html


def test_direct_post_destination_mutations_disabled(auth_client):
    """Direct POST attempts to create, update, or delete destinations flash warnings without calling backend API."""
    mock_api = MagicMock()
    with _patch_view_api("admin_fr13.create_destination", mock_api):
        resp = auth_client.post("/admin/destinations", data={"title": "Test Dest"})
        assert resp.status_code == 302
        assert resp.headers.get("Location").endswith("/admin/destinations")
        mock_api.assert_not_called()

    with _patch_view_api("admin_fr13.update_destination", mock_api):
        resp = auth_client.post("/admin/destinations/dest_123/update", data={"title": "Updated Dest"})
        assert resp.status_code == 302
        assert resp.headers.get("Location").endswith("/admin/destinations")
        mock_api.assert_not_called()

    with _patch_view_api("admin_fr13.delete_destination", mock_api):
        resp = auth_client.post("/admin/destinations/dest_123/delete")
        assert resp.status_code == 302
        assert resp.headers.get("Location").endswith("/admin/destinations")
        mock_api.assert_not_called()


def test_direct_post_activity_mutations_disabled(auth_client):
    """Direct POST attempts to create, update, or delete activities flash warnings without calling backend API."""
    mock_api = MagicMock()
    with _patch_view_api("admin_fr13.create_activity", mock_api):
        resp = auth_client.post("/admin/activities", data={"activityName": "Test Act"})
        assert resp.status_code == 302
        assert resp.headers.get("Location").endswith("/admin/activities")
        mock_api.assert_not_called()

    with _patch_view_api("admin_fr13.update_activity", mock_api):
        resp = auth_client.post("/admin/activities/act_123/update", data={"activityName": "Updated Act"})
        assert resp.status_code == 302
        assert resp.headers.get("Location").endswith("/admin/activities")
        mock_api.assert_not_called()

    with _patch_view_api("admin_fr13.delete_activity", mock_api):
        resp = auth_client.post("/admin/activities/act_123/delete")
        assert resp.status_code == 302
        assert resp.headers.get("Location").endswith("/admin/activities")
        mock_api.assert_not_called()


def test_unauthenticated_catalog_access_redirects(client):
    """Unauthenticated access to retired catalog endpoints redirects to login."""
    assert client.get("/admin/destinations").status_code == 302
    assert client.get("/admin/activities").status_code == 302
    assert client.post("/admin/destinations").status_code == 302
    assert client.post("/admin/activities").status_code == 302
