from datetime import date, timedelta

from sequence_contract.domain_functions import (
    calculateBudget,
    generateItinerary,
    recalculateItinerary,
)


def _activity(index, **changes):
    item = {
        'activityId': f'a{index}',
        'activityName': f'Activity {index}',
        'category': 'museum',
        'estimatedCost': 10,
        'gps_coordinates': {
            'latitude': 5.40 + (index * 0.005),
            'longitude': 100.30 + (index * 0.005),
        },
    }
    item.update(changes)
    return item


def _trip(days, count=12, pace='moderate', start=None):
    start = start or date(2026, 10, 10)
    return {
        'startDate': start.isoformat(),
        'endDate': (start + timedelta(days=days - 1)).isoformat(),
        'travelPace': pace,
        'activities': [_activity(i) for i in range(count)],
    }


def test_one_three_and_seven_day_trips_use_dynamic_capacity():
    one = generateItinerary([], {}, _trip(1, 20))
    three = generateItinerary([], {}, _trip(3, 20))
    seven = generateItinerary([], {}, _trip(7, 20))

    assert len(one['dailySchedule']) == 1
    assert len(three['dailySchedule']) == 3
    assert len(seven['dailySchedule']) == 7
    assert one['scheduledActivityCount'] < three['scheduledActivityCount']
    assert three['scheduledActivityCount'] <= seven['scheduledActivityCount']
    assert one['unscheduledActivityCount'] > 0


def test_relaxed_capacity_is_lower_than_active_capacity():
    relaxed = generateItinerary([], {}, _trip(1, 12, 'relaxed'))
    active = generateItinerary([], {}, _trip(1, 12, 'active'))

    assert relaxed['dailyPlanningWindow'] == {'startTime': '10:00', 'endTime': '20:00'}
    assert active['dailyPlanningWindow'] == {'startTime': '08:00', 'endTime': '21:30'}
    assert relaxed['scheduledActivityCount'] < active['scheduledActivityCount']


def test_missing_hours_are_allowed_but_closed_attraction_is_unscheduled():
    trip = _trip(1, 0)
    trip['activities'] = [
        _activity(1, openingHours=''),
        _activity(2, openingHours='Closed'),
    ]
    planned = generateItinerary([], {}, trip)

    assert [x['activityId'] for x in planned['activities']] == ['a1']
    assert planned['activities'][0]['openingHoursStatus'] == 'unknown'
    assert planned['unscheduledSuggestions'][0]['activityId'] == 'a2'
    assert 'closed' in planned['unscheduledSuggestions'][0]['unscheduledReason'].lower()


def test_geographic_grouping_avoids_cross_region_bounce_and_records_provenance():
    trip = _trip(1, 0)
    trip['activities'] = [
        _activity(1, gps_coordinates={'latitude': 5.414, 'longitude': 100.329}),
        _activity(2, gps_coordinates={'latitude': 5.470, 'longitude': 100.245}),
        _activity(3, gps_coordinates={'latitude': 5.416, 'longitude': 100.331}),
    ]
    planned = generateItinerary([], {}, trip)

    assert [x['activityId'] for x in planned['activities'][:2]] == ['a1', 'a3']
    assert planned['activities'][1]['travelTimeSource'] == 'estimated_haversine'
    assert planned['activities'][1]['travelDistanceKm'] is not None
    assert any('nearby' in note.lower() for note in planned['activities'][1]['scheduleNotes'])


def test_weather_is_mapped_by_actual_date_and_out_of_range_is_not_fabricated():
    start = date(2026, 10, 10)
    forecast = {
        'daily': {
            'time': ['2026-10-10'],
            'precipitation_probability_max': [80],
            'weather_code': [61],
        }
    }
    planned = generateItinerary([], forecast, _trip(2, 4, start=start))

    assert planned['dailySchedule'][0]['weather']['date'] == '2026-10-10'
    assert planned['dailySchedule'][0]['weather']['heavyRainLikely'] is True
    assert planned['dailySchedule'][1]['weather']['source'] == 'unavailable'
    assert planned['dailySchedule'][1]['weather']['message'] == 'Weather forecast unavailable for this date.'


def test_opening_hours_shift_and_overflow_are_explicit():
    trip = _trip(1, 0, 'relaxed')
    trip['activities'] = [
        _activity(1, openingHours='09:00-12:00', recommendedDurationMinutes=120),
        _activity(2, openingHours='18:00-20:00', recommendedDurationMinutes=120),
        _activity(3, openingHours='09:00-10:00', recommendedDurationMinutes=120),
    ]
    planned = generateItinerary([], {}, trip)

    assert planned['activities'][0]['scheduledEndTime'] <= '12:00'
    assert any(x['scheduledStartTime'] == '18:00' for x in planned['activities'])
    assert any(x['activityId'] == 'a3' for x in planned['unscheduledSuggestions'])


def test_recalculation_updates_times_order_days_and_budget_inputs():
    trip = generateItinerary([], {}, _trip(2, 5))
    removed_id = trip['activities'][0]['activityId']
    trip['activities'] = [x for x in trip['activities'] if x['activityId'] != removed_id]
    reordered = list(reversed(trip['activities']))
    reordered[0]['dayNo'] = 2
    trip['activities'] = reordered

    recalculated = recalculateItinerary(trip, preserveOrder=True, respectDayAssignments=True)
    assert removed_id not in [x['activityId'] for x in recalculated['activities']]
    day_two = [x for x in recalculated['activities'] if x['dayNo'] == 2]
    assert day_two[0]['activityId'] == reordered[0]['activityId']
    assert all(x['scheduledStartTime'] and x['scheduledEndTime'] for x in recalculated['activities'])
    assert sum(day['estimatedCost'] for day in recalculated['dailySchedule']) == sum(
        x['estimatedCost'] for x in recalculated['activities']
    )


def test_add_recalculation_assigns_real_times_and_updates_day_cost():
    trip = generateItinerary([], {}, _trip(2, 2))
    added = _activity(99, dayNo=2, estimatedCost=35)
    trip['activities'] = [*trip['activities'], added]
    trip['unscheduledSuggestions'] = []

    recalculated = recalculateItinerary(
        trip, preserveOrder=True, respectDayAssignments=True
    )
    saved = next(x for x in recalculated['activities'] if x['activityId'] == 'a99')
    day = next(x for x in recalculated['dailySchedule'] if x['dayNo'] == 2)
    assert saved['dayNo'] == 2
    assert saved['scheduledStartTime'] < saved['scheduledEndTime']
    assert day['estimatedCost'] >= 35


def test_budget_uses_hotel_nights_and_marks_estimates():
    budget = calculateBudget({
        **_trip(3, 2),
        'travellerCount': 2,
        'hotelNightlyRate': 150,
        'roomQuantity': 2,
        'budgetLimit': 2000,
    })

    assert budget['hotelNights'] == 2
    assert budget['hotel'] == 600
    assert budget['activities'] == 20
    assert budget['costProvenance']['hotel'] == 'estimated_from_nightly_rate'
    assert budget['costProvenance']['transport'] == 'estimated_daily_allowance'

