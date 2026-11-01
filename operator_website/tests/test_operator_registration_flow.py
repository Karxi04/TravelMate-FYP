import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import requests
from flask import session

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
import operator_website.api_client as api_client_module


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    if "request_rate_limiter" in app.extensions:
        app.extensions["request_rate_limiter"].reset()
    with app.test_client() as c:
        yield c


def _mock_firebase_auth_success(uid="fake_operator_uid", email="operator@example.com"):
    return {
        "idToken": "fake_operator_id_token",
        "refreshToken": "fake_operator_refresh_token",
        "localId": uid,
        "email": email,
        "expiresIn": "3600",
    }, 200


# =========================================================================
# OP-REG-01, 02, 03: Full Valid Operator Registration Flow
# =========================================================================

def test_op_reg_01_02_03_valid_registration_flow(client):
    """OP-REG-01, OP-REG-02, OP-REG-03: Valid registration creates Firebase account,
    provisions Firestore profile with pending status, and directs user to login."""
    mock_auth = MagicMock(return_value=_mock_firebase_auth_success())
    mock_profile_resp = MagicMock()
    mock_profile_resp.ok = True
    mock_profile_resp.status_code = 200
    mock_profile_resp.json.return_value = {
        "ok": True,
        "message": "Profile created",
        "role": "operator",
        "verificationStatus": "pending",
    }
    mock_call_api = MagicMock(return_value=mock_profile_resp)

    patch_dict = {
        "createUserAccount": mock_auth,
        "call_api": mock_call_api,
    }

    form_data = {
        "name": "Borneo Eco Tours",
        "email": "borneo@example.com",
        "password": "Password123!",
        "confirmPassword": "Password123!",
        "companyName": "Borneo Eco Tours Sdn Bhd",
        "registrationNo": "202401099887",
        "businessContact": "+60123456789",
    }

    with patch.dict(app.view_functions["operator_fr01.register"].__globals__, patch_dict):
        response = client.post("/register", data=form_data, follow_redirects=True)

        # Successful registration redirects to login with confirmation message
        assert response.status_code == 200
        assert b"awaiting Administrator verification" in response.data

        # OP-REG-01: Verify createUserAccount called with email and password
        mock_auth.assert_called_once_with("borneo@example.com", "Password123!")

        # OP-REG-01: Verify call_api called with POST /api/fr1/profile and correct payload
        mock_call_api.assert_called_once()
        call_args = mock_call_api.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "/api/fr1/profile"
        payload = call_args[1]["json"]
        assert payload["role"] == "operator"
        assert payload["name"] == "Borneo Eco Tours"
        assert payload["companyName"] == "Borneo Eco Tours Sdn Bhd"
        assert payload["registrationNo"] == "202401099887"
        assert payload["businessContact"] == "+60123456789"


# =========================================================================
# OP-REG-04, 05: Token Refresh on Backend 401 & Automatic Retry
# =========================================================================

def test_op_reg_04_05_call_api_retries_on_401(client):
    """OP-REG-04, OP-REG-05: When backend returns 401, call_api refreshes ID token and retries once."""
    resp_401 = MagicMock()
    resp_401.status_code = 401
    resp_401.ok = False

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.ok = True
    resp_200.json.return_value = {"ok": True, "profile": {"role": "operator"}}

    mock_refresh = MagicMock(return_value=({
        "id_token": "brand_new_refreshed_token",
        "refresh_token": "brand_new_refresh_token",
        "expires_in": "3600",
    }, 200))

    with app.test_request_context():
        session["id_token"] = "expired_token"
        session["refresh_token"] = "valid_refresh_token"
        session["token_expires_at"] = time.time() + 1000

        with patch("requests.request", side_effect=[resp_401, resp_200]) as mock_req, \
             patch("operator_website.api_client.refresh_id_token", mock_refresh):
            resp = api_client_module.call_api("GET", "/api/fr1/me")

            assert resp.status_code == 200
            assert mock_refresh.call_count == 1
            assert mock_req.call_count == 2
            # Second call must use the refreshed token
            second_headers = mock_req.call_args_list[1][1]["headers"]
            assert second_headers["Authorization"] == "Bearer brand_new_refreshed_token"
            assert session["id_token"] == "brand_new_refreshed_token"


# =========================================================================
# OP-REG-06: Unauthenticated Request Rejection
# =========================================================================

def test_op_reg_06_unauthenticated_requests_redirect_to_login(client):
    """OP-REG-06: Protected operator endpoints redirect to login when unauthenticated."""
    endpoints = ["/dashboard", "/verification", "/profile", "/complete-setup"]
    for ep in endpoints:
        resp = client.get(ep)
        assert resp.status_code == 302
        assert "/" in resp.headers["Location"]


