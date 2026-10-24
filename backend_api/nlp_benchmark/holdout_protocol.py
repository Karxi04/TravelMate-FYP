"""
TravelMate Independent NLP Evaluation Holdout Protocol
Standardized evaluation protocol for assessing generalization across 50 previously
unseen Malaysian travel utterances. Governed by double-blind human annotation standards.

STATUS: PENDING_INDEPENDENT_HUMAN_ANNOTATION
In accordance with FYP academic integrity guidelines, holdout labels must be
independently annotated by two human evaluators with formal adjudication.
No AI-generated or self-authored pseudo-labels may be substituted as ground truth.
"""

HOLDOUT_METADATA = {
    "protocol_version": "1.0.0",
    "status": "PENDING_INDEPENDENT_HUMAN_ANNOTATION",
    "dataset_size": 50,
    "creation_date": "2026-10-24",
    "git_commit_baseline": "51708d1f20e48cc7a574afaba269f3e9f25774c4",
    "geographic_scope": "Malaysia Nationwide (13 States, 3 Federal Territories)",
    "evaluation_rules": {
        "production_tuning_prohibited": True,
        "human_annotators_required": 2,
        "lead_adjudicator_required": 1,
        "agreement_metric_categorical": "Cohen's Kappa (kappa >= 0.80 required for release)",
        "agreement_metric_set_valued": "Macro-averaged F1 overlap",
    },
    "category_distribution": {
        "Negation & Exclusions (Broad vs Specific)": 10,
        "Multi-Turn Adjustments & Corrections": 10,
        "Rain-Safe & Weather Adaptations": 8,
        "Localized Phrases & Locality Aliases": 8,
        "Conflicting Constraints": 6,
        "Ambiguous Queries": 4,
        "Unsupported Road-Trip Requests": 4,
    },
}

HOLDOUT_ANNOTATION_GUIDELINES = """
================================================================================
TRAVELMATE NLP HOLDOUT ANNOTATION GUIDELINES FOR HUMAN EVALUATORS
================================================================================

1. INTENT CLASSIFICATION (Choose exactly one primary intent):
   - ITINERARY_PLANNING: Request to construct or schedule a multi-step travel plan.
   - ITINERARY_MODIFICATION: Explicit request to replace destination or modify trip structure.
   - BUDGET_ENQUIRY: Informational question about general travel costs or budgeting advice.
   - BUDGET_ADJUSTMENT: Request to update, increase, or reduce a travel budget figure.
   - TRAVELLER_COUNT_ADJUSTMENT: Updating party size or number of participants.
   - DURATION_ADJUSTMENT: Modifying trip duration (shortening or extending days).
   - DATE_ADJUSTMENT: Shifting or rescheduling travel dates.
   - INTEREST_MODIFICATION: Modifying travel activity preferences or exclusions.
   - INDOOR_ALTERNATIVE: Explicit request for rain-safe, indoor, or sheltered options.
   - WEATHER_ENQUIRY: Informational inquiry about weather forecast, rain risk, temperature.
   - HOTEL_ENQUIRY: Accommodation discovery, room types, or prebook guidance.
   - FLIGHT_ENQUIRY: Airline flights, fares, or airport routes.
   - CAR_RENTAL_ENQUIRY: Vehicle rentals, categories, pickup locations.
   - FEATURE_EXPLANATION: Inquiries about TravelMate capabilities and operation.
   - DESTINATION_ENQUIRY: Informational query about specific attractions or localities.
   - DESTINATION_RECOMMENDATION: Open-ended discovery (where should I go?).
   - FOREIGN_UNSUPPORTED: Travel outside Malaysia (Singapore, Tokyo, Bali, etc.).
   - GENERAL_CONVERSATION: Greetings, gratitude, chit-chat.

2. SLOT & ENTITY EXTRACTION:
   - destinationArea: Specific city or tourism locality (e.g., George Town, Melaka City, Ipoh).
   - destinationState: Federal state (e.g., Penang, Melaka, Perak, Sabah, Sarawak).
   - tripDays: Integer count of travel days.
   - budgetLimit: Numeric Malaysian Ringgit target budget (float).
   - travellerCount: Integer party size.
   - interests: Broad positive travel categories:
       ['Food', 'Culture', 'Nature', 'Beach', 'Relaxation', 'Shopping', 'Family', 'Photography']
   - excludedInterests: Broad negative travel categories (same 8 categories).
   - excludedActivityTypes: Specific narrow venue/activity exclusions:
       ['Museum', 'Shopping Mall']
   - preferIndoor: True if query explicitly demands indoor/sheltered options; False/None otherwise.
   - isForeign: True if primary destination is outside Malaysia.

3. DISAGREEMENT & ADJUDICATION PROCEDURE:
   - Annotator 1 and Annotator 2 independently annotate all 50 items.
   - Calculate Cohen's Kappa for Intent and Slot agreement.
   - Disagreements are submitted to Lead Adjudicator for binding arbitration with documented rationale.
"""

