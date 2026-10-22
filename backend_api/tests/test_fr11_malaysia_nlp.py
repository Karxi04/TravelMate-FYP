import pytest
from unittest.mock import patch, MagicMock
from datetime import date, timedelta
from modules.fr11_chatbot_travel_assistant.nlp_extractor import (
    extract_geographic_entities,
    extract_duration,
    extract_budget,
    extract_travellers,
    extract_dates,
    extract_interests,
    extract_day_specific,
    classify_user_intent,
    check_requirement_completeness,
    build_structured_trip_plan,
    validate_save_plan_payload,
    find_matching_catalog_destinations,
)


# ============================================================================
# 1. Malaysian States Coverage (13 States)
# ============================================================================

@pytest.mark.parametrize("query,expected_area,expected_state", [
    ("Plan a trip to Johor Bahru", "Johor Bahru", "Johor"),
    ("Plan a trip to Langkawi, Kedah", "Langkawi", "Kedah"),
    ("Plan a trip to Kota Bharu", "Kota Bharu", "Kelantan"),
    ("Plan a trip to Melaka", "Melaka City", "Melaka"),
    ("Plan a trip to Seremban", "Seremban", "Negeri Sembilan"),
    ("Plan a trip to Kuantan", "Kuantan", "Pahang"),
    ("Plan a trip to Penang", "Penang", "Penang"),
    ("Plan a trip to Ipoh, Perak", "Ipoh", "Perak"),
    ("Plan a trip to Kangar", "Kangar", "Perlis"),
    ("Plan a trip to Kota Kinabalu", "Kota Kinabalu", "Sabah"),
    ("Plan a trip to Kuching", "Kuching", "Sarawak"),
    ("Plan a trip to Petaling Jaya", "Petaling Jaya", "Selangor"),
    ("Plan a trip to Kuala Terengganu", "Kuala Terengganu", "Terengganu"),
])
def test_all_malaysian_states_recognized(query, expected_area, expected_state):
    geo = extract_geographic_entities(query)
    assert geo['destination_country'] == 'Malaysia'
    assert geo['destination_state'] == expected_state
    assert geo['destination_area'] == expected_area
    assert geo['is_foreign'] is False


# ============================================================================
# 2. Federal Territories (3 FTs)
# ============================================================================

@pytest.mark.parametrize("query,expected_area,expected_state", [
    ("Plan a trip to Kuala Lumpur", "Kuala Lumpur", "Kuala Lumpur"),
    ("Plan a visit to Putrajaya", "Putrajaya", "Putrajaya"),
    ("Plan a trip to Labuan", "Labuan", "Labuan"),
])
def test_federal_territories_recognized(query, expected_area, expected_state):
    geo = extract_geographic_entities(query)
    assert geo['destination_country'] == 'Malaysia'
    assert geo['destination_state'] == expected_state
    assert geo['destination_area'] == expected_area


# ============================================================================
# 3. Penang Locality & Mainland Destinations
# ============================================================================

@pytest.mark.parametrize("query,expected_locality", [
    ("Plan a heritage tour in George Town", "George Town"),
    ("Plan a food trip to Butterworth", "Butterworth"),
    ("Explore nature in Balik Pulau", "Balik Pulau"),
    ("Visit Kek Lok Si temple in Air Itam", "Air Itam"),
])
def test_penang_localities_recognized(query, expected_locality):
    geo = extract_geographic_entities(query)
    assert geo['destination_state'] == 'Penang'
    assert geo['destination_area'] == expected_locality


# ============================================================================
# 4. East Malaysian Localities
# ============================================================================

@pytest.mark.parametrize("query,expected_area,expected_state", [
    ("Plan a highland trip to Kundasang", "Kundasang", "Sabah"),
    ("Visit Sepilok in Sandakan", "Sandakan", "Sabah"),
    ("Explore Miri national parks", "Miri", "Sarawak"),
])
def test_east_malaysia_localities_recognized(query, expected_area, expected_state):
    geo = extract_geographic_entities(query)
    assert geo['destination_state'] == expected_state
    assert geo['destination_area'] == expected_area


# ============================================================================
# 5. Malaysian Islands
# ============================================================================

@pytest.mark.parametrize("query,expected_area,expected_state", [
    ("Plan a 4-day Langkawi holiday", "Langkawi", "Kedah"),
    ("Recommend diving in Redang Island", "Redang Island", "Terengganu"),
    ("Snorkeling in Perhentian", "Perhentian", "Terengganu"),
])
def test_malaysian_islands_recognized(query, expected_area, expected_state):
    geo = extract_geographic_entities(query)
    assert geo['destination_state'] == expected_state
    assert geo['destination_area'] == expected_area


