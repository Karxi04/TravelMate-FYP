from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from modules.fr04_hybrid_recommendation import routes
from scripts.core_technology_demo import run_demo, IsolatedRepository
from sequence_contract.domain_functions import (applyContentBasedFiltering, applyCollaborativeFiltering,
    calculateRecommendationScore, prepareRecommendationInput)
from services.recommendation_taxonomy import concepts_for
from services.preference_learning import effective_preference_profile, apply_explicit_feedback
from modules.fr11_chatbot_travel_assistant.nlp_extractor import extract_interests, extract_excluded_interests

AUTH={'Authorization':'Bearer fixture'}
UID='test_traveller_uid'


@pytest.fixture(scope='module')
def demo():
    return run_demo()


def test_same_verified_penang_pool_three_authenticated_handler_profiles(demo):
    assert demo['candidateCount']==16 and demo['providerCalls']==demo['productionWrites']==0
    rankings=[];plans=[]
    for label,result in demo['profiles'].items():
        phases=result['phases']
        initial=phases['initial']['ranking'];liked=phases['after_like']['ranking'];negative=phases['after_dislike']['ranking']
        did=result['actions']['like']
        before=next(r for r in initial if r['destinationId']==did)
        after=next(r for r in liked if r['destinationId']==did)
        assert after['finalScore']>before['finalScore']
        assert result['actions']['dislike'] not in {r['destinationId'] for r in negative}
        for row in initial:
            assert row['finalScore']==pytest.approx(round(.6*row['contentScore']+.3*row['collaborativeScore']+.1*row['popularityScore'],2))
            assert row['popularitySource']=='neutral_missing_rating'
            assert row['recommendationReason'] and row['destinationConcepts']
        plan=result['chat']['structuredPlan']
        assert plan['tripDays']==3 and plan['budgetLimit']==600 and plan['destinationArea']=='Penang'
        assert plan['startDate']=='2027-06-12' and plan['endDate']=='2027-06-14'
        assert {a['dayNo'] for a in plan['activities']}=={1,2,3}
        assert result['actions']['dislike'] not in {a['destinationId'] for a in plan['activities']}
        assert plan['budgetEstimate']['incomplete']
        assert result['chat']['completedRequest']['session']['travellerId']==f'demo_{label}'
        rankings.append(tuple(row['destinationId'] for row in initial))
        plans.append(tuple(row['destinationId'] for row in plan['activities']))
    assert len(set(rankings))==len(set(plans))==3


def test_category_metadata_and_plural_aliases_are_scoring_evidence():
    row=applyContentBasedFiltering(prepareRecommendationInput({'interests':['Culture']},[
        {'destinationId':'x','title':'A venue','category':'Cultural museums'}]))[0]
    assert row['contentSignals']['interests']['primaryCategoryMatch']
    assert row['contentSignals']['interests']['baseScore']==100
    assert {'culture','food','nature','adventure'} <= concepts_for(['Cultural sites','Restaurants','Outdoor activities'])


def test_shared_mobile_parity_golden_matches_current_python_engine():
    directory = Path(__file__).parent / 'fixtures'
    candidates = json.loads((directory / 'penang_core_demo.json').read_text(encoding='utf-8'))['candidates']
    golden = json.loads((directory / 'recommendation_parity.json').read_text(encoding='utf-8'))
    for case in golden['cases']:
        profile = case['preferences']
        rows = calculateRecommendationScore(applyCollaborativeFiltering(
            applyContentBasedFiltering(prepareRecommendationInput(profile, candidates)),
            golden['feedback'], golden['peers'], profile, profile['travellerId']))
        for row in rows:
            expected = next(item for item in case['expected'] if item['destinationId'] == row['destinationId'])
            for key in ('contentScore', 'collaborativeScore', 'popularityScore', 'finalScore','personalSuitabilityScore','evidenceConfidence'):
                assert row[key] == pytest.approx(expected[key], abs=.011)


def test_sparse_popularity_is_neutral_not_fabricated_and_invalid_numbers_do_not_boost():
    rows=calculateRecommendationScore([{'contentScore':80,'collaborativeScore':50},
        {'contentScore':float('nan'),'collaborativeScore':float('inf'),'rating':float('nan')}])
    assert rows[0]['popularityScore']==50 and rows[0]['finalScore']==68
    assert rows[0]['popularitySource']=='neutral_missing_rating'
    assert 'Popular and well reviewed' not in rows[0]['matchReasons']
    assert rows[1]['contentScore']==rows[1]['collaborativeScore']==0
    assert rows[1]['scoreBreakdown']['content']==rows[1]['scoreBreakdown']['collaborative']==0
    assert rows[1]['finalScore']==5


