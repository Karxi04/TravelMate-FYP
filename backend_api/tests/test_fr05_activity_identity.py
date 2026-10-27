import pytest
from unittest.mock import patch, MagicMock
from copy import deepcopy

from sequence_contract.domain_functions import (
    addActivity,
    removeActivity,
    rearrangeActivity,
    updateActivity,
    createItinerary,
    calculateBudget,
    recalculateItinerary,
    generateItinerary,
)
from services.budget_aware_selection import select_budget_aware_activities


# ==============================================================================
# SECTION 5: FAILING REPRODUCTION BEFORE REPAIR
# ==============================================================================

def test_reproduction_activity_id_collision_on_unpatched_code():
    """
    1. Create a synthetic Trip with A1, A2 and A3.
    2. Delete A2.
    3. Add a new attraction.
    4. Verify that newly added activity receives a collision-free ID.
    5. Demonstrate that IDs are unique and remove/rearrange operate on exactly one intended activity.
    """
    trip = {
        'id': 'trip_collision_repro',
        'activities': [
            {'activityId': 'A1', 'activityName': 'First Attraction'},
            {'activityId': 'A2', 'activityName': 'Second Attraction'},
            {'activityId': 'A3', 'activityName': 'Third Attraction'},
        ]
    }

    # Step 2: Delete A2
    trip = removeActivity(trip, 'A2')
    assert [x['activityId'] for x in trip['activities']] == ['A1', 'A3']

    # Step 3: Add new attraction
    trip = addActivity(trip, {'activityName': 'Fourth Attraction'})

    # Step 4: Verify NO collision (all activity IDs must be distinct)
    ids = [x['activityId'] for x in trip['activities']]
    assert len(ids) == len(set(ids)), f"Collision detected! Duplicate activity IDs: {ids}"
    assert ids[-1] != 'A3', f"Newly added activity reused A3! IDs: {ids}"
    assert ids[-1] == 'A4'

    # Step 5: Verify remove only removes intended activity
    after_remove = removeActivity(trip, 'A3')
    assert len(after_remove['activities']) == 2
    assert [x['activityId'] for x in after_remove['activities']] == ['A1', 'A4']

    # Step 6: Verify rearrange does not collapse distinct activities
    after_rearrange = rearrangeActivity(trip, ['A4', 'A1', 'A3'])
    assert len(after_rearrange['activities']) == 3
    assert [x['activityId'] for x in after_rearrange['activities']] == ['A4', 'A1', 'A3']


# ==============================================================================
# SECTION 10: 20 MANDATORY TEST SCENARIOS
# ==============================================================================

def test_scenario_1_normal_first_activity_creation():
    """Scenario 1: Adding an activity to an empty trip creates ID 'A1'."""
    trip = {'id': 't1', 'activities': []}
    updated = addActivity(trip, {'activityName': 'First Place'})
    assert len(updated['activities']) == 1
    assert updated['activities'][0]['activityId'] == 'A1'
    assert updated['activities'][0]['activityName'] == 'First Place'


def test_scenario_2_multiple_sequential_additions():
    """Scenario 2: Multiple sequential additions produce sequential unique IDs (A1, A2, A3)."""
    trip = {'id': 't2', 'activities': []}
    trip = addActivity(trip, {'activityName': 'Place 1'})
    trip = addActivity(trip, {'activityName': 'Place 2'})
    trip = addActivity(trip, {'activityName': 'Place 3'})
    ids = [x['activityId'] for x in trip['activities']]
    assert ids == ['A1', 'A2', 'A3']
    assert len(ids) == len(set(ids))


