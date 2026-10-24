"""
Tests for Local Catalog Image Integrity and Provenance Metadata (Batch 21D-D2A)
Verifies that invalid fabricated Wikimedia URLs have been neutralized,
only verified priority attractions retain authentic image metadata,
and all catalog destinations propagate safely through FR03 and FR11.
Runs completely offline without external network dependencies.
"""
import pytest
from services.local_catalog import DESTINATIONS
from modules.fr03_destination_search_information.routes import _local_destination
from modules.fr11_chatbot_travel_assistant.routes import _extract_place_suggestions
from modules.fr11_chatbot_travel_assistant.nlp_extractor import build_structured_trip_plan


PRIORITY_ATTRACTION_IDS = {
    "local_klcc",
    "local_batu_caves",
    "local_merdeka_square",
}


def test_catalog_destinations_structure_and_count():
    """Verify all 35 local destinations are preserved with canonical identifiers."""
    assert len(DESTINATIONS) == 35, f"Expected 35 destinations, found {len(DESTINATIONS)}"
    ids = [d.get("place_id") for d in DESTINATIONS]
    assert len(set(ids)) == 35, "All destination IDs must be unique"

    required_keys = {
        "place_id",
        "destinationId",
        "title",
        "address",
        "category",
        "type",
        "rating",
        "reviews",
        "description",
        "gps_coordinates",
        "indoor",
        "estimatedCost",
        "openingHours",
        "recommendedDurationMinutes",
        "imageUrl",
        "thumbnail",
        "photoAuthor",
        "photoSourceUrl",
        "photoLicense",
        "photoLicenseUrl",
        "photoAttribution",
        "imageSource",
        "imageStatus",
        "lastValidatedAt",
    }
    for d in DESTINATIONS:
        missing = required_keys - set(d.keys())
        assert not missing, f"Destination {d.get('place_id')} missing keys: {missing}"
        assert d.get("imageStatus") in {"verified", "unverified"}, (
            f"Invalid imageStatus in {d.get('place_id')}: {d.get('imageStatus')}"
        )


def test_catalog_three_priority_attractions_verified():
    """Verify only the three priority attractions have authentic verified metadata."""
    verified = [d for d in DESTINATIONS if d.get("imageStatus") == "verified"]
    assert len(verified) == 3, f"Expected exactly 3 verified destinations, found {len(verified)}"
    verified_ids = {d["place_id"] for d in verified}
    assert verified_ids == PRIORITY_ATTRACTION_IDS, f"Unexpected verified IDs: {verified_ids}"

    for d in verified:
        # Full and thumbnail URLs must use HTTPS and recognized Wikimedia domains
        assert d["imageUrl"].startswith("https://upload.wikimedia.org/wikipedia/commons/"), (
            f"Invalid imageUrl format: {d['imageUrl']}"
        )
        assert d["thumbnail"].startswith("https://thumb.wikimedia.org/wikipedia/commons/thumb/"), (
            f"Invalid thumbnail format: {d['thumbnail']}"
        )
        # Provenance fields must be populated
        assert d["photoAuthor"] and len(d["photoAuthor"].strip()) > 2
        assert d["photoSourceUrl"].startswith("https://commons.wikimedia.org/wiki/File:")
        assert d["photoLicense"] in {"CC BY-SA 4.0", "CC BY-SA 3.0", "Public Domain"}
        assert d["photoLicenseUrl"].startswith("https://creativecommons.org/") or d["photoLicense"] == "Public Domain"
        assert d["photoAttribution"] and d["photoAuthor"] in d["photoAttribution"]
        assert d["imageSource"] == "wikimedia_commons"
        assert d["lastValidatedAt"] == "2026-10-24"


