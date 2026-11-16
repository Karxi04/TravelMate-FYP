"""Verified Traveller capabilities. Interpretation selects a tool, never a record or write."""
import re

from .nlp_extractor import clean_text

# Handler names describe actual read paths; no HTTP GET with reconciliation/cache effects.
CAPABILITIES = {
    'preferences': ('FR2 saved/effective preferences', 'preferences',
        'Preferences records your interests and travel style. Explicit chat preferences apply to this conversation; they do not change your saved questionnaire.'),
    'recommendations': ('FR4 owned saved snapshots', 'recommendations',
        'For You uses the existing 60% content, 30% collaborative and 10% popularity weighting. Available candidate metadata and your recorded preferences limit the matches; a recommendation is not verified availability.'),
    'saved': ('FR3 owned favourites', 'saved',
        'Open Saved Places to see destinations you saved. Saving a place does not book it or add a paid service.'),
    'itinerary': ('FR5 owned trip preview; FR11 confirmed draft/history', 'trips',
        'A trip is your saved itinerary, dates, activities and budget. A tourism package is an Operator offer with its own inclusions, departures and authoritative price. Ask to adjust a saved trip for a preview; changes and restorations require confirmation.'),
    'budget': ('FR5 pure budget/recorded costs; Batch B', 'budget',
        'Trip Budget separates modelled costs, recorded spending and linked payments. Unknown prices are unavailable, not free. A trip budget is a group total; package per-person quotes are separate.'),
    'alternatives': ('FR5 compatible replacement preview; Batch B', 'alternatives',
        'Lower-Cost Alternatives compares compatible recorded activity costs. It shows a preview and requires confirmation before replacement; missing prices cannot establish a saving.'),
    'what_if': ('Batch B pure budget scenario', 'what_if',
        'I can compare a total budget or traveller count without changing your trip. Selected commercial offers are not repriced for a different group.'),
    'selected_travel': ('FR5 owned selections; owned linked FR8 records', 'selection',
        'Trip Details shows selected flights and hotels. A selection, a Stripe payment and a supplier-confirmed booking are separate states. Chat reads saved evidence without refreshing quotes or contacting suppliers.'),
    'orders': ('FR9 saved owner-scoped payment projection; no reconciliation', 'orders',
        'Payment, order status and supplier confirmation are separate. A Stripe payment alone does not establish a hotel reservation, flight ticket or package arrangement. Open Payment History for the recorded details and supported reconciliation controls; chat cannot pay, cancel or refund.'),
    'packing': ('Existing Smart Packing selector/checklist', None,
        'Smart Packing uses trip dates, activities and available weather data to suggest checklist items. General advice is not a live forecast. For Malaysian domestic travel bring MyKad where applicable; international travel needs a passport. Open your checklist to review suggestions; chat has not edited it.'),
    'weather': ('Existing Weather screen', None,
        'Open Weather for available forecast dates. General rain advice is not a live forecast; I cannot infer rain on an unverified trip date.'),
    'flights': ('FR7 Malaysian airports/search; explicit app search', None,
        'Search flights from Home → Flights, or Trip Details → Flights to keep the trip context. Choose supported Malaysian airports, dates and passengers. Search and More Results can contact the provider; chat has not started a search or selected a flight.'),
    'hotels': ('FR8 LiteAPI sandbox search/attachment; explicit app controls', None,
        'Open Hotels from Trip Details to keep that trip, or Home to browse before choosing an owned compatible trip. Select a valid room offer and review the budget attachment. Selection or Stripe payment alone is not supplier reservation confirmation.'),
    'packages': ('FR11 published package catalogue; campaigns_v1 pricing', None,
        'I can find and compare published tourism packages and their recorded inclusions. Package pricing comes from the existing authoritative quote and approved campaign rules, not generated text. Purchase remains in the app checkout controls.'),
    'promotions': ('Existing public campaigns and authoritative package quote', None,
        'Applicable approved active campaigns are evaluated by the package pricing service. Published terms, dates, party eligibility and package association matter. I cannot invent a discount or guarantee a previously displayed offer is still valid.'),
    'help': ('Traveller navigation only', None,
        'TravelMate supports Malaysian destination discovery, personalised recommendations, saved places, trip planning and history, budgets, weather, Smart Packing, flights, hotels, published packages and payment history. I can explain saved information and preview supported itinerary changes. Booking, payment and permanent changes require the app’s explicit controls.'),
}
READ_TOOLS = {name: entry[1] for name, entry in CAPABILITIES.items() if entry[1]}


