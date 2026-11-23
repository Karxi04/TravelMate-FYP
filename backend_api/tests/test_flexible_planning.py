"""Personal planning uses real FR5 routes and in-memory owner-scoped records only."""
from copy import deepcopy
from unittest.mock import Mock
import pytest
from test_fr08_fr09_hotels_payments import MemoryPersistence
from test_pu3b_flight_adjustment import _trip, _flight
from test_fr05_advisory_apply import HEADERS
from services.itinerary_history import history_patch, HistoryConflict
from services.flexible_planning import validate_preferences, validate_blocks, availability_for
from services.flight_itinerary_adjustment import reset_flight_adjustment_previews
from modules.fr05_smart_itinerary_budget_planner import routes as r

BASE='/api/fr5/itineraries'
PATH=BASE+'/flex'


@pytest.fixture
def planning(monkeypatch,mock_traveller_auth):
    memory=MemoryPersistence();writes=[]
    def update(collection,identity,patch,expected=None):
        current=memory.retrieve(collection,identity)
        if expected is not None and current!=expected:raise HistoryConflict('stale')
        writes.append(deepcopy(patch))
        return memory.update(collection,identity,history_patch(current,patch))
    monkeypatch.setattr(r,'retrieveRecord',memory.retrieve)
    monkeypatch.setattr(r,'claimRecord',memory.claim)
    monkeypatch.setattr(r,'updateRecord',update)
    monkeypatch.setattr(r,'storeRecord',lambda c,record:memory.seed(c,'flex',record) or memory.retrieve(c,'flex'))
    for name in ['retrieveDestinationResults','retrieveLocationAndTravelTime','retrieveSevenDayForecast']:
        monkeypatch.setattr(r,name,Mock(side_effect=AssertionError('No provider request authorized.')))
    reset_flight_adjustment_previews()
    return memory,writes


def basics(mode='manual'):
    return {'title':'Personal Penang plan','destinationArea':'Penang','startDate':'2027-12-12','endDate':'2027-12-16',
            'travellerCount':2,'budgetLimit':900,'travelMode':'undecided','accommodationChoice':'staying_with_family',
            'planningMode':mode,'generationRequestId':'flex-create-intent'}


def saved(memory,flight=True):
    trip=_trip();trip.update(id='flex',startDate='2027-12-12',endDate='2027-12-16',planningMode='assisted')
    trip['selectedFlight']=_flight('2027-12-12','10:00','2027-12-16','20:00') if flight else {}
    memory.seed('itineraries','flex',trip)
    return deepcopy(memory.retrieve('itineraries','flex'))


def preview(client,changes=None,**command):
    return client.post(PATH+'/flight-adjustment/preview',headers=HEADERS,
                       json={'planningChanges':changes or {},**command})


@pytest.mark.parametrize('mode',['manual','assisted'])
def test_empty_personal_creation_without_recommendations_or_arrangements(client,planning,mode):
    memory,writes=planning
    result=client.post(BASE,headers=HEADERS,json=basics(mode))
    assert result.status_code==201,result.json
    trip=result.json['itinerary']
    assert trip['planningMode']==mode and trip['activities']==[] and len(trip['dailySchedule'])==5
    assert not trip.get('selectedFlight') and not trip.get('hotelBookingId')
    assert client.post(BASE,headers=HEADERS,json=basics(mode)).status_code==200
    assert len(memory.collections['itineraries'])==1 and not writes
    assert client.post(BASE,headers=HEADERS,json={**basics(mode),'title':'Different'}).status_code==409


