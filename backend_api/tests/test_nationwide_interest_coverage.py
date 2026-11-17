from itertools import combinations
import pytest
from test_shared_destination_discovery import discovery_route
from services.malaysian_locality import resolve_destination_scope, discovery_scope, validate_candidate
from services.recommendation_taxonomy import candidate_concepts, preference_concepts
from sequence_contract.domain_functions import diversifyRecommendations

AREAS = {
 'Penang':'George Town|Butterworth|Bukit Mertajam|Alma|Machang Bubok|Balik Pulau',
 'Kedah':'Kulim|Sungai Petani|Alor Setar|Langkawi|Baling',
 'Perak':'Ipoh|Taiping|Kampar|Kuala Kangsar|Lumut',
 'Selangor':'Shah Alam|Klang|Petaling Jaya|Kuala Selangor',
 'Kuala Lumpur':'Bukit Bintang|Cheras|Kuala Lumpur',
 'Johor':'Johor Bahru|Muar|Batu Pahat|Kluang|Desaru',
 'Pahang':'Kuantan|Cameron Highlands|Bentong|Temerloh',
 'Negeri Sembilan':'Seremban|Port Dickson|Nilai', 'Melaka':'Melaka City|Ayer Keroh|Alor Gajah',
 'Kelantan':'Kota Bharu|Gua Musang', 'Terengganu':'Kuala Terengganu|Kuala Besut|Marang',
 'Perlis':'Kangar|Kuala Perlis', 'Sabah':'Kota Kinabalu|Kundasang|Sandakan|Semporna|Tawau',
 'Sarawak':'Kuching|Miri|Sibu|Bintulu|Sri Aman', 'Putrajaya':'Putrajaya', 'Labuan':'Labuan'}

@pytest.mark.parametrize('state,name',[(s,n) for s,names in AREAS.items() for n in names.split('|')])
def test_nationwide_strict_nearby_and_foreign_rejection(state,name):
    scope=resolve_destination_scope(f'{name}, {state}, Malaysia')
    if (state,name)==('Kuala Lumpur','Cheras'):
        assert not scope['resolved']  # Known catalogue omission; never substitute Selangor's point.
        return
    assert scope['resolved'] and scope['state']==state and scope['country']=='Malaysia'
    row={'title':'Fictional museum fixture','city':scope.get('city'), 'state':state,'type_id':'museum',
         'address':f'{name}, {state}, Malaysia'}
    if scope.get('coordinateStatus')=='verified_locality':
        row['gps_coordinates']={'latitude':scope['latitude'],'longitude':scope['longitude']}
        nearby=discovery_scope(scope,'nearby')
        ok,result=validate_candidate(row,nearby)
        assert ok and result['nearbyDistanceKm']==0 and result['address']==row['address']
    else:
        with pytest.raises(ValueError): discovery_scope(scope,'nearby')
    assert validate_candidate(row,scope)[0]
    assert not validate_candidate({**row,'country':'SG'},scope)[0]

def rows():
    return [dict(destinationId=f'{concept}{i}',score=90 if concept=='nature' else 80,
       destinationConcepts=[concept],type_id=kind,interestEvidenceSource='primary_metadata',
       contentSignals={'interests':{'score':100}},discoveryEligible=True)
       for concept,kind in [('nature','park'),('shopping','shopping_mall'),('food','restaurant')]
       for i in range(8)]

def test_strong_nature_shopping_are_both_represented_without_score_changes():
    original=rows(); pref={'interests':['Nature','Shopping']}
    result=diversifyRecommendations(original,pref,limit=6,coverageAware=True)
    assert sum('nature' in r['destinationConcepts'] for r in result)>=2
    assert sum('shopping' in r['destinationConcepts'] for r in result)>=2
    assert all(r['score']==next(x['score'] for x in original if x['destinationId']==r['destinationId']) for r in result)

@pytest.mark.parametrize('interests',[['Nature','Shopping','Food'],*map(list,combinations(['Nature','Shopping','Food'],2))])
def test_supported_interests_are_covered(interests):
    result=diversifyRecommendations(rows(),{'interests':interests},limit=6,coverageAware=True)
    assert preference_concepts(interests)<=set().union(*(set(r['destinationConcepts']) for r in result))

@pytest.mark.parametrize('item,unexpected',[
 ({'category':'Tourist attraction','title':'Nature Shopping Family Food Culture Venue'},'nature'),
 ({'type_id':'amusement_park','category':'Theme park'},'nature'),
 ({'type_id':'shopping_mall','title':'Nature Shopping Mall'},'nature'),
 ({'type_id':'museum','description':'Near shopping malls and restaurants.'},'shopping'),
 ({'type_id':'restaurant','address':'Museum Street','description':'Near a museum.'},'culture')])
def test_category_evidence_is_not_nearby_marketing(item,unexpected):
    assert unexpected not in candidate_concepts(item)

