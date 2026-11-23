"""Actual FR4 -> FR5 routes with isolated source-controlled reviews and persistence."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

from modules.fr04_hybrid_recommendation import routes as fr4
from modules.fr05_smart_itinerary_budget_planner import routes as fr5, expense_routes as expenses
from services import demonstration_recommendations as demo
from scripts.plan_penang_fyp_reviews import build_plan
from scripts.plan_penang_fyp_expansion import build_plan as expansion
from test_fr08_fr09_hotels_payments import MemoryPersistence
from test_flexible_planning import basics

HEADERS={'Authorization':'Bearer valid_test_token','X-TravelMate-Review-Context':'fyp-v1'}


@pytest.fixture
def integrated(app,monkeypatch,mock_traveller_auth):
    memory=MemoryPersistence()
    memory.seed('travel_preferences','test_traveller_uid',{**deepcopy(demo.SIMULATED_PROFILES['culture']),'version':1})
    original,more=build_plan(),expansion()
    places=original['documents']['fyp_review_datasets/penang_v1']['destinations']
    rows=[{**row,'id':path.rsplit('/',1)[-1]} for path,row in [*original['documents'].items(),*more['documents'].items()] if 'rating' in row]
    monkeypatch.setattr(demo,'private_dataset',lambda:('isolated',places))
    monkeypatch.setattr(demo,'dataset_reviews',lambda *_:deepcopy(rows))
    monkeypatch.setattr(fr4,'cached_candidates',lambda *_:[])
    for module in [fr4,fr5]:monkeypatch.setattr(module,'retrieveRecord',memory.retrieve)
    monkeypatch.setattr(fr5,'claimRecord',memory.claim)
    monkeypatch.setattr(fr5,'updateRecord',lambda c,i,data,**kwargs:memory.update(c,i,data))
    monkeypatch.setattr(fr5,'retrieveLocationAndTravelTime',lambda rows:[])
    blocked=Mock(side_effect=AssertionError('Live provider or genuine snapshot write prohibited'))
    monkeypatch.setattr(fr4,'storeRecord',blocked)
    monkeypatch.setattr(fr4,'_provider_destinations',blocked)
    monkeypatch.setattr(fr5,'retrieveDestinationResults',blocked)
    monkeypatch.setattr(fr5,'retrieveSevenDayForecast',blocked)
    app.config.update(LOCAL_FYP_SAMPLE_REVIEWS=True,RECOMMENDATION_EVIDENCE_MODE='fyp_evaluation')
    return memory,blocked


def generated(client):
    result=client.post('/api/fr4/recommendations/generate',headers=HEADERS,json={'destinationArea':'Penang','purpose':'trip_planning'})
    assert result.status_code==200,result.json
    data=result.json
    assert data['recommendationGenerationId'].startswith('fyp-evaluation-') and data['recommendations']
    return data['recommendationGenerationId']


def build(client,generation,**extra):
    return client.post('/api/fr5/personalised-trips/generate',headers=HEADERS,
        json={**basics('smart'),'recommendationGenerationId':generation,**extra})


def test_fresh_fr4_evaluation_generation_builds_and_reopens_actual_smart_trip(client,integrated):
    memory,blocked=integrated;generation=generated(client)
    assert memory.retrieve('recommendation_snapshots',generation) is None  # The prior FR5 lookup misses this valid generation.
    response=build(client,generation)
    assert response.status_code==200,response.json
    trip=response.json['itinerary'];assert trip['activities'] and len(trip['dailySchedule'])==5
    assert trip['recommendationGenerationId']==generation
    assert all(row['recommendationGenerationId']==generation for row in trip['activities'])
    assert trip['generationContext']['destinationSource']=='fyp_evaluation'
    assert client.get('/api/fr5/itineraries/'+response.json['id'],headers=HEADERS).json['itinerary']['activities']==trip['activities']
    assert build(client,generation).json['id']==trip['id'] and len(memory.collections['itineraries'])==1
    assert not memory.collections.get('recommendation_snapshots') and not blocked.called


@pytest.mark.parametrize('change',['preferences','learning','review','staging','identity','expired','restart','forged','foreign','destination','genuine_mode','context','candidate'])
def test_evaluation_freshness_and_source_boundaries(client,integrated,change,monkeypatch):
    memory,_=integrated;generation=generated(client)
    session=client.application.extensions['recommendation_evaluation']
    extra={};headers=HEADERS
    if change=='preferences':memory.update('travel_preferences','test_traveller_uid',{'interests':['Nature']})
    elif change=='learning':session.learning('test_traveller_uid',lambda _ : ({'learnedPreferenceVersion':'changed','affinities':{}},None,True))
    elif change=='review':session.mark_evidence_changed()
    elif change=='staging':monkeypatch.setattr(fr4.review_staging,'evidence_revision',lambda:'changed-local-evidence')
    elif change=='identity':session.snapshots[generation][1]['recommendationGenerationId']='other-generation'
    elif change=='expired':session.snapshots[generation]=(0,session.snapshots[generation][1])
    elif change=='restart':client.application.extensions.pop('recommendation_evaluation')
    elif change=='forged':generation='fyp-evaluation-not-owned'
    elif change=='foreign':session.snapshots[generation][1]['travellerId']='foreign-owner'
    elif change=='destination':extra={'destinationArea':'Melaka'}
    elif change=='genuine_mode':client.application.config['RECOMMENDATION_EVIDENCE_MODE']='genuine'
    elif change=='context':headers={'Authorization':HEADERS['Authorization']}
    elif change=='candidate':session.snapshots[generation][1]['recommendationResults'][0]['recommendationGenerationId']='other-generation'
    result=client.post('/api/fr5/personalised-trips/generate',headers=headers,json={**basics('smart'),'recommendationGenerationId':generation,**extra})
    assert result.status_code==409,result.json
    assert not memory.collections.get('itineraries')


def test_concurrent_builds_and_expired_session_recovery_do_not_duplicate_saved_trip(app,integrated):
    with app.test_client() as c:generation=generated(c)
    def request(_):
        with app.test_client() as c:return build(c,generation)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(request,range(2)))
    assert all(row.status_code in {200,202} for row in results)
    memory,_=integrated;assert len(memory.collections['itineraries'])==1
    app.extensions.pop('recommendation_evaluation')
    with app.test_client() as c:
        recovered=build(c,generation)
        assert recovered.status_code==200 and recovered.json['reused']


def test_local_evidence_outage_is_retryable_without_claiming_a_stale_generation(client,integrated,monkeypatch):
    memory,_=integrated;generation=generated(client)
    monkeypatch.setattr(fr4.review_staging,'evidence_revision',Mock(side_effect=fr4.review_staging.ReviewStagingUnavailable('isolated outage')))
    result=build(client,generation)
    assert result.status_code==503 and result.json['requiresExplicitRegeneration'] is False
    assert result.json['retryable'] and not memory.collections.get('itineraries')


def test_budget_get_is_read_only_and_personal_cost_counted_once(client,monkeypatch,mock_traveller_auth):
    trip={**basics(),'id':'budget-trip','travellerId':'test_traveller_uid','itineraryRevision':4,'activities':[],
          'planningBlocks':[{'dayNo':2,'estimatedCost':25}], 'manualExpenses':[{'amountMinor':1000,'type':'actual'}]}
    read=Mock(return_value=deepcopy(trip));write=Mock(side_effect=AssertionError('Budget GET cannot write'))
    monkeypatch.setattr(fr5,'retrieveRecord',read);monkeypatch.setattr(fr5,'updateRecord',write)
    result=client.get('/api/fr5/itineraries/budget-trip/budget',headers=HEADERS)
    assert result.status_code==200,result.json
    assert result.json['budget']['personalPlans']==25 and not write.called and read.call_count==1


@pytest.mark.parametrize('fixed',[False,True])
def test_rest_day_preserves_visits_for_preview_and_never_cancels_arrangements(client,integrated,fixed):
    memory,_=integrated
    trip={**basics('assisted'),'id':'rest-trip','travellerId':'test_traveller_uid',
          'selectedHotel':{'name':'Existing selected hotel'},'hotelCost':200,'hotelCurrency':'MYR',
          'activities':[{'activityId':'chosen','activityName':'Existing selected visit','dayNo':3,'fixed':fixed,
                         'scheduledStartTime':'10:00','scheduledEndTime':'11:00','recommendedDurationMinutes':60}],
          'planningBlocks':[{'blockId':'personal-rest','type':'rest','label':'Rest','dayNo':3,'estimatedCost':0}]}
    memory.seed('itineraries','rest-trip',trip)
    result=client.post('/api/fr5/itineraries/rest-trip/flight-adjustment/preview',headers=HEADERS,json={
        'planningChanges':{'travelDayPreferences':{'days':[{'dayNo':3,'restDay':True}]}}}).json['preview']
    assert result['canApply'] is not fixed
    assert result['after']['hotelCost']==200 and result['after']['selectedHotel']==trip['selectedHotel']
    assert result['after']['planningBlocks']==trip['planningBlocks']
    assert any(row['activityId']=='chosen' for row in result['after']['activities']+result['after'].get('unscheduledSuggestions',[]))
    assert memory.retrieve('itineraries','rest-trip')==trip


@pytest.mark.parametrize('mode',['missing',None,'genuine'])
def test_genuine_saved_snapshot_still_builds_without_evaluation_context(client,integrated,mode):
    memory,blocked=integrated;client.application.config['RECOMMENDATION_EVIDENCE_MODE']='genuine'
    memory.seed('recommendation_snapshots','genuine-existing',{'travellerId':'test_traveller_uid',
        'recommendationGenerationId':'genuine-existing','requestedDestination':'Penang','source':'cache',
        'recommendationResults':[{'destinationId':'local_heritage','title':'Isolated genuine-snapshot attraction',
            'state':'Penang','address':'George Town, Penang, Malaysia','openingHours':'08:00-20:00'}]})
    if mode!='missing':memory.update('recommendation_snapshots','genuine-existing',{'recommendationEvidenceMode':mode})
    response=client.post('/api/fr5/personalised-trips/generate',headers={'Authorization':HEADERS['Authorization']},
        json={**basics('smart'),'recommendationGenerationId':'genuine-existing'})
    assert response.status_code==200,response.json
    assert response.json['itinerary']['activities'] and not blocked.called


def test_expenses_get_reads_only_required_owned_links_without_transaction(client,monkeypatch,mock_traveller_auth):
    trip={**basics(),'travellerId':'test_traveller_uid','id':'expense-trip','activities':[],
          'hotelBookingId':'hotel-owned','manualExpenseRevision':2,'manualExpenses':[{'id':'meal','type':'actual','amountMinor':1000}]}
    records={('itineraries','expense-trip'):trip,('hotel_bookings','hotel-owned'):{'travellerId':'test_traveller_uid',
             'checkoutOrderId':'paid-hotel'},('checkout_orders','paid-hotel'):{'travellerId':'test_traveller_uid',
             'status':'paid','paymentStatus':'paid','currency':'MYR','amountMinor':12345,'hotelBookingId':'hotel-owned'}}
    reads=[]
    def collection(name):
        def document(identity):
            def get(**kwargs):
                assert not kwargs,'Read-only GET must not start a transaction'
                reads.append((name,identity));data=deepcopy(records.get((name,identity)))
                return SimpleNamespace(exists=data is not None,to_dict=lambda:data)
            return SimpleNamespace(get=get)
        return SimpleNamespace(document=document)
    db=SimpleNamespace(collection=collection,transaction=Mock(side_effect=AssertionError('No transaction for GET')))
    monkeypatch.setattr(expenses.firebase_firestore,'get_db',lambda:db)
    result=client.get('/api/fr5/itineraries/expense-trip/expenses',headers=HEADERS)
    assert result.status_code==200,result.json
    assert result.json['overview']['verifiedMinor']==12345 and result.json['revision']==2
    assert len(reads)==3 and not db.transaction.called and result.headers['X-Request-ID']
    records[('checkout_orders','paid-hotel')]['travellerId']='foreign-owner'
    assert client.get('/api/fr5/itineraries/expense-trip/expenses',headers=HEADERS).json['overview']['verifiedMinor']==0
    records[('itineraries','expense-trip')]['travellerId']='foreign-owner';reads.clear()
    assert client.get('/api/fr5/itineraries/expense-trip/expenses',headers=HEADERS).status_code==404 and len(reads)==1
