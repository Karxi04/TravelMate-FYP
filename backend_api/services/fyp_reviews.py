"""Private Penang demonstration reviews, selected by the authenticated UID."""
import os
from collections import Counter

from firebase_service import get_db


PROJECT = 'travelmate2-30a8a'
DATASET_PATH = 'fyp_review_datasets/penang_v1'
REVIEW_COUNT = 36


def dataset_for(uid):
    viewer = os.getenv('FYP_REVIEW_VIEWER_UID', '').strip()
    if not viewer or uid != viewer:
        return None
    db = get_db()
    if db.project != PROJECT or os.getenv('FIRESTORE_EMULATOR_HOST'):
        return None
    ref = db.document(DATASET_PATH)
    snapshot = ref.get()
    metadata = (snapshot.to_dict() or {}) if snapshot.exists else {}
    destinations = metadata.get('destinations')
    if (metadata.get('synthetic') is not True or metadata.get('reviewCount') != REVIEW_COUNT
            or not isinstance(destinations, dict) or len(destinations) != 12):
        return None
    return ref, destinations


def dataset_reviews(ref, destinations):
    rows = [{**(doc.to_dict() or {}), 'id': doc.id}
            for doc in ref.collection('reviews').limit(REVIEW_COUNT + 1).stream()]
    counts = Counter(row.get('destinationId') for row in rows)
    if (len(rows) != REVIEW_COUNT or counts != dict.fromkeys(destinations, 3)
            or any(row.get('synthetic') is not True for row in rows)):
        raise ValueError('The private review dataset is unavailable.')
    return rows
