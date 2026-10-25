from datetime import datetime, date
from math import radians, sin, cos, sqrt, atan2, isfinite
from utils import utc_now_iso
from services.recommendation_taxonomy import (
    candidate_concepts,
    concepts_for,
    display_concepts,
    normalize_budget,
    normalize_pace,
    normalize_personality,
    normalize_phrase,
    normalize_purpose,
)
from services.preference_learning import LEARNED_INTEREST_STRENGTH
from services.activity_pricing import activity_pricing, traveller_count
from sequence_contract.validators import (
    ACCOMMODATION_CHOICES,
    CAR_RENTAL_CHOICES,
    TRAVEL_MODES,
)


def _float(value, default=0.0):
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return float(default)


def _text(value):
    return str(value or '').strip()


def _tokens(*values):
    words = set()
    for value in values:
        if isinstance(value, (list, tuple, set)):
            value = ' '.join(str(x) for x in value)
        raw = str(value or '').lower().replace('/', ' ').replace('-', ' ')
        words.update(x.strip('.,()[]') for x in raw.split() if len(x.strip('.,()[]')) > 2)
    return words


def _destination_id(item):
    return str(item.get('destinationId') or item.get('place_id') or item.get('data_id') or item.get('id') or item.get('title') or item.get('name') or '')


def createPreferenceProfile(data):
    return {**data, 'updatedAt': utc_now_iso()}


def updatePreferenceProfile(existing, updates):
    return {**(existing or {}), **updates, 'updatedAt': utc_now_iso()}


def applyHomepageCategoryMatching(preferenceProfile):
    interests = [str(x).strip() for x in preferenceProfile.get('interests', []) if str(x).strip()]
    return interests[:5] or ['Culture', 'Food', 'Nature']


def applyDestinationFilter(items, filterOption=None):
    if not filterOption:
        return list(items)
    if isinstance(filterOption, str):
        value = filterOption.lower()
        return [x for x in items if value in (' '.join(str(x.get(k, '')) for k in ['type', 'category', 'title', 'description'])).lower()]
    return list(items)


def applyDestinationSorting(items, sortOption=None):
    items = list(items)
    if sortOption == 'rating':
        return sorted(items, key=lambda x: _float(x.get('rating')), reverse=True)
    if sortOption == 'name':
        return sorted(items, key=lambda x: str(x.get('title') or x.get('name') or '').lower())
    return items


def checkDestinationExists(itinerary, destinationId):
    return any(str(x.get('destinationId', '')) == str(destinationId) for x in (itinerary or {}).get('activities', []))


def checkDestinationLimit(itinerary, maxDestinations=20):
    return len((itinerary or {}).get('activities', [])) < maxDestinations


# ---------------------------------------------------------------------------
# FR4 Hybrid Recommendation Engine
# Exact sequence names are intentionally retained.
# ---------------------------------------------------------------------------

def prepareRecommendationInput(preferenceProfile, destinationData, collaborativeData=None):
    return {
        'preferenceProfile': preferenceProfile or {},
        'destinationData': destinationData or [],
        'collaborativeData': collaborativeData or [],
    }


def applyContentBasedFiltering(recommendationInput):
    """Score destinations against the traveller profile (0-100).

    The logic is intentionally simple and explainable for an FYP viva. Related phrases
    are mapped into a small shared taxonomy. Interests carry the largest contribution;
    the remaining factors are used only when the destination has defensible evidence.
    """
    pref = recommendationInput.get('preferenceProfile', {}) or {}
    raw_interests = [
        value for value in pref.get('interests', []) if _text(value)
    ]
    interest_concepts = concepts_for(raw_interests)
    excluded_concepts = concepts_for(pref.get('excludedInterests', []))
    travel_type_concepts = concepts_for(pref.get('travelType'))
    requested_budget = normalize_budget(pref.get('budgetRange'))
    requested_pace = normalize_pace(pref.get('travelPace'))
    requested_purpose = normalize_purpose(pref.get('travelPurpose'))
    requested_personality = normalize_personality(pref.get('travelPersonality'))

    results = []
    for item in recommendationInput.get('destinationData', []) or []:
        destination_concepts = candidate_concepts(item)
        if excluded_concepts.intersection(destination_concepts):
            continue
        matched_concepts = interest_concepts.intersection(destination_concepts)
        if interest_concepts:
            # Preferences are alternatives, not an attraction's required checklist.
            # Candidate-side coverage rewards additional relevant evidence without
            # penalising a specialist when unrelated user interests are added.
            interest_coverage = len(matched_concepts) / max(1, len(destination_concepts))
            primary_concepts = concepts_for([
                item.get('title'), item.get('name'), item.get('type')
            ])
            primary_match = bool(
                primary_concepts.intersection(interest_concepts))
            base_interest_score = interest_coverage * (
                1.0 if primary_match else 0.80)
        else:
            base_interest_score = 0.55
            primary_match = False
        learned_affinities = pref.get('learnedAffinities') or {}
        learned_matches = {
            concept: max(-1.0, min(1.0, _float(learned_affinities.get(concept))))
            for concept in destination_concepts
            if concept in learned_affinities
        }
        learned_mean = (
            sum(learned_matches.values()) / len(learned_matches)
            if learned_matches else 0.0
        )
        learned_adjustment = LEARNED_INTEREST_STRENGTH * learned_mean
        interest_score = max(
            -LEARNED_INTEREST_STRENGTH,
            min(1.0, base_interest_score + learned_adjustment),
        )
        type_score = _concept_compatibility(
            travel_type_concepts, destination_concepts, neutral=0.60)
        pace_score, pace_applied = _pace_suitability(requested_pace, item)
        budget_score, budget_applied = _budget_suitability(requested_budget, item)
        purpose_score, purpose_applied = _purpose_suitability(requested_purpose, item)
        personality_score, personality_applied = _personality_suitability(
            requested_personality, item)

        # Internal content score only. The documented hybrid score remains 60/30/10.
        content_score = 100.0 * (
            interest_score * 0.55
            + type_score * 0.15
            + pace_score * 0.10
            + budget_score * 0.10
            + purpose_score * 0.06
            + personality_score * 0.04
        )
        matched_interests = display_concepts(matched_concepts)
        content_signals = {
            'interests': {
                'score': round(interest_score * 100.0, 2),
                'applied': bool(interest_concepts),
                'matched': matched_interests,
                'requestedConcepts': sorted(interest_concepts),
                'primaryCategoryMatch': primary_match,
                'baseScore': round(base_interest_score * 100.0, 2),
                'learnedAdjustment': round(learned_adjustment * 100.0, 2),
                'learnedPositive': display_concepts([
                    concept for concept, value in learned_matches.items()
                    if value >= 0.10
                ]),
                'learnedNegative': display_concepts([
                    concept for concept, value in learned_matches.items()
                    if value <= -0.10
                ]),
            },
            'travelType': {
                'score': round(type_score * 100.0, 2),
                'applied': bool(travel_type_concepts),
                'matched': display_concepts(
                    travel_type_concepts.intersection(destination_concepts)),
            },
            'pace': _signal(pace_score, pace_applied, requested_pace),
            'budget': _signal(budget_score, budget_applied, requested_budget),
            'travelPurpose': _signal(
                purpose_score, purpose_applied, requested_purpose),
            'travelPersonality': _signal(
                personality_score, personality_applied, requested_personality),
        }

        results.append({
            **item,
            'destinationId': _destination_id(item),
            'contentScore': round(max(0.0, min(100.0, content_score)), 2),
            'matchedInterests': matched_interests,
            'matchedProfileTerms': [
                key for key, value in content_signals.items()
                if value.get('applied') and _float(value.get('score')) >= 80.0
            ],
            'destinationConcepts': sorted(destination_concepts),
            'contentSignals': content_signals,
        })
    return results