def test_arrival_rest_departure_cutoff_preview_cancel_confirm_and_reopen(client,planning):
    memory,writes=planning;before=saved(memory)
    response=preview(client,{'travelDayPreferences':{'arrival':{'choice':'rest','startTime':'15:00'},
                        'departure':{'choice':'custom','endTime':'15:00'}}})
    assert response.status_code==200,response.json
    p=response.json['preview'];assert p['canApply'],p
    assert p['availability']['days']['2027-12-12']['startMinutes']==900
    assert p['availability']['days']['2027-12-16']['endMinutes']==900
    assert all(row['scheduledStartTime']>='15:00' for row in p['after']['activities'] if row['dayNo']==1)
    assert memory.retrieve('itineraries','flex')==before and not writes
    applied=client.post(PATH+'/flight-adjustment/apply',headers=HEADERS,json={'previewId':p['previewId']})
    assert applied.status_code==200,applied.json
    response=client.get(PATH,headers=HEADERS).json
    reopened=response['itinerary']
    assert reopened['travelDayPreferences']['arrival']['startTime']=='15:00'
    assert response['planning']['availability']['confirmationStatus']=='confirmed'
    assert reopened['selectedFlight']==before['selectedFlight'] and reopened['hotelCost']==before['hotelCost']
    repeat=client.post(PATH+'/flight-adjustment/apply',headers=HEADERS,json={'previewId':p['previewId']})
    assert repeat.status_code==200 and repeat.json['idempotent'] and len(writes)==1


def test_earlier_than_safe_arrival_is_explained_without_rewriting_choice(client,planning):
    memory,writes=planning;saved(memory)
    response=preview(client,{'travelDayPreferences':{'arrival':{'choice':'custom','startTime':'12:00'}}})
    p=response.json['preview'];assert not p['canApply']
    assert '13:00' in p['reason']
    assert p['after']['travelDayPreferences']['arrival']['startTime']=='12:00'
    assert client.post(PATH+'/flight-adjustment/apply',headers=HEADERS,json={'previewId':p['previewId']}).status_code==409
    assert not writes


def test_no_flight_estimated_transport_and_rest_only_day(client,planning):
    memory,writes=planning;saved(memory,flight=False)
    result=preview(client,{'travelDayPreferences':{'transport':{'arrivalDate':'2027-12-12','arrivalTime':'10:00',
        'departureDate':'2027-12-16','departureTime':'20:00','bufferMinutes':60},
        'arrival':{'choice':'none'},'days':[{'dayNo':3,'restDay':True}]}})
    p=result.json['preview'];assert p['canApply'],p
    assert p['boundaries']['source']=='user_estimate'
    assert p['availability']['days']['2027-12-12']['availableMinutes']==0
    assert p['availability']['days']['2027-12-14']['availableMinutes']==0
    assert not writes


@pytest.mark.parametrize('bad',[{'arrival':{'choice':'custom','startTime':'25:00'}},
    {'days':[{'dayNo':True,'startTime':'09:00','endTime':'18:00'}]},
    {'days':[{'dayNo':2,'startTime':'18:00','endTime':'09:00'}]}, {'confirmedFor':'untrusted'},
    {'transport':{'bufferMinutes':-1}}, {'transport':{'arrivalDate':'2027-12-12'}}])
def test_malformed_preferences_rejected_before_writes(client,planning,bad):
    memory,writes=planning;saved(memory)
    assert preview(client,{'travelDayPreferences':bad}).status_code==400
    assert not writes


def test_custom_blocks_preserved_and_counted_once_without_reservations(client,planning):
    memory,writes=planning;saved(memory,flight=False)
    blocks=[{'blockId':'rest-block-001','label':'Rest first','type':'rest','dayNo':1,'startTime':'09:00',
        'endTime':'11:00','locked':True}, {'blockId':'meal-block-002','label':'Personal meal','type':'meal',
        'dayNo':1,'startTime':'12:00','endTime':'13:00','estimatedCost':25}]
    p=preview(client,{'planningBlocks':blocks},action='improve').json['preview']
    assert p['canApply'],p
    assert p['budgetAfter']['personalPlans']==25
    assert p['after']['flightCost']==p['before']['flightCost'] and p['after']['hotelCost']==p['before']['hotelCost']
    for row in p['after']['activities']:
        if row['dayNo']==1:assert row['scheduledStartTime']>='11:00'
    assert client.post(PATH+'/flight-adjustment/apply',headers=HEADERS,json={'previewId':p['previewId']}).status_code==200
    reopened=client.get(PATH,headers=HEADERS).json['itinerary']
    assert len(reopened['planningBlocks'])==2 and reopened['budgetEstimate']['personalPlans']==25
    assert len([b for b in reopened['dailySchedule'][0]['planningBlocks'] if b.get('personal')])==2


