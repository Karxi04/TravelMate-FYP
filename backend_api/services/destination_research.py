"""Sourced named-place identities, kept outside the planning-ready catalogue."""
import json
from functools import lru_cache
from pathlib import Path

from services.recommendation_taxonomy import normalize_phrase


@lru_cache(maxsize=1)
def attraction_identities():
    path = Path(__file__).parent / 'data/malaysia_attraction_identities.json'
    return json.loads(path.read_text(encoding='utf-8'))['records']


def _public_identity(row):
    pinned = bool(row.get('gps_coordinates'))
    return dict(row, place_id=row['destinationId'], reviewDestinationId=row['destinationId'],
                 address=f"{row['city']}, {row['state']}, Malaysia", source='official_identity',
                 detailsAvailable=False, metadataStatus='identity_and_coordinates' if pinned else 'identity_only',
                 materialWarning='Official attraction identity; current hours and admission have not been verified.'
                                 + ('' if pinned else ' Exact location is not verified.'))


def named_attractions(query):
    name = normalize_phrase(query)
    return [_public_identity(row) for row in attraction_identities() if normalize_phrase(row['title']) == name]


def attraction_identity(reference):
    row = next((row for row in attraction_identities() if row['destinationId'] == reference), None)
    return _public_identity(row) if row else None
