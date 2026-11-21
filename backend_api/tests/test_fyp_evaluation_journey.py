"""Normal routes with existing Penang definitions; all persistence/providers mocked."""
from copy import deepcopy
from decimal import Decimal
from unittest.mock import Mock, patch
import pytest

from app import create_app
from modules.fr04_hybrid_recommendation import routes
from services import demonstration_recommendations as demo
from services.recommendation_review_evidence import approved_contributions
from services.review_destination import review_candidate_id
from scripts.plan_penang_fyp_reviews import build_plan
from scripts.plan_penang_fyp_expansion import build_plan as expansion_plan

HEADERS = {'Authorization': 'Bearer isolated', 'X-TravelMate-Review-Context': 'fyp-v1'}
URL = '/api/fr4/recommendations'


@pytest.fixture
def evaluation(client, mock_traveller_auth, monkeypatch):
    base, expansion = build_plan(), expansion_plan()
    places = demo.prepare_candidates(list(base['documents']['fyp_review_datasets/penang_v1']['destinations'].values()))
    reviews = [row for row in [*base['documents'].values(), *expansion['documents'].values()] if 'rating' in row]
    state = {'profile': deepcopy(demo.SIMULATED_PROFILES['culture']), 'reviews': reviews, 'places': places}
    def read(collection, identity=None, **options):
        assert collection == 'travel_preferences' and identity == mock_traveller_auth.return_value['uid']
        return deepcopy(state['profile'])
    monkeypatch.setattr(routes, 'retrieveRecord', read)
    monkeypatch.setattr(routes, 'cached_candidates', lambda *a: [])
    monkeypatch.setattr(routes, 'DESTINATIONS', [])
    monkeypatch.setattr(demo, 'load_sources', lambda area: (deepcopy(state['places']), deepcopy(state['reviews'])))
    blocked = Mock(side_effect=AssertionError('No genuine history, feedback, provider or account mutations'))
    for name in ('storeRecord', 'loadRecommendationSnapshot', 'retrieveRecordsById', 'transactPreferenceLearning', '_provider_destinations'):
        monkeypatch.setattr(routes, name, blocked)
    client.application.config.update(LOCAL_FYP_SAMPLE_REVIEWS=True, RECOMMENDATION_EVIDENCE_MODE='fyp_evaluation')
    def generate(**body):
        response = client.post(URL+'/generate', headers=HEADERS,
            json={'destinationArea':'Penang', 'discoveryMode':routes.DISCOVERY_MODE, **body})
        assert response.status_code == 200, response.json
        return response.json
    return state, generate, blocked, mock_traveller_auth


def test_normal_home_get_generate_and_paging_are_owner_scoped_without_genuine_history(client, evaluation):
    state, generate, blocked, _ = evaluation
    before = deepcopy(state)
    empty = client.get(URL, headers=HEADERS, query_string={'discoveryMode':routes.DISCOVERY_MODE})
    assert empty.status_code == 200 and empty.json['recommendationGenerationId'] == ''
    assert empty.json['requiresExplicitRegeneration'] is True
    generated = generate()
    assert generated['recommendationEvidenceMode'] == 'fyp_evaluation'
    assert generated['evidenceProvenance']['approvedContributions'] == 96
    identity = generated['recommendationGenerationId']
    saved = client.get(URL, headers=HEADERS, query_string={'generationId':identity, 'limit':2, 'offset':0})
    assert saved.status_code == 200 and len(saved.json['recommendations']) == 2
    assert saved.headers['Cache-Control'] == 'private, no-store'
    assert saved.headers['X-TravelMate-Recommendation-Evidence'] == 'fyp_evaluation'
    assert 'travellerId' not in saved.json['snapshot']
    assert saved.json['pagination']['hasMore'] is True
    assert not saved.json['pagination']['providerHasMore']
    home=client.get(URL,headers=HEADERS,query_string={'discoveryMode':routes.DISCOVERY_MODE})
    assert home.json['recommendationGenerationId']==identity
    assert home.json['snapshot']['requestedDestination']=='Penang'
    assert state == before and not blocked.called


def test_actual_target_preferences_change_scores_and_rankings_using_existing_formula(evaluation):
    state, generate, _, _ = evaluation
    results=[]
    for key in ('culture', 'nature', 'family'):
        state['profile'] = deepcopy(demo.SIMULATED_PROFILES[key])  # Mocked saved questionnaire.
        result=generate(limit=50, discoveryMode=None)
        rows=result['recommendations']
        assert len(rows)==12
        for row in rows:
            breakdown=row['scoreBreakdown']
            # Display components are rounded; the unchanged scorer weights full precision.
            displayed_sum=round(.6*breakdown['content'] + .3*breakdown['collaborative'] + .1*row['popularityEvidence']['score'],2)
            assert abs(Decimal(str(row['finalScore']))-Decimal(str(displayed_sum))) <= Decimal('.01')
            assert result['engine']['weightedScoring']=={'content':.6,'collaborative':.3,'popularity':.1}
            assert row['synthetic'] is True and row['recommendationEvidenceMode']=='fyp_evaluation'
            if row['collaborativeRatingCount']:
                assert row['collaborativeConfidence'] > 0
            else:
                assert row['collaborativeConfidence']==0 and row['collaborativeScore']==50
                assert row['collaborativeFallbackReason']=='no_similar_peers'
            assert review_candidate_id(row) in {p['destinationId'] for p in state['places']}
        results.append([(row['destinationId'],row['finalScore'],row['collaborativeScore']) for row in rows])
        assert any(row['collaborativeRatingCount'] > 0 for row in rows)
    assert len({str(result) for result in results})==3
    assert len({tuple(row[0] for row in result) for result in results}) > 1


