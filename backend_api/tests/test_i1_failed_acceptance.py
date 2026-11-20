"""Reproduce failed-acceptance paths with isolated data/providers, never owner records."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from modules.fr05_smart_itinerary_budget_planner import routes as budget_routes
from modules.fr07_flight_search import routes as flights
from test_local_reviews import memory, headers
from test_batch_i1_budget_flights import trip
from test_fr05_advisory_apply import _fixture, HEADERS, PATH


def test_saved_cabin_survives_expired_quote_without_provider_or_firestore(monkeypatch):
    current = trip()
    current['selectedFlight']['requestedTravelClass'] = 3
    current['selectedFlight']['outboundSegments'][0].pop('travelClass')
    current['flightSearchId'] = 'expired-owned-quote'
    lookup = Mock(side_effect=AssertionError('Persisted cabin does not require old quote reads'))
    monkeypatch.setattr(flights, '_load_quote', lookup)
    assert budget_routes._flight_cabin(current) == 3
    assert budget_routes._flight_comparison_diagnostics(current)['status'] == 'eligible'
    lookup.assert_not_called()


def test_saved_segments_and_known_cabin_conflict_is_not_guessed(monkeypatch):
    current = trip()
    current['selectedFlight']['requestedTravelClass'] = 3
    assert budget_routes._flight_cabin(current) is None


def test_normal_expensive_flight_attaches_to_origin_but_is_not_a_cheaper_alternative(client, memory, monkeypatch):
    current = trip()
    current['flightSearchId'] = 'old'
    option = {**deepcopy(current['selectedFlight']), 'id': 'expensive', 'optionId': 'expensive',
              'price': 900, 'quoteCompleteness': 'complete', 'budgetEligible': True}
    quote = {'id': 'fresh', 'travellerId': 'owner', 'criteria': {'traveller_count': 2, 'travel_class': 1},
             'expiresAt': (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()}
    monkeypatch.setattr(flights, '_quote_item', lambda _: (quote, option, None))
    monkeypatch.setattr(flights, '_own_itinerary', lambda _: deepcopy(current))
    writes = []
    def write(collection, identity, patch):
        assert collection == 'itineraries' and identity == 'owned'
        current.update(deepcopy(patch)); writes.append(identity); return deepcopy(current)
    monkeypatch.setattr(flights, 'updateRecord', write)
    response = client.post('/api/fr7/flights/select', headers=headers(),
                           json={'itineraryId': 'owned', 'searchId': 'fresh', 'optionId': 'expensive'})
    assert response.status_code == 200, response.json
    assert response.json['itinerary']['id'] == 'owned' and response.json['budget']['flight'] == 900
    assert response.json['budget']['total'] == 1365
    assert response.json['budget']['affordabilityStatus'] == 'over_budget'
    assert response.json['budget']['overBy'] == 665
    assert current['selectedFlight']['price'] == 900 and writes == ['owned']
    # Budget replacement is a different contract; an increase is never advertised as a saving.
    from sequence_contract.domain_functions import _alternative_savings
    baseline = trip()
    assert _alternative_savings('flight', {**option, '_validatedAlternative': True}, baseline) is None


def test_whole_trip_party_and_unknown_cost_boundaries_are_preserved():
    from services.trip_budget_replan import preview_budget_replan
    from sequence_contract.domain_functions import calculateBudget
    for limit, food, transport, flight, hotel in [(200,180,105,0,0),(700,360,105,263,0),
                                                 (800,360,210,0,504.92),(900,360,105,600,0)]:
        source = trip()
        source.update(budgetLimit=limit, foodCost=food, transportCost=transport, flightCost=flight,
                      hotelCost=hotel, hotelCurrency='MYR')
        original=deepcopy(source)
        _,preview=preview_budget_replan(source,{'foodCost':food-40})
        assert preview['estimatedReduction']==40 and source==original
        assert preview['budget']['knownEstimatedSubtotal']==round(calculateBudget(source)['knownEstimatedSubtotal']-40,2)
        assert preview['budget']['affordabilityStatus'] != 'within_budget'
        if limit==900:
            assert preview['budget']['overBy']>0  # Allowance reduction can leave a trip over budget.


def same_day_trip(protected=False):
    current = trip()
    current.update(startDate='2026-11-24', endDate='2026-11-24', flightCost=1833)
    flight = deepcopy(current['selectedFlight'])
    flight.update(price=1833, requestedTravelClass=1,
                  outboundSegments=[{'departureAirportCode':'KUL','arrivalAirportCode':'PEN',
                      'departureDate':'2026-11-24','arrivalDate':'2026-11-24',
                      'departureTime':'10:50','arrivalTime':'11:50','travelClass':'Economy'}],
                  returnSegments=[{'departureAirportCode':'PEN','arrivalAirportCode':'KUL',
                      'departureDate':'2026-11-24','arrivalDate':'2026-11-24',
                      'departureTime':'12:35','arrivalTime':'13:40','travelClass':'Economy'}])
    activities = [{'activityId':'art','activityName':'Penang Street Art','dayNo':1,
                   'scheduledStartTime':'09:00','scheduledEndTime':'10:00','timeSlot':'09:00',
                   'recommendedDurationMinutes':60,'openingHours':'08:00-18:00'},
                  {'activityId':'later','activityName':'Afternoon visit','dayNo':1,
                   'scheduledStartTime':'13:30','scheduledEndTime':'14:30','timeSlot':'13:30',
                   'recommendedDurationMinutes':60,'openingHours':'08:00-18:00'}]
    if protected:
        activities[0].update(paymentId='protected-payment', paid=True)
    current.update(selectedFlight=flight, activities=activities,
                   dailySchedule=[{'dayNo':1,'dayDate':'2026-11-24','activities':deepcopy(activities)}])
    return current


def test_exact_same_day_flights_warn_for_both_reported_visits():
    current = same_day_trip()
    warnings = flights._flight_conflicts(current, current['selectedFlight'])
    assert any(row['activityId']=='art' and row['type']=='arrival_activity' for row in warnings)
    assert any(row['activityId']=='later' and row['type']=='departure_activity' for row in warnings)


def test_adjust_same_day_no_window_does_not_leave_stale_day_cards_or_claim_feasibility():
    from services.flight_itinerary_adjustment import create_preview
    current = same_day_trip()
    before=deepcopy(current)
    preview=create_preview(current,current['selectedFlight'],'owner')
    assert current==before
    assert preview['after']['activities']==[]
    assert preview['after']['dailySchedule'][0]['activities']==[]
    assert {row['activityId'] for row in preview['newlyUnscheduled']}=={'art','later'}
    assert preview['scheduleFeasibility']=='no_sightseeing_window'
    assert 'No sightseeing window' in preview['reason']


def test_paid_visits_are_never_moved_or_removed_by_flight_adjustment():
    from services.flight_itinerary_adjustment import create_preview,apply_preview
    current=same_day_trip(protected=True)
    before=deepcopy(current)
    preview=create_preview(current,current['selectedFlight'],'owner')
    assert next(row for row in preview['after']['activities'] if row['activityId']=='art')==current['activities'][0]
    assert any(row['activityId']=='art' for row in preview['remainingConflicts'])
    assert not preview['canApply']
    update=Mock(side_effect=AssertionError('No apply with protected flight conflict'))
    result,error=apply_preview(preview['previewId'],current,current['selectedFlight'],'owner',update)
    assert result is None and error
    update.assert_not_called()
    assert current==before


def test_actual_storage_adapter_allowance_cancel_confirm_reopen_and_concurrent_change(client, memory, monkeypatch):
    from test_itinerary_history import HistoryDatabase
    from sequence_contract import firebase_firestore as storage
    from services.itinerary_history import HistoryConflict
    db=HistoryDatabase()
    current=trip()
    db.records[('itineraries','owned')]={k:v for k,v in current.items() if k!='id'}
    monkeypatch.setattr(storage,'get_db',lambda:db)
    monkeypatch.setattr('google.cloud.firestore.transactional',db.transactional)
    def read(collection,identity=None,**kw):
        row=db.records.get((collection,identity))
        return {'id':identity,**deepcopy(row)} if row else None
    monkeypatch.setattr(budget_routes,'retrieveRecord',read)
    path='/api/fr5/itineraries/owned/budget-replan'
    options=client.get(path,headers=headers()).json
    command={'changes':{'foodCost':320},'stateVersion':options['stateVersion']}
    preview=client.post(path+'/preview',headers=headers(),json=command)
    assert preview.status_code==200 and db.writes==0
    assert db.records[('itineraries','owned')]['foodCost']==360  # Cancel is no call to Apply.
    command.update(confirmed=True,previewToken=preview.json['previewToken'])
    accepted=client.post(path+'/apply',headers=headers(),json=command)
    assert accepted.status_code==200 and db.writes==1
    reopened=client.get('/api/fr5/itineraries/owned',headers=headers()).json['itinerary']
    assert reopened['foodCost']==320 and reopened['budgetEstimate']['total']==688
    assert reopened['itineraryHistory'][0]['state']['foodCost']==360
    assert reopened['selectedFlight']==current['selectedFlight']
    assert client.post(path+'/apply',headers=headers(),json=command).status_code==409 and db.writes==1
    # A separate edit after Preview is rejected by the actual storage expected-state guard.
    options=client.get(path,headers=headers()).json
    next_command={'changes':{'foodCost':300},'stateVersion':options['stateVersion']}
    preview=client.post(path+'/preview',headers=headers(),json=next_command)
    next_command.update(confirmed=True,previewToken=preview.json['previewToken'])
    def concurrent(collection,identity,patch,expected=None):
        db.records[(collection,identity)]['budgetLimit']=800
        return storage.updateRecord(collection,identity,patch,expected=expected)
    monkeypatch.setattr(budget_routes,'updateRecord',concurrent)
    stale=client.post(path+'/apply',headers=headers(),json=next_command)
    assert stale.status_code==409 and db.writes==1
    assert db.records[('itineraries','owned')]['foodCost']==320


def test_flight_adjustment_write_uses_expected_trip_and_syncs_saved_day_cards(client, memory, monkeypatch):
    from services.itinerary_history import HistoryConflict
    current=same_day_trip()
    current['selectedFlight']['returnSegments'][0]['departureTime']='21:00'
    current['selectedFlight']['returnSegments'][0]['arrivalTime']='22:00'
    current['endDate']='2026-11-25'
    before=deepcopy(current)
    monkeypatch.setattr(budget_routes,'_own',lambda _:deepcopy(current))
    preview=client.post('/api/fr5/itineraries/owned/flight-adjustment/preview',headers=headers()).json['preview']
    assert preview['canApply']
    calls=[]
    def update(collection,identity,patch,expected=None):
        assert expected==before
        calls.append(patch);current.update(deepcopy(patch));return deepcopy(current)
    monkeypatch.setattr(budget_routes,'updateRecord',update)
    saved=client.post('/api/fr5/itineraries/owned/flight-adjustment/apply',headers=headers(),
                     json={'previewId':preview['previewId']})
    assert saved.status_code==200 and len(calls)==1
    assert saved.json['itinerary']['dailySchedule'][0]['activities']==saved.json['itinerary']['activities']
    assert current['selectedFlight']==before['selectedFlight']
