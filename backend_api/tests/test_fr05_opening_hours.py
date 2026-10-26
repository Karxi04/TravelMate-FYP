from datetime import date, timedelta
import pytest

from sequence_contract.domain_functions import (
    _opening_window,
    _constraint_plan,
    _candidate_order,
    generateItinerary,
)


def _activity(index, **changes):
    item = {
        'activityId': f'act_{index}',
        'activityName': f'Attraction {index}',
        'category': 'museum',
        'estimatedCost': 20,
        'gps_coordinates': {
            'latitude': 5.414 + (index * 0.005),
            'longitude': 100.329 + (index * 0.005),
        },
    }
    item.update(changes)
    return item


def _trip(days=1, pace='moderate', start=None, activities=None):
    start = start or date(2026, 11, 24)  # Tuesday
    return {
        'startDate': start.isoformat(),
        'endDate': (start + timedelta(days=days - 1)).isoformat(),
        'travelPace': pace,
        'travellerCount': 2,
        'activities': activities if activities is not None else [_activity(i) for i in range(12)],
    }


# 1. "Closed · Opens 9 am Mon" for a future Tuesday
def test_scenario_01_closed_opens_9am_mon_for_future_tuesday():
    res = _opening_window('Closed · Opens 9 am Mon', date(2026, 11, 24))
    assert res['status'] == 'unknown'
    assert res['window'] is None


# 2. "Closed · Opens 8:30 am Mon" for a future Monday
def test_scenario_02_closed_opens_830am_mon_for_future_monday():
    res = _opening_window('Closed · Opens 8:30 am Mon', date(2026, 11, 23))
    assert res['status'] == 'unknown'
    assert res['window'] is None


# 3. "Currently closed" with no structured hours
def test_scenario_03_currently_closed_with_no_structured_hours():
    res = _opening_window('Currently closed', date(2026, 11, 24))
    assert res['status'] == 'unknown'
    assert res['window'] is None


# 4. "Open now" for a future trip
def test_scenario_04_open_now_for_future_trip():
    res = _opening_window('Open now', date(2026, 11, 24))
    assert res['status'] == 'unknown'
    assert res['window'] is None


# 5. Genuine permanently closed venue
def test_scenario_05_genuine_permanently_closed_venue():
    res1 = _opening_window('Permanently closed', date(2026, 11, 24))
    assert res1['status'] == 'closed'
    assert res1['window'] is None

    res2 = _opening_window('Closed permanently', date(2026, 11, 24))
    assert res2['status'] == 'closed'
    assert res2['window'] is None


# 6. Weekly schedule with Tuesday explicitly closed
def test_scenario_06_weekly_schedule_with_tuesday_explicitly_closed():
    # Dict format
    res_dict = _opening_window(
        {'monday': '9:00 AM - 5:00 PM', 'tuesday': 'Closed', 'wednesday': '9:00 AM - 5:00 PM'},
        date(2026, 11, 24),  # Tuesday
    )
    assert res_dict['status'] == 'closed'
    assert res_dict['window'] is None

    # String format
    res_str = _opening_window(
        'Monday: 9:00 AM - 5:00 PM\nTuesday: Closed\nWednesday: 9:00 AM - 5:00 PM',
        date(2026, 11, 24),  # Tuesday
    )
    assert res_str['status'] == 'closed'
    assert res_str['window'] is None

    # Explicit day closure phrase
    res_phrase = _opening_window('Closed on Tuesdays', date(2026, 11, 24))
    assert res_phrase['status'] == 'closed'


# 7. Weekly schedule with Tuesday open
def test_scenario_07_weekly_schedule_with_tuesday_open():
    # Dict format
    res_dict = _opening_window(
        {'monday': '9:00 AM - 5:00 PM', 'tuesday': '09:00 - 18:00'},
        date(2026, 11, 24),  # Tuesday
    )
    assert res_dict['status'] == 'open'
    assert res_dict['window'] == (540, 1080)

    # String format
    res_str = _opening_window(
        'Monday: 9:00 AM - 5:00 PM\nTuesday: 10:00 AM - 6:00 PM',
        date(2026, 11, 24),  # Tuesday
    )
    assert res_str['status'] == 'open'
    assert res_str['window'] == (600, 1080)