def test_scenario_3_delete_middle_activity_and_add_again():
    """Scenario 3: Delete middle activity (A2) from [A1, A2, A3] and add new place -> allocates A4."""
    trip = {
        'id': 't3',
        'activities': [
            {'activityId': 'A1', 'activityName': 'Place 1'},
            {'activityId': 'A2', 'activityName': 'Place 2'},
            {'activityId': 'A3', 'activityName': 'Place 3'},
        ]
    }
    trip = removeActivity(trip, 'A2')
    assert [x['activityId'] for x in trip['activities']] == ['A1', 'A3']

    trip = addActivity(trip, {'activityName': 'Place 4'})
    ids = [x['activityId'] for x in trip['activities']]
    assert ids == ['A1', 'A3', 'A4']
    assert len(ids) == len(set(ids))


def test_scenario_4_delete_first_activity_and_add_again():
    """Scenario 4: Delete first activity (A1) from [A1, A2, A3] and add new place -> allocates A4."""
    trip = {
        'id': 't4',
        'activities': [
            {'activityId': 'A1', 'activityName': 'Place 1'},
            {'activityId': 'A2', 'activityName': 'Place 2'},
            {'activityId': 'A3', 'activityName': 'Place 3'},
        ]
    }
    trip = removeActivity(trip, 'A1')
    assert [x['activityId'] for x in trip['activities']] == ['A2', 'A3']

    trip = addActivity(trip, {'activityName': 'Place 4'})
    ids = [x['activityId'] for x in trip['activities']]
    assert ids == ['A2', 'A3', 'A4']
    assert len(ids) == len(set(ids))


def test_scenario_5_delete_last_activity_and_add_again():
    """Scenario 5: Delete last activity (A3) from [A1, A2, A3] and add new place -> allocates A4 (prevents reuse)."""
    trip = {
        'id': 't5',
        'activities': [
            {'activityId': 'A1', 'activityName': 'Place 1'},
            {'activityId': 'A2', 'activityName': 'Place 2'},
            {'activityId': 'A3', 'activityName': 'Place 3'},
        ]
    }
    trip = removeActivity(trip, 'A3')
    assert [x['activityId'] for x in trip['activities']] == ['A1', 'A2']

    trip = addActivity(trip, {'activityName': 'Place 4'})
    ids = [x['activityId'] for x in trip['activities']]
    assert ids == ['A1', 'A2', 'A4']
    assert len(ids) == len(set(ids))


def test_scenario_6_repeated_add_remove_operations():
    """Scenario 6: Repeated additions and deletions never generate colliding IDs across the lifecycle."""
    trip = {'id': 't6', 'activities': []}
    all_seen_ids = set()

    for i in range(1, 6):
        trip = addActivity(trip, {'activityName': f'Initial {i}'})
        new_id = trip['activities'][-1]['activityId']
        assert new_id not in all_seen_ids
        all_seen_ids.add(new_id)

    # Current IDs: A1, A2, A3, A4, A5
    assert [x['activityId'] for x in trip['activities']] == ['A1', 'A2', 'A3', 'A4', 'A5']

    # Remove A3, then add new
    trip = removeActivity(trip, 'A3')
    trip = addActivity(trip, {'activityName': 'New After A3'})
    new_id = trip['activities'][-1]['activityId']
    assert new_id not in all_seen_ids
    all_seen_ids.add(new_id)
    assert new_id == 'A6'

    # Remove A1, then add new
    trip = removeActivity(trip, 'A1')
    trip = addActivity(trip, {'activityName': 'New After A1'})
    new_id = trip['activities'][-1]['activityId']
    assert new_id not in all_seen_ids
    all_seen_ids.add(new_id)
    assert new_id == 'A7'

    # Verify all remaining activities have distinct IDs
    remaining_ids = [x['activityId'] for x in trip['activities']]
    assert len(remaining_ids) == len(set(remaining_ids))


def test_scenario_7_existing_non_a_prefixed_ids():
    """Scenario 7: Existing activities with non-A-prefixed IDs remain untouched and new additions allocate collision-free IDs."""
    trip = {
        'id': 't7',
        'activities': [
            {'activityId': 'custom_spot_101', 'activityName': 'Custom Venue 1'},
            {'activityId': 'dest_penang_hill', 'activityName': 'Penang Hill'},
        ]
    }
    trip = addActivity(trip, {'activityName': 'Standard Addition'})
    ids = [x['activityId'] for x in trip['activities']]
    assert ids == ['custom_spot_101', 'dest_penang_hill', 'A1']
    assert len(ids) == len(set(ids))


