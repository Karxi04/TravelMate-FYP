import hashlib
import re
from requests import Timeout as RequestsTimeout


ATTEMPT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


def normalize_attempt_id(value, field_name):
    attempt_id = str(value or "").strip()
    if not ATTEMPT_ID_PATTERN.fullmatch(attempt_id):
        raise ValueError(
            f"{field_name} must contain 8-128 letters, numbers, underscores or hyphens"
        )
    return attempt_id


def operation_document_id(kind, uid, attempt_id, stage=""):
    digest = hashlib.sha256(
        f"travelmate|{kind}|{uid}|{attempt_id}|{stage}".encode("utf-8")
    ).hexdigest()
    return f"{kind}_{digest[:40]}"


def provider_idempotency_key(kind, uid, attempt_id, stage):
    """Return an opaque provider-visible key without exposing the Firebase UID."""
    digest = hashlib.sha256(
        f"travelmate-provider|{kind}|{uid}|{attempt_id}|{stage}".encode("utf-8")
    ).hexdigest()
    return f"tm_{kind}_{stage}_{digest[:32]}"


def is_ambiguous_provider_error(exc):
    if isinstance(exc, (TimeoutError, RequestsTimeout)):
        return True
    # Avoid importing a provider SDK here. Stripe API connection errors and
    # equivalent transport failures use these stable class names.
    return exc.__class__.__name__ in {
        "APIConnectionError",
        "ConnectionError",
        "ConnectTimeout",
        "ReadTimeout",
    }