# ============================================================================
# 6. Alternate Names & Common Spellings
# ============================================================================

@pytest.mark.parametrize("query,expected_state", [
    ("Plan a trip to Pulau Pinang", "Penang"),
    ("Heritage walk in Georgetown", "Penang"),
    ("Historical tour in Malacca", "Melaka"),
    ("Temple visit in Ayer Itam", "Penang"),
])
def test_alternate_place_names_resolved(query, expected_state):
    geo = extract_geographic_entities(query)
    assert geo['destination_state'] == expected_state


# ============================================================================
# 7. Common Abbreviations
# ============================================================================

@pytest.mark.parametrize("query,expected_area,expected_state", [
    ("Plan a 3-day KL trip", "Kuala Lumpur", "Kuala Lumpur"),
    ("Weekend trip to JB", "Johor Bahru", "Johor"),
    ("Holiday in KK Sabah", "Kota Kinabalu", "Sabah"),
])
def test_common_abbreviations_resolved(query, expected_area, expected_state):
    geo = extract_geographic_entities(query)
    assert geo['destination_area'] == expected_area
    assert geo['destination_state'] == expected_state


# ============================================================================
# 8. Foreign Destinations (Explicit Rejection from Malaysian Scope)
# ============================================================================

@pytest.mark.parametrize("query,foreign_name", [
    ("Plan a trip to Singapore", "Singapore"),
    ("Plan a 5-day holiday in Tokyo", "Tokyo, Japan"),
    ("Recommend Bangkok attractions", "Bangkok, Thailand"),
    ("Create a five-day itinerary in Bali", "Bali, Indonesia"),
])
def test_foreign_destinations_flagged_unsupported(query, foreign_name):
    geo = extract_geographic_entities(query)
    assert geo['is_foreign'] is True
    assert geo['destination_country'] is None
    assert geo['unsupported_foreign'] == foreign_name


# ============================================================================
# 9. International Transport Origin with Malaysian Sightseeing Destination
# ============================================================================

def test_flight_origin_foreign_with_malaysian_destination():
    # Flying from Singapore to Penang: origin is foreign, destination is Malaysia!
    geo1 = extract_geographic_entities("Plan a trip from Singapore to Penang.")
    assert geo1['foreign_origin'] == 'Singapore'
    assert geo1['destination_area'] == 'Penang'
    assert geo1['destination_state'] == 'Penang'
    assert geo1['destination_country'] == 'Malaysia'
    assert geo1['is_foreign'] is False

    # Flying from Tokyo to Kuala Lumpur
    geo2 = extract_geographic_entities("Flying from Tokyo to Kuala Lumpur for 5 days.")
    assert geo2['foreign_origin'] == 'Tokyo, Japan'
    assert geo2['destination_area'] == 'Kuala Lumpur'
    assert geo2['destination_state'] == 'Kuala Lumpur'
    assert geo2['destination_country'] == 'Malaysia'
    assert geo2['is_foreign'] is False


# ============================================================================
# 10. Multi-State Itineraries
# ============================================================================

def test_multi_destination_detection():
    geo = extract_geographic_entities("Plan a trip from Kuala Lumpur to Ipoh and Penang.")
    assert geo['is_multi_destination'] is True
    assert 'Kuala Lumpur' in geo['multiple_destinations']
    assert 'Ipoh' in geo['multiple_destinations']
    assert 'Penang' in geo['multiple_destinations']

    geo2 = extract_geographic_entities("Visit Melaka and Johor Bahru over five days.")
    assert geo2['is_multi_destination'] is True
    assert 'Melaka City' in geo2['multiple_destinations']
    assert 'Johor Bahru' in geo2['multiple_destinations']


# ============================================================================
# 11. Explicit Date Parsing
# ============================================================================

def test_explicit_date_parsing():
    s1, e1 = extract_dates("Start on 25 October 2026", duration_days=3)
    assert s1 == "2026-10-25"
    assert e1 == "2026-10-27"

    s2, e2 = extract_dates("Travel from 25/10/2026", duration_days=4)
    assert s2 == "2026-10-25"
    assert e2 == "2026-10-28"


# ============================================================================
# 12. Relative Date Parsing
# ============================================================================

