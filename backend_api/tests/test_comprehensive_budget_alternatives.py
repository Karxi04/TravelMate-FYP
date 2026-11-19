
"""Offline end-to-end budget category and flight-window regression cases."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import pytest
from test_fr05_advisory_apply import _fixture, PATH, HEADERS, P
from test_fr05_alternative_integrity import _planned_trip, _isolated
from test_i1_failed_acceptance import same_day_trip
from services.trip_budget_replan import planning_alternatives, preview_budget_replan
from sequence_contract.domain_functions import calculateBudget
from services.flight_itinerary_adjustment import create_preview, apply_preview


def _990():
    return dict(id='trip', travellerId='test_traveller_uid', destinationArea='Penang',
                startDate='2026-11-24', endDate='2026-11-26', travellerCount=2,
                budgetLimit=700, foodCost=360, transportCost=105, flightCost=525,
                flightCurrency='MYR', flightPriceBasis='group_total', travelMode='flight', activities=[])


def test_990_shows_independent_food_and_transport_with_exact_reductions():
    trip=_990();before=deepcopy(trip)
    result=planning_alternatives(trip,calculateBudget(trip))
    assert calculateBudget(trip)['total']==990
    assert [(row['category'],row['currentEstimatedCost'],row['replacementEstimatedCost'],
             row['estimatedSavings'],row['remainingOverBy']) for row in result]==[
        ('Food',360,324,36,254),('Local transport',105,94.5,10.5,279.5)]
    assert trip==before
    _,preview=preview_budget_replan(trip,{'foodCost':324,'transportCost':94.5})
    assert preview['budget']['total']==943.5 and preview['budget']['overBy']==243.5
    assert preview['estimatedReduction']==46.5


def test_local_options_survive_each_independent_quote_store_failure(client,mock_traveller_auth):
    with _fixture() as (trip,_,_,write,store):
        trip.update(_990(),hotelBookingId='old',hotelCost=200,hotelCurrency='MYR',accommodationChoice='paid_hotel')
        with patch(P+'_flight_alternative_options',side_effect=TimeoutError), \
             patch(P+'_activity_options',side_effect=RuntimeError), \
             patch(P+'retrieveRecord',side_effect=lambda collection,identity=None,**kw:
                   deepcopy(trip) if collection=='itineraries' else (_ for _ in ()).throw(RuntimeError())):
            result=client.post(PATH,headers=HEADERS)
        assert result.status_code==200
        assert {row['category'] for row in result.json['planningAlternatives']}=={'Food','Local transport'}
        write.assert_not_called();store.assert_not_called()


def test_695_1500_skips_all_quote_discovery_even_with_unpriced_costs(client,mock_traveller_auth):
    with _fixture() as (trip,_,_,write,store):
        trip.update(foodCost=300,transportCost=195,flightCost=0,hotelCost=200,budgetLimit=1500,
                    travelMode='own_vehicle',selectedFlight=None,activities=[{}])
        with patch(P+'_flight_alternative_options',side_effect=AssertionError('No searches')), \
             patch(P+'_activity_options',side_effect=AssertionError('No catalogue scan')):
            result=client.post(PATH,headers=HEADERS)
        assert result.status_code==200 and result.json['budget']['total']==695
        assert result.json['planningAlternatives']==result.json['alternatives']==[]
        assert result.json['budget']['pendingExpenseCategories']
        write.assert_not_called();store.assert_not_called()


@pytest.mark.parametrize('mutation',[
    {'paid':True},{'locked':True},{'userFixed':True},{'isLocked':True},{'manualTime':True},
    {'required':True},{'bookingReference':'protected'},{'optional':False}])
def test_optional_removal_preserves_each_protection(mutation):
    from services.trip_budget_replan import _removable
    trip=_990()
    trip['activities']=[dict(activityId='visit',estimatedCost=40,pricingUnit='per_group',
                             costProvenance='user_entered',**mutation)]
    assert _removable(trip)==[]


def test_unknown_admission_never_becomes_free_or_numeric_saving():
    trip=_990();trip['activities']=[dict(activityId='unpriced',activityName='Unknown visit')]
    assert not any(row['category']=='Activities' for row in planning_alternatives(trip,calculateBudget(trip)))
    assert 'activities' in calculateBudget(trip)['pendingExpenseCategories']


def test_optional_unpaid_admission_removal_is_a_real_recalculated_preview():
    trip=_planned_trip();trip.pop('checkoutOrderId');trip['activities']=trip['activities'][:1]
    trip['dailySchedule']=trip['dailySchedule'][:1];trip['endDate']=trip['startDate']
    options=planning_alternatives(trip,calculateBudget(trip))
    removal=next(row for row in options if row['category']=='Activities')
    assert removal['estimatedSavings']==80
    patch,preview=preview_budget_replan(trip,removal['changes'])
    assert patch['activities']==[] and patch['dailySchedule'][0]['activities']==[]
    assert preview['estimatedReduction']==80 and trip['activities']


@pytest.mark.parametrize('invalid', ['expired','occupancy','rooms','currency','basis','paid','pending','supplier'])
def test_invalid_or_protected_hotels_never_become_actionable(client,mock_traveller_auth,invalid):
    with _fixture() as (trip,_,bookings,write,store):
        row=bookings['new']
        row.update(saveDetailsOnly=True,acceptedPrebookSnapshotId='accepted',
            acceptedPrebookSnapshot={'id':'accepted','status':'accepted','amount':120,'currency':'MYR',
                                     'priceBasis':'stay_total','expiresAt':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()})
        if invalid=='expired':row['acceptedPrebookSnapshot']['expiresAt']='2020-01-01T00:00:00+00:00'
        if invalid=='occupancy':row['stayCriteria']['adults']=1
        if invalid=='rooms':row['selectedHotel']['roomQuantity']=2
        if invalid=='currency':row['hotelCurrency']='USD'
        if invalid=='basis':row['acceptedPrebookSnapshot']['priceBasis']='per_night'
        if invalid=='paid':bookings['old']['bookingStatus']='paid'
        if invalid=='pending':bookings['old']['verificationRequired']=True
        if invalid=='supplier':bookings['old']['hotelConfirmationCode']='protected'
        reply=client.post(PATH,headers=HEADERS)
        assert reply.status_code==200
        assert not any(item['alternativeType']=='hotel' for item in reply.json['alternatives'])
        assert reply.json['planningAlternatives']
        write.assert_not_called();store.assert_not_called()


def test_valid_unpaid_hotel_offer_preview_cancel_confirm_reopen(client,mock_traveller_auth):
    with _fixture() as (trip,_,bookings,write,store):
        row=bookings['new']
        row.update(saveDetailsOnly=True,acceptedPrebookSnapshotId='accepted',
            acceptedPrebookSnapshot={'id':'accepted','status':'accepted','amount':120,'currency':'MYR',
                                     'priceBasis':'stay_total','expiresAt':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()})
        response=client.post(PATH,headers=HEADERS)
        option=next(item for item in response.json['alternatives'] if item['alternativeType']=='hotel')
        assert option['estimatedSavings']==80
        before=deepcopy(trip)
        preview=client.post(PATH+'/preview',headers=HEADERS,json={'alternative':option})
        assert preview.status_code==200 and preview.json['estimatedReduction']==80
        assert trip==before;write.assert_not_called() # Cancel
        applied=client.post(PATH+'/apply',headers=HEADERS,json={'alternative':option})
        assert applied.status_code==200 and trip['hotelCost']==120
        assert trip['hotelBookingId']=='new' and bookings['old']['hotelCost']==200
        assert client.get('/api/fr5/itineraries/trip',headers=HEADERS).json['itinerary']['hotelCost']==120
        write.assert_called_once();store.assert_not_called()


@pytest.mark.parametrize('arrival,departure,can_apply', [('08:00','21:00',True),('11:50','12:35',False)])
def test_exact_reported_day_vs_feasible_day(arrival,departure,can_apply):
    trip=same_day_trip();trip['selectedFlight']['outboundSegments'][0]['arrivalTime']=arrival
    trip['selectedFlight']['returnSegments'][0]['departureTime']=departure
    preview=create_preview(trip,trip['selectedFlight'],'fixture')
    assert preview['canApply'] is can_apply
    if can_apply:
        assert preview['after']['activities']
        assert preview['after']['dailySchedule'][0]['activities']==preview['after']['activities']
        for row in preview['after']['activities']:
            assert row['scheduledStartTime']>='09:30' and row['scheduledEndTime']<='17:30'


def test_multiday_oneway_and_different_local_dates_do_not_invent_return():
    trip=same_day_trip()
    trip['endDate']='2026-11-26'
    flight=trip['selectedFlight'];flight['returnSegments']=[]
    flight['outboundSegments'][0]['arrivalDate']='2026-11-25'
    trip['activities'][1].update(dayNo=2,dayDate='2026-11-25')
    trip['dailySchedule']=[{'dayNo':i,'activities':[]} for i in range(1,4)]
    preview=create_preview(trip,flight,'fixture')
    assert preview['canApply'] and preview['boundaries']['departureLocal'] is None
    assert preview['availability']['days']['2026-11-24']['availableMinutes']==0
    assert not any(row['dayNo']==1 for row in preview['after']['activities'])
    assert preview['availability']['days']['2026-11-26']['availableMinutes']>0


def test_closed_activity_is_not_fabricated_and_protected_visit_stays_fixed():
    trip=same_day_trip(protected=True)
    flight=trip['selectedFlight'];flight['outboundSegments'][0]['arrivalTime']='06:00'
    flight['returnSegments'][0]['departureTime']='23:00'
    trip['activities'][1]['openingHours']='Closed'
    preview=create_preview(trip,flight,'fixture')
    assert preview['after']['activities'][0]==trip['activities'][0]
    assert any(row['activityId']=='later' for row in preview['newlyUnscheduled'])


def test_non_penang_malaysian_destination_uses_own_airport():
    trip=same_day_trip();trip['destinationArea']='Kuching'
    flight=trip['selectedFlight'];flight['outboundSegments'][0].update(arrivalAirportCode='KCH',arrivalTime='08:00')
    flight['returnSegments'][0].update(departureAirportCode='KCH',departureTime='21:00')
    preview=create_preview(trip,flight,'fixture')
    assert preview['boundaries']['arrivalLocal'] and preview['canApply']


def test_no_valid_reduction_at_existing_low_allowances():
    trip=_990();trip.update(foodCost=10,transportCost=5)
    assert planning_alternatives(trip,calculateBudget(trip))==[]
    trip.update(budgetLimit=1)
    assert planning_alternatives(trip,calculateBudget(trip))==[]


def test_actual_storage_combined_reduction_cancel_confirm_reopen_and_stale(client,mock_traveller_auth,monkeypatch):
    from test_itinerary_history import HistoryDatabase
    from sequence_contract import firebase_firestore as storage
    from modules.fr05_smart_itinerary_budget_planner import routes
    db=HistoryDatabase();trip=_990()
    db.records[('itineraries','trip')]={key:value for key,value in trip.items() if key!='id'}
    monkeypatch.setattr(storage,'get_db',lambda:db)
    monkeypatch.setattr('google.cloud.firestore.transactional',db.transactional)
    monkeypatch.setattr(routes,'retrieveRecord',lambda collection,identity=None,**kw:
        {'id':identity,**deepcopy(db.records[(collection,identity)])})
    base='/api/fr5/itineraries/trip/budget-replan'
    state=client.get(base,headers=HEADERS).json
    command={'changes':{'foodCost':324,'transportCost':94.5},'stateVersion':state['stateVersion']}
    preview=client.post(base+'/preview',headers=HEADERS,json=command)
    assert preview.status_code==200 and db.writes==0
    assert preview.json['budget']['total']==943.5
    command.update(confirmed=True,previewToken=preview.json['previewToken'])
    saved=client.post(base+'/apply',headers=HEADERS,json=command)
    assert saved.status_code==200 and db.writes==1
    reopened=client.get('/api/fr5/itineraries/trip',headers=HEADERS).json['itinerary']
    assert reopened['foodCost']==324 and reopened['transportCost']==94.5
    assert reopened['budgetEstimate']['total']==943.5
    assert reopened['itineraryHistory'][0]['state']['foodCost']==360
    assert client.post(base+'/apply',headers=HEADERS,json=command).status_code==409 and db.writes==1


def test_flight_constrained_optional_removal_never_creates_before_arrival_schedule():
    trip=same_day_trip()
    trip['activities'][1].update(estimatedCost=40,unitPrice=40,pricingUnit='per_group',costProvenance='user_entered')
    with pytest.raises(ValueError,match='flight-time conflict'):
        preview_budget_replan(trip,{'removeActivityIds':['later']})


def test_locked_visit_late_in_day_is_reserved_before_scheduling_other_visits():
    trip=same_day_trip()
    trip['selectedFlight']['outboundSegments'][0]['arrivalTime']='08:00'
    trip['selectedFlight']['returnSegments'][0]['departureTime']='23:00'
    trip['activities'][1].update(userFixed=True,scheduledStartTime='10:00',scheduledEndTime='11:00')
    before=deepcopy(trip['activities'][1])
    preview=create_preview(trip,trip['selectedFlight'],'fixture')
    assert next(row for row in preview['after']['activities'] if row['activityId']=='later')==before
    assert any(row['activityId']=='art' for row in preview['newlyUnscheduled'])
    assert not any(row.get('activityId')=='later' for row in preview['remainingConflicts'])


def test_protected_closed_venue_blocks_application_instead_of_moving_it():
    trip=same_day_trip(protected=True)
    trip['selectedFlight']['outboundSegments'][0]['arrivalTime']='06:00'
    trip['selectedFlight']['returnSegments'][0]['departureTime']='23:00'
    trip['activities'][0]['openingHours']='Closed'
    preview=create_preview(trip,trip['selectedFlight'],'fixture')
    assert not preview['canApply'] and preview['after']['activities'][0]==trip['activities'][0]



def test_activity_replacements_respect_saved_draft_exclusions_without_changing_scores(monkeypatch):
    from modules.fr05_smart_itinerary_budget_planner import routes
    from services.recommendation_taxonomy import candidate_concepts
    trip=_planned_trip()
    trip['planningPreferences']={'interests':['Culture'],'excludedInterests':['Nature']}
    options=routes._activity_options(trip)
    assert not any('nature' in candidate_concepts(item) for item in options.values())
    assert trip['planningPreferences']=={'interests':['Culture'],'excludedInterests':['Nature']}