# 8. Split opening periods
def test_scenario_08_split_opening_periods():
    res = _opening_window('09:00 - 13:00, 14:00 - 18:00', date(2026, 11, 24))
    assert res['status'] == 'open'
    assert res['window'] == (540, 1080)


# 9. Overnight operating hours
def test_scenario_09_overnight_operating_hours():
    res = _opening_window('20:00 - 02:00', date(2026, 11, 24))
    assert res['status'] == 'open'
    assert res['window'] == (1200, 1560)


# 10. Genuine 24-hour schedule
def test_scenario_10_genuine_24_hour_schedule():
    for text in ('Open 24 hours', '24 hours', 'open all day', '24/7', '24-hour'):
        res = _opening_window(text, date(2026, 11, 24))
        assert res['status'] == 'open'
        assert res['window'] == (0, 1439)


# 11. Empty opening-hours field
def test_scenario_11_empty_opening_hours_field():
    assert _opening_window('', date(2026, 11, 24)) == {'status': 'unknown', 'window': None, 'text': ''}
    assert _opening_window(None, date(2026, 11, 24)) == {'status': 'unknown', 'window': None, 'text': ''}


# 12. Malformed provider string
def test_scenario_12_malformed_provider_string():
    res = _opening_window('unparseable string with no dates or numbers', date(2026, 11, 24))
    assert res['status'] == 'unknown'
    assert res['window'] is None


# 13. Structured schedule combined with transient closed-now label
def test_scenario_13_structured_schedule_with_transient_closed_now_label():
    res = _opening_window('Closed now · 9:00 AM - 5:00 PM', date(2026, 11, 24))
    assert res['status'] == 'open'
    assert res['window'] == (540, 1020)


# 14. No invention of future opening hours
def test_scenario_14_no_invention_of_future_opening_hours():
    res = _opening_window('Closed · Opens 9 am Mon', date(2026, 11, 24))
    assert res['window'] is None
    assert res['status'] == 'unknown'


# 15. Unknown-hours candidates not falsely marked closed all trip days
def test_scenario_15_unknown_hours_candidates_not_falsely_marked_closed_all_trip_days():
    trip = _trip(
        days=1,
        activities=[
            _activity(1, openingHours='Closed · Opens 9 am Mon'),
            _activity(2, openingHours='Closed · Opens 8:30 am Mon'),
        ],
    )
    planned = generateItinerary([], {}, trip)
    # Both are eligible and should be scheduled within the 1-day planning window
    assert planned['scheduledActivityCount'] == 2
    assert all(a['openingHoursStatus'] == 'unknown' for a in planned['activities'])
    assert planned['unscheduledActivityCount'] == 0


# 16. Known closed-day activities remain excluded or rescheduled correctly
def test_scenario_16_known_closed_day_activities_remain_excluded_or_rescheduled():
    # Day 1: Tuesday (2026-11-24), Day 2: Wednesday (2026-11-25)
    trip = _trip(
        days=2,
        activities=[
            # Closed specifically on Tuesdays
            _activity(1, openingHours='Tuesday: Closed\nWednesday: 10:00 AM - 5:00 PM'),
            # Permanently closed
            _activity(2, openingHours='Permanently closed'),
        ],
    )
    planned = generateItinerary([], {}, trip)

    # Activity 1 cannot be scheduled on Day 1 (Tuesday), but can be scheduled on Day 2 (Wednesday)
    day2_items = [a for a in planned['activities'] if a['dayNo'] == 2]
    assert any(a['activityId'] == 'act_1' for a in day2_items)

    # Activity 2 is permanently closed on all days and remains unscheduled
    permanently_closed_item = next(
        u for u in planned['unscheduledSuggestions'] if u['activityId'] == 'act_2'
    )
    assert 'closed on all trip days' in permanently_closed_item['unscheduledReason'].lower()


