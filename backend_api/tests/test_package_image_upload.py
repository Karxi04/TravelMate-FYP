import io
import os
import shutil
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from services.image_storage_service import (
    get_upload_dir,
    validate_image_file,
    save_image_file,
    is_safe_filename,
    delete_image_file,
)
from services.package_service import normalise_package, package_for_read
from services.public_content_projection import public_package


# Sample minimal valid image bytes
# 1x1 transparent PNG
SAMPLE_PNG_BYTES = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4'
    b'\x00\x00\x00\x00IEND\xaeB`\x82'
)

# 1x1 JPEG minimal bytes
SAMPLE_JPEG_BYTES = (
    b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00'
    b'\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t'
    b'\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00'
    b'\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00'
    b'\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00'
    b'\xff\xd9'
)

# Minimal WebP bytes
SAMPLE_WEBP_BYTES = (
    b'RIFF\x1a\x00\x00\x00WEBPVP8 \x0e\x00\x00\x00'
    b'\x30\x01\x00\x9d\x01\x2a\x01\x00\x01\x00\x02\x00\x34\x25'
)


@pytest.fixture
def temp_upload_dir(monkeypatch):
    temp_dir = tempfile.mkdtemp()
    monkeypatch.setenv("PACKAGE_IMAGE_UPLOAD_DIR", temp_dir)
    monkeypatch.setenv("PUBLIC_IMAGE_BASE_URL", "http://172.20.10.5:5000")
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


# =========================================================================
# 1. UNIT TESTS: IMAGE STORAGE SERVICE
# =========================================================================

def test_is_safe_filename():
    assert is_safe_filename("a" * 32 + ".png")
    assert is_safe_filename("0123456789abcdef0123456789abcdef.jpg")
    assert is_safe_filename("0123456789abcdef0123456789abcdef.webp")
    assert not is_safe_filename("../../etc/passwd")
    assert not is_safe_filename("evil.exe")
    assert not is_safe_filename("script.js")
    assert not is_safe_filename("short.png")
    assert not is_safe_filename("")
    assert not is_safe_filename(None)


def test_validate_image_file_valid_png():
    storage = MagicMock()
    storage.filename = "penang_cover.png"
    storage.content_type = "image/png"
    storage.stream = io.BytesIO(SAMPLE_PNG_BYTES)

    ok, err, ext = validate_image_file(storage)
    assert ok is True
    assert err is None
    assert ext == ".png"


def test_validate_image_file_valid_jpeg():
    storage = MagicMock()
    storage.filename = "georgetown.jpeg"
    storage.content_type = "image/jpeg"
    storage.stream = io.BytesIO(SAMPLE_JPEG_BYTES)

    ok, err, ext = validate_image_file(storage)
    assert ok is True
    assert err is None
    assert ext == ".jpg"


def test_validate_image_file_valid_webp():
    storage = MagicMock()
    storage.filename = "food.webp"
    storage.content_type = "image/webp"
    storage.stream = io.BytesIO(SAMPLE_WEBP_BYTES)

    ok, err, ext = validate_image_file(storage)
    assert ok is True
    assert err is None
    assert ext == ".webp"


def test_validate_image_file_invalid_extension():
    storage = MagicMock()
    storage.filename = "malware.exe"
    storage.content_type = "application/x-msdownload"
    storage.stream = io.BytesIO(b"MZ\x90\x00")

    ok, err, ext = validate_image_file(storage)
    assert ok is False
    assert "Unsupported file extension" in err


def test_validate_image_file_fake_extension_magic_bytes_rejected():
    # File named .png but contains text / executable content
    storage = MagicMock()
    storage.filename = "fake_image.png"
    storage.content_type = "image/png"
    storage.stream = io.BytesIO(b"Hello world, I am not an image!")

    ok, err, ext = validate_image_file(storage)
    assert ok is False
    assert "not a recognized JPEG, PNG, or WebP" in err


def test_validate_image_file_oversized_rejected():
    storage = MagicMock()
    storage.filename = "giant.png"
    storage.content_type = "image/png"
    # Create stream reporting size > 8MB
    oversized = io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * (9 * 1024 * 1024))
    storage.stream = oversized

    ok, err, ext = validate_image_file(storage)
    assert ok is False
    assert "exceeds the 8MB limit" in err