def test_similar_peer_positive_negative_dissimilar_and_cold_start():
    pref={'interests':['Culture'],'travelType':'Culture','travelPace':'Relaxed'}
    peers={f'p{i}':deepcopy(pref) for i in range(3)}
    def score(rating,profiles=peers):
        rows=[{'travellerId':uid,'destinationId':'x','rating':rating} for uid in profiles]
        return applyCollaborativeFiltering([{'destinationId':'x','rating':5}],rows,
            peerPreferences=profiles,currentPreference=pref,currentTravellerId='self')[0]
    assert score(5)['collaborativeScore']>50
    assert score(1)['collaborativeScore']<50
    assert score(5,{'other':{'interests':['Nature'],'travelType':'Nature','travelPace':'Active'}})['collaborativeScore']==50
    cold=applyCollaborativeFiltering([{'destinationId':'x','rating':5}],[],currentPreference=pref)[0]
    assert cold['collaborativeScore']==50 and cold['collaborativeConfidence']==0


def test_learning_cap_has_no_fictitious_positive_contribution_and_resettable_negative_identity():
    item={'destinationId':'x','title':'Culture museum','category':'Culture'}
    pref={'interests':['Culture']}
    updated,_,_=apply_explicit_feedback(None,user_id=UID,destination_id='x',feedback_type='more_like_this',destination_concepts=['culture'])
    row=applyContentBasedFiltering(prepareRecommendationInput(effective_preference_profile(pref,updated),[item]))[0]
    assert row['contentSignals']['interests']['learnedAdjustment']==0
    assert row['contentSignals']['interests']['learnedPositive']==[]
    updated,_,_=apply_explicit_feedback(updated,user_id=UID,destination_id='x',feedback_type='not_for_me',destination_concepts=['culture'])
    assert not applyContentBasedFiltering(prepareRecommendationInput(effective_preference_profile(pref,updated),[item]))
    assert applyContentBasedFiltering(prepareRecommendationInput(effective_preference_profile(pref,None),[item]))


def test_unknown_metadata_can_be_excluded_without_inventing_concepts():
    updated,_,_=apply_explicit_feedback(None,user_id=UID,destination_id='unknown',feedback_type='not_for_me',destination_concepts=[])
    assert updated['affinities']=={} and updated['feedbackByDestination']['unknown']['feedbackType']=='not_for_me'
    assert not applyContentBasedFiltering(prepareRecommendationInput(effective_preference_profile({'interests':['Culture']},updated),[
        {'destinationId':'unknown','title':'A venue'}]))
    with pytest.raises(ValueError,match='Reliable interest information'):
        apply_explicit_feedback(None,user_id=UID,destination_id='unknown',feedback_type='more_like_this',destination_concepts=[])


@pytest.mark.parametrize('minimum,offset,expected',[(70,0,list(range(12))),
    (70,12,list(range(12,24))),(90,0,list(range(6))),(100,0,[])])
def test_filter_before_page_has_no_duplicates_or_below_threshold(minimum,offset,expected):
    rows=[{'destinationId':str(i),'score':95-i,'address':'Penang, Malaysia'} for i in range(40)]
    record={'requestedDestination':'Penang','recommendationResults':rows}
    before=deepcopy(record)
    page=routes._page(record,{'minimumMatchScore':minimum,'offset':offset})
    assert [int(row['destinationId']) for row in page['recommendationResults']]==expected
    assert all(row['score']>=minimum for row in page['recommendationResults'])
    assert record==before


@pytest.mark.parametrize('options',[{'minimumMatchScore':101},{'minimumMatchScore':'NaN'},
    {'offset':-1},{'limit':0},{'limit':51}])
def test_invalid_threshold_and_page_fail_closed(options):
    assert routes._page({},options) is None