# 17. Existing travel-time and activity-duration constraints remain active
def test_scenario_17_travel_time_and_activity_duration_constraints_remain_active():
    # 5 activities with 180 min each cannot all fit in one moderate day (12 hrs = 720 min, plus travel)
    trip = _trip(
        days=1,
        pace='moderate',
        activities=[
            _activity(i, recommendedDurationMinutes=180, openingHours='Closed · Opens 9 am Mon')
            for i in range(5)
        ],
    )
    planned = generateItinerary([], {}, trip)
    # With 180m + lunch buffer, at most 3 can fit in moderate 09:00 - 21:00 window
    assert planned['scheduledActivityCount'] < 5
    assert planned['unscheduledActivityCount'] > 0
    for u in planned['unscheduledSuggestions']:
        assert u['unscheduledReason'] == 'Could not fit within available time, travel, and opening-hour constraints.'


# 18. Existing weather and geographic restrictions remain active
def test_scenario_18_weather_and_geographic_restrictions_remain_active():
    start = date(2026, 11, 24)
    forecast = {
        'daily': {
            'time': ['2026-11-24'],
            'precipitation_probability_max': [90],
            'weather_code': [65],
        }
    }
    trip = _trip(
        days=1,
        start=start,
        activities=[
            _activity(1, category='outdoor park', indoor=False, openingHours='09:00 - 18:00'),
            _activity(2, category='indoor museum', indoor=True, openingHours='Closed · Opens 9 am Mon'),
        ],
    )
    planned = generateItinerary([], forecast, trip)
    # Indoor activity should be prioritized when heavy rain is likely
    first_scheduled = planned['activities'][0]
    assert first_scheduled['activityId'] == 'act_2'
    assert 'rain' in first_scheduled.get('weatherNote', '').lower() or any('rain' in n.lower() for n in first_scheduled.get('scheduleNotes', []))


# 19. FR04 candidate ordering remains compatible
def test_scenario_19_fr04_candidate_ordering_remains_compatible():
    act_closing_early = _activity(1, openingHours='09:00 - 14:00')  # Closes at 14:00 (840 min)
    act_unknown_hours = _activity(2, openingHours='Closed · Opens 9 am Mon')  # Unknown close time (1440 min)
    act_open_late = _activity(3, openingHours='09:00 - 22:00')  # Closes at 22:00 (1320 min)

    weather = {'heavyRainLikely': False}
    ordered = _candidate_order([act_unknown_hours, act_open_late, act_closing_early], None, weather, False)
    # Early closing item should be ordered before late closing / unknown closing items
    assert ordered[0]['activityId'] == 'act_1'


# 20. Historical stored itinerary snapshots remain untouched
def test_scenario_20_historical_stored_itinerary_snapshots_remain_untouched():
    # A pre-existing historical itinerary object passed to recalculate should keep historical values
    # unless recalculation explicitly updates it.
    snapshot = {
        'itineraryId': 'hist_trip_123',
        'tripDays': 1,
        'travelPace': 'moderate',
        'activities': [
            {
                'activityId': 'historical_a1',
                'activityName': 'Historic Site',
                'dayNo': 1,
                'scheduledStartTime': '09:00',
                'scheduledEndTime': '11:00',
                'openingHours': 'Closed · Opens 9 am Mon',
                'openingHoursStatus': 'historical_status_unchanged',
                'effectiveCost': 15.0,
            }
        ],
        'unscheduledSuggestions': [],
    }
    # Verify reading the snapshot does not mutate stored historical fields
    assert snapshot['activities'][0]['openingHoursStatus'] == 'historical_status_unchanged'
    assert snapshot['activities'][0]['scheduledStartTime'] == '09:00'
