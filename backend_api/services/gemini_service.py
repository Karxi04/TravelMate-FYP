import os
import re
import time
import logging
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

SYSTEM_PREFIX = (
    "You are TravelMate, a concise and practical Malaysia-wide travel-planning assistant. "
    "TravelMate supports travel planning across the entire country of Malaysia (all 13 states and 3 federal territories, "
    "including Kuala Lumpur, Penang, Langkawi, Melaka, Sabah, Sarawak, Johor, Perak, Pahang, Kedah, Kelantan, "
    "Terengganu, Negeri Sembilan, Perlis, Putrajaya, and Labuan). "
    "If a traveller requests a destination outside Malaysia (e.g. Singapore, Tokyo, Bangkok, Bali), politely explain that "
    "TravelMate is dedicated exclusively to Malaysia travel planning, but offer to assist with any Malaysian destination. "
    "Help with destinations, personalised itinerary ideas, budget planning, weather interpretation, "
    "flight/hotel planning and general travel questions. Use the traveller context and active trip planning state when supplied. "
    "Never claim a booking or payment is confirmed unless the system context includes an actual reference."
)

DEFAULT_TIMEOUT_SECONDS = 30
MIN_TIMEOUT_SECONDS = 5
MAX_TIMEOUT_SECONDS = 120


def get_gemini_timeout_seconds():
    raw = os.getenv('GEMINI_TIMEOUT_SECONDS')
    if raw is None or str(raw).strip() == '':
        return DEFAULT_TIMEOUT_SECONDS
    try:
        val = float(str(raw).strip())
        if val <= 0:
            return DEFAULT_TIMEOUT_SECONDS
        if val < MIN_TIMEOUT_SECONDS:
            return MIN_TIMEOUT_SECONDS
        if val > MAX_TIMEOUT_SECONDS:
            return MAX_TIMEOUT_SECONDS
        return val
    except (ValueError, TypeError):
        return DEFAULT_TIMEOUT_SECONDS


def _classify_provider_error(exc):
    """Sanitized classification of provider errors without logging PII or raw secrets."""
    status_code = getattr(exc, 'code', None)
    exc_name = type(exc).__name__
    msg = str(exc)

    if status_code is not None or 'ClientError' in exc_name or 'ServerError' in exc_name:
        if status_code == 400 or '400' in msg:
            return 'HTTP_400_BAD_REQUEST'
        elif status_code in {401, 403} or '401' in msg or '403' in msg:
            return 'HTTP_401_403_AUTH_ERROR'
        elif status_code == 429 or '429' in msg or 'RESOURCE_EXHAUSTED' in msg:
            return 'HTTP_429_RATE_LIMIT_EXHAUSTED'
        elif status_code == 503 or '503' in msg or 'UNAVAILABLE' in msg:
            return 'HTTP_503_SERVICE_UNAVAILABLE'
        elif status_code == 504 or '504' in msg or 'DEADLINE_EXCEEDED' in msg:
            return 'HTTP_504_DEADLINE_EXCEEDED'
        elif status_code:
            return f'HTTP_{status_code}_PROVIDER_ERROR'

    if 'timeout' in exc_name.lower() or 'timeout' in msg.lower() or 'timed out' in msg.lower():
        return 'CLIENT_TIMEOUT'

    if 'empty' in msg.lower():
        return 'EMPTY_PROVIDER_RESPONSE'

    return 'UNEXPECTED_PROVIDER_ERROR'


def _fallback_mode():
    return os.getenv('FALLBACK_MODE', 'false').lower() in {'1', 'true', 'yes'}


def is_gemini_configured():
    return bool(os.getenv('GEMINI_API_KEY', '').strip())


