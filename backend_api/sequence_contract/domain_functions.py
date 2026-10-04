from datetime import datetime, date
from math import radians, sin, cos, sqrt, atan2
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
    interest_groups = [concepts_for(value) for value in raw_interests]
    interest_groups = [group for group in interest_groups if group]
    interest_concepts = set().union(*interest_groups) if interest_groups else set()
    travel_type_concepts = concepts_for(pref.get('travelType'))
    requested_budget = normalize_budget(pref.get('budgetRange'))
    requested_pace = normalize_pace(pref.get('travelPace'))
    requested_purpose = normalize_purpose(pref.get('travelPurpose'))
    requested_personality = normalize_personality(pref.get('travelPersonality'))

    results = []
    for item in recommendationInput.get('destinationData', []) or []:
        destination_concepts = candidate_concepts(item)
        matched_concepts = interest_concepts.intersection(destination_concepts)
        if interest_groups:
            matched_group_count = sum(
                1 for group in interest_groups
                if group.intersection(destination_concepts)
            )
            interest_coverage = matched_group_count / len(interest_groups)
            primary_concepts = concepts_for([
                item.get('title'), item.get('name'), item.get('type')
            ])
            primary_match = bool(
                primary_concepts.intersection(interest_concepts))
            interest_score = interest_coverage * (
                1.0 if primary_match else 0.80)
        else:
            interest_score = 0.55
            primary_match = False
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
            'contentScore': round(min(100.0, content_score), 2),
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


def calculateBudget(itineraryOrSelections):
    data = itineraryOrSelections or {}
    limit = _float(data.get('budgetLimit'))
    travellers = max(1, int(_float(data.get('travellerCount'), 1)))
    flight = _float(data.get('flightCost'))
    hotel = _float(data.get('hotelCost'))
    car_rental = _float(data.get('carRentalCost'))
    try:
        days = _trip_days(data)
    except Exception:
        days = 1
    transport = _float(data.get('transportCost')) if data.get('transportCost') not in (None, '') else round(35.0 * days, 2)
    food = _float(data.get('foodCost')) if data.get('foodCost') not in (None, '') else round(60.0 * travellers * days, 2)
    activities = sum(_float(x.get('estimatedCost')) for x in data.get('activities', []))
    total = flight + hotel + car_rental + transport + food + activities
    difference = limit - total if limit else 0.0
    status = 'within_budget' if not limit or total <= limit else 'over_budget'
    utilization = round((total / limit) * 100.0, 2) if limit > 0 else 0.0

    return {
        'limit': round(limit, 2),
        'travellers': travellers,
        'flight': round(flight, 2),
        'hotel': round(hotel, 2),
        'carRental': round(car_rental, 2),
        'transport': round(transport, 2),
        'food': round(food, 2),
        'activities': round(activities, 2),
        'total': round(total, 2),
        'difference': round(difference, 2),
        'remaining': round(max(0.0, difference), 2) if limit else 0.0,
        'overBy': round(max(0.0, -difference), 2) if limit else 0.0,
        'utilizationPercent': utilization,
        'status': status,
    }


def compareBudget(budgetEstimate):
    budget = budgetEstimate or {}
    if budget.get('status') == 'over_budget':
        return f"Over budget by RM {budget.get('overBy', 0):.2f}. Review the suggested alternatives."
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
    return max(1, min(5, int(_float(itinerary.get('tripDays'), 1))))


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


def _parse_time_minutes(value):
    text = _text(value).replace('.', ':')
    try:
        parts = text.split(':')
        if len(parts) >= 2:
            hour = int(parts[0])
            minute = int(parts[1][:2])
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return hour * 60 + minute
    except (TypeError, ValueError):
        return None
    return None


def _opening_window(opening_hours):
    text = _text(opening_hours)
    if not text:
        return None
    lowered = text.lower()
    if 'open all day' in lowered or '24 hour' in lowered:
        return (0, 24 * 60 - 1)
    import re
    match = re.search(r'(\d{1,2}[:.]\d{2})\s*[–-]\s*(\d{1,2}[:.]\d{2})', text)
    if not match:
        return None
    start = _parse_time_minutes(match.group(1))
    end = _parse_time_minutes(match.group(2))
    if start is None or end is None:
        return None
    return (start, end)


