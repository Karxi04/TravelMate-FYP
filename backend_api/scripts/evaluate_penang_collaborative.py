"""Offline CF evaluation; never loads .env, initializes Firebase or imports reviews.

Run with --output-dir D:/workspace/... . All source contributions remain synthetic.
The qualifying projection is a counterfactual model input in memory, not a genuine
review record. Its only purpose is to exercise the existing scoring formula.
"""
import argparse
from copy import deepcopy
from hashlib import sha256
import html
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sequence_contract.domain_functions import applyCollaborativeFiltering, calculateRecommendationScore

FIXTURE = Path(__file__).resolve().parents[1] / 'tests/fixtures/penang_collaborative_benchmark.json'


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def qualifying_projection(fixture):
    """Explicitly simulate qualifying observations inside the offline benchmark."""
    assert fixture['synthetic'] is True
    fields = ('id', 'travellerId', 'destinationId', 'rating', 'feedbackStatus',
              'moderationStatus', 'updatedAt')
    assert all(row['synthetic'] is True for row in fixture['ratingContributions'])
    return [{key: deepcopy(row[key]) for key in fields}
            for row in fixture['ratingContributions']]


def evaluate():
    fixture = load_fixture()
    original = deepcopy(fixture)
    rows = []
    for name, profile in fixture['currentProfiles'].items():
        for mode, contributions in [('cold_start', []),
                ('synthetic_as_stored', fixture['ratingContributions']),
                ('qualifying_counterfactual', qualifying_projection(fixture))]:
            scored = calculateRecommendationScore(applyCollaborativeFiltering(
                [{**row, 'contentScore': 70} for row in fixture['candidates']],
                contributions, fixture['peerPreferences'], profile, 'cf_benchmark_viewer'))
            for row in scored:
                rows.append({'profile': name, 'mode': mode, 'destinationId': row['destinationId'],
                    'destination': row['title'], 'eligiblePeers': row['collaborativeRatingCount'],
                    'rawPeerScore': row['rawCollaborativeScore'],
                    'confidence': row['collaborativeConfidence'],
                    'collaborativeScore': row['collaborativeScore'],
                    'fallbackReason': row.get('collaborativeFallbackReason') or (
                        'none' if row['collaborativeRatingCount'] else 'no_eligible_peer_ratings'),
                    'missingProfiles': row.get('collaborativeMissingProfileCount', 0),
                    'dissimilarPeers': row.get('collaborativeDissimilarPeerCount', 0),
                    'hybridScore': row['score']})
    assert fixture == original
    # Normalize checkout line endings so the frozen fixture works on Windows and CI.
    return {'synthetic': True, 'fixtureSha256': sha256(FIXTURE.read_text(encoding='utf-8').encode('utf-8')).hexdigest(),
            'ratingContributions': 50, 'peerProfiles': 10,
            'note': 'Offline counterfactual evaluation, not real customer evidence. As-stored synthetic ratings stay excluded.',
            'weights': {'content': .6, 'collaborative': .3, 'popularity': .1}, 'results': rows}


def render_report(result):
    headers = ['Profile', 'Destination', 'Eligible peers', 'Raw /100', 'Confidence', 'Final CF /100', 'Fallback reason']
    cells = [[r['profile'], r['destination'], r['eligiblePeers'], r['rawPeerScore'],
              r['confidence'], r['collaborativeScore'], r['fallbackReason']]
             for r in result['results'] if r['mode'] == 'qualifying_counterfactual']
    return ('<!doctype html><meta charset="utf-8"><title>Penang CF offline evaluation</title>'
        '<style>body{font:15px/1.5 system-ui;max-width:1200px;margin:40px auto;color:#213547}'
        'table{border-collapse:collapse;width:100%}td,th{padding:9px;border:1px solid #ccd8d5;text-align:left}'
        'th{background:#eaf4f2}</style><h1>Penang collaborative evidence — isolated benchmark</h1>'
        '<p>' + html.escape(result['note']) + '</p><p>50 fictional contributions,10 peer profiles,6 existing Penang identities.'
        ' Cold start and synthetic-as-stored remain50 with zero confidence. Confidence-aware neutral shrinkage and60/30/10 are unchanged.</p>'
        '<table><tr>' + ''.join('<th>'+html.escape(h)+'</th>' for h in headers) + '</tr>'
        + ''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in row)+'</tr>' for row in cells)
        + '</table><p>Fixture SHA-256: '+result['fixtureSha256']+'</p>')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    result = evaluate()
    (output / 'evaluation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    (output / 'evaluation.html').write_text(render_report(result), encoding='utf-8')
    print('Offline evaluation complete;50 synthetic contributions; no Firebase/provider operations.')
