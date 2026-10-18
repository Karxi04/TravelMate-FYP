import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

ROOT = Path(__file__).resolve().parents[2]
ADMIN_DIR = ROOT / "admin_website"
OP_DIR = ROOT / "operator_website"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
while str(ADMIN_DIR) in sys.path:
    sys.path.remove(str(ADMIN_DIR))
if str(OP_DIR) not in sys.path:
    sys.path.insert(0, str(OP_DIR))

for k in list(sys.modules.keys()):
    if k == "modules" or k.startswith("modules."):
        del sys.modules[k]

from operator_website.app import app


@pytest.fixture
def auth_client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    if "request_rate_limiter" in app.extensions:
        app.extensions["request_rate_limiter"].reset()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["id_token"] = "fake_op_tok"
            sess["portal_role"] = "operator"
            sess["verification_status"] = "approved"
            sess["operator_id"] = "op_test_1"
        yield client


SAMPLE_PACKAGE_PAYLOAD = {
    "title": "George Town UNESCO Heritage & Hawker Walk",
    "destination": "George Town, Penang",
    "destinationArea": "Heritage Core & Clan Jetties",
    "category": "Culture & Heritage",
    "durationDays": "2",
    "durationNights": "1",
    "shortDescription": "Discover authentic Penang food and shophouses.",
    "fullDescription": "A comprehensive 2-day walking and dining excursion through historic George Town.",
    "heroImage": "https://images.unsplash.com/photo-1596422846543-75c6fc197f07",
    "galleryImages": "https://images.unsplash.com/photo-1\nhttps://images.unsplash.com/photo-2",
    "priceBasis": "per_person",
    "currency": "MYR",
    "adultPrice": "180.00",
    "childPrice": "90.00",
    "originalPrice": "220.00",
    "promotionalPrice": "150.00",
    "promotionStart": "2026-11-01",
    "promotionEnd": "2026-11-30",
    "minimumTravellers": "2",
    "maximumTravellers": "12",
    "taxIncluded": "on",
    "taxNotes": "6% SST and heritage fee included",
    "departureDates": "2026-11-05\n2026-11-12",
    "departureLocation": "Swettenham Pier Cruise Terminal",
    "meetingPoint": "Beside Victoria Memorial Clock Tower",
    "departureNotes": "Please assemble 15 minutes prior to departure.",
    "availabilityStatus": "available",
    "highlights": "UNESCO World Heritage Shophouses\nAuthentic Hawker Tasting\nClan Jetties Stroll",
    "inclusions": "Licensed English-speaking tour guide\nAttraction entrance passes\nMineral water & herbal tea",
    "accommodationName": "Eastern & Oriental Hotel",
    "accommodationCategory": "5-Star Colonial Heritage",
    "roomType": "Heritage Deluxe Suite",
    "transportTypes": "Executive Air-Conditioned Van\nTraditional Trishaw",
    "accommodationNotes": "Check-in at 3:00 PM; check-out at 12:00 PM.",
    "exclusions": "Personal souvenir shopping\nAlcoholic drinks",
    "whatToBring": "Comfortable walking shoes\nSun hat and sunscreen\nLight umbrella",
    "cancellationPolicy": "Free cancellation up to 48 hours prior to start.",
    "refundPolicy": "100% refund processed within 5-7 business days.",
    "bookingTerms": "Instant digital mobile voucher confirmation.",
    "importantNotes": "Moderate walking required along paved streets.",
    "transportNotes": "1 piece of standard luggage per passenger.",
}

SAMPLE_ITINERARY_DAYS = [
    {
        "title": "Day 1 Heritage & Shophouses",
        "accommodation": "Eastern & Oriental Hotel",
        "description": "Guided walking tour along Armenian Street and Clan Jetties.",
        "activities": "Armenian Street Murals\nClan Jetties\nKhoo Kongsi Temple",
        "meals": "Buffet Breakfast\nNyonya Tasting Lunch",
        "transportNotes": "Traditional Trishaw Escort",
    },
    {
        "title": "Day 2 Penang Hill Funicular & Botanical",
        "accommodation": "None (Departure Day)",
        "description": "Scenic morning ascent to Penang Hill and Habitat rainforest walk.",
        "activities": "Penang Hill Funicular\nThe Habitat Rainforest Walk",
        "meals": "High Tea at David Brown Restaurant",
        "transportNotes": "Executive Air-Conditioned Van",
    },
]


