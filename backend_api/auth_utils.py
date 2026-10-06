from functools import wraps
from flask import request, jsonify, g
from firebase_admin import auth
from firebase_service import get_db


APPROVED_OPERATOR_STATUSES = {"approved", "verified"}


def _error(message, status=401):
    return jsonify({"ok": False, "error": message}), status


def auth_required(roles=None):
    allowed_roles = set(roles or [])

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            header = request.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return _error("Missing Firebase ID token")

            token = header.split(" ", 1)[1].strip()
            try:
                decoded = auth.verify_id_token(token)
            except Exception:
                return _error("Invalid or expired Firebase ID token")

            uid = decoded["uid"]
            profile_ref = get_db().collection("users").document(uid)
            snap = profile_ref.get()
            profile = snap.to_dict() if snap.exists else None

            if profile and profile.get("status", "active") != "active":
                return _error("Account is deactivated", 403)

            raw_role = str(profile.get("role", "") if profile else "").strip().lower()
            role = raw_role
            if raw_role in {"operator", "tourism_operator"}:
                role = "operator"
            elif raw_role in {"admin", "administrator"}:
                role = "admin"
            elif raw_role in {"traveller", "traveler", "user"}:
                role = "traveller"

            if allowed_roles:
                role_matches = (role in allowed_roles) or (raw_role in allowed_roles)
                if not role_matches and role == "admin" and ("operator" in allowed_roles or "admin" in allowed_roles):
                    role_matches = True
                if not role_matches:
                    return _error("Insufficient role permission", 403)

                # Operator registration starts in the canonical `pending`
                # state. Protected operator APIs remain unavailable until an
                # Administrator approves the account. Administrators retain
                # their existing override for operator-management endpoints.
                if role == "operator" and "operator" in allowed_roles:
                    verification_status = str(
                        profile.get("verificationStatus", "pending")
                    ).strip().lower()
                    if verification_status not in APPROVED_OPERATOR_STATUSES:
                        return _error("Tourism Operator account is not verified", 403)

            g.uid = uid
            g.firebase_user = decoded
            g.profile = profile or {}
            g.role = role
            return fn(*args, **kwargs)

        return wrapper
    return decorator