def _schedule_activity(activity, day_date, day_index, slot_index, sequence_no, first_in_day=False):
    activity = dict(activity or {})
    duration = int(max(45, min(360, _float(activity.get('recommendedDurationMinutes'), 105))))
    start_minutes = 9 * 60 if first_in_day else None
    if start_minutes is None:
        start_minutes = _parse_time_minutes(activity.get('timeSlot')) or (9 * 60 + slot_index * 240)
    buffer_minutes = 0 if first_in_day else int(max(20, _float(activity.get('travelBufferMinutes'), 30)))
    start_minutes += 0 if first_in_day else buffer_minutes
    end_minutes = start_minutes + duration
    notes = [str(x) for x in activity.get('scheduleNotes', []) if str(x).strip()] if isinstance(activity.get('scheduleNotes'), list) else []

    opening = _opening_window(activity.get('openingHours'))
    if opening:
        open_start, open_end = opening
        if start_minutes < open_start or end_minutes > open_end:
            notes.append(f"Check opening hours before visiting: {_text(activity.get('openingHours'))}.")
    elif _text(activity.get('openingHours')):
        notes.append(f"Opening info: {_text(activity.get('openingHours'))}.")

    activity.update({
        'dayNo': day_index + 1,
        'dayDate': _format_date(day_date),
        'dayLabel': f"Day {day_index + 1} · {_format_date(day_date)}",
        'sequenceNo': sequence_no,
        'timeSlot': _format_time(start_minutes),
        'scheduledStartTime': _format_time(start_minutes),
        'scheduledEndTime': _format_time(end_minutes),
        'timeRangeLabel': f"{_format_time(start_minutes)} - {_format_time(end_minutes)}",
        'travelBufferMinutes': buffer_minutes,
        'recommendedDurationMinutes': duration,
        'scheduleNotes': notes[:3],
    })
    return activity, end_minutes


def _build_daily_schedule(activities):
    days = {}
    for activity in activities or []:
        day_no = int(_float(activity.get('dayNo'), 1))
        days.setdefault(day_no, {
            'dayNo': day_no,
            'dayDate': activity.get('dayDate', ''),
            'dayLabel': activity.get('dayLabel') or f"Day {day_no}",
            'activities': [],
            'estimatedMinutes': 0,
            'estimatedCost': 0.0,
        })
        days[day_no]['activities'].append(activity)
        days[day_no]['estimatedMinutes'] += int(_float(activity.get('recommendedDurationMinutes')) + _float(activity.get('travelBufferMinutes')))
        days[day_no]['estimatedCost'] += _float(activity.get('estimatedCost'))
    return [
        {**day, 'estimatedCost': round(day['estimatedCost'], 2)}
        for _, day in sorted(days.items())
    ]


