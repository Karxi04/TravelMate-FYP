"""Reproducible, offline paired evaluation; judgements are engineering assumptions."""
import argparse
from copy import deepcopy
import csv
import hashlib
import json
from math import log2
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sequence_contract.domain_functions import (
    applyCollaborativeFiltering,applyContentBasedFiltering,calculateRecommendationScore,
    diversifyRecommendations,prepareRecommendationInput,rankRecommendations,
)
from services.preference_learning import apply_explicit_feedback,effective_preference_profile,reset_learning_profile

FIXTURES=Path(__file__).resolve().parents[1]/'tests/fixtures'


def rank(profile,candidates,feedback=(),peers=None):
    rows=calculateRecommendationScore(applyCollaborativeFiltering(
        applyContentBasedFiltering(prepareRecommendationInput(profile,candidates)),feedback,peers or {},profile,profile.get('travellerId')))
    return diversifyRecommendations(rankRecommendations(rows),profile,limit=150)


def metrics(rows,labels):
    result={}
    for k in (5,10):
        grades=[labels[row['destinationId']]['grade'] for row in rows[:k]]
        ideal=sorted((entry['grade'] for entry in labels.values()),reverse=True)[:k]
        dcg=sum((2**grade-1)/log2(i+2) for i,grade in enumerate(grades))
        idcg=sum((2**grade-1)/log2(i+2) for i,grade in enumerate(ideal))
        result.update({f'precision@{k}':sum(g>=1 for g in grades)/k,
                       f'primaryPrecision@{k}':sum(g==2 for g in grades)/k,
                       f'nDCG@{k}':round(dcg/idcg,4) if idcg else None})
    return result


def evaluate():
    fixture_path=FIXTURES/'penang_core_demo.json'
    fixture=json.loads(fixture_path.read_text(encoding='utf-8'))
    baseline=json.loads((FIXTURES/'recommendation_relevance_baseline.json').read_text(encoding='utf-8'))
    judgements=json.loads((FIXTURES/'recommendation_relevance_judgements.json').read_text(encoding='utf-8'))
    parity=json.loads((FIXTURES/'recommendation_parity.json').read_text(encoding='utf-8'))
    digest=hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    assert digest==baseline['candidateFixtureSha256']==judgements['candidateFixtureSha256']
    candidates=fixture['candidates'];ids={row['destinationId'] for row in candidates}
    result={'baselineCommit':baseline['commit'],'candidateCount':len(ids),'candidateFixtureSha256':digest,
            'judgements':judgements['purpose'],'threshold':70,'rankingWeights':[.6,.3,.1],
            'scenarios':{},'feedback':{},'providerCalls':0,'productionWrites':0}
    for scenario,reviews,peers in [('cold_start',[],{}),('similar_peers',parity['feedback'],parity['peers'])]:
        profiles={}
        for label,profile in fixture['profiles'].items():
            labels=judgements['profiles'][label];assert set(labels)==ids
            old=baseline['scenarios'][scenario][label];current=rank(profile,candidates,reviews,peers)
            assert {row['destinationId'] for row in old}=={row['destinationId'] for row in current}==ids
            qualified=[row for row in current if row['personalSuitabilityScore'] is not None and row['personalSuitabilityScore']>=70]
            profiles[label]={'before':old,'after':current,'beforeMetrics':metrics(old,labels),'afterMetrics':metrics(current,labels),
                'beforeHybridQualified':[row['destinationId'] for row in old if row['finalScore']>=70],
                'afterHybridQualified':[row['destinationId'] for row in current if row['finalScore']>=70],
                'afterPersonalQualified':[row['destinationId'] for row in qualified],
                'personalQualifiedRelevancePrecision':round(sum(labels[row['destinationId']]['grade']>=1 for row in qualified)/len(qualified),4) if qualified else None,
                'personalRelevantCoverage':round(sum(labels[row['destinationId']]['grade']>=1 for row in qualified)/sum(entry['grade']>=1 for entry in labels.values()),4)}
        result['scenarios'][scenario]=profiles
    for label,profile in fixture['profiles'].items():
        before=rank(profile,candidates);actions=fixture['actions'][label]
        target=next(row for row in before if row['destinationId']==actions['like'])
        learned,event,changed=apply_explicit_feedback(None,user_id=profile['travellerId'],destination_id=target['destinationId'],feedback_type='more_like_this',destination_concepts=target['destinationConcepts'])
        assert changed and event
        repeated,_,changed=apply_explicit_feedback(learned,user_id=profile['travellerId'],destination_id=target['destinationId'],feedback_type='more_like_this',destination_concepts=target['destinationConcepts'])
        assert not changed and repeated==learned
        strengths={}
        for strength in (.10,.20,.30):
            with patch('sequence_contract.domain_functions.LEARNED_INTEREST_STRENGTH',strength):
                after=rank(effective_preference_profile(profile,learned),candidates)
            row=next(row for row in after if row['destinationId']==target['destinationId'])
            strengths[str(strength)]={'beforeHybrid':target['finalScore'],'afterHybrid':row['finalScore'],
                'beforePersonal':target['personalSuitabilityScore'],'afterPersonal':row['personalSuitabilityScore'],
                'beforeRank':target['rankNo'],'afterRank':row['rankNo']}
        disliked=next(row for row in before if row['destinationId']==actions['dislike'])
        negative,_,_=apply_explicit_feedback(learned,user_id=profile['travellerId'],destination_id=disliked['destinationId'],feedback_type='not_for_me',destination_concepts=disliked['destinationConcepts'])
        excluded=disliked['destinationId'] not in {row['destinationId'] for row in rank(effective_preference_profile(profile,negative),candidates)}
        reset,_,_=reset_learning_profile(negative,user_id=profile['travellerId'])
        assert rank(effective_preference_profile(profile,reset),candidates)==before
        result['feedback'][label]={'liked':target['destinationId'],'strengthExperiments':strengths,'disliked':disliked['destinationId'],
            'exactNegativeExcluded':excluded,'repeatStacks':False,'resetRestoresOriginalRanking':True,'questionnaire':deepcopy(profile)}
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    output=Path(args.output).resolve()
    if not output.is_relative_to(Path('D:/workspace').resolve()):raise ValueError('Export audit evidence under D:/workspace.')
    output.mkdir(parents=True,exist_ok=True);result=evaluate()
    (output/'PENANG_EVALUATION.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    with (output/'PENANG_SCORES.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['scenario','profile','algorithm','rank','destination','personalSuitability','content','collaborative','popularity','hybrid','qualifiedAt70'])
        for scenario,profiles in result['scenarios'].items():
            for label,phases in profiles.items():
                for phase in ('before','after'):
                    for row in phases[phase]:
                        personal=row.get('personalSuitabilityScore');qualified=row['finalScore']>=70 if phase=='before' else personal is not None and personal>=70
                        writer.writerow([scenario,label,phase,row['rankNo'],row['destinationId'],personal,row['contentScore'],row['collaborativeScore'],row['popularityScore'],row['finalScore'],qualified])
    print(json.dumps({scenario:{label:{'before':p['beforeMetrics'],'after':p['afterMetrics'],'oldHybridQualified':len(p['beforeHybridQualified']),'newPersonalQualified':len(p['afterPersonalQualified'])} for label,p in profiles.items()} for scenario,profiles in result['scenarios'].items()},indent=2))


if __name__=='__main__':main()