@pytest.mark.parametrize('protection',['fixed','paymentId'])
def test_fixed_or_paid_visit_cannot_be_moved_to_force_arrival_preferences(client,planning,protection):
    memory,writes=planning;trip=saved(memory)
    trip['activities'][0][protection]=True if protection=='fixed' else 'synthetic-payment'
    memory.seed('itineraries','flex',trip)
    p=preview(client,{'travelDayPreferences':{'arrival':{'choice':'rest','startTime':'15:00'}}}).json['preview']
    assert not p['canApply'] and p['remainingConflicts']
    assert not writes and memory.retrieve('itineraries','flex')==trip


def test_single_day_assistance_preserves_other_days_and_rejects_stale_apply(client,planning):
    memory,writes=planning;trip=saved(memory,flight=False)
    trip['activities'].append({**trip['activities'][0],'activityId':'last-day','dayNo':5})
    memory.seed('itineraries','flex',trip)
    p=preview(client,{},action='improve',scope='day',dayNo=1).json['preview']
    assert next(row for row in p['after']['activities'] if row['activityId']=='last-day')==trip['activities'][-1]
    assert p['after']['dailySchedule'][-1]['activities']==[trip['activities'][-1]]
    memory.update('itineraries','flex',{'title':'Changed while preview open'})
    assert client.post(PATH+'/flight-adjustment/apply',headers=HEADERS,json={'previewId':p['previewId']}).status_code==409
    assert not writes


@pytest.mark.parametrize('mutation',[{'travellerId':'other-synthetic-owner'},{'packageTrip':True}])
def test_ownership_and_package_rules_cover_new_preferences(client,planning,mutation):
    memory,writes=planning;trip=saved(memory);memory.update('itineraries','flex',mutation)
    assert preview(client,{'planningMode':'manual'}).status_code==(404 if 'travellerId' in mutation else 409)
    assert not writes


def test_manual_activity_day3_edit_move_remove_and_preserve_other_work(client,planning):
    memory,writes=planning;trip=saved(memory,flight=False);trip['activities']=[]
    memory.seed('itineraries','flex',trip)
    payload={'activityName':'Chosen heritage place','destinationId':'local_street_art','dayNo':3,
             'openingHours':'08:00-20:00','recommendedDurationMinutes':60,'clientRequestId':'add-chosen-place'}
    added=client.post(PATH+'/activities',headers=HEADERS,json=payload)
    assert added.status_code==200,added.json
    activity=added.json['activities'][0];assert activity['dayNo']==3
    assert client.post(PATH+'/activities',headers=HEADERS,json=payload).json['alreadyAdded']
    edited=client.put(PATH+'/activities/'+activity['activityId'],headers=HEADERS,
        json={'timeSlot':'11:00','recommendedDurationMinutes':60,'notes':'Personal note','fixed':True})
    assert edited.status_code==200,edited.json
    fixed=edited.json['activities'][0];assert fixed['scheduledStartTime']=='11:00' and fixed['fixed']
    moved=client.put(PATH+'/activities/'+activity['activityId'],headers=HEADERS,json={'dayNo':2})
    assert moved.status_code==200,moved.json
    assert moved.json['activities'][0]['dayNo']==2 and moved.json['activities'][0]['notes']=='Personal note'
    assert client.delete(PATH+'/activities/'+activity['activityId'],headers=HEADERS).status_code==200
    assert memory.retrieve('itineraries','flex')['activities']==[]
    assert memory.retrieve('itineraries','flex')['hotelCost']==trip['hotelCost']


def test_explicitly_flexible_edit_honours_selected_time_before_later_proposals(client,planning):
    memory,writes=planning;saved(memory,flight=False)
    reply=client.put(PATH+'/activities/morning',headers=HEADERS,json={'timeSlot':'14:00','fixed':False})
    assert reply.status_code==200,reply.json
    row=next(row for row in reply.json['activities'] if row['activityId']=='morning')
    assert row['scheduledStartTime']=='14:00' and row['fixed'] is False and row['manualTime'] is False


