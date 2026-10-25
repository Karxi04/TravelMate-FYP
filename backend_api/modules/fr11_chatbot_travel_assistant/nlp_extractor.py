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
from services.activity_pricing import pricing_snapshot

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


def _ordered_malaysian_mentions(text):
    """Return canonical Malaysian places in the order the traveller wrote them."""
    mentions = []
    locality_states = set()
    for area, (state, aliases) in LOCALITIES.items():
        positions = [
            match.start()
            for alias in aliases
            for match in re.finditer(rf'\b{re.escape(alias)}\b', text)
        ]
        if positions:
            mentions.append((min(positions), area, state))
            locality_states.add(state)
    for state, aliases in STATE_ALIASES.items():
        if state in locality_states:
            continue
        positions = [
            match.start()
            for alias in aliases
            for match in re.finditer(rf'\b{re.escape(alias)}\b', text)
        ]
        if positions:
            mentions.append((min(positions), state, state))

    ordered = []
    seen = set()
    for _, area, state in sorted(mentions, key=lambda item: item[0]):
        if area not in seen:
            ordered.append({'area': area, 'state': state})
            seen.add(area)
    return ordered


def extract_geographic_entities(text):
    """Accurately identify destination, origin, multi-destination and country boundary."""
    t_clean = clean_text(text)

    # 1. Check for origin/destination pattern "from X to Y"
    from_to = re.search(r'\bfrom\s+([a-z\s]+?)\s+to\s+([a-z\s]+?)(?:\s+(?:for|in|starting|under|with|next|this|on|\d)|$)', t_clean)
    foreign_origin = None
    origin_part = None
    dest_part = None

    is_dest_change = bool(re.search(
        r'\b(?:change|switch|update|modify|replace|move|instead\s+of)\b.*?\bfrom\b',
        t_clean
    )) or bool(re.search(r'\bfrom\s+[a-z\s]+?\s+to\s+[a-z\s]+?\s+instead\b', t_clean))

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
    if is_dest_change and dest_part:
        text_to_scan = dest_part
    elif origin_part and foreign_origin:
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

    ordered_mentions = _ordered_malaysian_mentions(text_to_scan)
    all_malaysian = [item['area'] for item in ordered_mentions]

    is_multi = len(all_malaysian) > 1 and not is_dest_change
    origin_mentions = _ordered_malaysian_mentions(clean_text(origin_part)) if origin_part else []
    target_mentions = _ordered_malaysian_mentions(clean_text(dest_part)) if dest_part else []
    origin_destination = None
    target_destination = None
    if is_multi:
        origin_destination = (
            origin_mentions[0]['area'] if origin_mentions else ordered_mentions[0]['area']
        )
        target_destination = (
            target_mentions[-1]['area'] if target_mentions else ordered_mentions[-1]['area']
        )

    # Foreign destination check: true only if foreign destination found without valid Malaysian sightseeing destination
    is_foreign = bool(foreign_dests and not malaysian_locs and not malaysian_states)
    unsupported_foreign = foreign_dests[0] if is_foreign else None

    primary_area = None
    primary_state = None
    if is_multi and target_mentions:
        primary_area = target_mentions[-1]['area']
        primary_state = target_mentions[-1]['state']
    elif ordered_mentions:
        primary_area = ordered_mentions[0]['area']
        primary_state = ordered_mentions[0]['state']

    return {
        'foreign_origin': foreign_origin,
        'is_foreign': is_foreign,
        'unsupported_foreign': unsupported_foreign,
        'is_multi_destination': is_multi,
        'multiple_destinations': all_malaysian if is_multi else [],
        'origin_destination': origin_destination,
        'target_destination': target_destination,
        'is_destination_change': is_dest_change,
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


def _parse_safe_count(val):
    if not val:
        return None
    val_str = str(val).strip().lower()
    if val_str in NUMBER_WORDS:
        return NUMBER_WORDS[val_str]
    try:
        n = int(val_str)
        return n if n > 0 else None
    except (ValueError, TypeError):
        return None


def extract_travellers(text, default=None):
    q = text.lower()

    # 1. Composite passenger expressions (e.g. "two adults and one child", "2 adults + 2 kids")
    num_pat = r'(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)'
    m_comp = re.search(
        rf'\b({num_pat})\s*(?:adults?|persons?|people|pax)\s*(?:and|&|\+|,)?\s*({num_pat})\s*(?:child(?:ren)?|kids?)\b',
        q
    )
    if m_comp:
        a = _parse_safe_count(m_comp.group(1))
        c = _parse_safe_count(m_comp.group(2))
        if a is not None and c is not None:
            return max(1, min(20, a + c))

    m_comp_rev = re.search(
        rf'\b({num_pat})\s*(?:child(?:ren)?|kids?)\s*(?:and|&|\+|,)?\s*({num_pat})\s*(?:adults?|persons?|people|pax)\b',
        q
    )
    if m_comp_rev:
        c = _parse_safe_count(m_comp_rev.group(1))
        a = _parse_safe_count(m_comp_rev.group(2))
        if a is not None and c is not None:
            return max(1, min(20, a + c))

    # 2. Solo / couple phrases
    if any(k in q for k in ['solo', 'by myself', 'alone', 'for 1 person', 'for one person', '1 person']):
        return 1
    if any(k in q for k in ['couple', 'two of us', '2 of us']):
        return 2

    # 3. Family of X
    m_fam = re.search(rf'\bfamily\s+of\s+({num_pat})\b', q)
    if m_fam:
        val = _parse_safe_count(m_fam.group(1))
        if val is not None:
            return max(1, min(20, val))

    # 4. X of us
    m_of_us = re.search(rf'\b({num_pat})\s+of\s+us\b', q)
    if m_of_us:
        val = _parse_safe_count(m_of_us.group(1))
        if val is not None:
            return max(1, min(20, val))

    # 5. Standard count with passenger/traveller noun (written number word or digits)
    m_count = re.search(
        rf'\b({num_pat})\s*(?:people|pax|travellers?|travelers?|persons?|adults?|passengers?)\b',
        q
    )
    if m_count:
        val = _parse_safe_count(m_count.group(1))
        if val is not None:
            return max(1, min(20, val))

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


NEGATION_CUES = r'\b(?:not|no|never|don\'?t|dont|do\s+not|exclude|excluding|excluded|avoid|avoiding|without|skip|skipping|remove|drop|dislike|hate)\b'

INTEREST_MAPPING = {
    'Food': ['food', 'culinary', 'eat', 'hawker', 'dining', 'cuisine', 'seafood'],
    'Culture': ['culture', 'cultural', 'heritage', 'history', 'historical', 'museum', 'temple', 'colonial', 'mosque'],
    'Nature': ['nature', 'adventure', 'hiking', 'mountain', 'wildlife', 'jungle', 'park'],
    'Beach': ['beach', 'island', 'coastal', 'snorkeling', 'sea', 'diving'],
    'Relaxation': ['relax', 'relaxing', 'relaxation', 'chill', 'peaceful', 'spa', 'calm'],
    'Shopping': ['shopping', 'mall', 'market', 'bazaar'],
    'Family': ['family', 'kids', 'children', 'child'],
    'Photography': ['photo', 'photography', 'viewpoint'],
}

SPECIFIC_ACTIVITY_TYPES = {
    'Museum': [r'museums?'],
    'Shopping Mall': [r'shopping\s+malls?', r'malls?'],
}

BROAD_EXCLUSION_TERMS = {
    'Food': [r'food', r'culinary', r'dining', r'cuisine'],
    'Culture': [r'culture', r'cultural\s+attractions?', r'heritage\s+attractions?'],
    'Nature': [r'nature', r'outdoor\s+nature'],
    'Beach': [r'beach(?:es)?', r'coastal\s+activities'],
    'Relaxation': [r'relaxation', r'relaxing\s+activities'],
    'Shopping': [r'shopping(?!\s+malls?)'],
    'Family': [r'family\s+activities'],
    'Photography': [r'photography'],
}

BROAD_ACTIVITY_TERMS = {
    'Food': {'food', 'culinary', 'dining', 'cuisine', 'restaurant', 'hawker'},
    'Culture': {'culture', 'cultural', 'heritage', 'history', 'historical', 'museum', 'temple', 'colonial', 'mosque', 'gallery'},
    'Nature': {'nature', 'adventure', 'hiking', 'mountain', 'wildlife', 'jungle', 'park', 'garden'},
    'Beach': {'beach', 'island', 'coastal', 'snorkeling', 'sea', 'diving'},
    'Relaxation': {'relax', 'relaxing', 'relaxation', 'spa', 'wellness'},
    'Shopping': {'shopping', 'mall', 'market', 'bazaar'},
    'Family': {'family', 'kids', 'children', 'child'},
    'Photography': {'photo', 'photography', 'viewpoint'},
}


def _is_negated_match(text, match_start):
    preceding = text[max(0, match_start - 60):match_start]
    clause = re.split(r'[,.!?;]|\bbut\b', preceding)[-1]
    return bool(re.search(rf'{NEGATION_CUES}[\w\s]{{0,45}}$', clause))


def extract_interests(text, existing=None):
    q = text.lower()
    interests = list(existing or [])

    for cat, keywords in INTEREST_MAPPING.items():
        cat_positives = 0
        cat_negatives = 0
        for kw in keywords:
            matches = list(re.finditer(rf'\b{re.escape(kw)}s?\b', q))
            if not matches:
                continue
            for m in matches:
                if _is_negated_match(q, m.start()):
                    if kw in {'museum', 'mall'}:
                        continue
                    cat_negatives += 1
                else:
                    cat_positives += 1

        if cat_negatives > 0 and cat_positives == 0:
            if cat in interests:
                interests.remove(cat)
        elif cat_positives > 0:
            if cat not in interests:
                interests.append(cat)
    return interests


def extract_excluded_interests(text, existing=None):
    q = text.lower()
    excluded = list(existing or [])

    for cat, patterns in BROAD_EXCLUSION_TERMS.items():
        for pattern in patterns:
            matches = list(re.finditer(rf'\b(?:{pattern})\b', q))
            for m in matches:
                if _is_negated_match(q, m.start()):
                    if cat not in excluded:
                        excluded.append(cat)
                    break
    return excluded


def extract_excluded_activity_types(text, existing=None):
    """Track narrow attraction exclusions without erasing broader interests."""
    q = text.lower()
    excluded = list(existing or [])

    for activity_type, patterns in SPECIFIC_ACTIVITY_TYPES.items():
        singular = 'museum' if activity_type == 'Museum' else 'shopping mall'
        plural = 'museums' if activity_type == 'Museum' else 'shopping malls'
        recovery_patterns = [
            rf'\b(?:{singular}|{plural})\s+(?:are\s+|is\s+)?(?:okay|ok|fine|allowed)(?:\s+now)?\b',
            rf'\b(?:include|allow|restore|add)\s+(?:the\s+)?(?:{singular}|{plural})\b',
        ]
        if any(re.search(pattern, q) for pattern in recovery_patterns):
            excluded = [value for value in excluded if value != activity_type]

        for pattern in patterns:
            if any(_is_negated_match(q, match.start()) for match in re.finditer(rf'\b(?:{pattern})\b', q)):
                if activity_type not in excluded:
                    excluded.append(activity_type)
                break
    return excluded


def extract_indoor_preference(text, existing=None):
    q = text.lower()
    if re.search(r'\b(?:replace\s+outdoor|indoor\s+only|indoor\s+activities|indoor\s+attractions|indoor\s+alternatives|indoor\s+places|find\s+indoor|sheltered|rain[-\s]+safe|wet\s+weather|avoid\s+outdoor|no\s+outdoor)\b', q):
        return True
    if re.search(r'\b(?:prefer\s+outdoor|outdoor\s+only|sunny|outdoor\s+activities|outdoor\s+adventure)\b', q):
        return False
    return existing


def activity_satisfies_constraints(activity, excluded_interests=None,
                                   excluded_activity_types=None, prefer_indoor=False):
    """Return whether one catalog activity satisfies every active hard constraint."""
    if prefer_indoor and activity.get('indoor') is not True:
        return False

    searchable = clean_text(' '.join(str(activity.get(field, '') or '') for field in (
        'title', 'name', 'category', 'type', 'description'
    )))

    for activity_type in excluded_activity_types or []:
        normalized = clean_text(activity_type)
        if normalized == 'museum' and re.search(r'\bmuseums?\b', searchable):
            return False
        if normalized == 'shopping mall' and (
            re.search(r'\bmalls?\b', searchable)
            or 'shopping centre' in searchable
            or 'shopping center' in searchable
        ):
            return False

    metadata = clean_text(f"{activity.get('category', '')} {activity.get('type', '')}")
    metadata_words = set(metadata.split())
    for category in excluded_interests or []:
        terms = BROAD_ACTIVITY_TERMS.get(str(category), {clean_text(category)})
        if metadata_words.intersection(terms) or any(
            re.search(rf'\b{re.escape(term)}s?\b', metadata) for term in terms
        ):
            return False
    return True


def filter_constraint_candidates(candidates, excluded_interests=None,
                                 excluded_activity_types=None, prefer_indoor=False):
    return [
        item for item in candidates
        if activity_satisfies_constraints(
            item,
            excluded_interests=excluded_interests,
            excluded_activity_types=excluded_activity_types,
            prefer_indoor=prefer_indoor,
        )
    ]


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


def classify_detailed_intent(text, planning_state=None):
    q = text.lower().strip()
    ps = dict(planning_state or {})

    # 1. Foreign / unsupported boundary check
    geo = extract_geographic_entities(text)
    if geo.get('is_foreign'):
        return 'FOREIGN_UNSUPPORTED'
    if geo.get('is_destination_change'):
        return 'ITINERARY_MODIFICATION'

    # Check for explicit itinerary planning phrases
    is_explicit_planning = (
        any(p in q for p in [
            'plan a ', 'plan my', 'plan 1', 'plan 2', 'plan 3', 'plan 4', 'plan 5', 'plan 6', 'plan 7',
            'plan one', 'plan two', 'plan three', 'plan four', 'plan five',
            'create an itinerary', 'create a ', 'build an itinerary', 'build a ', 'build an ',
            'trip to', 'holiday in', 'vacation in', 'getaway to', 'tour in', 'days in', 'day trip to',
            'schedule in', 'culinary trip to'
        ]) or (
            any(t in q for t in ['plan', 'itinerary']) and any(d in q for d in ['day', 'trip', 'weekend', 'week', 'holiday', 'vacation', 'pax', 'adults', 'travellers'])
        )
    ) and not any(k in q for k in ['change our destination', 'switch destination', 'update the plan', 'change our budget', 'reduce our budget'])

    # 2. Car rental inquiry
    if re.search(r'\b(?:car\s+rental|rent\s+a\s+car|car\s+hire|rental\s+car|vehicle\s+rental|rent\s+a\s+sedan|hire\s+an\s+suv)\b', q) or ('rent a car' in q or 'hire a car' in q or 'car rentals' in q):
        return 'CAR_RENTAL_ENQUIRY'

    # 3. Flight search inquiry
    explicit_flight = re.search(r'\b(?:flights?|airfare|airline|airports?|fly\s+to)\b', q)
    airport_route = re.search(
        r'\b(?:kul|pen|bki|kch)\b\s*(?:to|[-–>])\s*\b(?:kul|pen|bki|kch)\b', q
    )
    if (explicit_flight or airport_route) and not is_explicit_planning:
        return 'FLIGHT_ENQUIRY'

    # 4. Hotel booking inquiry
    if re.search(r'\b(?:hotels?|resorts?|rooms?|accommodation|prebook|lodging|hostel)\b', q) and not is_explicit_planning:
        return 'HOTEL_ENQUIRY'

    # 5. Feature explanation
    if any(f in q for f in ['what can you do', 'what can travelmate do', 'how does travelmate work', 'explain features', 'explain travelmate', 'what functions', 'what are your capabilities', 'what features', 'how travelmate balances']):
        return 'FEATURE_EXPLANATION'

    # 6. Indoor alternative request vs Weather inquiry
    if re.search(r'\b(?:replace\s+outdoor|indoor\s+activities|indoor\s+attractions|sheltered\s+places|indoor\s+sheltered|wet\s+weather|indoor\s+alternatives|indoor\s+rain|indoor\s+places|indoor\s+museums)\b', q) or ('indoor' in q and any(w in q for w in ['rain', 'raining', 'wet', 'pours', 'thunderstorm'])):
        return 'INDOOR_ALTERNATIVE'
    if re.search(r'\b(?:rain|rains|rainy|raining|downpour|thunderstorm|weather|forecast|temperature|hot|cold)\b', q) and not is_explicit_planning:
        return 'WEATHER_ENQUIRY'

    # 7. Conversational modifications & adjustments
    if re.search(r'\b(?:change\s+(?:our\s+|the\s+)?destination|switch\s+destination|change\s+from\s+\w+\s+to\s+\w+|update\s+(?:the\s+)?plan|modify\s+(?:the\s+)?schedule)\b', q):
        return 'ITINERARY_MODIFICATION'

    if re.search(r'\b(?:change\s+(?:the\s+|our\s+)?budget|reduce\s+(?:the\s+|our\s+)?budget|increase\s+(?:the\s+|our\s+)?budget|set\s+budget|budget\s+to\s+rm|make\s+it\s+cheaper|cheaper\s+budget)\b', q) or (
        extract_budget(text) is not None and any(w in q for w in ['change', 'reduce', 'make', 'update', 'actually', 'instead', 'increase']) and not is_explicit_planning
    ):
        return 'BUDGET_ADJUSTMENT'

    if re.search(r'\b(?:there\s+will\s+be|add\s+one\s+more\s+person|now\s+there\s+are|change\s+(?:the\s+)?(?:travellers?|people|pax))\b', q) or (
        extract_travellers(text) is not None and any(w in q for w in ['people', 'adults', 'kids', 'children', 'of us', 'pax', 'travellers']) and not is_explicit_planning and not any(de in q for de in ['tell me', 'what is', 'what to', 'attractions', 'places'])
    ):
        return 'TRAVELLER_COUNT_ADJUSTMENT'

    if re.search(r'\b(?:actually\s+make\s+it\s+\w+\s+days?|make\s+it\s+\d+\s+days?|change\s+(?:the\s+)?duration|change\s+to\s+\d+\s+days?|extend\s+(?:the\s+|our\s+)?trip|extend\s+to|shorten\s+(?:the\s+|our\s+)?holiday|shorten\s+to)\b', q):
        return 'DURATION_ADJUSTMENT'

    if re.search(r'\b(?:change\s+(?:travel\s+|our\s+|the\s+)?dates?|move\s+(?:the\s+)?dates?|travel\s+dates\s+to|starting\s+tomorrow|start\s+date|reschedule|different\s+date)\b', q):
        return 'DATE_ADJUSTMENT'

    # 8. Budget advice enquiry
    if re.search(r'\b(?:how\s+should\s+i\s+budget|how\s+to\s+budget|save\s+money|budget\s+tips|affordable\s+tips|is\s+rm\s*\d+\s+enough|how\s+much\s+money|how\s+much\s+budget|how\s+much\s+should\s+i\s+budget)\b', q) and not is_explicit_planning:
        return 'BUDGET_ENQUIRY'

    # 9. Interest modification
    if re.search(r'\b(?:do\s+not\s+include|exclude|no\s+museums|no\s+shopping|no\s+extreme\s+sports|enjoy\s+food|focus\s+on|prefer\s+nature|avoid|skip)\b', q) and not is_explicit_planning:
        return 'INTEREST_MODIFICATION'

    # 10. Destination recommendation vs Explicit Planning
    if any(e in q for e in ['somewhere relaxing', 'where should i go', 'recommend somewhere', 'suggest a destination', 'any nice place', 'recommend a place', 'best destination', 'best malaysian destination', 'where should i visit']):
        return 'DESTINATION_RECOMMENDATION'

    # 11. Explicit planning
    if is_explicit_planning:
        return 'ITINERARY_PLANNING'

    # 12. Destination enquiry
    if any(de in q for de in ['tell me about', 'what is', 'what to see in', 'attractions in', 'places to visit in', 'what can i see in', 'highlights of', 'good places', 'must-see', 'tourist spots', 'hawker stalls', 'places to eat', 'is bako', 'can i visit', 'what attractions', 'recommend the best', 'what can tourists']):
        return 'DESTINATION_ENQUIRY'

    # 13. Social / general conversation
    if any(gc in q for gc in ['hello', 'hi', 'good morning', 'good evening', 'thank you', 'thanks', 'goodbye', 'bye', 'nice to meet you', 'who created you']):
        return 'GENERAL_CONVERSATION'

    # 14. Fallbacks
    if any(t in q for t in ['recommend', 'food', 'eat', 'restaurant', 'attraction']):
        return 'DESTINATION_ENQUIRY'
    if any(t in q for t in ['plan', 'itinerary', 'trip']):
        return 'ITINERARY_PLANNING'

    return 'GENERAL_CONVERSATION'


def classify_user_intent(text, planning_state=None):
    detailed = classify_detailed_intent(text, planning_state)
    ps = dict(planning_state or {})
    dest = ps.get('destinationArea') or extract_geographic_entities(text).get('destination_area')

    if detailed in {'ITINERARY_PLANNING', 'ITINERARY_MODIFICATION'}:
        return 'PLANNING_REQUEST'
    if detailed in {'DURATION_ADJUSTMENT', 'BUDGET_ADJUSTMENT', 'TRAVELLER_COUNT_ADJUSTMENT', 'DATE_ADJUSTMENT', 'INTEREST_MODIFICATION', 'INDOOR_ALTERNATIVE'}:
        if dest:
            return 'PLANNING_REQUEST'
        return 'GENERAL_QUESTION'
    if detailed == 'DESTINATION_RECOMMENDATION':
        return 'PROVISIONAL_EXPLORATION'
    if detailed in {'DESTINATION_ENQUIRY', 'BUDGET_ENQUIRY', 'WEATHER_ENQUIRY', 'HOTEL_ENQUIRY', 'FLIGHT_ENQUIRY', 'CAR_RENTAL_ENQUIRY', 'FEATURE_EXPLANATION', 'FOREIGN_UNSUPPORTED'}:
        return 'GENERAL_QUESTION'
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
                               traveller_count=1, start_date=None, end_date=None, interests=None,
                               excluded_interests=None, excluded_activity_types=None,
                               prefer_indoor=False, catalog=None):
    """Build a structured trip plan from authentic catalog activities, or report coverage gap."""
    matching = find_matching_catalog_destinations(destination_area, destination_state, catalog)
    if not matching:
        return None, 'coverage_gap'

    matching = filter_constraint_candidates(
        matching,
        excluded_interests=excluded_interests,
        excluded_activity_types=excluded_activity_types,
        prefer_indoor=prefer_indoor,
    )
    if not matching:
        return None, 'constraint_conflict'

    days = max(1, min(7, int(days or 3)))
    time_slots = ['Morning (09:00 - 12:00)', 'Afternoon (13:30 - 16:30)', 'Evening (18:00 - 20:30)']
    activities = []
    activity_count = days * len(time_slots)
    has_hard_constraints = bool(excluded_interests or excluded_activity_types or prefer_indoor)
    scheduled = (
        matching[:activity_count]
        if has_hard_constraints
        else [matching[idx % len(matching)] for idx in range(activity_count)]
    )
    for idx, d in enumerate(scheduled):
        day_no = (idx // len(time_slots)) + 1
        slot = time_slots[idx % len(time_slots)]
        activities.append({
                'activityId': f'A{len(activities) + 1}',
                'activityName': d.get('title') or d.get('name') or f'Stop {len(activities) + 1}',
                'destinationId': d.get('destinationId') or d.get('place_id') or f'dest_{len(activities) + 1}',
                'imageUrl': d.get('imageUrl') or d.get('thumbnail') or '',
                'thumbnail': d.get('thumbnail') or d.get('imageUrl') or '',
                'photoAttribution': d.get('photoAttribution') or 'Wikimedia Commons',
                'imageSource': d.get('imageSource') or 'local_catalog',
                'address': d.get('address', ''),
                'state': d.get('state') or destination_state or '',
                'city': d.get('city') or destination_area or '',
                'dayNo': day_no,
                'timeSlot': slot,
                'timeRangeLabel': slot,
                'estimatedCost': float(d.get('estimatedCost', 0) or 0),
                **pricing_snapshot(d),
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
        'excludedInterests': list(excluded_interests or []),
        'excludedActivityTypes': list(excluded_activity_types or []),
        'preferIndoor': bool(prefer_indoor),
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