def test_relative_date_parsing():
    today = date.today()
    s1, e1 = extract_dates("Starting tomorrow", duration_days=3)
    expected_start = (today + timedelta(days=1)).isoformat()
    expected_end = (today + timedelta(days=3)).isoformat()
    assert s1 == expected_start
    assert e1 == expected_end

    s2, e2 = extract_dates("Trip next Saturday", duration_days=2)
    assert s2 is not None
    assert e2 is not None


# ============================================================================
# 13. Duration Expressions
# ============================================================================

@pytest.mark.parametrize("query,expected_days", [
    ("Plan a 3-day Kuala Lumpur trip", 3),
    ("Five days in Sabah", 5),
    ("Four days in Langkawi", 4),
    ("Three days and two nights in Melaka", 3),
    ("Weekend trip to Melaka", 2),
    ("A week travelling in Penang", 7),
])
def test_duration_expressions_extracted(query, expected_days):
    assert extract_duration(query) == expected_days


# ============================================================================
# 14. Budget Extraction
# ============================================================================

@pytest.mark.parametrize("query,expected_budget", [
    ("Plan a trip with budget RM500", 500.0),
    ("Looking for places under RM 800", 800.0),
    ("Budget of 1,500 ringgit", 1500.0),
    ("Under RM1,000", 1000.0),
    ("Maximum budget RM2,000", 2000.0),
    ("Reduce my budget to RM600", 600.0),
])
def test_budget_expressions_extracted(query, expected_budget):
    assert extract_budget(query) == expected_budget


# ============================================================================
# 15. Traveller Count Extraction
# ============================================================================

@pytest.mark.parametrize("query,expected_count", [
    ("Solo trip to Penang", 1),
    ("Holiday for two people", 2),
    ("Vacation for a family of four", 4),
    ("There are three travellers", 3),
    ("Trip for 5 pax in Sabah", 5),
])
def test_traveller_count_extracted(query, expected_count):
    assert extract_travellers(query) == expected_count


# ============================================================================
# 16. Preferences Extraction (Food, Culture, Nature, Beach)
# ============================================================================

def test_interest_preferences_extracted():
    ints1 = extract_interests("I love local food and culinary experiences")
    assert 'Food' in ints1

    ints2 = extract_interests("Interested in heritage, colonial architecture and museum stops")
    assert 'Culture' in ints2

    ints3 = extract_interests("We love nature, mountain hiking and adventure")
    assert 'Nature' in ints3

    ints4 = extract_interests("Looking for relaxing beach and island time")
    assert 'Beach' in ints4
    assert 'Relaxation' in ints4


# ============================================================================
# 17. Requirement Clarification vs Provisional Exploration
# ============================================================================

def test_clarification_for_underspecified_planning_request():
    # User says "Plan my holiday" without destination -> Clarification needed!
    check = check_requirement_completeness("Plan my holiday")
    assert check['clarification_needed'] is True
    assert 'destination' in check['missing']
    assert check['ready'] is False

    # User says "Plan a 3-day Langkawi trip for RM800" -> Destination known -> Ready!
    check2 = check_requirement_completeness("Plan a 3-day Langkawi trip for RM800")
    assert check2['clarification_needed'] is False
    assert check2['ready'] is True
    assert check2['destination'] == 'Langkawi'


def test_general_question_does_not_demand_planning_constraints():
    # Asking for food recommendations in KL should NOT demand dates or duration
    check = check_requirement_completeness("Recommend food in Kuala Lumpur")
    assert check['intent'] == 'GENERAL_QUESTION'
    assert check['clarification_needed'] is False
    assert check['ready'] is False


def test_provisional_exploration_intent():
    check = check_requirement_completeness("I want somewhere relaxing in Malaysia")
    assert check['intent'] == 'PROVISIONAL_EXPLORATION'
    assert check['clarification_needed'] is False
    assert check['ready'] is False


# ============================================================================
# 18. Multi-Turn Context Retention (7-Turn Sequence from Section 9)
# ============================================================================

