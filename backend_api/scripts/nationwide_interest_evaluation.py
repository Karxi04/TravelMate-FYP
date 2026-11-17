"""Frozen paired engineering evaluation; zero HTTP, Firebase or owner writes."""
import json, sys, hashlib
from pathlib import Path
from itertools import combinations
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'backend_api'),str(ROOT/'backend_api/scripts')]
import batch_d_discovery_evaluation as existing
existing.BASELINE='15835b5d660e975cd6bb1f3d55e1aba406069466'
from services import recommendation_taxonomy as taxonomy

PROFILES={'A':['Culture','Heritage'],'B':['Nature','Shopping'],'C':['Food','Photography'],
          'D':['Nature','Adventure'],'E':['Shopping'],'F':['Culture','Food','Nature']}
def evaluate():
    pool,labels=existing.mock_pool()
    pool=[row for row in pool if row['state']=='Penang']
    # Same frozen, neutral context; increase supply without adding new category judgements.
    pool=[{**row,'destinationId':row['destinationId']+f'_{i}','title':row['title']+f' variant {i}'} for row in pool for i in range(3)]
    labels={row['destinationId']:existing.CATEGORY_LABELS[row['type_id']] for row in pool}
    report={'baseline':existing.BASELINE,'poolSha256':hashlib.sha256(json.dumps(pool,sort_keys=True).encode()).hexdigest(),
            'labels':'Previously frozen engineering category judgements, not visitor ground truth',
            'liveRequests':0,'productionWrites':0,'before':{},'after':{}}
    for old in (True,False):
        target=report['before' if old else 'after']; sets={}
        with existing.algorithms(old) as (d,t,disc,geo):
            for name,interests in PROFILES.items():
                pref={'interests':interests,'travelPace':'Moderate','budgetRange':'Moderate'}
                accepted,_=geo.filter_candidates(pool,geo.normalize_destination_scope('Penang'))
                scores=d.calculateRecommendationScore(d.applyCollaborativeFiltering(d.applyContentBasedFiltering(d.prepareRecommendationInput(pref,accepted)),[],{},pref,'fixture'))
                ranked=d.diversifyRecommendations(scores,pref,limit=150,**({} if old else {'coverageAware':True}))
                ranked=[r for r in ranked if disc.discovery_annotations(r,pref)['discoveryEligible']]
                wanted=t.preference_concepts(interests)
                grades={key:max((v.get(c,0) for c in wanted),default=0) for key,v in labels.items()}
                metrics=existing.metrics(ranked,grades,t,len(pool),len(accepted))
                metrics['interestCoverage']={str(k):{c:sum(c in labels[r['destinationId']] for r in ranked[:k]) for c in sorted(wanted)} for k in (5,6,10)}
                metrics['eligiblePerInterest']={c:sum(c in labels[r['destinationId']] for r in ranked) for c in sorted(wanted)}
                metrics['hybridScoresAt10']=[r['score'] for r in ranked[:10]]
                metrics['meanHybridAt10']=sum(r['score'] for r in ranked[:10])/max(1,len(ranked[:10]))
                metrics['incorrectAt10']=sum(not grades[r['destinationId']] for r in ranked[:10])
                metrics['categoryDiversityAt10']=len({r.get('type_id') for r in ranked[:10]})
                metrics['contribution']={'fixture':len(pool),'liveProvider':0,'productionCache':0}
                metrics['emptyCategoryReasons']={c:'No labelled eligible fixture candidate' for c,n in metrics['eligiblePerInterest'].items() if not n}
                target[name]=metrics; sets[name]=metrics['idsAt10']
            target['overlap']={a+b:{'jaccard':len(set(sets[a])&set(sets[b]))/max(1,len(set(sets[a])|set(sets[b]))),
                                     'commonRankDisplacement':sum(abs(sets[a].index(k)-sets[b].index(k)) for k in set(sets[a])&set(sets[b]))}
                               for a,b in combinations(PROFILES,2)}
    # Direct hybrid-score stress pool: all candidates have strong primary evidence.
    from sequence_contract.domain_functions import diversifyRecommendations
    stress=[{'destinationId':f'{c}{i}','score':score,'type_id':kind,'destinationConcepts':[c],
             'interestEvidenceSource':'primary_metadata','contentSignals':{'interests':{'score':100}}}
            for c,score,kind in [('nature',90,'park'),('shopping',80,'shopping_mall')] for i in range(8)]
    report['stress']={str(mode):[r['destinationId'] for r in diversifyRecommendations(stress,{'interests':['Nature','Shopping']},6,coverageAware=mode)] for mode in (False,True)}
    human_bytes=(existing.FIXTURES/'photography_food_discovery.json').read_bytes()
    human=json.loads(human_bytes)
    venues=json.loads((existing.FIXTURES/'penang_core_demo.json').read_text(encoding='utf-8'))['candidates']+human['additionalCandidates']
    report['humanLabelSha256']=hashlib.sha256(human_bytes).hexdigest()
    report['ownerReviewed']={}
    for old in (True,False):
        with existing.algorithms(old) as (d,t,disc,geo):
            original=d.diversifyRecommendations
            def aware(*args,**kwargs):
                kwargs['coverageAware']=True
                return original(*args,**kwargs)
            if not old: d.diversifyRecommendations=aware
            try:
                result,accepted=existing.rank(d,disc,geo,human['profile'],venues)
                report['ownerReviewed']['before' if old else 'after']=existing.metrics(result,
                    {k:v['grade'] for k,v in human['judgements'].items()},t,len(venues),accepted)
            finally: d.diversifyRecommendations=original
    return report
if __name__=='__main__': print(json.dumps(evaluate(),indent=2,allow_nan=False))
