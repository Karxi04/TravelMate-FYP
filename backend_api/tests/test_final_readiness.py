"""Isolated contracts across the actual FYP routes, not mocked domain algorithms."""

import importlib
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from requests import Timeout
from google.genai import errors

from services.malaysian_locality import normalize_destination_scope, validate_candidate
from services import gemini_service
from services.campaign_schedule import malaysia_today
from test_csrf_rate_limiting import csrf_token, load_portal
from test_fr08_fr09_hotels_payments import MemoryPersistence


TRAVELLER = "journey-traveller"
OPERATOR = "journey-operator"
ADMIN = "journey-admin"
AUTH = {"Authorization": f"Bearer {TRAVELLER}"}
PREFERENCES = {
    "travelPersonality": "Explorer", "travelType": "Solo",
    "interests": ["Shopping", "Food"], "budgetRange": "Moderate",
    "travelPace": "Moderate", "travelPurpose": "Holiday",
}


class JourneyMemory(MemoryPersistence):
    def learning(self,uid,transform):
        updated,event,changed=transform(self.retrieve('learned_preference_profiles',uid))
        if event is not None:
            self.store('learned_preference_profiles',updated,uid)
            self.store('recommendation_feedback_events',event,event['feedbackEventId'])
        return updated,event,changed
    def update(self, collection, document_id, data, expected=None):
        if expected is not None and self.retrieve(collection,document_id) != expected:
            from services.review_service import ReviewConflict
            raise ReviewConflict('This record changed. Refresh and try again.')
        return super().update(collection,document_id,data)

    def store(self, collection, data, document_id=None, merge=False):
        document_id = document_id or f"{collection}_{len(self.collections.get(collection, {})) + 1}"
        previous = self.retrieve(collection, document_id) if merge else {}
        self.seed(collection, document_id, deepcopy({**(previous or {}), **data}))
        return self.retrieve(collection, document_id)

    def retrieve(self, *args, **kwargs):
        return deepcopy(super().retrieve(*args, **kwargs))

    def delete(self, collection, document_id):
        return self.collections.get(collection, {}).pop(document_id, None) is not None


@pytest.fixture
def journey(app, client, monkeypatch):
    memory = JourneyMemory()
    for uid, role in ((ADMIN, "admin"), (OPERATOR, "operator")):
        memory.store("users", {
            "uid": uid, "email": f"{uid}@example.test", "name": "Demo test account",
            "role": role, "status": "active", "verificationStatus": "pending",
        }, uid)

    def verify(token, *, clock_skew_seconds):
        assert clock_skew_seconds == 10
        assert token in {TRAVELLER, OPERATOR, ADMIN}
        return {"uid": token, "email": f"{token}@example.test"}

    def document(uid):
        return SimpleNamespace(get=lambda: SimpleNamespace(
            exists=bool(memory.retrieve("users", uid)),
            to_dict=lambda: memory.retrieve("users", uid),
        ))

    monkeypatch.setattr("auth_utils.auth.verify_id_token", verify)
    monkeypatch.setattr("auth_utils.get_db", lambda: SimpleNamespace(
        collection=lambda _name: SimpleNamespace(document=document),
    ))
    monkeypatch.setattr("firebase_admin.auth.update_user", Mock())
    for blueprint in app.blueprints.values():
        module = importlib.import_module(blueprint.import_name)
        for name, handler in {
            "retrieveRecord": memory.retrieve, "storeRecord": memory.store,
            "updateRecord": memory.update, "deleteRecord": memory.delete,
            "claimRecord": memory.claim,
            "transactPreferenceLearning": memory.learning,
        }.items():
            if hasattr(module, name):
                monkeypatch.setattr(module, name, handler)

    monkeypatch.setenv("SERPAPI_KEY", "fake-key")
    monkeypatch.setenv("FALLBACK_MODE", "true")
    for target in (
        "modules.fr04_hybrid_recommendation.routes.retrieveDestinationResults",
        "modules.fr03_destination_search_information.routes.retrieveDestinationDetails",
        "modules.fr05_smart_itinerary_budget_planner.routes.geocode",
        "modules.fr05_smart_itinerary_budget_planner.routes.retrieveSevenDayForecast",
    ):
        monkeypatch.setattr(target, Mock(side_effect=Timeout("Provider unavailable in isolated demo")))

    scope = normalize_destination_scope("Penang")
    for index, category in enumerate(("Shopping", "Food")):
        memory.store("destination_cache", {
            "destinationId": category.lower(), "title": f"Test {category} stop",
            "address": "George Town, Penang, Malaysia", "category": category,
            "rating": 4.5, "reviews": 300, "estimatedCost": 40,
            "openingHours": "08:00-20:00", "recommendedDurationMinutes": 60,
            "gps_coordinates": {"latitude": 5.416, "longitude": 100.335 + index * .001},
            "canonicalDestinationScope": scope["scopeKey"],
        }, category.lower())
    # This deliberately mis-scoped cache row must never reach the snapshot.
    memory.store("destination_cache", {
        "destinationId": "outside", "title": "Kuala Lumpur Test Stop",
        "address": "Kuala Lumpur, Malaysia", "category": "Food",
        "gps_coordinates": {"latitude": 3.139, "longitude": 101.6869},
        "canonicalDestinationScope": scope["scopeKey"],
    }, "outside")
    return memory


