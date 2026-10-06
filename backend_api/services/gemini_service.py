import os
from google import genai

SYSTEM_PREFIX = (
    "You are TravelMate, a concise and practical Malaysia travel-planning assistant. "
    "Help with destinations, personalised itinerary ideas, budget planning, weather interpretation, "
    "flight/hotel planning and general travel questions. Use the traveller context when supplied. "
    "Never claim a booking or payment is confirmed unless the system context includes an actual reference."
)


def _fallback_mode():
    return os.getenv('FALLBACK_MODE', 'false').lower() in {'1', 'true', 'yes'}


def is_gemini_configured():
    return bool(os.getenv('GEMINI_API_KEY', '').strip())


def _generate(message):
    key = os.getenv('GEMINI_API_KEY', '').strip()
    if not key:
        raise RuntimeError('GEMINI_API_KEY is not configured')
    model = os.getenv('GEMINI_MODEL', 'gemini-3.7-flash').strip() or 'gemini-3.7-flash'
    client = genai.Client(api_key=key)
    interaction = client.interactions.create(
        model=model,
        input=SYSTEM_PREFIX + '\n\n' + message,
    )
    text = getattr(interaction, 'output_text', None)
    if not text:
        text = ''.join(
            getattr(output, 'text', '') or ''
            for output in (getattr(interaction, 'outputs', None) or [])
            if getattr(output, 'type', '') == 'text'
        )
    if not text:
        raise RuntimeError('Gemini returned an empty response')
    return text.strip()


def _local_assistant(question, context=''):
    """A useful local fallback so FR11 remains localnstrable without a paid/live key."""
    q = str(question or '').strip().lower()
    context_lower = str(context or '').lower()

    if any(word in q for word in ['budget', 'cheap', 'cost', 'rm ', 'save money', 'affordable']):
        return (
            "For a practical TravelMate budget, split the limit into transport, hotel, food and activities. "
            "Keep a 10–15% buffer. If the itinerary is over budget, compare a lower hotel tier, a cheaper flight time, "
            "group nearby attractions to reduce transport, and replace one premium activity with a free heritage, garden or beach stop. "
            "Open Trips → Budget to see the system's calculated total and alternatives."
        )

    if any(word in q for word in ['rain', 'weather', 'forecast', 'hot', 'temperature']):
        return (
            "Check the Weather tool for the live Open-Meteo forecast. TravelMate's smart itinerary generator treats museums, malls and indoor food experiences "
            "as safer wet-weather choices, while beaches, gardens, hill viewpoints and outdoor adventure stops stay flexible when rain probability is high."
        )

    if any(word in q for word in ['flight', 'airport', 'kul', 'pen', 'airline']):
        return (
            "Use Home → Flights to search by airport code and date. TravelMate can compare price, duration and stops, then attach a selected flight reference and cost to an itinerary. "
            "With a SerpApi key the results are live; in fallback mode the same selection and comparison flow remains usable."
        )

    if any(word in q for word in ['hotel', 'room', 'stay', 'accommodation', 'prebook']):
        return (
            "Use Home → Hotels to search by destination and dates. You can filter refundable offers, compare room prices, prebook an offer and complete a safe sandbox/local booking. "
            "The selected hotel cost can then be included in the itinerary budget."
        )

    if any(word in q for word in ['food', 'eat', 'hawker', 'restaurant']):
        return (
            "For Penang, a balanced food plan could include a George Town hawker breakfast, char koay teow or nasi kandar for lunch, cendol in the afternoon, and a local dinner near the day's final attraction. "
            "Grouping meals with nearby activities keeps transport cost lower."
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
        "I can help you plan destinations, build an itinerary, compare a budget, interpret weather, search flights/hotels, or improve an existing TravelMate trip. "
        "Try: ‘Plan a 3-day Penang trip under RM1200’ or ‘What should I change if it rains on Day 2?’"
    )


def generateChatbotResponse(question, context='', *, with_source=False):
    source = 'travelmate-assistant'
    if is_gemini_configured():
        try:
            reply = _generate((context + '\n\n' if context else '') + 'Traveller: ' + str(question))
            source = 'gemini'
        except Exception:
            if _fallback_mode():
                reply = _local_assistant(question, context)
            else:
                raise
    elif _fallback_mode():
        reply = _local_assistant(question, context)
    else:
        raise RuntimeError('GEMINI_API_KEY is not configured')
    return {'reply': reply, 'source': source} if with_source else reply


def generateFollowUpResponse(question, context='', *, with_source=False):
    return generateChatbotResponse(question, context, with_source=with_source)


def ask(message):
    return generateChatbotResponse(message)