# =========================================================================
# OP-REG-07: Firebase Creation Succeeded, Profile Failed -> Non-Fatal Guidance
# =========================================================================

def test_op_reg_07_partial_registration_failure_guides_to_login(client):
    """OP-REG-07: If Firebase auth succeeds but profile creation fails,
    the user is redirected to login with clear guidance rather than stranded."""
    mock_auth = MagicMock(return_value=_mock_firebase_auth_success())
    mock_profile_resp = MagicMock()
    mock_profile_resp.ok = False
    mock_profile_resp.status_code = 500
    mock_profile_resp.json.return_value = {"error": "Internal Server Error"}
    mock_call_api = MagicMock(return_value=mock_profile_resp)

    patch_dict = {
        "createUserAccount": mock_auth,
        "call_api": mock_call_api,
    }

    form_data = {
        "name": "Borneo Eco Tours",
        "email": "borneo@example.com",
        "password": "Password123!",
        "confirmPassword": "Password123!",
        "companyName": "Borneo Eco Tours Sdn Bhd",
        "registrationNo": "202401099887",
        "businessContact": "+60123456789",
    }

    with patch.dict(app.view_functions["operator_fr01.register"].__globals__, patch_dict):
        response = client.post("/register", data=form_data, follow_redirects=True)

        assert response.status_code == 200
        assert b"Please sign in to continue" in response.data


# =========================================================================
# OP-REG-08: Stranded Account Signs In -> Redirected to /complete-setup
# =========================================================================

def test_op_reg_08_stranded_account_login_redirects_complete_setup(client):
    """OP-REG-08: When a user with an Auth account but missing profile signs in,
    they are redirected to /complete-setup to finish registration."""
    mock_auth = MagicMock(return_value=_mock_firebase_auth_success())
    mock_me_resp = MagicMock()
    mock_me_resp.ok = True
    mock_me_resp.status_code = 200
    mock_me_resp.json.return_value = {"ok": True, "profile": None}

    patch_dict = {
        "authenticateCredentials": mock_auth,
        "call_api": MagicMock(return_value=mock_me_resp),
    }

    with patch.dict(app.view_functions["operator_fr01.login"].__globals__, patch_dict):
        response = client.post("/", data={"email": "stranded@example.com", "password": "Password123!"})

        assert response.status_code == 302
        assert "/complete-setup" in response.headers["Location"]
        with client.session_transaction() as sess:
            assert sess.get("incomplete_setup") is True
            assert sess.get("portal_role") == "operator"


# =========================================================================
# OP-REG-09, 10: Repeated Registration with Existing Email
# =========================================================================

def test_op_reg_09_10_email_exists_clear_sign_in_guidance(client):
    """OP-REG-09, OP-REG-10: Submitting an existing email redirects to login with clear sign-in guidance
    and does NOT call profile API."""
    mock_auth = MagicMock(return_value=({"error": {"message": "EMAIL_EXISTS"}}, 400))
    mock_call_api = MagicMock()

    patch_dict = {
        "createUserAccount": mock_auth,
        "call_api": mock_call_api,
    }

    form_data = {
        "name": "Borneo Eco Tours",
        "email": "already_exists@example.com",
        "password": "Password123!",
        "confirmPassword": "Password123!",
        "companyName": "Borneo Eco Tours Sdn Bhd",
        "registrationNo": "202401099887",
        "businessContact": "+60123456789",
    }

    with patch.dict(app.view_functions["operator_fr01.register"].__globals__, patch_dict):
        response = client.post("/register", data=form_data, follow_redirects=True)

        assert response.status_code == 200
        assert b"This email is already registered." in response.data
        assert b"Sign in" in response.data
        # Profile creation API must NOT be called
        mock_call_api.assert_not_called()


# =========================================================================
# OP-REG-11: Completing Setup via /complete-setup
# =========================================================================

