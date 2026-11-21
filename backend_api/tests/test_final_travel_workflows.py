"""Owner-scoped real routes with synthetic records and blocked provider boundaries."""
from copy import deepcopy
import json
import pytest

from test_budget_provider_discovery import scenario,BASE,options,visit
from test_fr05_advisory_apply import HEADERS
from services.budget_provider_discovery import flight_comparison,DiscoveryError
from test_batch_f2_trip_integrity import owned,trip as personal_trip,visit as attraction,PATH as TRIP_PATH,AUTH

LABELS={1:'Economy',2:'Premium Economy',3:'Business',4:'First'}


def configure_cabin(memory,original,search,returns):
    trip=memory.retrieve('itineraries','trip');flight=deepcopy(trip['selectedFlight'])
    flight['requestedTravelClass']=original
    for leg in flight['outboundSegments']+flight['returnSegments']:leg['travelClass']=LABELS[original]
    memory.update('itineraries','trip',{'selectedFlight':flight})
    for provider in [search,returns]:
        response=deepcopy(provider.return_value)
        def respond(*args,_response=response,**kwargs):
            result=deepcopy(_response)
            for row in result['items']:
                for leg in row.get('outboundSegments',[])+row.get('returnSegments',[]):
                    leg['travelClass']=LABELS[kwargs['travelClass']]
            return result
        provider.side_effect=respond


def search(client,mode='same_cabin',target=None,intent='final-flight-search'):
    state=client.get('/api/fr5/itineraries/trip/budget-replan',headers=HEADERS).json['stateVersion']
    return client.post(BASE+'/discover',headers=HEADERS,json={'category':'flight','stateVersion':state,
        'providerSearchConfirmed':True,'searchRequestId':intent,'cabinComparison':mode,'comparisonCabin':target})


@pytest.mark.parametrize('original,target,mode',[(3,3,'same_cabin'),(3,2,'include_lower'),(3,1,'include_lower'),
    (2,1,'include_lower'),(1,1,'same_cabin'),(4,3,'include_lower')])
def test_explicit_cabin_comparison_preview_cancel_confirm_reopen(client,scenario,original,target,mode):
    memory,_,provider,returns,_,writes,_=scenario
    configure_cabin(memory,original,provider,returns)
    before=deepcopy(memory.retrieve('itineraries','trip'))
    result=search(client,mode,target)
    assert result.status_code==200,result.json
    assert result.json['search']['requestsAttempted']==2 and result.json['search']['providerReached']
    assert result.json['search']['comparison']['comparisonCabin']==target
    assert provider.call_args.kwargs['travelClass']==returns.call_args.kwargs['travelClass']==target
    body=client.post(BASE,headers=HEADERS,json={'cabinComparison':mode,'comparisonCabin':target}).json
    option=next(row for row in body['alternatives'] if row['alternativeType']=='flight')
    assert option['data']['cabin']['cabinDowngrade']==(target<original)
    assert option['data']['cabinComparison']==mode
    assert option['estimatedSavings']==180 and option['replacementEstimatedCost']==420
    assert client.post(BASE+'/preview',headers=HEADERS,json={'alternative':option}).status_code==200
    assert not writes and memory.retrieve('itineraries','trip')==before
    applied=client.post(BASE+'/apply',headers=HEADERS,json={'alternative':option})
    assert applied.status_code==200,applied.json
    saved=client.get('/api/fr5/itineraries/trip',headers=HEADERS).json['itinerary']
    assert saved['selectedFlight']['requestedTravelClass']==target and saved['flightCost']==420
    assert saved['selectedFlight']['returnSegments']
    repeated=client.post(BASE+'/apply',headers=HEADERS,json={'alternative':option})
    assert repeated.status_code==409 and len(writes)==1
    print('FINAL_TRAVEL_COMPARISON_EVIDENCE='+json.dumps({'synthetic':True,'kind':'flight',
        'originalCabin':original,'proposedCabin':target,'originalMYR':600,'proposedMYR':saved['flightCost'],
        'savingsMYR':option['estimatedSavings'],'providerAttempts':result.json['search']['requestsAttempted'],
        'savedBudgetMYR':saved['budgetEstimate']['total'],'cancelUnchanged':True,'duplicateWrites':0}))


