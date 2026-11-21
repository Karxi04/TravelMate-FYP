"""All records are isolated sample definitions. No Firebase/provider access."""
from copy import deepcopy
import pytest
from services import demonstration_recommendations as demo, fyp_reviews, penang_evaluation_coverage as coverage
from services import review_staging
from services.recommendation_review_evidence import approved_contributions, review_summaries, popularity_evidence
from services.review_service import screen_submission, published_review
from services.review_destination import review_candidate_id
from scripts.plan_penang_fyp_reviews import build_plan
from scripts.plan_penang_fyp_expansion import build_plan as expansion_plan
from sequence_contract import domain_functions as engine
from test_local_reviews import memory, headers


@pytest.fixture
def penang(monkeypatch):
    base, expansion=build_plan(),expansion_plan()
    places=list(base['documents']['fyp_review_datasets/penang_v1']['destinations'].values())
    original=[{**row,'id':key.rsplit('/',1)[-1]} for key,row in [*base['documents'].items(),*expansion['documents'].items()] if 'rating' in row]
    monkeypatch.setenv('FYP_REVIEW_STAGING_PATH','')
    monkeypatch.setattr(demo,'private_dataset',lambda:('isolated-ref',{row['destinationId']:row for row in places}))
    monkeypatch.setattr(demo,'dataset_reviews',lambda *_:deepcopy(original))
    return places,original


def test_coverage_is_existing_canonical_identity_and_real_screening_not_status_override(penang):
    places, original=penang
    assert set(coverage.ATTRACTIONS)==fyp_reviews.PENANG_DESTINATION_IDS=={p['destinationId'] for p in places}
    rows=[row for identity in coverage.ATTRACTIONS for row in coverage.sources(identity)]
    assert len(rows)==72 and len({r['id'] for r in rows})==72
    assert not {r['id'] for r in original} & {r['id'] for r in rows}
    assert {r['rating'] for r in rows}=={2,3,4,5}
    assert len(coverage.REVIEWER_PROFILES)==6
    for row in rows:
        assert row['synthetic'] is True and row['source']=='fyp_private'
        assert row['dataset']==coverage.DATASET and row['travellerId'] in coverage.REVIEWER_PROFILES
        fresh=screen_submission(row['comment'],row['rating'])
        assert row['moderationStatus']==fresh['moderationStatus']=='reviewed'
        assert row['moderationDecision']['actor']=='system'
        assert row['screening']['sentiment']['ratingMismatch'] is False
        assert published_review(row)
    assert not approved_contributions(rows)
    assert len(original)==104 and sum(map(len,approved_contributions(original,demonstration=True).values()))==96


def test_all12_have_profile_coverage_without_changing_formula_or_source_data(penang):
    _, original=penang
    before=deepcopy(original)
    places,rows=demo.load_sources('Penang')
    assert len(rows)==224 and sum(map(len,approved_contributions(rows,demonstration=True).values()))==215
    for profile in demo.SIMULATED_PROFILES.values():
        result=demo.evaluate(profile,places,rows,evidence_mode='fyp_evaluation')
        assert len(result)==18 and coverage.ATTRACTIONS.keys() <= {r['destinationId'] for r in result}
        for item in result:
            assert item['collaborativeRatingCount']>0 and item['collaborativeConfidence']>0
            assert item['popularitySource']=='demonstration_approved_reviews'
            assert item['popularityEvidence']['reviewCount']==len(approved_contributions(rows,demonstration=True)[review_candidate_id(item)])
            assert item['scoreBreakdown']['collaborativeWeight']==.3 and item['scoreBreakdown']['popularityWeight']==.1
    assert original==before
    changed=deepcopy(rows)
    for row in changed:row['rating']=1
    assert demo.simulated_profiles(rows)==demo.simulated_profiles(changed)


def test_local_aggregate_independent_of_profile_but_collaborative_is_personalized(penang):
    places,rows=demo.load_sources('Penang')
    results=[{r['destinationId']:r for r in demo.evaluate(profile,places,rows,evidence_mode='fyp_evaluation')}
             for profile in demo.SIMULATED_PROFILES.values()]
    for identity in coverage.ATTRACTIONS:
        assert len({r[identity]['popularityScore'] for r in results})==1
    assert any(len({r[identity]['collaborativeScore'] for r in results})>1 for identity in coverage.ATTRACTIONS)
    assert all(r['collaborativeRatingCount']==0 for r in engine.applyCollaborativeFiltering(places,rows,demo.simulated_profiles(rows),demo.SIMULATED_PROFILES['culture']))
    assert not review_summaries(approved_contributions(rows))


@pytest.mark.parametrize('invalid',[None,{}, {'rating':5,'reviews':0}, {'rating':6,'reviews':3}, {'rating':4,'reviews':3,'synthetic':False}, {'rating':4,'reviews':3,'source':'genuine_approved_local_reviews'}])
def test_provider_only_when_no_qualifying_local_summary(invalid):
    place={'destinationId':'local_kek_lok_si','ratingSource':'provider','rating':4.5,'reviews':9000}
    local={'rating':3,'reviews':12,'synthetic':True,'source':'demonstration_approved_reviews'}
    valid=popularity_evidence(place,{'local_kek_lok_si':local},demonstration=True)
    assert valid['rating']==3 and valid['reviewCount']==12 and valid['source']=='demonstration_approved_reviews'
    broken={**local,**invalid} if isinstance(invalid,dict) else invalid
    fallback=popularity_evidence(place,{'local_kek_lok_si':broken} if broken else {},demonstration=True)
    if invalid=={}:assert fallback['source']=='demonstration_approved_reviews'
    else:assert fallback['score']==50 and fallback['rating'] is None and fallback['reviewCount'] is None
    neutral=popularity_evidence({**place,'ratingSource':'unknown'},{},demonstration=True)
    assert neutral['score']==50
    assert popularity_evidence(place,{'local_kek_lok_si':local})['source']=='provider_rating_review_count'


