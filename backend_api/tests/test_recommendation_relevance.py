from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from modules.fr04_hybrid_recommendation import routes
from scripts.core_technology_demo import IsolatedRepository
from scripts.recommendation_relevance_audit import evaluate,rank
from sequence_contract.domain_functions import applyCollaborativeFiltering,applyContentBasedFiltering,prepareRecommendationInput,calculateRecommendationScore,diversifyRecommendations,rankRecommendations
from services.recommendation_taxonomy import candidate_concepts,normalize_phrase
from services.malaysian_locality import normalize_destination_scope
from services.preference_learning import apply_explicit_feedback,effective_preference_profile

AUTH={'Authorization':'Bearer isolated'}
UID='test_traveller_uid'


def test_verified_penang_metadata_reaches_refresh_and_persisted_discovery(client, mock_traveller_auth, repository):
    repository.update('travel_preferences', UID, {'interests':['Photography','Food']})
    rows = [
        {'destinationId':'street','title':'Lebuh Armenian','category':'Tourist attraction','address':'George Town, Penang'},
        {'destinationId':'mall','title':'Gurney Plaza','category':'Shopping mall','address':'Penang'},
        {'destinationId':'park','title':'ESCAPE Penang','category':'Adventure park','address':'Penang'},
        {'destinationId':'museum','title':'Pinang Peranakan Mansion','description':'Heritage architecture.','address':'Penang'},
        {'destinationId':'wrong','title':'Entopia','address':'Teluk Bahang, Penang',
         'gps_coordinates':{'latitude':3.139,'longitude':101.6869}},
    ]
    for row in rows:
        repository.store('destination_cache', row, row['destinationId'])
    request = {'destinationArea':'Penang','discoveryMode':'relevant_v1'}
    first = client.post('/api/fr4/recommendations/generate', headers=AUTH, json=request)
    assert first.status_code == 200, first.json
    first_id = first.json['recommendationGenerationId']
    first_snapshot = deepcopy(repository.read('recommendation_snapshots', first_id))
    response = client.post('/api/fr4/recommendations/generate', headers=AUTH,
                           json={**request, 'previousGenerationId':first_id})
    assert response.status_code == 200, response.json
    assert response.json['recommendationGenerationId'] != first_id
    assert repository.read('recommendation_snapshots', first_id) == first_snapshot
    public = {row['destinationId']:row for row in response.json['recommendations']}
    assert set(public) == {'street','mall'}
    assert public['street']['category'] == 'Tourist attraction'
    assert public['street']['verifiedDestinationEvidence']['suppliesCategory']
    assert public['street']['discoveryMatchedConcepts'] == ['photography']
    assert public['mall']['foodExperienceType'] == 'dining'
    for row in public.values():
        assert row['finalScore'] == round(.6*row['contentScore']+.3*row['collaborativeScore']+.1*row['popularityScore'], 2)
    assert repository.read('destination_cache', 'street') == {**rows[0], 'id':'street'}
    reopened = client.get('/api/fr4/recommendations', headers=AUTH,
                          query_string={'generationId':response.json['recommendationGenerationId'], 'discoveryMode':'relevant_v1'})
    assert reopened.json['recommendations'] == response.json['recommendations']


def score(candidate,profile=None):return rank(profile or {'interests':['Culture'],'travelType':'Culture','travelPace':'Relaxed','budgetRange':'Moderate'},[candidate])[0]


@pytest.mark.parametrize('field,value,concept',[
    ('title','Heritage Museum','culture'),('destinationType','Hiking trail','adventure'),
    ('category','Café','food'),('types',['Botanical gardens'],'nature'),
    ('categories',[{'name':'Art gallery'}],'culture'),('tags',[{'title':'Street art'}],'photography'),
    ('description','Explore the botanical gardens and waterfall.','nature')])
def test_genuine_evidence_normalizes_consistently(field,value,concept):
    assert concept in candidate_concepts({field:value})