def _signal(score, applied, requested):
    return {
        'score': round(score * 100.0, 2),
        'applied': bool(applied),
        'requested': requested,
    }


def _concept_compatibility(preferred, supported, neutral=0.55):
    if not preferred:
        return neutral
    if not supported:
        return 0.45
    return len(set(preferred).intersection(supported)) / max(1, len(preferred))


def _normalised_values(value, normalizer):
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return {normalizer(entry) for entry in values if normalizer(entry)}


def _matrix_suitability(requested, supported, matrix, neutral=0.55):
    if not requested or not supported:
        return neutral, False
    return max(matrix.get((requested, value), 0.35) for value in supported), True


def _budget_suitability(requested, item):
    supported = _normalised_values(
        item.get('budgetLevel') or item.get('budgetRange'), normalize_budget)
    matrix = {
        ('budget', 'budget'): 1.00,
        ('budget', 'moderate'): 0.60,
        ('budget', 'premium'): 0.20,
        ('moderate', 'budget'): 0.90,
        ('moderate', 'moderate'): 1.00,
        ('moderate', 'premium'): 0.65,
        ('premium', 'budget'): 0.85,
        ('premium', 'moderate'): 0.95,
        ('premium', 'premium'): 1.00,
    }
    return _matrix_suitability(requested, supported, matrix)


def _pace_suitability(requested, item):
    supported = _normalised_values(item.get('pace'), normalize_pace)
    matrix = {
        ('relaxed', 'relaxed'): 1.00,
        ('relaxed', 'moderate'): 0.72,
        ('relaxed', 'active'): 0.35,
        ('moderate', 'relaxed'): 0.82,
        ('moderate', 'moderate'): 1.00,
        ('moderate', 'active'): 0.75,
        ('active', 'relaxed'): 0.45,
        ('active', 'moderate'): 0.82,
        ('active', 'active'): 1.00,
    }
    return _matrix_suitability(requested, supported, matrix)


def _purpose_suitability(requested, item):
    supported = _normalised_values(item.get('purpose'), normalize_purpose)
    if requested == 'holiday' and supported:
        return (1.0 if 'holiday' in supported else 0.78), True
    return _matrix_suitability(
        requested, supported, {(value, value): 1.0 for value in supported})


def _personality_suitability(requested, item):
    supported = _normalised_values(item.get('personality'), normalize_personality)
    if requested == 'balanced' and supported:
        return 0.85, True
    return _matrix_suitability(
        requested, supported, {(value, value): 1.0 for value in supported})


def applyCollaborativeFiltering(items, collaborativeData=None, peerPreferences=None,
                                currentPreference=None, currentTravellerId=None):
    """Compute an explainable collaborative score (0-100).

    Feedback from other travellers is used directly. If peer preference profiles are
    available, their interest/type/pace similarity weights their destination ratings.
    Sparse data is blended toward a neutral constant. This preserves the documented
    30% collaborative component without pretending provider ratings are peer evidence.
    """
    peer_preferences = peerPreferences or {}
    current = currentPreference or {}
    current_interests = concepts_for(current.get('interests', []))

    ratings = {}
    for row in collaborativeData or []:
        did = str(row.get('destinationId') or '')
        if not did:
            continue
        uid = str(row.get('travellerId') or '')
        if currentTravellerId and uid == str(currentTravellerId):
            continue
        rating = max(0.0, min(5.0, _float(row.get('rating'))))
        peer = peer_preferences.get(uid) if isinstance(peer_preferences, dict) else None
        if not peer or not current:
            continue
        peer_interests = concepts_for(peer.get('interests', []))
        union = current_interests.union(peer_interests)
        jaccard = (
            len(current_interests.intersection(peer_interests)) / max(1, len(union))
            if union else 0.0
        )
        type_match = _set_similarity(
            concepts_for(peer.get('travelType')),
            concepts_for(current.get('travelType')),
        )
        pace_match = _exact_profile_match(peer, current, 'travelPace', normalize_pace)
        purpose_match = _exact_profile_match(
            peer, current, 'travelPurpose', normalize_purpose)
        personality_match = _exact_profile_match(
            peer, current, 'travelPersonality', normalize_personality)
        similarity = (
            0.60 * jaccard
            + 0.15 * type_match
            + 0.10 * pace_match
            + 0.10 * purpose_match
            + 0.05 * personality_match
        )
        if similarity < 0.25:
            continue
        ratings.setdefault(did, []).append((rating, similarity))

    output = []
    for item in items or []:
        did = _destination_id(item)
        values = ratings.get(did, [])
        if values:
            weighted_sum = sum(r * w for r, w in values)
            total_weight = sum(w for _, w in values) or 1.0
            avg_rating = weighted_sum / total_weight
            raw_collaborative_score = (avg_rating / 5.0) * 100.0
            collaborative_confidence = min(1.0, total_weight / 3.0)
            collaborative_score = 50.0 + (
                raw_collaborative_score - 50.0) * collaborative_confidence
            collaborative_source = f'{len(values)} similar traveller rating(s)'
        else:
            raw_collaborative_score = 50.0
            collaborative_confidence = 0.0
            collaborative_score = 50.0
            collaborative_source = 'neutral cold-start baseline (no similar traveller evidence)'

        output.append({
            **item,
            'collaborativeScore': round(collaborative_score, 2),
            'rawCollaborativeScore': round(raw_collaborative_score, 2),
            'collaborativeConfidence': round(collaborative_confidence, 3),
            'collaborativeRatingCount': len(values),
            'collaborativeSource': collaborative_source,
        })
    return output


def _set_similarity(left, right):
    union = set(left or []).union(right or [])
    return len(set(left or []).intersection(right or [])) / max(1, len(union)) if union else 0.0


def _exact_profile_match(peer, current, field, normalizer):
    peer_value = normalizer(peer.get(field))
    current_value = normalizer(current.get(field))
    return 1.0 if peer_value and peer_value == current_value else 0.0


