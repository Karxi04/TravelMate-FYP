"""Real routes + disposable SQLite; no live Firebase or running services."""
import os
import sys
from pathlib import Path

if __name__=='__main__':
    os.environ.update(TRAVELMATE_TESTING='true',FALLBACK_MODE='true',LOCAL_LAN_DEMO='false',
        RECOMMENDATION_EVIDENCE_MODE='genuine',FYP_REVIEW_STAGING_PATH='')
    for key in ('FIREBASE_SERVICE_ACCOUNT','FIREBASE_SERVICE_ACCOUNT_JSON','GOOGLE_APPLICATION_CREDENTIALS',
                'SERPAPI_KEY','LITEAPI_KEY','STRIPE_SECRET_KEY','GEMINI_API_KEY'):
        os.environ[key]=''
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import json
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
import pytest

from services import review_staging, fyp_reviews, demonstration_recommendations as demo
from services.review_service import review_revision, ReviewConflict, moderation_state
from test_local_reviews import memory, headers
from test_nationwide_evaluation_reviews import nationwide, generate


def configure(client,memory,monkeypatch,nationwide,path):
    from modules.fr13_administrator_management import routes
    monkeypatch.setenv('FYP_REVIEW_STAGING_PATH',str(path))
    review_staging.initialize()
    profile,blocked,places,private_rows=nationwide
    private_history={}
    genuine_history={}
    monkeypatch.setattr(routes,'private_dataset',lambda:('private-fixture',places))
    monkeypatch.setattr(routes,'dataset_reviews',lambda *_:deepcopy(private_rows))
    def private_commit(ref,expected,updates):
        current=next(r for r in private_rows if r['id']==expected['id'])
        if review_revision(current)!=review_revision(expected):raise ReviewConflict('Refresh and try again.')
        private_history.setdefault(current['id'],[current.get('moderationDecision',{})]).append(updates['moderationDecision'])
        current.update(deepcopy(updates));return deepcopy(current)
    monkeypatch.setattr(routes,'moderate_review',private_commit)
    monkeypatch.setattr(routes,'moderation_history',lambda ref,row:list(reversed(private_history.get(row['id'],[row.get('moderationDecision',{})]))))
    def genuine_commit(collection,identity,updates,expected=None):
        assert collection=='feedback'
        current=memory[collection,identity]
        if expected!=current:raise ReviewConflict('Refresh and try again.')
        genuine_history.setdefault(identity,[current.get('moderationDecision',{})]).append(updates['moderationDecision'])
        current.update(deepcopy(updates));return deepcopy(current)
    monkeypatch.setattr(routes,'updateRecord',genuine_commit)
    monkeypatch.setattr(routes,'review_history',lambda identity:list(reversed(genuine_history.get(identity,[]))))
    monkeypatch.setattr('auth_utils.get_db',lambda:SimpleNamespace(collection=lambda _:SimpleNamespace(
        document=lambda uid:SimpleNamespace(get=lambda:SimpleNamespace(exists=True,to_dict=lambda:{
            'role':'admin' if uid in {'admin','admin-two'} else 'traveller','status':'active'})))))
    return {'path':path,'profile':profile,'blocked':blocked,'private':private_rows}


@pytest.fixture
def moderated(client,memory,nationwide,monkeypatch,tmp_path):
    return configure(client,memory,monkeypatch,nationwide,tmp_path/'moderation.sqlite3')


def listing(client):
    result=client.get('/api/fr13/feedback?source=all',headers=headers('admin'))
    assert result.status_code==200,result.json
    return result.json['items']


def act(client,row,action,note='',**override):
    return client.post('/api/fr13/feedback/'+row['id']+'/review?source='+row['reviewSource'],headers=headers('admin'),
        json={'decision':action,'expectedRevision':row['reviewRevision'],'comment':note,**override})