def _patch_fr12(mock_call):
    fn_globals = app.view_functions["operator_fr12.new_package"].__globals__
    return patch.dict(fn_globals, {"call_api": mock_call})


def test_package_new_get_contract(auth_client):
    """GET /packages/new must render HTTP 200 with all 43 contract fields and CSRF token."""
    resp = auth_client.get("/packages/new")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Check CSRF token hidden input
    assert 'name="csrf_token"' in html

    # Check 6-step progress stepper
    assert 'class="builder-stepper"' in html
    assert 'Basic Info' in html
    assert 'Pricing & Dates' in html
    assert 'Inclusions' in html
    assert 'Policies & Terms' in html
    assert 'Daily Itinerary' in html
    assert 'Brochure & Submit' in html

    # Check Step 1 fields
    assert 'name="title"' in html
    assert 'name="destination"' in html
    assert 'name="destinationArea"' in html
    assert 'name="category"' in html
    assert 'name="durationDays"' in html
    assert 'name="durationNights"' in html
    assert 'name="shortDescription"' in html
    assert 'name="fullDescription"' in html
    assert 'name="heroImage"' in html
    assert 'name="galleryImages"' in html

    # Check Step 2 fields
    assert 'name="priceBasis"' in html
    assert 'name="currency"' in html
    assert 'name="adultPrice"' in html
    assert 'name="childPrice"' in html
    assert 'name="originalPrice"' in html
    assert 'name="promotionalPrice"' in html
    assert 'name="promotionStart"' in html
    assert 'name="promotionEnd"' in html
    assert 'name="minimumTravellers"' in html
    assert 'name="maximumTravellers"' in html
    assert 'name="taxIncluded"' in html
    assert 'name="taxNotes"' in html
    assert 'name="departureDates"' in html
    assert 'name="departureLocation"' in html
    assert 'name="meetingPoint"' in html
    assert 'name="departureNotes"' in html
    assert 'name="availabilityStatus"' in html

    # Check Step 3 fields
    assert 'name="highlights"' in html
    assert 'name="inclusions"' in html
    assert 'name="accommodationName"' in html
    assert 'name="accommodationCategory"' in html
    assert 'name="roomType"' in html
    assert 'name="transportTypes"' in html
    assert 'name="accommodationNotes"' in html

    # Check Step 4 fields
    assert 'name="exclusions"' in html
    assert 'name="whatToBring"' in html
    assert 'name="cancellationPolicy"' in html
    assert 'name="refundPolicy"' in html
    assert 'name="bookingTerms"' in html
    assert 'name="importantNotes"' in html
    assert 'name="transportNotes"' in html

    # Check Step 5 itinerary fields
    assert 'name="itineraryTitle"' in html
    assert 'name="itineraryAccommodation"' in html
    assert 'name="itineraryDescription"' in html
    assert 'name="itineraryActivities"' in html
    assert 'name="itineraryMeals"' in html
    assert 'name="itineraryTransportNotes"' in html

    # Check Step 6 brochure and submit
    assert 'id="live-brochure-card"' in html
    assert 'id="brochure-hero-banner"' in html
    assert 'id="brochure-status-pill"' in html
    assert 'id="btn-final-submit"' in html