def register_profile(client):
    # Firebase email/password exchange is mocked at the external identity boundary.
    # Exercise the real mobile post-registration profile and post-login contracts.
    response = client.post("/api/fr1/profile", headers=AUTH, json={"name": "Journey Traveller", "role": "traveller"})
    assert response.status_code == 200
    assert response.get_json()["profile"]["uid"] == TRAVELLER
    assert client.get("/api/fr1/me", headers=AUTH).get_json()["profile"]["role"] == "traveller"


def test_complete_traveller_journey_and_explicit_learning_refresh(client, journey):
    register_profile(client)
    assert client.get("/api/fr2/preferences", headers=AUTH).get_json()["preferences"] is None
    saved = client.put("/api/fr2/preferences", headers=AUTH, json=PREFERENCES)
    assert saved.status_code == 200
    original_preferences = journey.retrieve("travel_preferences", TRAVELLER)
    # These are the actual Home/entry-gate endpoints.
    assert client.get("/api/fr1/me", headers=AUTH).status_code == 200
    assert client.get("/api/fr2/preferences", headers=AUTH).get_json()["preferences"]["interests"] == PREFERENCES["interests"]
    assert client.get("/api/fr5/itineraries", headers=AUTH).get_json()["items"] == []

    first = client.post("/api/fr4/recommendations/generate", headers=AUTH, json={"destinationArea": "Penang"})
    assert first.status_code == 200
    first = first.get_json()
    generation_id = first["recommendationGenerationId"]
    original_snapshot = journey.retrieve("recommendation_snapshots", generation_id)
    assert first["source"] == "cache"  # Provider outage uses geographically eligible cache.
    assert {row["destinationId"] for row in first["recommendations"]} == {"shopping", "food"}
    assert [row['destinationId'] for row in first['recommendations']] == ['food','shopping']
    assert first['recommendations'][0]['score'] == first['recommendations'][1]['score']  # Stable identity tie-break, not a fabricated relevance gap.
    assert all(validate_candidate(row, normalize_destination_scope("Penang"))[0] for row in first["recommendations"])
    assert client.get("/api/fr4/recommendations", headers=AUTH).get_json()["recommendationGenerationId"] == generation_id
    details = client.get("/api/fr3/destinations/food", headers=AUTH).get_json()
    assert details["source"] == "cache"
    assert details["detailsAvailable"] is True

    planned = client.post("/api/fr5/personalised-trips/generate", headers=AUTH, json={
        "title": "Journey Penang Trip", "destinationArea": "Penang", "destinationName": "Penang",
        "startDate": "2026-11-01", "endDate": "2026-11-03", "travellerCount": 1,
        "budgetLimit": 1200, "travelPace": "Moderate",
        "recommendationGenerationId": generation_id, "generationRequestId": "journey_request_001",
    })
    assert planned.status_code == 200, planned.get_data(as_text=True)
    trip = planned.get_json()["itinerary"]
    trip_id = planned.get_json()["tripId"]
    assert trip["status"] == "planned"
    assert trip["recommendationGenerationId"] == generation_id
    assert all(row["recommendationGenerationId"] == generation_id for row in trip["activities"])
    assert trip["activities"] and trip["budgetEstimate"]
    assert all(day["weather"]["source"] == "unavailable" and day["weather"]["message"] for day in trip["dailySchedule"])
    listed = client.get("/api/fr5/itineraries", headers=AUTH).get_json()["items"]
    assert listed[0]["id"] == trip_id  # The exact Trip Details contract.

    order = [row["activityId"] for row in reversed(trip["activities"])]
    edited = client.post(f"/api/fr5/itineraries/{trip_id}/activities/rearrange", headers=AUTH, json={"orderedActivityIds": order})
    assert edited.status_code == 200
    edited_trip = edited.get_json()["itinerary"]
    assert [row["activityId"] for row in edited_trip["activities"]] == order
    assert edited_trip["dailySchedule"] and edited_trip["totalScheduledMinutes"] > 0
    assert journey.retrieve("itineraries", trip_id)["activities"] == edited_trip["activities"]
    assert journey.retrieve("recommendation_snapshots", generation_id) == original_snapshot

    versions = []
    for destination_id, feedback in (("shopping", "not_for_me"), ("food", "more_like_this")):
        response = client.post("/api/fr4/preference-feedback", headers=AUTH, json={
            "destinationId": destination_id, "feedbackType": feedback,
            "recommendationGenerationId": generation_id, "sourceContext": "for_you",
        })
        assert response.status_code == 200
        versions.append(response.get_json()["learning"]["learnedPreferenceVersion"])
    assert versions[0] != versions[1]
    assert journey.retrieve("travel_preferences", TRAVELLER) == original_preferences
    unchanged = client.get("/api/fr4/recommendations", headers=AUTH).get_json()
    assert unchanged["recommendationGenerationId"] == generation_id
    assert unchanged['stale'] and unchanged['recommendations']==[]
    assert journey.retrieve('recommendation_snapshots',generation_id)==original_snapshot

    refreshed = client.post("/api/fr4/recommendations/generate", headers=AUTH, json={"destinationArea": "Penang"})
    assert refreshed.status_code == 200
    refreshed = refreshed.get_json()
    assert refreshed["recommendationGenerationId"] != generation_id
    assert refreshed["snapshot"]["preferenceProfileVersion"] != first["snapshot"]["preferenceProfileVersion"]
    before = {row["destinationId"]: row for row in first["recommendations"]}
    after = {row["destinationId"]: row for row in refreshed["recommendations"]}
    assert 'shopping' not in after and 'shopping' in before
    assert after["food"]["score"] >= before["food"]["score"]
    assert refreshed["recommendations"][0]["destinationId"] == "food"
    assert journey.retrieve("recommendation_snapshots", generation_id) == original_snapshot
    assert refreshed["engine"]["weightedScoring"] == {"content": .60, "collaborative": .30, "popularity": .10}
    stale = client.post(f"/api/fr5/itineraries/{trip_id}/generate", headers=AUTH, json={
        "recommendationGenerationId": refreshed["recommendationGenerationId"],
    })
    assert stale.status_code == 409
    assert journey.retrieve("itineraries", trip_id)["recommendationGenerationId"] == generation_id


