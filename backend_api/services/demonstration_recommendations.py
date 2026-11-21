"""Read-only simulation using existing approved examples; never saves snapshots."""
from copy import deepcopy
from collections import OrderedDict
from hashlib import sha256
from threading import Lock
from time import monotonic
from services.fyp_reviews import private_dataset, dataset_reviews, regional_demo_destinations, regional_demo_reviews
from services.local_catalog import DESTINATIONS
from services.destination_research import attraction_identities
from services.review_destination import review_candidate_id
from services.recommendation_review_evidence import approved_contributions, review_summaries
from services.penang_evaluation_coverage import REVIEWER_PROFILES


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
    return {uid: {**deepcopy(REVIEWER_PROFILES.get(uid) or choices[int(sha256(uid.encode()).hexdigest(), 16) % len(choices)]), 'synthetic': True}
            for uid in {str(row.get('travellerId') or '') for row in rows if row.get('synthetic') is True} if uid}


def load_sources(area='Penang'):
    candidates, rows = [], []
    if area in {'Penang', 'Malaysia'}:
        dataset = private_dataset()
        if not dataset:
            raise ValueError('The existing approved demonstration review data is unavailable.')
        ref, destinations = dataset
        rows.extend(dataset_reviews(ref, destinations))
        for identity in destinations:
            rows.extend(regional_demo_reviews(identity))
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


def evaluate(profile, candidates, rows, *, evidence_mode='demonstration'):
    if evidence_mode not in {'demonstration', 'fyp_evaluation'}:
        raise ValueError('The evaluation engine cannot produce genuine customer evidence.')
    from sequence_contract.domain_functions import (prepareRecommendationInput, applyContentBasedFiltering,
        applyCollaborativeFiltering, calculateRecommendationScore, rankRecommendations, deduplicateRecommendations)
    groups = approved_contributions(rows, demonstration=True)
    summaries = review_summaries(groups, demonstration=True)
    approved = [row for group in groups.values() for row in group]
    content = applyContentBasedFiltering(prepareRecommendationInput(profile, candidates))
    combined = applyCollaborativeFiltering(content, approved, simulated_profiles(rows), profile,
        evidenceMode=evidence_mode)
    scored = calculateRecommendationScore(combined, summaries, evidenceMode=evidence_mode)
    for item in scored:
        summary = summaries.get(review_candidate_id(item)) or {}
        item['demonstrationReviewSummary'] = {**summary, 'ratingBasis': 'private_illustrative',
            'reviewEnvironment': 'private_demo', 'privateExamplesAllowed': True}
        item['recommendationSource'] = 'demonstration_review_data'
    return rankRecommendations(deduplicateRecommendations(scored))


class EvaluationSession:
    """Owner-scoped, bounded, one-hour evaluation history; never a Firestore collection."""
    def __init__(self):
        self.snapshots, self.profiles = OrderedDict(), OrderedDict()
        self.lock = Lock()

    def _prune(self, records):
        for key, (expires, _) in list(records.items()):
            if expires <= monotonic():
                del records[key]
        while len(records) > 64:
            records.popitem(last=False)

    def save(self, record):
        with self.lock:
            self.snapshots[record['recommendationGenerationId']] = (monotonic() + 3600, deepcopy(record))
            self._prune(self.snapshots)

    def snapshot(self, uid, generation_id='', scope_key=None):
        with self.lock:
            self._prune(self.snapshots)
            candidates = ([self.snapshots[generation_id][1]] if generation_id in self.snapshots else []) if generation_id else [value[1] for value in reversed(self.snapshots.values())]
            return next((deepcopy(row) for row in candidates if row['travellerId'] == uid
                and (scope_key is None or row['canonicalDestinationScope']['scopeKey'] == scope_key)), None)

    def learning(self, uid, update=None):
        with self.lock:
            self._prune(self.profiles)
            profile = deepcopy(self.profiles.get(uid, (0, None))[1])
            if update is None:
                return profile
            result = update(profile)
            result[0].update(synthetic=True, recommendationEvidenceMode='fyp_evaluation')
            self.profiles[uid] = (monotonic() + 3600, deepcopy(result[0]))
            self.profiles.move_to_end(uid)
            self._prune(self.profiles)
            return result
