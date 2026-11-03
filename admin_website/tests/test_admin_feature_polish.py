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
def admin_client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["id_token"] = "valid_admin_token"
            sess["portal_role"] = "admin"
            sess["email"] = "admin@travelmate.test"
        yield client


def _mock_response(json_data, status_code=200):
    mock = MagicMock()
    mock.ok = (200 <= status_code < 300)
    mock.status_code = status_code
    mock.json.return_value = json_data
    return mock


def _patch_view_api(view_name, mock_fn):
    fn_globals = app.view_functions[view_name].__globals__
    return patch.dict(fn_globals, {"call_api": mock_fn})


# =========================================================================
# 1. Dashboard Feature Polish Tests
# =========================================================================

def test_dashboard_renders_moderation_and_commerce_kpis(admin_client):
    """Dashboard presents moderation queues, commerce KPIs, and pending operator badges."""
    report_data = {
        "report": {
            "generatedAt": "2026-11-01T10:00:00Z",
            "counts": {
                "users": 42,
                "tourism_packages": 15,
                "promotional_campaigns": 8,
                "feedback": 5,
                "hotel_bookings": 12,
                "package_bookings": 7,
                "payment_records": 19,
            },
            "summary": {
                "users": {
                    "total": 42,
                    "travellers": 30,
                    "operators": 10,
                    "administrators": 2,
                    "pendingOperators": 3,
                    "approvedOperators": 7,
                },
                "packages": {"total": 15, "pending": 4, "approved": 10, "rejected": 1},
                "campaigns": {"total": 8, "pending": 2, "active": 5, "rejected": 1},
                "feedback": {"total": 5, "pending": 1, "visible": 4, "removed": 0},
                "payments": {
                    "total": 19,
                    "paid": 14,
                    "pending": 3,
                    "failed": 2,
                    "totalPaidRevenue": 4850.50,
                    "testPaidTotal": 4850.50,
                },
            },
        }
    }

    mock_api = MagicMock(return_value=_mock_response(report_data))
    with _patch_view_api("admin_fr13.dashboard", mock_api):
        resp = admin_client.get("/admin/dashboard")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        # System overview header
        assert "System Overview" in html
        assert "Supervise platform metrics" in html

        # Moderation KPI metrics
        assert "Package Queue" in html
        assert "Campaign Queue" in html
        assert "Feedback Queue" in html
        assert "3 Pending Operators" in html

        # Moderation attention banner (4 + 2 + 1 = 7 pending)
        assert "Moderation Attention Required" in html
        assert "7 submission(s) currently awaiting administrative decision" in html

        # Commerce & Booking Oversight card
        assert "Commerce &amp; Booking Oversight" in html
        assert "MYR 4850.50" in html
        assert "Stripe Test: MYR 4850.50" in html
        assert "Platform bookings" in html


def test_dashboard_cleared_moderation_state(admin_client):
    """When all queues are zero, displays positive cleared banner."""
    report_data = {
        "report": {
            "generatedAt": "2026-11-01T10:00:00Z",
            "counts": {"users": 10, "tourism_packages": 5, "feedback": 2},
            "summary": {
                "users": {"total": 10, "travellers": 8, "operators": 2, "pendingOperators": 0},
                "packages": {"pending": 0, "approved": 5},
                "campaigns": {"pending": 0, "active": 2},
                "feedback": {"pending": 0, "visible": 2},
                "payments": {"totalPaidRevenue": 0},
            },
        }
    }
    mock_api = MagicMock(return_value=_mock_response(report_data))
    with _patch_view_api("admin_fr13.dashboard", mock_api):
        resp = admin_client.get("/admin/dashboard")
        assert resp.status_code == 200
        assert b"All Moderation Queues Cleared" in resp.data


# =========================================================================
# 2. Package Queue & Detail Review Tests
# =========================================================================

