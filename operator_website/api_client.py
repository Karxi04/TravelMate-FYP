import time
import requests
from flask import session
from firebase_auth_rest import refresh_id_token
from portal_security_config import backend_base_url


def _ensure_token(force_refresh=False):
    token = session.get("id_token")
    refresh = session.get("refresh_token")
    expires_at = float(session.get("token_expires_at", 0) or 0)
    if refresh and (force_refresh or (expires_at and time.time() >= expires_at - 60)):
        data, status = refresh_id_token(refresh)
        if status == 200:
            token = data.get("id_token")
            session["id_token"] = token
            session["refresh_token"] = data.get("refresh_token", refresh)
            session["token_expires_at"] = time.time() + int(data.get("expires_in", 3600))
        elif force_refresh:
            token = None
    return token


def call_api(method, path, **kwargs):
    try:
        token = _ensure_token()
        headers = kwargs.pop("headers", {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        headers.setdefault("Accept", "application/json")
        url = backend_base_url() + path
        response = requests.request(method, url, headers=headers, timeout=60, **kwargs)

        # Token expiry retry: if backend returns 401 and a refresh token exists, refresh and retry once
        if response.status_code == 401 and session.get("refresh_token"):
            refreshed_token = _ensure_token(force_refresh=True)
            if refreshed_token:
                headers["Authorization"] = f"Bearer {refreshed_token}"
                response = requests.request(method, url, headers=headers, timeout=60, **kwargs)

        return response
    except requests.RequestException:
        response = requests.Response()
        response.status_code = 503
        response.headers['Content-Type'] = 'application/json'
        response._content = b'{"ok":false,"error":"TravelMate is temporarily unavailable. Please try again."}'
        return response