def test_op_reg_11_complete_setup_flow(client):
    """OP-REG-11: User with incomplete_setup completes registration details at /complete-setup."""
    with client.session_transaction() as sess:
        sess["id_token"] = "valid_token"
        sess["uid"] = "user_123"
        sess["incomplete_setup"] = True
        sess["portal_role"] = "operator"

    mock_profile_resp = MagicMock()
    mock_profile_resp.ok = True
    mock_profile_resp.status_code = 200
    mock_profile_resp.json.return_value = {"ok": True, "message": "Profile created"}

    mock_me_resp = MagicMock()
    mock_me_resp.ok = True
    mock_me_resp.json.return_value = {"ok": True, "profile": None}

    def _api_side_effect(method, path, **kwargs):
        if path == "/api/fr1/me":
            return mock_me_resp
        if path == "/api/fr1/profile":
            return mock_profile_resp
        return MagicMock(ok=False, status_code=404)

    patch_dict = {
        "call_api": MagicMock(side_effect=_api_side_effect),
    }

    form_data = {
        "name": "Sabah Travel Co",
        "companyName": "Sabah Travel Co Sdn Bhd",
        "registrationNo": "202409876543",
        "businessContact": "+60198765432",
    }

    with patch.dict(app.view_functions["operator_fr01.complete_setup"].__globals__, patch_dict):
        # 1. GET displays complete_setup template
        get_resp = client.get("/complete-setup")
        assert get_resp.status_code == 200
        assert b"Complete Operator Setup" in get_resp.data

        # 2. POST submits details to /api/fr1/profile
        post_resp = client.post("/complete-setup", data=form_data)
        assert post_resp.status_code == 302
        assert "/verification" in post_resp.headers["Location"]

        with client.session_transaction() as sess:
            assert sess.get("incomplete_setup") is None
            assert sess.get("portal_role") == "operator"
            assert sess.get("verification_status") == "pending"


# =========================================================================
# OP-REG-12: Incomplete Operator Cannot Access Dashboard
# =========================================================================

def test_op_reg_12_incomplete_operator_cannot_access_dashboard(client):
    """OP-REG-12: Incomplete operator is redirected to /complete-setup when requesting /dashboard."""
    with client.session_transaction() as sess:
        sess["id_token"] = "valid_token"
        sess["portal_role"] = "operator"
        sess["incomplete_setup"] = True

    response = client.get("/dashboard")
    assert response.status_code == 302
    assert "/complete-setup" in response.headers["Location"]


# =========================================================================
# OP-REG-13: Pending Operator Redirected to Verification
# =========================================================================

def test_op_reg_13_pending_operator_redirected_to_verification(client):
    """OP-REG-13: Operator with pending status is redirected to /verification when requesting /dashboard."""
    with client.session_transaction() as sess:
        sess["id_token"] = "valid_token"
        sess["portal_role"] = "operator"
        sess["verification_status"] = "pending"

    response = client.get("/dashboard")
    assert response.status_code == 302
    assert "/verification" in response.headers["Location"]


# =========================================================================
# OP-REG-14: Approved Operator Accesses Dashboard
# =========================================================================

def test_op_reg_14_approved_operator_accesses_dashboard(client):
    """OP-REG-14: Operator with approved status can access /dashboard successfully."""
    with client.session_transaction() as sess:
        sess["id_token"] = "valid_token"
        sess["portal_role"] = "operator"
        sess["verification_status"] = "approved"

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"items": []}

    patch_dict = {
        "call_api": MagicMock(return_value=mock_resp),
    }

    with patch.dict(app.view_functions["operator_fr12.dashboard"].__globals__, patch_dict):
        response = client.get("/dashboard")
        assert response.status_code == 200


# =========================================================================
# OP-REG-15: Rejected Operator Redirected with Warning
# =========================================================================