@pytest.mark.parametrize('description,concept',[('A museum that is not crowded.','culture'),('Not a museum but a botanical garden.','nature')])
def test_negation_applies_to_the_feature_not_an_unrelated_description_word(description,concept):
    assert concept in candidate_concepts({'description':description})


@pytest.mark.parametrize('description',[
    'Fun for family, social leisure, culture, food and shopping.',
    'Near a museum, botanical gardens and shopping mall.',
    'Not a museum. No hiking trails here.',
])
def test_generic_marketing_nearby_and_negated_features_are_not_matches(description):
    assert not candidate_concepts({'title':'A venue','description':description})


def test_theme_park_is_not_automatically_a_nature_hike_and_objects_do_not_leak_keys():
    assert 'nature' not in candidate_concepts({'title':'Theme Park'})
    assert not candidate_concepts({'categories':[{'unverifiedDescription':'museum'}]})
    assert normalize_phrase('Café')==normalize_phrase('Cafe\u0301')=='cafe'


def test_real_primary_fit_not_diluted_by_unrelated_categories_and_unknowns_explicit():
    row=score({'destinationId':'x','title':'Heritage Museum','category':'Culture Shopping'})
    assert row['contentSignals']['interests']['baseScore']==87.5
    assert row['personalSuitabilityScore']==pytest.approx(90.18)
    assert row['evidenceConfidence']==pytest.approx(.778)
    assert row['finalScore']<70 and row['personalSuitabilityScore']>70
    assert row['finalScore']==round(.6*row['contentScore']+.3*row['collaborativeScore']+.1*row['popularityScore'],2)
    unknown=score({'title':'Unknown venue','destinationId':'u'})
    assert unknown['personalSuitabilityScore'] is None and unknown['evidenceConfidence']==0
    assert not routes._page({'requestedDestination':'Penang','recommendationResults':[{**unknown,'address':'Penang, Malaysia'}]}, {'scoreBasis':'personal_v2','minimumMatchScore':40})['recommendationResults']


def test_missing_peer_popularity_evidence_changes_ranking_not_personal_suitability():
    item={'destinationId':'x','title':'Heritage museum'}
    cold=score(item)
    profile={'interests':['Culture'],'travelType':'Culture'}
    content=applyContentBasedFiltering(prepareRecommendationInput(profile,[{**item,'rating':5,'reviews':10000}]))
    community=calculateRecommendationScore(applyCollaborativeFiltering(content,[{'destinationId':'x','travellerId':f'p{i}','rating':5} for i in range(4)],{f'p{i}':profile for i in range(4)},profile,'self'))[0]
    assert cold['personalSuitabilityScore']==community['personalSuitabilityScore']==100
    assert community['finalScore']>cold['finalScore']
    assert cold['collaborativeConfidence']==0 and cold['popularityScore']==50


def test_collaborative_duplicate_or_invalid_ratings_cannot_manufacture_confidence():
    profile={'interests':['Culture'],'travelType':'Culture'}
    rows=[{'destinationId':'x','travellerId':'p','rating':5,'updatedAt':'2026-01-01'}]*5
    rows+=[{'destinationId':'x','travellerId':'p','rating':1,'updatedAt':'2026-02-01'},
           {'destinationId':'x','travellerId':'bad','rating':99},
           {'destinationId':'x','travellerId':'self','rating':5}]
    result=applyCollaborativeFiltering([{'destinationId':'x'}],rows,{'p':profile,'bad':profile,'self':profile},profile,'self')[0]
    assert result['collaborativeRatingCount']==1 and result['rawCollaborativeScore']==20
    assert result['collaborativeConfidence']==.25


def test_diversity_never_uses_an_unbounded_category_penalty():
    rows=[{'destinationId':str(i),'score':90-i,'destinationConcepts':['culture']} for i in range(6)]
    rows.append({'destinationId':'weak','score':80,'destinationConcepts':['shopping']})
    ranked=diversifyRecommendations(rankRecommendations(rows),{'interests':['Culture']},limit=20)
    assert ranked[-1]['destinationId']=='weak'
    assert all(row['score']-row['diversityAdjustedScore']<=4 for row in ranked)