def calculateRecommendationScore(items):
    """Weighted scoring: 60% content + 30% collaborative + 10% popularity."""
    output = []
    for item in items or []:
        content = max(0.0, min(100.0, _float(item.get('contentScore'))))
        collaborative = max(0.0, min(100.0, _float(item.get('collaborativeScore'))))
        rating = min(5.0, max(0.0, _float(item.get('rating'))))
        reviews = max(0.0, _float(item.get('reviews')))
        # Rating dominates popularity; review count adds only a small saturation boost.
        popularity = min(100.0, (rating / 5.0) * 80.0 + min(20.0, reviews / 500.0))
        score = content * 0.60 + collaborative * 0.30 + popularity * 0.10

        reasons = _recommendation_reasons(item, popularity)
        reason = f"{round(score)}% match"
        if reasons:
            reason += ' • ' + ' • '.join(reasons)
        else:
            reason += ' • Limited profile evidence; neutral fallback applied'

        output.append({
            **item,
            'popularityScore': round(popularity, 2),
            'score': round(score, 2),
            'finalScore': round(score, 2),
            'scoreBreakdown': {
                'contentWeight': 0.60,
                'collaborativeWeight': 0.30,
                'popularityWeight': 0.10,
                'content': round(content, 2),
                'collaborative': round(collaborative, 2),
                'popularity': round(popularity, 2),
            },
            'reason': reason,
            'recommendationReason': reason,
            'matchReasons': reasons,
        })
    return output


def _recommendation_reasons(item, popularity):
    reasons = []
    matches = item.get('matchedInterests', []) or []
    signals = item.get('contentSignals', {}) or {}
    if matches:
        reasons.append(f"Matches your {', '.join(matches[:2])} interests")
    learned_positive = (
        (signals.get('interests', {}) or {}).get('learnedPositive', []) or [])
    if learned_positive:
        reasons.append(
            f"Based on your recent interest in {', '.join(learned_positive[:2]).lower()}")
    primary_factor_labels = (
        ('travelType', 'travel style'),
        ('pace', 'travel pace'),
        ('budget', 'budget preference'),
    )
    for key, label in primary_factor_labels:
        signal = signals.get(key, {}) or {}
        if signal.get('applied') and _float(signal.get('score')) >= 80.0:
            reasons.append(f'Fits your {label}')
    confidence = _float(item.get('collaborativeConfidence'))
    if confidence >= 0.25 and _float(item.get('rawCollaborativeScore')) >= 70.0:
        reasons.append('Highly rated by similar travellers')
    for key, label in (
        ('travelPurpose', 'travel purpose'),
        ('travelPersonality', 'traveller personality'),
    ):
        signal = signals.get(key, {}) or {}
        if signal.get('applied') and _float(signal.get('score')) >= 80.0:
            reasons.append(f'Fits your {label}')
    if popularity >= 85.0:
        reasons.append('Popular and well reviewed')
    return reasons[:5]


def rankRecommendations(items):
    ranked = sorted(
        items or [],
        key=lambda x: (_float(x.get('score')), _float(x.get('rating')), _float(x.get('reviews'))),
        reverse=True,
    )
    return [{**item, 'rankNo': index + 1} for index, item in enumerate(ranked)]


def deduplicateRecommendations(items):
    """Keep the best-scoring representation of each destination identity."""
    ranked = sorted(
        items or [],
        key=lambda item: (_float(item.get('score')), _float(item.get('rating'))),
        reverse=True,
    )
    seen_ids = set()
    seen_names = set()
    output = []
    for item in ranked:
        destination_id = normalize_phrase(_destination_id(item))
        name = normalize_phrase(item.get('title') or item.get('name'))
        if (destination_id and destination_id in seen_ids) or (name and name in seen_names):
            continue
        if destination_id:
            seen_ids.add(destination_id)
        if name:
            seen_names.add(name)
        output.append(item)
    return output


def diversifyRecommendations(items, preferenceProfile=None, limit=12):
    """Greedy lightweight reranking that keeps strong preferences dominant."""
    remaining = [dict(item) for item in (items or [])]
    selected = []
    category_counts = {}
    preferred = concepts_for((preferenceProfile or {}).get('interests', []))
    while remaining and len(selected) < max(0, int(limit or 0)):
        best_index = 0
        best_adjusted = float('-inf')
        best_category = 'general'
        best_penalty = 0.0
        for index, item in enumerate(remaining):
            concepts = set(item.get('destinationConcepts') or candidate_concepts(item))
            preferred_matches = sorted(concepts.intersection(preferred))
            category = preferred_matches[0] if preferred_matches else (
                sorted(concepts)[0] if concepts else 'general')
            repeated = category_counts.get(category, 0)
            penalty_rate = 2.0 if category in preferred else 7.0
            penalty = repeated * penalty_rate
            adjusted = _float(item.get('score')) - penalty
            if adjusted > best_adjusted:
                best_index = index
                best_adjusted = adjusted
                best_category = category
                best_penalty = penalty
        chosen = remaining.pop(best_index)
        chosen['diversityCategory'] = best_category
        chosen['diversityAdjustedScore'] = round(best_adjusted, 2)
        if best_penalty:
            chosen['diversityReason'] = 'Light category repetition penalty applied'
        selected.append(chosen)
        category_counts[best_category] = category_counts.get(best_category, 0) + 1
    return [{**item, 'rankNo': index + 1} for index, item in enumerate(selected)]


# ---------------------------------------------------------------------------
# FR5 Smart Itinerary & Budget Planner
# ---------------------------------------------------------------------------

def createItinerary(data, travellerId):
    return {
        **data,
        'travellerId': travellerId,
        'status': data.get('status', 'draft'),
        'activities': data.get('activities', []),
        'createdAt': utc_now_iso(),
        'updatedAt': utc_now_iso(),
    }


def addActivity(itinerary, activityData):
    itinerary = dict(itinerary or {})
    activities = list(itinerary.get('activities', []))
    activities.append({'activityId': activityData.get('activityId') or f'A{len(activities) + 1}', **activityData})
    itinerary['activities'] = activities
    itinerary['updatedAt'] = utc_now_iso()
    return itinerary


def removeActivity(itinerary, activityId):
    itinerary = dict(itinerary or {})
    itinerary['activities'] = [x for x in itinerary.get('activities', []) if str(x.get('activityId')) != str(activityId)]
    itinerary['updatedAt'] = utc_now_iso()
    return itinerary


def rearrangeActivity(itinerary, orderedActivityIds):
    itinerary = dict(itinerary or {})
    existing = list(itinerary.get('activities', []))
    by_id = {str(x.get('activityId')): x for x in existing}
    ordered = [by_id[str(i)] for i in orderedActivityIds if str(i) in by_id]
    remaining = [x for x in existing if str(x.get('activityId')) not in {str(i) for i in orderedActivityIds}]
    itinerary['activities'] = ordered + remaining
    itinerary['updatedAt'] = utc_now_iso()
    return itinerary


def updateActivity(itinerary, activityId, changes):
    itinerary = dict(itinerary or {})
    itinerary['activities'] = [
        {**x, **changes} if str(x.get('activityId')) == str(activityId) else x
        for x in itinerary.get('activities', [])
    ]
    itinerary['updatedAt'] = utc_now_iso()
    return itinerary


def _budget_amount(value):
    try:
        amount = float(value or 0)
        return amount if isfinite(amount) and amount >= 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def _budget_choice(data, field, allowed):
    value = str(data.get(field) or 'undecided').strip().lower()
    return value if value in allowed else 'undecided'


