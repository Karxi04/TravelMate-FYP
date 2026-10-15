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
    if "request_rate_limiter" in app.extensions:
        app.extensions["request_rate_limiter"].reset()
    with app.test_client() as client:
        yield client


def _mock_firebase_success():
    return {
        "idToken": "fake_admin_token",
        "refreshToken": "fake_refresh_token",
        "localId": "fake_admin_uid",
        "expiresIn": "3600",
    }, 200


def _patch_admin(auth_return=_mock_firebase_success(), call_api_return=None, call_api_side_effect=None):
    mocks = {
        "authenticateCredentials": MagicMock(return_value=auth_return),
    }
    if call_api_side_effect is not None:
        mocks["call_api"] = MagicMock(side_effect=call_api_side_effect)
    elif call_api_return is not None:
        mocks["call_api"] = MagicMock(return_value=call_api_return)
    return patch.dict(app.view_functions["admin_fr01.login"].__globals__, mocks)


def test_admin_login_success(client):
    """Valid Admin account and matching role redirects to dashboard."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True, "profile": {"role": "admin", "name": "Admin User"}}

    with _patch_admin(call_api_return=mock_resp):
        response = client.post("/", data={"email": "admin@example.com", "password": "anyPassword123!"})

        assert response.status_code == 302
        assert "/admin/dashboard" in response.headers["Location"]
        with client.session_transaction() as sess:
            assert sess.get("id_token") == "fake_admin_token"
            assert sess.get("portal_role") == "admin"


def test_admin_login_normalized_role_administrator(client):
    """Admin role string 'administrator' is normalized and accepted."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True, "profile": {"role": " Administrator ", "name": "Admin User"}}

    with _patch_admin(call_api_return=mock_resp):
        response = client.post("/", data={"email": "admin@example.com", "password": "anyPassword123!"})

        assert response.status_code == 302
        assert "/admin/dashboard" in response.headers["Location"]


def test_admin_login_wrong_role_rejection(client):
    """Non-admin account (e.g. traveller) is rejected and session is cleared."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True, "profile": {"role": "traveller", "name": "Travel User"}}

    with _patch_admin(call_api_return=mock_resp):
        response = client.post("/", data={"email": "traveller@example.com", "password": "anyPassword123!"})

        assert response.status_code == 200
        assert b"This account is not an Administrator account." in response.data
        with client.session_transaction() as sess:
            assert sess.get("id_token") is None
            assert sess.get("portal_role") is None


def test_admin_login_invalid_credentials(client):
    """Invalid credentials from Firebase are cleanly reported."""
    fail_data = {"error": {"message": "INVALID_LOGIN_CREDENTIALS"}}

    with _patch_admin(auth_return=(fail_data, 400)):
        response = client.post("/", data={"email": "bad@example.com", "password": "wrong"})

        assert response.status_code == 200
        assert b"Invalid email or password." in response.data
        with client.session_transaction() as sess:
            assert sess.get("id_token") is None


def test_admin_login_backend_401(client):
    """Backend HTTP 401 reports session expired or invalid and clears session."""
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 401

    with _patch_admin(call_api_return=mock_resp):
        response = client.post("/", data={"email": "admin@example.com", "password": "anyPassword123!"})

        assert response.status_code == 200
        assert b"Authentication session expired or invalid." in response.data
        with client.session_transaction() as sess:
            assert sess.get("id_token") is None


def test_admin_login_backend_403(client):
    """Backend HTTP 403 reports session expired or invalid and clears session."""
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 403

    with _patch_admin(call_api_return=mock_resp):
        response = client.post("/", data={"email": "admin@example.com", "password": "anyPassword123!"})

        assert response.status_code == 200
        assert b"Authentication session expired or invalid." in response.data
        with client.session_transaction() as sess:
            assert sess.get("id_token") is None


def test_admin_login_backend_500(client):
    """Backend HTTP 500 reports service temporarily unavailable and clears session."""
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 500

    with _patch_admin(call_api_return=mock_resp):
        response = client.post("/", data={"email": "admin@example.com", "password": "anyPassword123!"})

        assert response.status_code == 200
        assert b"Backend service is temporarily unavailable." in response.data
        with client.session_transaction() as sess:
            assert sess.get("id_token") is None


def test_admin_login_backend_404(client):
    """Backend HTTP 404 reports unable to verify account and clears session."""
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 404

    with _patch_admin(call_api_return=mock_resp):
        response = client.post("/", data={"email": "admin@example.com", "password": "anyPassword123!"})

        assert response.status_code == 200
        assert b"Unable to verify account with backend service." in response.data
        with client.session_transaction() as sess:
            assert sess.get("id_token") is None


def test_admin_login_backend_timeout(client):
    """Backend connection timeout reports service unavailable and clears session."""
    with _patch_admin(call_api_side_effect=requests.Timeout("Connection timed out")):
        response = client.post("/", data={"email": "admin@example.com", "password": "anyPassword123!"})

        assert response.status_code == 200
        assert b"Backend service is temporarily unavailable." in response.data
        with client.session_transaction() as sess:
            assert sess.get("id_token") is None


def test_admin_login_missing_profile(client):
    """Missing user profile reports error and clears session."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True, "profile": None}

    with _patch_admin(call_api_return=mock_resp):
        response = client.post("/", data={"email": "admin@example.com", "password": "anyPassword123!"})

        assert response.status_code == 200
        assert b"User profile could not be found." in response.data
        with client.session_transaction() as sess:
            assert sess.get("id_token") is None


def test_admin_login_malformed_json(client):
    """Malformed JSON response from backend reports error and clears session."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.side_effect = ValueError("Invalid JSON")

    with _patch_admin(call_api_return=mock_resp):
        response = client.post("/", data={"email": "admin@example.com", "password": "anyPassword123!"})

        assert response.status_code == 200
        assert b"Received an invalid response from backend service." in response.data
        with client.session_transaction() as sess:
            assert sess.get("id_token") is None


def test_admin_csrf_protection():
    """CSRF protection rejects POST request when CSRF token is missing."""
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = True
    with app.test_client() as csrf_client:
        response = csrf_client.post("/", data={"email": "admin@example.com", "password": "anyPassword123!"})
        assert response.status_code == 400