def test_current_moderation_and_negative_ratings_are_not_raised_or_reclassified(evaluation):
    state, generate, _, _ = evaluation
    original=deepcopy(state['reviews'])
    assert len(original)==104 and sum(map(len,approved_contributions(original,demonstration=True).values()))==96
    for row in state['reviews']:
        if row['destinationId']=='local_kek_lok_si':
            row['rating']=1  # Isolated sensitivity check; source definitions are untouched.
    row=next(r for r in generate(limit=50)['recommendations'] if r['destinationId']=='local_kek_lok_si')
    assert row['rawCollaborativeScore']==20 and row['collaborativeScore'] < 50
    assert row['popularityScore'] < 50
    for r in state['reviews']:
        if r['destinationId']=='local_kek_lok_si':
            r['feedbackStatus']='hidden'
    row=next(r for r in generate(limit=50)['recommendations'] if r['destinationId']=='local_kek_lok_si')
    assert row['collaborativeRatingCount']==0 and row['collaborativeScore']==50
    assert row['popularityScore']==50
    assert all(r['synthetic'] is True for r in state['reviews'])


def test_existing_local_summary_wins_and_provider_is_fallback_without_becoming_peer_evidence(evaluation):
    state, generate, _, _ = evaluation
    place=state['places'][0]
    # Simulate the existing approved provider cache, not a provider request.
    with patch.object(routes,'cached_candidates',return_value=[{**place,'ratingSource':'provider','rating':4.5,'reviews':9000}]):
        row=next(r for r in generate(limit=50)['recommendations'] if r['destinationId']==place['destinationId'])
    assert row['popularitySource']=='demonstration_approved_reviews'
    assert row['popularityEvidence']['reviewCount'] < 9000
    assert row['collaborativeRatingCount'] < 9000
    for review in state['reviews']:
        if review['destinationId']==place['destinationId']:
            review['feedbackStatus']='hidden'
    with patch.object(routes,'cached_candidates',return_value=[{**place,'ratingSource':'provider','rating':4.5,'reviews':9000}]):
        row=next(r for r in generate(limit=50)['recommendations'] if r['destinationId']==place['destinationId'])
    assert row['popularitySource']=='provider_rating_review_count' and row['popularityScore']==90
    assert row['collaborativeRatingCount']==0 and row['collaborativeScore']==50
    assert row['popularityEvidence']['fallbackReason']=='no_approved_local_evaluation_reviews'


def test_learning_changes_only_temporary_evaluation_profile_and_preserves_questionnaire(client, evaluation):
    state, generate, blocked, _ = evaluation
    before=deepcopy(state['profile'])
    result=generate()
    row=result['recommendations'][0]
    payload={'destinationId':row['destinationId'],'recommendationGenerationId':result['recommendationGenerationId'],'feedbackType':'not_for_me'}
    response=client.post('/api/fr4/preference-feedback',headers=HEADERS,json=payload)
    assert response.status_code==200, response.json
    learning=client.get('/api/fr4/preference-feedback',headers=HEADERS).json['learning']
    assert learning['currentFeedback'][row['destinationId']]=='not_for_me'
    stale=client.get(URL,headers=HEADERS,query_string={'generationId':result['recommendationGenerationId']})
    assert stale.json['stale'] is True and stale.json['recommendations']==[]
    updated=generate()
    assert all(r['destinationId'] != row['destinationId'] for r in updated['recommendations'])
    assert state['profile']==before and not blocked.called
    assert client.delete('/api/fr4/preference-feedback',headers=HEADERS).status_code==200


def test_questionnaire_changes_require_new_generation_without_rewriting_old(client,evaluation):
    state, generate, _, _=evaluation
    first=generate(limit=50, discoveryMode=None)
    state['profile']=deepcopy(demo.SIMULATED_PROFILES['nature'])
    read=client.get(URL,headers=HEADERS,query_string={'generationId':first['recommendationGenerationId']})
    assert read.json['stale'] is True and read.json['recommendations']==[]
    assert read.json['requiresExplicitRegeneration'] is True
    second=generate(limit=50)
    assert first['recommendationGenerationId']!=second['recommendationGenerationId']
    stored=client.application.extensions['recommendation_evaluation']
    assert stored.snapshot('test_traveller_uid',first['recommendationGenerationId'])['recommendationResults']==first['snapshot']['recommendationResults']