def test_op_reg_15_rejected_operator_redirected_with_warning(client):
    """OP-REG-15: Operator with rejected status is redirected to /verification with a warning."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "ok": True,
        "profile": {"role": "operator", "name": "Rejected Tour", "verificationStatus": "rejected"},
    }

    patch_dict = {
        "authenticateCredentials": MagicMock(return_value=_mock_firebase_auth_success()),
        "call_api": MagicMock(return_value=mock_resp),
    }

    with patch.dict(app.view_functions["operator_fr01.login"].__globals__, patch_dict):
        response = client.post("/", data={"email": "op@example.com", "password": "Password123!"})

        assert response.status_code == 302
        assert "/verification" in response.headers["Location"]
        with client.session_transaction() as sess:
            assert sess.get("verification_status") == "rejected"


# =========================================================================
# OP-REG-16: Existing Traveller Cannot Convert to Operator
# =========================================================================

def test_op_reg_16_traveller_cannot_convert_to_operator(client):
    """OP-REG-16: Traveller credentials cannot be used to gain operator portal access or run complete-setup."""
    # 1. Login rejection
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "ok": True,
        "profile": {"role": "traveller", "name": "Solo Traveller"},
    }

    patch_dict_login = {
        "authenticateCredentials": MagicMock(return_value=_mock_firebase_auth_success()),
        "call_api": MagicMock(return_value=mock_resp),
    }

    with patch.dict(app.view_functions["operator_fr01.login"].__globals__, patch_dict_login):
        response = client.post("/", data={"email": "traveller@example.com", "password": "Password123!"})
        assert response.status_code == 200
        assert b"This account is not a Tourism Operator account." in response.data
        with client.session_transaction() as sess:
            assert sess.get("id_token") is None

    # 2. Complete setup rejection if profile is traveller
    with client.session_transaction() as sess:
        sess["id_token"] = "valid_token"
        sess["incomplete_setup"] = True

    patch_dict_setup = {
        "call_api": MagicMock(return_value=mock_resp),
    }
    with patch.dict(app.view_functions["operator_fr01.complete_setup"].__globals__, patch_dict_setup):
        response = client.get("/complete-setup")
        assert response.status_code == 302
        assert "/" in response.headers["Location"]
        with client.session_transaction() as sess:
            assert sess.get("id_token") is None


# =========================================================================
# OP-REG-17: Existing Administrator Role Preservation
# =========================================================================

def test_op_reg_17_admin_role_cannot_be_overwritten_by_complete_setup(client):
    """OP-REG-17: Admin accounts accessing complete-setup are blocked from role alteration."""
    mock_admin_resp = MagicMock()
    mock_admin_resp.ok = True
    mock_admin_resp.status_code = 200
    mock_admin_resp.json.return_value = {
        "ok": True,
        "profile": {"role": "admin", "name": "System Administrator"},
    }

    with client.session_transaction() as sess:
        sess["id_token"] = "admin_token"
        sess["incomplete_setup"] = True

    patch_dict = {
        "call_api": MagicMock(return_value=mock_admin_resp),
    }

    with patch.dict(app.view_functions["operator_fr01.complete_setup"].__globals__, patch_dict):
        response = client.get("/complete-setup")
        assert response.status_code == 302
        assert "/" in response.headers["Location"]
        with client.session_transaction() as sess:
            assert sess.get("id_token") is None


# =========================================================================
# OP-REG-18: Logout Clears Session Cleanly
# =========================================================================

def test_op_reg_18_logout_clears_session(client):
    """OP-REG-18: Logging out clears all session attributes and redirects to login."""
    with client.session_transaction() as sess:
        sess["id_token"] = "active_token"
        sess["portal_role"] = "operator"
        sess["verification_status"] = "approved"
        sess["incomplete_setup"] = True

    response = client.post("/logout")
    assert response.status_code == 302
    assert "/" in response.headers["Location"]

    with client.session_transaction() as sess:
        assert sess.get("id_token") is None
        assert sess.get("portal_role") is None
        assert sess.get("verification_status") is None
        assert sess.get("incomplete_setup") is None


# =========================================================================
# OP-REG-19: Network Failures During Registration
# =========================================================================

def test_op_reg_19_network_failures_display_friendly_error(client):
    """OP-REG-19: Network exceptions during registration show a friendly error without credential leaks."""
    mock_auth = MagicMock(side_effect=requests.RequestException("DNS lookup timeout"))

    patch_dict = {
        "createUserAccount": mock_auth,
    }

    form_data = {
        "name": "Borneo Eco Tours",
        "email": "borneo@example.com",
        "password": "SecretPassword123!",
        "confirmPassword": "SecretPassword123!",
        "companyName": "Borneo Eco Tours Sdn Bhd",
        "registrationNo": "202401099887",
        "businessContact": "+60123456789",
    }

    with patch.dict(app.view_functions["operator_fr01.register"].__globals__, patch_dict):
        response = client.post("/register", data=form_data)
        assert response.status_code == 200
        assert b"Unable to connect to TravelMate. Check your connection and try again." in response.data
        # Ensure password was not printed in response
        assert b"SecretPassword123!" not in response.data


# =========================================================================
# OP-REG-20: Auth Error Messages Sanitized & Non-Enumerating
# =========================================================================

def test_op_reg_20_auth_errors_sanitized(client):
    """OP-REG-20: Authentication error codes are mapped to safe, sanitized user-facing messages."""
    error_cases = [
        ("WEAK_PASSWORD", b"Password must be at least 8 characters with a mix of letters and numbers."),
        ("INVALID_EMAIL", b"Please enter a valid business email address."),
        ("TOO_MANY_ATTEMPTS_TRY_LATER", b"Too many failed attempts. Please try again later."),
    ]

    for err_code, expected_msg in error_cases:
        mock_auth = MagicMock(return_value=({"error": {"message": err_code}}, 400))
        patch_dict = {
            "createUserAccount": mock_auth,
        }
        with patch.dict(app.view_functions["operator_fr01.register"].__globals__, patch_dict):
            resp = client.post("/register", data={
                "name": "Test",
                "email": "test@test.com",
                "password": "Password123!",
                "confirmPassword": "Password123!",
                "companyName": "Test Co",
                "registrationNo": "12345",
                "businessContact": "12345",
            })
            assert resp.status_code == 200
            assert expected_msg in resp.data
