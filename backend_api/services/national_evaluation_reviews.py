"""Curated, source-controlled sample reviews; never Firebase users or feedback."""
import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

from services.destination_research import attraction_identity
from services.local_catalog import DESTINATIONS
from services.malaysian_locality import normalize_destination_scope, validate_candidate
from services.recommendation_discovery import is_planning_candidate
from services.review_service import review_id, screen_submission, valid_review

DATASET = 'fyp-malaysia-coverage-v1'
REGIONS = ('penang', 'north', 'central', 'south', 'east_coast', 'borneo')
ROOT = Path(__file__).parent / 'data/evaluation_reviews'


@lru_cache(maxsize=1)
def _definitions():
    profiles = json.loads((ROOT / 'profiles.json').read_text(encoding='utf-8'))
    documents = [json.loads((ROOT / (region + '.json')).read_text(encoding='utf-8')) for region in REGIONS]
    if any(doc.get('dataset') != DATASET or doc.get('version') != 1 or doc.get('synthetic') is not True
           for doc in [profiles, *documents]):
        raise ValueError('Invalid evaluation dataset provenance.')
    records = [row for doc in documents for row in doc['records']]
    if len({row['destinationId'] for row in records}) != len(records):
        raise ValueError('Duplicate evaluation destination.')
    return profiles['profiles'], {row['destinationId']: row for row in records}


def profiles():
    return deepcopy(_definitions()[0])


@lru_cache(maxsize=1)
def _destinations():
    local = {row['destinationId']: row for row in DESTINATIONS}
    result = {}
    for identity, record in _definitions()[1].items():
        place = deepcopy(local.get(identity) or attraction_identity(identity))
        if not place or place.get('title') != record['destinationName'] or not place.get('gps_coordinates'):
            raise ValueError('Evaluation attraction requires an existing named, pinned identity.')
        eligible, checked = validate_candidate(place, normalize_destination_scope(record['state']))
        if not eligible or not is_planning_candidate(place):
            raise ValueError('Evaluation attraction fails existing geography/tourism validation.')
        # Identity-only records are never bulk-promoted. This explicit curated subset
        # retains unknown hours/prices and the existing official-identity disclosure.
        result[identity] = checked
    return result


def destinations():
    return deepcopy(_destinations())


@lru_cache(maxsize=100)
def _sources(identity):
    record = _definitions()[1].get(identity)
    if not record:
        return []
    place = _destinations()[identity]
    rows, seen = [], set()
    for raw in record['contributions']:
        uid = raw['travellerId']
        profile = _definitions()[0].get(uid, {})
        payload = {'destinationId': identity, 'rating': raw['rating'], 'comment': raw['comment']}
        if (not valid_review(payload) or raw.get('synthetic') is not True or raw.get('source') != 'fyp_private'
                or raw.get('dataset') != DATASET or raw.get('datasetVersion') != 1
                or profile.get('synthetic') is not True or profile.get('dataset') != DATASET
                or raw['id'] != review_id(uid, identity) or uid in seen):
            raise ValueError('Invalid or duplicate evaluation contribution.')
        seen.add(uid)
        screened = screen_submission(raw['comment'], raw['rating'])
        screened['screening']['screenedAt'] = raw['submittedAt']
        screened['moderationDecision']['at'] = raw['submittedAt']
        rows.append({**raw, **screened, 'destinationId': identity, 'destinationName': place['title'],
                     'destinationAddress': place.get('address', ''), 'dataset': DATASET, 'datasetVersion': 1,
                     'source': 'fyp_private', 'synthetic': True})
    return rows


def sources(identity):
    return deepcopy(_sources(identity))
