import os
import time
import requests
from flask import session
from firebase_auth_rest import refresh_id_token


def _ensure_token():
    token = session.get("id_token")
    refresh = session.get("refresh_token")
    expires_at = float(session.get("token_expires_at", 0) or 0)
    if refresh and expires_at and time.time() >= expires_at - 60:
        data, status = refresh_id_token(refresh)
        if status == 200:
            token = data.get("id_token")
            session["id_token"] = token
            session["refresh_token"] = data.get("refresh_token", refresh)
            session["token_expires_at"] = time.time() + int(data.get("expires_in", 3600))
    return token


def call_api(method, path, **kwargs):
    token = _ensure_token()
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    headers.setdefault("Accept", "application/json")
    url = os.getenv("BACKEND_URL", "http://127.0.0.1:5000").rstrip("/") + path
    return requests.request(method, url, headers=headers, timeout=60, **kwargs)
