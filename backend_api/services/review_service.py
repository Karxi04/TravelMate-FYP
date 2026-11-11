"""Local review validation, deterministic NLP triage and publication policy."""
import hashlib
import json
import re
import unicodedata
from math import isfinite

from utils import utc_now_iso
from services.review_sentiment import classify_review_sentiment

SCREENING_POLICY = 'travelmate-review-auto-v1'


def valid_review(data, partial=False):
    if not isinstance(data, dict) or not data:
        return False
    fields = {'rating', 'comment'} | (set() if partial else {'destinationId', 'destinationName', 'destinationAddress'})
    if not set(data) <= fields:
        return False
    if not partial and not {'rating', 'comment', 'destinationId'} <= set(data):
        return False
    if 'rating' in data and (type(data['rating']) is not int or not 1 <= data['rating'] <= 5):
        return False
    if 'comment' in data and (not isinstance(data['comment'], str) or not 5 <= len(data['comment'].strip()) <= 2000):
        return False
    return all(isinstance(data[key], str) and 0 < len(data[key].strip()) <= 500
               for key in ('destinationId',) if key in data) and all(
        isinstance(data[key], str) and len(data[key]) <= 500
        for key in ('destinationName', 'destinationAddress') if key in data)


def review_id(uid, destination):
    return 'review_' + hashlib.sha256(f'{uid}\0{destination}'.encode()).hexdigest()


def review_revision(item):
    fields = ('travellerId', 'destinationId', 'rating', 'comment', 'updatedAt', 'moderationStatus', 'feedbackStatus')
    return hashlib.sha256(json.dumps({key:item.get(key) for key in fields}, sort_keys=True, default=str).encode()).hexdigest()


def screen_review(comment, rating=None):
    """Rule-based NLP triage, not an AI approval or a statistical confidence score."""
    text = unicodedata.normalize('NFKC', comment).casefold()
    tokens = re.findall(r'\w+', text)
    flags = []
    if set(tokens) & {'fuck', 'fucking', 'bastard', 'bodoh', 'babi'}:
        flags.append('abusive_language')
    if re.search(r'https?://|www\.|<\s*script|buy now|click here', text):
        flags.append('spam_or_unsafe_content')
    if re.search(r'(.)\1{7,}', text) or (len(tokens) >= 8 and len(set(tokens)) / len(tokens) < .35):
        flags.append('repeated_content')
    sentiment = classify_review_sentiment(text, rating)
    if sentiment['ratingMismatch']:
        flags.append('rating_sentiment_mismatch')
    evidence = sentiment['positiveEvidence'] + sentiment['negativeEvidence']
    meaningful = len(tokens) >= 3 or (len(comment.strip()) >= 8 and evidence >= 2)
    uncertain = not meaningful or sentiment['ratingAlignment'] == 'uncertain'
    risk = 'flagged' if flags else 'uncertain' if uncertain else 'low'
    result = {'method': 'local_rules_v2_rating_sentiment', 'risk': risk, 'flags': flags,
              'sentiment': sentiment, 'screenedAt': utc_now_iso()}
    if risk == 'uncertain':
        result['reason'] = 'insufficient_text' if not meaningful else 'rating_alignment_unclear'
    return result


def _screening(comment, rating):
    comment = comment if isinstance(comment, str) else ''
    try:
        result = screen_review(comment, rating)
    except Exception:
        result = {'method': 'unavailable', 'risk': 'uncertain', 'flags': [],
                  'reason': 'screening_unavailable', 'screenedAt': utc_now_iso()}
    result['contentHash'] = hashlib.sha256(comment.encode()).hexdigest()
    result['rating'] = rating
    result['policyVersion'] = SCREENING_POLICY
    return result


