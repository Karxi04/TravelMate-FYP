import json
import os
import re
import uuid
from pathlib import Path

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
ALLOWED_MIMETYPES = {'image/jpeg', 'image/png', 'image/webp'}
MAX_FILE_SIZE = 8 * 1024 * 1024  # 8 MB

FILENAME_REGEX = re.compile(r'^[a-f0-9]{32}\.(jpg|jpeg|png|webp)$')


def get_upload_dir() -> Path:
    """Return the absolute path to the package images upload directory, creating it if needed."""
    custom_dir = os.getenv("PACKAGE_IMAGE_UPLOAD_DIR", "").strip()
    if custom_dir:
        path = Path(custom_dir)
    else:
        # Default to backend_api/static/uploads/package_images
        base = Path(__file__).resolve().parents[1]
        path = base / "static" / "uploads" / "package_images"
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_safe_filename(filename: str) -> bool:
    """Ensure the filename matches the strict 32-hex UUID + allowed extension pattern."""
    if not filename or not isinstance(filename, str):
        return False
    return bool(FILENAME_REGEX.match(filename.lower()))


def _detect_magic_bytes(header: bytes) -> str | None:
    """
    Inspect magic bytes to detect actual image format:
    - JPEG: 0xFF, 0xD8, 0xFF
    - PNG: 0x89, 'PNG\r\n\x1a\n'
    - WebP: 'RIFF' .... 'WEBP'
    """
    if len(header) >= 3 and header[:3] == b'\xff\xd8\xff':
        return 'image/jpeg'
    if len(header) >= 8 and header[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'
    if len(header) >= 12 and header[:4] == b'RIFF' and header[8:12] == b'WEBP':
        return 'image/webp'
    return None


def validate_image_file(file_storage) -> tuple[bool, str | None, str | None]:
    """
    Validate an uploaded file from Flask request.files.
    Returns (is_valid, error_message, normalized_extension).
    """
    if not file_storage or not getattr(file_storage, 'filename', None):
        return False, "No file selected.", None

    filename = file_storage.filename.strip()
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"Unsupported file extension '{ext}'. Only JPG, PNG, and WebP are allowed.", None

    # Check Content-Type header if present
    content_type = getattr(file_storage, 'content_type', '') or getattr(file_storage, 'mimetype', '')
    content_type = content_type.lower()
    if content_type and content_type not in ALLOWED_MIMETYPES and content_type != 'application/octet-stream':
        return False, f"Invalid MIME type '{content_type}'. Must be image/jpeg, image/png, or image/webp.", None

    # Read header and check file size
    stream = file_storage.stream
    stream.seek(0)
    header = stream.read(512)
    stream.seek(0, os.SEEK_END)
    file_size = stream.tell()
    stream.seek(0)

    if file_size == 0:
        return False, "The uploaded file is empty.", None

    if file_size > MAX_FILE_SIZE:
        return False, f"File size ({file_size / (1024 * 1024):.1f}MB) exceeds the 8MB limit.", None

    detected_mime = _detect_magic_bytes(header)
    if not detected_mime:
        return False, "File content is not a recognized JPEG, PNG, or WebP image.", None

    # Normalize extension
    if detected_mime == 'image/jpeg' and ext not in ('.jpg', '.jpeg'):
        ext = '.jpg'
    elif detected_mime == 'image/png' and ext != '.png':
        ext = '.png'
    elif detected_mime == 'image/webp' and ext != '.webp':
        ext = '.webp'

    if ext == '.jpeg':
        ext = '.jpg'

    return True, None, ext


def save_image_file(file_storage, ext: str, host_url: str | None = None) -> tuple[str, str]:
    """
    Save the validated file stream to disk with a random UUID filename.
    Returns (filename, public_url).
    """
    filename = f"{uuid.uuid4().hex}{ext}"
    upload_dir = get_upload_dir()
    target_path = upload_dir / filename

    file_storage.seek(0)
    with open(target_path, "wb") as f:
        while True:
            chunk = file_storage.stream.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)

    url = get_public_image_url(filename, host_url=host_url)
    return filename, url


def get_public_image_url(filename: str, host_url: str | None = None) -> str:
    """
    Generate authoritative public URL for the uploaded image.
    Prefers PUBLIC_IMAGE_BASE_URL, then STRIPE_CHECKOUT_RETURN_ORIGIN, then host_url,
    defaulting to http://127.0.0.1:5000.
    """
    base_url = (os.getenv("PUBLIC_IMAGE_BASE_URL") or "").strip().rstrip("/")
    if not base_url:
        base_url = (os.getenv("STRIPE_CHECKOUT_RETURN_ORIGIN") or "").strip().rstrip("/")
    if not base_url and host_url:
        base_url = host_url.rstrip("/")
    if not base_url:
        base_url = "http://127.0.0.1:5000"

    return f"{base_url}/api/public/package-images/{filename}"