def portal_bridge(portal, backend_client, uid):
    _name, app, api, auth = portal
    auth.authenticateCredentials.return_value = ({"idToken": uid, "localId": uid, "expiresIn": "3600"}, 200)

    def call_api(method, path, **kwargs):
        from flask import session
        response = backend_client.open(path, method=method,
            headers={"Authorization": f"Bearer {session['id_token']}"},
            json=kwargs.get("json"), query_string=kwargs.get("params"))
        return SimpleNamespace(ok=response.status_code < 400, json=response.get_json,
                               status_code=response.status_code, content=response.data)

    api.side_effect = call_api
    client = app.test_client()
    token = csrf_token(client)
    response = client.post("/", data={"csrf_token": token, "email": "demo@example.test", "password": "test-only"})
    return client, token, response


@pytest.mark.parametrize("status", ["pending", "rejected", "approved", "verified"])
def test_actual_operator_login_requires_verification(client, journey, monkeypatch, status):
    journey.update("users", OPERATOR, {"verificationStatus": status})
    browser, _token, response = portal_bridge(load_portal("operator", monkeypatch), client, OPERATOR)
    assert response.status_code == 302
    with browser.session_transaction() as session:
        assert bool(session.get("id_token")) is True
    if status in {"pending", "rejected"}:
        pending_page = browser.get(response.location)
        assert pending_page.status_code == 200
        assert b"Account Verification Pending" in pending_page.data or b"Account Needs Attention" in pending_page.data
        assert client.get("/api/fr12/packages", headers={"Authorization": f"Bearer {OPERATOR}"}).status_code == 403
    else:
        dashboard = browser.get("/dashboard")
        assert dashboard.status_code == 200
        assert b"Moderation Attention" in dashboard.data or b"Operator Dashboard" in dashboard.data
        assert browser.get("/profile").status_code == 200
        profile_update = browser.post("/profile", data={
            "csrf_token": _token, "name": "Updated Demo Operator",
            "companyName": "Demo Travel Company", "businessContact": "+60123456789",
        })
        assert profile_update.status_code == 302
        assert journey.retrieve("users", OPERATOR)["name"] == "Updated Demo Operator"
        assert browser.get("/packages").status_code == 200
        assert browser.get("/packages/new").status_code == 200
        assert browser.get("/campaigns").status_code == 200


