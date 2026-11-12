import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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

from admin_website.app import app  # noqa: E402
from admin_website.package_review_formatter import (  # noqa: E402
    format_structured_blocks,
    inline_segments,
    parse_float,
    parse_itinerary_activity,
)


@pytest.fixture
def auth_client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["id_token"] = "valid_admin_token"
            sess["portal_role"] = "admin"
            sess["admin_id"] = "admin_redesign_test"
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


def test_formatter_parses_markdown_headings_lists_and_bold_without_raw_markers():
    sample = (
        "### Morning Briefing\n\n"
        "**What to expect**\n"
        "Arrive at **Jetty Point** before boarding.\n"
        "- Bring **sunscreen** and water\n"
        "- Valid photo ID required\n"
    )
    blocks = format_structured_blocks(sample)
    assert blocks[0]["type"] == "heading"
    assert blocks[0]["segments"] == [{"text": "Morning Briefing", "bold": False}]

    assert blocks[1]["type"] == "heading"
    assert blocks[1]["segments"] == [{"text": "What to expect", "bold": True}]

    assert blocks[2]["type"] == "paragraph"
    assert [s["text"] for s in blocks[2]["segments"]] == [
        "Arrive at ",
        "Jetty Point",
        " before boarding.",
    ]
    assert blocks[2]["segments"][1]["bold"] is True

    assert blocks[3]["type"] == "list"
    assert len(blocks[3]["items"]) == 2
    assert inline_segments("Plain **highlighted** text")[1] == {
        "text": "highlighted",
        "bold": True,
    }


def test_formatter_parses_activities_without_inventing_missing_times():
    timed = parse_itinerary_activity("08:30 AM - Ferry crossing to Butterworth")
    assert timed["time"] == "08:30 AM"
    assert timed["title"] == "Ferry crossing to Butterworth"

    untimed = parse_itinerary_activity("Street art heritage walk around Kampung Benggali")
    assert untimed["time"] == ""
    assert untimed["title"] == "Street art heritage walk around Kampung Benggali"

    structured = parse_itinerary_activity(
        {
            "activityName": "02:15 PM - Penang Bird Park Visit",
            "location": "Seberang Jaya",
            "description": "Guided boardwalk **tour**",
        }
    )
    assert structured["time"] == "02:15 PM"
    assert structured["title"] == "Penang Bird Park Visit"
    assert structured["location"] == "Seberang Jaya"

    assert parse_float("199.50") == 199.5
    assert parse_float("") is None
    assert parse_float(True) is None


@pytest.mark.parametrize(
    "pkg_state,availability,expected_status,expected_discovery,has_decision_form,has_suspend_btn",
    [
        ("pending", "available", "Under review", "Hidden (Under review)", True, False),
        ("submitted", "available", "Under review", "Hidden (Under review)", True, False),
        ("approved", "available", "Published", "Publicly Visible", False, True),
        ("approved", "unavailable", "Approved (Unavailable)", "Hidden (Unavailable)", False, True),
        ("rejected", "available", "Needs changes", "Hidden (Needs changes)", False, False),
        ("suspended", "available", "Suspended", "Hidden (Suspended)", False, False),
        ("draft", "available", "Draft", "Hidden (Draft)", False, False),
        ("archived", "available", "Archived", "Hidden (Archived)", False, False),
    ],
)
def test_package_review_all_lifecycle_states(
    auth_client,
    pkg_state,
    availability,
    expected_status,
    expected_discovery,
    has_decision_form,
    has_suspend_btn,
):
    pkg = {
        "id": f"pkg_{pkg_state}_{availability}",
        "title": "Heritage Discovery Package",
        "destination": "Penang",
        "approvalStatus": pkg_state,
        "availabilityStatus": availability,
        "price": 320.0,
        "operatorName": "Northern Trails Sdn Bhd",
        "suspensionReason": "Safety audit required" if pkg_state == "suspended" else None,
        "reviewReason": "Please clarify pickup point." if pkg_state == "rejected" else None,
    }

    mock_api = MagicMock(return_value=_mock_pkg_response(pkg))
    with _patch_admin_api(mock_api):
        res = auth_client.get(f"/admin/packages/{pkg['id']}")
        assert res.status_code == 200
        html = res.get_data(as_text=True)

        assert expected_status in html
        assert expected_discovery in html
        assert ('id="moderationDecisionForm"' in html) is has_decision_form
        assert ('id="openSuspendModalBtn"' in html) is has_suspend_btn
        assert ("Package Suspended &amp; Unpublished" in html) is (pkg_state == "suspended")