def test_package_new_post_serialization(auth_client):
    """POST /packages/new must serialize all 43 fields and dynamic itinerary array in order."""
    form_data = dict(SAMPLE_PACKAGE_PAYLOAD)

    # Multi-value itinerary arrays
    form_data["itineraryTitle"] = [d["title"] for d in SAMPLE_ITINERARY_DAYS]
    form_data["itineraryAccommodation"] = [d["accommodation"] for d in SAMPLE_ITINERARY_DAYS]
    form_data["itineraryDescription"] = [d["description"] for d in SAMPLE_ITINERARY_DAYS]
    form_data["itineraryActivities"] = [d["activities"] for d in SAMPLE_ITINERARY_DAYS]
    form_data["itineraryMeals"] = [d["meals"] for d in SAMPLE_ITINERARY_DAYS]
    form_data["itineraryTransportNotes"] = [d["transportNotes"] for d in SAMPLE_ITINERARY_DAYS]

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"id": "pkg_new_123", "title": form_data["title"]}

    mock_call = MagicMock(return_value=mock_resp)
    with _patch_fr12(mock_call):
        resp = auth_client.post("/packages/new", data=form_data, follow_redirects=False)

        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/packages")
        assert mock_call.called

        method, endpoint = mock_call.call_args[0]
        kwargs = mock_call.call_args[1]
        payload = kwargs.get("json", {})

        assert method == "POST"
        assert endpoint == "/api/fr12/packages"

        # Verify exact serialization of fields
        assert payload["schemaVersion"] == 2
        assert payload["title"] == "George Town UNESCO Heritage & Hawker Walk"
        assert payload["destination"] == "George Town, Penang"
        assert payload["destinationArea"] == "Heritage Core & Clan Jetties"
        assert payload["category"] == "Culture & Heritage"
        assert payload["durationDays"] == 2
        assert payload["durationNights"] == 1
        assert payload["shortDescription"] == "Discover authentic Penang food and shophouses."
        assert payload["fullDescription"] == "A comprehensive 2-day walking and dining excursion through historic George Town."
        assert payload["heroImage"] == "https://images.unsplash.com/photo-1596422846543-75c6fc197f07"
        assert payload["galleryImages"] == [
            "https://images.unsplash.com/photo-1",
            "https://images.unsplash.com/photo-2",
        ]
        assert payload["priceBasis"] == "per_person"
        assert payload["currency"] == "MYR"
        assert payload["adultPrice"] == 180.00
        assert payload["childPrice"] == 90.00
        assert payload["originalPrice"] == 220.00
        assert payload["promotionalPrice"] == 150.00
        assert payload["promotionStart"] == "2026-11-01"
        assert payload["promotionEnd"] == "2026-11-30"
        assert payload["minimumTravellers"] == 2
        assert payload["maximumTravellers"] == 12
        assert payload["taxIncluded"] is True
        assert payload["taxNotes"] == "6% SST and heritage fee included"
        assert payload["departureDates"] == ["2026-11-05", "2026-11-12"]
        assert payload["departureLocation"] == "Swettenham Pier Cruise Terminal"
        assert payload["meetingPoint"] == "Beside Victoria Memorial Clock Tower"
        assert payload["departureNotes"] == "Please assemble 15 minutes prior to departure."
        assert payload["availabilityStatus"] == "available"
        assert payload["highlights"] == [
            "UNESCO World Heritage Shophouses",
            "Authentic Hawker Tasting",
            "Clan Jetties Stroll",
        ]
        assert payload["inclusions"] == [
            "Licensed English-speaking tour guide",
            "Attraction entrance passes",
            "Mineral water & herbal tea",
        ]
        assert payload["accommodationName"] == "Eastern & Oriental Hotel"
        assert payload["accommodationCategory"] == "5-Star Colonial Heritage"
        assert payload["roomType"] == "Heritage Deluxe Suite"
        assert payload["transportTypes"] == [
            "Executive Air-Conditioned Van",
            "Traditional Trishaw",
        ]
        assert payload["accommodationNotes"] == "Check-in at 3:00 PM; check-out at 12:00 PM."
        assert payload["exclusions"] == [
            "Personal souvenir shopping",
            "Alcoholic drinks",
        ]
        assert payload["whatToBring"] == [
            "Comfortable walking shoes",
            "Sun hat and sunscreen",
            "Light umbrella",
        ]
        assert payload["cancellationPolicy"] == "Free cancellation up to 48 hours prior to start."
        assert payload["refundPolicy"] == "100% refund processed within 5-7 business days."
        assert payload["bookingTerms"] == "Instant digital mobile voucher confirmation."
        assert payload["importantNotes"] == "Moderate walking required along paved streets."
        assert payload["transportNotes"] == "1 piece of standard luggage per passenger."

        # Verify dynamic itinerary array ordering and structure
        itin = payload["itineraryDays"]
        assert len(itin) == 2
        assert itin[0]["dayNumber"] == 1
        assert itin[0]["title"] == "Day 1 Heritage & Shophouses"
        assert itin[0]["accommodation"] == "Eastern & Oriental Hotel"
        assert itin[0]["description"] == "Guided walking tour along Armenian Street and Clan Jetties."
        assert itin[0]["activities"] == ["Armenian Street Murals", "Clan Jetties", "Khoo Kongsi Temple"]
        assert itin[0]["meals"] == ["Buffet Breakfast", "Nyonya Tasting Lunch"]
        assert itin[0]["transportNotes"] == "Traditional Trishaw Escort"

        assert itin[1]["dayNumber"] == 2
        assert itin[1]["title"] == "Day 2 Penang Hill Funicular & Botanical"
        assert itin[1]["accommodation"] == "None (Departure Day)"
        assert itin[1]["activities"] == ["Penang Hill Funicular", "The Habitat Rainforest Walk"]
        assert itin[1]["meals"] == ["High Tea at David Brown Restaurant"]
        assert itin[1]["transportNotes"] == "Executive Air-Conditioned Van"