@pytest.mark.parametrize('fare',[560,661])
def test_reported_fare_shape_compares_complete_return_total(client,scenario,fare):
    memory,_,provider,returns,_,writes,_=scenario
    flight=memory.retrieve('itineraries','trip')['selectedFlight'];flight['price']=934
    memory.update('itineraries','trip',{'selectedFlight':flight,'flightCost':934})
    returns.return_value['items'][0]['price']=fare
    configure_cabin(memory,3,provider,returns)
    assert search(client,'include_lower',1).status_code==200
    body=client.post(BASE,headers=HEADERS,json={'cabinComparison':'include_lower','comparisonCabin':1}).json
    option=next(row for row in body['alternatives'] if row['alternativeType']=='flight')
    assert option['replacementEstimatedCost']==fare and option['estimatedSavings']==934-fare
    assert client.post(BASE+'/preview',headers=HEADERS,json={'alternative':option}).status_code==200
    assert not writes
    print('FINAL_TRAVEL_COMPARISON_EVIDENCE='+json.dumps({'synthetic':True,'kind':'reported_fare_shape',
      'originalMYR':934,'proposedMYR':fare,'savingsMYR':934-fare,'previewOnly':True}))


@pytest.mark.parametrize('target,mode',[(1,'same_cabin'),(4,'include_lower'),(True,'include_lower'),('1','include_lower'),(0,'include_lower'),(1,'silent'),(1,[])])
def test_client_cannot_override_cabin_relationship(client,scenario,target,mode):
    memory,_,provider,returns,_,writes,_=scenario
    configure_cabin(memory,3,provider,returns)
    reply=search(client,mode,target)
    assert reply.status_code==409 and not reply.json['providerReached']
    assert reply.json['eligibility']['reasonCode']=='invalid_cabin_comparison'
    provider.assert_not_called();returns.assert_not_called();assert not writes


@pytest.mark.parametrize('mode',['missing','conflicting_return'])
def test_missing_or_conflicting_cabin_evidence_is_not_assumed_economy(client,scenario,mode):
    memory,_,provider,returns,_,writes,_=scenario
    flight=memory.retrieve('itineraries','trip')['selectedFlight']
    if mode=='missing':
        flight.pop('requestedTravelClass')
        for leg in flight['outboundSegments']+flight['returnSegments']:leg.pop('travelClass')
    else:flight['returnSegments'][0]['travelClass']='Business'
    memory.update('itineraries','trip',{'selectedFlight':flight})
    assert search(client).status_code==409
    provider.assert_not_called();returns.assert_not_called();assert not writes


def test_comparison_mode_changes_do_not_reuse_same_search_or_replay_an_intent(client,scenario):
    memory,_,provider,returns,*_=scenario
    configure_cabin(memory,3,provider,returns)
    assert search(client).status_code==200
    assert search(client).json['search']['reused'] and provider.call_count==1
    assert search(client,'include_lower',1).status_code==409 #same intent cannot change its meaning
    assert search(client,'include_lower',1,'new-cabin-search').status_code==200
    assert provider.call_count==returns.call_count==2
    same=client.post(BASE,headers=HEADERS).json
    assert all(row['data']['cabin']['comparisonCabin']==3 for row in same['alternatives'] if row['alternativeType']=='flight')


@pytest.mark.parametrize('fault,code', [('missing','missing_quote'),('expired','expired_quote'),
    ('currency','protected_or_currency_mismatch'),('rooms','occupancy_mismatch'),('amount','amount_mismatch')])
def test_hotel_eligibility_reasons_before_provider(client,scenario,fault,code):
    memory,trip,_,_,provider,writes,_=scenario
    if fault=='missing':memory.update('itineraries','trip',{'hotelBookingId':None,'hotelOfferQuoteId':None})
    if fault=='expired':memory.update('hotel_bookings','original',{'acceptedPrebookSnapshot':{'expiresAt':'2020-01-01T00:00:00+00:00'}})
    if fault=='currency':memory.update('itineraries','trip',{'hotelCurrency':'USD'})
    if fault=='rooms':
        booking=memory.retrieve('hotel_bookings','original')
        memory.update('hotel_bookings','original',{'stayCriteria':{**booking['stayCriteria'],'roomQuantity':2}})
    if fault=='amount':memory.update('hotel_bookings','original',{'hotelCost':500})
    state=client.get('/api/fr5/itineraries/trip/budget-replan',headers=HEADERS).json
    assert state['hotelComparison']['reasonCode']==code
    response=client.post(BASE+'/discover',headers=HEADERS,json={'category':'hotel','providerSearchConfirmed':True,
        'stateVersion':state['stateVersion'],'searchRequestId':'hotel-rejected-intent'})
    assert response.status_code==409 and response.json['eligibility']['reasonCode']==code
    assert response.json['eligibility']['reasons'] and response.json['providerReached'] is False
    provider.assert_not_called();assert not writes