def test_save_and_delete_image_file(temp_upload_dir):
    storage = MagicMock()
    storage.filename = "test.png"
    storage.stream = io.BytesIO(SAMPLE_PNG_BYTES)

    filename, url = save_image_file(storage, ".png")
    assert filename.endswith(".png")
    assert url == f"http://172.20.10.5:5000/api/public/package-images/{filename}"

    file_path = os.path.join(temp_upload_dir, filename)
    assert os.path.isfile(file_path)

    deleted = delete_image_file(filename)
    assert deleted is True
    assert not os.path.isfile(file_path)


# =========================================================================
# 2. INTEGRATION TESTS: BACKEND API ENDPOINTS
# =========================================================================

def test_operator_upload_unauthorized(client):
    response = client.post("/api/fr12/package-images/upload")
    assert response.status_code in (401, 403)


def test_traveller_cannot_upload_package_image(client, mock_traveller_auth):
    data = {
        'file': (io.BytesIO(SAMPLE_PNG_BYTES), 'test.png', 'image/png')
    }
    response = client.post(
        "/api/fr12/package-images/upload",
        data=data,
        content_type='multipart/form-data',
        headers={'Authorization': 'Bearer valid_traveller_token'},
    )
    assert response.status_code == 403


def test_operator_upload_missing_file(client, mock_operator_auth):
    response = client.post(
        "/api/fr12/package-images/upload",
        data={},
        content_type='multipart/form-data',
        headers={'Authorization': 'Bearer valid_op_token'},
    )
    assert response.status_code == 400
    assert response.get_json()['error'] == 'No image file provided'


def test_operator_upload_valid_png(client, mock_operator_auth, temp_upload_dir):
    data = {
        'file': (io.BytesIO(SAMPLE_PNG_BYTES), 'georgetown_cover.png', 'image/png')
    }
    response = client.post(
        "/api/fr12/package-images/upload",
        data=data,
        content_type='multipart/form-data',
        headers={'Authorization': 'Bearer valid_op_token'},
    )
    assert response.status_code == 201
    body = response.get_json()
    assert body['ok'] is True
    assert body['filename'].endswith('.png')
    assert '/api/public/package-images/' in body['url']

    # Now verify public retrieval endpoint
    filename = body['filename']
    pub_resp = client.get(f"/api/public/package-images/{filename}")
    assert pub_resp.status_code == 200
    assert pub_resp.data == SAMPLE_PNG_BYTES
    assert 'max-age=86400' in pub_resp.headers.get('Cache-Control', '')


def test_operator_upload_valid_jpeg(client, mock_operator_auth, temp_upload_dir):
    data = {
        'file': (io.BytesIO(SAMPLE_JPEG_BYTES), 'street_art.jpg', 'image/jpeg')
    }
    response = client.post(
        "/api/fr12/package-images/upload",
        data=data,
        content_type='multipart/form-data',
        headers={'Authorization': 'Bearer valid_op_token'},
    )
    assert response.status_code == 201
    body = response.get_json()
    assert body['ok'] is True
    assert body['filename'].endswith('.jpg')

    pub_resp = client.get(f"/api/public/package-images/{body['filename']}")
    assert pub_resp.status_code == 200
    assert pub_resp.data == SAMPLE_JPEG_BYTES


def test_public_serving_not_found(client, temp_upload_dir):
    fake_filename = "0" * 32 + ".png"
    response = client.get(f"/api/public/package-images/{fake_filename}")
    assert response.status_code == 404
    assert response.get_json()['error'] == 'Image not found'


def test_public_serving_invalid_filename_traversal_rejected(client, temp_upload_dir):
    response = client.get("/api/public/package-images/..%2F..%2Fetc%2Fpasswd")
    assert response.status_code in (400, 404)


def test_operator_delete_image(client, mock_operator_auth, temp_upload_dir):
    # Upload first
    data = {'file': (io.BytesIO(SAMPLE_PNG_BYTES), 'to_delete.png', 'image/png')}
    upload_res = client.post(
        "/api/fr12/package-images/upload",
        data=data,
        content_type='multipart/form-data',
        headers={'Authorization': 'Bearer valid_op_token'},
    )
    filename = upload_res.get_json()['filename']

    # Delete
    del_res = client.delete(
        f"/api/fr12/package-images/{filename}",
        headers={'Authorization': 'Bearer valid_op_token'},
    )
    assert del_res.status_code == 200
    assert del_res.get_json()['ok'] is True
    assert del_res.get_json()['deleted'] is True

    # Check that public serving now returns 404
    check_res = client.get(f"/api/public/package-images/{filename}")
    assert check_res.status_code == 404


