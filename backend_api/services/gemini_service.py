import os
from google import genai

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
    """A useful local fallback so FR11 remains demonstrable without a paid/live key across Malaysia."""
    q = str(question or '').strip().lower()
    context_lower = str(context or '').lower()

    # Foreign destinations boundary check
    foreign_keywords = ['singapore', 'tokyo', 'japan', 'bangkok', 'thailand', 'bali', 'indonesia', 'seoul', 'london', 'paris', 'phuket']
    if any(f in q for f in foreign_keywords) and not ('from ' in q and any(my in q for my in ['penang', 'kuala lumpur', 'kl', 'melaka', 'malaysia'])):
        return (
            "TravelMate is dedicated exclusively to travel planning within Malaysia. "
            "I cannot create travel plans or search attractions for foreign destinations, but I would be glad to help you "
            "plan an exciting trip to Kuala Lumpur, Penang, Langkawi, Melaka, Sabah, Sarawak, or anywhere across Malaysia!"
        )

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

    if any(word in q for word in ['flight', 'airport', 'kul', 'pen', 'bki', 'kch', 'airline']):
        return (
            "Use Home → Flights to search by airport code and date across Malaysian hubs (KUL, PEN, BKI, KCH, etc.). "
            "TravelMate can compare price, duration and stops, then attach a selected flight reference and cost to an itinerary. "
            "With a SerpApi key the results are live; in fallback mode the same selection and comparison flow remains usable."
        )

    if any(word in q for word in ['hotel', 'room', 'stay', 'accommodation', 'prebook']):
        return (
            "Use Home → Hotels to search by destination and dates across Malaysia. You can filter refundable offers, compare room prices, prebook an offer and complete a safe sandbox/local booking. "
            "The selected hotel cost can then be included in the itinerary budget."
        )

    # Destination-specific food and planning advice
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
