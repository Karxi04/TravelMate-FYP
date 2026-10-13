"""Rate-limit helpers for TravelMate Flask applications.

The backend uses Firestore transactions so a limit is shared by every Gunicorn
worker and Cloud Run instance. Browser portals retain the small in-process
limiter because their Firebase REST sign-in requests do not run through the
backend or have a Firestore service identity.
"""

import hashlib
import math
import os
import time
from collections import deque
from datetime import datetime, timezone
from threading import Lock

from flask import current_app, jsonify, request


LIMITS = {
    "authentication": 10,
    "chat": 12,
    "recommendation": 6,
    "provider_search": 30,
    "payment_mutation": 10,
    "hotel_mutation": 10,
}

_LIMIT_ENVIRONMENT = {
    "authentication": "RATE_LIMIT_AUTHENTICATION_PER_WINDOW",
    "chat": "RATE_LIMIT_CHAT_PER_WINDOW",
    "recommendation": "RATE_LIMIT_RECOMMENDATION_PER_WINDOW",
    "provider_search": "RATE_LIMIT_PROVIDER_SEARCH_PER_WINDOW",
    "payment_mutation": "RATE_LIMIT_PAYMENT_MUTATION_PER_WINDOW",
    "hotel_mutation": "RATE_LIMIT_HOTEL_MUTATION_PER_WINDOW",
}

API_LIMITS = {
    "fr01_users.create_or_update_profile": "authentication",
    "fr03_destinations.search_destinations": "provider_search",
    "fr03_destinations.destination_details": "provider_search",
    "fr03_destinations.ratings_reviews": "provider_search",
    "fr03_destinations.nearby_places": "provider_search",
    "fr04_recommendations.generate": "recommendation",
    "fr06_weather.location_search": "provider_search",
    "fr06_weather.weather": "provider_search",
    "fr07_flights.search_flights": "provider_search",
    "fr07_flights.search_flight_returns": "provider_search",
    "fr07_flights.compare_flights": "provider_search",
    "fr07_flights.flight_details": "provider_search",
    "fr08_hotels.places": "provider_search",
    "fr08_hotels.hotels_search": "provider_search",
    "fr08_hotels.compare_hotels": "provider_search",
    "fr08_hotels.hotel_prebook": "hotel_mutation",
    "fr08_hotels.hotel_book": "hotel_mutation",
    "fr09_payments.create_checkout_session": "payment_mutation",
    "fr09_payments.create_payment_intent": "payment_mutation",
    "fr09_payments.process_payment": "payment_mutation",
    "fr09_payments.retry_payment": "payment_mutation",
    "fr09_payments.cancel_payment": "payment_mutation",
    "fr11_chatbot.chat": "chat",
}


class RateLimitStoreUnavailable(RuntimeError):
    """Raised when a shared rate-limit decision cannot be made safely."""


def _positive_int(value, name, minimum=1):
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must be an integer of at least {minimum}") from exc
    if parsed < minimum:
        raise RuntimeError(f"{name} must be an integer of at least {minimum}")
    return parsed


def configured_limits(environ=None):
    source = environ if environ is not None else os.environ
    return {
        category: _positive_int(source.get(environment_name, LIMITS[category]), environment_name)
        for category, environment_name in _LIMIT_ENVIRONMENT.items()
    }


def configured_window_seconds(environ=None):
    source = environ if environ is not None else os.environ
    return _positive_int(source.get("RATE_LIMIT_WINDOW_SECONDS", 60), "RATE_LIMIT_WINDOW_SECONDS")


def configured_retention_seconds(window_seconds, environ=None):
    source = environ if environ is not None else os.environ
    return _positive_int(
        source.get("RATE_LIMIT_RETENTION_SECONDS", 86400),
        "RATE_LIMIT_RETENTION_SECONDS",
        minimum=window_seconds,
    )