@pytest.mark.parametrize('identity',['demo_penang_street_art','penang_armenian_street','local_kek_lok_si','local_my_perak_zoo_taiping'])
def test_full_moderation_algorithm_lifecycle_and_immutable_generations(client,moderated,identity):
    # Include low-rated, sentiment-compatible contributions: hiding one can raise
    # the aggregate, so moderation must never assume approval means a higher score.
    row=min((r for r in listing(client) if r['destinationId']==identity and r['reviewSource']=='fyp_regional'
             and moderation_state(r)=='approved'),key=lambda r:r['rating'])
    source=deepcopy(next(r for r in fyp_reviews._regional_sources(identity) if r['id']==row['id']))
    area='Perak' if 'perak' in identity else 'Penang'
    previous=generate(client,area)
    session=client.application.extensions['recommendation_evaluation']
    saved=session.snapshot('owner',previous['recommendationGenerationId'])
    def metrics(body):
        item=next(r for r in body['recommendations'] if r['destinationId']==identity)
        assert item['finalScore']==pytest.approx(item['contentScore']*.6+item['collaborativeScore']*.3+item['popularityScore']*.1,abs=.02)
        return item
    baseline=metrics(previous)
    evidence=[]
    def record(action,item):
        evidence.append({'action':action,'approvedCount':item['popularityEvidence']['reviewCount'],
            'rating':item['popularityEvidence']['rating'],'popularity':item['popularityScore'],
            'eligiblePeers':item['collaborativeRatingCount'],'rawPeerScore':item['rawCollaborativeScore'],
            'confidence':item['collaborativeConfidence'],'collaborative':item['collaborativeScore'],
            'content':item['contentScore'],'hybrid':item['finalScore']})
    record('before',baseline)
    for action,note,delta,state in [('hide','',-1,'hidden'),('restore','Restore after review',0,'approved'),
                                  ('reverse','Approval reversed after audit',-1,'rejected'),('restore','Reapprove after audit',0,'approved')]:
        row=next(r for r in listing(client) if r['id']==source['id'])
        result=act(client,row,action,note)
        assert result.status_code==200,result.json
        assert moderation_state(result.json['feedback'])==state
        assert act(client,row,action,note).status_code==409
        old=client.get('/api/fr4/recommendations',headers={**headers(),'X-TravelMate-Review-Context':'fyp-v1'},
            query_string={'generationId':previous['recommendationGenerationId']})
        assert old.json['staleReason']=='review_evidence_changed' and old.json['requiresExplicitRegeneration']
        assert not old.json['recommendations']
        assert session.snapshot('owner',saved['recommendationGenerationId'])==saved
        new=generate(client,area,previousGenerationId=previous['recommendationGenerationId'])
        current=metrics(new)
        assert current['popularityEvidence']['reviewCount']==baseline['popularityEvidence']['reviewCount']+delta
        expected_mean=(baseline['popularityEvidence']['rating']*baseline['popularityEvidence']['reviewCount']
                       - (source['rating'] if delta else 0))/(baseline['popularityEvidence']['reviewCount']+delta)
        assert current['popularityEvidence']['rating']==pytest.approx(expected_mean)
        assert current['demonstrationReviewSummary']['reviews']==current['popularityEvidence']['reviewCount']
        assert current['collaborativeRatingCount']<=baseline['collaborativeRatingCount']
        assert current['collaborativeConfidence']<=baseline['collaborativeConfidence']
        record(action,current)
        previous=new
    history=client.get('/api/fr13/feedback/'+source['id']+'/history?source=fyp_regional',headers=headers('admin'))
    assert [e['outcome'] for e in history.json['items'][:4]]==['restore','revoke','restore','hide']
    assert next(r for r in fyp_reviews._regional_sources(identity) if r['id']==source['id'])==source
    assert not moderated['blocked'].called
    print('MODERATION_EVIDENCE='+json.dumps({'destination':identity,'contributionRating':source['rating'],'steps':evidence}))