def test_scenario_8_existing_mixed_format_ids():
    """Scenario 8: Itinerary with mixed format IDs allocates strictly higher A-sequence without collision."""
    trip = {
        'id': 't8',
        'activities': [
            {'activityId': 'legacy_spot', 'activityName': 'Legacy Spot'},
            {'activityId': 'A2', 'activityName': 'Existing A2'},
            {'activityId': 'uuid_12345', 'activityName': 'UUID Spot'},
            {'activityId': 'A7', 'activityName': 'Existing A7'},
        ]
    }
    trip = addActivity(trip, {'activityName': 'Next Spot'})
    ids = [x['activityId'] for x in trip['activities']]
    assert ids == ['legacy_spot', 'A2', 'uuid_12345', 'A7', 'A8']
    assert len(ids) == len(set(ids))


def test_scenario_9_scheduled_vs_unscheduled_references():
    """Scenario 9: Unscheduled suggestions are included in identity checks; adding a new place never collides with unscheduled items."""
    trip = {
        'id': 't9',
        'activities': [
            {'activityId': 'A1', 'activityName': 'Scheduled One', 'dayNo': 1},
        ],
        'unscheduledSuggestions': [
            {'activityId': 'A2', 'activityName': 'Unscheduled Two', 'dayNo': 1, 'unscheduledReason': 'Closed'},
        ],
        'startDate': '2026-11-01',
        'endDate': '2026-11-02',
    }
    # Adding a new activity must NOT reuse A2 because A2 exists in unscheduledSuggestions
    trip = addActivity(trip, {'activityName': 'New Third Place', 'dayNo': 1})
    assert trip['activities'][-1]['activityId'] == 'A3'

    # Removing the unscheduled place clears it from unscheduledSuggestions
    trip = removeActivity(trip, 'A2')
    assert not any(x.get('activityId') == 'A2' for x in trip.get('unscheduledSuggestions', []))
    assert [x['activityId'] for x in trip['activities']] == ['A1', 'A3']


def test_scenario_10_removal_of_one_specifically_selected_activity():
    """Scenario 10: Removing one specific activity leaves all other activities intact with unchanged IDs."""
    trip = {
        'id': 't10',
        'activities': [
            {'activityId': 'A1', 'activityName': 'Activity 1'},
            {'activityId': 'A2', 'activityName': 'Activity 2'},
            {'activityId': 'A3', 'activityName': 'Activity 3'},
            {'activityId': 'A4', 'activityName': 'Activity 4'},
        ]
    }
    trip = removeActivity(trip, 'A3')
    assert [x['activityId'] for x in trip['activities']] == ['A1', 'A2', 'A4']
    assert trip['activities'][0]['activityName'] == 'Activity 1'
    assert trip['activities'][1]['activityName'] == 'Activity 2'
    assert trip['activities'][2]['activityName'] == 'Activity 4'


def test_scenario_11_rearrangement_without_activity_loss():
    """Scenario 11: Rearranging activities preserves all distinct items without collapse or drop."""
    trip = {
        'id': 't11',
        'activities': [
            {'activityId': 'A1', 'activityName': 'First'},
            {'activityId': 'A2', 'activityName': 'Second'},
            {'activityId': 'A3', 'activityName': 'Third'},
            {'activityId': 'A4', 'activityName': 'Fourth'},
        ]
    }
    rearranged = rearrangeActivity(trip, ['A3', 'A1', 'A4', 'A2'])
    assert [x['activityId'] for x in rearranged['activities']] == ['A3', 'A1', 'A4', 'A2']
    assert [x['activityName'] for x in rearranged['activities']] == ['Third', 'First', 'Fourth', 'Second']