@pytest.mark.parametrize('basis,expected',[('hybrid_v1',['high-ranking']),('personal_v2',['strong-fit'])])
def test_explicit_threshold_basis_filters_before_pagination_without_score_fallback(basis,expected):
    rows=[{'destinationId':'strong-fit','score':60,'personalSuitabilityScore':90},
          {'destinationId':'high-ranking','score':80,'personalSuitabilityScore':30},
          {'destinationId':'unknown','score':60,'personalSuitabilityScore':None}]
    rows=[{**row,'address':'Penang, Malaysia'} for row in rows]
    page=routes._page({'requestedDestination':'Penang','recommendationResults':rows},{'scoreBasis':basis,'minimumMatchScore':70,'limit':1})
    assert [row['destinationId'] for row in page['recommendationResults']]==expected
    assert page['pagination']['scoreBasis']==basis and page['pagination']['qualifiedCount']==1
    assert routes._page({}, {'scoreBasis':'invented'}) is None


@pytest.fixture
def repository(monkeypatch):
    repo=IsolatedRepository()
    repo.store('travel_preferences',{'travellerId':UID,'interests':['Culture'],'travelType':'Culture','preferenceProfileVersion':'base'},UID)
    for did,title,scope in [('one','Heritage museum',normalize_destination_scope('Penang')['scopeKey']),('two','Historic temple',None),('three','Nature park',None)]:
        row={'destinationId':did,'title':title,'address':'Penang, Malaysia'}
        if scope:row['canonicalDestinationScope']=scope
        repo.store('destination_cache',row,did)
    monkeypatch.setattr(routes,'retrieveRecord',repo.read);monkeypatch.setattr(routes,'storeRecord',repo.store)
    monkeypatch.setattr(routes,'transactPreferenceLearning',repo.learning)
    return repo


def test_legacy_settings_preserved_until_explicit_user_choice(client,mock_traveller_auth,repository):
    repository.store('recommendation_settings',{'minimumMatchScore':80},UID)
    original=deepcopy(repository.records)
    settings=client.get('/api/fr4/settings',headers=AUTH).json
    assert settings['minimumMatchScore']==80 and settings['scoreBasis']=='hybrid_v1'
    assert original==repository.records
    changed=client.put('/api/fr4/settings',headers=AUTH,json={'minimumMatchScore':80,'scoreBasis':'personal_v2'})
    assert changed.status_code==200 and changed.json['minimumMatchScore']==80
    assert repository.read('recommendation_settings',UID)['scoreBasis']=='personal_v2'
    assert client.put('/api/fr4/settings',headers=AUTH,json={'minimumMatchScore':80}).json['scoreBasis']=='personal_v2'
    assert client.put('/api/fr4/settings',headers=AUTH,json={'minimumMatchScore':80,'scoreBasis':'invented'}).status_code==400


def test_actual_generation_feedback_staleness_profile_change_and_account_isolation(client,mock_traveller_auth,repository):
    payload={'destinationArea':'Penang','scoreBasis':'personal_v2','minimumMatchScore':70}
    response=client.post('/api/fr4/recommendations/generate',headers=AUTH,json=payload)
    assert response.status_code==200,response.json
    assert {row['destinationId'] for row in response.json['recommendations']}=={'one','two'}
    generation=response.json['recommendationGenerationId']
    request={'destinationId':'one','recommendationGenerationId':generation,'feedbackType':'not_for_me'}
    assert client.post('/api/fr4/preference-feedback',headers=AUTH,json=request).json['changed']
    assert not client.post('/api/fr4/preference-feedback',headers=AUTH,json=request).json['changed']
    assert len(repository.read('recommendation_feedback_events'))==1
    assert client.get('/api/fr4/recommendations',headers=AUTH,query_string={'generationId':generation,'scoreBasis':'personal_v2'}).json['stale']
    fresh=client.post('/api/fr4/recommendations/generate',headers=AUTH,json={**payload,'previousGenerationId':generation}).json
    assert {row['destinationId'] for row in fresh['recommendations']}=={'two'}
    repository.update('travel_preferences',UID,{'interests':['Nature'],'travelType':'Nature','preferenceProfileVersion':'changed'})
    nature=client.post('/api/fr4/recommendations/generate',headers=AUTH,json=payload).json
    assert {row['destinationId'] for row in nature['recommendations']}=={'three'}
    mock_traveller_auth.return_value={'uid':'other-account'}
    assert client.get('/api/fr4/recommendations',headers=AUTH,query_string={'generationId':generation}).status_code==404
    assert client.post('/api/fr4/preference-feedback',headers=AUTH,json=request).status_code==404
    assert client.get('/api/fr4/settings',headers=AUTH).json['scoreBasis']=='personal_v2'