def test_mode_only_switch_to_manual_preserves_exact_saved_activities(client,planning):
    memory,writes=planning;before=saved(memory)
    p=preview(client,{'planningMode':'manual'}).json['preview']
    assert p['canApply'] and p['after']['activities']==before['activities']
    assert not writes


def test_early_departure_bounds_the_previous_evening_too(client,planning):
    memory,writes=planning;trip=saved(memory)
    trip['selectedFlight']['returnSegments'][0]['departureTime']='02:00'
    memory.seed('itineraries','flex',trip)
    p=preview(client,{'travelDayPreferences':{'days':[{'dayNo':4,'startTime':'09:00','endTime':'23:00'}]}}).json['preview']
    assert p['availability']['days']['2027-12-15']['endMinutes']==22*60+30
    assert not p['canApply'] and '22:30' in p['reason'] and not writes


def test_overnight_arrival_closes_pre_arrival_day(client,planning):
    memory,writes=planning;trip=saved(memory)
    trip['selectedFlight']['outboundSegments'][0].update(departureDate='2027-12-12',arrivalDate='2027-12-13',arrivalTime='10:00')
    memory.seed('itineraries','flex',trip)
    p=preview(client,{'travelDayPreferences':{'arrival':{'choice':'rest','startTime':'15:00'}}}).json['preview']
    assert p['availability']['days']['2027-12-12']['availableMinutes']==0
    assert p['availability']['days']['2027-12-13']['startMinutes']==900
    assert not writes


@pytest.mark.parametrize('field,value',[('timeSlot','99:00'),('dayNo',False),('recommendedDurationMinutes',-1),
    ('estimatedCost',float('inf')),('fixed','true'),('notes',['bad']),('paymentId','fake-reference')])
def test_activity_edits_reject_invalid_times_prices_and_authorization_fields(client,planning,field,value):
    memory,writes=planning;trip=saved(memory,flight=False)
    response=client.put(PATH+'/activities/morning',headers=HEADERS,json={field:value})
    assert response.status_code in {400,409},response.json
    assert not writes and memory.retrieve('itineraries','flex')==trip


def test_paid_visit_cannot_be_removed_or_reordered_around_to_hide_conflicts(client,planning):
    memory,writes=planning;trip=saved(memory)
    trip['activities'][0]['paymentId']='synthetic-paid-reference'
    memory.seed('itineraries','flex',trip)
    assert client.delete(PATH+'/activities/morning',headers=HEADERS).status_code==409
    assert not writes


def test_regeneration_needs_owned_matching_saved_recommendation_evidence(client,planning):
    memory,writes=planning;saved(memory,flight=False)
    missing = preview(client,{},action='regenerate',scope='day',dayNo=2)
    assert missing.status_code == 409
    assert missing.json['code'] == 'RECOMMENDATION_NOT_FOUND'
    assert missing.json['nextAction'] == 'refresh_suggestions'
    memory.seed('recommendation_snapshots','saved-generation',{'travellerId':'another-owner','requestedDestination':'Penang','items':[]})
    assert preview(client,{},action='regenerate',recommendationGenerationId='saved-generation').status_code==409
    assert not writes


