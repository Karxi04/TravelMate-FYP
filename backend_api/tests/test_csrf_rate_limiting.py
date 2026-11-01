import importlib.util
import io
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

import pytest
from services.transaction_reliability import operation_document_id

from app import create_app
from request_rate_limit import API_LIMITS, LIMITS, ProcessLocalLimiter
from services.stripe_service import SimulatedPaymentIntent
from test_fr08_fr09_hotels_payments import MemoryPersistence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUTH = {"Authorization": "Bearer valid_test_token"}
CSRF_ERROR = "This form has expired or could not be verified. Reload the page and try again."


@pytest.fixture(params=["admin", "operator"])
def portal(request, monkeypatch):
    return load_portal(request.param, monkeypatch)


def load_portal(name, monkeypatch):
    """Load each real portal without colliding with the backend's modules package."""
    directory = PROJECT_ROOT / f"{name}_website"
    monkeypatch.syspath_prepend(str(directory))
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SECRET_KEY", "csrf-test-secret-with-no-production-use")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    api = Mock(return_value=Mock(ok=True, status_code=200, json=lambda: {
        "ok": True,
        "profile": {"role": "admin", "name": "Test"},
        "items": [{"id": "item", "approvalStatus": "approved", "reviewStatus": "draft"}],
        "filename": "12345678901234567890123456789012.png",
        "url": "http://127.0.0.1:5000/api/public/package-images/12345678901234567890123456789012.png",
    }))
    auth = ModuleType("firebase_auth_rest")
    auth.authenticateCredentials = Mock(return_value=({
        "idToken": "test-token", "localId": "portal-user", "expiresIn": "3600",
    }, 200))
    auth.createUserAccount = Mock(return_value=({
        "idToken": "test-token", "localId": "portal-user", "expiresIn": "3600",
    }, 200))
    auth.sendPasswordResetEmail = Mock(return_value=({}, 200))
    auth.signOutUser = Mock(side_effect=lambda session: session.clear())
    api_module = ModuleType("api_client")
    api_module.call_api = api
    with patch.dict(sys.modules):
        for key in list(sys.modules):
            if key == "modules" or key.startswith("modules."):
                del sys.modules[key]
        sys.modules["api_client"] = api_module
        sys.modules["firebase_auth_rest"] = auth
        spec = importlib.util.spec_from_file_location(f"test_{name}_portal", directory / "app.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        module.app.config["TESTING"] = True
    module.app.extensions["request_rate_limiter"].clock = lambda: 1000
    return name, module.app, api, auth


def csrf_token(client, path="/"):
    response = client.get(path)
    assert response.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True))
    assert match is not None
    return match.group(1)


def test_portal_login_accepts_valid_csrf(portal):
    name, app, api, auth = portal
    client = app.test_client()
    token = csrf_token(client)
    response = client.post("/", data={"csrf_token": token, "email": "test@example.com", "password": "test"})
    assert response.status_code == 302
    auth.authenticateCredentials.assert_called_once()
    api.assert_called_once_with("GET", "/api/fr1/me")


@pytest.mark.parametrize("token", [None, "invalid-csrf-token"])
def test_all_portal_mutations_reject_bad_csrf_before_side_effects(portal, token):
    _name, app, api, auth = portal
    client = app.test_client()
    csrf_token(client)
    with client.session_transaction() as session:
        session.update(id_token="test-token", uid="portal-user")
    for rule in app.url_map.iter_rules():
        if "POST" not in rule.methods:
            continue
        path = re.sub(r"<[^>]+>", "item", rule.rule)
        response = client.post(path, data={} if token is None else {"csrf_token": token})
        assert response.status_code == 400, path
        assert response.get_data(as_text=True) == CSRF_ERROR
        assert response.headers["Cache-Control"] == "no-store"
    api.assert_not_called()
    auth.authenticateCredentials.assert_not_called()
    auth.createUserAccount.assert_not_called()
    auth.sendPasswordResetEmail.assert_not_called()
    auth.signOutUser.assert_not_called()


