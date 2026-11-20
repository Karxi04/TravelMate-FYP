"""Offline 12-attraction comparison; no Firebase/provider initialization or import.

Existing examples stay synthetic. Genuine eligibility is tested using separate
isolated contract fixtures in memory, never deployed as customer records.
"""
import argparse
import ast
from copy import deepcopy
import html
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.plan_penang_fyp_reviews import build_plan as base_plan
from scripts.plan_penang_fyp_expansion import build_plan as expansion_plan
from services import demonstration_recommendations as demo
from services.recommendation_review_evidence import approved_contributions, review_summaries
from services.review_destination import review_candidate_id
from sequence_contract import domain_functions as engine

BASELINE = '0dc1f25da1008295906552651401d1ace1fc5866'


def inputs():
    base, expansion = base_plan(), expansion_plan()
    candidates = demo.prepare_candidates(list(base['documents']['fyp_review_datasets/penang_v1']['destinations'].values()))
    examples = [row for row in [*base['documents'].values(), *expansion['documents'].values()] if 'rating' in row]
    # Derived parity data omits comments/names; source definitions remain authoritative.
    examples = [{k: row[k] for k in ('travellerId', 'destinationId', 'rating', 'feedbackStatus',
        'moderationStatus', 'updatedAt', 'synthetic')} for row in examples]
    example_profiles = demo.simulated_profiles(examples)
    fixture_profiles = {f'isolated_{key}': {**profile, 'fixtureScope': 'isolated_genuine_contract'}
                        for key, profile in demo.SIMULATED_PROFILES.items()}
    observations = []
    patterns = ([5,4,2], [2,3,4], [5,5,4], [2,2,3])
    for i, place in enumerate(candidates):
        ratings = [5,5,4,4,4,4,3,3,3,3] if place['destinationId'] == 'local_kek_lok_si' else patterns[i % 4]
        for j, rating in enumerate(ratings):
            uid = list(fixture_profiles)[j % 3] if len(ratings) == 3 else f'isolated_kek_peer_{j}'
            fixture_profiles.setdefault(uid, {**demo.SIMULATED_PROFILES['culture'], 'fixtureScope': 'isolated_genuine_contract'})
            observations.append({'id': f'isolated_{i}_{j}', 'travellerId': uid,
                'destinationId': place['destinationId'], 'rating': rating, 'fixtureScope': 'isolated_genuine_contract',
                'feedbackStatus': 'visible', 'moderationStatus': 'approved'})
    return {'synthetic': True, 'scope': 'Isolated model evaluation only; no real customers or provider observations.',
        'candidates': candidates, 'examples': examples, 'exampleProfiles': example_profiles,
        'currentProfiles': demo.SIMULATED_PROFILES, 'genuineEligibilityFixtures': observations,
        'genuineFixtureProfiles': fixture_profiles}


def genuine_contract_inputs(fixture):
    assert fixture['synthetic'] and all(r['fixtureScope'] == 'isolated_genuine_contract'
                                       for r in fixture['genuineEligibilityFixtures'])
    return deepcopy(fixture['genuineEligibilityFixtures'])


def evaluate(fixture=None):
    fixture = fixture or inputs()
    original = deepcopy(fixture)
    genuine = genuine_contract_inputs(fixture)
    summaries = review_summaries(approved_contributions(genuine))
    results = []
    for key, profile in fixture['currentProfiles'].items():
        content = engine.applyContentBasedFiltering(engine.prepareRecommendationInput(profile, fixture['candidates']))
        public_cf = engine.applyCollaborativeFiltering(content, genuine, fixture['genuineFixtureProfiles'], profile)
        public = engine.calculateRecommendationScore(public_cf, summaries)
        simulation = demo.evaluate(profile, fixture['candidates'], fixture['examples'])
        for mode, rows in [('genuine_eligibility_fixture', public), ('demonstration', simulation)]:
            for row in rows:
                results.append({'profile': key, 'mode': mode, 'destinationId': row['destinationId'],
                    'title': row['title'], 'content': row['contentScore'],
                    'eligiblePeers': row['collaborativeRatingCount'], 'rawPeer': row['rawCollaborativeScore'],
                    'confidence': row['collaborativeConfidence'], 'collaborative': row['collaborativeScore'],
                    'popularity': row['popularityScore'], 'popularitySource': row['popularitySource'],
                    'popularityEvidence': row['popularityEvidence'], 'hybrid': row['score']})
    assert original == fixture
    return {'synthetic': True, 'scope': fixture['scope'], 'results': results}


def before_values(fixture):
    root = Path(__file__).resolve().parents[2]
    code = subprocess.check_output(['git', 'show', BASELINE+':backend_api/sequence_contract/domain_functions.py'], cwd=root, text=True, encoding='utf-8')
    function = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef) and n.name == 'calculateRecommendationScore')
    namespace = dict(vars(engine))
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<verified-baseline>', 'exec'), namespace)
    old_score = namespace['calculateRecommendationScore']
    genuine = genuine_contract_inputs(fixture)
    result = {}
    for key, profile in fixture['currentProfiles'].items():
        content = engine.applyContentBasedFiltering(engine.prepareRecommendationInput(profile, fixture['candidates']))
        for mode, contributions, peers in [('genuine_eligibility_fixture', genuine, fixture['genuineFixtureProfiles']),
                                           ('demonstration', fixture['examples'], fixture['exampleProfiles'])]:
            combined = engine.applyCollaborativeFiltering(content, contributions, peers, profile)
            for row in old_score(combined):
                result[key, mode, review_candidate_id(row)] = row
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    output = Path(args.output_dir); output.mkdir(parents=True, exist_ok=True)
    fixture = inputs(); result = evaluate(fixture); previous = before_values(fixture)
    for row in result['results']:
        old = previous[row['profile'], row['mode'], row['destinationId']]
        row.update(beforeCollaborative=old['collaborativeScore'], beforePopularity=old['popularityScore'], beforeHybrid=old['score'])
    (output/'evaluation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    headers = ['Profile', 'Mode', 'Attraction', 'CF before', 'CF after', 'Peers', 'Confidence', 'Popularity before', 'Popularity after', 'Source', 'Hybrid']
    body = '<!doctype html><meta charset="utf-8"><title>Penang review integration evaluation</title><style>body{font:15px system-ui;margin:30px;color:#213547}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #ccd8d5}th{background:#eaf4f2}</style><h1>Penang review integration — isolated evaluation</h1><p>'+html.escape(result['scope'])+'</p><p>Demonstration uses the existing 104 synthetic definitions and their initial approval states; live moderation has not been read. Its baseline shows the genuine engine correctly excluding examples, not a claim that examples should affect public scores. Genuine eligibility uses independent fictional test observations in memory, never real customer records. No data is imported. Baseline: '+BASELINE+'</p><table><tr>'+''.join('<th>'+h+'</th>' for h in headers)+'</tr>'
    for row in result['results']:
        values = [row['profile'], row['mode'], row['title'], row['beforeCollaborative'], row['collaborative'], row['eligiblePeers'], row['confidence'], row['beforePopularity'], row['popularity'], row['popularitySource'], row['hybrid']]
        body += '<tr>'+''.join('<td>'+html.escape(str(value))+'</td>' for value in values)+'</tr>'
    (output/'evaluation.html').write_text(body+'</table>', encoding='utf-8')
    print('72 isolated destination/profile/mode results;104existing examples; no database/provider operations.')