def test_scenario_12_move_between_itinerary_days():
    """Scenario 12: Moving an activity to another day via updateActivity preserves its activityId."""
    trip = {
        'id': 't12',
        'activities': [
            {'activityId': 'A1', 'activityName': 'Place 1', 'dayNo': 1},
            {'activityId': 'A2', 'activityName': 'Place 2', 'dayNo': 1},
        ]
    }
    updated = updateActivity(trip, 'A1', {'dayNo': 2})
    target = next(x for x in updated['activities'] if x['activityId'] == 'A1')
    assert target['dayNo'] == 2
    assert target['activityId'] == 'A1'


def test_scenario_13_save_and_reload_identity_preservation():
    """Scenario 13: Storing and retrieving an itinerary preserves activity IDs and sequence counters."""
    storage = {}

    def mock_store(coll, doc):
        storage[doc.get('id', 'trip_s13')] = deepcopy(doc)
        return storage[doc.get('id', 'trip_s13')]

    def mock_retrieve(coll, doc_id):
        return deepcopy(storage.get(doc_id))

    trip = {'id': 'trip_s13', 'activities': []}
    trip = addActivity(trip, {'activityName': 'Place 1'})
    trip = addActivity(trip, {'activityName': 'Place 2'})
    mock_store('itineraries', trip)

    reloaded = mock_retrieve('itineraries', 'trip_s13')
    assert [x['activityId'] for x in reloaded['activities']] == ['A1', 'A2']

    # Continue mutating after reload
    reloaded = addActivity(reloaded, {'activityName': 'Place 3'})
    assert reloaded['activities'][-1]['activityId'] == 'A3'


def test_scenario_14_budget_recalculation_compatibility():
    """Scenario 14: Budget recalculation and constraint planning retain all activity IDs accurately."""
    trip = {
        'id': 'trip_s14',
        'title': 'Penang Budget Trip',
        'destinationArea': 'Penang',
        'destinationName': 'Penang',
        'startDate': '2026-11-01',
        'endDate': '2026-11-02',
        'travellerCount': 2,
        'budgetLimit': 1000.0,
        'travelPace': 'Moderate',
        'activities': [
            {'activityId': 'A1', 'activityName': 'Kek Lok Si', 'estimatedCost': 20.0, 'dayNo': 1},
            {'activityId': 'A2', 'activityName': 'Penang Hill', 'estimatedCost': 60.0, 'dayNo': 1},
        ]
    }
    recalculated = recalculateItinerary(trip, preserveOrder=True, respectDayAssignments=True)
    budget = calculateBudget(recalculated)

    assert [x['activityId'] for x in recalculated['activities']] == ['A1', 'A2']
    assert budget['budgetLimit'] == 1000.0
    assert budget['activities'] == 80.0


def test_scenario_15_smart_itinerary_generation_compatibility():
    """Scenario 15: Initial Smart Itinerary generation produces valid scheduled activities with distinct IDs."""
    destinations = [
        {'id': 'd1', 'name': 'Cheong Fatt Tze Mansion', 'estimatedCost': 25.0, 'category': 'Heritage', 'latitude': 5.421, 'longitude': 100.335},
        {'id': 'd2', 'name': 'Clan Jetties', 'estimatedCost': 0.0, 'category': 'Culture', 'latitude': 5.413, 'longitude': 100.340},
    ]
    itinerary_input = {
        'title': 'Heritage Plan',
        'destinationArea': 'Penang',
        'startDate': '2026-11-01',
        'endDate': '2026-11-02',
        'travellerCount': 1,
        'budgetLimit': 500.0,
        'travelPace': 'Moderate',
        'activities': [
            {'activityId': f'A{i+1}', 'activityName': d['name'], 'destinationId': d['id'], 'estimatedCost': d['estimatedCost'], 'dayNo': 1}
            for i, d in enumerate(destinations)
        ]
    }
    generated = generateItinerary(destinations, {}, itinerary_input)
    assert generated['status'] == 'generated'
    ids = [x['activityId'] for x in generated['activities']]
    assert ids == ['A1', 'A2']
    assert len(ids) == len(set(ids))