def test_seven_turn_multi_turn_state_retention():
    state = {}
    turns = [
        ("Plan a 4-day trip to Kota Kinabalu.", {"destinationArea": "Kota Kinabalu", "destinationState": "Sabah", "tripDays": 4}),
        ("Our total budget is RM2,000.", {"budgetLimit": 2000.0}),
        ("There are three of us.", {"travellerCount": 3}),
        ("We enjoy nature and local food.", {"interests": ["Food", "Nature"]}),
        ("Start on 5 December 2026.", {"startDate": "2026-12-05", "endDate": "2026-12-08"}),
        ("Actually change the budget to RM1,800.", {"budgetLimit": 1800.0}),
        ("Make Day 2 more relaxing.", {"daySpecificPreferences": {2: "relaxing"}}),
    ]

    for utterance, expected_updates in turns:
        geo = extract_geographic_entities(utterance)
        dur = extract_duration(utterance, state.get('tripDays'))
        bud = extract_budget(utterance, state.get('budgetLimit'))
        trav = extract_travellers(utterance, state.get('travellerCount'))
        s_date, e_date = extract_dates(utterance, dur or 3, state.get('startDate'), state.get('endDate'))
        ints = extract_interests(utterance, state.get('interests'))
        day_pref = extract_day_specific(utterance)

        if geo.get('destination_area'):
            state['destinationArea'] = geo['destination_area']
            state['destinationState'] = geo['destination_state']
            state['destinationCountry'] = 'Malaysia'
        if dur: state['tripDays'] = dur
        if bud: state['budgetLimit'] = bud
        if trav: state['travellerCount'] = trav
        if s_date:
            state['startDate'] = s_date
            state['endDate'] = e_date
        if ints: state['interests'] = ints
        if day_pref:
            cur = dict(state.get('daySpecificPreferences') or {})
            cur.update(day_pref)
            state['daySpecificPreferences'] = cur

        for k, v in expected_updates.items():
            assert state[k] == v

    # Final accumulated state verification:
    assert state['destinationArea'] == 'Kota Kinabalu'
    assert state['destinationState'] == 'Sabah'
    assert state['tripDays'] == 4
    assert state['startDate'] == '2026-12-05'
    assert state['endDate'] == '2026-12-08'
    assert state['budgetLimit'] == 1800.0
    assert state['travellerCount'] == 3
    assert 'Food' in state['interests'] and 'Nature' in state['interests']
    assert state['daySpecificPreferences'][2] == 'relaxing'


# ============================================================================
# 19. Catalog Data Coverage & Geographic Fallback Integrity
# ============================================================================

def test_kuala_lumpur_trip_contains_only_kuala_lumpur_activities():
    plan, status = build_structured_trip_plan("Kuala Lumpur", "Kuala Lumpur", days=3, budget_limit=1500.0)
    assert status == 'ready'
    assert plan['destinationArea'] == 'Kuala Lumpur'
    assert len(plan['activities']) == 9
    for act in plan['activities']:
        assert 'Penang' not in act['address'], f"Defect: Penang activity found in KL plan: {act['activityName']}"
        assert 'Kuala Lumpur' in act['address'] or 'Gombak' in act['address']


def test_melaka_trip_contains_only_melaka_activities():
    plan, status = build_structured_trip_plan("Melaka City", "Melaka", days=2, budget_limit=800.0)
    assert status == 'ready'
    assert len(plan['activities']) == 6
    for act in plan['activities']:
        assert 'Melaka' in act['address'] or 'Banda Hilir' in act['address']
        assert 'Penang' not in act['address']


def test_langkawi_trip_contains_only_langkawi_activities():
    plan, status = build_structured_trip_plan("Langkawi", "Kedah", days=3, budget_limit=1200.0)
    assert status == 'ready'
    assert len(plan['activities']) == 9
    for act in plan['activities']:
        assert 'Langkawi' in act['address']
        assert 'Penang' not in act['address']


def test_data_coverage_gap_reported_truthfully():
    # Kangar (Perlis) has no static catalog destinations -> Must report coverage_gap, NOT substitute Penang!
    plan, status = build_structured_trip_plan("Kangar", "Perlis", days=3)
    assert status == 'coverage_gap'
    assert plan is None

    # Labuan has no static catalog destinations -> Must report coverage_gap
    plan_labuan, status_labuan = build_structured_trip_plan("Labuan", "Labuan", days=2)
    assert status_labuan == 'coverage_gap'
    assert plan_labuan is None


# ============================================================================
# 20. Save Endpoint Independent Validation
# ============================================================================