# =========================================================================
# 3. PACKAGE SCHEMA PERSISTENCE, REOPENING & PROJECTION
# =========================================================================

def test_package_normalization_retains_hero_and_gallery():
    payload = {
        'title': 'Penang Heritage Walk',
        'destination': 'George Town, Penang',
        'heroImage': 'http://172.20.10.5:5000/api/public/package-images/abc123.jpg',
        'galleryImages': [
            'http://172.20.10.5:5000/api/public/package-images/gallery1.jpg',
            'http://172.20.10.5:5000/api/public/package-images/gallery2.jpg',
            'https://images.unsplash.com/photo-legacy',
        ],
        'adultPrice': 150.0,
        'durationDays': 2,
    }
    normalized = normalise_package(payload)
    assert normalized['heroImage'] == 'http://172.20.10.5:5000/api/public/package-images/abc123.jpg'
    assert normalized['imageUrl'] == 'http://172.20.10.5:5000/api/public/package-images/abc123.jpg'
    assert len(normalized['galleryImages']) == 3
    assert normalized['galleryImages'][0] == 'http://172.20.10.5:5000/api/public/package-images/gallery1.jpg'
    assert normalized['galleryImages'][2] == 'https://images.unsplash.com/photo-legacy'


def test_package_update_preserves_images_when_editing_unrelated_fields():
    existing = {
        'id': 'pkg-1',
        'operatorId': 'test_operator_uid',
        'title': 'Original Title',
        'destination': 'George Town, Penang',
        'heroImage': 'http://172.20.10.5:5000/api/public/package-images/cover.jpg',
        'galleryImages': [
            'http://172.20.10.5:5000/api/public/package-images/photo1.jpg',
            'http://172.20.10.5:5000/api/public/package-images/photo2.jpg',
        ],
        'adultPrice': 100.0,
        'durationDays': 1,
    }
    # Operator edits title and price, sending existing heroImage and galleryImages
    update_payload = {
        'title': 'Updated Title',
        'adultPrice': 120.0,
        'heroImage': existing['heroImage'],
        'galleryImages': existing['galleryImages'],
    }
    merged = normalise_package(update_payload, existing=existing)
    assert merged['title'] == 'Updated Title'
    assert merged['adultPrice'] == 120.0
    assert merged['heroImage'] == existing['heroImage']
    assert merged['galleryImages'] == existing['galleryImages']


def test_gallery_ordering_preserved():
    # Operator reorders gallery: photo2 before photo1
    payload = {
        'title': 'Test Package',
        'destination': 'George Town',
        'galleryImages': [
            'http://172.20.10.5:5000/api/public/package-images/photo2.jpg',
            'http://172.20.10.5:5000/api/public/package-images/photo1.jpg',
        ],
    }
    normalized = normalise_package(payload)
    assert normalized['galleryImages'] == [
        'http://172.20.10.5:5000/api/public/package-images/photo2.jpg',
        'http://172.20.10.5:5000/api/public/package-images/photo1.jpg',
    ]


def test_public_package_projection_retains_hero_and_gallery():
    package = {
        'id': 'pkg-approved',
        'title': 'Penang Discovery',
        'destination': 'George Town, Penang',
        'heroImage': 'http://172.20.10.5:5000/api/public/package-images/hero.jpg',
        'galleryImages': [
            'http://172.20.10.5:5000/api/public/package-images/g1.jpg',
            'http://172.20.10.5:5000/api/public/package-images/g2.jpg',
        ],
        'adultPrice': 200.0,
        'durationDays': 3,
        'approvalStatus': 'approved',
    }
    projected = public_package(package)
    assert projected['heroImage'] == 'http://172.20.10.5:5000/api/public/package-images/hero.jpg'
    assert projected['imageUrl'] == 'http://172.20.10.5:5000/api/public/package-images/hero.jpg'
    assert projected['galleryImages'] == [
        'http://172.20.10.5:5000/api/public/package-images/g1.jpg',
        'http://172.20.10.5:5000/api/public/package-images/g2.jpg',
    ]