def test_pending_private_and_national_reviews_and_genuine_records_use_valid_actions(client,moderated,memory):
    pending=[r for r in listing(client) if moderation_state(r)=='pending']
    for origin,action in [('fyp_penang','keep'),('fyp_regional','reject')]:
        row=next(r for r in pending if r['reviewSource']==origin)
        from services import national_evaluation_reviews
        area='Penang' if origin=='fyp_penang' else national_evaluation_reviews.destinations()[row['destinationId']]['state']
        before=next(r for r in generate(client,area)['recommendations'] if r['destinationId']==row['destinationId'])
        response=act(client,row,action,'Reviewed rating and comment')
        assert response.status_code==200,response.json
        assert moderation_state(response.json['feedback'])==('approved' if action=='keep' else 'rejected')
        assert response.json['feedback']['synthetic'] is True
        after=next(r for r in generate(client,area)['recommendations'] if r['destinationId']==row['destinationId'])
        assert after['popularityEvidence']['reviewCount']==before['popularityEvidence']['reviewCount']+(1 if action=='keep' else 0)
        for item in [before,after]:
            assert item['finalScore']==pytest.approx(item['contentScore']*.6+item['collaborativeScore']*.3+item['popularityScore']*.1,abs=.02)
        print('PENDING_MODERATION_EVIDENCE='+json.dumps({'source':origin,'destination':row['destinationId'],'action':action,
            'steps':[{key:item[key] for key in ['popularityEvidence','popularityScore','collaborativeRatingCount',
                'rawCollaborativeScore','collaborativeConfidence','collaborativeScore','contentScore','finalScore']} for item in [before,after]]}))
    row=next(r for r in listing(client) if r['reviewSource']=='fyp_regional' and moderation_state(r)=='approved')
    assert act(client,row,'reject').status_code==409
    assert act(client,row,'reverse').status_code==400
    assert act(client,row,'invented').status_code==400
    memory['feedback','real-fixture']={'id':'real-fixture','travellerId':'owner','destinationId':'isolated',
        'rating':2,'comment':'A disappointing visit.','moderationStatus':'pending_review','feedbackStatus':'visible'}
    for action,note in [('keep',''),('hide',''),('restore','Reviewed for restoration')]:
        row=next(r for r in listing(client) if r['id']=='real-fixture')
        response=act(client,row,action,note)
        assert response.status_code==200,response.json
    assert not memory['feedback','real-fixture'].get('synthetic')
    assert len(client.get('/api/fr13/feedback/real-fixture/history',headers=headers('admin')).json['items'])==4


def test_concurrent_admin_decisions_one_commit_and_no_unauthorized_mutation(client,moderated):
    row=next(r for r in listing(client) if r['reviewSource']=='fyp_regional' and moderation_state(r)=='approved')
    path='/api/fr13/feedback/'+row['id']+'/review?source=fyp_regional'
    command={'decision':'hide','expectedRevision':row['reviewRevision']}
    assert client.post(path,headers=headers(),json=command).status_code==403
    def submit(actor):
        with client.application.test_client() as other:
            return other.post(path,headers=headers(actor),json=command).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit,['admin','admin-two']))==[200,409]
    events=client.get('/api/fr13/feedback/'+row['id']+'/history?source=fyp_regional',headers=headers('admin')).json['items']
    assert len(events)==2


def test_storage_failure_is_closed_and_never_republishes_source_defaults(client,moderated,monkeypatch,tmp_path):
    monkeypatch.setenv('FYP_REVIEW_STAGING_PATH',str(tmp_path/'missing.sqlite3'))
    assert not review_staging.ready()
    assert client.get('/api/fr3/destinations/local_kek_lok_si/ratings-reviews',headers={**headers(),'X-TravelMate-Review-Context':'fyp-v1'}).status_code==503
    assert generate_unavailable(client)==503
    result=client.get('/api/fr13/feedback?source=all',headers=headers('admin'))
    assert result.status_code==200 and result.json['regionalUnavailable']
    assert all(r['reviewSource']!='fyp_regional' for r in result.json['items'])
    assert not (tmp_path/'missing.sqlite3').exists()


def generate_unavailable(client):
    return client.post('/api/fr4/recommendations/generate',headers={**headers(),'X-TravelMate-Review-Context':'fyp-v1'},json={'destinationArea':'Penang'}).status_code