class ProcessLocalLimiter:
    """Legacy limiter for portal sign-in and isolated tests only."""

    def __init__(self, clock=time.monotonic, limits=None):
        self.clock = clock
        self.limits = limits or LIMITS
        self._lock = Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self._buckets = {}
            self._next_cleanup = 0

    def consume(self, category, identity):
        with self._lock:
            now = self.clock()
            cutoff = now - 60
            if now >= self._next_cleanup:
                self._buckets = {
                    key: hits for key, hits in self._buckets.items()
                    if hits and hits[-1] > cutoff
                }
                self._next_cleanup = now + 60
            hits = self._buckets.setdefault((category, identity), deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limits[category]:
                return max(1, math.ceil(hits[0] + 60 - now))
            hits.append(now)
            return 0


class FirestoreFixedWindowLimiter:
    """Atomic fixed-window budgets with hashed identities and Firestore TTL."""

    def __init__(
        self,
        db_factory,
        limits=None,
        window_seconds=None,
        retention_seconds=None,
        clock=time.time,
        transaction_runner=None,
    ):
        self._db_factory = db_factory
        self.limits = limits or configured_limits()
        self.window_seconds = window_seconds or configured_window_seconds()
        self.retention_seconds = retention_seconds or configured_retention_seconds(self.window_seconds)
        self.clock = clock
        self._transaction_runner = transaction_runner

    @staticmethod
    def _document_id(category, identity):
        digest = hashlib.sha256(f"{category}\x00{identity}".encode("utf-8")).hexdigest()
        return f"{category}-{digest}"

    @staticmethod
    def _snapshot_data(snapshot):
        return (snapshot.to_dict() or {}) if snapshot and getattr(snapshot, "exists", False) else {}

    def _run_transaction(self, db, operation):
        if self._transaction_runner is not None:
            return self._transaction_runner(operation)
        from firebase_admin import firestore

        transaction = db.transaction()

        @firestore.transactional
        def run(transaction):
            return operation(transaction)

        return run(transaction)

    def consume(self, category, identity):
        if category not in self.limits:
            raise RuntimeError(f"Unknown rate-limit category: {category}")
        now = int(self.clock())
        window_start = now - (now % self.window_seconds)
        window_end = window_start + self.window_seconds
        document_id = self._document_id(category, identity)
        try:
            db = self._db_factory()
            document = db.collection("rate_limit_windows").document(document_id)

            def operation(transaction):
                current = self._snapshot_data(document.get(transaction=transaction))
                count = int(current.get("count", 0)) if current.get("windowStart") == window_start else 0
                if count >= self.limits[category]:
                    return max(1, window_end - now)
                transaction.set(document, {
                    "category": category,
                    "windowStart": window_start,
                    "count": count + 1,
                    "expiresAt": datetime.fromtimestamp(
                        window_end + self.retention_seconds,
                        tz=timezone.utc,
                    ),
                })
                return 0

            return self._run_transaction(db, operation)
        except RateLimitStoreUnavailable:
            raise
        except Exception as exc:
            raise RateLimitStoreUnavailable("Shared rate-limit storage is unavailable") from exc


def init_rate_limiter(app, db_factory=None):
    limits = configured_limits()
    if db_factory is None:
        # shortcut: portal Firebase REST logins need an edge/shared limiter when public traffic grows.
        limiter = ProcessLocalLimiter(limits=limits)
    elif str(os.getenv("TRAVELMATE_TESTING", "")).strip().lower() == "true":
        limiter = ProcessLocalLimiter(limits=limits)
    else:
        limiter = FirestoreFixedWindowLimiter(db_factory, limits=limits)
    app.extensions["request_rate_limiter"] = limiter


def _request_identity(uid):
    if uid:
        return f"uid:{uid}"
    # Deliberately ignore X-Forwarded-For: callers can supply it themselves.
    return f"network:{request.remote_addr or 'unknown'}"


def _limited_response(retry_after):
    response = jsonify({
        "ok": False,
        "error": "Too many requests. Please wait before trying again.",
        "retryAfterSeconds": retry_after,
    })
    response.status_code = 429
    response.headers["Retry-After"] = str(retry_after)
    response.headers["Cache-Control"] = "no-store"
    return response


def _unavailable_response():
    response = jsonify({
        "ok": False,
        "error": "Rate-limit service is temporarily unavailable. Please retry shortly.",
    })
    response.status_code = 503
    response.headers["Retry-After"] = "60"
    response.headers["Cache-Control"] = "no-store"
    return response


def rate_limit_response(category, uid=None):
    if category is None:
        return None
    try:
        retry_after = current_app.extensions["request_rate_limiter"].consume(
            category,
            _request_identity(uid),
        )
    except RateLimitStoreUnavailable:
        current_app.logger.warning("Shared rate-limit storage is unavailable")
        return _unavailable_response()
    if not retry_after:
        return None
    return _limited_response(retry_after)
