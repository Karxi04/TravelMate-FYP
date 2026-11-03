from datetime import date, timedelta
from copy import deepcopy
from math import radians, sin, cos, sqrt, atan2
from unittest.mock import patch

import pytest
from sequence_contract import domain_functions as core

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


def test_geographic_grouping_avoids_cross_region_bounce_and_records_provenance(monkeypatch):
    # Keep the legacy exact-order assertion separate from enabled route guarantees.
    monkeypatch.setenv('TRAVELMATE_ROUTE_IMPROVEMENT_ENABLED', 'false')
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


ROUTE_FLAG = 'TRAVELMATE_ROUTE_IMPROVEMENT_ENABLED'


def _route_trip(days=1, count=4, pace='moderate', spread=.1):
    start = date(2027, 1, 4)
    return {**_trip(days, 0, pace, start), 'travellerCount': 2, 'budgetLimit': 5000,
        'activities': [_activity(i, category='culture', score=99-i,
            openingHours='09:00-21:00', providerDurationMinutes=45,
            testPeriods=[(540, 1260)], gps_coordinates={
                'latitude': 5.416 + (i % 2)*spread + (i//2)*.001, 'longitude': 100.33})
            for i in range(count)]}


def _route_km(items):
    total = 0
    for a, b in zip(items, items[1:]):
        a, b = a['gps_coordinates'], b['gps_coordinates']
        x, y = radians(a['latitude']), radians(b['latitude'])
        h = sin((y-x)/2)**2 + cos(x)*cos(y)*sin(radians(b['longitude']-a['longitude'])/2)**2
        total += 6371*2*atan2(sqrt(h), sqrt(max(0, 1-h)))
    return total


def _clock(value):
    h, m = map(int, value.split(':'))
    return h*60 + m


def _assert_route_preserved(before, after):
    assert before['startDate'] == after['startDate'] and before['endDate'] == after['endDate']
    assert before['unscheduledSuggestions'] == after['unscheduledSuggestions']
    assert before['generationContext'] == after['generationContext']
    assert before['scheduledActivityCount'] == after['scheduledActivityCount']
    assert before['provisionalActivityCount'] == after['provisionalActivityCount']
    assert calculateBudget(before) == calculateBudget(after)
    for old, new in zip(before['dailySchedule'], after['dailySchedule']):
        old_ids = {a['activityId'] for a in old['activities']}
        assert old_ids == {a['activityId'] for a in new['activities']}
        assert old['dayDate'] == new['dayDate'] and old['dayNo'] == new['dayNo']
        assert old['weather'] == new['weather'] and old['planningBlocks'] == new['planningBlocks']
        assert old['estimatedCost'] == new['estimatedCost']
        if old['activities']:
            assert new['activities'][-1]['scheduledEndTime'] <= old['activities'][-1]['scheduledEndTime']
            assert sum(a['travelDurationMinutes'] for a in new['activities']) <= sum(a['travelDurationMinutes'] for a in old['activities'])
        assert _route_km(new['activities']) <= _route_km(old['activities']) + 1e-6
        previous = _clock(new['planningWindow']['startTime'])
        for item in new['activities']:
            original = next(a for a in old['activities'] if a['activityId'] == item['activityId'])
            for key in ('score', 'estimatedCost', 'recommendedDurationMinutes', 'scheduleFeasibility', 'openingHoursEvidence'):
                assert item[key] == original[key]
            start, end = _clock(item['scheduledStartTime']), _clock(item['scheduledEndTime'])
            assert start >= previous + item['travelDurationMinutes']
            assert end - start == item['recommendedDurationMinutes']
            assert end <= _clock(new['planningWindow']['endTime'])
            assert not (start < 810 and end > 750)
            if item.get('testPeriods'):
                assert any(left <= start and end <= right for left, right in item['testPeriods'])
            assert item['dayDate'] == new['dayDate'] and item['dayNo'] == new['dayNo']
            previous = end
    assert [a['sequenceNo'] for a in after['activities']] == list(range(1, len(after['activities'])+1))
    assert after['activities'] == [a for d in after['dailySchedule'] for a in d['activities']]


def _route_pair(monkeypatch, data, forecast=None):
    original = deepcopy(data)
    monkeypatch.setenv(ROUTE_FLAG, 'false')
    baseline = generateItinerary([], forecast or {}, data)
    monkeypatch.setenv(ROUTE_FLAG, 'true')
    improved = generateItinerary([], forecast or {}, data)
    assert data == original
    _assert_route_preserved(baseline, improved)
    return baseline, improved


@pytest.mark.parametrize('closing', [False, True])
def test_route_reproduces_audit_and_repairs_only_feasible_order(monkeypatch, closing):
    data = _route_trip()
    if closing:
        for item, offset, close in zip(data['activities'], [0, .001, .1, .101], [20, 18, 19, 21]):
            item['gps_coordinates']['latitude'] = 5.416 + offset
            item['openingHours'] = f'09:00-{close}:00'
            item['testPeriods'] = [(540, close*60)]
    before, after = _route_pair(monkeypatch, data)
    assert _route_km(before['activities']) == pytest.approx(33.3584779934 if closing else 11.2306875911)
    assert _route_km(after['activities']) == pytest.approx(11.2306875911)
    if closing:
        assert [a['activityId'] for a in after['activities']] == ['a0', 'a1', 'a2', 'a3']


@pytest.mark.parametrize('days', [1, 3, 5])
@pytest.mark.parametrize('pace', ['slow', 'moderate', 'fast'])
@pytest.mark.parametrize('count', [5, 10, 20])
@pytest.mark.parametrize('spread', [.002, .1])
def test_route_multiday_pace_density_counts_and_scores(monkeypatch, days, pace, count, spread):
    data = _route_trip(days, count, pace, spread)
    with patch.object(core, '_constraint_plan', wraps=core._constraint_plan) as planner:
        _route_pair(monkeypatch, data)
    assert planner.call_count <= 66  # two baselines plus at most64 replay trials


@pytest.mark.parametrize('hours,periods', [
    ('09:00-12:00; 14:00-19:00', [(540,720),(840,1140)]),
    ('20:00-02:00', [(1200,1560)]),
    ('', None),
    ('Closed now', None),
    ('Permanently closed', None),
    ({'monday':'Closed', 'tuesday':'09:30-17:00'}, [(570,1020)]),
    ({'periods':[{'open':{'day':1,'time':'0930'},'close':{'day':1,'time':'1700'}}]}, [(570,1020)]),
])
def test_route_hours_evidence_and_uncertainty_survive(monkeypatch, hours, periods):
    data = _route_trip(3, 10)
    data['activities'][2].update(openingHours=hours, testPeriods=periods)
    _route_pair(monkeypatch, data)


def test_route_rejects_shorter_orders_that_lose_required_visits(monkeypatch):
    data = _route_trip()
    for item, hours, periods in zip(data['activities'],
            ['09:00-10:00','10:30-11:30','14:00-15:00','16:00-17:00'],
            [[(540,600)],[(630,690)],[(840,900)],[(960,1020)]]):
        item.update(openingHours=hours, testPeriods=periods, required=True)
    before, after = _route_pair(monkeypatch, data)
    assert [a['activityId'] for a in after['activities']] == ['a0','a1','a2','a3']
    assert before['dailySchedule'] == after['dailySchedule']


def test_route_rain_preference_pattern_is_not_weakened(monkeypatch):
    data = _route_trip(3, 10)
    for i, item in enumerate(data['activities']):
        item.update(category='museum' if i%2 else 'nature')
    forecast = {'daily':{'time':['2027-01-04','2027-01-05','2027-01-06'],
                         'precipitation_probability_max':[90,90,90], 'weather_code':[61,61,61]}}
    before, after = _route_pair(monkeypatch, data, forecast)
    for old, new in zip(before['dailySchedule'], after['dailySchedule']):
        assert [core._indoor(a) for a in old['activities']] == [core._indoor(a) for a in new['activities']]


@pytest.mark.parametrize('kind', ['missing_coordinates','nan','range','provider','ties','impossible'])
def test_route_safe_fallbacks(monkeypatch, kind, caplog):
    data = _route_trip()
    if kind == 'missing_coordinates':
        data['activities'][0].pop('gps_coordinates')
    elif kind == 'provider':
        data['activities'][1].update(providerTravelDurationMinutes=20,travelTimeSource='provider')
    elif kind == 'ties':
        for item in data['activities']:item['gps_coordinates']={'latitude':5.416,'longitude':100.33}
    elif kind == 'impossible':
        for item in data['activities']:item.update(openingHours='09:00-09:30',providerDurationMinutes=120)
    monkeypatch.setenv(ROUTE_FLAG, 'false')
    baseline = generateItinerary([], {}, data)
    if kind in {'nan','range'}:
        baseline['dailySchedule'][0]['activities'][0]['gps_coordinates']['latitude'] = float('nan') if kind=='nan' else 95
    original = deepcopy(baseline)
    # Invalid coordinates are tested at the improvement boundary, not certified as valid baseline data.
    with caplog.at_level('DEBUG'):
        result = core._improve_route(baseline,{})
    assert result is baseline
    assert repr(baseline) == repr(original)
    assert 'original schedule retained' in caplog.text


def test_route_timeout_returns_original_and_logs_no_false_success(monkeypatch, caplog):
    data = _route_trip()
    baseline = core._constraint_plan(data,{})
    ticks = iter([0,1])
    monkeypatch.setattr(core,'perf_counter',lambda:next(ticks))
    with caplog.at_level('INFO'):
        assert core._improve_route(baseline,{}) is baseline
    assert 'time limit; original schedule retained' in caplog.text


def test_route_disabled_and_manual_reorder_are_backward_compatible(monkeypatch):
    data = _route_trip(3,10)
    monkeypatch.setattr(core,'utc_now_iso',lambda:'fixed-fixture-time')
    with patch.object(core,'_improve_route',side_effect=AssertionError('Must not optimize')):
        results=[]
        for value in ('false','0','invalid',''):
            monkeypatch.setenv(ROUTE_FLAG,value)
            results.append(generateItinerary([],{},data))
        assert all(result==results[0] for result in results)
        monkeypatch.setenv(ROUTE_FLAG,'true')
        manual=recalculateItinerary(results[0],preserveOrder=True,respectDayAssignments=True)
        assert [a['activityId'] for a in manual['activities']]==[a['activityId'] for a in results[0]['activities']]


def test_route_retains_local_calendar_dates_from_offset_timestamps(monkeypatch):
    data = _route_trip(3, 10)
    data.update(startDate='2027-01-04T00:15:00+08:00',endDate='2027-01-06T23:00:00+08:00')
    _, after = _route_pair(monkeypatch,data)
    assert [day['dayDate'] for day in after['dailySchedule']]==['2027-01-04','2027-01-05','2027-01-06']


@pytest.mark.parametrize('selection_enabled',[False,True])
def test_route_improvement_executes_through_registered_http_generation(client,mock_traveller_auth,monkeypatch,selection_enabled):
    from test_fr05_budget_aware_integration import fixture,_personalised_payload,HEADERS
    data=_route_trip()
    for item,offset,close in zip(data['activities'],[0,.001,.1,.101],[20,18,19,21]):
        item['gps_coordinates']['latitude']=5.416+offset
        item['openingHours']=f'09:00-{close}:00'
        item.update(address='George Town, Penang, Malaysia',destinationId='synthetic-'+item['activityId'])
    monkeypatch.setenv('TRAVELMATE_BUDGET_AWARE_SELECTION_ENABLED',str(selection_enabled).lower())
    results=[]
    for enabled in (False,True):
        monkeypatch.setenv(ROUTE_FLAG,str(enabled).lower())
        with fixture(data['activities'],new_trip=True),patch.object(core,'_improve_route',wraps=core._improve_route) as improvement:
            response=client.post('/api/fr5/personalised-trips/generate',headers=HEADERS,
                json={**_personalised_payload(5000),'startDate':'2027-01-04','endDate':'2027-01-04'})
            assert response.status_code==200,response.json
            saved=response.json['itinerary']
            results.append(saved)
            assert bool(improvement.call_count)==enabled
    before,after=results
    assert len(before['activities'])==len(after['activities'])==4
    assert {a['destinationId'] for a in before['activities']}=={a['destinationId'] for a in after['activities']}
    assert _route_km(before['activities'])==pytest.approx(33.3584779934)
    assert _route_km(after['activities'])==pytest.approx(11.2306875911)
    assert before['budgetEstimate']==after['budgetEstimate']
    if selection_enabled:
        assert before['budgetAwareSelection']==after['budgetAwareSelection']


@pytest.mark.parametrize('budget,count,total', [(50,0,95),(500,4,495),(5000,5,595)])
def test_route_enabled_preserves_real_http_budget_and_snapshot(client, mock_traveller_auth, monkeypatch, budget, count, total):
    from test_fr05_budget_aware_integration import fixture, _personalised_payload, HEADERS
    from test_budget_aware_selection import activity
    monkeypatch.setenv(ROUTE_FLAG,'true')
    monkeypatch.setenv('TRAVELMATE_BUDGET_AWARE_SELECTION_ENABLED','true')
    items=[activity(f'ticket{i}',100,99-i,'per_group') for i in range(5)]
    with fixture(items,new_trip=True) as (current,snapshot,_,writes):
        response=client.post('/api/fr5/personalised-trips/generate',headers=HEADERS,json=_personalised_payload(budget))
        assert response.status_code==200,response.json
        saved=response.json['itinerary']
        assert len(saved['activities'])==count and saved['budgetEstimate']['totalEstimatedCost']==total
        assert saved['budgetAwareSelection']['applied'] is True
        assert saved==current and writes.call_count==1
        assert [a['score'] for a in saved['activities']]==list(range(99,99-count,-1))
        if budget==50:assert 'no fully affordable itinerary' in saved['budgetEstimate']['attention']
        retry=client.post('/api/fr5/personalised-trips/generate',headers=HEADERS,json=_personalised_payload(budget))
        assert retry.json['reused'] is True and retry.json['itinerary']==saved

