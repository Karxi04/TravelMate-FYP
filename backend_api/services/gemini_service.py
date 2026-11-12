import os
import re
import time
import logging
import math
import json
from time import monotonic
from google import genai
from google.genai import types
from httpx import TimeoutException

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
    "Never invent Operator packages, availability, campaign discounts, payable amounts or supplier confirmations. "
    "Commercial facts must come from structured TravelMate backend tools; ordinary itinerary estimates are not package offers. "
    "Never claim a booking or payment is confirmed unless a verified TravelMate record confirms its status. "
    "Use short plain-text paragraphs and compact lists. Answer the specific question and use relevant context. "
    "Never output JSON, internal identifiers, or provider diagnostics. "
    "Give general weather guidance unless a current forecast was supplied. Never present general advice as live data."
    " TravelMate does not offer car rental. Smart Packing Checklist is available from a saved trip. "
    "Hotel search results and payment records do not by themselves confirm supplier reservations."
)

DEFAULT_TIMEOUT_SECONDS = 8
MIN_TIMEOUT_SECONDS = 5
MAX_TIMEOUT_SECONDS = 120
SERVER_TIMEOUT_FLOOR_SECONDS = 20
PROVIDER_COOLDOWN_SECONDS = 45
_provider_retry_at = 0.0
_CAR_RENTAL_REPLY = (
    "TravelMate no longer offers car rental. If you already have transport, you can account for it in your trip budget. "
    "Open a saved trip to use Smart Packing Checklist."
)


def get_gemini_timeout_seconds():
    raw = os.getenv('GEMINI_TIMEOUT_SECONDS')
    if raw is None or str(raw).strip() == '':
        return DEFAULT_TIMEOUT_SECONDS
    try:
        val = float(str(raw).strip())
        if not math.isfinite(val) or val <= 0:
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
    if type(status_code) is int:
        return {
            400: 'HTTP_400_BAD_REQUEST',
            401: 'HTTP_401_403_AUTH_ERROR',
            403: 'HTTP_401_403_AUTH_ERROR',
            404: 'HTTP_404_MODEL_OR_RESOURCE_NOT_FOUND',
            429: 'HTTP_429_RATE_LIMIT_EXHAUSTED',
            500: 'HTTP_500_PROVIDER_ERROR',
            503: 'HTTP_503_SERVICE_UNAVAILABLE',
            504: 'HTTP_504_DEADLINE_EXCEEDED',
        }.get(status_code, 'OTHER_PROVIDER_HTTP_ERROR')
    if isinstance(exc, (TimeoutException, TimeoutError)):
        return 'CLIENT_TIMEOUT'
    if isinstance(exc, EmptyProviderResponse):
        return 'EMPTY_PROVIDER_RESPONSE'
    if isinstance(exc, InvalidProviderResponse):
        return 'INVALID_PROVIDER_RESPONSE'

    return 'UNEXPECTED_PROVIDER_ERROR'


def _fallback_mode():
    return os.getenv('FALLBACK_MODE', 'false').lower() in {'1', 'true', 'yes'}


def is_gemini_configured():
    return bool(os.getenv('GEMINI_API_KEY', '').strip())


class EmptyProviderResponse(RuntimeError):
    pass


class InvalidProviderResponse(RuntimeError):
    pass


