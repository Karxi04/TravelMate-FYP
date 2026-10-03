import pytest
from unittest.mock import patch, MagicMock
from app import create_app

@pytest.fixture
def app():
    app = create_app()
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