def _expense(amount, state, provenance, **details):
    return {
        'amount': round(_budget_amount(amount), 2),
        'currency': 'MYR',
        'state': state,
        'provenance': provenance,
        **details,
    }


def _simulated_selection(selection, source=None):
    values = {
        str(source or '').strip().lower(),
        str(selection.get('source') or '').strip().lower(),
        str(selection.get('transactionMode') or '').strip().lower(),
        str(selection.get('rateProvenance') or '').strip().lower(),
    }
    return bool(selection.get('sandbox') or selection.get('isSimulated') or values.intersection({
        'sample_fixture', 'test_fixture', 'local', 'local_demo',
        'provider_sandbox', 'sandbox_provider_quote',
    }))


def calculateBudget(itineraryOrSelections):
    data = itineraryOrSelections or {}
    limit = _budget_amount(data.get('budgetLimit'))
    has_budget_limit = data.get('budgetLimit') not in (None, '')
    travellers = traveller_count(data.get('travellerCount', 1))
    travel_mode_raw = data.get('travelMode')
    has_explicit_travel_mode = travel_mode_raw not in (None, '')
    travel_mode = _budget_choice(data, 'travelMode', TRAVEL_MODES)
    accommodation_choice = _budget_choice(
        data, 'accommodationChoice', ACCOMMODATION_CHOICES)
    rental_choice = _budget_choice(data, 'carRentalChoice', CAR_RENTAL_CHOICES)
    pending = []
    excluded = []
    limitations = []

    raw_flight = data.get('flightCost')
    if raw_flight in (None, '') and isinstance(data.get('selectedFlight'), dict):
        raw_flight = data['selectedFlight'].get('price')
    selected_flight = data.get('selectedFlight') if isinstance(data.get('selectedFlight'), dict) else {}
    flight_currency = str(data.get('flightCurrency') or selected_flight.get('currency') or '').upper()
    flight_basis = data.get('flightPriceBasis') or selected_flight.get('priceBasis')
    flight_issue = bool(selected_flight) and (
        flight_currency != 'MYR' or not flight_basis
        or selected_flight.get('priceStatus') == 'unknown'
        or _budget_amount(raw_flight) <= 0
    )
    flight = 0.0 if flight_issue else _budget_amount(raw_flight)
    flight_selection_status = data.get('flightSelectionStatus')
    has_valid_selected_flight = (
        bool(selected_flight)
        and not flight_issue
        and flight > 0
        and flight_selection_status != 'removed'
    )

    if not has_explicit_travel_mode:
        if has_valid_selected_flight:
            if _simulated_selection(selected_flight, data.get('flightSelectionSource')):
                flight_state = 'simulated_estimate'
                limitations.append('The selected flight price is a planning or sandbox estimate, not a completed reservation.')
            else:
                flight_state = 'priced'
        elif selected_flight and (flight_issue or flight <= 0):
            flight_state = 'selected_unpriced'
            pending.append('flight')
        else:
            flight_state = 'undecided'
            pending.append('flight')
    elif travel_mode == 'flight':
        if not selected_flight or flight_issue or flight <= 0:
            flight_state = 'selected_unpriced'
            pending.append('flight')
        elif _simulated_selection(selected_flight, data.get('flightSelectionSource')):
            flight_state = 'simulated_estimate'
            limitations.append('The selected flight price is a planning or sandbox estimate, not a completed reservation.')
        else:
            flight_state = 'priced'
    elif travel_mode == 'undecided':
        flight_state = 'undecided'
        pending.append('flight')
        if selected_flight:
            limitations.append('A historical flight selection is attached, but travel mode is undecided; flight selection remains pending confirmation.')
    else:
        flight = 0.0
        flight_state = 'not_required'
        if selected_flight:
            limitations.append(f"An attached flight selection conflicts with the selected '{travel_mode}' travel mode; the non-flight choice takes precedence.")

    nights = max(0, _trip_days(data) - 1)
    hotel_is_explicit = data.get('hotelCost') not in (None, '')
    rooms = max(1, int(_float(data.get('roomQuantity'), 1)))
    nightly_rate = _budget_amount(data.get('hotelNightlyRate') or data.get('nightlyRate'))
    selected_hotel = data.get('selectedHotel') if isinstance(data.get('selectedHotel'), dict) else {}
    hotel_currency = str(data.get('hotelCurrency') or selected_hotel.get('currency') or '').upper()
    hotel_currency_issue = hotel_is_explicit and hotel_currency != 'MYR'
    hotel = 0.0 if hotel_currency_issue else (
        _budget_amount(data.get('hotelCost')) if hotel_is_explicit else round(nightly_rate * nights * rooms, 2)
    )
    if accommodation_choice == 'paid_hotel':
        if hotel <= 0 or (selected_hotel and hotel_currency_issue):
            hotel_state = 'selected_unpriced'
            pending.append('hotel')
        elif _simulated_selection(selected_hotel):
            hotel_state = 'simulated_estimate'
            limitations.append('The selected hotel price is a sandbox or simulated estimate, not a completed reservation.')
        else:
            hotel_state = 'priced'
    elif accommodation_choice == 'undecided':
        hotel_state = 'undecided'
        pending.append('hotel')
    elif accommodation_choice == 'other':
        hotel = 0.0
        hotel_state = 'excluded_outside_scope'
        excluded.append('accommodation')
        limitations.append('Costs for the selected other accommodation arrangement are outside the current planner scope.')
    else:
        hotel = 0.0
        hotel_state = 'not_required'

    selected_rental = data.get('selectedCarRental') if isinstance(data.get('selectedCarRental'), dict) else {}
    car_rental = _budget_amount(data.get('carRentalCost'))
    if rental_choice == 'selected':
        if not selected_rental or car_rental <= 0:
            rental_state = 'selected_unpriced'
            pending.append('carRental')
        else:
            rental_state = 'simulated_estimate'
            limitations.append('Car-rental pricing uses the simulated local catalogue and is not a live provider quote.')
    elif rental_choice == 'undecided':
        rental_state = 'undecided'
        pending.append('carRental')
    else:
        car_rental = 0.0
        rental_state = 'not_required'

    try:
        days = _trip_days(data)
    except Exception:
        days = 1
    transport = _budget_amount(data.get('transportCost')) if data.get('transportCost') not in (None, '') else round(35.0 * days, 2)
    food = _budget_amount(data.get('foodCost')) if data.get('foodCost') not in (None, '') else round(60.0 * travellers * days, 2)
    activity_items = [x for x in data.get('activities', []) if isinstance(x, dict)]
    pricing = [activity_pricing(x, data.get('travellerCount', 1)) for x in activity_items]
    activities = sum(x['effectiveCost'] for x in pricing)
    pricing_issues = sorted({issue for x in pricing for issue in x['pricingIssues']})
    activity_overlap = any(x['overlapsAllowance'] for x in pricing)
    if pricing_issues:
        activity_state = 'unit_unknown' if 'unknown_pricing_unit' in pricing_issues else 'unverified_estimate'
        pending.append('activities')
        limitations.append(
            'Some activity pricing units, amounts or source evidence are unknown or unverified.')
    else:
        activity_state = 'priced' if activity_items else 'not_required'
    if activity_overlap or (activities > 0 and pricing_issues):
        activity_overlap = True
        if 'activities' not in pending:
            pending.append('activities')
        limitations.append(
            'Activity spending may overlap food or local-transport allowances; amounts are retained pending clarification.')
    if any(x['costProvenance'] in {'catalog_estimate', 'user_entered'} for x in pricing):
        limitations.append('Activity prices include planning estimates, not verified current ticket prices.')
    if rental_choice == 'selected':
        limitations.append(
            'The local-transport allowance may overlap with selected car-rental spending.')
    if travel_mode == 'own_vehicle':
        excluded.append('ownVehicleFuelAndTolls')
        limitations.append(
            'Own-vehicle fuel and toll costs are outside the current planner scope.')
    elif travel_mode == 'other':
        excluded.append('otherTravel')
        limitations.append(
            'Costs for the selected other travel mode are outside the current planner scope.')

    total = flight + hotel + car_rental + transport + food + activities
    difference = limit - total if has_budget_limit else 0.0
    incomplete = bool(pending or excluded)
    status = 'over_budget' if has_budget_limit and total > limit else (
        'incomplete' if incomplete else 'within_budget')
    utilization = round((total / limit) * 100.0, 2) if limit > 0 else 0.0
    category_totals = {
        'flight': round(flight, 2),
        'hotel': round(hotel, 2),
        'carRental': round(car_rental, 2),
        'transport': round(transport, 2),
        'food': round(food, 2),
        'activities': round(activities, 2),
    }
    expense_breakdown = {
        'flight': _expense(
            flight, flight_state, 'selected_flight' if selected_flight else 'none',
            choice=travel_mode, priceBasis=flight_basis,
            priceSource=data.get('flightSelectionSource') or selected_flight.get('source'),
            selectionStatus=data.get('flightSelectionStatus')),
        'hotel': _expense(
            hotel, hotel_state,
            'selected_hotel' if selected_hotel else ('nightly_rate_estimate' if nightly_rate else 'none'),
            choice=accommodation_choice, priceBasis=selected_hotel.get('priceBasis'),
            priceSource=selected_hotel.get('rateProvenance') or selected_hotel.get('source'),
            selectionStatus=data.get('hotelSelectionStatus')),
        'carRental': _expense(
            car_rental, rental_state,
            'simulated_local_catalogue' if selected_rental else 'none',
            choice=rental_choice,
            priceSource=(selected_rental.get('source') or 'local') if selected_rental else None,
            selectionStatus='selected' if selected_rental else None),
        'transport': _expense(transport, 'priced', 'provided' if data.get('transportCost') not in (None, '') else 'estimated_daily_allowance'),
        'food': _expense(food, 'priced', 'provided' if data.get('foodCost') not in (None, '') else 'estimated_daily_allowance'),
        'activities': _expense(
            activities, activity_state, 'mixed_estimates',
            pricingIssues=pricing_issues, overlapsAllowance=activity_overlap),
    }
    if travel_mode == 'own_vehicle':
        expense_breakdown['ownVehicleFuelAndTolls'] = _expense(
            0, 'excluded_outside_scope', 'not_modelled')
    elif travel_mode == 'other':
        expense_breakdown['otherTravel'] = _expense(
            0, 'excluded_outside_scope', 'not_modelled')

    return {
        'limit': round(limit, 2),
        'budgetLimit': round(limit, 2),
        'travellers': travellers,
        'flight': category_totals['flight'],
        'hotel': category_totals['hotel'],
        'hotelNights': nights,
        'hotelRooms': rooms,
        'carRental': category_totals['carRental'],
        'transport': category_totals['transport'],
        'food': category_totals['food'],
        'activities': category_totals['activities'],
        'total': round(total, 2),
        'totalEstimatedCost': round(total, 2),
        'knownEstimatedSubtotal': round(total, 2),
        'categoryTotals': category_totals,
        'expenseBreakdown': expense_breakdown,
        'difference': round(difference, 2),
        'remaining': round(max(0.0, difference), 2) if has_budget_limit else 0.0,
        'overBy': round(max(0.0, -difference), 2) if has_budget_limit else 0.0,
        'utilizationPercent': utilization,
        'status': status,
        'affordabilityStatus': status,
        'completenessStatus': 'incomplete' if incomplete else 'complete',
        'pendingExpenseCategories': list(dict.fromkeys(pending)),
        'excludedExpenseCategories': list(dict.fromkeys(excluded)),
        'estimateLimitations': list(dict.fromkeys(limitations)),
        'incomplete': incomplete,
        'attention': (limitations + [
            f"Pending expense information: {', '.join(dict.fromkeys(pending))}."
        ])[0] if incomplete else '',
        'costProvenance': {
            'flight': (
                'not_required' if flight_state == 'not_required'
                else 'pending_unpriced' if flight_state == 'selected_unpriced'
                else 'simulated_estimate' if flight_state == 'simulated_estimate'
                else 'excluded_unknown_currency_or_basis' if flight_issue
                else 'confirmed_total' if flight else 'not_selected'
            ),
            'hotel': (
                'not_required' if hotel_state == 'not_required'
                else 'outside_scope' if hotel_state == 'excluded_outside_scope'
                else 'pending_unpriced' if hotel_state == 'selected_unpriced'
                else 'simulated_estimate' if hotel_state == 'simulated_estimate'
                else 'excluded_unknown_currency' if hotel_currency_issue
                else 'confirmed_total' if hotel_is_explicit
                else 'estimated_from_nightly_rate' if nightly_rate else 'not_selected'
            ),
            'carRental': (
                'not_required' if rental_state == 'not_required'
                else 'pending_unpriced' if rental_state == 'selected_unpriced'
                else 'simulated_local_catalogue' if rental_state == 'simulated_estimate'
                else 'confirmed' if car_rental else 'not_selected'
            ),
            'transport': 'provided' if data.get('transportCost') not in (None, '') else 'estimated_daily_allowance',
            'food': 'provided' if data.get('foodCost') not in (None, '') else 'estimated_daily_allowance',
            'activities': 'mixed_estimates',
        },
    }