def normalize_message(message):
    # Correct domain tokens only; never fuzzy-match destination names, IDs, dates or money.
    aliases = {'prefrences': 'preferences', 'preferances': 'preferences', 'preferrences': 'preferences',
               'budjet': 'budget', 'buget': 'budget', 'itinary': 'itinerary', 'itenary': 'itinerary',
               'recomendations': 'recommendations', 'recomend': 'recommend', 'packin': 'packing',
               'pls': 'please', 'plz': 'please'}
    return re.sub(r'\b(?:' + '|'.join(aliases) + r')\b',
                  lambda m: aliases[m[0].lower()], message, flags=re.I)


def personal_intent(q):
    """Small subject grammar for natural personal reads, not new itinerary requirements."""
    if re.search(r'\b(?:what|which|how|where|why|show|explain|tell|did|have|is|are|can)\b', q):
        if re.search(r'\b(?:kind|type) of traveller am i\b', q):
            return 'preferences'
        if re.search(r'\bwhy do you think i prefer\b', q):
            return 'preferences'
        if re.search(r'\bwhere am i staying\b|\bdid i .*select .*hotel\b|\bwhich flight did i (?:choose|select)\b', q):
            return 'selection'
        if re.search(r'\bmy\b.*\b(?:saved trips|saved itineraries)\b', q) and not re.search(r'\b(?:edit|change|restore|history|budget)\b', q):
            return 'trips'
    return None


def help_response(name, state):
    reply = CAPABILITIES[name][2]
    actions = {'preferences': 'preferences', 'recommendations': 'preferences', 'saved': 'saved',
               'orders': 'payments', 'packing': 'packing'}
    action = actions.get(name, 'trips' if name in {'itinerary', 'budget', 'alternatives', 'flights', 'hotels', 'selected_travel'} else None)
    item = {'reply': reply, 'readOnlyAnswer': True}
    if action:
        item['assistantActions'] = [{'kind': action}]
    if name == 'weather':
        area = (state.get('adjustment') or {}).get('tripContext', {}).get('destinationArea') or state.get('destinationArea') or ''
        item['weatherAction'] = {'destination': area}
    return item


def resolve_help(message, state):
    q = clean_text(message)
    explaining = bool(re.search(r'\b(?:how (?:does|do|can)|what (?:is|are|does|can)|can i|difference|where can|where do)\b', q))
    if re.search(r'\b(?:packing|checklist|pack|umbrella|passport|mykad)\b', q) and not re.search(r'\b(?:package|remove|delete|check off)\b', q):
        return help_response('packing', state)
    if re.search(r'\bpayment\b', q) and re.search(r'\b(?:mean|supplier|reservation|confirmation)\b', q) and not re.search(r'\b(?:my|i|this order)\b', q):
        return help_response('orders', state)
    if not explaining:
        return None
    if 'difference' in q and 'trip' in q and 'package' in q:
        return help_response('itinerary', state)
    if re.search(r'\b(?:recommendation|recommendations)\b', q) and 'work' in q:
        return help_response('recommendations', state)
    if re.search(r'\b(?:what can (?:travelmate|you) do|your capabilities|travelmate work)\b', q):
        return help_response('help', state)
    for pattern, name in ((r'\bsaved places\b', 'saved'), (r'\b(?:search|find) flights?\b', 'flights'),
                          (r'\bchange (?:my |the )?(?:hotel|flight)\b', 'selected_travel')):
        if re.search(pattern, q):
            return help_response(name, state)
    return None