def test_cross_account_expiry_wrong_area_and_genuine_configuration_fail_closed(client,evaluation,monkeypatch):
    _, generate, blocked, auth=evaluation
    identity=generate()['recommendationGenerationId']
    auth.return_value['uid']='isolated_other_owner'
    assert client.get(URL,headers=HEADERS,query_string={'generationId':identity}).status_code==404
    assert client.post('/api/fr4/preference-feedback',headers=HEADERS,json={
        'destinationId':'local_kek_lok_si','recommendationGenerationId':identity,'feedbackType':'more_like_this'}).status_code==404
    auth.return_value['uid']='test_traveller_uid'
    assert client.get(URL,headers=HEADERS,query_string={'generationId':identity,'destinationArea':'Sabah'}).status_code==404
    client.application.config['RECOMMENDATION_EVIDENCE_MODE']='genuine'
    assert client.get(URL,headers=HEADERS,query_string={'generationId':identity}).status_code==404
    client.application.config['RECOMMENDATION_EVIDENCE_MODE']='fyp_evaluation'
    monkeypatch.setattr(demo,'monotonic',lambda:float('inf'))
    assert client.get(URL,headers=HEADERS,query_string={'generationId':identity}).status_code==404
    assert not blocked.called


@pytest.mark.parametrize('options',[{'evidenceMode':'fyp_evaluation'},{'profileKey':'nature','evidenceMode':'demonstration'},{'limit':True}])
def test_client_cannot_switch_evidence_mode_or_supply_invalid_options(client,evaluation,options):
    assert client.post(URL+'/generate',headers=HEADERS,json={'destinationArea':'Penang',**options}).status_code==400


def test_auth_context_and_missing_data_never_fall_back_to_genuine_or_approve_samples(client,evaluation,monkeypatch):
    assert client.post(URL+'/generate',json={}).status_code==401
    assert client.post(URL+'/generate',headers={'Authorization':'Bearer isolated'},json={}).status_code==403
    client.application.config['LOCAL_FYP_SAMPLE_REVIEWS']=False
    assert client.get(URL,headers=HEADERS).status_code==403
    client.application.config['LOCAL_FYP_SAMPLE_REVIEWS']=True
    monkeypatch.setattr(demo,'load_sources',Mock(side_effect=ValueError('Missing private approvals')))
    response=client.post(URL+'/generate',headers=HEADERS,json={'destinationArea':'Penang'})
    assert response.status_code==503
    assert 'No genuine recommendations were changed' in response.json['error']


@pytest.mark.parametrize('mode',['unknown','fyp_evaluation'])
def test_configuration_requires_explicit_supported_mode_and_restricted_lan(monkeypatch,mode):
    monkeypatch.setenv('RECOMMENDATION_EVIDENCE_MODE',mode)
    with pytest.raises(RuntimeError,match='RECOMMENDATION_EVIDENCE_MODE|restricted local LAN'):
        create_app()


def test_memory_bound_and_learning_updates_are_isolated():
    session=demo.EvaluationSession()
    for i in range(70):
        session.save({'recommendationGenerationId':str(i),'travellerId':'isolated','canonicalDestinationScope':{'scopeKey':'my'}})
    assert len(session.snapshots)==64 and session.snapshot('isolated','0') is None
    assert session.snapshot('different-owner','69') is None
    assert session.learning('isolated') is None
    with pytest.raises(ValueError,match='cannot produce genuine'):
        demo.evaluate({},[],[],evidence_mode='genuine')


def test_explicit_local_configuration_is_accepted_without_changing_default(monkeypatch):
    monkeypatch.setenv('RECOMMENDATION_EVIDENCE_MODE','fyp_evaluation')
    monkeypatch.setenv('LOCAL_LAN_DEMO','true')
    monkeypatch.setenv('APP_ENV','local')
    monkeypatch.setenv('TRUSTED_LAN_CIDR','192.168.100.0/24')
    monkeypatch.setenv('LOCAL_LAN_ORIGINS','')
    with patch('app.init_firebase'):
        app=create_app()
    assert app.config['RECOMMENDATION_EVIDENCE_MODE']=='fyp_evaluation'
    assert app.test_client().get(URL).status_code==401


def test_current_approval_changes_affect_only_explicit_new_evaluation(client,evaluation):
    state, generate, _, _=evaluation
    original=generate(limit=50,discoveryMode=None)
    before=next(r for r in original['recommendations'] if r['destinationId']=='local_penang_hill')
    for row in state['reviews']:
        if row['destinationId']=='local_penang_hill':
            row['feedbackStatus']='removed'
    read=client.get(URL,headers=HEADERS,query_string={'generationId':original['recommendationGenerationId'],'limit':50})
    assert next(r for r in read.json['recommendations'] if r['destinationId']=='local_penang_hill')['collaborativeRatingCount']==before['collaborativeRatingCount']
    new=generate(limit=50,discoveryMode=None)
    assert next(r for r in new['recommendations'] if r['destinationId']=='local_penang_hill')['collaborativeRatingCount']==0