def test_portal_logout_requires_post_and_valid_csrf(portal):
    _name, app, _api, auth = portal
    client = app.test_client()
    token = csrf_token(client)
    with client.session_transaction() as session:
        session.update(id_token="test-token", uid="portal-user")
    assert client.get("/logout").status_code == 405
    assert client.post("/logout").status_code == 400
    assert client.post("/logout", data={"csrf_token": token}).status_code == 302
    auth.signOutUser.assert_called_once()
    with client.session_transaction() as session:
        assert "id_token" not in session


def test_rendered_portal_forms_have_valid_tokens(portal):
    name, app, _api, _auth = portal
    client = app.test_client()
    csrf_token(client)
    with client.session_transaction() as session:
        session.update(id_token="test-token", uid="portal-user",portal_role=name,verification_status='approved')
    paths = ["/admin/users", "/admin/destinations", "/admin/activities",
             "/admin/packages", "/admin/campaigns", "/admin/feedback"] if name == "admin" else [
        "/register", "/reset", "/profile", "/packages", "/campaigns", "/submit-package",
        "/packages/item/edit-page", "/campaigns/item/edit-page",
    ]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, path
        forms = re.findall(r'<form\b[^>]*method="post"[^>]*>(.*?)</form>', response.get_data(as_text=True), re.S)
        assert forms, path
        for form in forms:
            token = re.search(r'name="csrf_token" value="([^"]+)"', form)
            assert token is not None, path
            # Exercise the actual CSRF validator without mutating the rendered operation.
            with app.test_request_context("/", method="POST"):
                from flask import session
                from flask_wtf.csrf import validate_csrf
                with client.session_transaction() as browser_session:
                    session["csrf_token"] = browser_session["csrf_token"]
                validate_csrf(token.group(1))


