"""Read-only simulation using existing approved examples; never saves snapshots."""
from copy import deepcopy
from hashlib import sha256
from services.fyp_reviews import private_dataset, dataset_reviews, regional_demo_destinations, regional_demo_reviews
from services.local_catalog import DESTINATIONS
from services.destination_research import attraction_identities
from services.review_destination import review_candidate_id
from services.recommendation_review_evidence import approved_contributions, review_summaries


SIMULATED_PROFILES = {
    'culture': {'label': 'Culture and photography', 'interests': ['Culture', 'Photography', 'Food'],
        'travelType': 'Mixed', 'travelPace': 'Relaxed', 'travelPurpose': 'Holiday', 'travelPersonality': 'Explorer'},
    'nature': {'label': 'Nature and adventure', 'interests': ['Nature', 'Adventure', 'Photography'],
        'travelType': 'Lesser-known places', 'travelPace': 'Packed', 'travelPurpose': 'Solo travel', 'travelPersonality': 'Explorer'},
    'family': {'label': 'Family and cultural visits', 'interests': ['Family', 'Culture', 'Photography'],
        'travelType': 'Popular landmarks', 'travelPace': 'Relaxed', 'travelPurpose': 'Family trip', 'travelPersonality': 'Planner'},
}


def simulated_profiles(rows):
    # Assignment is stable per fictional author and independent of their rating/comment.
    choices = list(SIMULATED_PROFILES.values())
    return {uid: {**deepcopy(choices[int(sha256(uid.encode()).hexdigest(), 16) % len(choices)]), 'synthetic': True}
            for uid in {str(row.get('travellerId') or '') for row in rows if row.get('synthetic') is True} if uid}


def load_sources(area='Penang'):
    candidates, rows = [], []
    if area in {'Penang', 'Malaysia'}:
        dataset = private_dataset()
        if not dataset:
            raise ValueError('The existing approved demonstration review data is unavailable.')
        ref, destinations = dataset
        rows.extend(dataset_reviews(ref, destinations))
        candidates.extend(deepcopy(list(destinations.values())))
    regional = regional_demo_destinations()
    for identity, place in regional.items():
        if area == 'Malaysia' or place.get('state') == area:
            candidates.append(deepcopy(place))
            rows.extend(regional_demo_reviews(identity))
    if not candidates:
        raise ValueError('No existing demonstration review data is available for this area.')
    return prepare_candidates(candidates), rows


def prepare_candidates(candidates):
    metadata = {review_candidate_id(row): row for row in [*attraction_identities(), *DESTINATIONS]}
    result = []
    for row in candidates:
        identity = review_candidate_id(row)
        place = {**deepcopy(metadata.get(identity, {})), **row, 'destinationId': identity,
                 'reviewDestinationId': identity, 'ratingSource': 'unverified_local_catalog'}
        if place.get('state'):
            place.setdefault('address', f"{place.get('city', '')}, {place['state']}, Malaysia")
        result.append(place)
    return result


def evaluate(profile, candidates, rows):
    from sequence_contract.domain_functions import (prepareRecommendationInput, applyContentBasedFiltering,
        applyCollaborativeFiltering, calculateRecommendationScore, rankRecommendations, deduplicateRecommendations)
    groups = approved_contributions(rows, demonstration=True)
    summaries = review_summaries(groups, demonstration=True)
    approved = [row for group in groups.values() for row in group]
    content = applyContentBasedFiltering(prepareRecommendationInput(profile, candidates))
    combined = applyCollaborativeFiltering(content, approved, simulated_profiles(rows), profile,
        evidenceMode='demonstration')
    scored = calculateRecommendationScore(combined, summaries, evidenceMode='demonstration')
    for item in scored:
        summary = summaries.get(review_candidate_id(item)) or {}
        item['demonstrationReviewSummary'] = {**summary, 'ratingBasis': 'private_illustrative',
            'reviewEnvironment': 'private_demo', 'privateExamplesAllowed': True}
        item['recommendationSource'] = 'demonstration_review_data'
    return rankRecommendations(deduplicateRecommendations(scored))