@pytest.mark.parametrize("failure", ["invalid", "expired"])
def test_firebase_verification_failure_remains_unauthorized(client, failure):
    from firebase_admin import auth
    error = (auth.ExpiredIdTokenError("Synthetic expired token", None) if failure == "expired"
             else auth.InvalidIdTokenError("Synthetic invalid token"))
    with patch("auth_utils.auth.verify_id_token", side_effect=error) as verify:
        response = client.get("/api/fr1/me", headers=AUTH)
    assert response.status_code == 401
    assert response.get_json()["error"] == "Invalid or expired Firebase ID token"
    verify.assert_called_once_with(TRAVELLER, clock_skew_seconds=10)


def test_operator_login_with_expired_backend_token_clears_session(client, journey, monkeypatch):
    from firebase_admin import auth
    with patch("auth_utils.auth.verify_id_token",
               side_effect=auth.ExpiredIdTokenError("Synthetic expired token", None)) as verify:
        browser, _token, response = portal_bridge(load_portal("operator", monkeypatch), client, OPERATOR)
    # An authentication error renders login; valid-user redirect assertions stay intact.
    assert response.status_code == 200
    assert b"Authentication session expired or invalid" in response.data
    with browser.session_transaction() as session:
        assert not session.get("id_token")
        assert not session.get("portal_role")
    verify.assert_called_once_with(OPERATOR, clock_skew_seconds=10)


