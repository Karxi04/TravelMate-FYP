import os

import pytest
from unittest.mock import patch, MagicMock

# These values must be set before importing app because app.py loads .env at
# import time. An empty value prevents a developer's local credentials from
# becoming active during the default test suite.
os.environ["TRAVELMATE_TESTING"] = "true"
os.environ["FALLBACK_MODE"] = "true"
for _provider_key in (
    "FIREBASE_SERVICE_ACCOUNT",
    "FIREBASE_SERVICE_ACCOUNT_JSON",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "SERPAPI_KEY",
    "LITEAPI_KEY",
    "STRIPE_SECRET_KEY",
    "GEMINI_API_KEY",
):
    os.environ[_provider_key] = ""

from app import create_app


def _blocked_live_service(*_args, **_kwargs):
    raise AssertionError(
        "Live Firebase/provider access is disabled in the default pytest suite. "
        "Use a deterministic test double, or mark an explicit manual test as integration."
    )


@pytest.fixture(autouse=True)
def block_live_firebase(monkeypatch):
    """Fail fast if a regression test misses its Firebase test double."""
    monkeypatch.setattr("firebase_service.get_db", _blocked_live_service)
    monkeypatch.setattr(
        "sequence_contract.firebase_firestore.get_db",
        _blocked_live_service,
    )
    monkeypatch.setattr("auth_utils.get_db", _blocked_live_service)
    monkeypatch.setattr("auth_utils.auth.verify_id_token", _blocked_live_service)
    monkeypatch.setattr(
        "firebase_admin.auth.update_user",
        _blocked_live_service,
    )


@pytest.fixture
def app():
    # create_app() normally initializes the Firebase Admin SDK. Unit/regression
    # tests instead mock the persistence/authentication boundaries they exercise.
    with patch("app.init_firebase") as mock_init_firebase:
        app = create_app()
    mock_init_firebase.assert_called_once_with()
    app.config.update({"TESTING": True})
    return app

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def mock_traveller_auth():
    with patch("auth_utils.auth.verify_id_token") as mock_verify, \
         patch("auth_utils.get_db") as mock_get_db:
        mock_verify.return_value = {
            "uid": "test_traveller_uid",
            "email": "traveller@test.com",
            "name": "Test Traveller"
        }
        mock_doc = MagicMock()
        mock_snap = MagicMock()
        mock_snap.exists = True
        mock_snap.to_dict.return_value = {
            "uid": "test_traveller_uid",
            "email": "traveller@test.com",
            "name": "Test Traveller",
            "role": "traveller",
            "status": "active"
        }
        mock_doc.get.return_value = mock_snap
        mock_coll = MagicMock()
        mock_coll.document.return_value = mock_doc
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_coll
        mock_get_db.return_value = mock_db
        yield mock_verify

@pytest.fixture
def mock_operator_auth():
    with patch("auth_utils.auth.verify_id_token") as mock_verify, \
         patch("auth_utils.get_db") as mock_get_db:
        mock_verify.return_value = {
            "uid": "test_operator_uid",
            "email": "operator@test.com",
            "name": "Test Operator"
        }
        mock_doc = MagicMock()
        mock_snap = MagicMock()
        mock_snap.exists = True
        mock_snap.to_dict.return_value = {
            "uid": "test_operator_uid",
            "email": "operator@test.com",
            "name": "Test Operator",
            "role": "operator",
            "status": "active",
            "verificationStatus": "approved"
        }
        mock_doc.get.return_value = mock_snap
        mock_coll = MagicMock()
        mock_coll.document.return_value = mock_doc
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_coll
        mock_get_db.return_value = mock_db
        yield mock_verify

@pytest.fixture
def mock_admin_auth():
    with patch("auth_utils.auth.verify_id_token") as mock_verify, \
         patch("auth_utils.get_db") as mock_get_db:
        mock_verify.return_value = {
            "uid": "test_admin_uid",
            "email": "admin@test.com",
            "name": "Test Admin"
        }
        mock_doc = MagicMock()
        mock_snap = MagicMock()
        mock_snap.exists = True
        mock_snap.to_dict.return_value = {
            "uid": "test_admin_uid",
            "email": "admin@test.com",
            "name": "Test Admin",
            "role": "admin",
            "status": "active"
        }
        mock_doc.get.return_value = mock_snap
        mock_coll = MagicMock()
        mock_coll.document.return_value = mock_doc
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_coll
        mock_get_db.return_value = mock_db
        yield mock_verify
