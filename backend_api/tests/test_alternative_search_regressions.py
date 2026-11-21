"""Real routes, synthetic owner records, Firestore-shaped reads and mocked suppliers."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest

from test_budget_provider_discovery import scenario, BASE, discover, options
from test_fr05_advisory_apply import HEADERS
from modules.fr05_smart_itinerary_budget_planner import routes as r
from modules.fr07_flight_search import routes as fr7


def firestore_reads(monkeypatch, memory):
    def retrieve(collection, document_id=None, **kwargs):
        result = memory.retrieve(collection, document_id, **kwargs)
        if document_id is None and collection == 'flight_quotes':
            return [{**row, 'id': fr7._quote_doc_id(row['travellerId'], row['id'])} for row in result]
        return result
    monkeypatch.setattr(r, 'retrieveRecord', retrieve)


def test_persisted_economy_quote_keeps_search_identity_after_worker_cache_loss(client, scenario, monkeypatch):
    memory, _, _, _, _, writes, _ = scenario
    result = discover(client, 'flight').json['search']
    expected = result['references'][0]['searchId']
    firestore_reads(monkeypatch, memory)
    fr7.reset_flight_quotes()
    offer = options(client, 'flight')[0]
    assert offer['data']['searchId'] == expected
    fr7.reset_flight_quotes()
    assert client.post(BASE + '/preview', headers=HEADERS, json={'alternative': offer}).status_code == 200
    assert not writes


@pytest.mark.parametrize('category', ['flight', 'hotel'])
def test_discovery_references_survive_older_forty_quote_records(client, scenario, monkeypatch, category):
    memory, _, _, _, _, writes, _ = scenario
    # Real collection limits return the first forty old quotes, excluding the new one.
    for index in range(40):
        identity = f'old-search-{index}'
        memory.seed('flight_quotes', fr7._quote_doc_id('test_traveller_uid', identity),
                    {'id':identity,'travellerId':'test_traveller_uid','expiresAt':'2000-01-01T00:00:00+00:00'})
        memory.seed('hotel_offer_quotes', identity,
                    {'quoteId':identity,'travellerId':'test_traveller_uid','expiresAt':'2000-01-01T00:00:00+00:00','offer':{}})
    firestore_reads(monkeypatch, memory)
    search = discover(client, category).json['search']
    fr7.reset_flight_quotes()
    body = client.post(BASE, headers=HEADERS, json={'searchIds': {category: search.get('searchId')}}).json
    offers = [row for row in body['alternatives'] if row['alternativeType'] == category]
    assert len(offers) == 1
    assert body['searches'][category]['searchStatus'] == 'completed'
    assert body['searches'][category]['cheaperCandidateCount'] == 1
    assert not writes


def list_search(client, category, search, **settings):
    response = client.post(BASE, headers=HEADERS, json={'searchIds':{category:search['searchId']}, **settings})
    assert response.status_code == 200, response.json
    return response.json


def test_no_search_is_distinct_from_no_inventory(client, scenario):
    memory, _, flight, _, hotel, writes, _ = scenario
    body = client.post(BASE, headers=HEADERS).json
    assert body['searches']['flight']['searchStatus'] == 'not_started'
    assert body['searches']['hotel']['providerReached'] is None
    flight.assert_not_called();hotel.assert_not_called()
    assert not writes


@pytest.mark.parametrize('category', ['flight','hotel'])
def test_completed_empty_search_reports_no_offers(client, scenario, category):
    scenario[2 if category=='flight' else 4].return_value={'items':[]}
    search = discover(client, category).json['search']
    summary = list_search(client, category, search)['searches'][category]
    assert summary['searchStatus']=='completed' and summary['providerReached']
    assert summary['candidateCount']==summary['validQuoteCount']==summary['cheaperCandidateCount']==0
    assert summary['reasonCode']=='no_offers'


@pytest.mark.parametrize('category,price', [('flight',900),('hotel',180),('hotel',114.93)])
def test_complete_more_expensive_offers_are_not_called_missing_inventory(client, scenario, category, price):
    memory, _, _, returns, hotels, writes, rate = scenario
    if category=='hotel':
        memory.update('itineraries','trip',{'hotelCost':114.92,'selectedHotel':{**scenario[1]['selectedHotel'],'price':114.92}})
        memory.update('hotel_bookings','original',{'hotelCost':114.92,'selectedHotel':{**scenario[1]['selectedHotel'],'price':114.92}})
        hotels.return_value={'items':[{**rate,'price':price}]}
    else:
        returns.return_value['items'][0]['price']=price
    search = discover(client, category).json['search']
    body = list_search(client, category, search)
    summary = body['searches'][category]
    assert summary['validQuoteCount']==1 and summary['cheaperCandidateCount']==0
    assert summary['reasonCode']=='no_cheaper_comparable_offers'
    assert summary['comparisonRejectionCounts']['not_cheaper']==1
    assert not [row for row in body['alternatives'] if row['alternativeType']==category]
    assert not writes


@pytest.mark.parametrize('category', ['flight','hotel'])
def test_replacement_preview_cancel_confirm_and_reopen_after_cache_reset(client, scenario, category):
    memory, _, _, _, _, writes, _ = scenario
    search=discover(client,category).json['search']
    offer=next(row for row in list_search(client,category,search)['alternatives'] if row['alternativeType']==category)
    before=deepcopy(memory.retrieve('itineraries','trip'))
    assert client.post(BASE+'/preview',headers=HEADERS,json={'alternative':offer}).status_code==200
    assert not writes and memory.retrieve('itineraries','trip')==before # Cancel is no apply request.
    fr7.reset_flight_quotes()
    applied=client.post(BASE+'/apply',headers=HEADERS,json={'alternative':offer})
    assert applied.status_code==200,applied.json
    saved=client.get('/api/fr5/itineraries/trip',headers=HEADERS).json['itinerary']
    assert saved[f'{category}Cost']==(420 if category=='flight' else 250)
    assert len(writes)==1
    assert client.post(BASE+'/apply',headers=HEADERS,json={'alternative':offer}).status_code==409
    assert len(writes)==1


@pytest.mark.parametrize('category', ['flight','hotel'])
def test_expired_returned_evidence_is_reported_not_silently_lost(client,scenario,category):
    memory, _, _, _, _, writes, _=scenario
    search=discover(client,category).json['search']
    collection='flight_quotes' if category=='flight' else 'hotel_offer_quotes'
    for row in memory.collections[collection].values():row['expiresAt']='2000-01-01T00:00:00+00:00'
    fr7.reset_flight_quotes()
    summary=list_search(client,category,search)['searches'][category]
    assert summary['reasonCode']=='expired_quote'
    assert summary['comparisonRejectionCounts']['expired_quote']==1 and not writes


@pytest.mark.parametrize('field,value',[('travellerId','other-owner'),('tripId','other-trip'),
    ('stateVersion','old-revision'),('category','hotel')])
def test_search_evidence_cannot_cross_ownership_trip_revision_or_category(client,scenario,field,value):
    memory, _, _, _, _, writes, _=scenario
    search=discover(client,'flight').json['search']
    memory.update('budget_alternative_searches',search['searchId'],{field:value})
    summary=list_search(client,'flight',search)['searches']['flight']
    assert summary['reasonCode']=='search_mismatch' and 'candidateCount' not in summary
    assert not writes


def test_new_explicit_intent_can_refresh_expired_search_but_old_intent_never_replays(client,scenario):
    from test_final_travel_workflows import search as flight_search
    memory, _, provider, returns, _, writes, _=scenario
    first=flight_search(client,intent='original-search-intent').json['search']
    memory.collections['budget_alternative_searches'][first['searchId']]['result']['expiresAt']='2000-01-01T00:00:00+00:00'
    replay=flight_search(client,intent='original-search-intent').json['search']
    assert replay['reused'] and provider.call_count==returns.call_count==1
    refreshed=flight_search(client,intent='new-search-intent').json['search']
    assert not refreshed['reused'] and refreshed['searchId']!=first['searchId']
    assert provider.call_count==returns.call_count==2 and not writes


@pytest.mark.parametrize('category',['flight','hotel'])
def test_timeout_state_survives_saved_search_read_without_replay(client,scenario,category):
    provider=scenario[2 if category=='flight' else 4];provider.side_effect=TimeoutError('synthetic')
    search=discover(client,category).json['search']
    summary=list_search(client,category,search)['searches'][category]
    assert summary['searchStatus']=='unavailable' and summary['providerReached']
    assert summary['failureCode']=='provider_timeout' and summary['requestsAttempted']==1
    assert provider.call_count==1


@pytest.mark.parametrize('stored_cabin',[None,1])
def test_legacy_and_new_economy_selections_use_economy(client,scenario,stored_cabin):
    memory,trip,provider,returns,_,writes,_=scenario
    flight=deepcopy(trip['selectedFlight'])
    if stored_cabin is None:flight.pop('requestedTravelClass')
    memory.update('itineraries','trip',{'selectedFlight':flight})
    search=discover(client,'flight').json['search']
    body=list_search(client,'flight',search)
    assert provider.call_args.kwargs['travelClass']==returns.call_args.kwargs['travelClass']==1
    assert body['searches']['flight']['cheaperCandidateCount']==1 and not writes


def test_duplicate_quote_timings_collapse_but_distinct_flights_remain(client,scenario):
    from test_budget_provider_discovery import visit
    memory,_,_,_,_,writes,_=scenario
    row=visit(protected=True)
    memory.update('itineraries','trip',{'activities':[row],
        'dailySchedule':[{'dayNo':1,'dayDate':'2027-02-10','activities':[deepcopy(row)]}]})
    discover(client,'flight')
    original=next(iter(fr7._FLIGHT_QUOTES.values()))
    for suffix, distinct in [('duplicate',False),('distinct',True)]:
        quote=deepcopy(original);identity=original['id']+suffix;quote['id']=identity
        quote['retrievedAt']='2027-01-01T00:00:00+00:00'
        for offer in quote['completedOptions'].values():
            offer['retrievedAt']=quote['retrievedAt'];offer['searchId']=identity
            if distinct:offer['outboundSegments'][0]['flightNumber']='MH999'
        fr7._FLIGHT_QUOTES[identity]=quote
    body=client.post(BASE,headers=HEADERS).json
    assert len(body['flightTimingPreviews'])==2
    assert not [row for row in body['alternatives'] if row['alternativeType']=='flight']
    assert len({row['reason'] for row in body['flightTimingPreviews']})==1
    assert not writes


def test_pending_search_has_no_completed_or_empty_result_claim(client,scenario):
    memory,_,provider,_,_,writes,_=scenario
    search=discover(client,'flight').json['search']
    record=memory.collections['budget_alternative_searches'][search['searchId']]
    record.update(status='pending',result={})
    summary=list_search(client,'flight',search)['searches']['flight']
    assert summary['searchStatus']=='pending' and summary['reasonCode'] is None
    assert 'candidateCount' not in summary and provider.call_count==1 and not writes


def test_rejected_hotel_price_evidence_reports_candidates_without_claiming_no_inventory(client,scenario):
    scenario[4].return_value={'items':[{**scenario[6],'taxesAndFeesStatus':'unknown'}]}
    search=discover(client,'hotel').json['search']
    summary=list_search(client,'hotel',search)['searches']['hotel']
    assert summary['candidateCount']==summary['rejectedCount']==1
    assert summary['validQuoteCount']==0 and summary['reasonCode']=='quotes_rejected'
    assert summary['rejectionCounts']=={'incomplete_price_or_charges':1}


def test_legacy_empty_search_without_counts_does_not_invent_rejected_inventory(client,scenario):
    memory,_,_,_,provider,_,_=scenario
    provider.return_value={'items':[]}
    search=discover(client,'hotel').json['search']
    result=memory.collections['budget_alternative_searches'][search['searchId']]['result']
    for key in ['candidateCount','validQuoteCount','rejectedCount','rejectionCounts']:result.pop(key,None)
    summary=list_search(client,'hotel',search)['searches']['hotel']
    assert summary['reasonCode']=='evidence_unavailable' and 'candidateCount' not in summary