def test_package_review_butterworth_full_fixture_and_long_text_dom(auth_client):
    fixture_path = (
        ROOT
        / "backend_api"
        / "tests"
        / "fixtures"
        / "butterworth_full_original_editor.json"
    )
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    pkg = dict(raw.get("package", raw))
    pkg.setdefault("id", "pkg_butterworth_full")
    pkg.setdefault("approvalStatus", "submitted")
    pkg.setdefault("availabilityStatus", "available")
    pkg.setdefault("originalPrice", 980.0)
    pkg.setdefault("price", 780.0)
    pkg.setdefault("childPrice", 490.0)

    mock_api = MagicMock(return_value=_mock_pkg_response(pkg))
    with _patch_admin_api(mock_api):
        res = auth_client.get(f"/admin/packages/{pkg['id']}")
        assert res.status_code == 200
        html = res.get_data(as_text=True)

        # Overview metrics & pricing
        assert "RM 780.00" in html
        assert "RM 980.00" in html
        assert "RM 490.00" in html

        # Individual departure date chips instead of raw joined comma wall
        for dep_date in pkg.get("departureDates", []):
            assert f'class="pkg-date-chip">{dep_date}</span>' in html

        # Structured day-by-day itinerary without raw markdown or missing activities
        assert "Day-by-day itinerary" in html
        for day in pkg.get("itinerary", []):
            if day.get("title"):
                assert day["title"] in html
            for act in day.get("activities", []):
                parsed = parse_itinerary_activity(act)
                if parsed["title"]:
                    assert parsed["title"] in html

        # Full prose kept in DOM even when long descriptions trigger collapse
        if len(pkg.get("fullDescription", "")) > 420:
            assert "pkg-collapsible" in html
            assert "Show full details" in html
        for exc in pkg.get("exclusions", []):
            assert exc in html


def test_package_review_escapes_html_injection_and_handles_minimal_payload(auth_client):
    xss_payload = "<script>window.__xss=1</script>"
    pkg = {
        "id": "pkg_xss_minimal",
        "title": f"Tour {xss_payload}",
        "shortDescription": f"Intro {xss_payload}",
        "fullDescription": f"First paragraph.\n\n{xss_payload}",
        "highlights": [f"Highlight {xss_payload}"],
        "inclusions": [f"Meal {xss_payload}"],
        "cancellationPolicy": f"Policy {xss_payload}",
        "approvalStatus": "pending",
    }

    mock_api = MagicMock(return_value=_mock_pkg_response(pkg))
    with _patch_admin_api(mock_api):
        res = auth_client.get("/admin/packages/pkg_xss_minimal")
        assert res.status_code == 200
        html = res.get_data(as_text=True)

        assert "<script>window.__xss=1</script>" not in html
        assert "&lt;script&gt;window.__xss=1&lt;/script&gt;" in html
        assert "No cover image was submitted for this package." in html
        assert "No day-by-day itinerary submitted yet." in html


def test_package_review_stylesheet_contains_responsive_breakpoints():
    css_text = (ADMIN_DIR / "static" / "styles.css").read_text(encoding="utf-8")
    for expected_token in (
        ".pkg-review-workspace",
        ".pkg-review-sidebar",
        "@media (max-width: 1240px)",
        "@media (max-width: 1100px)",
        "@media (max-width: 980px)",
        "@media (max-width: 680px)",
        "@media (max-width: 420px)",
    ):
        assert expected_token in css_text