def screen_submission(comment, rating):
    screening = _screening(comment, rating)
    sentiment = screening.get('sentiment', {})
    eligible_ratings = {
        'positive': (4, 5), 'negative': (1, 2), 'neutral': (3,), 'mixed': (3,),
    }
    if screening['risk'] == 'low':
        if len(re.findall(r'\w+', comment)) < 3:
            screening.update(risk='uncertain', reason='insufficient_text')
        elif rating not in eligible_ratings.get(sentiment.get('label'), ()):
            screening.update(risk='uncertain', reason='rating_alignment_unclear')
    approved = screening['risk'] == 'low'
    return {
        'moderationStatus': 'reviewed' if approved else 'pending_review',
        'feedbackStatus': 'visible',
        'screening': screening,
        'moderationDecision': {'actor': 'system', 'outcome': 'approve' if approved else 'pending',
                               'at': screening['screenedAt'], 'policyVersion': SCREENING_POLICY},
    }


def current_screen(item):
    comment = item.get('comment') if isinstance(item.get('comment'), str) else ''
    rating = item.get('rating')
    stored = item.get('screening')
    if (isinstance(stored, dict) and stored.get('policyVersion') == SCREENING_POLICY
            and stored.get('rating') == rating
            and stored.get('contentHash') == hashlib.sha256(comment.encode()).hexdigest()):
        return stored
    return screen_submission(comment, rating)['screening']


def published_review(item):
    try:
        rating = float(item.get('rating'))
    except (ValueError, TypeError, OverflowError):
        return False
    return (isfinite(rating) and 1 <= rating <= 5
            and item.get('feedbackStatus') == 'visible'
            and item.get('moderationStatus') in {'reviewed', 'approved'})


def approved_reviews(records):
    """One approved contribution per owner; preserve historical source duplicates."""
    unique = {}
    for item in sorted(records, key=lambda x: str(x.get('updatedAt') or x.get('submittedAt') or ''), reverse=True):
        if published_review(item):
            unique.setdefault(item.get('travellerId') or item.get('id'), item)
    return list(unique.values())


class ReviewConflict(ValueError):
    pass


def stage_public_review(write, projection, document_id, record):
    from services.public_content_projection import public_review
    if published_review(record):
        write.set(projection, public_review({**record, 'id': document_id}))
    else:
        write.delete(projection)


def stage_review_decision(write, source, record):
    decision = record.get('moderationDecision')
    if decision:
        audit = {**decision, 'screening': record.get('screening', {})}
        write.set(source.collection('moderation_history').document(review_revision(record)), audit)


def review_history(document_id):
    from firebase_service import get_db
    source = get_db().collection('feedback').document(document_id)
    history = [entry.to_dict() for entry in source.collection('moderation_history').stream()]
    return sorted(history, key=lambda entry: entry.get('at') or entry.get('removedAt') or entry.get('reviewedAt') or '',
                  reverse=True)


def commit_feedback(document_id, expected, patch=None):
    """CAS source and public projection together; prevent stale moderation approvals."""
    from firebase_service import get_db
    from google.cloud import firestore
    db = get_db()
    source = db.collection('feedback').document(document_id)
    projection = db.collection('public_destination_reviews').document(document_id)

    @firestore.transactional
    def commit(transaction):
        snap = source.get(transaction=transaction)
        current = snap.to_dict() if snap.exists else None
        if not current or review_revision(current) != review_revision(expected):
            raise ReviewConflict('This review changed. Refresh and try again.')
        if patch is None:
            transaction.delete(source)
            transaction.delete(projection)
            return True
        updated = {**current, **patch}
        if patch:
            transaction.update(source, patch)
        stage_public_review(transaction, projection, document_id, updated)
        if patch and 'moderationDecision' in patch:
            if not current.get('moderationDecision') and (current.get('reviewedBy') or current.get('removedBy')):
                # Capture a pre-policy Administrator decision before replacing its metadata.
                legacy = {key: current[key] for key in (
                    'reviewedBy', 'reviewedAt', 'removedBy', 'removedAt', 'reviewComment',
                    'moderationStatus', 'feedbackStatus',
                ) if key in current}
                transaction.set(source.collection('moderation_history').document(review_revision(current)), legacy)
            stage_review_decision(transaction, source, updated)
        return {'id': document_id, **updated}
    return commit(db.transaction())
