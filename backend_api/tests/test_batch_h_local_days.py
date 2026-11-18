"""Deterministic schedule tests. Coordinates are fixture pins, not venue records."""
from copy import deepcopy
from datetime import date, timedelta

import pytest

from sequence_contract.domain_functions import (
    LOCAL_DAYS_POLICY, _distance_km, generateItinerary, plan_intercity_transfer,
    recalculateItinerary,
)


def visit(key, name, latitude, longitude=102.57, category='Culture', **details):
    return {
        'activityId': key, 'destinationId': key, 'activityName': name,
        'gps_coordinates': {'latitude': latitude, 'longitude': longitude} if latitude is not None else {},
        'category': category, 'openingHours': 'Daily 08:00 - 21:00',
        'recommendedDurationMinutes': 75, **details,
    }


def make_trip(items, days=1, **changes):
    return {
        'destinationArea': 'Johor', 'startDate': '2030-12-12',
        'endDate': (date(2030, 12, 12) + timedelta(days=days-1)).isoformat(),
        'travelMode': 'own_vehicle', 'travelPace': 'Packed', 'activities': items,
        'geographyPlanningPolicy': LOCAL_DAYS_POLICY, **changes,
    }


def johor():
    return [
        visit('otak', 'Otak-Otak Cheng Boi', 2.051, category='Restaurant', recommendedDurationMinutes=81),
        visit('gallery', 'Muar Art Gallery', 2.055, recommendedDurationMinutes=105),
        visit('temple', 'Arulmigu Rajamariamman Temple', 1.49, 103.7837),
    ]


def ids(result):
    return [item['activityId'] for item in result['activities']]


def test_reconstructed_vivo_leg_was_allowed_by_the_old_window():
    trip = make_trip(johor())
    original = deepcopy(trip)
    legacy = generateItinerary([], {}, {**trip, 'geographyPlanningPolicy': None})
    assert ids(legacy) == ['otak', 'gallery', 'temple']
    leg = legacy['activities'][-1]
    assert abs(leg['travelDistanceKm'] - 148.8) < 0.1
    assert leg['travelDurationMinutes'] == 407
    updated = generateItinerary([], {}, trip)
    assert ids(updated) == ['otak', 'gallery']
    assert 'too far' in updated['unscheduledSuggestions'][0]['unscheduledReason']
    assert trip == original


@pytest.mark.parametrize('days', [3, 5])
def test_focus_and_confirmed_dedicated_intercity_day(days):
    items = johor() + [visit('museum', 'Johor Bahru Museum', 1.491, 103.785),
                       visit('garden', 'Muar Riverside Garden', 2.059, category='Nature')]
    result = generateItinerary([], {}, make_trip(items, days))
    assert len(result['dailySchedule']) == days
    assert set(ids(result)) == {'otak', 'gallery', 'garden'}
    assert {item['activityId'] for item in result['unscheduledSuggestions']} == {'temple', 'museum'}
    request = {'dayNo': 2, 'toDestinationId': 'temple', 'mode': 'drive'}
    with pytest.raises(ValueError, match='Confirm'):
        plan_intercity_transfer(result, request)
    approved = plan_intercity_transfer(result, {**request, 'confirmed': True})
    day2 = approved['dailySchedule'][1]
    assert day2['activities'] == []
    assert day2['planningBlocks'][0]['type'] == 'intercity_transfer'
    assert day2['estimatedMinutes'] > 300
    assert set(ids(approved)) == {'otak', 'gallery', 'garden', 'temple', 'museum'}
    assert all(row['dayNo'] >= 3 for row in approved['activities']
               if row['activityId'] in {'temple', 'museum'})
    assert result.get('confirmedIntercityTransfer') is None


