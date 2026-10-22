import re
import unicodedata
from datetime import date, timedelta
from services.malaysian_locality import (
    STATE_ALIASES,
    LOCALITIES,
    FOREIGN_DESTINATIONS,
    normalize_destination_scope,
    normalize_candidate_geography,
)
from services.local_catalog import DESTINATIONS

NUMBER_WORDS = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10
}

MONTH_NAMES = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
}


def clean_text(text):
    v = unicodedata.normalize('NFKD', str(text or ''))
    v = ''.join(c for c in v if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', ' ', v.lower()).strip()


def extract_geographic_entities(text):
    """Accurately identify destination, origin, multi-destination and country boundary."""
    t_clean = clean_text(text)

    # 1. Check for origin/destination pattern "from X to Y"
    from_to = re.search(r'\bfrom\s+([a-z\s]+?)\s+to\s+([a-z\s]+?)(?:\s+(?:for|in|starting|under|with|next|this|on|\d)|$)', t_clean)
    foreign_origin = None
    origin_part = None
    dest_part = None

    if from_to:
        origin_candidate = from_to.group(1).strip()
        dest_part = from_to.group(2).strip()
        origin_part = origin_candidate
        for f_alias, f_canon in FOREIGN_DESTINATIONS.items():
            if re.search(rf'\b{re.escape(f_alias)}\b', origin_candidate):
                foreign_origin = f_canon
                break

    # Determine text to scan for destination
    text_to_scan = t_clean
    if origin_part and foreign_origin:
        text_to_scan = re.sub(rf'\bfrom\s+{re.escape(origin_part)}\b', '', t_clean)

    # Detect foreign destinations in destination part/text
    foreign_dests = []
    for f_alias, f_canon in FOREIGN_DESTINATIONS.items():
        if re.search(rf'\b{re.escape(f_alias)}\b', text_to_scan):
            foreign_dests.append(f_canon)

    # Detect Malaysian localities
    malaysian_locs = []
    for loc_name, (state, aliases) in LOCALITIES.items():
        for alias in aliases:
            if re.search(rf'\b{re.escape(alias)}\b', text_to_scan):
                malaysian_locs.append((loc_name, state))
                break

    # Detect Malaysian states
    malaysian_states = []
    for state_name, aliases in STATE_ALIASES.items():
        for alias in aliases:
            if re.search(rf'\b{re.escape(alias)}\b', text_to_scan):
                malaysian_states.append(state_name)
                break

    # Detect multi-destination Malaysian road trips
    all_malaysian = []
    for loc, st in malaysian_locs:
        if loc not in all_malaysian:
            all_malaysian.append(loc)
    for st in malaysian_states:
        if st not in all_malaysian and not any(l_st == st for _, l_st in malaysian_locs):
            all_malaysian.append(st)

    # Also check if origin was a Malaysian city in a domestic road trip: e.g. "from Kuala Lumpur to Ipoh and Penang"
    if from_to and not foreign_origin:
        origin_clean = clean_text(from_to.group(1))
        for loc_name, (state, aliases) in LOCALITIES.items():
            for alias in aliases:
                if re.search(rf'\b{re.escape(alias)}\b', origin_clean) and loc_name not in all_malaysian:
                    all_malaysian.insert(0, loc_name)
                    break

    is_multi = len(all_malaysian) > 1

    # Foreign destination check: true only if foreign destination found without valid Malaysian sightseeing destination
    is_foreign = bool(foreign_dests and not malaysian_locs and not malaysian_states)
    unsupported_foreign = foreign_dests[0] if is_foreign else None

    primary_area = None
    primary_state = None
    if malaysian_locs:
        primary_area = malaysian_locs[0][0]
        primary_state = malaysian_locs[0][1]
    elif malaysian_states:
        primary_area = malaysian_states[0]
        primary_state = malaysian_states[0]

    return {
        'foreign_origin': foreign_origin,
        'is_foreign': is_foreign,
        'unsupported_foreign': unsupported_foreign,
        'is_multi_destination': is_multi,
        'multiple_destinations': all_malaysian if is_multi else [],
        'destination_area': primary_area,
        'destination_state': primary_state,
        'destination_country': 'Malaysia' if (primary_area or primary_state) else None,
    }


def extract_duration(text, default=None):
    q = text.lower()
    m = re.search(r'\b(\d+)\s*(?:-| )?\s*days?\b', q)
    if m:
        return max(1, min(14, int(m.group(1))))
    for word, num in NUMBER_WORDS.items():
        if re.search(rf'\b{word}\s*(?:-| )?\s*days?\b', q):
            return num
    m_dn = re.search(r'\b(\d+)\s*d\s*(\d+)\s*n\b', q)
    if m_dn:
        return max(1, min(14, int(m_dn.group(1))))
    m_dn2 = re.search(r'\b(\d+)\s*days?\s*(?:and|&)?\s*\d+\s*nights?\b', q)
    if m_dn2:
        return max(1, min(14, int(m_dn2.group(1))))
    if 'weekend' in q:
        return 2
    if 'one week' in q or 'a week' in q:
        return 7
    return default


def extract_budget(text, default=None):
    q = text.lower()
    m = re.search(r'\b(?:rm|\$)\s*([\d,]+(?:\.\d{1,2})?)\b', q)
    if m:
        try:
            return float(m.group(1).replace(',', ''))
        except Exception:
            pass
    m_cur = re.search(r'\b([\d,]+(?:\.\d{1,2})?)\s*(?:ringgit|myr)\b', q)
    if m_cur:
        try:
            return float(m_cur.group(1).replace(',', ''))
        except Exception:
            pass
    m_b = re.search(r'\bbudget\s*(?:of|is|limit|to|:)?\s*(?:rm)?\s*([\d,]+(?:\.\d{1,2})?)\b', q)
    if m_b:
        try:
            return float(m_b.group(1).replace(',', ''))
        except Exception:
            pass
    return default


def extract_travellers(text, default=None):
    q = text.lower()
    if any(k in q for k in ['solo', 'by myself', 'alone', 'for 1 person', 'for one person']):
        return 1
    if any(k in q for k in ['couple', 'two people', 'for 2 people', 'for two', 'for 2', 'two of us', '2 travellers', '2 pax']):
        return 2
    if 'family of four' in q or 'four travellers' in q or '4 pax' in q or '4 people' in q:
        return 4
    if 'three travellers' in q or '3 pax' in q or '3 people' in q or 'three of us' in q:
        return 3
    m = re.search(r'\b(\d+)\s*(?:people|pax|travellers|persons|adults)\b', q)
    if m:
        return max(1, min(20, int(m.group(1))))
    return default


def extract_dates(text, duration_days=3, default_start=None, default_end=None):
    q = text.lower()
    today = date.today()

    if 'starting tomorrow' in q or 'starts tomorrow' in q:
        start = today + timedelta(days=1)
        end = start + timedelta(days=duration_days - 1)
        return start.isoformat(), end.isoformat()
    if 'next saturday' in q:
        days_ahead = (5 - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        start = today + timedelta(days=days_ahead)
        end = start + timedelta(days=duration_days - 1)
        return start.isoformat(), end.isoformat()

    m_exp = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\s+(\d{4})\b', q)
    if m_exp:
        day_num = int(m_exp.group(1))
        m_str = m_exp.group(2)
        year_num = int(m_exp.group(3))
        if m_str in MONTH_NAMES:
            month_num = MONTH_NAMES[m_str]
            try:
                start = date(year_num, month_num, day_num)
                end = start + timedelta(days=duration_days - 1)
                return start.isoformat(), end.isoformat()
            except Exception:
                pass

    m_slash = re.search(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b', q)
    if m_slash:
        d_val, m_val, y_val = int(m_slash.group(1)), int(m_slash.group(2)), int(m_slash.group(3))
        try:
            start = date(y_val, m_val, d_val)
            end = start + timedelta(days=duration_days - 1)
            return start.isoformat(), end.isoformat()
        except Exception:
            pass

    return default_start, default_end


def extract_interests(text, existing=None):
    q = text.lower()
    interests = list(existing or [])
    mapping = {
        'Food': ['food', 'culinary', 'eat', 'hawker', 'dining', 'cuisine'],
        'Culture': ['culture', 'heritage', 'history', 'historical', 'museum', 'temple', 'colonial'],
        'Nature': ['nature', 'adventure', 'hiking', 'mountain', 'wildlife', 'jungle', 'park'],
        'Beach': ['beach', 'island', 'coastal', 'snorkeling', 'sea', 'diving'],
        'Relaxation': ['relax', 'relaxing', 'relaxation', 'chill', 'peaceful', 'spa', 'calm'],
        'Shopping': ['shopping', 'mall', 'market', 'bazaar'],
        'Family': ['family', 'kids', 'children'],
        'Photography': ['photo', 'photography', 'viewpoint'],
    }
    for cat, keywords in mapping.items():
        if any(k in q for k in keywords) and cat not in interests:
            interests.append(cat)
    return interests


def extract_day_specific(text):
    q = text.lower()
    m = re.search(r'\bday\s*(\d+)\s*(?:more|less|to\s+be)?\s*([a-z\s]+?)(?:\.|$|,)', q)
    if m:
        try:
            day_no = int(m.group(1))
            pref = m.group(2).strip()
            return {day_no: pref}
        except Exception:
            pass
    return {}


def classify_user_intent(text, planning_state=None):
    q = text.lower()
    planning_triggers = ['plan', 'itinerary', 'trip', 'schedule', 'arrange', 'holiday', 'vacation']
    info_triggers = ['recommend', 'food', 'eat', 'restaurant', 'attraction', 'weather', 'rain', 'flight', 'hotel', 'where should', 'what are the best', 'how to']

    # Explicit itinerary request
    is_planning = any(p in q for p in ['plan a', 'plan my', 'create an itinerary', 'build an itinerary', 'trip to', 'holiday in', 'vacation in', 'days in', '-day']) or (any(t in q for t in ['plan', 'itinerary']) and any(d in q for d in ['day', 'trip', 'weekend', 'week', 'holiday', 'vacation']))
    is_exploration = any(e in q for e in ['somewhere relaxing', 'where should i go', 'recommend somewhere', 'suggest a destination', 'any nice place'])
    is_food_query = any(f in q for f in ['recommend food', 'food in', 'where to eat', 'good food', 'hawker food'])

    if is_planning and not is_food_query:
        return 'PLANNING_REQUEST'
    if is_exploration:
        return 'PROVISIONAL_EXPLORATION'
    if is_food_query or any(t in q for t in info_triggers):
        return 'GENERAL_QUESTION'
    if any(t in q for t in planning_triggers):
        return 'PLANNING_REQUEST'
    return 'GENERAL_CONVERSATION'


def check_requirement_completeness(message, planning_state=None):
    """Detect whether essential constraints are present before planning."""
    state = dict(planning_state or {})
    intent = classify_user_intent(message, state)

    if intent != 'PLANNING_REQUEST':
        return {
            'intent': intent,
            'clarification_needed': False,
            'missing': [],
            'ready': False,
        }

    geo = extract_geographic_entities(message)
    dest = geo.get('destination_area') or state.get('destinationArea')

    if not dest:
        return {
            'intent': 'PLANNING_REQUEST',
            'clarification_needed': True,
            'missing': ['destination'],
            'ready': False,
            'clarification_prompt': (
                "I would love to help you plan your Malaysian holiday! Which destination would you like to explore? "
                "(For example: Kuala Lumpur, Penang, Langkawi, Melaka, Sabah, Sarawak, or another Malaysian destination)."
            ),
        }

    return {
        'intent': 'PLANNING_REQUEST',
        'clarification_needed': False,
        'missing': [],
        'ready': True,
        'destination': dest,
    }


def find_matching_catalog_destinations(destination_area, destination_state=None, catalog=None):
    """Find authentic destinations in the catalog matching the requested locality/state."""
    items = catalog if catalog is not None else DESTINATIONS
    area_low = clean_text(destination_area)
    state_low = clean_text(destination_state or '')

    # Try matching by city/locality
    matches = []
    for d in items:
        geo = normalize_candidate_geography(d)
        addr = clean_text(d.get('address', ''))
        title = clean_text(d.get('title', ''))

        # Exact city or locality match
        if geo.get('city') and clean_text(geo['city']) == area_low:
            matches.append(d)
        elif area_low in addr or area_low in title:
            matches.append(d)

    if matches:
        return matches

    # Try matching by state
    if state_low:
        for d in items:
            geo = normalize_candidate_geography(d)
            if geo.get('state') and clean_text(geo['state']) == state_low:
                matches.append(d)
    return matches


def build_structured_trip_plan(destination_area, destination_state=None, days=3, budget_limit=1200.0,
                               traveller_count=1, start_date=None, end_date=None, interests=None, catalog=None):
    """Build a structured trip plan from authentic catalog activities, or report coverage gap."""
    matching = find_matching_catalog_destinations(destination_area, destination_state, catalog)
    if not matching:
        return None, 'coverage_gap'

    days = max(1, min(7, int(days or 3)))
    time_slots = ['Morning (09:00 - 12:00)', 'Afternoon (13:30 - 16:30)', 'Evening (18:00 - 20:30)']
    activities = []
    idx = 0

    for day_no in range(1, days + 1):
        for slot in time_slots:
            d = matching[idx % len(matching)]
            idx += 1
            activities.append({
                'activityId': f'A{len(activities) + 1}',
                'activityName': d.get('title') or d.get('name') or f'Stop {len(activities) + 1}',
                'destinationId': d.get('destinationId') or d.get('place_id') or f'dest_{len(activities) + 1}',
                'address': d.get('address', ''),
                'state': d.get('state') or destination_state or '',
                'city': d.get('city') or destination_area or '',
                'dayNo': day_no,
                'timeSlot': slot,
                'timeRangeLabel': slot,
                'estimatedCost': float(d.get('estimatedCost', 0) or 0),
                'gps_coordinates': d.get('gps_coordinates', {}),
                'type': d.get('type') or d.get('category') or '',
                'category': d.get('category') or d.get('type') or '',
                'description': d.get('description', ''),
                'indoor': bool(d.get('indoor', False)),
                'recommendedDurationMinutes': int(d.get('recommendedDurationMinutes', 90) or 90),
                'travelBufferMinutes': 15,
                'scheduleNotes': [f"Recommended stop for Day {day_no}"],
            })

    s_date = start_date or date.today().isoformat()
    if not end_date:
        try:
            s_parsed = date.fromisoformat(s_date[:10])
            e_date = (s_parsed + timedelta(days=days - 1)).isoformat()
        except Exception:
            e_date = (date.today() + timedelta(days=days - 1)).isoformat()
    else:
        e_date = end_date

    return {
        'title': f"{days}-Day {destination_area} Itinerary Plan",
        'destinationArea': destination_area,
        'destinationState': destination_state or '',
        'destinationCountry': 'Malaysia',
        'startDate': s_date[:10],
        'endDate': e_date[:10],
        'budgetLimit': float(budget_limit or 1200.0),
        'numberOfTravellers': int(traveller_count or 1),
        'interests': list(interests or []),
        'activities': activities,
    }, 'ready'


def validate_save_plan_payload(plan):
    """Enforce strict geographic and data integrity before saving to Firestore."""
    if not plan or not isinstance(plan, dict):
        return False, 'No trip plan is available to save.'

    dest = str(plan.get('destinationArea') or plan.get('destination') or '').strip()
    if not dest:
        return False, 'Destination area is required.'

    dest_norm = normalize_destination_scope(dest)
    if not dest_norm.get('resolved') or dest_norm.get('country') != 'Malaysia':
        return False, f"TravelMate only supports travel destinations within Malaysia. '{dest}' is not a recognized Malaysian destination."

    raw_activities = plan.get('activities') or []
    if not raw_activities:
        return False, 'Cannot save a trip without scheduled activities.'

    plan_state = dest_norm.get('state')
    for act in raw_activities:
        if not isinstance(act, dict):
            continue
        act_geo = normalize_candidate_geography(act)
        if act_geo.get('resolved') and act_geo.get('state') and plan_state:
            if act_geo['state'].lower() != plan_state.lower():
                return False, f"Geographic mismatch: plan destination is '{dest}' ({plan_state}), but activity '{act.get('activityName')}' is located in '{act_geo['state']}'."

    start_str = str(plan.get('startDate') or '')[:10]
    end_str = str(plan.get('endDate') or '')[:10]
    if start_str and end_str and start_str > end_str:
        return False, f"Invalid travel dates: startDate '{start_str}' must be before or equal to endDate '{end_str}'."

    limit = float(plan.get('budgetLimit') or 0.0)
    if limit <= 0:
        return False, 'Budget limit must be a positive amount.'

    travellers_val = plan.get('numberOfTravellers')
    if travellers_val is not None:
        try:
            travellers = int(travellers_val)
        except Exception:
            travellers = 0
    else:
        travellers = 1
    if travellers < 1:
        return False, 'Number of travellers must be at least 1.'

    return True, 'Valid'
