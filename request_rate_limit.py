"""Small process-local request budgets shared by the API and browser portals."""

import math
import time
from collections import deque
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

API_LIMITS = {
    "fr01_users.create_or_update_profile": "authentication",
    "fr04_recommendations.generate": "recommendation",
    "fr11_chatbot.chat": "chat",
    "fr03_destinations.search_destinations": "provider_search",
    "fr03_destinations.destination_details": "provider_search",
    "fr06_weather.location_search": "provider_search",
    "fr06_weather.weather": "provider_search",
    "fr07_flights.search_flights": "provider_search",
    "fr08_hotels.places": "provider_search",
    "fr08_hotels.hotels_search": "provider_search",
    "fr09_payments.create_payment_intent": "payment_mutation",
    "fr09_payments.process_payment": "payment_mutation",
    "fr09_payments.create_checkout_session": "payment_mutation",
    "fr09_payments.reconcile_order": "payment_mutation",
    "fr09_payments.retry_payment": "payment_mutation",
    "fr09_payments.cancel_payment": "payment_mutation",
    "fr08_hotels.hotel_prebook": "hotel_mutation",
    "fr08_hotels.hotel_book": "hotel_mutation",
}


class ProcessLocalLimiter:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._lock = Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self._buckets = {}
            self._next_cleanup = 0

    def consume(self, category, identity):
        # ponytail: one process/lock, use shared storage if global worker budgets are needed.
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
            if len(hits) >= LIMITS[category]:
                return max(1, math.ceil(hits[0] + 60 - now))
            hits.append(now)
            return 0


def init_rate_limiter(app):
    app.extensions["request_rate_limiter"] = ProcessLocalLimiter()


def rate_limit_response(category, uid=None):
    if category is None:
        return None
    identity = ("uid", uid) if uid else ("ip", request.remote_addr or "unknown")
    retry_after = current_app.extensions["request_rate_limiter"].consume(category, identity)
    if not retry_after:
        return None
    response = jsonify({
        "ok": False,
        "error": "Too many requests. Please wait before trying again.",
        "retryAfterSeconds": retry_after,
    })
    response.status_code = 429
    response.headers["Retry-After"] = str(retry_after)
    response.headers["Cache-Control"] = "no-store"
    return response
