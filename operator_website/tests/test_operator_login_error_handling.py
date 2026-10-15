import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import requests

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
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    if "request_rate_limiter" in app.extensions:
        app.extensions["request_rate_limiter"].reset()
    with app.test_client() as client:
        yield client


def _mock_firebase_success():
    return {
        "idToken": "fake_operator_token",
        "refreshToken": "fake_refresh_token",
        "localId": "fake_operator_uid",
        "expiresIn": "3600",
    }, 200


def _patch_operator(auth_return=_mock_firebase_success(), call_api_return=None, call_api_side_effect=None):
    mocks = {
        "authenticateCredentials": MagicMock(return_value=auth_return),
    }
    if call_api_side_effect is not None:
        mocks["call_api"] = MagicMock(side_effect=call_api_side_effect)
    elif call_api_return is not None:
        mocks["call_api"] = MagicMock(return_value=call_api_return)
    return patch.dict(app.view_functions["operator_fr01.login"].__globals__, mocks)


def test_operator_login_success(client):
    """Valid Operator account with approved verification redirects to dashboard."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "ok": True,
        "profile": {"role": "operator", "name": "Tour Operator", "verificationStatus": "approved"},
    }

    with _patch_operator(call_api_return=mock_resp):
        response = client.post("/", data={"email": "op@example.com", "password": "anyPassword123!"})

        assert response.status_code == 302
        assert "/dashboard" in response.headers["Location"]
        with client.session_transaction() as sess:
            assert sess.get("id_token") == "fake_operator_token"
            assert sess.get("portal_role") == "operator"
            assert sess.get("verification_status") == "approved"


def test_operator_login_normalized_role_tourism_operator(client):
    """Operator role string 'tourism_operator' is normalized and accepted."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "ok": True,
        "profile": {"role": " tourism_operator ", "name": "Tour Operator", "verificationStatus": "approved"},
    }

    with _patch_operator(call_api_return=mock_resp):
        response = client.post("/", data={"email": "op@example.com", "password": "anyPassword123!"})

        assert response.status_code == 302
        assert "/dashboard" in response.headers["Location"]


def test_operator_login_admin_override(client):
    """Admin role has override capability on Operator portal."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "ok": True,
        "profile": {"role": "admin", "name": "Admin Supervisor"},
    }

    with _patch_operator(call_api_return=mock_resp):
        response = client.post("/", data={"email": "admin@example.com", "password": "anyPassword123!"})

        assert response.status_code == 302
        assert "/dashboard" in response.headers["Location"]


def test_operator_login_pending_verification(client):
    """Operator with pending verification redirects to verification page."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "ok": True,
        "profile": {"role": "operator", "name": "New Operator", "verificationStatus": "pending"},
    }

    with _patch_operator(call_api_return=mock_resp):
        response = client.post("/", data={"email": "op@example.com", "password": "anyPassword123!"})

        assert response.status_code == 302
        assert "/verification" in response.headers["Location"]


def test_operator_login_rejected_verification(client):
    """Operator with rejected verification receives warning and redirects to verification page."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "ok": True,
        "profile": {"role": "operator", "name": "Rejected Operator", "verificationStatus": "rejected"},
    }

    with _patch_operator(call_api_return=mock_resp):
        response = client.post("/", data={"email": "op@example.com", "password": "anyPassword123!"})

        assert response.status_code == 302
        assert "/verification" in response.headers["Location"]


def test_operator_login_wrong_role_rejection(client):
    """Non-operator account (e.g. traveller) is rejected and session is cleared."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True, "profile": {"role": "traveller", "name": "Traveller"}}

    with _patch_operator(call_api_return=mock_resp):
        response = client.post("/", data={"email": "traveller@example.com", "password": "anyPassword123!"})

        assert response.status_code == 200
        assert b"This account is not a Tourism Operator account." in response.data
        with client.session_transaction() as sess:
            assert sess.get("id_token") is None
            assert sess.get("portal_role") is None


