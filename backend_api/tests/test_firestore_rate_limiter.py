from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from unittest.mock import patch

import pytest
from flask import Flask

from request_rate_limit import (
    FirestoreFixedWindowLimiter,
    RateLimitStoreUnavailable,
    _request_identity,
    init_rate_limiter,
    rate_limit_response,
)


class _Snapshot:
    def __init__(self, value):
        self.exists = value is not None
        self._value = value

    def to_dict(self):
        return dict(self._value) if self._value is not None else None


class _Document:
    def __init__(self, store, document_id):
        self.store = store
        self.document_id = document_id

    def get(self, transaction=None):
        return _Snapshot(self.store.records.get(self.document_id))


class _Collection:
    def __init__(self, store):
        self.store = store

    def document(self, document_id):
        return _Document(self.store, document_id)


class _Transaction:
    def __init__(self, store):
        self.store = store

    def set(self, document, value):
        self.store.records[document.document_id] = dict(value)


class MemoryFirestore:
    """Transaction-faithful test double shared by multiple limiter instances."""

    def __init__(self):
        self.records = {}
        self._lock = Lock()

    def collection(self, name):
        assert name == "rate_limit_windows"
        return _Collection(self)

    def run_transaction(self, operation):
        with self._lock:
            return operation(_Transaction(self))


def _limiter(store, now, limit=6):
    return FirestoreFixedWindowLimiter(
        lambda: store,
        limits={"recommendation": limit},
        window_seconds=60,
        retention_seconds=3600,
        clock=lambda: now[0],
        transaction_runner=store.run_transaction,
    )


def test_shared_firestore_transaction_is_atomic_across_limiter_instances():
    now = [1200]
    store = MemoryFirestore()
    first = _limiter(store, now)
    second = _limiter(store, now)

    with ThreadPoolExecutor(max_workers=12) as workers:
        results = list(workers.map(
            lambda index: (first if index % 2 else second).consume("recommendation", "uid:traveller"),
            range(30),
        ))

    assert results.count(0) == 6
    assert results.count(60) == 24
    assert len(store.records) == 1


def test_shared_firestore_limiter_resets_at_fixed_window_and_hashes_identity():
    now = [1200]
    store = MemoryFirestore()
    limiter = _limiter(store, now, limit=1)

    assert limiter.consume("recommendation", "uid:traveller-secret") == 0
    assert limiter.consume("recommendation", "uid:traveller-secret") == 60
    document_id, record = next(iter(store.records.items()))
    assert "traveller-secret" not in document_id
    assert "traveller-secret" not in repr(record)
    assert record["count"] == 1
    assert record["expiresAt"].tzinfo is not None

    now[0] = 1259
    assert limiter.consume("recommendation", "uid:traveller-secret") == 1
    now[0] = 1260
    assert limiter.consume("recommendation", "uid:traveller-secret") == 0


def test_production_backend_uses_shared_limiter_and_portal_style_init_stays_local(monkeypatch):
    monkeypatch.delenv("TRAVELMATE_TESTING", raising=False)
    backend = Flask("backend")
    init_rate_limiter(backend, db_factory=lambda: MemoryFirestore())
    assert isinstance(backend.extensions["request_rate_limiter"], FirestoreFixedWindowLimiter)

    portal = Flask("portal")
    init_rate_limiter(portal)
    assert type(portal.extensions["request_rate_limiter"]).__name__ == "ProcessLocalLimiter"


def test_rate_limit_response_has_retry_after_and_ignores_spoofed_forwarded_ip():
    now = [1200]
    store = MemoryFirestore()
    limiter = _limiter(store, now, limit=1)
    app = Flask("response")
    app.extensions["request_rate_limiter"] = limiter

    with app.test_request_context(
        "/api/fr4/recommendations/generate",
        headers={"X-Forwarded-For": "198.51.100.9"},
        environ_base={"REMOTE_ADDR": "192.0.2.44"},
    ):
        assert _request_identity(None) == "network:192.0.2.44"
        assert rate_limit_response("recommendation", "traveller") is None
        response = rate_limit_response("recommendation", "traveller")

    assert response.status_code == 429
    assert response.get_json()["retryAfterSeconds"] == 60
    assert response.headers["Retry-After"] == "60"
    assert response.headers["Cache-Control"] == "no-store"


def test_firestore_failure_fails_closed_before_expensive_handler(app, client, mock_traveller_auth):
    def unavailable():
        raise OSError("offline")

    app.extensions["request_rate_limiter"] = FirestoreFixedWindowLimiter(unavailable)
    response = client.post(
        "/api/fr11/chat",
        headers={"Authorization": "Bearer valid_test_token"},
        json={"message": "Hello"},
    )

    assert response.status_code == 503
    assert response.get_json() == {
        "ok": False,
        "error": "Rate-limit service is temporarily unavailable. Please retry shortly.",
    }
    assert response.headers["Retry-After"] == "60"


def test_health_and_stripe_webhook_are_not_rate_limited_when_store_is_unavailable(app, client):
    def unavailable():
        raise OSError("offline")

    app.extensions["request_rate_limiter"] = FirestoreFixedWindowLimiter(unavailable)
    assert client.get("/api/health").status_code == 200
    with patch(
        "modules.fr09_payment.routes.constructStripeWebhookEvent",
        return_value={"type": "ignored", "data": {"object": {"metadata": {}}}},
    ):
        assert client.post("/api/fr9/webhooks/stripe", data=b"{}").status_code == 200


def test_unknown_store_failure_is_reported_as_closed_limiter():
    limiter = FirestoreFixedWindowLimiter(lambda: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(RateLimitStoreUnavailable):
        limiter.consume("recommendation", "uid:traveller")
