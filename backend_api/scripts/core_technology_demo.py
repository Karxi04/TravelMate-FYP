r"""Reproducible isolated FYP replay. All repositories/auth/providers are test doubles.

Run with --output D:\workspace\...; never seeds Firebase or public feedback.
"""
import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import date
import csv
import json
import os
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.malaysian_locality import normalize_destination_scope

FIXTURE=Path(__file__).resolve().parents[1]/'tests/fixtures/penang_core_demo.json'


class IsolatedRepository:
    def __init__(self):
        self.records={}
        self.counter=0
    def read(self,collection,document=None,filters=None,limit=None,**kwargs):
        if document is not None:
            value=self.records.get((collection,str(document)))
            return {'id':str(document),**deepcopy(value)} if value is not None else None
        rows=[{'id':key,**deepcopy(value)} for (coll,key),value in self.records.items() if coll==collection
              and all(value.get(field)==expected for field,op,expected in filters or [])]
        return rows[:limit] if limit else rows
    def store(self,collection,data,document=None,merge=False,**kwargs):
        self.counter+=1
        key=str(document or data.get('id') or f'isolated_{collection}_{self.counter}')
        current=self.records.get((collection,key),{}) if merge else {}
        self.records[(collection,key)]={**current,**deepcopy(data)}
        return {'id':key,**deepcopy(self.records[(collection,key)])}
    def update(self,collection,document,data,**kwargs):
        return self.store(collection,data,document,merge=True)
    def claim(self,collection,document,data):
        existing=self.read(collection,document)
        return (existing,False) if existing else (self.store(collection,data,document),True)
    def learning(self,uid,transform):
        updated,event,changed=transform(self.read('learned_preference_profiles',uid))
        if event is not None:
            self.store('learned_preference_profiles',updated,uid)
            self.store('recommendation_feedback_events',event,event['feedbackEventId'])
        return updated,event,changed


def run_demo():
    fixture=json.loads(FIXTURE.read_text(encoding='utf-8'))
    repo=IsolatedRepository()
    peers={}
    reviews=[]
    for label,profile in fixture['profiles'].items():
        repo.store('travel_preferences',profile,profile['travellerId'])
        for index,rating in enumerate((5,4)):
            uid=f'isolated_peer_{label}_{index}'
            peers[uid]={**profile,'travellerId':uid}
            repo.store('travel_preferences',peers[uid],uid)
            for direction,value in [('like',rating),('dislike',6-rating)]:
                reviews.append({'id':f'isolated_review_{label}_{index}_{direction}','travellerId':uid,
                    'destinationId':fixture['actions'][label][direction],'rating':value,
                    'feedbackStatus':'visible','moderationStatus':'reviewed','source':'isolated_demo_fixture'})
    for review in reviews:repo.store('feedback',review,review['id'])
    scope=normalize_destination_scope('Penang')['scopeKey']
    for candidate in fixture['candidates']:
        repo.store('destination_cache',{**candidate,'canonicalDestinationScope':scope},candidate['destinationId'])

    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ,{'FALLBACK_MODE':'false','SERPAPI_KEY':'','TRAVELMATE_TESTING':'true'}))
        stack.enter_context(patch('requests.sessions.Session.request',side_effect=AssertionError('Network disabled in isolated demo')))
        stack.enter_context(patch('app.init_firebase'))
        from app import create_app
        app=create_app();app.config['TESTING']=True
        auth=stack.enter_context(patch('auth_utils.auth.verify_id_token'))
        database=MagicMock()
        snapshot=MagicMock(exists=True)
        snapshot.to_dict.return_value={'role':'traveller','status':'active','name':'Isolated demonstration traveller'}
        database.collection.return_value.document.return_value.get.return_value=snapshot
        stack.enter_context(patch('auth_utils.get_db',return_value=database))
        for module in ('modules.fr04_hybrid_recommendation.routes','modules.fr11_chatbot_travel_assistant.routes'):
            for name,operation in [('retrieveRecord',repo.read),('storeRecord',repo.store),('updateRecord',repo.update),('claimRecord',repo.claim)]:
                stack.enter_context(patch(module+'.'+name,side_effect=operation,create=True))
        stack.enter_context(patch('modules.fr04_hybrid_recommendation.routes.transactPreferenceLearning',side_effect=repo.learning))
        chat='modules.fr11_chatbot_travel_assistant.routes.'
        stack.enter_context(patch(chat+'DESTINATIONS',deepcopy(fixture['candidates'])))
        for name in ('generateChatbotResponse','generateFollowUpResponse'):
            stack.enter_context(patch(chat+name,return_value={'reply':'Isolated provider stub; structured places come from the fixture.','source':'isolated_fixture'}))
        client=app.test_client()
        for module in ('modules.fr11_chatbot_travel_assistant.guided_planning','modules.fr11_chatbot_travel_assistant.travel_dates'):
            stack.enter_context(patch(module+'.malaysian_today',return_value=date(2026,11,8)))
        headers={'Authorization':'Bearer isolated-token'}
        output={'scope':fixture['scope'],'candidateCount':len(fixture['candidates']),'profiles':{},'peerFeedback':reviews,
                'providerCalls':0,'productionWrites':0,'authenticatedEvidence':'Mocked authentication through actual Flask handlers; not live account acceptance.'}
        for label,profile in fixture['profiles'].items():
            uid=profile['travellerId'];auth.return_value={'uid':uid}
            actions=fixture['actions'][label]
            phases={}
            previous=''
            for phase,feedback in [('initial',None),('after_like','more_like_this'),('after_dislike','not_for_me')]:
                if feedback:
                    did=actions['like' if feedback=='more_like_this' else 'dislike']
                    response=client.post('/api/fr4/preference-feedback',headers=headers,json={
                        'destinationId':did,'recommendationGenerationId':previous,'feedbackType':feedback})
                    assert response.status_code==200,response.json
                    stale=client.get('/api/fr4/recommendations',headers=headers)
                    assert stale.json['stale'] and not stale.json['recommendations']
                response=client.post('/api/fr4/recommendations/generate',headers=headers,json={
                    'destinationArea':'Penang','minimumMatchScore':0,'limit':50,
                    **({'previousGenerationId':previous} if previous else {})})
                assert response.status_code==200,response.json
                previous=response.json['recommendationGenerationId']
                learned=repo.read('learned_preference_profiles',uid)
                phases[phase]={'ranking':response.json['recommendations'],
                    'qualifiedAt70':[i['destinationId'] for i in response.json['recommendations'] if i['finalScore']>=70],
                    'learnedProfile':deepcopy(learned or {})}
            first=client.post('/api/fr11/chat',headers=headers,json={'message':'Plan a 3-day Penang trip with a budget of RM600.','guidedPlanning':True})
            assert first.status_code==200,first.json
            session_id=first.json['session']['id']
            completed=client.post('/api/fr11/chat',headers=headers,json={'message':'12 June 2027 to 14 June 2027, 1 traveller.',
                'sessionId':session_id,'guidedPlanning':True})
            assert completed.status_code==200,completed.json
            plan=completed.json.get('tripPlan') or (completed.json.get('item') or {}).get('tripPlan')
            assert plan and plan['destinationArea']=='Penang' and plan['tripDays']==3 and plan['budgetLimit']==600,completed.json
            assert {a['dayNo'] for a in plan['activities']}=={1,2,3},plan
            assert repo.read('travel_preferences',uid)['interests']==profile['interests']
            output['profiles'][label]={'baseProfile':profile,'actions':actions,'phases':phases,
                'chat':{'firstRequest':first.json,'completedRequest':completed.json,'structuredPlan':plan}}
        for (collection,key),row in repo.records.items():
            if collection in {'chat_sessions','chat_messages','learned_preference_profiles'}:
                assert row.get('travellerId') in {p['travellerId'] for p in fixture['profiles'].values()}
        return output