def test_save_plan_validation_rules():
    # Valid KL plan
    valid_kl = {
        'title': '3-Day Kuala Lumpur Plan',
        'destinationArea': 'Kuala Lumpur',
        'startDate': '2026-10-25',
        'endDate': '2026-10-27',
        'budgetLimit': 1500.0,
        'numberOfTravellers': 2,
        'activities': [{'activityName': 'Petronas Towers', 'address': 'Kuala Lumpur, Malaysia', 'state': 'Kuala Lumpur'}]
    }
    ok, msg = validate_save_plan_payload(valid_kl)
    assert ok is True

    # Geographic mismatch: KL plan with Penang activity
    mismatched = {
        'title': '3-Day Kuala Lumpur Plan',
        'destinationArea': 'Kuala Lumpur',
        'startDate': '2026-10-25',
        'endDate': '2026-10-27',
        'budgetLimit': 1500.0,
        'numberOfTravellers': 2,
        'activities': [{'activityName': 'Kek Lok Si Temple', 'address': 'Air Itam, Penang, Malaysia', 'state': 'Penang'}]
    }
    ok, msg = validate_save_plan_payload(mismatched)
    assert ok is False
    assert 'Geographic mismatch' in msg

    # Foreign destination rejected
    foreign_plan = {
        'title': 'Tokyo Trip',
        'destinationArea': 'Tokyo',
        'startDate': '2026-10-25',
        'endDate': '2026-10-27',
        'budgetLimit': 3000.0,
        'numberOfTravellers': 1,
        'activities': [{'activityName': 'Shibuya', 'address': 'Tokyo, Japan'}]
    }
    ok, msg = validate_save_plan_payload(foreign_plan)
    assert ok is False
    assert 'only supports travel destinations within Malaysia' in msg

    # Non-positive budget rejected
    zero_budget = dict(valid_kl, budgetLimit=0)
    ok, msg = validate_save_plan_payload(zero_budget)
    assert ok is False
    assert 'Budget limit must be a positive amount' in msg

    # Invalid dates (start > end) rejected
    bad_dates = dict(valid_kl, startDate='2026-10-30', endDate='2026-10-25')
    ok, msg = validate_save_plan_payload(bad_dates)
    assert ok is False
    assert 'startDate' in msg and 'endDate' in msg

    # Zero travellers rejected
    no_travellers = dict(valid_kl, numberOfTravellers=0)
    ok, msg = validate_save_plan_payload(no_travellers)
    assert ok is False
    assert 'Number of travellers must be at least 1' in msg

    # Empty activities rejected
    empty_acts = dict(valid_kl, activities=[])
    ok, msg = validate_save_plan_payload(empty_acts)
    assert ok is False
    assert 'Cannot save a trip without scheduled activities' in msg


# ============================================================================
# 21. API Endpoint Integration Tests (/api/fr11/chat and /api/fr11/save-plan)
# ============================================================================

