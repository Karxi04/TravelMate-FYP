"""Review-derived evidence without changing review provenance or moderation."""
from math import isfinite
from services.review_destination import review_candidate_id, review_destination_id
from services.review_service import approved_reviews, genuine_review


def approved_contributions(records, *, demonstration=False):
    grouped = {}
    for row in records or []:
        if isinstance(row.get('rating'), bool):
            continue
        allowed = row.get('synthetic') is True if demonstration else genuine_review(row)
        if allowed:
            grouped.setdefault(review_destination_id(str(row.get('destinationId') or '')), []).append(row)
    return {identity: approved_reviews(rows) for identity, rows in grouped.items() if identity}


def review_summaries(groups, *, demonstration=False):
    return {identity: {'rating': sum(float(row['rating']) for row in rows) / len(rows),
            'reviews': len(rows), 'synthetic': demonstration,
            'source': 'demonstration_approved_reviews' if demonstration else 'genuine_approved_local_reviews'}
            for identity, rows in groups.items() if rows}


def _rating(value):
    try:
        number = float(value)
        return number if not isinstance(value, bool) and isfinite(number) and 1 <= number <= 5 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _count(value):
    try:
        number = float(value)
        return int(number) if not isinstance(value, bool) and isfinite(number) and number >= 0 and number.is_integer() else None
    except (TypeError, ValueError, OverflowError):
        return None


def popularity_evidence(item, summaries=None, *, demonstration=False):
    source = 'neutral_unverified_local_catalog' if item.get('ratingSource') == 'unverified_local_catalog' else 'neutral_missing_rating'
    rating = count = None
    if not demonstration and genuine_review(item) and item.get('ratingSource') == 'provider':
        rating, count = _rating(item.get('rating')), _count(item.get('reviews'))
        if rating is not None:
            source = 'provider_rating_review_count'
    if rating is None:
        summary = (summaries or {}).get(review_candidate_id(item)) or {}
        expected = 'demonstration_approved_reviews' if demonstration else 'genuine_approved_local_reviews'
        if summary.get('source') == expected and summary.get('synthetic') is demonstration:
            local_rating, local_count = _rating(summary.get('rating')), _count(summary.get('reviews'))
            if local_rating is not None and local_count and local_count > 0:
                rating, count, source = local_rating, local_count, expected
    score = min(100.0, rating / 5 * 80 + min(20.0, (count or 0) / 500)) if rating is not None else 50.0
    return {'score': score, 'source': source, 'rating': rating, 'reviewCount': count,
            'fallbackReason': None if rating is not None else 'no_approved_demonstration_reviews' if demonstration
                              else 'no_verified_provider_or_approved_genuine_local_reviews'}