def _generate(message):
    key = os.getenv('GEMINI_API_KEY', '').strip()
    if not key:
        raise RuntimeError('GEMINI_API_KEY is not configured')
    model = os.getenv('GEMINI_MODEL', 'gemini-3.7-flash').strip() or 'gemini-3.7-flash'
    timeout_sec = get_gemini_timeout_seconds()
    timeout_ms = int(timeout_sec * 1000)

    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=timeout_ms))

    config_kwargs = {'system_instruction': SYSTEM_PREFIX}
    if hasattr(types, 'ThinkingConfig') and hasattr(types, 'ThinkingLevel'):
        config_kwargs['thinking_config'] = types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)

    response = client.models.generate_content(
        model=model,
        contents=message,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    text = getattr(response, 'text', None)
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError('Gemini returned an empty response')
    return text.strip()


def _format_tailored_planning_fallback(dest, dest_state, days, budget, travellers, s_date, e_date, interests):
    """Composes structured, personalized guidance acknowledged from validated planningState."""
    parts = [f"Here is a tailored {days}-day travel plan for {dest}"]
    if dest_state and dest_state != dest and dest_state != 'Malaysia':
        parts[0] += f" ({dest_state})"
    if s_date and e_date:
        parts.append(f"from {s_date} to {e_date}")
    if travellers:
        s_plural = 's' if travellers > 1 else ''
        parts.append(f"for {travellers} traveller{s_plural}")
    if budget:
        parts.append(f"with an estimated target budget of RM{budget:g}")
    intro = ", ".join(parts) + "."
    if interests:
        intro += f" Highlighting your interests in {', '.join(interests)}."

    dest_lower = dest.lower()
    if 'kuala lumpur' in dest_lower or dest_lower == 'kl':
        structure = (
            "Recommended structure: Day 1 Petronas Twin Towers, KLCC Park and Bukit Bintang street food; "
            "Day 2 Batu Caves Temple, Merdeka Square and colonial heritage landmarks; "
            "Day 3 Perdana Botanical Garden, National Museum and Thean Hou Temple."
        )
    elif 'melaka' in dest_lower or 'malacca' in dest_lower:
        structure = (
            "Recommended structure: Day 1 A Famosa fortress, St. Paul's Hill, the Stadthuys Red Square, and Jonker Street night market; "
            "Day 2 Melaka River Cruise, Baba & Nyonya Heritage Museum, and local Peranakan food trails; "
            "Day 3 coastal views and historical handicrafts."
        )
    elif 'penang' in dest_lower or 'george town' in dest_lower:
        structure = (
            "Recommended structure: Day 1 George Town UNESCO heritage core, street art murals and food trail; "
            "Day 2 Kek Lok Si Temple, Penang Hill funicular and Air Itam laksa; "
            "Day 3 Penang Botanic Gardens or Batu Ferringhi beach."
        )
    elif 'langkawi' in dest_lower:
        structure = (
            "Recommended structure: Day 1 Langkawi SkyCab and curved Sky Bridge; "
            "Day 2 Kilim Karst Geoforest Park boat safari with eagle feeding and mangrove caves; "
            "Day 3 relaxation at Pantai Cenang beach and night food market."
        )
    elif 'sabah' in dest_lower or 'kota kinabalu' in dest_lower:
        structure = (
            "Recommended structure: Day 1 Kota Kinabalu City Mosque, waterfront market and Tanjung Aru sunset; "
            "Day 2 Tunku Abdul Rahman Marine Park island hopping; "
            "Day 3 day-trip to Kinabalu National Park and Kundasang highland farms."
        )
    elif 'sarawak' in dest_lower or 'kuching' in dest_lower:
        structure = (
            "Recommended structure: Day 1 Kuching Waterfront, Astana viewpoint and Borneo Cultures Museum; "
            "Day 2 Bako National Park coastal hike; "
            "Day 3 Sarawak Cultural Village and Semenggoh Wildlife Centre."
        )
    else:
        structure = f"Recommended structure: Explore the top cultural, natural, and culinary highlights of {dest} across {days} days, pacing activities conveniently by area."

    if budget:
        cost_note = f"Please note that the RM{budget:g} budget is an estimate covering local transit, dining, and admission fees; check live accommodation and flight prices in TravelMate before finalizing bookings."
    else:
        cost_note = "Please note that budget totals are estimates; verify live rates in TravelMate before making bookings."
    footer = f"{cost_note} Use the day-by-day plan and attraction cards below to explore your itinerary."

    return f"{intro}\n\n{structure}\n\n{footer}"


def _local_assistant(question, context='', planning_state=None):
    """A useful local fallback so FR11 remains demonstrable without a paid/live key across Malaysia."""
    q = str(question or '').strip().lower()
    context_lower = str(context or '').lower()
    ps = dict(planning_state or {})

    # 1. Foreign destinations boundary check
    foreign_keywords = ['singapore', 'tokyo', 'japan', 'bangkok', 'thailand', 'bali', 'indonesia', 'seoul', 'london', 'paris', 'phuket']
    matched_foreign = [f for f in foreign_keywords if f in q]
    if matched_foreign and not ('from ' in q and any(my in q for my in ['penang', 'kuala lumpur', 'kl', 'melaka', 'malaysia'])):
        foreign_name = matched_foreign[0].title()
        return (
            f"TravelMate is dedicated exclusively to travel planning within Malaysia. "
            f"I cannot create travel plans or search attractions for {foreign_name}, but I would be glad to help you "
            f"plan an exciting trip to Kuala Lumpur, Penang, Langkawi, Melaka, Sabah, Sarawak, or anywhere across Malaysia!"
        )

    # Helper detection
    is_explicit_planning = any(p in q for p in ['plan a', 'plan my', 'create an itinerary', 'build an itinerary', '-day trip', 'days in', 'day trip to']) or (
        any(t in q for t in ['plan', 'itinerary']) and any(d in q for d in ['day', 'trip', 'holiday', 'vacation'])
    )

    # 2. Weather inquiry (bounded regex to prevent 'hotel' matching 'hot')
    is_weather = bool(re.search(r'\b(?:rain|rains|rainy|raining|downpour|thunderstorm|weather|forecast|hot|temperature)\b', q))
    if is_weather and not is_explicit_planning:
        return (
            "Check the Weather tool for the live Open-Meteo forecast. TravelMate's smart itinerary generator treats museums, malls and indoor food experiences "
            "as safer wet-weather choices, while beaches, gardens, hill viewpoints and outdoor adventure stops stay flexible when rain probability is high."
        )

    # 3. Flight search inquiry
    if any(word in q for word in ['flight', 'airport', 'kul', 'pen', 'bki', 'kch', 'airline']) and not is_explicit_planning:
        return (
            "Use Home → Flights to search by airport code and date across Malaysian hubs (KUL, PEN, BKI, KCH, etc.). "
            "TravelMate can compare price, duration and stops, then attach a selected flight reference and cost to an itinerary. "
            "With a SerpApi key the results are live; in fallback mode the same selection and comparison flow remains usable."
        )

    # 4. Hotel booking inquiry
    if any(word in q for word in ['hotel', 'room', 'stay', 'accommodation', 'prebook']) and not is_explicit_planning:
        return (
            "Use Home → Hotels to search by destination and dates across Malaysia. You can filter refundable offers, compare room prices, prebook an offer and complete a safe sandbox/local booking. "
            "The selected hotel cost can then be included in the itinerary budget."
        )

    # 4b. Car rental inquiry
    if re.search(r'\b(?:car\s+rental|rent\s+a\s+car|car\s+hire|rental\s+car|vehicle\s+rental)\b', q) and not is_explicit_planning:
        return (
            "Use Home → Car Rental to compare vehicle categories (Economy, Compact, Sedan, SUV, Van) across Malaysian hubs like Kuala Lumpur, Penang, Kota Kinabalu, and Kuching. "
            "You can choose pickup dates, check simulated rates, and attach a car rental to your trip itinerary."
        )

    # 4c. Indoor alternative request
    if re.search(r'\b(?:replace\s+outdoor|indoor\s+only|indoor\s+activities|indoor\s+attractions|sheltered|rain\s+safe|wet\s+weather|indoor\s+alternatives)\b', q):
        dest_name = ps.get('destinationArea') or 'your destination'
        return (
            f"When wet weather is expected in {dest_name}, TravelMate's smart itinerary prioritizes indoor cultural and entertainment destinations "
            f"such as museums, aquariums, art galleries, and covered heritage sites (like Pinang Peranakan Mansion, Islamic Arts Museum, or Wonderfood Museum), "
            f"while outdoor hills, beaches and parks stay flexible. Your travel plan has been updated with indoor alternatives."
        )

    # 5. General feature explanation inquiry
    if any(f in q for f in ['what can you do', 'what can travelmate do', 'how does travelmate work', 'explain features', 'explain travelmate', 'what functions']):
        return (
            "TravelMate is your smart AI-driven travel planning assistant for Malaysia. I can help you discover destinations, "
            "build customized daily itineraries, balance your budget, check live weather, search flights, and simulate hotel bookings across all 13 states and 3 Federal Territories."
        )

    # 6. Pure standalone budget advice inquiry
    is_pure_budget = any(p in q for p in ['how to budget', 'how should i budget', 'save money', 'budget tips', 'affordable tips', 'how much should i budget']) or (
        any(word in q for word in ['budget', 'cheap', 'cost', 'save money', 'affordable']) and not is_explicit_planning and not any(k in q for k in ['change our budget', 'change the budget', 'budget to', 'set budget', 'limit of rm', 'budget of rm', 'reduce our budget', 'reduce the budget', 'make it cheaper', 'rm '])
    )
    if is_pure_budget and not is_explicit_planning:
        return (
            "For a practical TravelMate budget, split the limit into transport, hotel, food and activities. "
            "Keep a 10–15% buffer. If the itinerary is over budget, compare a lower hotel tier, a cheaper flight time, "
            "group nearby attractions to reduce transport, and replace one premium activity with a free heritage, garden or beach stop. "
            "Open Trips → Budget to see the system's calculated total and alternatives."
        )

    # 6b. Conversational Adjustments when planningState has active destination
    dest = ps.get('destinationArea') or ps.get('destinationState')
    if not dest:
        for candidate, canon in [('kuala lumpur', 'Kuala Lumpur'), ('kl', 'Kuala Lumpur'), ('melaka', 'Melaka'), ('malacca', 'Melaka'), ('penang', 'Penang'), ('george town', 'Penang'), ('langkawi', 'Langkawi'), ('sabah', 'Sabah'), ('kota kinabalu', 'Kota Kinabalu'), ('sarawak', 'Sarawak'), ('kuching', 'Kuching'), ('ipoh', 'Ipoh')]:
            if re.search(r'\b' + re.escape(candidate) + r'\b', q):
                dest = canon
                break

    has_planning_intent = is_explicit_planning or any(k in q for k in ['plan', 'itinerary', 'trip', 'change our budget', 'budget to', 'make it cheaper', 'days', 'travellers', 'people'])
    if dest and (has_planning_intent or ps.get('tripDays') or ps.get('budgetLimit')):
        dest_state = ps.get('destinationState') or dest
        days = ps.get('tripDays') or 3
        budget = ps.get('budgetLimit')
        travellers = ps.get('travellerCount')
        s_date = ps.get('startDate')
        e_date = ps.get('endDate')
        interests = ps.get('interests') or []
        return _format_tailored_planning_fallback(dest, dest_state, days, budget, travellers, s_date, e_date, interests)

    # 8. Destination-specific food advice
    if any(word in q for word in ['kuala lumpur', ' kl ']) or q.endswith(' kl') or q.startswith('kl '):
        if any(word in q for word in ['food', 'eat', 'hawker', 'restaurant']):
            return (
                "For Kuala Lumpur, must-try food experiences include Jalan Alor night street food (grilled chicken wings, satay, dim sum), "
                "Petaling Street Chinatown for beef noodles and claypot rice, and Brickfields for authentic South Indian banana leaf rice."
            )
        return (
            "A balanced 3-day Kuala Lumpur structure is: Day 1 Petronas Twin Towers, KLCC Park and Bukit Bintang shopping & street food; "
            "Day 2 Batu Caves Temple, Merdeka Square and colonial heritage landmarks; "
            "Day 3 Perdana Botanical Garden, National Museum and Thean Hou Temple. "
            "Use Home → Personalised Plan to arrange these automatically based on your preferences."
        )

    if any(word in q for word in ['melaka', 'malacca']):
        if any(word in q for word in ['food', 'eat', 'hawker', 'restaurant']):
            return (
                "In Melaka, do not miss Hainanese chicken rice balls along Jonker Street, authentic Nyonya laksa, Peranakan kuih, "
                "and refreshing Gula Melaka cendol near the Stadthuys."
            )
        return (
            "A simple Melaka itinerary includes: Day 1 A Famosa fortress, St. Paul's Hill, the Stadthuys Red Square, and Jonker Street night market; "
            "Day 2 Melaka River Cruise, Baba & Nyonya Heritage Museum, and a local food trail along the historical waterfront."
        )

    if 'langkawi' in q:
        if any(word in q for word in ['food', 'eat', 'hawker', 'restaurant']):
            return (
                "In Langkawi, enjoy fresh seafood along Pantai Cenang, local Malay laksa near the airport, and the rotating night markets "
                "in Kuah and Padang Matsirat for budget-friendly authentic street dishes."
            )
        return (
            "A great Langkawi holiday structure: Day 1 Langkawi SkyCab cable car and curved Sky Bridge; "
            "Day 2 Kilim Karst Geoforest Park boat safari with eagle feeding and mangrove caves; "
            "Day 3 relaxation and water activities at Pantai Cenang beach."
        )

    if any(word in q for word in ['sabah', 'kota kinabalu', ' kk ']) or q.endswith(' kk'):
        if any(word in q for word in ['food', 'eat', 'hawker', 'restaurant']):
            return (
                "In Sabah, savour fresh ocean seafood at the Kota Kinabalu Waterfront, local Tuaran mee, Hinava (traditional Kadazan-Dusun raw fish salad), "
                "and freshly grilled fish at the Filipino Market night stalls."
            )
        return (
            "A recommended Sabah itinerary: Day 1 Kota Kinabalu City Mosque, Tanjung Aru beach sunset and night food market; "
            "Day 2 Tunku Abdul Rahman Marine Park island hopping and snorkeling; "
            "Day 3 day-trip to Kinabalu National Park and Kundasang highland farms."
        )

    if any(word in q for word in ['sarawak', 'kuching']):
        if any(word in q for word in ['food', 'eat', 'hawker', 'restaurant']):
            return (
                "In Kuching, start your morning with authentic Sarawak laksa (praised by Anthony Bourdain), followed by springy kolo mee, "
                "crisp jungle midin fern, and layered Sarawak kek lapis along the waterfront."
            )
        return (
            "A memorable Sarawak trip: Day 1 Kuching Waterfront, Astana viewpoint and the world-class Borneo Cultures Museum; "
            "Day 2 Bako National Park coastal hike to spot proboscis monkeys and sea stacks; "
            "Day 3 Sarawak Cultural Village and Semenggoh Wildlife Centre orangutan sanctuary."
        )

    if any(word in q for word in ['food', 'eat', 'hawker', 'restaurant']):
        return (
            "Across Malaysia, every region offers iconic food: Penang is famous for Char Koay Teow, Asam Laksa and Cendol; "
            "Kuala Lumpur for Jalan Alor street food and Nasi Lemak; Melaka for Chicken Rice Balls and Nyonya cuisine; "
            "Ipoh for white coffee and bean sprout chicken; and Sarawak for authentic Sarawak Laksa and Kolo Mee."
        )

    if any(word in q for word in ['plan', 'itinerary', 'day', 'trip', 'penang', 'george town']):
        return (
            "A simple 3-day Penang structure is: Day 1 George Town heritage core + Peranakan/Wonderfood Museum + food trail; "
            "Day 2 Kek Lok Si + Penang Hill + Air Itam food; Day 3 Botanic Gardens or Batu Ferringhi, with an indoor mall/museum backup if rain is likely. "
            "For a personalised version, use Home → Personalised Plan so TravelMate ranks destinations from your preferences and generates the day schedule automatically."
        )

    if context_lower:
        return (
            "I can continue from your TravelMate context. Tell me whether you want to optimise the destination choices, daily activity order, budget, weather plan, flights or hotels, "
            "and I will keep the answer focused on that part of your trip."
        )

    return (
        "I can help you plan destinations across all of Malaysia, build an itinerary, compare a budget, interpret weather, search flights/hotels, or improve an existing TravelMate trip. "
        "Try: ‘Plan a 3-day Kuala Lumpur trip under RM1000’ or ‘Plan a 4-day Langkawi holiday’ or ‘What should I change if it rains on Day 2?’"
    )


def generateChatbotResponse(question, context='', *, with_source=False, planning_state=None):
    source = 'travelmate-assistant'
    start_t = time.perf_counter()
    if is_gemini_configured():
        try:
            reply = _generate((context + '\n\n' if context else '') + 'Traveller: ' + str(question))
            source = 'gemini'
        except Exception as exc:
            elapsed = time.perf_counter() - start_t
            category = _classify_provider_error(exc)
            logger.warning("[FR11 Gemini] Provider failure: category=%s, elapsed=%.2fs", category, elapsed)
            if _fallback_mode():
                reply = _local_assistant(question, context, planning_state=planning_state)
            else:
                raise RuntimeError('Gemini service is unavailable') from None
    elif _fallback_mode():
        reply = _local_assistant(question, context, planning_state=planning_state)
    else:
        raise RuntimeError('Gemini service is unavailable')
    return {'reply': reply, 'source': source} if with_source else reply


def generateFollowUpResponse(question, context='', *, with_source=False, planning_state=None):
    return generateChatbotResponse(question, context, with_source=with_source, planning_state=planning_state)


def ask(message, planning_state=None):
    return generateChatbotResponse(message, planning_state=planning_state)
