"""Private Penang demonstration reviews, selected by the authenticated UID."""
import os
from collections import Counter
from functools import lru_cache

from firebase_service import get_db
from services.review_service import ReviewConflict, review_id, review_revision, screen_submission, stage_review_decision


PROJECT = 'travelmate2-30a8a'
DATASET_PATH = 'fyp_review_datasets/penang_v1'
REVIEW_COUNT = 36
EXPANSION_COUNT = 68
MANIFEST_PATH = 'manifests/v2'
EXPANSION_COLLECTION = 'expanded_reviews'
MODERATION_COLLECTION = 'moderation'


def dataset_for(uid):
    viewer = os.getenv('FYP_REVIEW_VIEWER_UID', '').strip()
    if not viewer or uid != viewer:
        return None
    return private_dataset()


def private_dataset():
    """Call only from an authorized local demo, UID preview or Administrator route."""
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
    collection, version = MANIFEST_PATH.split('/')
    manifest = ref.collection(collection).document(version).get()
    if manifest.exists:
        metadata = manifest.to_dict() or {}
        ids = metadata.get('reviewIds')
        if (metadata.get('version') != 2 or metadata.get('synthetic') is not True
                or metadata.get('baseReviewCount') != REVIEW_COUNT
                or not isinstance(ids, list) or len(ids) != EXPANSION_COUNT
                or any(not isinstance(fid, str) for fid in ids)
                or len(set(ids)) != EXPANSION_COUNT):
            raise ValueError('The private review manifest is invalid.')
        added = [{**(doc.to_dict() or {}), 'id': doc.id}
                 for doc in ref.collection(EXPANSION_COLLECTION).limit(EXPANSION_COUNT + 1).stream()]
        if (len(added) != EXPANSION_COUNT or {row['id'] for row in added} != set(ids)
                or set(ids).intersection(row['id'] for row in rows)
                or any(row.get('synthetic') is not True or row.get('destinationId') not in destinations
                       for row in added)):
            raise ValueError('The private review expansion is unavailable.')
        rows.extend(added)
    decisions = {doc.id: doc.to_dict()
                 for doc in ref.collection(MODERATION_COLLECTION).limit(len(rows) + 1).stream()}
    if manifest.exists and set(decisions) - {row['id'] for row in rows}:
        raise ValueError('The private moderation state is invalid.')
    return [_effective(row, decisions.get(row['id'])) for row in rows]


def _effective(source, decision):
    fields = ('moderationStatus', 'feedbackStatus', 'updatedAt', 'moderationDecision',
              'reviewComment', 'reviewedBy', 'reviewedAt', 'removedBy', 'removedAt')
    return {**source, **{key: decision[key] for key in fields if key in (decision or {})}}


def moderation_history(ref, record):
    state = ref.collection(MODERATION_COLLECTION).document(record['id'])
    history = [entry.to_dict() for entry in state.collection('moderation_history').stream()]
    if not history and record.get('moderationDecision'):
        # The original create-only plan stored the initial decision on the source.
        history.append({**record['moderationDecision'], 'screening': record.get('screening', {})})
    return sorted(history, key=lambda event: event.get('at', ''), reverse=True)


def moderate_review(ref, expected, updates):
    """Atomically update only private visibility and its audit history."""
    from google.cloud import firestore

    state = ref.collection(MODERATION_COLLECTION).document(expected['id'])

    @firestore.transactional
    def commit(transaction):
        snapshot = state.get(transaction=transaction)
        # Source records are immutable; only this overlay can change after listing.
        original = ref.collection('reviews').document(expected['id']).get(transaction=transaction)
        if not original.exists:
            original = ref.collection(EXPANSION_COLLECTION).document(expected['id']).get(transaction=transaction)
        if not original.exists:
            raise ReviewConflict('This review changed. Refresh and try again.')
        current = _effective(original.to_dict(), snapshot.to_dict() if snapshot.exists else None)
        if review_revision(current) != review_revision(expected):
            raise ReviewConflict('This review changed. Refresh and try again.')
        updated = _effective(current, updates)
        transaction.set(state, {**(snapshot.to_dict() if snapshot.exists else {}), **updates})
        if not snapshot.exists:
            stage_review_decision(transaction, state, current)
        stage_review_decision(transaction, state, updated)
        return {**updated, 'id': expected['id']}

    return commit(get_db().transaction())



# Regional local-demo fixtures. They never enter feedback, recommendation inputs or
# public projections. The existing separately moderated Penang dataset stays in Firestore.
_REGIONAL_REVIEWS = {
    'local_klcc': (
        ('Aina R.', 5, 'Took my time looking at the skyline. Beautiful views in every direction; I kept going back for one more photo.'),
        ('Dylan P.', 3, 'Beautiful city views, but the short visit was disappointing. I would give myself longer next time.'),
        ('Nora L.', 2, 'A disappointing visit. The crowds were frustrating and made it difficult to see much. I left earlier than planned.'),
    ),
    'local_legoland_malaysia': (
        ('Kai M.', 5, 'We had a wonderful family day. My nephew wanted to stop and look closely at every little model.'),
        ('Mira S.', 4, 'We had a lovely afternoon in Miniland. The kids enjoyed spotting familiar buildings together.'),
        ('Hafiz T.', 2, 'I found the day tiring and the waiting frustrating. We went home before we had seen everything we wanted.'),
    ),
    'local_tunku_abdul_rahman': (
        ('Sara D.', 5, 'A beautiful break from the city. I mostly stayed by the water and loved that we could take the afternoon slowly.'),
        ('Jin A.', 3, 'The island scenery was lovely, but the beach felt crowded. I was ready to head back by mid-afternoon.'),
        ('Iman K.', 2, 'The afternoon felt too rushed. I was disappointed by how little time we spent on the island itself.'),
    ),
    'local_langkawi_skycab': (
        ('Devi M.', 5, 'Beautiful views over the hills and sea. I put my camera away for a while just to take it in.'),
        ('Ray H.', 4, 'I was nervous about the height, but the ride was enjoyable. The views were worth slowing down for.'),
        ('Nabil C.', 3, 'Beautiful scenery when it cleared, but the poor visibility was disappointing for much of the ride.'),
    ),
}


@lru_cache(maxsize=1)
def regional_demo_destinations():
    from services.local_catalog import DESTINATIONS
    return {row['destinationId']: row for row in DESTINATIONS
            if row['destinationId'] in _REGIONAL_REVIEWS}


@lru_cache(maxsize=len(_REGIONAL_REVIEWS))
def regional_demo_reviews(identity):
    rows = []
    for index, (author, rating, comment) in enumerate(_REGIONAL_REVIEWS.get(identity, ()), 1):
        uid = f'fyp-regional-v1-{index}'
        rows.append({
            'id': review_id(uid, identity), 'travellerId': uid,
            'travellerName': author, 'destinationId': identity,
            'rating': rating, 'comment': comment, 'synthetic': True,
            'dataset': 'fyp-regional-v1', 'submittedAt': f'2026-11-{10 + index}T10:00:00+08:00',
            **screen_submission(comment, rating),
        })
    return rows