def test_package_edit_prepopulation(auth_client):
    """GET /packages/<id>/edit-page must pre-populate all existing package data."""
    existing_package = {
        "id": "pkg_existing_888",
        "title": "Batu Ferringhi Coastal Sunset Cruise",
        "destination": "Batu Ferringhi, Penang",
        "destinationArea": "Northern Coastal Strip",
        "category": "Coastal & Island",
        "durationDays": 1,
        "durationNights": 0,
        "shortDescription": "Strait of Malacca luxury catamaran cruise.",
        "fullDescription": "Sail into golden hour sunsets with grilled seafood skewers.",
        "heroImage": "https://example.com/sunset.jpg",
        "adultPrice": 250.00,
        "priceBasis": "per_person",
        "minimumTravellers": 4,
        "maximumTravellers": 20,
        "departureLocation": "Batu Ferringhi Marina",
        "meetingPoint": "Pier 3 Marina Gate",
        "highlights": ["Catamaran Sunset", "Seafood BBQ"],
        "inclusions": ["Catamaran charter", "Welcome drink"],
        "exclusions": ["Hotel pickup outside Batu Ferringhi"],
        "cancellationPolicy": "Full refund if canceled 24 hours prior.",
        "itineraryDays": [
            {
                "dayNumber": 1,
                "title": "Sunset Catamaran Sailing",
                "accommodation": "None",
                "description": "Boarding at 5:00 PM followed by 3-hour sunset cruise.",
                "activities": ["Sailing", "Swimming netting"],
                "meals": ["BBQ Dinner"],
                "transportNotes": "Catamaran Cruise",
            }
        ],
    }

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"items": [existing_package]}

    with _patch_fr12(MagicMock(return_value=mock_resp)):
        resp = auth_client.get("/packages/pkg_existing_888/edit-page")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        assert 'value="Batu Ferringhi Coastal Sunset Cruise"' in html
        assert 'value="Batu Ferringhi, Penang"' in html
        assert 'value="Northern Coastal Strip"' in html
        assert 'value="250.0"' in html or 'value="250.00"' in html
        assert 'value="https://example.com/sunset.jpg"' in html
        assert "Catamaran Sunset" in html
        assert "Catamaran charter" in html
        assert "Hotel pickup outside Batu Ferringhi" in html
        assert "Full refund if canceled 24 hours prior." in html
        assert "Sunset Catamaran Sailing" in html


def test_package_new_post_failure_value_preservation(auth_client):
    """When API returns an error on save, form re-renders and preserves entered values."""
    form_data = dict(SAMPLE_PACKAGE_PAYLOAD)
    form_data["title"] = "Failed Save Preservation Test"

    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 400
    mock_resp.json.return_value = {"error": "Title validation failed on backend."}

    with _patch_fr12(MagicMock(return_value=mock_resp)):
        resp = auth_client.post("/packages/new", data=form_data)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        # Form must re-render with preserved values
        assert 'value="Failed Save Preservation Test"' in html
        assert 'value="George Town, Penang"' in html
        assert 'value="Heritage Core &amp; Clan Jetties"' in html
        assert 'Title validation failed on backend.' in html


def test_package_edit_post_failure_value_preservation(auth_client):
    """When API returns an error on edit, edit page re-renders with edited values preserved."""
    existing_package = {
        "id": "pkg_existing_777",
        "title": "Original Package Title",
        "destination": "George Town, Penang",
        "adultPrice": 100.0,
    }

    get_resp = MagicMock(ok=True, status_code=200, json=lambda: {"items": [existing_package]})
    put_resp = MagicMock(ok=False, status_code=500, json=lambda: {"error": "Database error updating package."})

    def mock_call_api(method, url, **kwargs):
        if method == "GET":
            return get_resp
        return put_resp

    edit_data = dict(SAMPLE_PACKAGE_PAYLOAD)
    edit_data["title"] = "Updated Title That Failed Save"

    with _patch_fr12(MagicMock(side_effect=mock_call_api)):
        resp = auth_client.post("/packages/pkg_existing_777/edit-page", data=edit_data)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        # The updated title must be preserved in the re-rendered form
        assert 'value="Updated Title That Failed Save"' in html
        assert 'Database error updating package.' in html