HOLDOUT_UTTERANCES = [
    # -------------------------------------------------------------
    # Category A: Negation & Exclusions (Broad vs Specific) - 10 items
    # -------------------------------------------------------------
    {"id": "holdout_001", "text": "Plan 4 days in Penang for 3 people with RM1800, but do not want museums.", "category": "Negation & Exclusions"},
    {"id": "holdout_002", "text": "We want to explore Kuala Lumpur for 3 days, avoid all shopping.", "category": "Negation & Exclusions"},
    {"id": "holdout_003", "text": "Plan 2 days in Melaka with RM600, skip theme parks and waterparks.", "category": "Negation & Exclusions"},
    {"id": "holdout_004", "text": "Can you build a Langkawi trip without any beach activities or boat tours?", "category": "Negation & Exclusions"},
    {"id": "holdout_005", "text": "I want to visit George Town food stalls but exclude spicy seafood.", "category": "Negation & Exclusions"},
    {"id": "holdout_006", "text": "Plan 3 days in Kota Kinabalu, do not include hiking or strenuous mountain climbs.", "category": "Negation & Exclusions"},
    {"id": "holdout_007", "text": "We love cultural heritage in Kuching but don't want indoor galleries.", "category": "Negation & Exclusions"},
    {"id": "holdout_008", "text": "A 2-day relaxing weekend in Ipoh, no shopping malls please.", "category": "Negation & Exclusions"},
    {"id": "holdout_009", "text": "Plan 3 days in Johor Bahru for 4 adults without noisy bars or night markets.", "category": "Negation & Exclusions"},
    {"id": "holdout_010", "text": "Create a Cameron Highlands tour avoiding crowded strawberry farms.", "category": "Negation & Exclusions"},

    # -------------------------------------------------------------
    # Category B: Multi-Turn Adjustments & Corrections - 10 items
    # -------------------------------------------------------------
    {"id": "holdout_011", "text": "Actually change our destination from Langkawi to Kota Kinabalu.", "category": "Multi-Turn Adjustments"},
    {"id": "holdout_012", "text": "Switch destination to Melaka instead of George Town.", "category": "Multi-Turn Adjustments"},
    {"id": "holdout_013", "text": "Update our budget to RM1500 instead of RM1000.", "category": "Multi-Turn Adjustments"},
    {"id": "holdout_014", "text": "Make the trip cheaper, reduce our budget to RM750.", "category": "Multi-Turn Adjustments"},
    {"id": "holdout_015", "text": "Now there are 5 people traveling with us.", "category": "Multi-Turn Adjustments"},
    {"id": "holdout_016", "text": "Change party size to solo traveler.", "category": "Multi-Turn Adjustments"},
    {"id": "holdout_017", "text": "Actually make it 5 days instead of 3 days.", "category": "Multi-Turn Adjustments"},
    {"id": "holdout_018", "text": "Shorten our trip to just 2 days.", "category": "Multi-Turn Adjustments"},
    {"id": "holdout_019", "text": "Move our travel dates to next weekend 14 to 16 November.", "category": "Multi-Turn Adjustments"},
    {"id": "holdout_020", "text": "Keep the same Penang plan but add one more day.", "category": "Multi-Turn Adjustments"},

    # -------------------------------------------------------------
    # Category C: Rain-Safe & Weather Adaptations - 8 items
    # -------------------------------------------------------------
    {"id": "holdout_021", "text": "It is pouring rain in George Town right now, give me indoor rain-safe places.", "category": "Rain-Safe & Weather"},
    {"id": "holdout_022", "text": "Heavy thunderstorm expected in KLCC this afternoon, what sheltered attractions can we visit?", "category": "Rain-Safe & Weather"},
    {"id": "holdout_023", "text": "Replace outdoor parks with indoor museum alternatives due to bad weather.", "category": "Rain-Safe & Weather"},
    {"id": "holdout_024", "text": "Is it safe to visit Bako National Park during the monsoon season?", "category": "Rain-Safe & Weather"},
    {"id": "holdout_025", "text": "Find indoor air-conditioned activities in Melaka for a hot humid afternoon.", "category": "Rain-Safe & Weather"},
    {"id": "holdout_026", "text": "What are rain-safe cultural activities in Kuching?", "category": "Rain-Safe & Weather"},
    {"id": "holdout_027", "text": "Will it rain in Kota Kinabalu tomorrow morning?", "category": "Rain-Safe & Weather"},
    {"id": "holdout_028", "text": "Any sheltered hawker centres in Penang if it starts raining?", "category": "Rain-Safe & Weather"},

    # -------------------------------------------------------------
    # Category D: Localized Phrases & Locality Aliases - 8 items
    # -------------------------------------------------------------
    {"id": "holdout_029", "text": "Plan 2 days in JB for food and cafe hopping with RM600 for 2 pax.", "category": "Localized Phrases & Aliases"},
    {"id": "holdout_030", "text": "What to do in KK for a weekend getaway?", "category": "Localized Phrases & Aliases"},
    {"id": "holdout_031", "text": "Best street food near Petaling Street and Bukit Bintang in KL.", "category": "Localized Phrases & Aliases"},
    {"id": "holdout_032", "text": "Weekend trip to PD with RM500 for beach relaxation.", "category": "Localized Phrases & Aliases"},
    {"id": "holdout_033", "text": "Plan 3 days in Cameron with tea plantation visits.", "category": "Localized Phrases & Aliases"},
    {"id": "holdout_034", "text": "Things to see around Georgetown heritage core.", "category": "Localized Phrases & Aliases"},
    {"id": "holdout_035", "text": "Tour around Taiping lake gardens and Maxwell Hill.", "category": "Localized Phrases & Aliases"},
    {"id": "holdout_036", "text": "Day trip from KL to Putrajaya landmarks for 2 adults.", "category": "Localized Phrases & Aliases"},

    # -------------------------------------------------------------
    # Category E: Conflicting Constraints - 6 items
    # -------------------------------------------------------------
    {"id": "holdout_037", "text": "Find a luxury 5-star resort in Langkawi for a total budget of RM150.", "category": "Conflicting Constraints"},
    {"id": "holdout_038", "text": "I want to relax on a quiet secluded natural beach in central Bukit Bintang.", "category": "Conflicting Constraints"},
    {"id": "holdout_039", "text": "Plan a 1-day trip to visit both Penang Hill and Mount Kinabalu.", "category": "Conflicting Constraints"},
    {"id": "holdout_040", "text": "We have 10 people and our entire 3-day budget for all 10 is RM200.", "category": "Conflicting Constraints"},
    {"id": "holdout_041", "text": "Show me outdoor hiking trails with zero sun exposure and guaranteed cold weather in Melaka.", "category": "Conflicting Constraints"},
    {"id": "holdout_042", "text": "Book a flight from Penang to Langkawi for 0 ringgit.", "category": "Conflicting Constraints"},

    # -------------------------------------------------------------
    # Category F: Ambiguous Queries - 4 items
    # -------------------------------------------------------------
    {"id": "holdout_043", "text": "Something fun for the kids that is not too tiring.", "category": "Ambiguous Queries"},
    {"id": "holdout_044", "text": "Where is the best place to go next month?", "category": "Ambiguous Queries"},
    {"id": "holdout_045", "text": "How much does a normal holiday cost in Malaysia?", "category": "Ambiguous Queries"},
    {"id": "holdout_046", "text": "Recommend good places.", "category": "Ambiguous Queries"},

    # -------------------------------------------------------------
    # Category G: Unsupported Road-Trip Requests - 4 items
    # -------------------------------------------------------------
    {"id": "holdout_047", "text": "Drive from George Town Penang to Kota Kinabalu Sabah over the weekend.", "category": "Unsupported Road Trips"},
    {"id": "holdout_048", "text": "Can you arrange a self-drive rental car road trip from Kuching to Kuala Lumpur?", "category": "Unsupported Road Trips"},
    {"id": "holdout_049", "text": "Plan a road trip covering Penang, Langkawi, Melaka, and Kota Kinabalu in 2 days by car.", "category": "Unsupported Road Trips"},
    {"id": "holdout_050", "text": "Road trip from Johor Bahru to Labuan by car.", "category": "Unsupported Road Trips"},
]

HOLDOUT_ANNOTATION_TEMPLATE = {
    "sample_id": None,
    "annotator_id": None,
    "annotation_timestamp": None,
    "intent": None,
    "entities": {
        "destinationArea": None,
        "destinationState": None,
        "tripDays": None,
        "budgetLimit": None,
        "travellerCount": None,
        "interests": [],
        "excludedInterests": [],
        "excludedActivityTypes": [],
        "preferIndoor": None,
        "isForeign": False,
    },
    "annotator_rationale": None,
    "adjudication_status": "PENDING_ARBITRATION",
}

# Standardized aliases
HOLDOUT_DATASET = HOLDOUT_UTTERANCES
HOLDOUT_EVALUATION_PROTOCOL = HOLDOUT_METADATA