def test_portal_admin_verification_package_campaign_and_traveller_publication(client, journey, monkeypatch):
    register_profile(client)
    admin, admin_token, login = portal_bridge(load_portal("admin", monkeypatch), client, ADMIN)
    assert login.status_code == 302
    pending_browser, _token, pending = portal_bridge(load_portal("operator", monkeypatch), client, OPERATOR)
    assert pending.status_code == 302
    account_update = {"role": "operator", "status": "active", "verificationStatus": "approved"}
    assert admin.post(f"/admin/users/{OPERATOR}/update", data=account_update).status_code == 400
    assert journey.retrieve("users", OPERATOR)["verificationStatus"] == "pending"
    assert admin.post(f"/admin/users/{OPERATOR}/update", data={**account_update, "csrf_token": admin_token}).status_code == 302
    assert journey.retrieve("users", OPERATOR)["verificationStatus"] == "approved"
    operator, operator_token, login = portal_bridge(load_portal("operator", monkeypatch), client, OPERATOR)
    assert login.status_code == 302
    package = {
        "title": "Isolated Penang test package", "destination": "Penang",
        "shortDescription": "A focused local package", "fullDescription": "Test fixture only",
        "durationDays": "2", "durationNights": "1", "currency": "MYR",
        "adultPrice": "100", "childPrice": "50", "priceBasis": "per_person",
        "minimumTravellers": "1", "maximumTravellers": "10",
        "departureDates": "2026-12-10\n2026-12-17", "departureLocation": "George Town",
        "itineraryTitle": ["Arrival", "Heritage day"],
        "itineraryDescription": ["Meet the local guide.", "Explore George Town."],
        "itineraryActivities": ["Hotel check-in", "Street art\nClan jetty"],
        "itineraryMeals": ["Dinner", "Breakfast\nLunch"],
        "highlights": "Local guide\nHeritage trail", "inclusions": "Transport\nGuide",
        "exclusions": "Flights", "accommodationName": "Demo Heritage Hotel",
        "transportTypes": "Private van", "cancellationPolicy": "Cancel seven days before departure.",
        "heroImage": "https://example.test/package.jpg",
    }
    assert operator.post("/packages", data=package).status_code == 400
    assert journey.retrieve("tourism_packages") == []
    assert operator.post("/packages", data={**package, "csrf_token": operator_token}).status_code == 302
    package_id = journey.retrieve("tourism_packages")[0]["id"]
    assert client.get("/api/public/tourism-packages", headers=AUTH).get_json()["items"] == []
    assert operator.post(f"/packages/{package_id}/submit", data={"csrf_token": operator_token}).status_code == 302
    assert journey.retrieve("tourism_packages", package_id)["approvalStatus"] == "pending"
    assert admin.get("/admin/packages?status=pending").status_code == 200
    details = admin.get(f"/admin/packages/{package_id}")
    assert details.status_code == 200
    assert b"Day-by-day itinerary" in details.data
    rejected = admin.post(f"/admin/packages/{package_id}/review", data={
        "csrf_token": admin_token, "decision": "rejected", "comment": "Clarify the second day meeting point."
    })
    assert rejected.status_code == 302
    assert journey.retrieve("tourism_packages", package_id)["approvalStatus"] == "rejected"
    assert b"Clarify the second day meeting point" in operator.get("/packages").data
    package["meetingPoint"] = "Hotel lobby"
    assert operator.post(f"/packages/{package_id}/edit-page", data={**package, "csrf_token": operator_token}).status_code == 302
    assert journey.retrieve("tourism_packages", package_id)["approvalStatus"] == "rejected"
    assert operator.post(f"/packages/{package_id}/submit", data={"csrf_token": operator_token}).status_code == 302
    assert admin.post(f"/admin/packages/{package_id}/review", data={"csrf_token": admin_token, "decision": "approved"}).status_code == 302
    assert journey.retrieve("tourism_packages", package_id)["approvalStatus"] == "approved"
    campaign = {"campaignTitle": "Isolated test campaign", "packageId": package_id,
                "description": "Test fixture only", "startDate": malaysia_today().isoformat(), "endDate": "2099-12-31"}
    assert operator.post("/campaigns", data={**campaign, "csrf_token": operator_token}).status_code == 302
    campaign_id = journey.retrieve("promotional_campaigns")[0]["id"]
    assert operator.post(f"/campaigns/{campaign_id}/submit", data={"csrf_token": operator_token}).status_code == 302
    assert journey.retrieve("promotional_campaigns", campaign_id)["reviewStatus"] == "pending"
    assert admin.post(f"/admin/campaigns/{campaign_id}/review", data={"csrf_token": admin_token, "decision": "approved"}).status_code == 302
    assert journey.retrieve("promotional_campaigns", campaign_id)["reviewStatus"] == "approved"
    campaign_update = {**campaign, "description": "Updated campaign content."}
    assert operator.post(f"/campaigns/{campaign_id}/edit-page", data={**campaign_update, "csrf_token": operator_token}).status_code == 302
    assert journey.retrieve("promotional_campaigns", campaign_id)["reviewStatus"] == "draft"
    assert client.get("/api/public/promotional-campaigns", headers=AUTH).get_json()["items"] == []
    assert operator.post(f"/campaigns/{campaign_id}/submit", data={"csrf_token": operator_token}).status_code == 302
    assert admin.post(f"/admin/campaigns/{campaign_id}/review", data={"csrf_token": admin_token, "decision": "rejected", "comment": "Clarify the promotion end date."}).status_code == 302
    assert b"Clarify the promotion end date" in operator.get("/campaigns").data
    assert operator.post(f"/campaigns/{campaign_id}/edit-page", data={**campaign_update, "description": "Clarified promotion.", "csrf_token": operator_token}).status_code == 302
    assert operator.post(f"/campaigns/{campaign_id}/submit", data={"csrf_token": operator_token}).status_code == 302
    assert admin.post(f"/admin/campaigns/{campaign_id}/review", data={"csrf_token": admin_token, "decision": "approved"}).status_code == 302
    assert journey.retrieve("promotional_campaigns", campaign_id)["reviewStatus"] == "approved"
    public_package = client.get("/api/public/tourism-packages", headers=AUTH).get_json()["items"][0]
    assert public_package["id"] == package_id
    assert public_package["title"] == package["title"]
    assert public_package["itineraryDays"][1]["activities"] == ["Street art", "Clan jetty"]
    assert public_package["departureDates"] == ["2026-12-10", "2026-12-17"]
    assert public_package["highlights"] == ["Local guide", "Heritage trail"]
    assert public_package["accommodationName"] == "Demo Heritage Hotel"
    assert public_package["adultPrice"] == 100
    assert public_package["operatorName"] == "Demo test account"
    assert "operatorId" not in public_package
    assert "approvalStatus" not in public_package
    assert "reviewedBy" not in public_package
    assert client.get("/api/public/promotional-campaigns", headers=AUTH).get_json()["items"][0]["id"] == campaign_id