def test_supplement_respects_existing_staging_moderation_and_audit_history(monkeypatch,tmp_path,penang):
    path=tmp_path/'isolated-review-moderation.sqlite3'
    monkeypatch.setenv('FYP_REVIEW_STAGING_PATH',str(path))
    review_staging.initialize()
    identity='local_kek_lok_si';source=coverage.sources(identity)[0]
    updates={'feedbackStatus':'hidden','updatedAt':'2026-11-21T03:00:00Z',
             'moderationDecision':{'actor':'admin','outcome':'hide','at':'2026-11-21T03:00:00Z'}}
    review_staging.moderate(source,updates,source)
    effective=fyp_reviews.regional_demo_reviews(identity)
    assert next(r for r in effective if r['id']==source['id'])['feedbackStatus']=='hidden'
    assert not {source['id']} & {r['id'] for r in approved_contributions(effective,demonstration=True)[identity]}
    assert len(review_staging.history(next(r for r in effective if r['id']==source['id'])))==2
    assert coverage.sources(identity)[0]==source


def test_admin_unified_source_includes_new_rows_and_can_moderate_through_existing_contract(client,mock_admin_auth,monkeypatch,tmp_path,penang):
    from modules.fr13_administrator_management import routes
    monkeypatch.setenv('FYP_REVIEW_STAGING_PATH',str(tmp_path/'admin-review-moderation.sqlite3'))
    review_staging.initialize()
    client.application.config['LOCAL_FYP_SAMPLE_REVIEWS']=True
    monkeypatch.setattr(routes,'private_dataset',lambda:None)
    monkeypatch.setattr(routes,'_load',lambda *_:[])
    headers={'Authorization':'Bearer isolated'}
    response=client.get('/api/fr13/feedback?source=all',headers=headers)
    assert response.status_code==200
    rows=[r for r in response.json['items'] if r.get('dataset')==coverage.DATASET]
    assert len(rows)==72 and all(r['reviewSource']=='fyp_regional' for r in rows)
    assert all(r['moderationWritable'] for r in rows)
    target=rows[0]
    url='/api/fr13/feedback/'+target['id']
    payload={'decision':'hide','expectedRevision':target['reviewRevision']}
    assert client.post(url+'/review?source=fyp_regional',headers=headers,json=payload).status_code==200
    assert client.post(url+'/review?source=fyp_regional',headers=headers,json=payload).status_code==409
    history=client.get(url+'/history?source=fyp_regional',headers=headers)
    assert history.status_code==200 and len(history.json['items'])==2


def test_penang_review_lists_badges_and_evaluation_share_moderated_counts(client,memory,monkeypatch,tmp_path,penang):
    from modules.fr03_destination_search_information import routes
    places,original=penang
    source={p['destinationId']:p for p in places}
    monkeypatch.setenv('FYP_REVIEW_STAGING_PATH',str(tmp_path/'penang-review-overlay.sqlite3'))
    review_staging.initialize()
    monkeypatch.setattr(routes,'_private_review_dataset',lambda **_:('isolated-ref',source))
    monkeypatch.setattr(routes,'dataset_reviews',lambda *_:deepcopy(original))
    client.application.config['LOCAL_FYP_SAMPLE_REVIEWS']=True
    identities=['demo_penang_street_art','penang_armenian_street','local_kek_lok_si','local_penang_hill','local_botanical_gardens']
    for account in ['owner','second','new-account']:
        context={**headers(account),'X-TravelMate-Review-Context':'fyp-v1'}
        summaries=client.get('/api/fr3/local-ratings',headers=context).json['items']
        for identity in identities:
            result=client.get('/api/fr3/destinations/'+identity+'/ratings-reviews',headers=context).json['result']
            expected=approved_contributions([*original,*fyp_reviews.regional_demo_reviews(identity)],demonstration=True)[identity]
            assert result['reviews']==len(result['user_reviews'])==len(expected)
            assert len({r['id'] for r in result['user_reviews']})==len(expected)
            assert result['genuineSummary']['reviews']==0
            assert (summaries[identity]['rating'],summaries[identity]['reviews'])==(result['rating'],result['reviews'])
        assert client.get('/api/fr3/destinations/local_kek_lok_si/ratings-reviews',headers=headers(account)).json['result']['reviews']==0
    identity='local_kek_lok_si';selected=fyp_reviews.regional_demo_reviews(identity)[0]
    review_staging.moderate(selected,{'feedbackStatus':'hidden','moderationDecision':{'actor':'admin','outcome':'hide','at':'2026-11-21T03:00:00Z'}},coverage.sources(identity)[0])
    context={**headers(),'X-TravelMate-Review-Context':'fyp-v1'}
    displayed=client.get('/api/fr3/destinations/'+identity+'/ratings-reviews',headers=context).json['result']
    candidates,rows=demo.load_sources('Penang')
    evaluated=next(r for r in demo.evaluate(demo.SIMULATED_PROFILES['culture'],candidates,rows,evidence_mode='fyp_evaluation') if r['destinationId']==identity)
    assert displayed['reviews']==evaluated['popularityEvidence']['reviewCount']==14
    assert not memory