@pytest.mark.parametrize('state,name',[(s,n) for s,names in AREAS.items() for n in names.split('|')])
def test_nationwide_provider_empty_error_and_snapshots(discovery_route,client,monkeypatch,state,name):
    from modules.fr04_hybrid_recommendation import routes
    from services.destination_candidates import provider_page
    from unittest.mock import Mock
    scope=resolve_destination_scope(f'{name}, {state}, Malaysia')
    if not scope['resolved']:
        assert (state,name)==('Kuala Lumpur','Cheras')
        return
    row={'destinationId':'fixture','title':'Fictional museum','type_id':'museum',
         'city':scope.get('city'),'state':state,'address':f'{name}, {state}, Malaysia'}
    if scope.get('coordinateStatus')=='verified_locality':
        row['gps_coordinates']={'latitude':scope['latitude'],'longitude':scope['longitude']}
    provider=Mock(return_value={'local_results':[row,row]})
    monkeypatch.setattr(routes,'retrieveDestinationResults',provider)
    payload={'destinationArea':scope['canonicalName'],'discoveryMode':'relevant_v1'}
    auth={'Authorization':'Bearer fixture'}
    result=client.post('/api/fr4/recommendations/generate',headers=auth,json=payload)
    assert result.status_code==200 and len(result.json['recommendations'])==1
    identity=result.json['recommendationGenerationId']
    if scope.get('coordinateStatus')=='verified_locality':
        nearby=client.post('/api/fr4/recommendations/generate',headers=auth,json={**payload,'geographicMode':'nearby'})
        assert nearby.status_code==200 and nearby.json['recommendationGenerationId']!=identity
    saved=client.get('/api/fr4/recommendations',headers=auth,query_string={'generationId':identity,'discoveryMode':'relevant_v1'})
    assert saved.status_code==200 and saved.json['snapshot']['canonicalDestinationScope'].get('geographicMode')!='nearby'
    assert provider_page(Mock(return_value={'local_results':[]}), 'museum',scope)['items']==[]
    with pytest.raises(TimeoutError): provider_page(Mock(side_effect=TimeoutError()),'museum',scope)

def test_coverage_requires_strong_evidence_and_never_invents_missing_interest():
    pool=rows(); pref={'interests':['Nature','Shopping','Photography']}
    for r in pool:
        if r['destinationConcepts']==['shopping']: r['contentSignals']['interests']['score']=30
    result=diversifyRecommendations(pool,pref,limit=6,coverageAware=True)
    assert not any('photography' in r['destinationConcepts'] for r in result)
    assert all(r['selectionReason']!='Early coverage of a strongly evidenced selected interest'
               for r in result if r['destinationConcepts']==['shopping'])

TYPES={'food':'restaurant','culture':'museum','nature':'park','shopping':'shopping_mall',
       'adventure':'adventure_sports_center','photography':'observation_deck','family':'zoo',
       'leisure':'beach','social':'community_center'}
@pytest.mark.parametrize('interests',[[c] for c in TYPES]+[list(p) for p in combinations(TYPES,2)]+[list(TYPES)])
def test_all_selectable_concepts_and_pairs_remain_evidenced_and_deterministic(interests):
    pool=[dict(destinationId=f'{c}{i}',score=90,type_id=TYPES[c],destinationConcepts=[c],
               interestEvidenceSource='primary_metadata',contentSignals={'interests':{'score':100}})
          for c in interests for i in range(3)]
    count=max(6,len(interests))
    result=diversifyRecommendations(pool,{'interests':interests},count,coverageAware=True)
    assert set(interests)<=set().union(*(candidate_concepts(r) for r in result))
    assert len({r['destinationId'] for r in result})==len(result)
    assert [r['destinationId'] for r in result]==[r['destinationId'] for r in diversifyRecommendations(list(reversed(pool)),{'interests':interests},count,coverageAware=True)]

def test_real_route_discloses_unavailable_interest_without_expanding(discovery_route,client,monkeypatch):
    from modules.fr04_hybrid_recommendation import routes
    records,calls,_=discovery_route
    # The shared provider fixture embeds the query in its title, which would itself
    # supply scenic-viewpoint evidence. This case deliberately has only museum data.
    monkeypatch.setattr(routes,'retrieveDestinationResults',lambda *a,**kw:{'local_results':[
        {'destinationId':'museum-fixture','title':'Recorded museum','city':'George Town','state':'Penang','type_id':'museum'}]})
    records['travel_preferences']['test_traveller_uid']['interests']=['Culture','Photography']
    result=client.post('/api/fr4/recommendations/generate',headers={'Authorization':'Bearer fixture'},
                       json={'destinationArea':'Penang','discoveryMode':'relevant_v1'})
    assert result.status_code==200
    snapshot=result.json['snapshot']
    assert snapshot['interestCoverage']['photography']=={'eligible':0,'displayed':0}
    assert 'Photography' in snapshot['coverageNotice']
    assert snapshot['canonicalDestinationScope']['state']=='Penang'
    assert snapshot['canonicalDestinationScope'].get('geographicMode')!='nearby'
    assert len(calls)<=3
