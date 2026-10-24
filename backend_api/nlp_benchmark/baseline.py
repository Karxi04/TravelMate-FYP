"""
Baseline NLP Extractor (Reference Naive Model)
Represents standard keyword/regex heuristic chatbots without context-window
negation handling, fine-grained state tracking, or Malaysian geographic normalization.
Used for academic comparative evaluation in TravelMate FYP Chapter 5.
"""
import re


class BaselineNLPExtractor:
    """A naive keyword-based baseline model for comparative benchmarking."""

    @staticmethod
    def classify_intent(text):
        q = str(text or "").lower()
        if "weather" in q or "rain" in q:
            return "WEATHER_ENQUIRY"
        if "hotel" in q or "room" in q:
            return "HOTEL_ENQUIRY"
        if "flight" in q or "airline" in q:
            return "FLIGHT_ENQUIRY"
        if "car" in q and "rent" in q:
            return "CAR_RENTAL_ENQUIRY"
        if "plan" in q or "itinerary" in q:
            return "ITINERARY_PLANNING"
        if "what" in q and ("do" in q or "recommend" in q or "place" in q):
            return "DESTINATION_ENQUIRY"
        if "hello" in q or "thank" in q or "bye" in q:
            return "GENERAL_CONVERSATION"
        if "budget" in q:
            return "BUDGET_ENQUIRY"
        return "GENERAL_CONVERSATION"

    @staticmethod
    def extract_entities(text):
        q = str(text or "").lower()
        res = {
            "destinationArea": None,
            "destinationState": None,
            "tripDays": None,
            "budgetLimit": None,
            "travellerCount": None,
            "interests": [],
            "excludedInterests": [],
            "preferIndoor": False,
            "isForeign": False,
        }

        # Naive destination matching (first match only, no synonym normalization)
        cities = {
            "penang": ("Penang", "Penang"),
            "kuala lumpur": ("Kuala Lumpur", "Kuala Lumpur"),
            "melaka": ("Melaka", "Melaka"),
            "langkawi": ("Langkawi", "Kedah"),
            "kota kinabalu": ("Kota Kinabalu", "Sabah"),
            "kuching": ("Kuching", "Sarawak"),
            "ipoh": ("Ipoh", "Perak"),
            "johor bahru": ("Johor Bahru", "Johor"),
        }
        for city, (area, state) in cities.items():
            if city in q:
                res["destinationArea"] = area
                res["destinationState"] = state
                break

        # Naive duration matching
        m_dur = re.search(r"(\d+)\s*days?", q)
        if m_dur:
            res["tripDays"] = int(m_dur.group(1))

        # Naive budget matching
        m_bud = re.search(r"rm\s*(\d+)", q)
        if m_bud:
            res["budgetLimit"] = float(m_bud.group(1))

        # Naive traveller count
        m_trav = re.search(r"(\d+)\s*(?:people|pax|travellers?)", q)
        if m_trav:
            res["travellerCount"] = int(m_trav.group(1))

        # Naive interests (NO negation handling: 'do not include museums' still adds Culture!)
        if "food" in q or "eat" in q:
            res["interests"].append("Food")
        if "museum" in q or "heritage" in q or "culture" in q:
            res["interests"].append("Culture")
        if "nature" in q or "beach" in q:
            res["interests"].append("Nature")
        if "shopping" in q or "mall" in q:
            res["interests"].append("Shopping")

        # Baseline has no concept of excludedInterests, preferIndoor, or foreign boundaries
        return res