def _apply_schedule_metadata(itinerary):
    itinerary = dict(itinerary or {})
    activities = [dict(x) for x in itinerary.get('activities', [])]
    days = max(1, _trip_days(itinerary))
    start_date = _trip_start_date(itinerary)
    per_day = {}
    scheduled = []
    sequence = 1

    for index, activity in enumerate(activities):
        day_index = min(days - 1, index // 3)
        per_day.setdefault(day_index, 9 * 60)
        is_first = len([x for x in scheduled if int(_float(x.get('dayNo'), 1)) == day_index + 1]) == 0
        if not is_first:
            activity['timeSlot'] = _format_time(per_day[day_index])
        day_date = start_date.fromordinal(start_date.toordinal() + day_index)
        item, end_minutes = _schedule_activity(activity, day_date, day_index, index % 3, sequence, first_in_day=is_first)
        per_day[day_index] = end_minutes
        scheduled.append(item)
        sequence += 1

    itinerary['activities'] = scheduled
    itinerary['tripDays'] = days
    itinerary['tripDateRangeLabel'] = f"{_format_date(start_date)} to {_format_date(start_date.fromordinal(start_date.toordinal() + days - 1))}"
    itinerary['dailySchedule'] = _build_daily_schedule(scheduled)
    itinerary['totalScheduledMinutes'] = sum(day.get('estimatedMinutes', 0) for day in itinerary['dailySchedule'])
    return itinerary


def generateItinerary(locationTravelData, forecastData, itineraryInput=None):
    """Destination planning + trip-day generation + initial activity arrangement."""
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
    return _apply_schedule_metadata(itinerary)


def _coord(activity):
    gps = activity.get('gps_coordinates') or activity.get('gpsCoordinates') or {}
    try:
        return float(gps.get('latitude')), float(gps.get('longitude'))
    except (TypeError, ValueError, AttributeError):
        return None


def _distance_km(a, b):
    ca, cb = _coord(a), _coord(b)
    if not ca or not cb:
        return 999.0
    lat1, lon1 = map(radians, ca)
    lat2, lon2 = map(radians, cb)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371.0 * 2 * atan2(sqrt(h), sqrt(1 - h))


def groupNearbyActivities(itinerary):
    """Greedy nearest-neighbour ordering within each day."""
    itinerary = dict(itinerary or {})
    activities = [dict(x) for x in itinerary.get('activities', [])]
    grouped = []
    for day_no in sorted({int(_float(x.get('dayNo'), 1)) for x in activities} or {1}):
        remaining = [x for x in activities if int(_float(x.get('dayNo'), 1)) == day_no]
        if not remaining:
            continue
        ordered = [remaining.pop(0)]
        while remaining:
            current = ordered[-1]
            idx = min(range(len(remaining)), key=lambda i: _distance_km(current, remaining[i]))
            ordered.append(remaining.pop(idx))
        grouped.extend(ordered)
    for index, activity in enumerate(grouped):
        activity['sequenceNo'] = index + 1
    itinerary['activities'] = grouped
    itinerary['generationContext'] = {**itinerary.get('generationContext', {}), 'nearbyGroupingApplied': True}
    return _apply_schedule_metadata(itinerary)


def checkOpeningHoursAndTravelTime(itinerary):
    itinerary = dict(itinerary or {})
    activities = [dict(x) for x in itinerary.get('activities', [])]
    for idx, activity in enumerate(activities):
        same_day_previous = idx > 0 and activity.get('dayNo') == activities[idx - 1].get('dayNo')
        activity['travelBufferMinutes'] = 0 if not same_day_previous else int(_float(activity.get('travelBufferMinutes'), 30))
        activity['openingHoursChecked'] = bool(activity.get('openingHours'))
        activity['recommendedDurationMinutes'] = int(_float(activity.get('recommendedDurationMinutes'), 105))
    itinerary['activities'] = activities
    itinerary['generationContext'] = {**itinerary.get('generationContext', {}), 'openingHoursAndTravelTimeChecked': True}
    return _apply_schedule_metadata(itinerary)


def _rainy_days(forecast_data):
    daily = (forecast_data or {}).get('daily', {}) if isinstance(forecast_data, dict) else {}
    dates = daily.get('time') or []
    probs = daily.get('precipitation_probability_max') or []
    codes = daily.get('weather_code') or []
    rainy = set()
    for index, day in enumerate(dates):
        prob = _float(probs[index] if index < len(probs) else 0)
        code = int(_float(codes[index] if index < len(codes) else 0))
        if prob >= 55 or code >= 51:
            rainy.add(index + 1)
    return rainy


def adjustWeatherSensitiveActivities(itinerary):
    itinerary = dict(itinerary or {})
    forecast = (itinerary.get('generationContext') or {}).get('forecastData') or {}
    rainy_days = _rainy_days(forecast)
    activities = [dict(x) for x in itinerary.get('activities', [])]

    for activity in activities:
        day_no = int(_float(activity.get('dayNo'), 1))
        indoor = bool(activity.get('indoor')) or 'indoor' in _text(activity.get('type')).lower() or 'museum' in _text(activity.get('type')).lower() or 'mall' in _text(activity.get('type')).lower()
        activity['weatherSensitive'] = not indoor
        if day_no in rainy_days:
            if indoor:
                activity['weatherNote'] = 'Prioritised because rain is likely.'
                activity['_weatherPriority'] = 0
            else:
                activity['weatherNote'] = 'Rain is likely; keep a flexible indoor backup.'
                activity['_weatherPriority'] = 1
        else:
            activity['weatherNote'] = 'No major weather rearrangement required.'
            activity['_weatherPriority'] = 0

    activities.sort(key=lambda x: (int(_float(x.get('dayNo'), 1)), int(x.get('_weatherPriority', 0)), int(_float(x.get('sequenceNo'), 999))))
    for index, activity in enumerate(activities):
        activity.pop('_weatherPriority', None)
        activity['sequenceNo'] = index + 1

    itinerary['activities'] = activities
    itinerary['generationContext'] = {
        **itinerary.get('generationContext', {}),
        'weatherConsideration': bool(forecast),
        'rainyDayNumbers': sorted(rainy_days),
    }
    return _apply_schedule_metadata(itinerary)


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
    return {**data, 'operatorId': operatorId, 'approvalStatus': 'draft', 'availabilityStatus': data.get('availabilityStatus', 'available'), 'createdAt': utc_now_iso(), 'updatedAt': utc_now_iso()}


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