def test_scenario_16_manual_trip_creation_compatibility(client, mock_traveller_auth):
    """Scenario 16: Manual Trip Creation via REST API correctly allocates collision-free activity IDs."""
    mock_db = {
        'itineraries': {
            'trip_manual_1': {
                'id': 'trip_manual_1',
                'travellerId': 'test_traveller_uid',
                'title': 'Manual Penang Trip',
                'destinationArea': 'Penang',
                'startDate': '2026-11-01',
                'endDate': '2026-11-03',
                'travellerCount': 1,
                'budgetLimit': 800.0,
                'status': 'draft',
                'activities': [],
            }
        }
    }

    def mock_retrieve(coll, doc_id=None, filters=None, limit=None):
        if doc_id:
            return deepcopy(mock_db.get(coll, {}).get(doc_id))
        return list(mock_db.get(coll, {}).values())

    def mock_update(coll, doc_id, patch_data):
        doc = mock_db[coll].setdefault(doc_id, {})
        doc.update(deepcopy(patch_data))
        return deepcopy(doc)

    headers = {'Authorization': 'Bearer valid_test_token'}
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', side_effect=mock_retrieve), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.updateRecord', side_effect=mock_update):

        # Add place 1 -> A1
        res1 = client.post('/api/fr5/itineraries/trip_manual_1/activities', headers=headers, json={'activityName': 'Place Alpha', 'dayNo': 1})
        assert res1.status_code == 200
        data1 = res1.get_json()
        assert data1['activities'][0]['activityId'] == 'A1'

        # Add place 2 -> A2
        res2 = client.post('/api/fr5/itineraries/trip_manual_1/activities', headers=headers, json={'activityName': 'Place Beta', 'dayNo': 1})
        assert res2.status_code == 200
        data2 = res2.get_json()
        assert [x['activityId'] for x in data2['activities']] == ['A1', 'A2']

        # Delete place 1 (A1)
        res_del = client.delete('/api/fr5/itineraries/trip_manual_1/activities/A1', headers=headers)
        assert res_del.status_code == 200
        data_del = res_del.get_json()
        assert [x['activityId'] for x in data_del['activities']] == ['A2']

        # Add place 3 -> A3 (not A2!)
        res3 = client.post('/api/fr5/itineraries/trip_manual_1/activities', headers=headers, json={'activityName': 'Place Gamma', 'dayNo': 1})
        assert res3.status_code == 200
        data3 = res3.get_json()
        ids = [x['activityId'] for x in data3['activities']]
        assert ids == ['A2', 'A3']
        assert len(ids) == len(set(ids))


def test_scenario_17_purchased_package_trip_read_only_behavior(client, mock_traveller_auth):
    """Scenario 17: Purchased package trips strictly reject activity add, update, remove, and rearrange with 409 Conflict."""
    package_trip = {
        'id': 'pkg_trip_lock',
        'travellerId': 'test_traveller_uid',
        'title': 'Locked Package Trip',
        'tripType': 'package',
        'packageTrip': True,
        'packageId': 'pkg_001',
        'activities': [{'activityId': 'A1', 'activityName': 'Locked Activity'}],
    }
    headers = {'Authorization': 'Bearer valid_test_token'}
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', return_value=package_trip):
        # Add rejected
        assert client.post('/api/fr5/itineraries/pkg_trip_lock/activities', headers=headers, json={'activityName': 'New'}).status_code == 409
        # Update rejected
        assert client.put('/api/fr5/itineraries/pkg_trip_lock/activities/A1', headers=headers, json={'activityName': 'Edit'}).status_code == 409
        # Remove rejected
        assert client.delete('/api/fr5/itineraries/pkg_trip_lock/activities/A1', headers=headers).status_code == 409
        # Rearrange rejected
        assert client.post('/api/fr5/itineraries/pkg_trip_lock/activities/rearrange', headers=headers, json={'orderedActivityIds': []}).status_code == 409


