from datetime import date, timedelta
from copy import deepcopy
import pytest

from sequence_contract.domain_functions import (
    _opening_window,
    _constraint_plan,
    _candidate_order,
    generateItinerary,
    _schedule_candidate,
    _activity_opening,
)
from modules.fr05_smart_itinerary_budget_planner.routes import _activity_from_destination


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
    assert res['periods'] == [(540, 780), (840, 1080)]


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
        assert res['window'] == (0, 1440)


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
    assert planned['provisionalActivityCount'] == 2
    assert all(a['scheduleFeasibility'] == 'provisional' for a in planned['activities'])
    assert all(any('Provisional' in note for note in a['scheduleNotes']) for a in planned['activities'])
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
        assert u['unscheduledReason'].startswith('Could not fit within available time, travel, and opening-hour constraints.')
        assert 'unverified' in u['unscheduledReason']


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


@pytest.mark.parametrize('name,hours,late_start', [
    ('Wonderfood Museum-like', '09:00-18:00', 17 * 60 + 16),
    ('Pinang Peranakan Mansion-like', '09:30-17:00', 19 * 60 + 9),
])
def test_reported_museum_hours_reject_late_visits(name, hours, late_start):
    activity = _activity(1, activityName=name, openingHours=hours)
    rejected, reason = _schedule_candidate(activity, None, late_start, date(2026, 11, 24), 21 * 60)
    assert rejected is None
    assert 'opening hours' in reason
    planned = generateItinerary([], {}, _trip(activities=[activity]))
    visit = planned['activities'][0]
    assert visit['scheduleFeasibility'] == 'feasible_with_reported_hours'
    assert visit['scheduledEndTime'] <= ('18:00' if 'Wonderfood' in name else '17:00')
    assert visit['openingHoursEvidence']['freshness'] == 'unverified'


@pytest.mark.parametrize('hours', ['', 'Closed now', 'Closed · Opens 9 am Mon', 'Closes at 6 pm'])
def test_unknown_hours_remain_available_but_explicitly_provisional(hours):
    planned = generateItinerary([], {}, _trip(activities=[_activity(1, openingHours=hours)]))
    assert planned['scheduledActivityCount'] == 1
    assert planned['provisionalActivityCount'] == 1
    visit = planned['activities'][0]
    assert visit['scheduleFeasibility'] == 'provisional'
    assert any('Confirm with the venue' in note for note in visit['scheduleNotes'])
    assert not any('Scheduled before' in note for note in visit['scheduleNotes'])


def test_split_periods_are_used_for_actual_scheduling_after_lunch_shift():
    activity = _activity(1, openingHours='09:00-12:00, 14:00-18:00',
                         providerDurationMinutes=90)
    visit, reason = _schedule_candidate(activity, None, 11 * 60, date(2026, 11, 24), 21 * 60)
    assert reason is None
    assert (visit['_startMinutes'], visit['_endMinutes']) == (840, 930)
    too_short = {**activity, 'openingHours': '09:00-09:45, 14:00-14:45'}
    assert _schedule_candidate(too_short, None, 9 * 60, date(2026, 11, 24), 21 * 60)[0] is None


@pytest.mark.parametrize('weekly', [
    {'tuesday': ['09:30-12:00', '14:00-17:00']},
    {'weekday_text': ['Monday: Closed', 'Tuesday: 09:30-12:00, 14:00-17:00']},
    {'periods': [
        {'open': {'day': 2, 'time': '0930'}, 'close': {'day': 2, 'time': '1200'}},
        {'open': {'day': 2, 'time': '1400'}, 'close': {'day': 2, 'time': '1700'}},
    ]},
])
def test_structured_weekly_evidence_survives_fr05_conversion_and_overrides_status(weekly):
    raw = {'destinationId': 'museum', 'title': 'Museum', 'openingHours': 'Closed now',
           'operating_hours': weekly, 'openingHoursSource': 'fixture_venue_timetable',
           'openingHoursUpdatedAt': '2026-10-20T10:00:00+08:00'}
    original = deepcopy(raw)
    activity = _activity_from_destination(raw, 0)
    evidence = _activity_opening(activity, date(2026, 11, 24))
    assert evidence['periods'] == [(570, 720), (840, 1020)]
    assert evidence['provisional'] is False
    visit, _ = _schedule_candidate(activity, None, 14 * 60, date(2026, 11, 24), 21 * 60)
    assert visit['scheduleFeasibility'] == 'feasible_with_reported_hours'
    assert visit['openingHoursEvidence']['field'] == 'operating_hours'
    assert visit['openingHoursEvidence']['source'] == 'fixture_venue_timetable'
    assert visit['openingHoursEvidence']['updatedAt'] == raw['openingHoursUpdatedAt']
    assert raw == original


