"""Local review validation, deterministic NLP triage and publication policy."""
import hashlib
import json
import re
import unicodedata
from math import isfinite

from utils import utc_now_iso
from services.review_sentiment import classify_review_sentiment


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
    return {'method': 'local_rules_v2_rating_sentiment', 'risk': risk, 'flags': flags,
            'sentiment': sentiment, 'screenedAt': utc_now_iso()}


def pending_screen(comment, rating=None):
    comment = comment if isinstance(comment, str) else ''
    try:
        result = screen_review(comment, rating)
    except Exception:
        result = {'method': 'unavailable', 'risk': 'uncertain', 'flags': [], 'screenedAt': utc_now_iso()}
    result['contentHash'] = hashlib.sha256(comment.encode()).hexdigest()
    # Existing policy requires Administrator review; low-risk is not auto-approved.
    return {'moderationStatus': 'pending_review', 'feedbackStatus': 'visible', 'screening': result}


def current_screen(item):
    comment = item.get('comment') if isinstance(item.get('comment'), str) else ''
    # Recompute cheap local triage: legacy/client-era cached indicators are not authority.
    return pending_screen(comment, item.get('rating'))['screening']


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


def commit_feedback(document_id, expected, patch=None):
    """CAS source and public projection together; prevent stale moderation approvals."""
    from firebase_service import get_db
    from google.cloud import firestore
    from services.public_content_projection import public_review
    db = get_db()
    source = db.collection('feedback').document(document_id)
    projection = db.collection('public_destination_reviews').document(document_id)

    @firestore.transactional
    def commit(transaction):
        snap = source.get(transaction=transaction)
        current = snap.to_dict() if snap.exists else None
        keys = ('travellerId', 'destinationId', 'rating', 'comment', 'updatedAt', 'moderationStatus', 'feedbackStatus')
        if not current or any(current.get(key) != expected.get(key) for key in keys):
            raise ReviewConflict('This review changed. Refresh and try again.')
        if patch is None:
            transaction.delete(source)
            transaction.delete(projection)
            return True
        updated = {**current, **patch}
        if patch:
            transaction.update(source, patch)
        if published_review(updated):
            transaction.set(projection, public_review({'id': document_id, **updated}))
        else:
            transaction.delete(projection)
        return {'id': document_id, **updated}
    return commit(db.transaction())