def compareBudget(budgetEstimate):
    budget = budgetEstimate or {}
    if budget.get('status') == 'over_budget':
        return f"Over budget by RM {budget.get('overBy', 0):.2f}. Review the suggested alternatives."
    if budget.get('affordabilityStatus') == 'incomplete' or budget.get('incomplete'):
        return f"Known estimates total RM {budget.get('knownEstimatedSubtotal', budget.get('total', 0)):.2f}; affordability is incomplete until pending or excluded costs are resolved."
    if _float(budget.get('limit')) <= 0:
        return 'No budget limit has been set yet.'
    return f"Within budget with RM {budget.get('remaining', 0):.2f} remaining."


def buildLowerCostAlternatives(flightOptions=None, hotelOptions=None, budgetEstimate=None, itinerary=None):
    items = []
    current = itinerary or {}
    budget = budgetEstimate or calculateBudget(current)
    current_flight = _float(current.get('flightCost'))
    current_hotel = _float(current.get('hotelCost'))

    for flight in flightOptions or []:
        price = _float(flight.get('price'))
        savings = max(0.0, current_flight - price) if current_flight else 0.0
        items.append({
            'alternativeType': 'flight',
            'title': f"Lower-cost flight: {flight.get('airline', 'Flight')}",
            'description': f"{flight.get('departureTime', '')} → {flight.get('arrivalTime', '')} • RM {price:.2f}",
            'estimatedSavings': round(savings, 2),
            'data': flight,
        })

    for hotel in hotelOptions or []:
        price = _float(hotel.get('price'))
        savings = max(0.0, current_hotel - price) if current_hotel else 0.0
        items.append({
            'alternativeType': 'hotel',
            'title': f"Lower-cost hotel: {hotel.get('name', 'Hotel')}",
            'description': f"{hotel.get('roomName', 'Room')} • RM {price:.2f}",
            'estimatedSavings': round(savings, 2),
            'data': hotel,
        })

    # Always provide usable strategy alternatives, even without provider results.
    if _float(budget.get('overBy')) > 0 or not items:
        strategies = [
            ('transport', 'Use public transport / grouped rides', 'Replace repeated e-hailing trips with bus, rail or grouped transfers.', 45.0),
            ('activity', 'Replace one premium activity', 'Swap the most expensive paid attraction for a free heritage, beach or garden activity.', 60.0),
            ('food', 'Use a local-food budget', 'Plan one hawker/local meal for each day instead of restaurant-only dining.', 35.0),
            ('schedule', 'Group nearby activities', 'Reduce transport cost by visiting nearby attractions in the same time block.', 25.0),
        ]
        for kind, title, description, saving in strategies:
            items.append({
                'alternativeType': kind,
                'title': title,
                'description': description,
                'estimatedSavings': saving,
                'data': {'strategy': kind},
            })

    return sorted(items, key=lambda x: _float(x.get('estimatedSavings')), reverse=True)