def test_frozen_same_pool_evaluation_actual_metrics_and_bounded_feedback():
    result=evaluate()
    assert result['candidateCount']==16 and result['providerCalls']==result['productionWrites']==0
    for scenario,profiles in result['scenarios'].items():
        rankings=[]
        for label,phases in profiles.items():
            assert len(phases['before'])==len(phases['after'])==16
            assert len(phases['afterPersonalQualified'])>len(phases['beforeHybridQualified'])
            assert 0<=phases['afterMetrics']['precision@5']<=1
            rankings.append(tuple(row['destinationId'] for row in phases['after']))
        assert len(set(rankings))==3
    for label,evidence in result['feedback'].items():
        assert evidence['exactNegativeExcluded'] and evidence['resetRestoresOriginalRanking'] and not evidence['repeatStacks']
        for experiment in evidence['strengthExperiments'].values():
            assert 0<=experiment['afterHybrid']-experiment['beforeHybrid']<=1.50
    directory=Path(__file__).parent/'fixtures'
    fixture=directory/'penang_core_demo.json'
    judgements=json.loads((directory/'recommendation_relevance_judgements.json').read_text(encoding='utf-8'))
    assert judgements['candidateFixtureSha256']==hashlib.sha256(fixture.read_bytes()).hexdigest()


@pytest.mark.parametrize('case',json.loads((Path(__file__).parent/'fixtures/recommendation_relevance_cases.json').read_text(encoding='utf-8'))['cases'],ids=lambda case:case['label'])
def test_extended_python_contract_cases(case):
    result=score(case['candidate'],case['preferences'])
    for key,expected in case['expected'].items():
        if isinstance(expected,(int,float)):assert result[key]==pytest.approx(expected,abs=.011)
        else:assert result[key]==expected


@pytest.mark.parametrize('rating',[99,-2,True,'not rated'])
def test_invalid_popularity_cannot_fabricate_rating_evidence(rating):
    assert score({'destinationId':'x','title':'Heritage museum','rating':rating})['popularityScore']==50


def test_secondary_metadata_cannot_claim_personal_fit_when_interests_unresolved():
    unknown=score({'destinationId':'x','title':'A venue','pace':'Relaxed','budgetLevel':'Moderate'})
    assert unknown['personalSuitabilityScore'] is None and unknown['evidenceConfidence']>0
    unsupported=score({'destinationId':'x','title':'A venue','budgetLevel':'Moderate'},{'interests':['Unmapped interest'],'budgetRange':'Moderate'})
    assert unsupported['personalSuitabilityScore'] is None


def test_unverified_or_invalid_popularity_cannot_reenter_via_ranking_ties():
    rows=[{'destinationId':'a','contentScore':80,'collaborativeScore':50,'rating':1,'reviews':1,'ratingSource':'unverified_local_catalog'},
          {'destinationId':'z','contentScore':80,'collaborativeScore':50,'rating':5,'reviews':90000,'ratingSource':'unverified_local_catalog'}]
    ranked=rankRecommendations(calculateRecommendationScore(rows))
    assert [row['destinationId'] for row in ranked]==['a','z']