def _generate(message):
    key = os.getenv('GEMINI_API_KEY', '').strip()
    if not key:
        raise RuntimeError('GEMINI_API_KEY is not configured')
    model = os.getenv('GEMINI_MODEL', 'gemini-3.7-flash').strip() or 'gemini-3.7-flash'
    timeout_sec = get_gemini_timeout_seconds()
    timeout_ms = int(timeout_sec * 1000)

    # The SDK also derives a server deadline from its client timeout unless explicitly supplied.
    server_timeout = math.ceil(max(timeout_sec, SERVER_TIMEOUT_FLOOR_SECONDS))
    options = types.HttpOptions(
        timeout=timeout_ms, headers={'X-Server-Timeout': str(server_timeout)},
        retry_options=types.HttpRetryOptions(attempts=1),
    )
    config_kwargs = {'system_instruction': SYSTEM_PREFIX, 'max_output_tokens': 1024}
    if model.startswith('gemini-3') and hasattr(types, 'ThinkingLevel'):
        config_kwargs['thinking_config'] = types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)

    client = genai.Client(api_key=key, http_options=options)
    try:
        response = client.models.generate_content(
            model=model,
            contents=message,
            config=types.GenerateContentConfig(**config_kwargs),
        )
    finally:
        client.close()
    text = getattr(response, 'text', None)
    if not isinstance(text, str) or not text.strip():
        raise EmptyProviderResponse()
    text = text.strip()
    if text.startswith(('{', '[', '```')):
        if text.startswith('```'):
            raise InvalidProviderResponse()
        try:
            structured = json.loads(text)
        except ValueError:
            structured = None
        if isinstance(structured, (dict, list)):
            raise InvalidProviderResponse()
    return text


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

    from modules.fr11_chatbot_travel_assistant.nlp_extractor import find_matching_catalog_destinations
    candidates = find_matching_catalog_destinations(dest, dest_state)
    names = [row.get('title') or row.get('name') for row in candidates[:5]]
    names = [name for name in names if name]
    structure = ('TravelMate catalogue ideas: ' + ', '.join(names) + '.' if names else
                 f'I have limited verified activity information for {dest}.')

    if budget:
        cost_note = f"Please note that the RM{budget:g} budget is an estimate covering local transit, dining, and admission fees; check live accommodation and flight prices in TravelMate before finalizing bookings."
    else:
        cost_note = "Please note that budget totals are estimates; verify live rates in TravelMate before making bookings."
    footer = f"{cost_note} Check current place details before adding stops to your itinerary."

    return f"{intro}\n\n{structure}\n\n{footer}"