def test_operator_login_invalid_credentials(client):
    """Invalid credentials from Firebase are cleanly reported."""
    fail_data = {"error": {"message": "INVALID_LOGIN_CREDENTIALS"}}

    with _patch_operator(auth_return=(fail_data, 400)):
        response = client.post("/", data={"email": "bad@example.com", "password": "wrong"})

        assert response.status_code == 200
        assert b"Invalid email or password." in response.data
        with client.session_transaction() as sess:
            assert sess.get("id_token") is None


def test_operator_login_backend_401(client):
    """Backend HTTP 401 reports session expired or invalid and clears session."""
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 401

    with _patch_operator(call_api_return=mock_resp):
        response = client.post("/", data={"email": "op@example.com", "password": "anyPassword123!"})

        assert response.status_code == 200
        assert b"Authentication session expired or invalid." in response.data
        with client.session_transaction() as sess:
            assert sess.get("id_token") is None


def test_operator_login_backend_403(client):
    """Backend HTTP 403 reports session expired or invalid and clears session."""
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 403

    with _patch_operator(call_api_return=mock_resp):
        response = client.post("/", data={"email": "op@example.com", "password": "anyPassword123!"})

        assert response.status_code == 200
        assert b"Authentication session expired or invalid." in response.data
        with client.session_transaction() as sess:
            assert sess.get("id_token") is None


def test_operator_login_backend_500(client):
    """Backend HTTP 500 reports service temporarily unavailable and clears session."""
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 500

    with _patch_operator(call_api_return=mock_resp):
        response = client.post("/", data={"email": "op@example.com", "password": "anyPassword123!"})

        assert response.status_code == 200
        assert b"Backend service is temporarily unavailable." in response.data
        with client.session_transaction() as sess:
            assert sess.get("id_token") is None


def test_operator_login_backend_404(client):
    """Backend HTTP 404 reports unable to verify account and clears session."""
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 404

    with _patch_operator(call_api_return=mock_resp):
        response = client.post("/", data={"email": "op@example.com", "password": "anyPassword123!"})

        assert response.status_code == 200
        assert b"Unable to verify account with backend service." in response.data
        with client.session_transaction() as sess:
            assert sess.get("id_token") is None


def test_operator_login_backend_timeout(client):
    """Backend connection timeout reports service unavailable and clears session."""
    with _patch_operator(call_api_side_effect=requests.Timeout("Connection timed out")):
        response = client.post("/", data={"email": "op@example.com", "password": "anyPassword123!"})

        assert response.status_code == 200
        assert b"Backend service is temporarily unavailable." in response.data
        with client.session_transaction() as sess:
            assert sess.get("id_token") is None


def test_operator_login_missing_profile(client):
    """Missing user profile reports error and clears session."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True, "profile": None}

    with _patch_operator(call_api_return=mock_resp):
        response = client.post("/", data={"email": "op@example.com", "password": "anyPassword123!"})

        assert response.status_code == 200
        assert b"User profile could not be found." in response.data
        with client.session_transaction() as sess:
            assert sess.get("id_token") is None


def test_operator_login_malformed_json(client):
    """Malformed JSON response from backend reports error and clears session."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.side_effect = ValueError("Invalid JSON")

    with _patch_operator(call_api_return=mock_resp):
        response = client.post("/", data={"email": "op@example.com", "password": "anyPassword123!"})

        assert response.status_code == 200
        assert b"Received an invalid response from backend service." in response.data
        with client.session_transaction() as sess:
            assert sess.get("id_token") is None


def test_operator_csrf_protection():
    """CSRF protection rejects POST request when CSRF token is missing."""
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = True
    with app.test_client() as csrf_client:
        response = csrf_client.post("/", data={"email": "op@example.com", "password": "anyPassword123!"})
        assert response.status_code == 400
