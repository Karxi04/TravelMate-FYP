import io
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

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


def _patch_upload(mock_call):
    fn_globals = app.view_functions["operator_fr12.upload_package_image_proxy"].__globals__
    return patch.dict(fn_globals, {"call_api": mock_call})


def test_portal_upload_image_unauthorized(unauth_client):
    response = unauth_client.post("/packages/upload-image")
    assert response.status_code == 401
    assert response.get_json()["error"] == "Unauthorized"


def test_portal_upload_image_missing_file(auth_client):
    response = auth_client.post("/packages/upload-image", data={})
    assert response.status_code == 400
    assert response.get_json()["error"] == "No image file provided"


def test_portal_upload_image_success(auth_client):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 201
    mock_resp.json.return_value = {
        "ok": True,
        "filename": "12345678901234567890123456789012.png",
        "url": "http://172.20.10.5:5000/api/public/package-images/12345678901234567890123456789012.png",
    }
    mock_call = MagicMock(return_value=mock_resp)

    with _patch_upload(mock_call):
        data = {
            "file": (io.BytesIO(b"\x89PNG\r\n\x1a\n"), "cover.png", "image/png"),
        }
        response = auth_client.post(
            "/packages/upload-image",
            data=data,
            content_type="multipart/form-data",
        )
        assert response.status_code == 201
        body = response.get_json()
        assert body["ok"] is True
        assert body["filename"] == "12345678901234567890123456789012.png"
        assert body["url"].startswith("http://172.20.10.5:5000/api/public/package-images/")

        mock_call.assert_called_once()
        args, kwargs = mock_call.call_args
        assert args[0] == "POST"
        assert args[1] == "/api/fr12/package-images/upload"
        assert "files" in kwargs


def test_portal_upload_image_backend_error_forwarded(auth_client):
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 400
    mock_resp.json.return_value = {
        "ok": False,
        "error": "File size exceeds the 8MB limit.",
    }
    mock_call = MagicMock(return_value=mock_resp)

    with _patch_upload(mock_call):
        data = {
            "file": (io.BytesIO(b"fake data"), "oversized.png", "image/png"),
        }
        response = auth_client.post(
            "/packages/upload-image",
            data=data,
            content_type="multipart/form-data",
        )
        assert response.status_code == 400
        body = response.get_json()
        assert body["ok"] is False
        assert body["error"] == "File size exceeds the 8MB limit."



def test_package_form_renders_image_upload_and_gallery_controls(auth_client):
    response = auth_client.get("/packages/new")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # Cover image upload components
    assert 'id="cover-dropzone"' in html
    assert 'id="cover-file-input"' in html
    assert 'name="heroImage"' in html
    assert 'id="btn-replace-cover"' in html
    assert 'id="btn-remove-cover"' in html

    # Gallery management components
    assert 'id="gallery-cards-grid"' in html
    assert 'id="gallery-file-input"' in html
    assert 'id="btn-gallery-browse-trigger"' in html
    assert 'name="galleryImages"' in html


def test_package_form_populates_existing_images(auth_client):
    pkg_item = {
        "id": "pkg-existing",
        "title": "George Town Food Walk",
        "destination": "George Town, Penang",
        "heroImage": "http://172.20.10.5:5000/api/public/package-images/cover.jpg",
        "galleryImages": [
            "http://172.20.10.5:5000/api/public/package-images/g1.jpg",
            "http://172.20.10.5:5000/api/public/package-images/g2.jpg",
        ],
        "durationDays": 2,
        "adultPrice": 120.0,
    }

    with auth_client.session_transaction() as sess:
        sess["id_token"] = "valid_test_op_token"

    # Render template with item
    from flask import render_template
    with app.test_request_context("/packages/pkg-existing/edit"):
        html = render_template(
            "fr12_tourism_operator_management/_package_form.html",
            item=pkg_item,
            form=pkg_item,
        )
        assert 'http://172.20.10.5:5000/api/public/package-images/cover.jpg' in html
        assert 'http://172.20.10.5:5000/api/public/package-images/g1.jpg' in html
        assert 'http://172.20.10.5:5000/api/public/package-images/g2.jpg' in html
