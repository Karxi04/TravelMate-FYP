import re
import pytest
from datetime import date
from unittest.mock import patch, MagicMock

from modules.fr11_chatbot_travel_assistant.nlp_extractor import (
    extract_geographic_entities,
    extract_duration,
    extract_budget,
    extract_travellers,
    extract_dates,
    extract_interests,
    extract_day_specific,
    classify_user_intent,
    build_structured_trip_plan,
    find_matching_catalog_destinations,
)
from modules.fr11_chatbot_travel_assistant.routes import _extract_place_suggestions
from services.gemini_service import generateChatbotResponse


# ==============================================================================
# 1. Extraction Tests (Scenarios 1 - 12)
# ==============================================================================

def test_1_food_and_cultural_attractions():
    text = "I enjoy food and cultural attractions."
    ints = extract_interests(text)
    assert "Food" in ints, "Must extract Food interest"
    assert "Culture" in ints, "Must extract Culture interest from 'cultural'"


def test_2_culture_and_history():
    text = "We like culture and history."
    ints = extract_interests(text)
    assert "Culture" in ints, "Must extract Culture interest"


def test_3_cultural_heritage():
    text = "Looking for cultural heritage sites in Malaysia"
    ints = extract_interests(text)
    assert "Culture" in ints, "Must extract Culture interest from 'cultural heritage'"


def test_4_three_people():
    text = "There are three people."
    count = extract_travellers(text)
    assert count == 3, f"Expected 3 travellers, got {count}"


def test_5_four_travellers():
    text = "We are four travellers."
    count = extract_travellers(text)
    assert count == 4, f"Expected 4 travellers, got {count}"


def test_6_two_adults_and_one_child():
    text = "Two adults and one child."
    count = extract_travellers(text)
    ints = extract_interests(text)
    assert count == 3, f"Expected 3 travellers (2 adults + 1 child), got {count}"
    assert "Family" in ints, "Must extract Family interest from 'child'"


def test_7_two_adults_and_two_children():
    text = "two adults and two children"
    count = extract_travellers(text)
    ints = extract_interests(text)
    assert count == 4, f"Expected 4 travellers, got {count}"
    assert "Family" in ints, "Must extract Family interest from 'children'"


def test_8_one_adult_and_one_child():
    text = "one adult and one child"
    count = extract_travellers(text)
    ints = extract_interests(text)
    assert count == 2, f"Expected 2 travellers, got {count}"
    assert "Family" in ints, "Must extract Family interest from 'child'"


def test_9_family_of_four():
    text = "A family of four."
    count = extract_travellers(text)
    ints = extract_interests(text)
    assert count == 4, f"Expected 4 travellers, got {count}"
    assert "Family" in ints, "Must extract Family interest from 'family'"


def test_10_three_of_us():
    text = "There will be three of us travelling."
    count = extract_travellers(text)
    assert count == 3, f"Expected 3 travellers, got {count}"


def test_11_existing_numeric_traveller_expressions():
    assert extract_travellers("3 people") == 3
    assert extract_travellers("4 pax") == 4
    assert extract_travellers("2 adults") == 2
    assert extract_travellers("5 passengers") == 5
    assert extract_travellers("party of 6") is not None or extract_travellers("6 travellers") == 6


def test_12_correct_handling_of_unrelated_numbers():
    # Duration and budget numbers must NOT be extracted as traveller count
    text = "Plan 3 days in Melaka with budget RM500"
    trav = extract_travellers(text)
    assert trav is None, f"Budget/duration numbers must not be treated as travellers, got {trav}"
    assert extract_duration(text) == 3
    assert extract_budget(text) == 500.0


# ==============================================================================
# 2. Multi-Turn PlanningState Tests (Scenarios 13 - 16)
# ==============================================================================

def test_13_traveller_count_updated_from_one_to_three():
    planning_state = {
        'destinationArea': 'Kuala Lumpur',
        'tripDays': 3,
        'travellerCount': 1,
    }
    # Follow-up turn provides explicit new count
    followup = "Actually, there are three people joining."
    new_trav = extract_travellers(followup, planning_state.get('travellerCount'))
    assert new_trav == 3, "New traveller count must override previous value"
    planning_state['travellerCount'] = new_trav
    assert planning_state['travellerCount'] == 3


def test_14_family_interest_retained_after_followup():
    planning_state = {
        'destinationArea': 'Penang',
        'interests': ['Family'],
        'travellerCount': 3,
    }
    # Follow-up turn does not mention family, but mentions budget
    followup = "My budget limit is RM1200."
    new_ints = extract_interests(followup, planning_state.get('interests'))
    assert "Family" in new_ints, "Family interest must be retained across turns"
    planning_state['interests'] = new_ints
    assert "Family" in planning_state['interests']


def test_15_culture_interest_retained_after_budget_change():
    planning_state = {
        'destinationArea': 'Melaka',
        'interests': ['Culture', 'Food'],
        'budgetLimit': 800.0,
    }
    # Follow-up changes budget to RM1500
    followup = "Let's increase the budget to RM1500"
    new_budget = extract_budget(followup, planning_state.get('budgetLimit'))
    new_ints = extract_interests(followup, planning_state.get('interests'))
    assert new_budget == 1500.0
    assert "Culture" in new_ints
    assert "Food" in new_ints