def test_all_portal_mutations_accept_valid_csrf(portal):
    _name, app, api, auth = portal
    client = app.test_client()
    for rule in app.url_map.iter_rules():
        if "POST" not in rule.methods:
            continue
        token = csrf_token(client)
        with client.session_transaction() as session:
            session.update(id_token="test-token", uid="portal-user",portal_role=_name,verification_status='approved')
        api.reset_mock()
        auth.authenticateCredentials.reset_mock()
        auth.createUserAccount.reset_mock()
        auth.sendPasswordResetEmail.reset_mock()
        auth.signOutUser.reset_mock()
        path = re.sub(r"<[^>]+>", "item", rule.rule)
        post_data = {
            "csrf_token": token, "email": "test@example.com", "password": "test",
            "decision": "approved", "packageId": "item", "name": "Test",
            "companyName": "Test", "registrationNo": "Test", "businessContact": "Test",
            "reason": "Valid suspension reason for testing purposes.",
        }
        if "upload-image" in path:
            post_data["file"] = (io.BytesIO(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"), "test.png", "image/png")
            response = client.post(path, data=post_data, content_type="multipart/form-data")
        else:
            response = client.post(path, data=post_data)
        assert response.status_code in {200, 302}, path
        assert api.called or auth.authenticateCredentials.called or auth.createUserAccount.called or \
            auth.sendPasswordResetEmail.called or auth.signOutUser.called, path


def test_portal_authentication_routes_share_ip_budget(portal):
    name, app, _api, auth = portal
    client = app.test_client()
    token = csrf_token(client)
    auth.authenticateCredentials.return_value = ({"error": {"message": "Login failed"}}, 400)
    paths = ["/"] if name == "admin" else ["/", "/reset"]
    for index in range(10):
        assert client.post(paths[index % len(paths)], data={
            "csrf_token": token, "email": "test@example.com", "password": "test",
        }).status_code == 200
    response = client.post("/", data={"csrf_token": token})
    assert_safe_429(response)


@pytest.fixture
def operation_boundaries():
    memory = MemoryPersistence()

    def store(collection, data, document_id=None, **_kwargs):
        document_id = document_id or f"record_{len(memory.collections.get(collection, {}))}"
        memory.seed(collection, document_id, data)
        return memory.retrieve(collection, document_id)

    def recommendation_read(collection, document_id=None, **_kwargs):
        if collection == "travel_preferences" and document_id:
            return {"interests": ["Culture"], "travelType": "Solo", "budgetLevel": "Moderate"}
        return []

    with ExitStack() as stack:
        for module in ("fr01_user_management", "fr04_hybrid_recommendation",
                       "fr08_hotel_booking", "fr09_payment", "fr11_chatbot_travel_assistant"):
            target = f"modules.{module}.routes"
            stack.enter_context(patch(f"{target}.retrieveRecord", side_effect=(
                recommendation_read if module == "fr04_hybrid_recommendation" else memory.retrieve
            )))
            if module in {"fr08_hotel_booking", "fr09_payment"}:
                stack.enter_context(patch(f"{target}.claimRecord", side_effect=memory.claim))
            else:
                stack.enter_context(patch(f"{target}.storeRecord", side_effect=store))
            if module != "fr04_hybrid_recommendation":
                stack.enter_context(patch(f"{target}.updateRecord", side_effect=memory.update))
        payment = stack.enter_context(patch(
            "modules.fr09_payment.routes.processPaymentAttempt",
            return_value=SimulatedPaymentIntent("pi_test", 1000),
        ))
        chat = stack.enter_context(patch(
            "modules.fr11_chatbot_travel_assistant.routes.generateChatbotResponse",
            return_value={"reply": "Test reply", "source": "travelmate-assistant"},
        ))
        stack.enter_context(patch(
            "modules.fr11_chatbot_travel_assistant.routes.generateFollowUpResponse",
            return_value={"reply": "Test reply", "source": "travelmate-assistant"},
        ))
        yield memory, payment, chat


def assert_safe_429(response):
    assert response.status_code == 429
    assert response.get_json() == {
        "ok": False,
        "error": "Too many requests. Please wait before trying again.",
        "retryAfterSeconds": 60,
    }
    assert response.headers["Retry-After"] == "60"
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("path,payload,category", [
    ("/api/fr1/profile", {"name": "Test"}, "authentication"),
    ("/api/fr4/recommendations/generate", {"destinationArea": "Penang"}, "recommendation"),
    ("/api/fr11/chat", {"message": "Hello"}, "chat"),
    ("/api/fr9/payments/process", {"amount": 10}, "payment_mutation"),
    ("/api/fr8/hotels/prebook", {"offerId": "local_offer_test"}, "hotel_mutation"),
    ("/api/fr8/hotels/book", {"prebookId": "local_prebook_test"}, "hotel_mutation"),
])
def test_api_budgets_accept_normal_requests_and_stop_before_side_effects(
    app, client, mock_traveller_auth, operation_boundaries, path, payload, category,
):
    app.extensions["request_rate_limiter"].clock = lambda: 1000
    memory, payment, chat = operation_boundaries
    for index in range(LIMITS[category]):
        attempt_id = f"hotel_attempt_{index}"
        if path.endswith('/hotels/book'):
            doc_id = operation_document_id(
                'hotel_prebook', 'test_traveller_uid', attempt_id
            )
            snapshot = {
                'id': doc_id,
                'status': 'accepted',
                'travellerId': 'test_traveller_uid',
                'provider': 'liteapi',
                'transactionMode': 'provider_sandbox',
                'hotelBookingAttemptId': attempt_id,
                'offerId': 'local_offer_test',
                'prebookId': 'local_prebook_test',
                'amount': 120.0,
                'currency': 'MYR',
                'priceBasis': 'stay_total',
                'taxesAndFeesStatus': 'included',
                'cancellation': {'tag': 'RFN', 'status': 'known'},
                'expiresAt': '2099-01-01T00:00:00Z',
            }
            memory.seed('hotel_prebook_attempts', doc_id, {
                'travellerId': 'test_traveller_uid',
                'hotelBookingAttemptId': attempt_id,
                'offerId': 'local_offer_test',
                'prebookId': 'local_prebook_test',
                'status': 'succeeded',
                'validatedOffer': {
                    'offerId': 'local_offer_test', 'name': 'Demo hotel',
                    'price': 120.0, 'priceStatus': 'available',
                    'priceBasis': 'stay_total', 'currency': 'MYR',
                    'currencyStatus': 'known', 'taxesAndFeesStatus': 'included',
                    'cancellation': {'tag': 'RFN', 'status': 'known'},
                },
                'validatedQuoteVersion': 'test-version',
                'acceptedPrebookSnapshot': snapshot,
            })
        response = client.post(path, headers=AUTH, json={
            **payload,
            "paymentAttemptId": f"payment_attempt_{index}",
            "hotelBookingAttemptId": attempt_id,
        })
        assert response.status_code == 200, response.get_data(as_text=True)
    counts = (repr(memory.collections), payment.call_count, chat.call_count)
    response = client.post(path, headers=AUTH, json=payload)
    assert_safe_429(response)
    assert counts == (repr(memory.collections), payment.call_count, chat.call_count)
    # Budgets are fresh in every app fixture, with no opt-out of production checks.
    app.extensions["request_rate_limiter"].reset()
    reset_payload = dict(payload)
    if path.endswith('/hotels/book'):
        reset_attempt = 'hotel_attempt_reset'
        reset_doc_id = operation_document_id(
            'hotel_prebook', 'test_traveller_uid', reset_attempt
        )
        reset_snapshot = {
            'id': reset_doc_id,
            'status': 'accepted',
            'travellerId': 'test_traveller_uid',
            'provider': 'liteapi',
            'transactionMode': 'provider_sandbox',
            'hotelBookingAttemptId': reset_attempt,
            'offerId': 'local_offer_test',
            'prebookId': 'local_prebook_test',
            'amount': 120.0,
            'currency': 'MYR',
            'priceBasis': 'stay_total',
            'taxesAndFeesStatus': 'included',
            'cancellation': {'tag': 'RFN', 'status': 'known'},
            'expiresAt': '2099-01-01T00:00:00Z',
        }
        memory.seed('hotel_prebook_attempts', reset_doc_id, {
            'travellerId': 'test_traveller_uid',
            'hotelBookingAttemptId': reset_attempt,
            'offerId': 'local_offer_test',
            'prebookId': 'local_prebook_test',
            'status': 'succeeded',
            'validatedOffer': {
                'offerId': 'local_offer_test', 'price': 120.0,
                'priceStatus': 'available', 'priceBasis': 'stay_total',
                'currency': 'MYR', 'currencyStatus': 'known',
                'taxesAndFeesStatus': 'included',
                'cancellation': {'tag': 'RFN', 'status': 'known'},
            },
            'acceptedPrebookSnapshot': reset_snapshot,
        })
        reset_payload['hotelBookingAttemptId'] = reset_attempt
    assert client.post(path, headers=AUTH, json=reset_payload).status_code == 200


@pytest.mark.parametrize("header", [{}, {"Authorization": "Bearer invalid-token"}])
def test_failed_bearer_authentication_uses_ip_budget(app, client, header):
    app.extensions["request_rate_limiter"].clock = lambda: 1000
    with patch("auth_utils.auth.verify_id_token", side_effect=ValueError("internal-token-detail")):
        for _ in range(10):
            assert client.get("/api/fr1/me", headers=header).status_code == 401
        response = client.get("/api/fr1/me", headers=header)
    assert_safe_429(response)
    assert "internal-token-detail" not in response.get_data(as_text=True)
    assert client.get("/api/fr1/me", headers=header, environ_overrides={"REMOTE_ADDR": "192.0.2.2"}).status_code == 401


def test_authenticated_uid_cannot_bypass_limit_with_new_ip_or_token(
    app, client, mock_traveller_auth, operation_boundaries,
):
    app.extensions["request_rate_limiter"].clock = lambda: 1000
    for _ in range(6):
        assert client.post("/api/fr4/recommendations/generate", headers=AUTH, json={"destinationArea": "Penang"}).status_code == 200
    response = client.post("/api/fr4/recommendations/generate", headers={
        "Authorization": "Bearer another-token",
        "X-Forwarded-For": "192.0.2.3",
    }, environ_overrides={"REMOTE_ADDR": "192.0.2.4"}, json={"destinationArea": "Penang"})
    assert_safe_429(response)
    mock_traveller_auth.return_value["uid"] = "another-user"
    assert client.post("/api/fr4/recommendations/generate", headers=AUTH, json={"destinationArea": "Penang"}).status_code == 200


def test_bearer_api_has_no_portal_csrf_and_cheap_reads_are_unlimited(
    client, mock_traveller_auth, operation_boundaries,
):
    assert client.post("/api/fr1/profile", headers=AUTH, json={"name": "Test"}).status_code == 200
    for _ in range(40):
        assert client.get("/api/fr1/me", headers=AUTH).status_code == 200
        assert client.get("/api/fr9/payments", headers=AUTH).status_code == 200
        assert client.get("/api/health").status_code == 200


def test_payment_and_hotel_routes_share_category_budgets_and_reconciliation_stays_available(
    app, client, mock_traveller_auth, operation_boundaries,
):
    app.extensions["request_rate_limiter"].clock = lambda: 1000
    for _ in range(10):
        assert client.post("/api/fr9/payments/create-intent", headers=AUTH, json={}).status_code == 400
        assert client.post("/api/fr8/hotels/prebook", headers=AUTH, json={}).status_code == 400
    for path in ("/api/fr9/payments/process", "/api/fr9/payments/item/retry", "/api/fr9/payments/item/cancel",
                 "/api/fr8/hotels/book"):
        assert_safe_429(client.post(path, headers=AUTH, json={}))
    for path in ("/api/fr9/payments/attempts/attempt_test", "/api/fr8/bookings/attempts/attempt_test"):
        assert client.get(path, headers=AUTH).status_code == 404


def test_provider_search_budget_and_buckets_are_independent(app, client, mock_traveller_auth):
    app.extensions["request_rate_limiter"].clock = lambda: 1000
    with patch("modules.fr08_hotel_booking.routes.search_places", return_value={"data": []}) as provider:
        for _ in range(30):
            assert client.get("/api/fr8/places/search?q=Penang", headers=AUTH).status_code == 200
        assert_safe_429(client.get("/api/fr8/places/search?q=Penang", headers=AUTH))
        assert provider.call_count == 30
    assert_safe_429(client.get("/api/fr7/flights/search", headers=AUTH))
    assert client.post("/api/fr8/hotels/prebook", headers=AUTH, json={}).status_code == 400


def test_route_policy_matches_registered_endpoints_and_new_apps_start_empty(app):
    assert API_LIMITS.keys() <= app.view_functions.keys()
    app.extensions["request_rate_limiter"].consume("authentication", ("ip", "test"))
    with patch("app.init_firebase"):
        fresh_app = create_app()
    assert fresh_app.extensions["request_rate_limiter"]._buckets == {}
    assert fresh_app.extensions["request_rate_limiter"] is not app.extensions["request_rate_limiter"]


def test_limiter_window_reset_cleanup_and_atomic_concurrent_requests():
    now = [1000.0]
    limiter = ProcessLocalLimiter(clock=lambda: now[0])
    with ThreadPoolExecutor(max_workers=8) as workers:
        results = list(workers.map(lambda _: limiter.consume("recommendation", "user"), range(30)))
    assert results.count(0) == 6
    assert results.count(60) == 24
    now[0] += 59.5
    assert limiter.consume("recommendation", "user") == 1
    now[0] += 0.5
    assert limiter.consume("recommendation", "user") == 0
    assert limiter.consume("chat", "user") == 0
    now[0] += 60
    assert limiter.consume("chat", "another-user") == 0
    assert ("recommendation", "user") not in limiter._buckets
    limiter.reset()
    assert limiter._buckets == {}