def test_provider_expansion_is_explicit_bounded_and_previous_owner_scope_checked(client,mock_traveller_auth):
    repo=IsolatedRepository()
    repo.store('travel_preferences',{'travellerId':UID,'interests':['Culture'],'preferenceProfileVersion':'v1'},UID)
    def provider(query,location,coords,**kwargs):
        offset=kwargs.get('start',0)
        return {'local_results':[{'place_id':f'p{i}','title':f'Museum {i}','category':'Culture','address':'Penang, Malaysia'} for i in range(offset,offset+20)]}
    with patch.dict('os.environ',{'SERPAPI_KEY':'synthetic-only'}),patch.object(routes,'retrieveRecord',side_effect=repo.read), \
         patch.object(routes,'storeRecord',side_effect=repo.store),patch.object(routes,'retrieveDestinationResults',side_effect=provider) as get:
        initial=client.post('/api/fr4/recommendations/generate',headers=AUTH,json={'destinationArea':'Penang','minimumMatchScore':70})
        assert initial.status_code==200
        gid=initial.json['recommendationGenerationId']
        assert initial.json['pagination']['candidateCount']==20 and initial.json['pagination']['providerHasMore']
        rerank=client.post('/api/fr4/recommendations/generate',headers=AUTH,json={'destinationArea':'Penang','previousGenerationId':gid})
        assert rerank.status_code==200 and get.call_count==1
        expanded=client.post('/api/fr4/recommendations/generate',headers=AUTH,json={'destinationArea':'Penang','previousGenerationId':gid,'expandCandidates':True})
        assert expanded.status_code==200 and expanded.json['pagination']['candidateCount']==40
        assert get.call_args.kwargs['start']==20 and get.call_count==2
        with patch.object(routes,'retrieveDestinationResults',side_effect=RuntimeError('Unavailable')):
            assert client.post('/api/fr4/recommendations/generate',headers=AUTH,json={'destinationArea':'Penang','previousGenerationId':gid,'expandCandidates':True}).status_code==502
        assert client.post('/api/fr4/recommendations/generate',headers=AUTH,json={'destinationArea':'Kuala Lumpur','previousGenerationId':gid}).status_code==404
        repo.records[('recommendation_snapshots',gid)]['travellerId']='other'
        assert client.get('/api/fr4/recommendations?generationId='+gid,headers=AUTH).status_code==404
        assert repo.records[('recommendation_snapshots',gid)]['recommendationResults']


def test_settings_owned_validated_and_ordinary_search_does_not_gain_threshold(client,mock_traveller_auth):
    with patch.object(routes,'retrieveRecord',return_value={}),patch.object(routes,'storeRecord') as store:
        assert client.get('/api/fr4/settings',headers=AUTH).json['minimumMatchScore']==70
        assert client.put('/api/fr4/settings',headers=AUTH,json={'minimumMatchScore':60,'travellerId':'other'}).status_code==200
        assert store.call_args.args[2]==UID and store.call_args.args[1]['travellerId']==UID
        for value in (True,39,91,'70',None):
            assert client.put('/api/fr4/settings',headers=AUTH,json={'minimumMatchScore':value}).status_code==400


def test_profile_edits_invalidate_snapshot_even_when_legacy_version_is_unchanged(client,mock_traveller_auth):
    original={'interests':['Culture'],'preferenceProfileVersion':'static-legacy-version'}
    snapshot={'recommendationGenerationId':'g','travellerId':UID,'requestedDestination':'Penang',
        'preferenceProfileVersion':routes._preference_version(original),
        'preferenceFingerprint':routes._profile_fingerprint(original),
        'recommendationResults':[{'destinationId':'x','title':'Temple','address':'Penang, Malaysia','score':80}]}
    updated={**original,'interests':['Nature']}
    def read(collection,doc=None,**kwargs):
        if collection=='recommendation_snapshots':return [snapshot] if doc is None else snapshot
        if collection=='travel_preferences':return updated
        return None
    with patch.object(routes,'retrieveRecord',side_effect=read):
        result=client.get('/api/fr4/recommendations',headers=AUTH)
    assert result.status_code==200 and result.json['stale'] and not result.json['recommendations']


def test_temporary_negation_uses_shared_taxonomy_without_persisting_questionnaire():
    assert extract_interests('I prefer nature instead of shopping.')==['Nature']
    assert 'Shopping' in extract_excluded_interests('I prefer nature instead of shopping.')
    assert 'Photography' in extract_interests('I prefer photography places.')


def test_legacy_local_cache_is_geographically_filtered_and_not_treated_as_verified_popularity(client,mock_traveller_auth):
    repo=IsolatedRepository()
    repo.store('travel_preferences',{'interests':['Culture'],'travellerId':UID},UID)
    legacy={'destinationId':'local_george_town','title':'George Town Heritage Core','address':'Penang, Malaysia',
            'category':'Culture','rating':4.9,'reviews':9000}
    repo.store('destination_cache',legacy,'local_george_town')
    with patch.dict('os.environ',{'SERPAPI_KEY':'','FALLBACK_MODE':'false'}), \
         patch.object(routes,'retrieveRecord',side_effect=repo.read),patch.object(routes,'storeRecord',side_effect=repo.store):
        result=client.post('/api/fr4/recommendations/generate',headers=AUTH,json={'destinationArea':'Penang'})
    assert result.status_code==200
    row=result.json['recommendations'][0]
    assert row['destinationId']=='local_george_town' and row['popularityScore']==50
    assert row['popularitySource']=='neutral_unverified_local_catalog'
    assert repo.read('destination_cache','local_george_town')['rating']==4.9
    assert 'ratingSource' not in repo.read('destination_cache','local_george_town')
