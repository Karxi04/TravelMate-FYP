"""Paired offline evaluation. Frozen human labels and engineering mocks are separate.

No provider, Firebase, HTTP server or production write is used. Output goes to stdout.
The extra venues are fictional category fixtures, not new factual destination records.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from math import log2
from pathlib import Path
import subprocess
import sys
import types

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend_api'))
from services.recommendation_taxonomy import experience_types as measure_experiences
BASELINE = '07351e019425f42b19f9bd39f6a46c62db93bd21'
FIXTURES = ROOT / 'backend_api/tests/fixtures'

# Independent engineering judgements of fixture category meanings, frozen before comparison.
# These are not owner-reviewed visitor judgements or evidence of actual venue facilities.
CATEGORY_LABELS = {
    'restaurant': {'food': 2}, 'food_court': {'food': 2}, 'cafe': {'food': 2},
    'museum': {'culture': 2}, 'art_gallery': {'culture': 2}, 'historical_landmark': {'culture': 2},
    'botanical_garden': {'nature': 2}, 'national_park': {'nature': 2}, 'hiking_area': {'nature': 2, 'adventure': 2},
    'adventure_sports_center': {'adventure': 2}, 'amusement_park': {'adventure': 1, 'family': 2, 'leisure': 2},
    'observation_deck': {'photography': 2}, 'zoo': {'family': 2}, 'aquarium': {'family': 2},
    'beach': {'nature': 2, 'leisure': 2}, 'shopping_mall': {'shopping': 2},
    'market': {'shopping': 2}, 'night_market': {'shopping': 2, 'social': 2},
    'community_center': {'social': 2}, 'event_venue': {'social': 2},
}


def mock_pool():
    from services.malaysian_locality import STATE_CENTERS
    rows, labels = [], {}
    categories = list(CATEGORY_LABELS)
    for state_no, (state, coords) in enumerate(STATE_CENTERS.items()):
        for index, category in enumerate(categories):
            key = f'isolated_{state_no}_{index}'
            rows.append({'destinationId': key, 'title': f'Isolated venue {state_no}-{index}',
                         'category': 'Tourist attraction', 'type_id': category, 'state': state,
                         'gps_coordinates': {'latitude': coords[0], 'longitude': coords[1]},
                         'fixtureOnly': True})
            labels[key] = dict(CATEGORY_LABELS[category])
    return rows, labels


@contextmanager
def algorithms(baseline=False):
    modules = ['services.recommendation_taxonomy', 'services.recommendation_discovery',
               'services.malaysian_locality', 'sequence_contract.domain_functions']
    if not baseline:
        from sequence_contract import domain_functions as domain
        from services import recommendation_taxonomy as taxonomy, recommendation_discovery as discovery, malaysian_locality as geo
        yield domain, taxonomy, discovery, geo
        return
    saved = {name: sys.modules.get(name) for name in modules}
    loaded = {}
    try:
        for name in modules:
            relative = 'backend_api/' + name.replace('.', '/') + '.py'
            text = subprocess.check_output(['git', 'show', f'{BASELINE}:{relative}'], cwd=ROOT).decode('utf-8')
            module = types.ModuleType(name)
            module.__file__ = str(ROOT / relative)
            sys.modules[name] = module
            exec(compile(text, module.__file__, 'exec'), module.__dict__)
            loaded[name] = module
        yield tuple(loaded[name] for name in (modules[3], modules[0], modules[1], modules[2]))
    finally:
        for name, value in saved.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def rank(domain, discovery, geo, profile, pool):
    accepted, _ = geo.filter_candidates(deepcopy(pool), geo.normalize_destination_scope('Malaysia'))
    for row in accepted:
        row['ratingSource'] = 'unverified_local_catalog'
    accepted = [discovery.enrich_discovery_candidate(row) for row in accepted]
    rows = domain.calculateRecommendationScore(domain.applyCollaborativeFiltering(
        domain.applyContentBasedFiltering(domain.prepareRecommendationInput(profile, accepted)), [], {}, profile, 'isolated'))
    if not any(discovery.discovery_annotations(row, profile)['discoveryEligible'] for row in rows):
        return [], len(accepted)
    ranked = domain.diversifyRecommendations(domain.rankRecommendations(domain.deduplicateRecommendations(rows)), profile, limit=150)
    return [row for row in ranked if discovery.discovery_annotations(row, profile)['discoveryEligible']], len(accepted)


def metrics(rows, grades, taxonomy, pool_size, accepted):
    result = {}
    for k in (5, 10):
        observed = [grades.get(row['destinationId'], 0) for row in rows[:k]]
        ideal = sorted(grades.values(), reverse=True)[:k]
        dcg = sum((2**grade - 1) / log2(i + 2) for i, grade in enumerate(observed))
        idcg = sum((2**grade - 1) / log2(i + 2) for i, grade in enumerate(ideal))
        result.update({f'precision@{k}': sum(v > 0 for v in observed) / k,
                       f'primaryPrecision@{k}': sum(v == 2 for v in observed) / k,
                       f'nDCG@{k}': round(dcg / idcg, 4) if idcg else None})
    identities = [row['destinationId'] for row in rows]
    top = rows[:10]
    labels = {key for key, grade in grades.items() if grade > 0}
    # Same measurement vocabulary for both algorithms, independent of their ranking implementation.
    experiences = set().union(*(set(measure_experiences(r)) for r in top))
    result.update(candidateCoverage=len(set(identities) & labels) / len(labels) if labels else None,
                  uniqueDestinations=len(set(identities)), eligibleCount=len(rows),
                  duplicateRate=(len(identities) - len(set(identities))) / len(identities) if identities else 0,
                  experienceDiversityAt10=len(experiences),
                  geographicCoverageAt10=sorted({r.get('normalizedGeography', {}).get('state') for r in top if r.get('normalizedGeography', {}).get('state')}),
                  geographyRetention=accepted / pool_size if pool_size else 0,
                  mockProviderToRankingRetention=len(rows) / pool_size if pool_size else 0,
                  evidenceCompletenessAt10=sum(sum(bool(v.get('applied')) for v in r.get('contentSignals', {}).values()) / 6 for r in top) / len(top) if top else 0,
                  destinationsAt10=[r.get('title') for r in top], idsAt10=[r['destinationId'] for r in top])
    # A simulated alternative page must explicitly exclude displayed IDs; this is not Vivo evidence.
    shown = set(identities[:5])
    alternative = [key for key in identities if key not in shown][:5]
    result['alternativePageRepeatedDestinations'] = len(shown & set(alternative))
    return result


def evaluate():
    human_bytes = (FIXTURES / 'photography_food_discovery.json').read_bytes()
    human = json.loads(human_bytes)
    base = json.loads((FIXTURES / 'penang_core_demo.json').read_text(encoding='utf-8'))
    penang = base['candidates'] + human['additionalCandidates']
    synthetic, labels = mock_pool()
    concepts = ['food', 'culture', 'nature', 'adventure', 'photography', 'family', 'leisure', 'shopping', 'social']
    profiles = {name: [name] for name in concepts}
    profiles.update({'Photography + Food': ['photography', 'food'], 'Nature + Adventure': ['nature', 'adventure'],
                     'Family + Relaxation': ['family', 'leisure']})
    report = {'baseline': BASELINE, 'humanLabelSha256': hashlib.sha256(human_bytes).hexdigest(),
              'engineeringLabelSha256': hashlib.sha256(json.dumps(CATEGORY_LABELS, sort_keys=True).encode()).hexdigest(),
              'liveProviderRequests': 0, 'productionWrites': 0,
              'labelSources': {'human': 'Unmodified owner-reviewed Photography/Food fixture',
                              'engineering': 'Frozen synthetic provider-category judgements; not visitor ground truth'},
              'fixtureSources': ['https://developers.google.com/maps/documentation/places/web-service/place-types',
                                'https://github.com/dosm-malaysia/data-open/blob/b057365ccbf26cbe3db1c043668f6a0efe811cb2/datasets/geodata/administrative_1_state.geojson'],
              'limitations': ['Offline fixture metrics do not establish production accuracy or real provider coverage.',
                             'Engineering fixture venues are fictional; only category vocabulary and state geography have cited sources.',
                             'No personality, prices, accessibility or family facilities are inferred from categories.',
                             'Planned queries are counts, not executed provider requests.'], 'before': {}, 'after': {}}
    for baseline in (True, False):
        with algorithms(baseline) as (domain, taxonomy, discovery, geo):
            target = report['before' if baseline else 'after']
            rows, accepted = rank(domain, discovery, geo, human['profile'], penang)
            target['ownerReviewedPenang'] = metrics(rows, {k: v['grade'] for k, v in human['judgements'].items()},
                                                    taxonomy, len(penang), accepted)
            top_sets = {}
            target['engineeringProfiles'] = {}
            for name, requested in profiles.items():
                profile = {'interests': requested, 'travelPersonality': 'Explorer', 'travelPace': 'Moderate'}
                grades = {key: max((values.get(c, 0) for c in requested), default=0) for key, values in labels.items()}
                rows, accepted = rank(domain, discovery, geo, profile, synthetic)
                result = metrics(rows, grades, taxonomy, len(synthetic), accepted)
                result['plannedSearchesOnEmptyPool'] = len(discovery.discovery_queries(profile, []))
                result['plannedSearchesAfterPool'] = len(discovery.discovery_queries(profile, synthetic))
                target['engineeringProfiles'][name] = result
                top_sets[name] = set(result['idsAt10'])
            target['crossProfileOverlapAt10'] = {f'{a} / {b}': len(top_sets[a] & top_sets[b]) / len(top_sets[a] | top_sets[b])
                if top_sets[a] | top_sets[b] else None for a, b in [('Photography + Food', 'Nature + Adventure'),
                                                               ('Nature + Adventure', 'Family + Relaxation'), ('shopping', 'social')]}
    return report


if __name__ == '__main__':
    print(json.dumps(evaluate(), indent=2, allow_nan=False))