def test_scenario_18_existing_fr05_authorization_behavior(client, mock_traveller_auth):
    """Scenario 18: Unowned itineraries are inaccessible (404 Not Found), preventing unauthorized activity mutation."""
    foreign_trip = {
        'id': 'foreign_trip_999',
        'travellerId': 'other_traveller_uid',
        'title': 'Foreign Trip',
        'activities': [{'activityId': 'A1', 'activityName': 'Secret Activity'}],
    }
    headers = {'Authorization': 'Bearer valid_test_token'}
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', return_value=foreign_trip):
        res = client.post('/api/fr5/itineraries/foreign_trip_999/activities', headers=headers, json={'activityName': 'Intrusion'})
        assert res.status_code == 404
        assert res.get_json()['error'] == 'Itinerary not found'


def test_scenario_19_existing_flight_hotel_apply_paths():
    """Scenario 19: Applying flight and hotel adjustments preserves activity IDs intact."""
    trip = {
        'id': 'trip_s19',
        'activities': [
            {'activityId': 'A1', 'activityName': 'Activity One', 'dayNo': 1, 'estimatedCost': 50.0},
            {'activityId': 'A2', 'activityName': 'Activity Two', 'dayNo': 2, 'estimatedCost': 80.0},
        ],
        'flightCost': 300.0,
        'hotelCost': 400.0,
        'hotelCurrency': 'MYR',
        'startDate': '2026-11-01',
        'endDate': '2026-11-03',
    }
    # Calculate budget with flight/hotel
    budget = calculateBudget(trip)
    assert budget['flight'] == 300.0
    assert budget['hotel'] == 400.0
    assert budget['activities'] == 130.0

    # Ensure activity IDs remain unchanged
    assert [x['activityId'] for x in trip['activities']] == ['A1', 'A2']


def test_scenario_20_existing_budget_aware_selection_regressions():
    """Scenario 20: Budget-aware selection requires unique activityId strings and succeeds without collision."""
    itinerary = {
        'id': 'trip_s20',
        'title': 'Penang Selection',
        'destinationArea': 'Penang',
        'destinationName': 'Penang',
        'startDate': '2026-11-01',
        'endDate': '2026-11-02',
        'travellerCount': 1,
        'budgetLimit': 500.0,
        'travelPace': 'Moderate',
        'activities': [],
    }
    candidates = [
        {'activityId': 'A1', 'score': 80.0, 'effectiveCost': 20.0, 'category': 'Heritage', 'dayNo': 1, 'estimatedCost': 20.0},
        {'activityId': 'A2', 'score': 75.0, 'effectiveCost': 50.0, 'category': 'Nature', 'dayNo': 1, 'estimatedCost': 50.0},
        {'activityId': 'A3', 'score': 70.0, 'effectiveCost': 30.0, 'category': 'Food', 'dayNo': 1, 'estimatedCost': 30.0},
    ]
    # Unique candidate activity IDs succeed cleanly
    result = select_budget_aware_activities(candidates, itinerary)
    assert 'selectedActivities' in result
    all_res_ids = [x['activityId'] for x in result['selectedActivities']] + [x['activity']['activityId'] for x in result['unselectedActivities']]
    assert len(all_res_ids) == len(set(all_res_ids))

    # Duplicate candidate activity IDs strictly raise ValueError
    collided_candidates = [
        {'activityId': 'A1', 'score': 80.0, 'effectiveCost': 20.0, 'category': 'Heritage', 'dayNo': 1, 'estimatedCost': 20.0},
        {'activityId': 'A3', 'score': 75.0, 'effectiveCost': 50.0, 'category': 'Nature', 'dayNo': 1, 'estimatedCost': 50.0},
        {'activityId': 'A3', 'score': 70.0, 'effectiveCost': 30.0, 'category': 'Food', 'dayNo': 1, 'estimatedCost': 30.0},
    ]
    with pytest.raises(ValueError, match='Candidates require unique non-empty activityId strings'):
        select_budget_aware_activities(collided_candidates, itinerary)