def test_locality_labels_coordinates_and_hotel_anchor():
    first = visit('first', 'Art Museum', 2.047, city='Muar', state='Johor')
    nearby = visit('nearby', 'Market', 2.057, city='Bakri', state='Johor')
    wrong = visit('wrong', 'Conflicting Park', 2.052, normalizedGeography={'conflict': True})
    missing = visit('missing', 'Place without coordinates', None)
    distant = johor()[-1]
    no_base = generateItinerary([], {}, make_trip([first, nearby, wrong, missing, distant]))
    assert ids(no_base) == ['first', 'nearby']
    assert {row['activityId'] for row in no_base['unscheduledSuggestions']} == {'wrong', 'missing', 'temple'}
    assert no_base['activities'][0]['travelTimeSource'] == 'not_applicable'
    base = {'gps_coordinates': nearby['gps_coordinates']}
    based = generateItinerary([], {}, make_trip([first, nearby, distant], accommodationBase=base))
    assert based['activities'][0]['travelDurationMinutes'] > 0
    assert 'temple' not in ids(based)


def test_walk_drive_and_pair_bound_provider_evidence():
    first = visit('first', 'Art Museum', 2.055)
    second = visit('second', 'Riverside Market', 2.1, providerTravelDurationMinutes=80,
                   providerTravelFromDestinationId='unrelated', providerTravelMode='drive')
    assert _distance_km(first, second) > 3
    assert ids(generateItinerary([], {}, make_trip([first, second], transportMode='walk'))) == ['first']
    assert ids(generateItinerary([], {}, make_trip([first, second]))) == ['first', 'second']
    bound = {**second, 'providerTravelFromDestinationId': 'first'}
    assert ids(generateItinerary([], {}, make_trip([first, bound]))) == ['first']
    result = generateItinerary([], {}, make_trip([first, {**bound, 'providerTravelDurationMinutes': 35}]))
    assert result['activities'][1]['travelTimeSource'] == 'provider'
    assert result['activities'][1]['travelDurationMinutes'] == 35


@pytest.mark.parametrize('name,category,expected', [
    ('Restful Garden', 'Nature', 'garden'), ('Sandy Beach', 'Nature', 'beach'),
    ('Sky Viewpoint', 'Nature', 'viewpoint'), ('Bird Park', 'Nature', 'wildlife'),
    ('Town Museum', 'Culture', 'museum'), ('Old Temple', 'Heritage', 'religious'),
    ('Heritage Street', 'Culture', 'heritage'), ('Night Market', 'Shopping', 'market'),
    ('Local Mall', 'Shopping', 'mall'), ('Local Restaurant', 'Food', 'meal'),
])
def test_experience_types_are_based_on_candidate_evidence(name, category, expected):
    from sequence_contract.domain_functions import _visit_experience
    assert _visit_experience(visit('test', name, 2.06, category=category)) == expected


def test_multi_interest_coverage_and_fatigue_controls():
    rows = [
        visit('hike1', 'First Hike', 2.055, category='Nature'),
        visit('hike2', 'Second Hike', 2.058, category='Nature'),
        visit('beach', 'Sandy Beach', 2.06, category='Nature'),
        visit('mall', 'Local Mall', 2.062, category='Shopping'),
        visit('garden', 'Town Garden', 2.064, category='Nature'),
    ]
    plan = generateItinerary([], {}, make_trip(rows, interests=['Nature', 'Shopping'],
                                              planningPreferences={'travelPace': 'Packed'}))
    assert {'hike1', 'mall', 'beach', 'garden'} <= set(ids(plan))
    assert 'hike2' not in ids(plan)
    assert 'rest and variety' in plan['unscheduledSuggestions'][0]['unscheduledReason']
    focused = generateItinerary([], {}, make_trip(rows[:2], hikingFocused=True))
    assert ids(focused) == ['hike1', 'hike2']
    relaxed = generateItinerary([], {}, make_trip(rows, interests=['Nature', 'Shopping'],
                                                 planningPreferences={'travelPace': 'Relaxed'},
                                                 travelPace='Relaxed'))
    assert len(relaxed['activities']) == 2 and 'mall' in ids(relaxed)