def test_provider_hotel_diagnostics_distinguish_rejected_rates(client,scenario):
    from test_budget_provider_discovery import discover
    _,_,_,_,provider,_,rate=scenario
    provider.return_value={'items':[{**rate,'currency':'USD'},{**rate,'taxesAndFeesStatus':'unknown'},rate]}
    result=discover(client,'hotel').json['search']
    assert result['providerReached'] and result['candidateCount']==3
    assert result['validQuoteCount']==1 and result['rejectedCount']==2
    assert result['rejectionCounts']=={'currency':1,'incomplete_price_or_charges':1}


def test_expired_hotel_recovery_preserves_known_dates_and_two_rooms(client,scenario):
    memory,_,_,_,provider,_,_=scenario
    criteria=memory.retrieve('hotel_bookings','original')['stayCriteria']
    criteria.update(checkin='2027-02-11',roomQuantity=2,occupancies=[{'adults':1},{'adults':1}])
    memory.update('hotel_bookings','original',{'stayCriteria':criteria,
        'acceptedPrebookSnapshot':{'expiresAt':'2020-01-01T00:00:00+00:00'}})
    result=client.get('/api/fr5/itineraries/trip/budget-replan',headers=HEADERS).json['hotelComparison']
    assert result['reasonCode']=='expired_quote'
    assert result['searchCriteria']['checkin']=='2027-02-11' and result['searchCriteria']['roomQuantity']==2
    assert result['searchCriteria']['occupancies']==[{'adults':1},{'adults':1}]
    provider.assert_not_called()


def test_feasible_flight_adjustment_is_visible_and_atomic(client,scenario):
    from test_budget_provider_discovery import discover
    memory,_,_,_,_,writes,_=scenario
    row=visit();row.update(scheduledStartTime='08:00',scheduledEndTime='09:00')
    memory.update('itineraries','trip',{'activities':[row],'dailySchedule':[{'dayNo':1,'dayDate':'2027-02-10','activities':[deepcopy(row)]}]})
    assert discover(client,'flight').status_code==200
    option=options(client,'flight')[0]
    assert option['comparisonStatus']=='requires_schedule_adjustment'
    assert option['data']['itineraryChanges']
    before=deepcopy(memory.retrieve('itineraries','trip'))
    preview=client.post(BASE+'/preview',headers=HEADERS,json={'alternative':option})
    assert preview.status_code==200 and not writes and memory.retrieve('itineraries','trip')==before
    assert client.post(BASE+'/apply',headers=HEADERS,json={'alternative':option}).status_code==200
    saved=memory.retrieve('itineraries','trip')
    assert saved['flightCost']==420 and saved['activities'][0]['scheduledStartTime']!='08:00'
    assert saved['dailySchedule'][0]['activities'][0]['activityId']==saved['activities'][0]['activityId']


def test_attraction_day3_survives_reopen_and_repeated_send(client,mock_traveller_auth,owned):
    state,updater=owned
    state['f2']=personal_trip(5)
    payload={k:v for k,v in attraction(day=3).items() if k!='activityId'}
    payload['clientRequestId']='final-add-day-three'
    response=client.post(TRIP_PATH+'/activities',headers=AUTH,json=payload)
    assert response.status_code==200,response.json
    saved=client.get(TRIP_PATH,headers=AUTH).json['itinerary']
    assert saved['activities'][0]['dayNo']==3
    assert saved['dailySchedule'][2]['activities'][0]['activityId']==saved['activities'][0]['activityId']
    assert client.post(TRIP_PATH+'/activities',headers=AUTH,json=payload).json['alreadyAdded']
    assert updater.call_count==1


@pytest.mark.parametrize('day',[0,6,True,1.5,None])
def test_invalid_target_day_never_writes(client,mock_traveller_auth,owned,day):
    state,updater=owned;state['f2']=personal_trip(5)
    assert client.post(TRIP_PATH+'/activities',headers=AUTH,json={**attraction(),'dayNo':day}).status_code==400
    updater.assert_not_called()


@pytest.mark.parametrize('mutation',[{'tripType':'package'},{'packageTrip':True},{'travellerId':'unrelated-owner'}])
def test_package_and_foreign_trip_never_accept_attractions(client,mock_traveller_auth,owned,mutation):
    state,updater=owned;state['f2']=personal_trip(5,**mutation)
    response=client.post(TRIP_PATH+'/activities',headers=AUTH,json=attraction(day=3))
    assert response.status_code==(404 if 'travellerId' in mutation else 409)
    updater.assert_not_called()
