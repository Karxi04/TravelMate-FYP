"""Offline HTTP-level checks for the package checkout-attempt boundary."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Lock
from types import SimpleNamespace
from unittest.mock import patch

import pytest


class AtomicMemory:
    """Small Firestore-shaped store whose claim operation is truly atomic."""

    def __init__(self):
        self.collections = {}
        self._lock = Lock()

    def seed(self, collection, document_id, data):
        self.collections.setdefault(collection, {})[document_id] = {
            "id": document_id,
            **deepcopy(data),
        }

    def retrieve(self, collection, document_id=None, filters=None, limit=None):
        with self._lock:
            records = self.collections.setdefault(collection, {})
            if document_id:
                value = records.get(str(document_id))
                return deepcopy(value) if value else None
            values = [deepcopy(value) for value in records.values()]
        for field, operator, expected in filters or []:
            assert operator == "=="
            values = [value for value in values if value.get(field) == expected]
        return values[:limit] if limit else values

    def claim(self, collection, document_id, data):
        with self._lock:
            records = self.collections.setdefault(collection, {})
            if document_id in records:
                return deepcopy(records[document_id]), False
            records[document_id] = {"id": document_id, **deepcopy(data)}
            return deepcopy(records[document_id]), True


def eligible_package(**extra):
    return {
        "operatorId": "operator-1",
        "title": "Penang Heritage Weekend",
        "destination": "Penang",
        "adultPrice": 450,
        "currency": "MYR",
        "taxIncluded": True,
        "approvalStatus": "approved",
        "availabilityStatus": "available",
        "updatedAt": "package-revision-1",
        **extra,
    }


@pytest.fixture
def package_api(client, monkeypatch):
    memory = AtomicMemory()
    identity = {"uid": "traveller-1", "role": "traveller"}
    memory.seed("users", "operator-1", {"role": "operator", "status": "active"})

    def verify(token):
        if token == "invalid":
            raise ValueError("expired")
        return {"uid": token, "email": f"{token}@example.test"}

    def user_database():
        def document(uid):
            profile = {"uid": uid, "status": "active", "role": identity["role"]}
            if uid != identity["uid"]:
                profile = memory.retrieve("users", uid) or profile
            return SimpleNamespace(get=lambda: SimpleNamespace(
                exists=True, to_dict=lambda: deepcopy(profile)
            ))
        return SimpleNamespace(collection=lambda _collection: SimpleNamespace(document=document))

    monkeypatch.setattr("auth_utils.auth.verify_id_token", verify)
    monkeypatch.setattr("auth_utils.get_db", user_database)
    monkeypatch.setattr("modules.fr15_package_checkout.routes.retrieveRecord", memory.retrieve)
    monkeypatch.setattr("modules.fr15_package_checkout.routes.claimRecord", memory.claim)

    def headers(uid=None):
        return {"Authorization": f"Bearer {uid or identity['uid']}"}

    return memory, identity, headers


def post(client, headers, **payload):
    return client.post("/api/fr15/package-checkout-attempts", headers=headers, json=payload)


def seed_package(memory, package_id="package-1", **extra):
    memory.seed("tourism_packages", package_id, eligible_package(**extra))


def test_route_rejects_missing_invalid_and_non_traveller_authentication(client, package_api):
    memory, identity, headers = package_api
    seed_package(memory)
    payload = {"packageId": "package-1", "idempotencyKey": "auth-check"}

    assert post(client, {}, **payload).status_code == 401
    assert post(client, {"Authorization": "Bearer invalid"}, **payload).status_code == 401
    identity["role"] = "operator"
    assert post(client, headers(), **payload).status_code == 403


def test_route_creates_server_owned_pending_attempt_without_provider_side_effects(client, package_api):
    memory, _identity, headers = package_api
    seed_package(memory)
    with patch("services.stripe_service.createPaymentSession") as create_session:
        response = post(client, headers(), packageId="package-1", idempotencyKey="create-1",
                        amount=1, price=1, paymentStatus="succeeded", fulfillmentStatus="fulfilled")
    assert response.status_code == 200
    body = response.get_json()
    attempt = body["attempt"]
    assert body["ok"] is True and body["reused"] is False
    assert attempt["amount"] == 450 and attempt["packageSnapshot"]["price"] == 450
    assert attempt["participants"] == {"adults": 1, "children": 0, "total": 1}
    assert attempt["fulfillmentMode"] == "independent_package_trip"
    assert "intendedTripId" not in attempt
    assert attempt["paymentStatus"] == "payment_pending"
    assert attempt["fulfillmentStatus"] == "fulfillment_pending"
    assert set(memory.collections) == {"users", "tourism_packages", "package_checkout_attempts"}
    create_session.assert_not_called()


def test_route_calculates_group_total_and_rejects_client_amount_tampering(client, package_api):
    memory, _identity, headers = package_api
    seed_package(memory, childPrice=175, maximumTravellers=6, departureDates=["2027-02-10"])
    response = post(
        client, headers(), packageId="package-1", idempotencyKey="group-price",
        participants={"adults": 2, "children": 1}, departureDate="2027-02-10",
        amount=1, amountMinor=1, price=1, paymentStatus="paid",
    )
    assert response.status_code == 200
    attempt = response.get_json()["attempt"]
    assert attempt["amount"] == 1075
    assert attempt["packageSnapshot"]["amountMinor"] == 107500
    assert attempt["groupSize"] == 3
    assert attempt["paymentStatus"] == "payment_pending"
    assert attempt["selectedDepartureDate"] == "2027-02-10"


def test_route_rejects_unsupported_children_and_excess_capacity(client, package_api):
    memory, _identity, headers = package_api
    seed_package(memory, maximumTravellers=2)
    unsupported = post(
        client, headers(), packageId="package-1", idempotencyKey="no-child-price",
        participants={"adults": 1, "children": 1},
    )
    excessive = post(
        client, headers(), packageId="package-1", idempotencyKey="too-large",
        participants={"adults": 3, "children": 0},
    )
    assert unsupported.status_code == excessive.status_code == 409
    assert "Child pricing" in unsupported.get_json()["error"]
    assert "capacity" in excessive.get_json()["error"]


@pytest.mark.parametrize("package_data", [
    {"approvalStatus": "draft"}, {"approvalStatus": "pending"}, {"availabilityStatus": "unavailable"},
])
def test_route_rejects_unavailable_or_unapproved_packages(client, package_api, package_data):
    memory, _identity, headers = package_api
    seed_package(memory, **package_data)
    response = post(client, headers(), packageId="package-1", idempotencyKey="ineligible")
    assert response.status_code == 409
    assert response.get_json()["ok"] is False
    assert "package_checkout_attempts" not in memory.collections


def test_route_enforces_owned_existing_trip_and_destination(client, package_api):
    memory, _identity, headers = package_api
    seed_package(memory)
    memory.seed("itineraries", "other-trip", {"travellerId": "traveller-2", "destinationArea": "Penang"})
    foreign = post(client, headers(), packageId="package-1", intendedTripId="other-trip", idempotencyKey="foreign-trip")
    assert foreign.status_code == 409
    missing = post(client, headers(), packageId="package-1", intendedTripId="missing-trip", idempotencyKey="missing-trip")
    assert missing.status_code == 404
    memory.seed("itineraries", "kl-trip", {"travellerId": "traveller-1", "destinationArea": "Kuala Lumpur"})
    conflict = post(client, headers(), packageId="package-1", intendedTripId="kl-trip", idempotencyKey="wrong-destination")
    assert conflict.status_code == 409
    assert "package_checkout_attempts" not in memory.collections


def test_route_idempotency_returns_same_attempt_and_rejects_conflicting_reuse(client, package_api):
    memory, _identity, headers = package_api
    seed_package(memory, "package-1")
    seed_package(memory, "package-2", title="Penang Food Weekend")
    first = post(client, headers(), packageId="package-1", idempotencyKey="same-key")
    repeat = post(client, headers(), packageId="package-1", idempotencyKey="same-key")
    conflict = post(client, headers(), packageId="package-2", idempotencyKey="same-key")
    assert first.status_code == repeat.status_code == 200
    assert first.get_json()["attempt"]["id"] == repeat.get_json()["attempt"]["id"]
    assert repeat.get_json()["reused"] is True
    assert conflict.status_code == 409
    assert len(memory.collections["package_checkout_attempts"]) == 1


def test_route_idempotency_rejects_changed_participants(client, package_api):
    memory, _identity, headers = package_api
    seed_package(memory, childPrice=100)
    first = post(
        client, headers(), packageId="package-1", idempotencyKey="group-same-key",
        participants={"adults": 2, "children": 0},
    )
    changed = post(
        client, headers(), packageId="package-1", idempotencyKey="group-same-key",
        participants={"adults": 2, "children": 1},
    )
    assert first.status_code == 200
    assert changed.status_code == 409
    assert len(memory.collections["package_checkout_attempts"]) == 1


def test_route_concurrent_retries_produce_one_atomic_attempt(app, package_api):
    memory, _identity, headers = package_api
    seed_package(memory)

    def request_attempt():
        with app.test_client() as thread_client:
            return post(thread_client, headers(), packageId="package-1", idempotencyKey="concurrent-key")

    with ThreadPoolExecutor(max_workers=8) as workers:
        responses = list(workers.map(lambda _index: request_attempt(), range(8)))
    bodies = [response.get_json() for response in responses]
    assert all(response.status_code == 200 for response in responses)
    assert len({body["attempt"]["id"] for body in bodies}) == 1
    assert sum(not body["reused"] for body in bodies) == 1
    assert len(memory.collections["package_checkout_attempts"]) == 1


def test_route_applies_existing_payment_mutation_rate_limit(app, client, package_api):
    memory, _identity, headers = package_api
    seed_package(memory)
    limiter = app.extensions["request_rate_limiter"]
    limiter.limits["payment_mutation"] = 1
    first = post(client, headers(), packageId="package-1", idempotencyKey="rate-first")
    limited = post(client, headers(), packageId="package-1", idempotencyKey="rate-second")
    assert first.status_code == 200
    assert limited.status_code == 429
    assert limited.headers["Retry-After"]
    assert limited.get_json()["retryAfterSeconds"] >= 1


def test_route_get_is_owner_only(client, package_api):
    memory, identity, headers = package_api
    seed_package(memory)
    created = post(client, headers(), packageId="package-1", idempotencyKey="read-key").get_json()["attempt"]
    assert client.get(f"/api/fr15/package-checkout-attempts/{created['id']}", headers=headers()).status_code == 200
    identity["uid"] = "traveller-2"
    assert client.get(f"/api/fr15/package-checkout-attempts/{created['id']}", headers=headers()).status_code == 404


def test_route_masks_unexpected_persistence_failure(client, package_api, monkeypatch):
    memory, _identity, headers = package_api
    seed_package(memory)
    monkeypatch.setattr(
        "modules.fr15_package_checkout.routes.claimRecord",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("internal firestore detail")),
    )
    response = post(client, headers(), packageId="package-1", idempotencyKey="failure-key")
    assert response.status_code == 503
    assert response.get_json() == {
        "ok": False,
        "error": "Package checkout preparation is temporarily unavailable.",
    }
    assert "package_checkout_attempts" not in memory.collections
