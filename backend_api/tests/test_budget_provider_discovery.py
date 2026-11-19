"""Only synthetic accounts, mock provider responses and in-memory persistence."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
import pytest
from test_fr08_fr09_hotels_payments import MemoryPersistence
from test_fr05_advisory_apply import HEADERS
from test_f2_flight_quotes import _outbound, _return
from test_batch18b_hotel_integrity import _normalised_offer
from services.liteapi_service import normalizeHotelOffers as real_normalize_hotels
from services.serpapi_service import normalizeFlightResult
from modules.fr05_smart_itinerary_budget_planner import routes as r
from modules.fr07_flight_search import routes as fr7
from modules.fr08_hotel_booking import routes as fr8
from services import budget_provider_discovery as discovery

BASE='/api/fr5/itineraries/trip/lower-cost-alternatives'

@pytest.fixture
def scenario(monkeypatch, mock_traveller_auth):
    memory=MemoryPersistence()
    outbound=normalizeFlightResult(_outbound(price=600),traveller_count=2)
    inbound=normalizeFlightResult(_return(price=600),traveller_count=2)
    outbound.update(price=600,requestedTravelClass=1,returnSegments=inbound['outboundSegments'],
                    priceBasis='provider_round_trip_ticket_price_requested_adults',planningOnly=True)
    for row in outbound['outboundSegments']+outbound['returnSegments']:row['travelClass']='Economy'
    criteria={'destination':'Penang','checkin':'2027-02-10','checkout':'2027-02-12','adults':2,'children':0,
              'guestCount':2,'roomQuantity':1,'occupancies':[{'adults':2}],'currency':'MYR','guestNationality':'MY'}
    hotel=_normalised_offer(criteria['occupancies'])
    hotel.update(price=400,address='George Town, Penang, Malaysia',name='Original Hotel',planningOnly=True)
    trip={'id':'trip','travellerId':'test_traveller_uid','title':'Synthetic budget trip','destinationArea':'Penang',
          'startDate':'2027-02-10','endDate':'2027-02-12','travellerCount':2,'budgetLimit':1000,
          'foodCost':360,'transportCost':105,'selectedFlight':outbound,'flightCost':600,'flightCurrency':'MYR',
          'flightPriceBasis':outbound['priceBasis'],'travelMode':'flight','selectedHotel':hotel,
          'hotelBookingId':'original','hotelCost':400,'hotelCurrency':'MYR','accommodationChoice':'paid_hotel',
          'activities':[]}
    memory.seed('itineraries','trip',trip)
    memory.seed('hotel_bookings','original',{'travellerId':trip['travellerId'],'saveDetailsOnly':True,
      'itineraryId':'trip','bookingStatus':'confirmed','amountSource':'validated_offer','hotelCost':400,
      'hotelCurrency':'MYR','stayCriteria':criteria,'selectedHotel':hotel})
    for module in (r,fr7,fr8,discovery):
        for name,method in [('retrieveRecord',memory.retrieve),('claimRecord',memory.claim),
                            ('storeRecord',lambda c,i,d=None:None),('updateRecord',memory.update)]:
            if hasattr(module,name):monkeypatch.setattr(module,name,method)
    monkeypatch.setattr(fr7,'storeRecord',lambda c,row,identity:memory.seed(c,identity,deepcopy(row)) or deepcopy(row))
    writes=[]
    def commit(identity,expected,patch):
        current=memory.retrieve('itineraries',identity)
        if r._alternative_state(current)!=r._alternative_state(expected):raise r._AlternativeConflict('stale')
        writes.append(deepcopy(patch));return memory.update('itineraries',identity,patch)
    monkeypatch.setattr(r,'_commit_cost_alternative',commit)
    fr7.reset_flight_quotes()
    search=Mock(return_value={'items':[normalizeFlightResult(_outbound(price=1),traveller_count=2)]})
    returns=Mock(return_value={'items':[normalizeFlightResult(_return(price=420),traveller_count=2)]})
    hotel_provider=Mock(return_value={'data':[]})
    rate=_normalised_offer(criteria['occupancies']);rate.update(price=250,name='Cheaper Hotel',
          address='George Town, Penang, Malaysia',roomName='Twin room',offerId='cheaper')
    monkeypatch.setattr('services.serpapi_service.retrieveFlightOptions',search)
    monkeypatch.setattr('services.serpapi_service.retrieveFlightReturns',returns)
    monkeypatch.setattr('services.liteapi_service.retrieveHotelOffers',hotel_provider)
    monkeypatch.setattr('services.liteapi_service.normalizeHotelOffers',lambda result:deepcopy(result.get('items',[rate])))
    monkeypatch.setattr('services.liteapi_service.validateHotelOffer',Mock(side_effect=AssertionError('No prebooking')))
    monkeypatch.setattr('services.liteapi_service.createBookingReference',Mock(side_effect=AssertionError('No booking')))
    return memory,trip,search,returns,hotel_provider,writes,rate


def discover(client,category):
    state=client.get('/api/fr5/itineraries/trip/budget-replan',headers=HEADERS).json['stateVersion']
    return client.post(BASE+'/discover',headers=HEADERS,json={'category':category,'stateVersion':state,'providerSearchConfirmed':True,'searchRequestId':'search-intent-'+state[:12]})


def options(client,kind):
    response=client.post(BASE,headers=HEADERS)
    assert response.status_code==200,response.json
    return [row for row in response.json['alternatives'] if row['alternativeType']==kind]


def test_round_trip_discovery_is_explicit_complete_deduplicated_and_cancel_is_read_only(client,scenario):
    memory,trip,search,returns,_,writes,_=scenario
    before=deepcopy(memory.retrieve('itineraries','trip'))
    assert options(client,'flight')==[]
    search.assert_not_called()
    result=discover(client,'flight')
    assert result.status_code==200 and result.json['search']['requestsAttempted']==2
    assert discover(client,'flight').json['search']['reused']
    assert search.call_count==returns.call_count==1
    assert search.call_args.args==('KUL','PEN','2027-02-10','2027-02-12')
    assert search.call_args.kwargs['adults']==2 and search.call_args.kwargs['travelClass']==1
    offer=options(client,'flight')[0]
    assert offer['replacementEstimatedCost']==420 and offer['estimatedSavings']==180
    preview=client.post(BASE+'/preview',headers=HEADERS,json={'alternative':offer})
    assert preview.status_code==200 and preview.json['budget']['flight']==420
    assert not writes and memory.retrieve('itineraries','trip')==before


def test_flight_hotel_and_allowance_combination_reloads_without_double_counting(client,scenario,monkeypatch):
    memory,trip,_,_,_,writes,_=scenario
    assert discover(client,'flight').json['search']['status']=='completed'
    offer=options(client,'flight')[0]
    assert client.post(BASE+'/apply',headers=HEADERS,json={'alternative':offer}).status_code==200
    assert discover(client,'hotel').json['search']['status']=='completed'
    hotel=options(client,'hotel')[0]
    assert hotel['replacementEstimatedCost']==250 and hotel['estimatedSavings']==150
    original=deepcopy(memory.retrieve('hotel_bookings','original'))
    preview=client.post(BASE+'/preview',headers=HEADERS,json={'alternative':hotel})
    assert preview.status_code==200 and preview.json['budget']['hotel']==250
    assert len(writes)==1
    assert client.post(BASE+'/apply',headers=HEADERS,json={'alternative':hotel}).status_code==200
    current=memory.retrieve('itineraries','trip')
    assert current['hotelBookingId'] is None and current['hotelOfferQuoteId']
    assert current['selectedHotel']['planningOnly'] is True
    assert memory.retrieve('hotel_bookings','original')==original
    # Existing replan route is authoritative for independent combinations.
    monkeypatch.setattr(r,'updateRecord',lambda c,i,patch,expected=None:memory.update(c,i,patch))
    path='/api/fr5/itineraries/trip/budget-replan'
    state=client.get(path,headers=HEADERS).json['stateVersion']
    command={'changes':{'foodCost':324,'transportCost':94.5},'stateVersion':state}
    preview=client.post(path+'/preview',headers=HEADERS,json=command).json
    assert preview['budget']['total']==1088.5 #420+250+324+94.5, not original1465.
    command.update(confirmed=True,previewToken=preview['previewToken'])
    assert client.post(path+'/apply',headers=HEADERS,json=command).status_code==200
    saved=client.get('/api/fr5/itineraries/trip',headers=HEADERS).json['itinerary']
    assert saved['budgetEstimate']['total']==1088.5 and saved['budgetEstimate']['overBy']==88.5
    assert saved['selectedFlight']['returnSegments']
    assert discover(client,'hotel').json['search']['status']=='completed' #quote-only baseline remains usable.


@pytest.mark.parametrize('category',['flight','hotel'])
def test_provider_timeout_retains_local_options_and_does_not_replay(client,scenario,category):
    memory,trip,flight,returns,hotel,_,_=scenario
    provider=flight if category=='flight' else hotel
    provider.side_effect=TimeoutError('sanitized')
    reply=discover(client,category)
    assert reply.status_code==200 and reply.json['search']['status']=='unavailable'
    assert reply.json['search']['requestsAttempted']==1
    assert discover(client,category).json['search']['reused']
    assert provider.call_count==1
    assert {row['category'] for row in client.get('/api/fr5/itineraries/trip/budget-replan',headers=HEADERS).json['planningAlternatives']}=={'Food','Local transport'}


def test_no_cheaper_or_incomplete_roundtrip_is_not_offered(client,scenario):
    _,_,_,returns,_,_,_=scenario
    returns.return_value={'items':[]}
    assert discover(client,'flight').json['search']['status']=='completed'
    assert options(client,'flight')==[]


@pytest.mark.parametrize('field,value',[('price',700),('currency','USD'),('taxesAndFeesStatus','unknown'),
    ('priceBasis','room_total'),('roomQuantity',2),('address','Kuching, Sarawak')])
def test_incomparable_hotels_are_not_presented_as_savings(client,scenario,field,value):
    _,_,_,_,provider,_,rate=scenario
    rate[field]=value;provider.return_value={'items':[rate]}
    assert discover(client,'hotel').status_code==200
    assert options(client,'hotel')==[]


@pytest.mark.parametrize('protected',['paid','pending','supplier'])
def test_hotel_commercial_protection_blocks_provider_call(client,scenario,protected):
    memory,_,_,_,provider,_,_=scenario
    if protected=='paid':memory.update('hotel_bookings','original',{'bookingStatus':'paid'})
    if protected=='pending':memory.seed('checkout_orders','pending',{'travellerId':'test_traveller_uid','hotelBookingId':'original','status':'checkout_pending'})
    if protected=='supplier':memory.update('hotel_bookings','original',{'providerMutationCalled':True})
    assert discover(client,'hotel').status_code==409
    provider.assert_not_called()


def test_search_requires_confirmation_current_state_and_ownership(client,scenario):
    memory,_,provider,_,_,_,_=scenario
    assert client.post(BASE+'/discover',headers=HEADERS,json={'category':'flight'}).status_code==400
    assert client.post(BASE+'/discover',headers=HEADERS,json={'category':'flight','stateVersion':'stale','providerSearchConfirmed':True,'searchRequestId':'search-stale-intent'}).status_code==409
    memory.update('itineraries','trip',{'travellerId':'another-synthetic-owner'})
    assert client.post(BASE+'/discover',headers=HEADERS,json={'category':'flight','stateVersion':'stale','providerSearchConfirmed':True,'searchRequestId':'search-stale-intent'}).status_code==404
    provider.assert_not_called()


def test_expired_quote_and_changed_trip_reject_apply(client,scenario):
    memory,_,_,_,_,writes,_=scenario
    discover(client,'hotel')
    offer=options(client,'hotel')[0]
    memory.update('itineraries','trip',{'foodCost':999})
    assert client.post(BASE+'/apply',headers=HEADERS,json={'alternative':offer}).status_code==409
    memory.update('itineraries','trip',{'foodCost':360})
    for key,row in memory.collections.get('hotel_offer_quotes',{}).items():row['expiresAt']='2000-01-01T00:00:00+00:00'
    assert client.post(BASE+'/preview',headers=HEADERS,json={'alternative':offer}).status_code==409
    assert not writes


def test_per_account_hourly_quota_is_not_reset_by_changing_trip(client,scenario):
    memory,_,provider,_,_,_,_=scenario
    for amount in [360,361,362]:
        memory.update('itineraries','trip',{'foodCost':amount})
        reply=discover(client,'flight')
    assert reply.json['search']['status']=='quota_limited' and provider.call_count==2



@pytest.mark.parametrize('price',[600,900])
def test_complete_but_not_cheaper_flight_is_not_advertised(client,scenario,price):
    scenario[3].return_value={'items':[normalizeFlightResult(_return(price=price),traveller_count=2)]}
    assert discover(client,'flight').json['search']['status']=='completed'
    assert options(client,'flight')==[]


def test_one_way_uses_one_request_and_no_invented_return(client,scenario):
    memory,trip,search,returns,_,_,_=scenario
    selected=deepcopy(trip['selectedFlight'])
    selected['returnSegments']=[]
    selected['priceBasis']=normalizeFlightResult(_outbound(),traveller_count=2)['priceBasis']
    memory.update('itineraries','trip',{'selectedFlight':selected,'flightPriceBasis':selected['priceBasis']})
    search.return_value={'items':[normalizeFlightResult(_outbound(price=250),traveller_count=2)]}
    reply=discover(client,'flight')
    assert reply.json['search']['requestsAttempted']==1 and search.call_args.args[3] is None
    returns.assert_not_called()
    offer=options(client,'flight')[0]
    assert offer['replacementEstimatedCost']==250 and offer['data']['returnSegments']==[]


def visit(protected=False):
    return {'activityId':'visit','activityName':'Original visit','destinationId':'local_street_art',
            'dayNo':1,'dayDate':'2027-02-10','scheduledStartTime':'09:00','scheduledEndTime':'10:00',
            'timeSlot':'09:00','recommendedDurationMinutes':60,'openingHours':'08:00-18:00',
            'estimatedCost':30,'unitPrice':30,'pricingUnit':'per_group','costProvenance':'user_entered',
            'gps_coordinates':{'latitude':5.414,'longitude':100.328},**({'paymentId':'protected'} if protected else {})}


@pytest.mark.parametrize('protected',[False,True])
def test_cheaper_flight_requires_safe_schedule_and_explicit_confirmation(client,scenario,protected):
    memory,trip,_,_,_,writes,_=scenario
    activity=visit(protected)
    memory.update('itineraries','trip',{'activities':[activity],
        'dailySchedule':[{'dayNo':1,'dayDate':'2027-02-10','activities':[deepcopy(activity)]}]})
    before=deepcopy(memory.retrieve('itineraries','trip'))
    assert discover(client,'flight').json['search']['status']=='completed'
    offers=options(client,'flight')
    if protected:
        assert not offers and memory.retrieve('itineraries','trip')==before
        assert not writes
    else:
        offer=offers[0]
        preview=client.post(BASE+'/preview',headers=HEADERS,json={'alternative':offer})
        assert preview.status_code==200 and preview.json['itineraryChanges'][0]['kind']=='moved'
        assert preview.json['dailySchedule'][0]['activities'][0]['scheduledStartTime']>='13:10'
        assert memory.retrieve('itineraries','trip')==before and not writes
        accepted=client.post(BASE+'/apply',headers=HEADERS,json={'alternative':offer})
        assert accepted.status_code==200
        saved=client.get('/api/fr5/itineraries/trip',headers=HEADERS).json['itinerary']
        assert saved['dailySchedule'][0]['activities']==saved['activities']
        assert saved['activities'][0]['scheduledStartTime']>='13:10' and saved['flightCost']==420
        assert client.post(BASE+'/apply',headers=HEADERS,json={'alternative':offer}).status_code==409
        assert len(writes)==1


def test_impossible_reported_same_day_flight_is_never_an_applicable_saving(client,scenario):
    memory,trip,search,returns,_,writes,_=scenario
    outbound=normalizeFlightResult(_outbound(price=1),traveller_count=2)
    outbound['outboundSegments'][0]['arrivalTime']='11:50'
    returned=normalizeFlightResult(_return(price=420),traveller_count=2)
    returned['outboundSegments'][0].update(departureDate='2027-02-10',arrivalDate='2027-02-10',departureTime='12:35')
    selected={**deepcopy(trip['selectedFlight']),'returnSegments':deepcopy(returned['outboundSegments'])}
    memory.update('itineraries','trip',{'endDate':'2027-02-10','selectedFlight':selected,'activities':[visit()]})
    search.return_value={'items':[outbound]};returns.return_value={'items':[returned]}
    discover(client,'flight')
    assert options(client,'flight')==[] and not writes


def test_expired_flight_offer_cannot_be_confirmed(client,scenario):
    memory,_,_,_,_,writes,_=scenario
    discover(client,'flight');offer=options(client,'flight')[0]
    fr7._FLIGHT_QUOTES[offer['data']['searchId']]['expiresAt']='2000-01-01T00:00:00+00:00'
    assert client.post(BASE+'/apply',headers=HEADERS,json={'alternative':offer}).status_code==409
    assert not writes


@pytest.mark.parametrize('kind',['flight','hotel'])
def test_empty_provider_inventory_stays_empty(client,scenario,kind):
    provider=scenario[2] if kind=='flight' else scenario[4]
    provider.return_value={'items':[]}
    assert discover(client,kind).json['search']['status']=='completed'
    assert options(client,kind)==[]


def test_duplicate_inflight_search_returns_pending_without_another_call(scenario):
    memory,trip,_,_,_,_,_=scenario
    attempts=[]
    def outer(invoke):
        replay=discovery.run_search(trip['travellerId'],trip,'flight','same',lambda _:pytest.fail('Duplicate provider request'))
        assert replay['status']=='pending' and replay['reused']
        invoke(lambda:attempts.append(1))
        return []
    result=discovery.run_search(trip['travellerId'],trip,'flight','same',outer)
    assert result['status']=='completed' and attempts==[1]


def test_hard_provider_cap_cannot_be_exceeded(scenario):
    trip=scenario[1];calls=[]
    def search(invoke):
        for _ in range(5):invoke(lambda:calls.append(1))
        return []
    result=discovery.run_search(trip['travellerId'],trip,'flight','bounded',search)
    assert result['status']=='unavailable' and result['requestsAttempted']==2 and calls==[1,1]


def test_rate_limit_error_consumes_reservation_without_automatic_retry(client,scenario):
    from requests import HTTPError
    provider=scenario[4];provider.side_effect=HTTPError('Provider quota')
    assert discover(client,'hotel').json['search']['status']=='unavailable'
    discover(client,'hotel')
    assert provider.call_count==1



def test_intent_replay_survives_ten_minute_bucket_change(scenario,monkeypatch):
    memory,trip,_,_,_,_,_=scenario
    from datetime import datetime as real_datetime
    class Clock:
        value=real_datetime(2027,2,1,10,9,tzinfo=timezone.utc)
        @classmethod
        def now(cls,*_):return cls.value
    monkeypatch.setattr(discovery,'datetime',Clock)
    calls=[]
    def search(invoke):
        invoke(lambda:calls.append(1));return []
    first=discovery.run_search(trip['travellerId'],trip,'flight','current',search,request_id='stable-intent')
    Clock.value=real_datetime(2027,2,1,10,11,tzinfo=timezone.utc)
    replay=discovery.run_search(trip['travellerId'],trip,'flight','current',search,request_id='stable-intent')
    assert first['status']=='completed' and replay['reused'] and calls==[1]
    with pytest.raises(discovery.DiscoveryError,match='another trip revision'):
        discovery.run_search(trip['travellerId'],trip,'flight','changed',search,request_id='stable-intent')


def test_real_liteapi_normalizer_uses_offer_total_including_taxes(client,scenario,monkeypatch):
    provider=scenario[4]
    monkeypatch.setattr('services.liteapi_service.normalizeHotelOffers',real_normalize_hotels)
    provider.return_value={'hotels':[{'id':'actual-normalizer-hotel','name':'Provider Rate Hotel','address':'George Town, Penang, Malaysia'}],
      'data':[{'hotelId':'actual-normalizer-hotel','roomTypes':[{
        'offerId':'normalized-offer','roomName':'Twin room','offerRetailRate':{'amount':275,'currency':'MYR'},
        'rates':[{'adultCount':2,'childCount':0,'childrenAges':[],'maxOccupancy':2,
                  'retailRate':{'total':[{'amount':275}],'currency':'MYR','taxesAndFees':[{'included':True}]}}]}]}]}
    result=discover(client,'hotel')
    assert result.json['search']['requestsAttempted']==1
    selected=options(client,'hotel')[0]
    assert selected['replacementEstimatedCost']==275 and selected['estimatedSavings']==125
    request=provider.call_args.args[0]
    assert request['limit']==10 and request['maxRatesPerHotel']==2 and request['occupancies']==[{'adults':2}]


def test_stale_discovery_response_never_bypasses_apply_guard(client,scenario):
    memory,_,search,_,_,writes,_=scenario
    original=search.return_value
    def changed(*args,**kwargs):
        memory.update('itineraries','trip',{'travellerCount':3})
        return original
    search.side_effect=changed
    assert discover(client,'flight').status_code==200
    assert options(client,'flight')==[] and not writes



def test_nightly_room_rate_is_compared_as_complete_stay_total(client,scenario):
    provider=scenario[4];rate=scenario[6]
    rate.update(price=125,priceBasis='per_room_night')
    provider.return_value={'items':[rate]}
    assert discover(client,'hotel').json['search']['status']=='completed'
    offer=options(client,'hotel')[0]
    assert offer['replacementEstimatedCost']==250 and offer['estimatedSavings']==150
    assert offer['data']['selectedHotel']['priceBasis']=='stay_total'


def test_mismatched_child_occupancy_is_rejected_without_rate_invention(client,scenario):
    provider=scenario[4];rate=scenario[6]
    rate['occupancyBreakdown'][0].update(adultCount=1,childrenAges=[7])
    provider.return_value={'items':[rate]}
    discover(client,'hotel')
    assert options(client,'hotel')==[]


def test_cheaper_flight_must_not_drop_visits_to_manufacture_a_feasible_saving(client,scenario):
    memory,_,_,_,_,writes,_=scenario
    first=visit()
    second={**visit(),'activityId':'long-visit','destinationId':'other-venue',
            'activityName':'Long planned visit','scheduledStartTime':'10:30','scheduledEndTime':'17:30',
            'recommendedDurationMinutes':600}
    memory.update('itineraries','trip',{'activities':[first,second],
        'dailySchedule':[{'dayNo':1,'dayDate':'2027-02-10','activities':[deepcopy(first),deepcopy(second)]}]})
    discover(client,'flight')
    assert options(client,'flight')==[] and not writes