def test_regenerate_only_day2_preserves_fixed_visits_blocks_and_other_days(client,planning):
    memory,writes=planning;trip=saved(memory,flight=False)
    trip['activities'][0].update(fixed=True,dayNo=1)
    flexible={**deepcopy(trip['activities'][1]),'activityId':'replaceable','dayNo':2,'planningOrigin':'generated'}
    trip['activities']=[trip['activities'][0],flexible]
    trip['planningBlocks']=[{'blockId':'rest-existing-001','type':'rest','label':'My rest','dayNo':2,'startTime':'09:00','endTime':'10:00','estimatedCost':0}]
    memory.seed('itineraries','flex',trip)
    memory.seed('recommendation_snapshots','saved-generation',{'travellerId':trip['travellerId'],'requestedDestination':'Penang',
        'items':[{'id':'local_new','destinationId':'local_new','title':'Selected heritage museum','address':'George Town, Penang, Malaysia',
                  'state':'Penang','openingHours':'08:00-20:00','gps_coordinates':{'latitude':5.417,'longitude':100.338}}]})
    response=preview(client,{},action='regenerate',scope='day',dayNo=2,recommendationGenerationId='saved-generation')
    assert response.status_code==200,response.json
    p=response.json['preview'];assert p['canApply'],p
    assert p['after']['activities'][0]==trip['activities'][0]
    assert p['after']['planningBlocks']==trip['planningBlocks'] and not writes
    assert any(row['kind']=='removed' for row in p['changes'])
    assert any(row['activityName']=='Selected heritage museum' and row['dayNo']==2 for row in p['after']['activities'])
    assert client.post(PATH+'/flight-adjustment/apply',headers=HEADERS,json={'previewId':p['previewId']}).status_code==200
    saved_trip=memory.retrieve('itineraries','flex')
    assert saved_trip['recommendationGenerationId']=='saved-generation' and len(writes)==1


def test_later_replacement_keeps_preferences_but_requires_reconfirmation_when_infeasible(client,planning):
    memory,writes=planning;trip=saved(memory)
    trip['travelDayPreferences']={'arrival':{'choice':'rest','startTime':'15:00'}}
    trip['selectedFlight']['outboundSegments'][0]['arrivalTime']='13:00'
    memory.seed('itineraries','flex',trip)
    p=client.post(PATH+'/flight-adjustment/preview',headers=HEADERS).json['preview']
    assert not p['canApply'] and '16:00' in p['reason']
    assert memory.retrieve('itineraries','flex')['travelDayPreferences']['arrival']['startTime']=='15:00'
    assert not writes


def test_legacy_selected_visits_require_a_reviewed_regeneration(client,planning):
    memory,writes=planning;trip=saved(memory,flight=False)
    trip.pop('planningMode');trip['activities'][0]['planningOrigin']='user_selected'
    memory.seed('itineraries','flex',trip)
    assert client.post(PATH+'/generate',headers=HEADERS,json={}).status_code==409
    assert not writes and memory.retrieve('itineraries','flex')==trip


def test_flight_adjustment_keeps_day_costs_and_unpriced_personal_notes_consistent(client,planning):
    memory,writes=planning;trip=saved(memory)
    trip['planningBlocks']=[{'blockId':'meal-priced','type':'meal','label':'Meal','dayNo':2,'estimatedCost':25},
                            {'blockId':'rest-unpriced','type':'rest','label':'Rest','dayNo':3}]
    from sequence_contract.domain_functions import recalculateItinerary
    trip=recalculateItinerary(trip)
    memory.seed('itineraries','flex',trip)
    p=client.post(PATH+'/flight-adjustment/preview',headers=HEADERS).json['preview']
    assert p['canApply'],p['reason']
    assert p['after']['dailySchedule'][1]['knownEstimatedCost']>=25
    assert p['after']['dailySchedule'][2]['estimatedCost'] is None
    assert p['after']['dailySchedule'][2]['unpricedPersonalBlockCount']==1
    assert p['budgetAfter']['personalPlans']==25 and not writes


def test_legacy_personal_blocks_survive_explicit_opt_in_and_history(client,planning):
    memory,writes=planning;trip=saved(memory,flight=False)
    trip.pop('planningMode')
    trip['dailySchedule']=[{'dayNo':2,'planningBlocks':[
        {'type':'meal_rest','label':'Generated lunch','startTime':'12:00','endTime':'13:00'},
        {'type':'rest','label':'My saved rest','startTime':'10:00','endTime':'11:00','notes':'Keep this note'}]}]
    memory.seed('itineraries','flex',trip)
    read=client.get(PATH,headers=HEADERS).json
    assert 'planningBlocks' not in read['itinerary']
    blocks=read['planning']['personalBlocks']
    assert len(blocks)==1 and blocks[0]['label']=='My saved rest'
    p=preview(client,{'planningMode':'assisted'}).json['preview']
    assert p['canApply'] and p['after']['planningBlocks'][0]['notes']=='Keep this note'
    assert not writes
    assert client.post(PATH+'/flight-adjustment/apply',headers=HEADERS,json={'previewId':p['previewId']}).status_code==200
    reopened=client.get(PATH,headers=HEADERS).json['itinerary']
    assert reopened['planningBlocks'][0]['blockId']==blocks[0]['blockId']
    assert reopened['itineraryRevision']==2 and reopened['itineraryHistory']
    assert reopened['budgetEstimate']['expenseBreakdown']['personalPlans']['state']=='pending_unpriced'
    assert reopened['dailySchedule'][1]['unpricedPersonalBlockCount']==1
    assert reopened['dailySchedule'][1]['estimatedCost'] is None