def test_packages_queue_unminified_table_and_empty_state(admin_client):
    """Packages queue renders clean table columns, badges, and rich empty state."""
    # 1. Populated queue
    items_data = {
        "items": [
            {
                "id": "pkg_1",
                "title": "Georgetown Heritage Walk",
                "durationDays": 1,
                "operatorName": "Penang Guides",
                "destination": "George Town",
                "submittedAt": "2026-10-25T08:00:00Z",
                "price": 120.0,
                "currency": "MYR",
                "approvalStatus": "pending",
            }
        ]
    }
    mock_api = MagicMock(return_value=_mock_response(items_data))
    with _patch_view_api("admin_fr13.packages", mock_api):
        resp = admin_client.get("/admin/packages")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "Tourism Package Queue" in html
        assert "Georgetown Heritage Walk" in html
        assert "Under review" in html
        assert "Review details" in html

    # 2. Empty state
    mock_empty = MagicMock(return_value=_mock_response({"items": []}))
    with _patch_view_api("admin_fr13.packages", mock_empty):
        resp = admin_client.get("/admin/packages")
        assert resp.status_code == 200
        assert b"No packages match this view." in resp.data


# =========================================================================
# 3. Campaign Moderation Queue & Details Tests
# =========================================================================

def test_campaigns_queue_and_detail_presentation(admin_client):
    """Campaigns review renders structured cards, discount indicators, and decision form."""
    # 1. Campaign listing
    campaigns_data = {
        "items": [
            {
                "id": "camp_1",
                "campaignTitle": "Early Bird Penang 2026",
                "packageTitle": "Georgetown Heritage Walk",
                "destinationName": "George Town",
                "startDate": "2026-11-01",
                "endDate": "2026-11-30",
                "discountValue": 20,
                "discountType": "percentage",
                "promoCode": "EARLY20",
                "reviewStatus": "pending",
                "description": "Get 20% off all November bookings.",
            }
        ]
    }
    mock_api = MagicMock(return_value=_mock_response(campaigns_data))
    with _patch_view_api("admin_fr13.campaigns", mock_api):
        resp = admin_client.get("/admin/campaigns")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "Promotion reviews" in html
        assert "Early Bird Penang 2026" in html
        assert "20% OFF" in html
        assert "CODE: EARLY20" in html
        assert "Open review" in html

    # 2. Campaign detail
    camp_detail_data = {
        "campaign": {
            "id": "camp_1",
            "campaignTitle": "Early Bird Penang 2026",
            "packageTitle": "Georgetown Heritage Walk",
            "packageId": "pkg_1",
            "destinationName": "George Town",
            "startDate": "2026-11-01",
            "endDate": "2026-11-30",
            "discountValue": 20,
            "discountType": "percentage",
            "promoCode": "EARLY20",
            "reviewStatus": "pending",
            "description": "Get 20% off all November bookings.",
            "termsConditions": "Valid for direct bookings only.",
        }
    }
    mock_detail = MagicMock(return_value=_mock_response(camp_detail_data))
    with _patch_view_api("admin_fr13.campaign_details", mock_detail):
        resp = admin_client.get("/admin/campaigns/camp_1")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "Early Bird Penang 2026" in html
        assert "20% Percentage Discount" in html
        assert "EARLY20" in html
        assert "Approve &amp; publish" in html
        assert "name=\"decision\" value=\"rejected\"" in html


# =========================================================================
# 4. User Management & Operator Verification Tests
# =========================================================================

def test_users_table_role_and_operator_verification_display(admin_client):
    """User management cleanly separates operator accreditation, company SSM, and role actions."""
    users_data = {
        "items": [
            {
                "id": "usr_traveller",
                "name": "Jane Doe",
                "email": "jane@example.com",
                "role": "traveller",
                "status": "active",
            },
            {
                "id": "usr_operator",
                "name": "Bob Tours",
                "email": "bob@borneotours.my",
                "role": "operator",
                "companyName": "Borneo Tours Sdn Bhd",
                "registrationNo": "202401099887",
                "status": "active",
                "verificationStatus": "pending",
            },
        ]
    }
    mock_api = MagicMock(return_value=_mock_response(users_data))
    with _patch_view_api("admin_fr13.users", mock_api):
        resp = admin_client.get("/admin/users")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "People and verification" in html
        assert "Jane Doe" in html
        assert "Not applicable" in html
        assert "Borneo Tours Sdn Bhd" in html
        assert "202401099887" in html
        assert "Pending Verification" in html
        assert "name=\"verificationStatus\"" in html


# =========================================================================
# 5. Feedback Moderation Tests
# =========================================================================