def test_meals_rain_and_sleep_rhythm():
    rows = [visit(f'meal{i}', f'Restaurant {i}', 2.055 + i / 1000, category='Food') for i in range(3)]
    rows += [visit('garden', 'Central Garden', 2.058, category='Nature'),
             visit('museum', 'Local Museum', 2.059, indoor=True)]
    forecast = {'daily': {'time': ['2030-12-12'], 'precipitation_probability_max': [80]}}
    early = generateItinerary([], forecast, make_trip(rows, sleepingType='Early riser'))
    late = generateItinerary([], {}, make_trip(rows, sleepingType='Night owl'))
    assert ids(early).index('museum') < ids(early).index('garden')
    assert len([key for key in ids(early) if key.startswith('meal')]) == 2
    assert early['dailyPlanningWindow']['startTime'] == '07:30'
    assert late['dailyPlanningWindow']['startTime'] == '11:00'
    assert any(block['label'] == 'Lunch and rest' for block in early['dailySchedule'][0]['planningBlocks'])


def test_explicit_edit_applies_local_policy_without_mutating_previous_schedule():
    trip = make_trip(johor())
    previous = generateItinerary([], {}, {**trip, 'geographyPlanningPolicy': None})
    edited = recalculateItinerary({**previous, 'geographyPlanningPolicy': LOCAL_DAYS_POLICY})
    assert len(previous['activities']) == 3
    assert ids(edited) == ['otak', 'gallery']
    assert ids(previous) == ['otak', 'gallery', 'temple']


def test_owner_confirmation_and_rejected_manual_move_share_policy(client, mock_traveller_auth, monkeypatch):
    from modules.fr05_smart_itinerary_budget_planner import routes
    from services.itinerary_history import HistoryConflict

    original = generateItinerary([], {}, make_trip(johor(), 3))
    original.update(id='owned', travellerId='test_traveller_uid')
    db = {'owned': original, 'foreign': {**original, 'travellerId': 'different-owner'}}
    writes = []

    def retrieve(collection, identity):
        assert collection == 'itineraries'
        return deepcopy(db.get(identity))

    def update(collection, identity, patch, expected=None):
        assert collection == 'itineraries'
        if expected != db[identity]:
            raise HistoryConflict('This itinerary changed.')
        db[identity] = {**db[identity], **deepcopy(patch)}
        writes.append(identity)
        return db[identity]

    monkeypatch.setattr(routes, 'retrieveRecord', retrieve)
    monkeypatch.setattr(routes, 'updateRecord', update)
    auth = {'Authorization': 'Bearer valid_test_token'}
    base = '/api/fr5/itineraries/'
    command = {'dayNo': 2, 'toDestinationId': 'temple', 'mode': 'drive'}
    assert client.post(base+'foreign/intercity-transfer', headers=auth,
                       json={**command, 'confirmed': True}).status_code == 404
    assert client.post(base+'owned/intercity-transfer', headers=auth, json=command).status_code == 409
    invalid = client.post(base+'owned/intercity-transfer', headers=auth,
                          json={**command, 'confirmed': True, 'mode': []})
    assert invalid.status_code == 409 and writes == []
    move = client.put(base+'owned/activities/temple', headers=auth, json={'dayNo': 1})
    assert move.status_code == 409 and move.json['code'] == 'itinerary_travel_conflict'
    assert db['owned'] == original and writes == []
    applied = client.post(base+'owned/intercity-transfer', headers=auth,
                          json={**command, 'confirmed': True})
    assert applied.status_code == 200
    assert db['owned']['intercityTransferStatus'] == 'planned'
    assert applied.json['itinerary']['dailySchedule'][1]['activities'] == []
    assert writes == ['owned']
    assert client.post(base+'owned/intercity-transfer', headers=auth,
                       json={**command, 'confirmed': True}).status_code == 409
    assert writes == ['owned']