def _local_assistant(question, context='', planning_state=None):
    """A useful local fallback so FR11 remains demonstrable without a paid/live key across Malaysia."""
    from modules.fr11_chatbot_travel_assistant.nlp_extractor import (
        activity_request, car_rental_question, conversational_question,
        extract_duration, extract_geographic_entities,
    )

    q = str(question or '').strip().lower()
    context_lower = str(context or '').lower()
    ps = dict(planning_state or {})
    detailed_intent = ps.get('lastIntent')
    excluded_labels = list(ps.get('excludedInterests') or []) + list(ps.get('excludedActivityTypes') or [])
    if car_rental_question(q):
        return _CAR_RENTAL_REPLY

    def constrained_indoor_reply(destination):
        exclusion_note = ''
        if excluded_labels:
            exclusion_note = f" I will keep {', '.join(excluded_labels)} out of every suggestion."
        return (
            f"Indoor-only planning is active for {destination}.{exclusion_note} TravelMate will use only "
            "verified rain-safe catalog activities that satisfy all active constraints. If none remain, "
            "I will report a constraint conflict instead of inserting prohibited or outdoor substitutes."
        )

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

    if ps.get('tripMode') == 'road_trip' and detailed_intent == 'ITINERARY_PLANNING':
        origin = ps.get('originDestination') or 'the origin'
        target = ps.get('targetDestination') or 'the destination'
        return (
            f"I understand the road-trip request from {origin} to {target}. TravelMate currently generates "
            "verified itineraries for one destination at a time, so I have not created a misleading "
            "single-city route. Choose which city to plan first and I can prepare separate itineraries."
        )

    if detailed_intent == 'ITINERARY_MODIFICATION' and ps.get('destinationArea'):
        return (
            f"I have changed the active destination to {ps.get('destinationArea')} and kept the other "
            "validated trip preferences. The refreshed itinerary now uses that destination."
        )

    # 2. Weather inquiry (bounded regex to prevent 'hotel' matching 'hot')
    is_weather = bool(re.search(r'\b(?:rain|rains|rainy|raining|downpour|thunderstorm|weather|forecast|hot|temperature)\b', q))
    if is_weather and not is_explicit_planning:
        if ps.get('preferIndoor') or excluded_labels:
            return constrained_indoor_reply(ps.get('destinationArea') or 'your destination')
        return (
            "Check the Weather tool for the live Open-Meteo forecast. TravelMate's smart itinerary generator treats museums, malls and indoor food experiences "
            "as safer wet-weather choices, while beaches, gardens, hill viewpoints and outdoor adventure stops stay flexible when rain probability is high."
        )

    # 3. Flight search inquiry
    explicit_flight = re.search(r'\b(?:flights?|airfare|airline|airports?|fly\s+to)\b', q)
    airport_route = re.search(
        r'\b(?:kul|pen|bki|kch)\b\s*(?:to|[-–>])\s*\b(?:kul|pen|bki|kch)\b', q
    )
    if (detailed_intent == 'FLIGHT_ENQUIRY' or explicit_flight or airport_route) and not is_explicit_planning:
        return (
            "Use Home → Flights to search by airport code and date across Malaysian hubs (KUL, PEN, BKI, KCH, etc.). "
            "TravelMate can compare price, duration and stops, then attach a selected flight reference and cost to an itinerary. "
            "Check the search result’s source and fare terms before you rely on a price."
        )

    # 4. Hotel booking inquiry
    if re.search(r'\b(?:hotels?|rooms?|stay|accommodation|prebook)\b', q) and not is_explicit_planning:
        return (
            "Use Home → Hotels to search by destination and dates across Malaysia. Compare room prices and cancellation terms, "
            "and use the selected cost in your trip budget. Check your supplier confirmation before treating a room as reserved."
        )

    # 4c. Indoor alternative request
    if re.search(r'\b(?:replace\s+outdoor|indoor\s+only|indoor\s+activities|indoor\s+attractions|sheltered|rain\s+safe|wet\s+weather|indoor\s+alternatives)\b', q):
        dest_name = ps.get('destinationArea') or 'your destination'
        return constrained_indoor_reply(dest_name)

    # 5. General feature explanation inquiry
    if detailed_intent == 'FEATURE_EXPLANATION' or any(f in q for f in [
        'what can you do', 'what can travelmate do', 'how does travelmate work', 'explain features',
        'explain travelmate', 'what functions', 'itinerary generator work',
    ]):
        return (
            "TravelMate helps you discover places in Malaysia, build daily itineraries from destination, dates and interests, "
            "and compare estimated trip costs. You can also check weather, search flights and hotels, and use Smart Packing Checklist in a saved trip."
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

    geo = extract_geographic_entities(question)
    if conversational_question(str(question or '')):
        return 'I can’t verify an answer to that question right now. Your conversation is still here if you want to retry.'
    dest = geo.get('destination_area') or ps.get('destinationArea')
    dest_state = geo.get('destination_state') or ps.get('destinationState')
    planning_words = re.search(r'\b(?:plan|itinerary|trip|day|days|attractions|places|food|eat|visit)\b', q)
    if activity_request(q) or is_explicit_planning or planning_words or geo.get('destination_area') or (
        dest and (ps.get('tripDays') or detailed_intent in {
            'BUDGET_ADJUSTMENT', 'DURATION_ADJUSTMENT', 'TRAVELLER_COUNT_ADJUSTMENT', 'DATE_ADJUSTMENT',
        })
    ):
        if not dest:
            return 'Sure! Where in Malaysia would you like to explore?'
        days = ps.get('tripDays') or extract_duration(question)
        if not days:
            return f'How much time do you have in {dest}? I can suggest activities for a half day, a full day, or several days.'
        return _format_tailored_planning_fallback(
            dest, dest_state, days, ps.get('budgetLimit'), ps.get('travellerCount'),
            ps.get('startDate'), ps.get('endDate'), ps.get('interests') or [],
        )

    if context_lower:
        return (
            "I can’t answer that question right now. Your conversation is still here, and you can retry "
            "or ask about activities, your budget or weather guidance for the trip."
        )

    return (
        "I can help you plan destinations across all of Malaysia, build an itinerary, compare a budget, interpret weather, search flights/hotels, or improve an existing TravelMate trip. "
        "Try: ‘Plan a 3-day Kuala Lumpur trip under RM1000’ or ‘Plan a 4-day Langkawi holiday’ or ‘What should I change if it rains on Day 2?’"
    )


def generateChatbotResponse(question, context='', *, with_source=False, planning_state=None):
    from modules.fr11_chatbot_travel_assistant.nlp_extractor import car_rental_question

    global _provider_retry_at
    source = 'travelmate-assistant'
    if car_rental_question(str(question or '')):
        reply = _CAR_RENTAL_REPLY
    elif is_gemini_configured() and monotonic() >= _provider_retry_at:
        start_t = time.perf_counter()
        try:
            reply = _generate((context + '\n\n' if context else '') + 'Traveller: ' + str(question))
            source = 'gemini'
            logger.info("[FR11 Gemini] Provider text received: elapsed=%.2fs", time.perf_counter() - start_t)
        except Exception as exc:
            elapsed = time.perf_counter() - start_t
            category = _classify_provider_error(exc)
            if category in {'HTTP_429_RATE_LIMIT_EXHAUSTED', 'HTTP_503_SERVICE_UNAVAILABLE',
                            'HTTP_504_DEADLINE_EXCEEDED', 'CLIENT_TIMEOUT'}:
                _provider_retry_at = monotonic() + PROVIDER_COOLDOWN_SECONDS
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