def _trip_days(itinerary):
    start = _text(itinerary.get('startDate'))
    end = _text(itinerary.get('endDate'))
    try:
        if start and end:
            d1 = date.fromisoformat(start[:10])
            d2 = date.fromisoformat(end[:10])
            return max(1, (d2 - d1).days + 1)
    except ValueError:
        pass
    return max(1, min(14, int(_float(itinerary.get('tripDays'), 1))))


def _trip_start_date(itinerary):
    start = _text((itinerary or {}).get('startDate'))
    try:
        if start:
            return date.fromisoformat(start[:10])
    except ValueError:
        pass
    return date.today()


def _format_date(value):
    if not value:
        return ''
    return value.isoformat()


def _format_time(total_minutes):
    total_minutes = int(total_minutes) % (24 * 60)
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


PACE_WINDOWS = {
    'relaxed': (10 * 60, 20 * 60),
    'moderate': (9 * 60, 21 * 60),
    'active': (8 * 60, 21 * 60 + 30),
}

DURATION_DEFAULTS = {
    'food': 75, 'restaurant': 75, 'cafe': 75,
    'museum': 105, 'heritage': 105, 'culture': 105,
    'shopping': 120, 'market': 120, 'mall': 120,
    'nature': 135, 'beach': 135, 'park': 135, 'outdoor': 135,
    'theme park': 180, 'amusement': 180,
}


def _pace_key(itinerary):
    raw = _text(itinerary.get('pace') or itinerary.get('travelPace') or itinerary.get('preferredPace')).lower()
    if any(word in raw for word in ('relaxed', 'slow', 'leisure')):
        return 'relaxed'
    if any(word in raw for word in ('active', 'fast', 'packed', 'adventure')):
        return 'active'
    return 'moderate'


def _parse_time_minutes(value):
    import re
    text = _text(value).replace('.', ':').upper()
    match = re.search(r'\b(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?\b', text)
    if not match:
        return None
    try:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        suffix = match.group(3)
        if suffix:
            if not 1 <= hour <= 12:
                return None
            hour = (hour % 12) + (12 if suffix == 'PM' else 0)
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            return None
        return hour * 60 + minute
    except (TypeError, ValueError):
        return None


def _opening_window(opening_hours, day_date=None):
    import re
    value = opening_hours
    if isinstance(value, dict):
        key = day_date.strftime('%A').lower() if day_date else ''
        value = value.get(key) or value.get(key.title()) or value.get('default') or ''
    text = _text(value)
    if not text:
        return {'status': 'unknown', 'window': None, 'text': ''}
    lowered = text.lower()
    if re.search(r'\bclosed\b', lowered):
        return {'status': 'closed', 'window': None, 'text': text}
    if 'open all day' in lowered or '24 hour' in lowered or '24/7' in lowered:
        return {'status': 'open', 'window': (0, 24 * 60 - 1), 'text': text}
    match = re.search(
        r'(\d{1,2}(?::|\.)?\d{0,2}\s*(?:AM|PM)?)\s*(?:–|—|-)\s*'
        r'(\d{1,2}(?::|\.)?\d{0,2}\s*(?:AM|PM)?)',
        text, re.IGNORECASE,
    )
    if not match:
        return {'status': 'unknown', 'window': None, 'text': text}
    start = _parse_time_minutes(match.group(1))
    end = _parse_time_minutes(match.group(2))
    if start is None or end is None or end <= start:
        return {'status': 'unknown', 'window': None, 'text': text}
    return {'status': 'open', 'window': (start, end), 'text': text}


def _activity_duration(activity):
    provider = activity.get('providerDurationMinutes')
    source = _text(activity.get('durationSource')).lower()
    provided = activity.get('recommendedDurationMinutes')
    if provider not in (None, '') or (provided not in (None, '') and source in {'provider', 'confirmed'}):
        return int(max(30, min(480, _float(provider if provider not in (None, '') else provided, 105)))), 'provider'
    label = _text(activity.get('category') or activity.get('type') or activity.get('activityName')).lower()
    default = next((minutes for key, minutes in DURATION_DEFAULTS.items() if key in label), 105)
    if provided not in (None, ''):
        default = int(max(30, min(480, _float(provided, default))))
    return default, source if source in {'catalog_estimate', 'category_estimate'} else 'category_estimate'


def _coord(activity):
    gps = activity.get('gps_coordinates') or activity.get('gpsCoordinates') or {}
    try:
        return float(gps.get('latitude')), float(gps.get('longitude'))
    except (TypeError, ValueError, AttributeError):
        return None


def _distance_km(a, b):
    ca, cb = _coord(a), _coord(b)
    if not ca or not cb:
        return None
    lat1, lon1 = map(radians, ca)
    lat2, lon2 = map(radians, cb)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371.0 * 2 * atan2(sqrt(h), sqrt(max(0.0, 1 - h)))