def test_smart_creation_uses_real_generation_pipeline_and_owned_saved_evidence(client,planning,monkeypatch):
    memory,writes=planning
    candidate={'destinationId':'isolated_heritage','title':'Synthetic heritage attraction','address':'George Town, Penang, Malaysia',
               'state':'Penang','openingHours':'08:00-20:00','gps_coordinates':{'latitude':5.417,'longitude':100.338}}
    memory.seed('recommendation_snapshots','smart-owned-generation',{'travellerId':'test_traveller_uid',
        'recommendationGenerationId':'smart-owned-generation','requestedDestination':'Penang','recommendationResults':[candidate]})
    monkeypatch.setattr(r,'retrieveLocationAndTravelTime',lambda rows:[])
    payload={**basics('smart'),'recommendationGenerationId':'smart-owned-generation','travelDayPreferences':{}}
    first=client.post('/api/fr5/personalised-trips/generate',headers=HEADERS,json=payload)
    assert first.status_code==200,first.json
    trip=first.json['itinerary']
    assert trip['status']=='planned' and trip['planningMode']=='smart' and len(trip['dailySchedule'])==5
    assert trip['activities'][0]['destinationId']=='isolated_heritage'
    assert trip['activities'][0]['recommendationGenerationId']=='smart-owned-generation'
    assert client.post('/api/fr5/personalised-trips/generate',headers=HEADERS,json=payload).status_code==200
    assert len(memory.collections['itineraries'])==1


@pytest.mark.parametrize('boundary,allowed',[('personal',True),('destination',False)])
def test_origin_personal_notes_do_not_override_destination_flight_safety(client,planning,boundary,allowed):
    memory,writes=planning;saved(memory)
    block={'blockId':'personal-before-flight','type':'custom','label':'Personal travel note','boundary':boundary,
           'dayNo':1,'startTime':'07:00','endTime':'08:00'}
    p=preview(client,{'planningBlocks':[block]}).json['preview']
    assert p['canApply'] is allowed
    assert p['availability']['days']['2027-12-12']['earliestStartMinutes']==13*60
    assert p['after']['planningBlocks'][0]['estimatedCost'] is None
    assert 'personalPlans' in p['budgetAfter']['pendingExpenseCategories']
    assert not writes


