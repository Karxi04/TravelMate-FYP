import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import re

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


def _patch_operator_api(mock_fn):
    fn_globals = app.view_functions["operator_fr12.packages"].__globals__
    return patch.dict(fn_globals, {"call_api": mock_fn})


def test_01_new_create_package_form_defaults_to_available(auth_client):
    """Point 1: New Create Package form defaults to available."""
    res = auth_client.get("/packages/new")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Must contain available option with selected attribute
    assert re.search(r'<option\s+value=["\']available["\']\s+selected>', html) is not None
    # Unavailable option must NOT have selected attribute
    assert re.search(r'<option\s+value=["\']unavailable["\']\s+selected>', html) is None


def test_02_exactly_one_option_has_selected(auth_client):
    """Point 2: Exactly one option has selected=true within the availabilityStatus select element."""
    res = auth_client.get("/packages/new")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Extract the <select id="availabilityStatus" ... </select> block
    match = re.search(r'<select[^>]*id=["\']availabilityStatus["\'][^>]*>(.*?)</select>', html, re.DOTALL)
    assert match is not None, "availabilityStatus select element must be present"
    select_html = match.group(1)

    selected_matches = re.findall(r'\bselected\b', select_html)
    assert len(selected_matches) == 1, f"Expected exactly 1 selected attribute, found {len(selected_matches)}"


def test_03_empty_package_object_does_not_select_unavailable(auth_client):
    """Point 3: An empty package object does not select unavailable."""
    res = auth_client.get("/packages/new")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Check that unavailable option is NOT selected
    assert 'value="unavailable" selected' not in html
    assert "value='unavailable' selected" not in html


def test_04_existing_available_package_retains_available(auth_client):
    """Point 4: Existing available package retains available."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "ok": True,
        "items": [{
            "id": "pkg_avail_1",
            "title": "Available Heritage Tour",
            "approvalStatus": "approved",
            "availabilityStatus": "available",
            "adultPrice": 150.0,
            "destination": "George Town",
        }],
    }

    with _patch_operator_api(MagicMock(return_value=mock_resp)):
        res = auth_client.get("/packages/pkg_avail_1/edit-page")
        assert res.status_code == 200
        html = res.get_data(as_text=True)

        match = re.search(r'<select[^>]*id=["\']availabilityStatus["\'][^>]*>(.*?)</select>', html, re.DOTALL)
        assert match is not None
        select_html = match.group(1)
        assert re.search(r'<option\s+value=["\']available["\']\s+selected>', select_html) is not None
        assert re.search(r'<option\s+value=["\']unavailable["\']\s+selected>', select_html) is None


def test_05_existing_unavailable_package_retains_unavailable(auth_client):
    """Point 5: Existing unavailable package retains unavailable."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "ok": True,
        "items": [{
            "id": "pkg_unavail_1",
            "title": "Paused Island Adventure",
            "approvalStatus": "approved",
            "availabilityStatus": "unavailable",
            "adultPrice": 220.0,
            "destination": "Batu Ferringhi",
        }],
    }

    with _patch_operator_api(MagicMock(return_value=mock_resp)):
        res = auth_client.get("/packages/pkg_unavail_1/edit-page")
        assert res.status_code == 200
        html = res.get_data(as_text=True)

        match = re.search(r'<select[^>]*id=["\']availabilityStatus["\'][^>]*>(.*?)</select>', html, re.DOTALL)
        assert match is not None
        select_html = match.group(1)
        assert re.search(r'<option\s+value=["\']unavailable["\']\s+selected>', select_html) is not None
        assert re.search(r'<option\s+value=["\']available["\']\s+selected>', select_html) is None


def test_06_frontend_form_serialization_submits_selected_value(auth_client):
    """Point 6: Frontend form serialization submits the visible selected value."""
    # Subcase A: Submit available
    mock_api = MagicMock()
    mock_api.return_value.ok = True
    mock_api.return_value.json.return_value = {"ok": True, "package": {"id": "pkg_new_1"}}

    payload_available = {
        "title": "Test Penang Walk",
        "destination": "George Town, Penang",
        "durationDays": "2",
        "adultPrice": "150.00",
        "availabilityStatus": "available",
    }

    with _patch_operator_api(mock_api):
        res = auth_client.post("/packages/new", data=payload_available)
        assert res.status_code == 302
        call_kwargs = mock_api.call_args[1]
        sent_json = call_kwargs.get("json", {})
        assert sent_json.get("availabilityStatus") == "available"

    # Subcase B: Submit unavailable
    mock_api.reset_mock()
    payload_unavailable = {
        "title": "Test Paused Walk",
        "destination": "George Town, Penang",
        "durationDays": "2",
        "adultPrice": "150.00",
        "availabilityStatus": "unavailable",
    }

    with _patch_operator_api(mock_api):
        res = auth_client.post("/packages/new", data=payload_unavailable)
        assert res.status_code == 302
        call_kwargs = mock_api.call_args[1]
        sent_json = call_kwargs.get("json", {})
        assert sent_json.get("availabilityStatus") == "unavailable"


def test_07_multistep_navigation_and_availability_step2_structure(auth_client):
    """Point 7: Multi-step navigation does not change selection unexpectedly; availability field in Step 2."""
    res = auth_client.get("/packages/new")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Step panel 2 exists
    assert 'id="step-panel-2"' in html
    assert 'STEP 2 OF 6' in html
    # availabilityStatus select is inside step-panel-2
    assert 'name="availabilityStatus"' in html
    # Step 2 explanatory card contains required explanations
    assert "Eligible for Traveller discovery after Admin approval" in html
    assert "Remains hidden and unbookable until activated" in html


def test_08_operator_image_upload_and_gallery_controls_unaffected(auth_client):
    """Point 14: Operator package image upload and gallery controls remain unaffected."""
    res = auth_client.get("/packages/new")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert 'id="cover-dropzone"' in html
    assert 'id="cover-file-input"' in html
    assert 'id="heroImage"' in html
    assert 'name="heroImage"' in html
    assert 'Persistent Image Storage Active:' in html


def test_09_operator_auth_and_csrf_intact(unauth_client):
    """Point 15: Existing login and CSRF protections remain intact."""
    res = unauth_client.get("/packages/new")
    assert res.status_code == 302
    assert res.location in {"/", "/login", "http://localhost/", "http://localhost/login"}
