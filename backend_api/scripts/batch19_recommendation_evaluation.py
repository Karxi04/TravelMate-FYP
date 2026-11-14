"""Offline paired evaluation against Batch 19's starting commit.

The Penang candidates and Photography + Food labels are the existing frozen
fixture. The other two sets are engineering relevance judgements, kept
separate from catalogue metadata and fixed for both rankings.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend_api'))

from scripts.recommendation_relevance_audit import FIXTURES, rank
from services.recommendation_discovery import discovery_annotations, enrich_discovery_candidate
from services.recommendation_taxonomy import candidate_concepts

BASELINE = '1250e8f7981ce20fa70784d4f208d7a137271770'
NATURE_ADVENTURE = {
    'hill', 'gardens', 'national_park', 'escape', 'beach', 'spice', 'entopia',
}
FAMILY_RELAXATION = {
    'wonderfood', 'hill', 'gardens', 'beach', 'spice', 'entopia',
}


def evaluate():
    fixture = json.loads((FIXTURES / 'photography_food_discovery.json').read_text(encoding='utf-8'))
    candidates = json.loads((FIXTURES / 'penang_core_demo.json').read_text(encoding='utf-8'))['candidates']
    candidates += fixture['additionalCandidates']
    for item in candidates:
        item['state'] = 'Penang'
        item['normalizedGeography'] = {'state': 'Penang', 'conflict': False}
    profiles = {
        'Photography + Food': (fixture['profile'], {key for key, value in fixture['judgements'].items()
                                                     if value['grade'] > 0}, {'photography', 'food'}),
        'Nature + Adventure': ({'interests': ['Nature', 'I like outdoor activities and adventure'],
                                'travelPace': 'Active'}, {'demo_penang_' + name for name in NATURE_ADVENTURE},
                               {'nature', 'adventure'}),
        'Family + Relaxation': ({'interests': ['Something suitable for children', 'Somewhere peaceful'],
                                 'travelPace': 'Relaxed'}, {'demo_penang_' + name for name in FAMILY_RELAXATION},
                                {'family', 'leisure'}),
    }

    def measure(ranker, annotation):
        result = {}
        for name, (profile, labels, concepts) in profiles.items():
            eligible = [r for r in ranker(profile, [enrich_discovery_candidate(item) for item in candidates]) if annotation(r, profile)['discoveryEligible']]
            top = eligible[:10]
            ids = [row['destinationId'] for row in top]
            diversity = set().union(*(candidate_concepts(row) & concepts for row in top))
            result[name] = {
                'precision_at_5': sum(key in labels for key in ids[:5]) / 5,
                'precision_at_10': sum(key in labels for key in ids) / 10,
                'preferred_categories_at_10': sorted(diversity),
                'duplicates_at_10': len(ids) - len(set(ids)),
                'duplicate_rate_at_10': (len(ids) - len(set(ids))) / len(ids) if ids else 0,
                'destinations_at_10': [row['title'] for row in top],
                'relevant_coverage': len({row['destinationId'] for row in eligible} & labels) / len(labels),
                'eligible_count': len(eligible),
                'states_at_10': sorted({row['state'] for row in top}),
            }
        return result

    after = measure(rank, discovery_annotations)
    # Run the baseline implementations in a child process to avoid patched
    # functions or imports carrying newer logic into the baseline comparison.
    return {'baseline': BASELINE, 'before': baseline_measure(), 'after': after,
            'fixture': '17 Penang candidates; only Photography + Food has owner-reviewed labels.'}


def baseline_measure():
    code = """import runpy, subprocess, sys
from pathlib import Path
root = Path.cwd()
sys.path.insert(0, str(root / 'backend_api'))
base = '%s'
for name in ('services.recommendation_taxonomy', 'services.recommendation_discovery',
             'sequence_contract.domain_functions'):
    module = __import__(name, fromlist=['_'])
    source_path = 'backend_api/' + name.replace('.', '/') + '.py'
    source = subprocess.check_output(['git', 'show', base + ':' + source_path])
    exec(compile(source, source_path, 'exec'), module.__dict__)
scope = runpy.run_path('backend_api/scripts/batch19_recommendation_evaluation.py')
fn = scope['evaluate']
fn.__globals__['baseline_measure'] = lambda: None
print(__import__('json').dumps(fn()['after']))
""" % BASELINE
    return json.loads(subprocess.check_output([sys.executable, '-B', '-c', code], cwd=ROOT))


if __name__ == '__main__':
    print(json.dumps(evaluate(), indent=2, ensure_ascii=True))