def test_missing_credentials_use_local_recommendations_or_controlled_unavailable(client, journey, monkeypatch):
    register_profile(client)
    assert client.put("/api/fr2/preferences", headers=AUTH, json=PREFERENCES).status_code == 200
    journey.collections["destination_cache"] = {}
    monkeypatch.setenv("SERPAPI_KEY", "")
    response = client.post("/api/fr4/recommendations/generate", headers=AUTH, json={"destinationArea": "Penang"})
    assert response.status_code == 200
    snapshot = response.get_json()["snapshot"]
    assert snapshot["source"] == "fallback"
    assert all(validate_candidate(row, normalize_destination_scope("Penang"))[0] for row in snapshot["recommendationResults"])
    original = deepcopy(journey.collections["recommendation_snapshots"])
    monkeypatch.setenv("FALLBACK_MODE", "false")
    assert client.post("/api/fr4/recommendations/generate", headers=AUTH, json={"destinationArea": "Penang"}).status_code == 502
    assert client.post("/api/fr11/chat", headers=AUTH, json={"message": "Hello"}).status_code == 502
    assert client.post("/api/fr8/hotels/search", headers=AUTH, json={
        "destination": "Penang", "checkin": "2026-11-01", "checkout": "2026-11-03",
    }).status_code == 502
    assert journey.collections["recommendation_snapshots"] == original


def test_hotel_and_payment_fallback_are_simulated_not_provider_confirmations(client, journey):
    register_profile(client)
    prebook = client.post("/api/fr8/hotels/prebook", headers=AUTH, json={
        "offerId": "local_offer_test", "hotelBookingAttemptId": "journey_hotel_attempt",
    }).get_json()
    booked = client.post("/api/fr8/hotels/book", headers=AUTH, json={
        "validationId": prebook["result"]["validationId"], "hotelBookingAttemptId": "journey_hotel_attempt",
        "hotelCost": 120,
    })
    assert booked.status_code == 200
    booking = booked.get_json()["booking"]
    assert booking["isSimulated"] is True
    assert booking["bookingMode"] == "simulation"
    assert "providerRequestKey" not in booking
    paid = client.post("/api/fr9/payments/process", headers=AUTH, json={
        "bookingId": booking["id"], "paymentAttemptId": "journey_payment_attempt", "amount": 1,
    })
    assert paid.status_code == 200
    payment = paid.get_json()["payment"]
    assert payment["amount"] == 120
    assert payment["transactionReference"].startswith("pi_sim_")
    assert "providerIdempotencyKey" not in payment


@pytest.mark.parametrize("destination,has_offers", [("Penang", True), ("Kuala Lumpur", False)])
def test_hotel_fallback_never_returns_offers_for_another_locality(client, journey, destination, has_offers):
    register_profile(client)
    response = client.post("/api/fr8/hotels/search", headers=AUTH, json={
        "destination": destination, "checkin": "2026-11-01", "checkout": "2026-11-03",
    })
    assert response.status_code == 200
    data = response.get_json()
    assert data["source"] == "local"
    assert bool(data["items"]) == has_offers
    assert all(validate_candidate(row, normalize_destination_scope(destination))[0] for row in data["items"])


