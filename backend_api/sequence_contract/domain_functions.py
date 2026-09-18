from datetime import datetime, date
from math import radians, sin, cos, sqrt, atan2
from utils import utc_now_iso


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

    The logic is intentionally simple and explainable for an FYP viva. Interests carry
    the largest contribution, followed by travel type/purpose/personality/pace and the
    provider rating as a small quality signal.
    """
    pref = recommendationInput.get('preferenceProfile', {}) or {}
    interests = {_text(x).lower() for x in pref.get('interests', []) if _text(x)}
    profile_tokens = _tokens(
        pref.get('travelType'),
        pref.get('travelPurpose'),
        pref.get('travelPersonality'),
        pref.get('travelPace'),
        pref.get('budgetRange'),
    )

    results = []
    for item in recommendationInput.get('destinationData', []) or []:
        destination_tokens = _tokens(
            item.get('title'), item.get('name'), item.get('category'), item.get('type'),
            item.get('description'), item.get('address')
        )
        matched_interests = sorted(i for i in interests if i in destination_tokens)
        matched_profile = sorted(profile_tokens.intersection(destination_tokens))

        interest_ratio = len(matched_interests) / max(1, len(interests)) if interests else 0.35
        profile_ratio = min(1.0, len(matched_profile) / max(1, len(profile_tokens))) if profile_tokens else 0.35
        rating = min(5.0, max(0.0, _float(item.get('rating'))))
        rating_ratio = rating / 5.0

        # 65% actual profile match, 20% broader travel-style match, 15% quality signal.
        content_score = (interest_ratio * 65.0) + (profile_ratio * 20.0) + (rating_ratio * 15.0)
        if not matched_interests and interests:
            # Keep candidates visible but clearly behind strong matches.
            content_score *= 0.72

        results.append({
            **item,
            'destinationId': _destination_id(item),
            'contentScore': round(min(100.0, content_score), 2),
            'matchedInterests': matched_interests,
            'matchedProfileTerms': matched_profile,
        })
    return results


def applyCollaborativeFiltering(items, collaborativeData=None, peerPreferences=None, currentPreference=None):
    """Compute an explainable collaborative score (0-100).

    Feedback from other travellers is used directly. If peer preference profiles are
    available, their interest/type/pace similarity weights their destination ratings.
    Sparse-data fallback uses provider rating so a new FYP database still works.
    """
    peer_preferences = peerPreferences or {}
    current = currentPreference or {}
    current_interests = {_text(x).lower() for x in current.get('interests', []) if _text(x)}

    ratings = {}
    for row in collaborativeData or []:
        did = str(row.get('destinationId') or '')
        if not did:
            continue
        uid = str(row.get('travellerId') or '')
        rating = max(0.0, min(5.0, _float(row.get('rating'))))
        similarity = 1.0
        peer = peer_preferences.get(uid) if isinstance(peer_preferences, dict) else None
        if peer and current:
            peer_interests = {_text(x).lower() for x in peer.get('interests', []) if _text(x)}
            union = current_interests.union(peer_interests)
            jaccard = len(current_interests.intersection(peer_interests)) / max(1, len(union))
            type_match = 1.0 if _text(peer.get('travelType')).lower() == _text(current.get('travelType')).lower() and _text(current.get('travelType')) else 0.0
            pace_match = 1.0 if _text(peer.get('travelPace')).lower() == _text(current.get('travelPace')).lower() and _text(current.get('travelPace')) else 0.0
            purpose_match = 1.0 if _text(peer.get('travelPurpose')).lower() == _text(current.get('travelPurpose')).lower() and _text(current.get('travelPurpose')) else 0.0
            similarity = max(0.15, 0.55 * jaccard + 0.20 * type_match + 0.15 * pace_match + 0.10 * purpose_match)
        ratings.setdefault(did, []).append((rating, similarity))

    output = []
    for item in items or []:
        did = _destination_id(item)
        values = ratings.get(did, [])
        if values:
            weighted_sum = sum(r * w for r, w in values)
            total_weight = sum(w for _, w in values) or 1.0
            avg_rating = weighted_sum / total_weight
            collaborative_score = (avg_rating / 5.0) * 100.0
            collaborative_source = f'{len(values)} traveller rating(s)'
        else:
            collaborative_score = min(100.0, (_float(item.get('rating'), 3.5) / 5.0) * 100.0)
            collaborative_source = 'provider-rating fallback (cold start)'

        output.append({
            **item,
            'collaborativeScore': round(collaborative_score, 2),
            'collaborativeSource': collaborative_source,
        })
    return output


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

        matches = item.get('matchedInterests', []) or []
        reason = f"Matches {', '.join(matches[:3])}" if matches else 'Strong overall travel relevance'
        reason += f" • rating {item.get('rating', '-')}"

        output.append({
            **item,
            'popularityScore': round(popularity, 2),
            'score': round(score, 2),
            'scoreBreakdown': {
                'contentWeight': 0.60,
                'collaborativeWeight': 0.30,
                'popularityWeight': 0.10,
                'content': round(content, 2),
                'collaborative': round(collaborative, 2),
                'popularity': round(popularity, 2),
            },
            'reason': reason,
        })
    return output


def rankRecommendations(items):
    ranked = sorted(
        items or [],
        key=lambda x: (_float(x.get('score')), _float(x.get('rating')), _float(x.get('reviews'))),
        reverse=True,
    )
    return [{**item, 'rankNo': index + 1} for index, item in enumerate(ranked)]


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