def save_image_metadata(filename: str, owner_id: str, original_name: str = "") -> dict:
    """Save trusted server-side metadata for an uploaded image file."""
    if not is_safe_filename(filename):
        raise ValueError(f"Invalid image filename: {filename}")
    from utils import utc_now_iso
    upload_dir = get_upload_dir()
    meta_path = upload_dir / f"{filename}.meta.json"
    meta = {
        "filename": filename,
        "ownerId": str(owner_id or "").strip(),
        "uploadedAt": utc_now_iso(),
        "originalName": str(original_name or "").strip(),
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f)
    return meta


def get_image_metadata(filename: str) -> dict | None:
    """Retrieve trusted server-side metadata for an uploaded image file."""
    if not is_safe_filename(filename):
        return None
    upload_dir = get_upload_dir()
    meta_path = upload_dir / f"{filename}.meta.json"
    if not meta_path.is_file():
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def delete_image_file(filename: str) -> bool:
    """Safely delete an uploaded image file and its metadata sidecar if they exist."""
    if not is_safe_filename(filename):
        return False
    upload_dir = get_upload_dir()
    target = upload_dir / filename
    meta_target = upload_dir / f"{filename}.meta.json"
    deleted = False
    if target.is_file():
        try:
            target.unlink()
            deleted = True
        except OSError:
            pass
    if meta_target.is_file():
        try:
            meta_target.unlink()
        except OSError:
            pass
    return deleted


def find_image_references(filename: str) -> tuple[list, list]:
    """
    Search tourism_packages and promotional_campaigns for references to this filename.
    Returns (package_refs, campaign_refs).
    """
    from sequence_contract.firebase_firestore import retrieveRecord

    def _contains_image(val):
        if not val:
            return False
        if isinstance(val, str):
            return filename in val
        if isinstance(val, (list, tuple, set)):
            return any(_contains_image(x) for x in val)
        if isinstance(val, dict):
            return any(_contains_image(v) for v in val.values())
        return False

    package_refs = []
    try:
        packages = retrieveRecord('tourism_packages') or []
        for pkg in packages:
            if not isinstance(pkg, dict):
                continue
            if (
                _contains_image(pkg.get('heroImage'))
                or _contains_image(pkg.get('imageUrl'))
                or _contains_image(pkg.get('galleryImages'))
                or _contains_image(pkg.get('itineraryDays'))
            ):
                package_refs.append(pkg)
    except Exception:
        pass

    campaign_refs = []
    try:
        campaigns = retrieveRecord('promotional_campaigns') or []
        for camp in campaigns:
            if not isinstance(camp, dict):
                continue
            if (
                _contains_image(camp.get('bannerImageUrl'))
                or _contains_image(camp.get('packageImageUrl'))
            ):
                campaign_refs.append(camp)
    except Exception:
        pass

    return package_refs, campaign_refs


def verify_image_deletion_permission(filename: str, current_operator_id: str, is_admin: bool = False) -> tuple[bool, int, str]:
    """
    Verify whether the requesting operator or admin is authorized to delete the image.
    Enforces:
    - Valid filename (400)
    - Image exists on disk (404)
    - Not referenced by another operator's package (403)
    - Not referenced by an approved/active package (409)
    - Not referenced by any package of current operator (409)
    - Not referenced by another operator's campaign (403)
    - Not referenced by an approved/active campaign (409)
    - Not referenced by any campaign of current operator (409)
    - If metadata exists: owner must match requesting operator (403 if mismatch)
    - If legacy image with no metadata: fails closed for operators (403), allowed for admins
    Returns (allowed, status_code, error_message).
    """
    if not is_safe_filename(filename):
        return False, 400, "Invalid image filename"

    upload_dir = get_upload_dir()
    target_path = upload_dir / filename
    if not target_path.is_file():
        return False, 404, "Image file not found"

    package_refs, campaign_refs = find_image_references(filename)

    for pkg in package_refs:
        pkg_owner = pkg.get('operatorId')
        if pkg_owner and pkg_owner != current_operator_id and not is_admin:
            return False, 403, "Image is referenced by another operator's package"

    for pkg in package_refs:
        status = str(pkg.get('approvalStatus') or '').lower()
        if status in {'approved', 'active'} and not is_admin:
            return False, 409, "Image is referenced by an active or approved package and cannot be deleted"

    if package_refs and not is_admin:
        return False, 409, "Image is currently referenced by a tourism package and cannot be deleted"

    for camp in campaign_refs:
        camp_owner = camp.get('operatorId')
        if camp_owner and camp_owner != current_operator_id and not is_admin:
            return False, 403, "Image is referenced by another operator's campaign"
        review_status = str(camp.get('reviewStatus') or '').lower()
        camp_status = str(camp.get('campaignStatus') or '').lower()
        if (review_status == 'approved' or camp_status in {'active', 'approved'}) and not is_admin:
            return False, 409, "Image is referenced by an active or approved campaign and cannot be deleted"

    if campaign_refs and not is_admin:
        return False, 409, "Image is currently referenced by a promotional campaign and cannot be deleted"

    meta = get_image_metadata(filename)
    if not meta:
        if not is_admin:
            return False, 403, "Image ownership could not be verified"
    else:
        owner_id = meta.get('ownerId')
        if owner_id and owner_id != current_operator_id and not is_admin:
            return False, 403, "You do not have permission to delete this image"

    return True, 200, ""
