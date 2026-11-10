"""Paired owner-reviewed evaluation. Never seeds or enriches production records."""
import hashlib
import json
from pathlib import Path

from scripts.recommendation_relevance_audit import rank
from services.recommendation_discovery import discovery_annotations


def evaluate():
    fixtures=Path(__file__).resolve().parents[1]/'tests/fixtures'
    fixture=json.loads((fixtures/'photography_food_discovery.json').read_text(encoding='utf-8'))
    base=fixtures/'penang_core_demo.json'
    assert hashlib.sha256(base.read_bytes()).hexdigest()==fixture['baseFixtureSha256']
    candidates=json.loads(base.read_text(encoding='utf-8'))['candidates']+fixture['additionalCandidates']
    rows=rank(fixture['profile'],candidates)
    assert [row['destinationId'] for row in rows]==fixture['baselineOrdering']
    for row in rows:
        assert all(row[key]==value for key,value in fixture['baselineScores'][row['destinationId']].items())
    annotated=[{**row,**discovery_annotations(row,fixture['profile'])} for row in rows]
    shown=[row for row in annotated if row['discoveryEligible']]
    labels=fixture['judgements']
    def metrics(items):
        result={}
        for k in (5,10):
            selected=items[:k]
            themes=set().union(*(set(labels[row['destinationId']]['themes']) for row in selected)) if selected else set()
            result[f'precision@{k}']=sum(labels[row['destinationId']]['grade']>0 for row in selected)/len(selected) if selected else None
            result[f'strongPrecision@{k}']=sum(labels[row['destinationId']]['grade']==2 for row in selected)/len(selected) if selected else None
            result[f'interestCoverage@{k}']=len(themes & {'photography','food'})/2
        return result
    relevant_ids={did for did,label in labels.items() if label['grade']>0}
    shown_ids={row['destinationId'] for row in shown}
    return {'baselineCommit':fixture['baselineCommit'],'humanReview':fixture['humanReview'],
        'candidateCount':len(candidates),'scoresUnchanged':True,
        'beforeRanking':rows,'afterDiscovery':shown,'beforeRankingMetrics':metrics(rows),
        'afterDiscoveryMetrics':metrics(shown),
        'oldPersonal45Ids':[row['destinationId'] for row in rows if row['personalSuitabilityScore'] is not None and row['personalSuitabilityScore']>=45],
        'oldHybrid80Ids':[row['destinationId'] for row in rows if row['finalScore']>=80],
        'humanRelevantCount':len(relevant_ids),'relevantShownCount':len(shown_ids & relevant_ids),
        'humanRelevantCoverage':len(shown_ids & relevant_ids)/len(relevant_ids),
        'missingHumanRelevantIds':sorted(relevant_ids-shown_ids),
        'invalidRecommendationIds':sorted(shown_ids-relevant_ids),
        'annotations':annotated,'limits':'Seventeen documented identities and one owner review; not a large field study or guarantee of production metadata coverage.'}