def write_evidence(result,output):
    output.mkdir(parents=True,exist_ok=True)
    (output/'PENANG_DEMO.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    with (output/'PENANG_SCORES.csv').open('w',encoding='utf-8',newline='') as handle:
        writer=csv.writer(handle)
        writer.writerow(['profile','phase','rank','destinationId','title','content','collaborative','popularity','final','reason'])
        for label,profile in result['profiles'].items():
            for phase,details in profile['phases'].items():
                for row in details['ranking']:
                    writer.writerow([label,phase,row['rankNo'],row['destinationId'],row['title'],row['contentScore'],
                        row['collaborativeScore'],row['popularityScore'],row['finalScore'],row['recommendationReason']])
    lines=['# Isolated Penang demonstration: actual outputs','',result['scope'],
        '', 'No live Gemini, SerpApi, Firebase, public review, payment or booking operation occurred.',
        'Authentication is mocked through the real Flask handlers. Dates are completed in a second turn because a duration is not a chosen calendar date.',
        'Provider ratings, prices and opening hours are absent. Neutral popularity is labelled; budget completeness is not guaranteed.','']
    for label,profile in result['profiles'].items():
        lines += [f'## Profile {label}', '',json.dumps(profile['baseProfile']), '',
                  '| Phase | First three destinations | Qualified at 70 |','|---|---|---:|']
        for phase,details in profile['phases'].items():
            lines.append(f"| {phase} | {'; '.join(row['title'] for row in details['ranking'][:3])} | {len(details['qualifiedAt70'])} |")
        baseline={r['destinationId']:r for r in profile['phases']['initial']['ranking']}
        positive={r['destinationId']:r for r in profile['phases']['after_like']['ranking']}
        liked=profile['actions']['like']
        lines += ['',f"Liked destination: {baseline[liked]['finalScore']} -> {positive[liked]['finalScore']}; rank {baseline[liked]['rankNo']} -> {positive[liked]['rankNo']}. A score increase need not change rank.",
                  'The explicitly disliked destination is excluded from the next list until feedback is changed/reset. Related concepts retain bounded negative learning.',
                  '', 'Itinerary activities: '+', '.join(a['activityName'] for a in profile['chat']['structuredPlan']['activities']),
                  'Budget status: '+str(profile['chat']['structuredPlan'].get('budgetEstimate',{}).get('status')), '']
    (output/'PENANG_DEMO.md').write_text('\n'.join(lines),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    resolved=args.output.resolve()
    workspace=Path(r'D:\workspace').resolve()
    if not resolved.is_relative_to(workspace):parser.error('Evidence must be written under D:\\workspace.')
    result=run_demo();write_evidence(result,resolved)
    print(json.dumps({'profiles':list(result['profiles']),'candidates':result['candidateCount'],'networkCalls':0,'publicWrites':0}))