def test_api_chat_kuala_lumpur_creates_kl_plan(client, mock_traveller_auth):
    with patch('modules.fr11_chatbot_travel_assistant.routes.retrieveRecord') as mock_retrieve, \
         patch('modules.fr11_chatbot_travel_assistant.routes.storeRecord') as mock_store, \
         patch('modules.fr11_chatbot_travel_assistant.routes.updateRecord') as mock_update:

        mock_retrieve.return_value = []
        mock_store.side_effect = lambda coll, data: {'id': f'mock_{coll}_id', **data}
        mock_update.side_effect = lambda coll, doc_id, data: {'id': doc_id, **data}

        res = client.post(
            '/api/fr11/chat',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'message': 'Plan a 3-day Kuala Lumpur trip for RM1500'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert 'tripPlan' in data['item']
        plan = data['item']['tripPlan']
        assert plan['destinationArea'] == 'Kuala Lumpur'
        assert plan['budgetLimit'] == 1500.0
        assert len(plan['activities']) == 9
        # Check that activities are KL, NOT Penang!
        for a in plan['activities']:
            assert 'Penang' not in a['address']
            assert 'Kuala Lumpur' in a['address'] or 'Gombak' in a['address']


def test_api_chat_foreign_destination_returns_polite_rejection(client, mock_traveller_auth):
    with patch('modules.fr11_chatbot_travel_assistant.routes.retrieveRecord') as mock_retrieve, \
         patch('modules.fr11_chatbot_travel_assistant.routes.storeRecord') as mock_store, \
         patch('modules.fr11_chatbot_travel_assistant.routes.updateRecord') as mock_update:

        mock_retrieve.return_value = []
        mock_store.side_effect = lambda coll, data: {'id': f'mock_{coll}_id', **data}
        mock_update.side_effect = lambda coll, doc_id, data: {'id': doc_id, **data}

        res = client.post(
            '/api/fr11/chat',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'message': 'Plan a 5-day holiday in Tokyo'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert 'tripPlan' not in data['item']
        assert 'TravelMate is dedicated exclusively to travel planning within Malaysia' in data['reply']


def test_api_chat_clarification_for_missing_destination(client, mock_traveller_auth):
    with patch('modules.fr11_chatbot_travel_assistant.routes.retrieveRecord') as mock_retrieve, \
         patch('modules.fr11_chatbot_travel_assistant.routes.storeRecord') as mock_store, \
         patch('modules.fr11_chatbot_travel_assistant.routes.updateRecord') as mock_update:

        mock_retrieve.return_value = []
        mock_store.side_effect = lambda coll, data: {'id': f'mock_{coll}_id', **data}
        mock_update.side_effect = lambda coll, doc_id, data: {'id': doc_id, **data}

        res = client.post(
            '/api/fr11/chat',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'message': 'Plan my holiday'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert 'tripPlan' not in data['item']
        assert 'Which destination would you like to explore?' in data['reply']


def test_api_chat_message_length_limit(client, mock_traveller_auth):
    res = client.post(
        '/api/fr11/chat',
        headers={'Authorization': 'Bearer valid_test_token'},
        json={'message': 'a' * 2050}
    )
    assert res.status_code == 400
    assert 'exceeds 2000 character limit' in res.get_json()['error']


def test_api_save_plan_mismatched_activities_rejected(client, mock_traveller_auth):
    mismatched_plan = {
        'title': 'Kuala Lumpur Trip',
        'destinationArea': 'Kuala Lumpur',
        'startDate': '2026-10-25',
        'endDate': '2026-10-27',
        'budgetLimit': 1200.0,
        'numberOfTravellers': 1,
        'activities': [
            {
                'activityName': 'Penang Hill',
                'address': 'Air Itam, Penang, Malaysia',
                'state': 'Penang',
                'dayNo': 1,
            }
        ]
    }
    res = client.post(
        '/api/fr11/save-plan',
        headers={'Authorization': 'Bearer valid_test_token'},
        json={'plan': mismatched_plan}
    )
    assert res.status_code == 400
    assert 'Geographic mismatch' in res.get_json()['error']


def test_api_save_plan_foreign_destination_rejected(client, mock_traveller_auth):
    foreign_plan = {
        'title': 'Tokyo Trip',
        'destinationArea': 'Tokyo',
        'startDate': '2026-10-25',
        'endDate': '2026-10-27',
        'budgetLimit': 3000.0,
        'numberOfTravellers': 1,
        'activities': [{'activityName': 'Shibuya Crossing', 'address': 'Tokyo, Japan', 'state': 'Tokyo'}]
    }
    res = client.post(
        '/api/fr11/save-plan',
        headers={'Authorization': 'Bearer valid_test_token'},
        json={'plan': foreign_plan}
    )
    assert res.status_code == 400
    assert 'only supports travel destinations within Malaysia' in res.get_json()['error']


def test_api_save_plan_success_kuala_lumpur(client, mock_traveller_auth):
    valid_kl = {
        'title': '3-Day Kuala Lumpur Plan',
        'destinationArea': 'Kuala Lumpur',
        'startDate': '2026-10-25',
        'endDate': '2026-10-27',
        'budgetLimit': 1500.0,
        'numberOfTravellers': 2,
        'activities': [
            {
                'activityName': 'Petronas Twin Towers & KLCC',
                'destinationId': 'local_klcc',
                'address': 'Kuala Lumpur City Centre, Kuala Lumpur, Malaysia',
                'state': 'Kuala Lumpur',
                'dayNo': 1,
                'timeSlot': 'Morning',
                'estimatedCost': 80.0,
            }
        ]
    }
    with patch('modules.fr11_chatbot_travel_assistant.routes.storeRecord') as mock_store:
        mock_store.side_effect = lambda coll, data: {'id': 'itin_kl_1', **data}

        res = client.post(
            '/api/fr11/save-plan',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'plan': valid_kl}
        )
        assert res.status_code == 201
        data = res.get_json()
        assert data['ok'] is True
        assert data['itinerary']['destinationArea'] == 'Kuala Lumpur'
        assert data['itinerary']['destinationCountry'] == 'Malaysia'
        assert data['itinerary']['travellerId'] == 'test_traveller_uid'
        assert 'budget' in data