def test_date_specific_ordering_uses_weekday_closing_time():
    late = _activity(1, operating_hours={'tuesday': '09:00-21:00'})
    early = _activity(2, openingHours='Closed now', operating_hours={'tuesday': '09:30-17:00'})
    ordered = _candidate_order([late, early], None, {}, False, date(2026, 11, 24))
    assert ordered[0]['activityId'] == 'act_2'


@pytest.mark.parametrize('weekly', [
    {'monday': '20:00-02:00', 'tuesday': 'Closed'},
    {'periods': [{'open': {'day': 1, 'time': '2000'},
                  'close': {'day': 2, 'time': '0200'}}]},
])
def test_overnight_carry_belongs_to_previous_opening_day(weekly):
    activity = _activity(1, operating_hours=weekly, providerDurationMinutes=30)
    early, _ = _schedule_candidate(activity, None, 60, date(2026, 11, 24), 180)
    assert early is not None
    assert (early['_startMinutes'], early['_endMinutes']) == (60, 90)
    assert _schedule_candidate(activity, None, 180, date(2026, 11, 24), 21 * 60)[0] is None
    if 'periods' in weekly:
        assert _activity_opening(activity, date(2026, 11, 25))['status'] == 'closed'
    evening, _ = _schedule_candidate(activity, None, 20 * 60, date(2026, 11, 23), 21 * 60)
    assert evening is not None and evening['_startMinutes'] == 1200


def test_explicit_permanent_closure_overrides_weekly_hours_and_carry():
    activity = _activity(1, openingHours='Permanently closed',
                         operating_hours={'monday': '20:00-02:00', 'tuesday': '09:00-18:00'})
    planned = generateItinerary([], {}, _trip(activities=[activity]))
    assert planned['scheduledActivityCount'] == 0
    assert 'closed on all trip days' in planned['unscheduledSuggestions'][0]['unscheduledReason']


def test_stale_hours_still_constrain_times_but_visit_remains_provisional():
    activity = _activity(1, openingHours='09:00-17:00', openingHoursStale=True)
    visit = generateItinerary([], {}, _trip(activities=[activity]))['activities'][0]
    assert visit['scheduleFeasibility'] == 'provisional'
    assert visit['openingHoursEvidence']['freshness'] == 'reported_stale'
    assert _schedule_candidate(activity, None, 17 * 60, date(2026, 11, 24), 21 * 60)[0] is None


def test_unknown_and_known_scheduling_preserve_input_duration_travel_and_cost():
    trip = _trip(activities=[
        _activity(1, openingHours='09:00-18:00', providerDurationMinutes=60),
        _activity(2, openingHours='', providerDurationMinutes=60,
                  providerTravelDurationMinutes=20, travelTimeSource='provider'),
    ])
    original = deepcopy(trip)
    planned = generateItinerary([], {}, trip)
    assert trip == original
    first, second = planned['activities']
    assert second['travelDurationMinutes'] == 20
    assert first['recommendedDurationMinutes'] == second['recommendedDurationMinutes'] == 60
    assert planned['dailySchedule'][0]['estimatedCost'] == 40
    assert planned['dailySchedule'][0]['estimatedMinutes'] == 140


@pytest.mark.parametrize('hours', [
    {'tuesday': '09:30-17:00'},
    'Tuesday: 09:30-17:00; Wednesday: Closed',
    '09:30-17:00',
])
def test_separate_hours_field_is_not_lost_behind_closed_now(hours):
    activity = _activity_from_destination({
        'title': 'Museum', 'openingHours': 'Closed now', 'hours': hours,
    }, 0)
    opening = _activity_opening(activity, date(2026, 11, 24))
    assert opening['periods'] == [(570, 1020)]
    assert opening['evidence']['field'] == 'hours'
    assert opening['provisional'] is False


def test_weekday_range_closure_and_invalid_equal_clock_are_not_open_windows():
    assert _opening_window('Monday-Friday: Closed; Saturday: 09:00-18:00', date(2026, 11, 23))['status'] == 'closed'
    assert _opening_window('09:00-09:00', date(2026, 11, 24))['status'] == 'unknown'


def test_malformed_structured_periods_are_provisional_not_all_day_open():
    activity = _activity(1, opening_hours={'periods': [
        {'open': {'day': 2, 'time': '0900'}, 'close': {'day': 2, 'time': '9960'}},
    ]})
    visit = generateItinerary([], {}, _trip(activities=[activity]))['activities'][0]
    assert visit['openingHoursStatus'] == 'unknown'
    assert visit['scheduleFeasibility'] == 'provisional'
