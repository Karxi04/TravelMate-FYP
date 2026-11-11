"""Generate an offline create-only plan for the existing project's private dataset."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.fyp_reviews import DATASET_PATH, PROJECT, REVIEW_COUNT
from services.review_destination import review_destination_id
from services.review_service import review_id, screen_submission, valid_review

FIXTURE = Path(__file__).resolve().parents[1] / 'tests/fixtures/penang_synthetic_reviews.json'
REVIEW_DATE = '2026-11-11T09:00:00+08:00'
REVIEWERS = {'positive': 'A', 'mixed': 'B', 'negative': 'C'}


def build_plan():
    data = FIXTURE.read_bytes()
    fixture = json.loads(data)
    if fixture.get('synthetic') is not True or len(fixture['reviews']) != REVIEW_COUNT:
        raise ValueError('Expected exactly 36 Penang fixtures.')
    destinations = {}
    reviews = {}
    counts = Counter()
    for row in fixture['reviews']:
        identity = review_destination_id(row['destinationId'])
        payload = {'destinationId': identity, **{
            key: row[key] for key in ('destinationName', 'rating', 'comment')
        }}
        if not valid_review(payload):
            raise ValueError('Invalid fixture review.')
        decision = screen_submission(row['comment'], row['rating'])
        screening = decision['screening']
        tone = screening.get('sentiment', {}).get('label')
        if decision['moderationStatus'] != 'reviewed' or tone != row['expectedSentiment']:
            raise ValueError('Fixture did not qualify under the current policy.')
        reviewer = REVIEWERS[tone]
        author = f'penang_fixture_{reviewer.lower()}'
        path = f'{DATASET_PATH}/reviews/{review_id(author, identity)}'
        if path in reviews:
            raise ValueError('Duplicate fixture review identity.')
        reviews[path] = {**payload, **decision, 'synthetic': True,
                         'travellerId': author, 'travellerName': f'Reviewer {reviewer}',
                         'submittedAt': REVIEW_DATE, 'updatedAt': REVIEW_DATE}
        counts[identity] += 1
        destinations[identity] = {
            'destinationId': identity, 'place_id': identity, 'title': row['destinationName'],
            'address': 'Penang, Malaysia', 'state': 'Penang',
        }
    if len(destinations) != 12 or set(counts.values()) != {3}:
        raise ValueError('Expected three distinct reviews at each of 12 destinations.')
    metadata = {'synthetic': True, 'reviewCount': REVIEW_COUNT,
                'fixtureSha256': sha256(data).hexdigest(), 'destinations': destinations}
    return {'project': PROJECT, 'database': '(default)', 'operation': 'create_only',
            'documents': {DATASET_PATH: metadata, **reviews}}


if __name__ == '__main__':
    print(json.dumps(build_plan(), ensure_ascii=True, indent=2))