def _travel_leg(previous, activity):
    if previous is None:
        return 0, 0.0, 'not_applicable'
    provider = activity.get('providerTravelDurationMinutes') or activity.get('travelDurationMinutes')
    if provider not in (None, '') and _text(activity.get('travelTimeSource')).lower() in {'provider', 'confirmed'}:
        return int(max(1, _float(provider))), _float(activity.get('travelDistanceKm')), 'provider'
    distance = _distance_km(previous, activity)
    if distance is None:
        return 25, None, 'estimated_default'
    # Explainable urban-road assumption: haversine distance x 1.25, 28 km/h, plus 8 minutes.
    road_distance = distance * 1.25
    minutes = int(max(8, round((road_distance / 28.0) * 60 + 8)))
    return minutes, round(distance, 2), 'estimated_haversine'


def _forecast_by_date(forecast_data):
    daily = (forecast_data or {}).get('daily', {}) if isinstance(forecast_data, dict) else {}
    dates = daily.get('time') or []
    probs = daily.get('precipitation_probability_max') or []
    codes = daily.get('weather_code') or []
    result = {}
    for index, value in enumerate(dates):
        key = _text(value)[:10]
        if not key:
            continue
        probability = _float(probs[index] if index < len(probs) else 0)
        code = int(_float(codes[index] if index < len(codes) else 0))
        result[key] = {
            'date': key,
            'precipitationProbability': probability,
            'weatherCode': code,
            'heavyRainLikely': probability >= 55 or code in range(51, 100),
            'source': 'forecast',
        }
    return result


def _indoor(activity):
    label = _text(activity.get('category') or activity.get('type')).lower()
    return bool(activity.get('indoor')) or any(x in label for x in ('indoor', 'museum', 'mall', 'gallery', 'food', 'restaurant'))


def _candidate_order(remaining, previous, weather, preserve_order):
    if preserve_order:
        return list(remaining)
    def key(item):
        opening = _opening_window(item.get('openingHours'))
        close_time = opening['window'][1] if opening.get('window') else 24 * 60
        rain_rank = 0 if weather.get('heavyRainLikely') and _indoor(item) else 1
        distance = _distance_km(previous, item) if previous else None
        return (rain_rank, close_time, distance if distance is not None else 99999)
    return sorted(remaining, key=key)


def _schedule_candidate(activity, previous, current_minutes, day_date, window_end):
    duration, duration_source = _activity_duration(activity)
    travel_minutes, distance, travel_source = _travel_leg(previous, activity)
    opening = _opening_window(activity.get('openingHours'), day_date)
    if opening['status'] == 'closed':
        return None, 'Attraction is closed on this trip day.'
    start = current_minutes + travel_minutes
    if opening.get('window'):
        start = max(start, opening['window'][0])
    # Reserve a simple lunch/rest block instead of scheduling continuously through midday.
    if start < 13 * 60 + 30 and start + duration > 12 * 60 + 30:
        start = 13 * 60 + 30
    end = start + duration
    if opening.get('window') and end > opening['window'][1]:
        return None, 'Could not fit within the attraction opening hours.'
    if end > window_end:
        return None, 'Could not fit within the daily planning window.'
    return ({
        **activity,
        'recommendedDurationMinutes': duration,
        'durationSource': duration_source,
        'durationEstimated': duration_source != 'provider',
        'travelBufferMinutes': travel_minutes,
        'travelDurationMinutes': travel_minutes,
        'travelDistanceKm': distance,
        'travelTimeSource': travel_source,
        'openingHoursStatus': opening['status'],
        '_startMinutes': start,
        '_endMinutes': end,
    }, None)


def _constraint_plan(itinerary, forecast_data=None, preserve_order=False, respect_day_assignments=False):
    itinerary = dict(itinerary or {})
    activities = [dict(x) for x in itinerary.get('activities', [])]
    for item in itinerary.get('unscheduledSuggestions', []) or []:
        candidate = dict(item)
        candidate.pop('unscheduledReason', None)
        if not any(str(x.get('activityId')) == str(candidate.get('activityId')) for x in activities):
            activities.append(candidate)
    for activity in activities:
        if activity.get('pricingUnit'):
            activity['effectiveCost'] = activity_pricing(
                activity, itinerary.get('travellerCount', 1))['effectiveCost']
    days = _trip_days(itinerary)
    start_date = _trip_start_date(itinerary)
    pace = _pace_key(itinerary)
    window_start, window_end = PACE_WINDOWS[pace]
    weather_by_date = _forecast_by_date(forecast_data or {})
    remaining = activities
    scheduled = []
    daily = []

    for day_index in range(days):
        day_no = day_index + 1
        day_date = start_date.fromordinal(start_date.toordinal() + day_index)
        date_key = _format_date(day_date)
        weather = weather_by_date.get(date_key, {
            'date': date_key,
            'source': 'unavailable',
            'message': 'Weather forecast unavailable for this date.',
            'heavyRainLikely': False,
        })
        current = window_start
        previous = None
        day_items = []
        while remaining:
            eligible = [x for x in remaining if not respect_day_assignments or int(_float(x.get('dayNo'), day_no)) == day_no]
            if not eligible:
                break
            chosen = None
            reason_by_id = {}
            for candidate in _candidate_order(eligible, previous, weather, preserve_order):
                planned, reason = _schedule_candidate(candidate, previous, current, day_date, window_end)
                if planned:
                    chosen = planned
                    break
                reason_by_id[str(candidate.get('activityId'))] = reason
            if chosen is None:
                break
            remaining.remove(next(x for x in remaining if str(x.get('activityId')) == str(chosen.get('activityId'))))
            chosen['dayNo'] = day_no
            chosen['dayDate'] = date_key
            chosen['dayLabel'] = f"Day {day_no} · {date_key}"
            chosen['sequenceNo'] = len(scheduled) + 1
            chosen['timeSlot'] = _format_time(chosen.pop('_startMinutes'))
            end_minutes = chosen.pop('_endMinutes')
            chosen['scheduledStartTime'] = chosen['timeSlot']
            chosen['scheduledEndTime'] = _format_time(end_minutes)
            chosen['timeRangeLabel'] = f"{chosen['scheduledStartTime']} - {chosen['scheduledEndTime']}"
            notes = []
            if previous and chosen.get('travelTimeSource') == 'estimated_haversine':
                notes.append('Grouped with a nearby attraction to reduce estimated travel time.')
            opening = _opening_window(chosen.get('openingHours'), day_date)
            if opening.get('window') and opening['window'][1] <= 18 * 60:
                notes.append(f"Scheduled before closing at {_format_time(opening['window'][1])}.")
            if weather.get('heavyRainLikely'):
                if _indoor(chosen):
                    notes.append('Indoor activity prioritised because heavy rain is forecast for this date.')
                else:
                    notes.append('Rain is forecast; keep an indoor alternative available.')
            chosen['weather'] = weather
            chosen['weatherNote'] = notes[-1] if notes and 'rain' in notes[-1].lower() else ''
            chosen['scheduleNotes'] = notes[:3]
            day_items.append(chosen)
            scheduled.append(chosen)
            current = end_minutes
            previous = chosen

        meal_blocks = []
        if day_items:
            meal_blocks.append({
                'type': 'meal_rest', 'label': 'Lunch and rest',
                'startTime': '12:30', 'endTime': '13:30',
                'durationMinutes': 60, 'estimated': True,
            })
        daily.append({
            'dayNo': day_no,
            'dayDate': date_key,
            'dayLabel': f"Day {day_no} · {date_key}",
            'planningWindow': {'startTime': _format_time(window_start), 'endTime': _format_time(window_end), 'pace': pace},
            'activities': day_items,
            'planningBlocks': meal_blocks,
            'weather': weather,
            'estimatedMinutes': sum(int(_float(x.get('recommendedDurationMinutes'))) + int(_float(x.get('travelDurationMinutes'))) for x in day_items),
            'estimatedCost': round(sum(activity_pricing(
                x, itinerary.get('travellerCount', 1))['effectiveCost'] for x in day_items), 2),
        })

    unscheduled = []
    for item in remaining:
        all_closed = all(_opening_window(item.get('openingHours'), start_date.fromordinal(start_date.toordinal() + index))['status'] == 'closed' for index in range(days))
        unscheduled.append({
            **item,
            'unscheduledReason': 'Attraction is closed on all trip days.' if all_closed else 'Could not fit within available time, travel, and opening-hour constraints.',
        })
    itinerary.update({
        'activities': scheduled,
        'unscheduledSuggestions': unscheduled,
        'scheduledActivityCount': len(scheduled),
        'unscheduledActivityCount': len(unscheduled),
        'tripDays': days,
        'paceApplied': pace,
        'dailyPlanningWindow': {'startTime': _format_time(window_start), 'endTime': _format_time(window_end)},
        'tripDateRangeLabel': f"{_format_date(start_date)} to {_format_date(start_date.fromordinal(start_date.toordinal() + days - 1))}",
        'dailySchedule': daily,
        'totalScheduledMinutes': sum(day['estimatedMinutes'] for day in daily),
        'updatedAt': utc_now_iso(),
    })
    return itinerary