def test_gemini_adapter_accepts_generate_content_text_without_live_requests(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    response = SimpleNamespace(text="Live test text")
    with patch.object(gemini_service.genai, "Client") as client:
        client.return_value.models.generate_content.return_value = response
        result = gemini_service.generateChatbotResponse("Hello", with_source=True)
    assert result == {"reply": "Live test text", "source": "gemini"}
    client.return_value.models.generate_content.assert_called_once()
    client.return_value.interactions.create.assert_not_called()


def test_gemini_generate_content_keeps_system_and_traveller_context_separate(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    with patch.object(gemini_service.genai, "Client") as sdk:
        sdk.return_value.models.generate_content.return_value = SimpleNamespace(text=" Malaysia advice ")
        result = gemini_service.generateChatbotResponse(
            "Plan in Penang", "Traveller preferences: Food\nRecent conversation: KL",
            with_source=True,
        )
    assert result == {"reply": "Malaysia advice", "source": "gemini"}
    sdk.assert_called_once()
    assert sdk.call_args.kwargs["http_options"].timeout == 20_000
    kwargs = sdk.return_value.models.generate_content.call_args.kwargs
    assert kwargs["model"] == "gemini-3.8-flash"
    assert kwargs["contents"] == (
        "Traveller preferences: Food\nRecent conversation: KL\n\nTraveller: Plan in Penang"
    )
    assert "Malaysia" in kwargs["config"].system_instruction
    assert "Never claim a booking or payment is confirmed" in kwargs["config"].system_instruction
    sdk.return_value.interactions.create.assert_not_called()


@pytest.mark.parametrize("text", [None, "", "  ", 42])
def test_gemini_rejects_empty_or_invalid_response(monkeypatch, text):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("FALLBACK_MODE", "false")
    with patch.object(gemini_service.genai, "Client") as sdk:
        sdk.return_value.models.generate_content.return_value = SimpleNamespace(text=text)
        with pytest.raises(RuntimeError, match="Gemini service is unavailable"):
            gemini_service.generateChatbotResponse("Hello")


@pytest.mark.parametrize("failure", [
    errors.ClientError(code, {"error": {"message": "private-key-marker"}})
    for code in (400, 401, 403, 429)
] + [errors.ServerError(503, {"error": {"message": "private-key-marker"}}),
     Timeout("private-key-marker"), ValueError("private-key-marker")])
@pytest.mark.parametrize("fallback", [False, True])
def test_gemini_provider_failures_are_safe_and_source_labelled(monkeypatch, failure, fallback):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("FALLBACK_MODE", str(fallback).lower())
    with patch.object(gemini_service.genai, "Client") as sdk:
        sdk.return_value.models.generate_content.side_effect = failure
        if fallback:
            result = gemini_service.generateChatbotResponse("Budget advice", with_source=True)
            assert result["source"] == "travelmate-assistant"
            assert "private-key-marker" not in result["reply"]
        else:
            with pytest.raises(RuntimeError, match="^Gemini service is unavailable$") as exc:
                gemini_service.generateChatbotResponse("Budget advice", with_source=True)
            assert "private-key-marker" not in str(exc.value)
        sdk.return_value.models.generate_content.assert_called_once()


@pytest.mark.parametrize("fallback", [False, True])
def test_gemini_missing_key_is_safe_and_never_calls_sdk(monkeypatch, fallback):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("FALLBACK_MODE", str(fallback).lower())
    with patch.object(gemini_service.genai, "Client") as sdk:
        if fallback:
            result = gemini_service.generateChatbotResponse("Budget advice", with_source=True)
            assert result["source"] == "travelmate-assistant"
        else:
            with pytest.raises(RuntimeError, match="^Gemini service is unavailable$"):
                gemini_service.generateChatbotResponse("Budget advice")
        sdk.assert_not_called()


def test_gemini_flask_route_preserves_context_and_session(client, journey, monkeypatch):
    register_profile(client)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("FALLBACK_MODE", "false")
    # Keep provider-context assertions independent of changing local catalogue coverage.
    with patch.object(gemini_service.genai, "Client") as sdk, patch(
        'modules.fr11_chatbot_travel_assistant.routes.DESTINATIONS', [
            {'destinationId':f'isolated_context_{i}','title':f'Isolated context stop {i}',
             'address':'Kota Kinabalu, Sabah, Malaysia','category':'Culture',
             'recommendedDurationMinutes':60} for i in range(4)]
    ):
        sdk.return_value.models.generate_content.side_effect = [
            SimpleNamespace(text="First Gemini reply"),
            SimpleNamespace(text="Second Gemini reply"),
        ]
        first = client.post("/api/fr11/chat", headers=AUTH, json={"message": "Plan four days in Kota Kinabalu"})
        assert first.status_code == 200
        session_id = first.get_json()["session"]["id"]
        second = client.post("/api/fr11/chat", headers=AUTH, json={
            "sessionId": session_id, "message": "Our budget is RM2000 for 3 people",
        })
    assert second.status_code == 200
    data = second.get_json()
    assert data["ok"] is True
    assert data["reply"] == "Second Gemini reply"
    assert data["source"] == data["item"]["source"] == "gemini"
    assert data["session"]["planningState"]["destinationArea"] == "Kota Kinabalu"
    assert data["session"]["planningState"]["tripDays"] == 4
    assert data["session"]["planningState"]["budgetLimit"] == 2000
    assert data["session"]["planningState"]["travellerCount"] == 3
    contents = sdk.return_value.models.generate_content.call_args.kwargs["contents"]
    assert "Traveller preferences:" in contents
    assert "Active trip planning state:" in contents
    assert "First Gemini reply" in contents
    assert "Traveller: Our budget is RM2000 for 3 people" in contents
    assert len(journey.retrieve("chat_messages")) == 2


def test_gemini_flask_route_hides_provider_failure(client, journey, monkeypatch):
    register_profile(client)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("FALLBACK_MODE", "false")
    with patch.object(gemini_service.genai, "Client") as sdk:
        sdk.return_value.models.generate_content.side_effect = errors.ClientError(
            400, {"error": {"message": "private-key-marker unsupported legacy schema"}},
        )
        response = client.post("/api/fr11/chat", headers=AUTH, json={"message": "Budget advice"})
    assert response.status_code == 502
    assert response.get_json()["error"] == "The travel assistant is temporarily unavailable. Please retry."
    assert "private-key-marker" not in str(response.get_json())
    assert journey.retrieve("chat_messages") == []


def test_gemini_flask_route_does_not_reuse_another_travellers_session(client, journey, monkeypatch):
    register_profile(client)
    journey.store("users", {
        "uid": "other-traveller", "email": "other@example.test", "name": "Other",
        "role": "traveller", "status": "active",
    }, "other-traveller")
    def verify_session_user(token, *, clock_skew_seconds):
        assert clock_skew_seconds == 10
        assert token in {TRAVELLER, "other-traveller"}
        return {"uid": token}

    monkeypatch.setattr("auth_utils.auth.verify_id_token", verify_session_user)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("FALLBACK_MODE", "false")
    with patch.object(gemini_service.genai, "Client") as sdk:
        sdk.return_value.models.generate_content.side_effect = [
            SimpleNamespace(text="Private first reply"),
            SimpleNamespace(text="Independent second reply"),
        ]
        first = client.post("/api/fr11/chat", headers=AUTH, json={
            "message": "Plan three days in Langkawi SECRET_CROSS_USER_NOTE",
        })
        assert first.status_code == 200
        first_id = first.get_json()["session"]["id"]
        second = client.post("/api/fr11/chat", headers={
            "Authorization": "Bearer other-traveller",
        }, json={"sessionId": first_id, "message": "What can I do in Penang?"})
    assert second.status_code == 404
    assert second.get_json()["error"] == "Chat session not found."
    assert sdk.return_value.models.generate_content.call_count == 1
    assert len(journey.retrieve("chat_sessions")) == 1


def test_gemini_flask_route_keeps_auth_and_validation(client, journey, monkeypatch):
    register_profile(client)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    with patch.object(gemini_service.genai, "Client") as sdk:
        assert client.post("/api/fr11/chat", json={"message": "Hello"}).status_code == 401
        assert client.post("/api/fr11/chat", headers=AUTH, json={}).status_code == 400
        assert client.post("/api/fr11/chat", headers=AUTH, json={
            "message": "x" * 2001,
        }).status_code == 400
        sdk.assert_not_called()


def test_configured_gemini_outage_is_labelled_local_in_real_chat_route(client, journey, monkeypatch):
    register_profile(client)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    with patch.object(gemini_service, "_generate", side_effect=Timeout("Provider unavailable")):
        response = client.post("/api/fr11/chat", headers=AUTH, json={"message": "Budget advice"})
    assert response.status_code == 200
    assert response.get_json()["source"] == "travelmate-assistant"
    assert journey.retrieve("chat_messages")[0]["source"] == "travelmate-assistant"