def test_sqlite_decisions_survive_a_separate_python_process(client,moderated):
    import subprocess
    row=next(r for r in listing(client) if r['reviewSource']=='fyp_regional' and moderation_state(r)=='approved')
    assert act(client,row,'hide','Persistence check').status_code==200
    code="import json; from services.fyp_reviews import regional_demo_reviews; from services.review_staging import history; rows=regional_demo_reviews("+repr(row['destinationId'])+"); r=next(x for x in rows if x['id']=="+repr(row['id'])+"); print(json.dumps({'status':r['moderationStatus'],'outcome':r['moderationDecision']['outcome'],'events':len(history(r))}))"
    result=subprocess.run([sys.executable,'-B','-c',code],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=15,check=True)
    assert json.loads(result.stdout)=={'status':'removed','outcome':'hide','events':2}


def test_overlay_cannot_change_provenance_or_accept_genuine_records(moderated):
    source=fyp_reviews._regional_sources('demo_penang_street_art')[0]
    for invalid in [{'synthetic':False},{'travellerId':'another'},{'dataset':'genuine'}]:
        with pytest.raises(ValueError):
            review_staging.moderate(source,invalid,source)
    with pytest.raises(ValueError):
        review_staging.moderate({**source,'synthetic':False},{}, {**source,'synthetic':False})
    assert review_staging.overlay_rows([source])==[source]
    assert moderation_state({'moderationStatus':'rejected','feedbackStatus':'removed'})=='rejected'
    assert moderation_state({'moderationStatus':'removed','feedbackStatus':'removed'})=='hidden'


def test_corrupt_overlay_is_unavailable_not_a_reset_to_approved_defaults(client,moderated):
    moderated['path'].write_bytes(b'not a sqlite database')
    assert not review_staging.ready()
    with pytest.raises(review_staging.ReviewStagingUnavailable):
        review_staging.overlay_rows(fyp_reviews._regional_sources('demo_penang_street_art'))
    assert generate_unavailable(client)==503


def test_setup_refuses_an_unrelated_database_without_changing_its_tables(monkeypatch,tmp_path):
    import sqlite3
    target=tmp_path/'unrelated.sqlite3'
    with sqlite3.connect(target) as db:db.execute('CREATE TABLE unrelated (id TEXT)')
    monkeypatch.setenv('FYP_REVIEW_STAGING_PATH',str(target))
    with pytest.raises(ValueError):review_staging.initialize()
    with sqlite3.connect(target) as db:
        assert list(db.execute("SELECT name FROM sqlite_master WHERE type='table'"))==[('unrelated',)]


@pytest.mark.skipif(sys.platform!='win32',reason='Windows ACL provisioning test')
def test_owner_controlled_setup_plan_and_restricted_disposable_database(tmp_path):
    import subprocess
    script=Path(__file__).resolve().parents[1]/'scripts/prepare_review_staging.ps1'
    target=tmp_path/'private-staging'/'reviews.sqlite3'
    command=['pwsh','-NoProfile','-File',str(script),'-StagingPath',str(target)]
    planned=subprocess.run(command,capture_output=True,text=True,timeout=15)
    assert planned.returncode==0,planned.stderr
    assert not target.exists() and not target.parent.exists()
    prepared=subprocess.run([*command,'-Apply'],capture_output=True,text=True,timeout=20)
    assert prepared.returncode==0,prepared.stderr
    assert target.is_file() and 'True' in prepared.stdout


if __name__=='__main__':
    import pytest_socket
    pytest_socket.disable_socket()
    from app import create_app
    mp=pytest.MonkeyPatch()
    with patch('app.init_firebase'):
        application=create_app()
    client=application.test_client()
    records=memory.__wrapped__(mp)
    state=nationwide.__wrapped__(client,records,mp)
    configure(client,records,mp,state,Path(sys.argv[1]))
    for line in sys.stdin:
        message=json.loads(line)
        response=client.open(message['path'],method=message.get('method','GET'),json=message.get('body'),
            headers=headers(message.get('actor','admin')))
        print('BRIDGE_RESPONSE '+json.dumps({'status':response.status_code,'data':response.json}),flush=True)
