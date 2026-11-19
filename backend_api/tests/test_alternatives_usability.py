
"""Source-proven usability regressions; no production reads or provider calls."""
from copy import deepcopy
from datetime import datetime, timezone
import pytest
from test_budget_provider_discovery import scenario, discover, options, BASE, HEADERS
from services import budget_provider_discovery as discovery


def test_zero_provider_attempts_do_not_exhaust_search_quota(scenario):
    memory,trip,_,_,_,_,_=scenario
    def invalid(_):
        raise discovery.DiscoveryError('Missing local comparison data')
    for n in range(7):
        result=discovery.run_search(trip['travellerId'],trip,'flight','invalid-'+str(n),invalid)
        assert result['requestsAttempted']==0
    assert not memory.collections.get('budget_alternative_search_quota')
    calls=[]
    result=discovery.run_search(trip['travellerId'],trip,'flight','valid',
        lambda invoke: invoke(lambda:calls.append(1)) or [])
    assert result['status']=='completed' and calls==[1]


def test_page_open_and_cached_refresh_do_not_reserve_quota(client,scenario):
    memory,_,provider,_,hotel,_,_=scenario
    for _ in range(3):
        assert client.get('/api/fr5/itineraries/trip/budget-replan',headers=HEADERS).status_code==200
        assert client.post(BASE,headers=HEADERS).status_code==200
    provider.assert_not_called();hotel.assert_not_called()
    assert not memory.collections.get('budget_alternative_search_quota')


def test_three_real_failed_attempts_are_counted_but_do_not_exhaust_default_budget(client,scenario):
    memory,_,provider,_,_,_,_=scenario
    provider.side_effect=TimeoutError('provider submitted')
    for value in (360,361,362):
        memory.update('itineraries','trip',{'foodCost':value})
        result=discover(client,'flight')
        assert result.json['search']['status']=='unavailable'
    assert provider.call_count==3


def test_actual_limit_returns_retry_time_and_expired_cached_limit_is_not_replayed(scenario,monkeypatch):
    memory,trip,_,_,_,_,_=scenario
    monkeypatch.setenv('BUDGET_ALTERNATIVE_SEARCHES_PER_HOUR','1')
    class Clock(datetime):
        value=datetime(2027,2,1,10,15,tzinfo=timezone.utc)
        @classmethod
        def now(cls,*_):return cls.value
    monkeypatch.setattr(discovery,'datetime',Clock)
    calls=[]
    def search(invoke):
        invoke(lambda:calls.append(1));return []
    discovery.run_search(trip['travellerId'],trip,'flight','one',search,request_id='first-intent')
    limited=discovery.run_search(trip['travellerId'],trip,'flight','two',search,request_id='limited-intent')
    assert limited['status']=='quota_limited' and limited['requestsAttempted']==0
    assert limited['retryAt']=='2027-02-01T11:00:00+00:00'
    Clock.value=datetime(2027,2,1,11,15,tzinfo=timezone.utc)
    stale=discovery.run_search(trip['travellerId'],trip,'flight','two',search,request_id='limited-intent')
    assert stale['status']=='retry_available' and calls==[1]
    fresh=discovery.run_search(trip['travellerId'],trip,'flight','two',search,request_id='new-intent')
    assert fresh['status']=='completed' and calls==[1,1]


def test_sparse_selected_hotel_can_use_consistent_validated_evidence(client,scenario):
    memory,trip,_,_,provider,writes,_=scenario
    booking=memory.retrieve('hotel_bookings','original')
    validated=deepcopy(booking['selectedHotel'])
    memory.update('hotel_bookings','original',{'selectedHotel':{'name':'Original Hotel','currency':'MYR'},
        'validatedOffer':validated,'acceptedPrebookSnapshot':{
            'amount':400,'currency':'MYR','priceBasis':'stay_total','taxesAndFeesStatus':'unknown'}})
    response=discover(client,'hotel')
    assert response.status_code==200,response.json
    offer=options(client,'hotel')[0]
    assert offer['replacementEstimatedCost']==250
    before=deepcopy(memory.retrieve('itineraries','trip'))
    preview=client.post(BASE+'/preview',headers=HEADERS,json={'alternative':offer})
    assert preview.status_code==200 and memory.retrieve('itineraries','trip')==before and not writes
    assert client.post(BASE+'/apply',headers=HEADERS,json={'alternative':offer}).status_code==200
    saved=client.get('/api/fr5/itineraries/trip',headers=HEADERS).json['itinerary']
    assert saved['hotelCost']==250 and saved['selectedHotel']['planningOnly']


def test_stay_criteria_can_be_recovered_from_accepted_snapshot_and_verified_address(client,scenario):
    memory,_,_,_,_,_,_=scenario
    old=memory.retrieve('hotel_bookings','original')
    criteria=old['stayCriteria']
    memory.update('hotel_bookings','original',{'stayCriteria':{},'acceptedPrebookSnapshot':{
        'amount':400,'currency':'MYR','priceBasis':'stay_total','taxesAndFeesStatus':'included',
        'checkin':criteria['checkin'],'checkout':criteria['checkout'],
        'occupancies':criteria['occupancies'],'roomQuantity':criteria['roomQuantity']}})
    reply=discover(client,'hotel')
    assert reply.status_code==200,reply.json
    assert options(client,'hotel')


@pytest.mark.parametrize('mode',['taxes_missing','basis_conflict','amount_conflict','currency_conflict'])
def test_no_hotel_evidence_is_invented_and_user_message_is_concise(client,scenario,mode):
    memory,_,_,_,provider,_,_=scenario
    old=memory.retrieve('hotel_bookings','original')
    original=deepcopy(old['selectedHotel'])
    accepted={'amount':400,'currency':'MYR','priceBasis':'stay_total','taxesAndFeesStatus':'included'}
    if mode=='taxes_missing':
        original['taxesAndFeesStatus']='unknown';accepted['taxesAndFeesStatus']='unknown'
    if mode=='basis_conflict':original['priceBasis']='per_room_night'
    if mode=='amount_conflict':accepted['amount']=999
    if mode=='currency_conflict':accepted['currency']='USD'
    memory.update('hotel_bookings','original',{'selectedHotel':original,'acceptedPrebookSnapshot':accepted})
    reply=discover(client,'hotel')
    assert reply.status_code==409
    assert reply.json['error']=='No verified cheaper hotel is currently available for this stay.'
    provider.assert_not_called()