def test_16_previous_destination_and_dates_preserved():
    planning_state = {
        'destinationArea': 'Kuala Lumpur',
        'destinationState': 'Kuala Lumpur',
        'startDate': '2026-12-05',
        'endDate': '2026-12-07',
        'tripDays': 3,
    }
    # Follow-up only adds cultural interest
    followup = "I enjoy cultural attractions and historical museums."
    geo = extract_geographic_entities(followup)
    dur = extract_duration(followup, planning_state.get('tripDays'))
    s_date, e_date = extract_dates(followup, dur or 3, planning_state.get('startDate'), planning_state.get('endDate'))
    
    dest = geo.get('destination_area') or planning_state.get('destinationArea')
    assert dest == 'Kuala Lumpur', "Destination must be preserved"
    assert s_date == '2026-12-05', "Start date must be preserved"
    assert e_date == '2026-12-07', "End date must be preserved"


# ==============================================================================
# 3. Weather-Aware Recommendation Tests (Scenarios 17 - 23)
# ==============================================================================

def test_17_rainy_kuala_lumpur_cultural_attractions():
    msg = "What cultural attractions can I visit in Kuala Lumpur on a rainy day?"
    suggestions = _extract_place_suggestions(msg, destination_area="Kuala Lumpur")
    assert len(suggestions) > 0, "Must return at least one indoor suggestion"
    assert all(d.get('indoor') is True for d in suggestions), "All suggestions must be indoor on a rainy day"
    titles = [d.get('title') for d in suggestions]
    assert any("Petronas" in t for t in titles), "Petronas Twin Towers & KLCC must be returned"
    assert not any("Batu Caves" in t for t in titles), "Batu Caves must NOT be suggested on rainy day"
    assert not any("Merdeka Square" in t for t in titles), "Merdeka Square must NOT be suggested on rainy day"


def test_18_rainy_penang_sightseeing():
    msg = "Recommend places to visit in Penang if it rains tomorrow."
    suggestions = _extract_place_suggestions(msg, destination_area="Penang")
    assert len(suggestions) > 0, "Must return Penang indoor suggestions"
    assert all(d.get('indoor') is True for d in suggestions), "All Penang suggestions must be indoor on rain request"
    titles = [d.get('title') for d in suggestions]
    assert any("Peranakan" in t or "Wonderfood" in t or "Plaza" in t for t in titles)


def test_19_normal_kuala_lumpur_outdoor_sightseeing():
    msg = "What attractions can I visit in Kuala Lumpur?"
    suggestions = _extract_place_suggestions(msg, destination_area="Kuala Lumpur")
    assert len(suggestions) > 0
    titles = [d.get('title') for d in suggestions]
    # Outdoor attractions must be present when there is no rain request
    assert any("Batu Caves" in t or "Merdeka" in t for t in titles), "Outdoor sights should be returned normally"


def test_20_no_verified_indoor_candidates():
    # Perlis has 0 static records in local_catalog.py
    msg = "What attractions can I visit in Perlis on a rainy day?"
    suggestions = _extract_place_suggestions(msg, destination_area="Perlis")
    assert suggestions == [], "Must return empty list without crashing or leaking other states' attractions"


def test_21_unrelated_words_containing_rain():
    # Words like "train" must NOT trigger indoor-only filtering
    msg = "How can I take the train to visit attractions in Kuala Lumpur?"
    suggestions = _extract_place_suggestions(msg, destination_area="Kuala Lumpur")
    titles = [d.get('title') for d in suggestions]
    assert any("Batu Caves" in t or "Merdeka" in t for t in titles), "'train' must not trigger rain indoor filter"


def test_22_outdoor_request_with_no_rainy_day_constraint():
    msg = "Where can I go for nice outdoor sightseeing in Kuala Lumpur?"
    suggestions = _extract_place_suggestions(msg, destination_area="Kuala Lumpur")
    titles = [d.get('title') for d in suggestions]
    assert any("Batu Caves" in t or "Merdeka" in t or "Food Street" in t for t in titles)


def test_23_geographic_isolation_across_malaysian_states():
    kl_sug = _extract_place_suggestions("What places can I visit?", destination_area="Kuala Lumpur")
    assert all("kuala lumpur" in (d.get('address', '') + d.get('city', '') + d.get('state', '')).lower() for d in kl_sug)

    pen_sug = _extract_place_suggestions("What places can I visit?", destination_area="Penang")
    assert all("penang" in (d.get('address', '') + d.get('city', '') + d.get('state', '')).lower() for d in pen_sug)


# ==============================================================================
# 4. Source Transparency Tests (Scenarios 24 - 25)
# ==============================================================================

def test_24_gemini_response_source():
    # When _generate succeeds, source must be 'gemini'
    with patch('services.gemini_service.is_gemini_configured', return_value=True):
        with patch('services.gemini_service._generate', return_value='Authentic Gemini response'):
            res = generateChatbotResponse("Hello", with_source=True)
            assert isinstance(res, dict)
            assert res['source'] == 'gemini'
            assert res['reply'] == 'Authentic Gemini response'


def test_25_fallback_response_source():
    # When Gemini fails (e.g. 429 quota exhaustion), source must be 'travelmate-assistant'
    with patch('services.gemini_service.is_gemini_configured', return_value=True):
        with patch('services.gemini_service._generate', side_effect=Exception('429 RESOURCE_EXHAUSTED')):
            with patch('services.gemini_service._fallback_mode', return_value=True):
                res = generateChatbotResponse("What can I do if it rains?", with_source=True)
                assert isinstance(res, dict)
                assert res['source'] == 'travelmate-assistant'
                assert 'Weather tool' in res['reply']