def test_feedback_moderation_presentation_and_empty_state(admin_client):
    """Feedback review displays star rating, screening risk chips, and empty state."""
    fb_data = {
        "items": [
            {
                "id": "fb_1",
                "destinationName": "Kek Lok Si Temple",
                "destinationAddress": "Air Itam, Penang",
                "travellerName": "Sarah Lee",
                "rating": 5,
                "comment": "Stunning temple complex, especially at night during Chinese New Year!",
                "feedbackStatus": "visible",
                "moderationStatus": "pending_review",
                "screening": {"risk": "low", "flags": []},
                "submittedAt": "2026-10-30",
            }
        ]
    }
    mock_api = MagicMock(return_value=_mock_response(fb_data))
    with _patch_view_api("admin_fr13.feedback", mock_api):
        resp = admin_client.get("/admin/feedback")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "Traveller Reviews &amp; Feedback" in html
        assert "Kek Lok Si Temple" in html
        assert "★" in html
        assert "Sarah Lee" in html
        assert "Approve" in html

    # Empty state
    mock_empty = MagicMock(return_value=_mock_response({"items": []}))
    with _patch_view_api("admin_fr13.feedback", mock_empty):
        resp = admin_client.get("/admin/feedback")
        assert resp.status_code == 200
        assert b"No Traveller reviews have been submitted." in resp.data


# =========================================================================
# 6. Destinations & Activities Management Tests
# =========================================================================

def test_destinations_and_activities_presentation(admin_client):
    """Destinations and activities render create forms, tables, and expandable inline editors."""
    # Destinations
    dest_data = {
        "items": [
            {
                "id": "dest_1",
                "title": "Penang Hill",
                "address": "Air Itam",
                "category": "Nature",
                "type": "Attraction",
                "openingHours": "06:30 - 23:00",
                "estimatedCost": 30.0,
                "status": "active",
            }
        ]
    }
    # Destinations (Retired Management UI)
    mock_dest = MagicMock(return_value=_mock_response(dest_data))
    with _patch_view_api("admin_fr13.destinations", mock_dest):
        resp = admin_client.get("/admin/destinations")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "Catalog Management Interface Retired" in html
        assert "Destination Directory (Read-Only)" in html
        assert "Penang Hill" in html
        assert "Read-Only" in html
        assert "Add Destination" not in html
        assert "Edit / Update" not in html

    # Activities (Retired Management UI)
    act_data = {
        "items": [
            {
                "id": "act_1",
                "activityName": "Funicular Railway Ride",
                "destinationName": "Penang Hill",
                "category": "Sightseeing",
                "estimatedCost": 30.0,
                "recommendedDurationMinutes": 60,
                "status": "active",
            }
        ]
    }
    mock_act = MagicMock(return_value=_mock_response(act_data))
    with _patch_view_api("admin_fr13.activities", mock_act):
        resp = admin_client.get("/admin/activities")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "Catalog Management Interface Retired" in html
        assert "Activity Directory (Read-Only)" in html
        assert "Funicular Railway Ride" in html
        assert "60 min" in html
        assert "Read-Only" in html
        assert "Add Activity" not in html
        assert "Edit / Update" not in html


# =========================================================================
# 7. System Reports Tests
# =========================================================================

def test_reports_page_criteria_form_and_export_links(admin_client):
    """Reports page renders CSV/PDF export buttons, criteria form, and category breakdown cards."""
    report_data = {
        "report": {
            "generatedAt": "2026-11-01T10:30:00Z",
            "criteria": {"reportType": "system_summary", "startDate": "2026-10-01", "endDate": "2026-10-31"},
            "counts": {"filtered_records": 100},
            "summary": {
                "users": {"total": 50, "travellers": 40, "operators": 8, "administrators": 2, "active": 48, "deactivated": 2},
                "packages": {"total": 20, "approved": 15, "pending": 3, "rejected": 2, "draft": 0},
                "campaigns": {"total": 10, "approved": 8, "pending": 1, "active": 7, "rejected": 1},
                "feedback": {"total": 15, "visible": 12, "pending": 2, "removed": 1},
            },
        }
    }
    mock_api = MagicMock(return_value=_mock_response(report_data))
    with _patch_view_api("admin_fr13.reports", mock_api):
        resp = admin_client.get("/admin/reports")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "System Activity Report" in html
        assert "Export CSV" in html
        assert "Export PDF" in html
        assert "Configure Report Parameters" in html
        assert "User Accounts Breakdown" in html
        assert "Tourism Packages Breakdown" in html