def generateItinerary(locationTravelData, forecastData, itineraryInput=None):
    """Generate an explainable, constraint-aware heuristic itinerary."""
    base = dict(itineraryInput or {})
    activities = [dict(x) for x in base.get('activities', [])]
    days = _trip_days(base)

    for index, activity in enumerate(activities):
        activity.setdefault('estimatedCost', _float(activity.get('estimatedCost')))

    itinerary = {
        **base,
        'activities': activities,
        'tripDays': days,
        'generationContext': {
            'locationTravelData': locationTravelData or [],
            'forecastData': forecastData or {},
            'destinationPlanning': True,
            'activityArrangement': True,
            'tripDayGeneration': True,
            'weatherConsideration': bool(forecastData),
        },
        'status': 'generated',
        'updatedAt': utc_now_iso(),
    }
    itinerary['generationContext']['planner'] = 'constraint_aware_heuristic'
    return _constraint_plan(itinerary, forecastData, preserve_order=False, respect_day_assignments=False)


def recalculateItinerary(itinerary, preserveOrder=True, respectDayAssignments=True):
    context = (itinerary or {}).get('generationContext') or {}
    return _constraint_plan(
        itinerary,
        context.get('forecastData') or {},
        preserve_order=preserveOrder,
        respect_day_assignments=respectDayAssignments,
    )


def groupNearbyActivities(itinerary):
    """Compatibility wrapper; the authoritative planner already groups nearby activities."""
    return recalculateItinerary(itinerary, preserveOrder=False, respectDayAssignments=True)


def checkOpeningHoursAndTravelTime(itinerary):
    return recalculateItinerary(itinerary, preserveOrder=True, respectDayAssignments=True)


def adjustWeatherSensitiveActivities(itinerary):
    return recalculateItinerary(itinerary, preserveOrder=False, respectDayAssignments=True)


# ---------------------------------------------------------------------------
# Flight / hotel helper functions retained for sequence traceability.
# ---------------------------------------------------------------------------

def applyFlightFilter(items, filters=None):
    filters = filters or {}
    output = list(items or [])
    if str(filters.get('nonstop', '')).lower() in {'1', 'true', 'yes'}:
        output = [x for x in output if int(_float(x.get('stops'))) == 0]
    sort = filters.get('sort') or filters.get('sort_by')
    if sort in {'price', 'price_low', 'lowest'}:
        output.sort(key=lambda x: _float(x.get('price'), 999999))
    elif sort in {'duration', 'shortest'}:
        output.sort(key=lambda x: _float(x.get('durationMinutes'), 999999))
    return output


def compareSelectedFlights(items):
    output = list(items or [])
    return sorted(output, key=lambda x: (_float(x.get('price'), 999999), _float(x.get('durationMinutes'), 999999)))


def applyHotelFilter(items, filters=None):
    filters = filters or {}
    output = list(items or [])
    if str(filters.get('refundable', '')).lower() in {'1', 'true', 'yes'}:
        output = [x for x in output if bool(x.get('refundable'))]
    sort = filters.get('sort')
    if sort in {'price', 'price_low'}:
        output.sort(key=lambda x: _float(x.get('price'), 999999))
    elif sort == 'rating':
        output.sort(key=lambda x: _float(x.get('rating')), reverse=True)
    return output


def compareSelectedHotels(items):
    return sorted(list(items or []), key=lambda x: (_float(x.get('price'), 999999), -_float(x.get('rating'))))


# ---------------------------------------------------------------------------
# Existing FR12 / FR13 domain functions retained.
# ---------------------------------------------------------------------------

def createPackage(data, operatorId):
    from services.package_service import normalise_package
    return {**normalise_package(data), 'operatorId': operatorId, 'approvalStatus': 'draft', 'createdAt': utc_now_iso(), 'updatedAt': utc_now_iso()}


def submitForApproval(packageData):
    return {**packageData, 'approvalStatus': 'pending', 'submittedAt': utc_now_iso(), 'updatedAt': utc_now_iso(), 'reviewComment': ''}


def createCampaign(data, operatorId):
    return {**data, 'operatorId': operatorId, 'campaignStatus': 'draft', 'reviewStatus': 'draft', 'createdAt': utc_now_iso(), 'updatedAt': utc_now_iso()}


def calculatePackageViews(packages):
    return sum(int(p.get('viewCount', 0) or 0) for p in packages or [])


def calculateBookingCount(bookings):
    return len(bookings or [])


def calculateCampaignEngagement(campaigns):
    if not campaigns:
        return 0.0
    vals = [_float(c.get('engagementRate')) for c in campaigns]
    return round(sum(vals) / len(vals), 2)


def approve(record, comment=''):
    return {'decision': 'approved', 'reviewComment': comment, 'reviewedAt': utc_now_iso()}


def reject(record, comment=''):
    return {'decision': 'rejected', 'reviewComment': comment, 'reviewedAt': utc_now_iso()}


def generateReport(reportData):
    return {'generatedAt': utc_now_iso(), 'data': reportData}


def exportReport(report, exportFormat='csv'):
    return {'format': exportFormat, 'report': report}