def test_five_day_manual_flight_and_assisted_workflow_with_mocked_suppliers(client,planning,monkeypatch):
    from modules.fr07_flight_search import routes as flights
    from test_f2_flight_quotes import _leg
    memory,writes=planning
    created=client.post(BASE,headers=HEADERS,json=basics())
    assert created.status_code==201
    identity=created.json['id'];path=BASE+'/'+identity
    for day,name in enumerate(['George Town Street Art','Kek Lok Si Temple','Penang Hill'],1):
        response=client.post(path+'/activities',headers=HEADERS,json={'activityName':name,'dayNo':day,
            'destinationId':f'isolated_penang_{day}','openingHours':'08:00-20:00','recommendedDurationMinutes':60,
            'clientRequestId':f'five-day-add-{day}'})
        assert response.status_code==200,response.json
        assert next(row for row in response.json['activities'] if row['activityName']==name)['dayNo']==day
    flights.reset_flight_quotes()
    monkeypatch.setattr(flights,'retrieveRecord',memory.retrieve)
    monkeypatch.setattr(flights,'storeRecord',lambda c,data,doc:memory.seed(c,doc,data) or memory.retrieve(c,doc))
    monkeypatch.setattr(flights,'updateRecord',lambda c,doc,patch:memory.update(c,doc,history_patch(memory.retrieve(c,doc),patch)))
    monkeypatch.setattr(flights,'retrieveFlightOptions',lambda *a,**k:{'items':[{'flights':[
        _leg('SYN101','KUL','PEN','2027-12-12 09:00','2027-12-12 10:00')],
        'price':250,'currency':'MYR','departure_token':'isolated-provider-token'}]})
    monkeypatch.setattr(flights,'retrieveFlightReturns',lambda *a,**k:{'items':[{'flights':[
        _leg('SYN102','PEN','KUL','2027-12-16 20:00','2027-12-16 21:00')],'price':420,'currency':'MYR'}]})
    outbound=client.get('/api/fr7/flights/search?departure_id=KUL&arrival_id=PEN&outbound_date=2027-12-12&return_date=2027-12-16&traveller_count=2',headers=HEADERS).json
    assert outbound['ok'],outbound
    returns=client.post('/api/fr7/flights/returns',headers=HEADERS,json={'searchId':outbound['searchId'],'optionId':outbound['items'][0]['id']}).json
    assert returns['ok'],returns
    selected=client.post('/api/fr7/flights/select',headers=HEADERS,json={'itineraryId':identity,'searchId':outbound['searchId'],
        'optionId':outbound['items'][0]['id'],'returnOptionId':returns['items'][0]['id'],'acknowledgeConflicts':True})
    assert selected.status_code==200,selected.json
    assert selected.json['planningReviewRequired']
    prefs={'arrival':{'choice':'rest','startTime':'15:00'},'departure':{'choice':'light'}}
    blocks=[{'blockId':'five-day-rest','type':'rest','label':'Afternoon rest','dayNo':3,'startTime':'13:00','endTime':'14:00','estimatedCost':0},
            {'blockId':'five-day-meal','type':'meal','label':'Lunch','dayNo':2,'startTime':'12:00','endTime':'13:00','estimatedCost':25}]
    def propose(changes=None,**command):
        result=client.post(path+'/flight-adjustment/preview',headers=HEADERS,json={'planningChanges':changes or {},**command})
        assert result.status_code==200,result.json
        return result.json['preview']
    p=propose({'planningMode':'assisted','travelDayPreferences':prefs,'planningBlocks':blocks})
    assert p['canApply'],p['reason']
    assert client.post(path+'/flight-adjustment/apply',headers=HEADERS,json={'previewId':p['previewId']}).status_code==200
    trip=memory.retrieve('itineraries',identity)
    assert next(row for row in trip['activities'] if row['dayNo']==1)['scheduledStartTime']>='15:00'
    assert p['availability']['days']['2027-12-16']['endMinutes']<=16*60+30
    hill=next(row for row in trip['activities'] if row['dayNo']==3)
    edited=client.put(path+'/activities/'+hill['activityId'],headers=HEADERS,json={'dayNo':4,'timeSlot':'10:00','fixed':True})
    assert edited.status_code==200,edited.json
    before=deepcopy(memory.retrieve('itineraries',identity));write_count=len(writes)
    cancelled=propose(action='improve',scope='remaining',dayNo=2)
    assert cancelled['canApply'] and memory.retrieve('itineraries',identity)==before and len(writes)==write_count
    accepted=propose(action='improve',scope='remaining',dayNo=2)
    assert client.post(path+'/flight-adjustment/apply',headers=HEADERS,json={'previewId':accepted['previewId']}).status_code==200
    reopened=client.get(path,headers=HEADERS).json['itinerary']
    fixed=next(row for row in reopened['activities'] if row['activityId']==hill['activityId'])
    assert fixed['dayNo']==4 and fixed['scheduledStartTime']=='10:00' and fixed['fixed']
    assert len(reopened['planningBlocks'])==2 and reopened['budgetEstimate']['personalPlans']==25
    assert reopened['selectedFlight']==before['selectedFlight'] and reopened['flightCost']==before['flightCost']
    assert len(reopened['activities'])==3 and reopened['travelDayPreferences']['arrival']==prefs['arrival']