def test_catalog_thirty_two_attractions_unverified_safe_null():
    """Verify all other 32 attractions have neutralized image URLs and unverified status."""
    unverified = [d for d in DESTINATIONS if d.get("imageStatus") == "unverified"]
    assert len(unverified) == 32, f"Expected exactly 32 unverified destinations, found {len(unverified)}"

    for d in unverified:
        assert d["place_id"] not in PRIORITY_ATTRACTION_IDS
        # Explicit image URLs must be None to prevent 404 client-side errors
        assert d["imageUrl"] is None, f"Unverified destination {d['place_id']} has non-null imageUrl"
        assert d["thumbnail"] is None, f"Unverified destination {d['place_id']} has non-null thumbnail"
        # Provenance fields must be None (no fictional attribution)
        assert d["photoAuthor"] is None
        assert d["photoSourceUrl"] is None
        assert d["photoLicense"] is None
        assert d["photoLicenseUrl"] is None
        assert d["photoAttribution"] is None
        assert d["imageSource"] is None
        assert d["lastValidatedAt"] is None


def test_no_fabricated_wikimedia_urls_or_unsupported_verified_status():
    """Ensure no destination contains arbitrary, unvalidated Wikimedia paths."""
    for d in DESTINATIONS:
        img = d.get("imageUrl")
        if img is not None:
            assert d.get("place_id") in PRIORITY_ATTRACTION_IDS, (
                f"Non-priority destination {d.get('place_id')} has explicit imageUrl: {img}"
            )
            assert d.get("imageStatus") == "verified"
        else:
            assert d.get("imageStatus") == "unverified"


def test_fr03_destination_details_image_metadata_passthrough():
    """Verify FR03 local destination lookup safely projects verified and unverified DTOs."""
    klcc = _local_destination("local_klcc")
    assert klcc is not None
    assert klcc["place_id"] == "local_klcc"
    assert klcc["imageStatus"] == "verified"
    assert klcc["photoAuthor"] == "Bruce Poon"
    assert klcc["imageUrl"].startswith("https://upload.wikimedia.org/")

    batu = _local_destination("local_batu_caves")
    assert batu is not None
    assert batu["imageStatus"] == "verified"
    assert batu["photoAuthor"] == "CEphoto, Uwe Aranas"

    merdeka = _local_destination("local_merdeka_square")
    assert merdeka is not None
    assert merdeka["imageStatus"] == "verified"
    assert merdeka["photoAuthor"] == "CEphoto, Uwe Aranas"

    unverified = _local_destination("local_george_town")
    assert unverified is not None
    assert unverified["imageStatus"] == "unverified"
    assert unverified["imageUrl"] is None
    assert unverified["thumbnail"] is None


def test_fr11_place_suggestions_image_metadata_serialization():
    """Verify FR11 chatbot suggestions safely include verified image DTOs and handle unverified items."""
    sug = _extract_place_suggestions("What places to visit in Kuala Lumpur", destination_area="Kuala Lumpur")
    assert len(sug) > 0

    klcc = next((s for s in sug if s.get("destinationId") == "local_klcc"), None)
    if klcc:
        assert klcc["imageStatus"] == "verified"
        assert klcc["photoAuthor"] == "Bruce Poon"
        assert klcc["imageUrl"].startswith("https://upload.wikimedia.org/")

    # Suggestions for Penang should have unverified items with null images
    penang_sug = _extract_place_suggestions("Food places in Penang", destination_area="Penang")
    for s in penang_sug:
        assert s["imageStatus"] == "unverified"
        assert s["imageUrl"] is None
        assert s["thumbnail"] is None


def test_fr11_trip_plan_activity_image_safe_fallback():
    """Verify FR11 trip planner safely maps activities when catalog items have null images."""
    plan, status = build_structured_trip_plan("Penang", days=2)
    assert status == "ready"
    assert plan is not None
    activities = plan.get("activities", [])
    assert len(activities) > 0

    for a in activities:
        # nlp_extractor maps missing images to empty strings ('') for client safety
        assert isinstance(a.get("imageUrl"), str)
        assert isinstance(a.get("thumbnail"), str)
        assert isinstance(a.get("photoAttribution"), str)
