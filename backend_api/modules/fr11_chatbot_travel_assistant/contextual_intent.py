"""Bounded conversation references and advisory intent, never persistence authority."""
import json
import math
import re

from sequence_contract.domain_functions import _distance_km
from services.activity_pricing import activity_pricing
from services.recommendation_taxonomy import candidate_concepts, concepts_for, display_concepts
from .nlp_extractor import (clean_text, extract_itinerary_day, extract_activity_position,
                            extract_geographic_entities, extract_interests, itinerary_view_request,
                            extract_budget, extract_travellers, conversational_question, classify_detailed_intent,
                            find_matching_catalog_destinations)

INTENTS = {'view_trip', 'edit_day', 'edit_activity', 'resume', 'weather', 'reference', 'compare', 'clarify'}
INTERESTS = {'Food', 'Culture', 'Nature', 'Adventure', 'Relaxation', 'Photography', 'Family', 'Shopping', 'History'}
SCHEMA = {'intent': sorted(INTENTS), 'confidence': 'number 0..1; use clarify below 0.85',
          'day': 'optional integer 1..14', 'activityIndex': 'optional integer 1..20',
          'resultIndices': 'optional one or two displayed indices, starting at 1',
          'interests': 'optional list from ' + ', '.join(sorted(INTERESTS)),
          'operation': 'optional replace/add/remove/relax'}


def redact(value, limit=300):
    text = str(value or '')
    text = re.sub(r'\b[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}\b|\b(?:sk|pk)_(?:live|test)_\w+|\beyJ[\w.-]+', '[redacted]', text)
    text = re.sub(r'https?://\S+|\bBearer\s+\S+|\b(?:pi|cs|pm|tok|cus)_[\w-]+', '[redacted]', text, flags=re.I)
    text = re.sub(r'\b[A-Za-z0-9_-]{24,}\b', '[redacted]', text)
    text = re.sub(r'(?<!\d)(?:\d[ -]?){10,19}(?!\d)', '[redacted]', text)
    return text[:limit]


def _sets(item):
    return {kind: [r for r in item.get(field, []) if isinstance(r, dict)][:5]
            for kind, field in (('place', 'placeSuggestions'), ('package', 'packages'))
            if isinstance(item.get(field), list) and item[field]}


def result_id(row, kind):
    return str(row.get('destinationId' if kind == 'place' else 'packageId') or row.get('place_id') or row.get('id') or '')


def last_results(messages, state=None):
    pointer = ((state or {}).get('resultContext') or {}).get('messageId')
    pointed = [m for m in messages if isinstance(m, dict) and m.get('id') == pointer] if pointer else []
    for item in reversed(pointed or messages[-12:]):
        if isinstance(item, dict) and _sets(item):
            sets = _sets(item)
            if len(sets) != 1:
                return None, [], item.get('id')
            kind, rows = next(iter(sets.items()))
            return kind, rows, item.get('id')
    return None, [], None


def remember_results(state, item):
    sets = _sets(item)
    if sets:
        state['resultContext'] = {'messageId': item.get('id'), 'kinds': list(sets)}
        focus = state.get('selectedResult') or {}
        if not any(kind == focus.get('kind') and result_id(row, kind) == focus.get('id') for kind, rows in sets.items() for row in rows):
            state.pop('selectedResult', None)


def decorate_reply(item, state):
    message = item.get('message') or ''
    geo = extract_geographic_entities(message)
    if not geo.get('is_foreign') and re.search(r'\b(?:weather|rain|rains|raining|rainy|forecast)\b', clean_text(message)):
        area = geo.get('destination_area') or ((state.get('adjustment') or {}).get('tripContext') or {}).get('destinationArea') or state.get('destinationArea')
        item.setdefault('weatherAction', {'destination': area or ''})


def prompt_context(state, messages):
    adjustment = state.get('adjustment') or {}
    fields = ('destinationArea', 'destinationState', 'startDate', 'endDate', 'tripDays', 'budgetLimit',
              'travellerCount', 'interests', 'excludedInterests', 'preferIndoor', 'travelPace', 'guidedQuestion')
    relevant = {**state, **{key: value for key, value in (adjustment.get('tripContext') or {}).items() if key in fields}}
    context = {}
    for key in fields:
        value = relevant.get(key)
        if key in {'interests', 'excludedInterests'} and isinstance(value, list):
            context[key] = [redact(v, 80) for v in value[:8] if isinstance(v, str)]
        elif isinstance(value, str):
            context[key] = redact(value, 100)
        elif type(value) in (int, float, bool) and math.isfinite(value):
            context[key] = value
    context['selectedDay'] = adjustment.get('pendingDay') or adjustment.get('viewDay')
    context['pendingActivity'] = adjustment.get('pendingActivity')
    context['pendingOperation'] = adjustment.get('pendingOperation')
    context['hasUnsavedDraft'] = bool(state.get('activePlan'))
    plan = state.get('activePlan') or next((m.get('tripPlan') for m in reversed(messages[-8:])
                                          if isinstance(m, dict) and isinstance(m.get('tripPlan'), dict)), {})
    context['activityChoices'] = [{'index': i, 'name': redact(a.get('activityName'), 90)}
        for i, a in enumerate([a for a in (plan.get('activities') or []) if isinstance(a, dict)
                              and str(a.get('dayNo')) == str(context['selectedDay'])][:5], 1)]
    filters = state.get('packageSearch') or {}
    context['packageSearch'] = {k: filters[k] for k in ('destination', 'budgetMax', 'budgetBasis')
                                if type(filters.get(k)) in (str, int, float)}
    participants = filters.get('participants') or {}
    context['packageSearch']['participants'] = {key: participants[key] for key in ('adults', 'children')
        if isinstance(participants, dict) and type(participants.get(key)) is int and 0 <= participants[key] <= 20}
    kind, rows, _ = last_results(messages, state)
    context['displayedResults'] = [{'index': i, 'kind': kind, 'name': redact(r.get('title') or r.get('name'), 100),
                                   'category': redact(r.get('category'), 60),
                                   'area': redact(r.get('city') or r.get('destination') or r.get('state'), 80)} for i, r in enumerate(rows, 1)]
    context['recentTurns'] = [{'user': redact(m.get('message'), 200), 'assistant': redact(m.get('reply'), 220)}
                              for m in messages[-4:] if isinstance(m, dict)]
    return redact(json.dumps(context, ensure_ascii=True, default=str), 4200)


def validate_interpretation(value, state, rows):
    if not isinstance(value, dict) or set(value) - set(SCHEMA):
        return None
    confidence = value.get('confidence')
    if type(confidence) not in (int, float) or not .85 <= confidence <= 1:
        return None
    intent = value.get('intent')
    if not isinstance(intent, str) or intent not in INTENTS:
        return None
    for key, maximum in (('day', 14), ('activityIndex', 20)):
        if key in value and (type(value[key]) is not int or not 1 <= value[key] <= maximum):
            return None
    interests = value.get('interests', [])
    if not isinstance(interests, list) or len(interests) > 3 or any(not isinstance(v, str) or v not in INTERESTS for v in interests):
        return None
    indices = value.get('resultIndices', [])
    if not isinstance(indices, list) or not 0 <= len(indices) <= 2 or any(type(i) is not int or not 1 <= i <= len(rows) for i in indices):
        return None
    if len(set(indices)) != len(indices):
        return None
    if not isinstance(value.get('operation', 'replace'), str) or value.get('operation', 'replace') not in {'replace', 'add', 'remove', 'relax'}:
        return None
    active_trip = (state.get('adjustment') or {}).get('tripId')
    if intent == 'view_trip' and not (active_trip or (state.get('activePlan') and not state.get('dateClarification'))):
        return None
    if intent in {'edit_day', 'edit_activity'} and not active_trip:
        return None
    if intent == 'resume' and not (active_trip or state.get('guidedQuestion') or rows):
        return None
    if intent in {'edit_day', 'edit_activity'} and not (value.get('day') or (state.get('adjustment') or {}).get('pendingDay')):
        return None
    if intent == 'edit_activity' and not value.get('activityIndex'):
        return None
    if (intent == 'edit_day' and value.get('operation') == 'remove') or (intent == 'edit_activity' and value.get('operation') == 'relax'):
        return None
    if intent in {'reference', 'compare'} and len(indices) != (2 if intent == 'compare' else 1):
        return None
    return value


def _price(row, kind):
    if kind == 'package':
        quote = row.get('chatQuote') or {}
        amount = quote.get('finalPayable')
        if type(amount) in (int, float) and math.isfinite(amount) and amount >= 0:
            prefix = 'Reference party total' if (row.get('quoteContext') or {}).get('isReference', True) else 'Last displayed party total'
            return f'{prefix}: MYR {amount:.2f}; not a booking or a guarantee of current availability.'
        return 'Verified package pricing is unavailable; open the package details for a current quote.'
    pricing = activity_pricing(row, 1)
    if pricing['pricingIssues'] or row.get('currency', 'MYR') != 'MYR':
        return 'Verified activity pricing is unavailable for this place.'
    basis = pricing['pricingUnit'].replace('_', ' ')
    label = 'Recorded ticket price' if pricing['costProvenance'] == 'verified_ticket' else 'Recorded planning estimate'
    return f'{label}: MYR {pricing["effectiveCost"]:.2f} ({basis}), not a live quote.'


def _focused(state, messages, kind, rows):
    selected = state.get('selectedResult') or {}
    return next((r for r in rows if kind == selected.get('kind') and result_id(r, kind) == selected.get('id')), rows[0] if len(rows) == 1 else None)


def _known_distance(a, b):
    for row in (a, b):
        coordinates = row.get('gps_coordinates') or row.get('gpsCoordinates') or {}
        try:
            for key, bound in (('latitude', 90), ('longitude', 180)):
                value = float(coordinates.get(key))
                if isinstance(coordinates.get(key), bool) or not math.isfinite(value) or abs(value) > bound:
                    return None
        except (TypeError, ValueError, AttributeError):
            return None
    return _distance_km(a, b)


def _reference_reply(indices, kind, rows, state, compare=False):
    if not kind or not indices or any(not 1 <= i <= len(rows) for i in indices):
        return {'reply': 'Which result do you mean? Please use its displayed name or number.'}
    chosen = [rows[i - 1] for i in indices]
    if not compare:
        state['selectedResult'] = {'kind': kind, 'id': result_id(chosen[0], kind)}
        if state.get('rejectedResults'):
            state['rejectedResults'] = [entry for entry in state['rejectedResults']
                                       if entry != state['selectedResult']]
    lines = [f'{r.get("title") or r.get("name") or "Selected result"}: {_price(r, kind)}' for r in chosen]
    if compare:
        lines = [line + (f' Category: {row["category"]}.' if row.get('category') else '')
                 + (f' Location: {row["city"]}.' if row.get('city') else '') for line, row in zip(lines, chosen)]
    return {'reply': '\n'.join(lines)}


def resolve_turn(message, state, messages, *, interpret=None, lookup=None):
    """Return an existing-handler command or grounded reply; model output is never a write."""
    q = clean_text(message)
    adjustment = state.get('adjustment') or {}
    kind, rows, _ = last_results(messages, state)
    focus = _focused(state, messages, kind, rows)
    geo = extract_geographic_entities(message)
    if geo.get('is_foreign') or geo.get('is_multi_destination') or itinerary_view_request(message):
        return None
    named = [i for i, row in enumerate(rows, 1) if len(clean_text(row.get('title') or row.get('name'))) > 3
             and clean_text(row.get('title') or row.get('name')) in q]
    if len(named) == 1:
        state['selectedResult'] = {'kind': kind, 'id': result_id(rows[named[0] - 1], kind)}
        focus = rows[named[0] - 1]
    if focus and kind == 'place' and geo.get('destination_area') and not find_matching_catalog_destinations(
            geo['destination_area'], geo.get('destination_state'), [focus]):
        focus = None
    if re.fullmatch(r'(?:cancel|stop)(?: the)?(?: adjustment| changes| editing)?|never mind|nvm|leave it unchanged', q):
        return None
    explanation = adjustment.get('pendingExplanation') or {}
    if explanation and not re.search(r'\b(?:change|replace|remove|add|undo|cancel|stop)\b', q):
        day = extract_itinerary_day(message) or explanation.get('day')
        position = extract_activity_position(message, allow_short=True) or explanation.get('position')
        if extract_itinerary_day(message) or extract_activity_position(message, allow_short=True) or re.fullmatch(r'(?:the )?(?:saved|original|old|proposed|draft|new)(?: one)?', q):
            scope = 'proposed' if re.search(r'\b(?:proposed|draft|new)\b', q) else 'saved'
            return {'message': f'Why was the {scope} activity' + (f' {position}' if position else '')
                    + (f' on Day {day}' if day else '') + ' recommended?'}
    if re.search(r'\b(?:payments?|paid|orders?|bookings?|reservations?)\b', q):
        return {'commerce': 'records'}  # Existing owner-scoped tools, never model interpretation.
    basis_correction = bool(re.search(r'\b(?:per|each) (?:person|pax|traveller)|\bper group\b', q))
    if basis_correction and (extract_budget(message) is not None or re.search(r'\b\d+(?:\.\d+)?\b', q)):
        if state.get('assistantMode') == 'packages':
            amount = extract_budget(message)
            if amount is None:
                number = re.search(r'(?<![\w.,])([\d,]+(?:\.\d{1,2})?)\s+(?:per|each) (?:person|pax|traveller|group)\b', message, re.I)
                amount = float(number[1].replace(',', '')) if number else None
            if amount is None:
                return {'commerce': 'packages'}
            basis = 'per person' if re.search(r'\b(?:per|each) (?:person|pax|traveller)\b', q) else 'in total'
            return {'commerce': 'packages', 'message': f'{message}. Budget RM{amount:g} {basis}'}
        if adjustment.get('tripId'):
            return {'response': {'reply': 'Saved-trip budgets are totals, not per-person package quotes. What total trip budget should I use?'}}
    if re.search(r'\b(?:weather|raining|rains|rain|rainy|forecast)\b', q) and not re.search(r'\b(?:replace|remove|add|change|indoor|indoors|sheltered|museums?|attractions?|places|alternatives)\b', q):
        area = geo.get('destination_area') or ((focus.get('city') or focus.get('state')) if focus else None)
        areas = {row.get('city') or row.get('destination') or row.get('state') for row in rows}
        areas.discard(None)
        if area is None and len(areas) == 1 and extract_itinerary_day(message) is None:
            area = next(iter(areas))
        area = area or (adjustment.get('tripContext') or {}).get('destinationArea') or state.get('destinationArea')
        return {'response': {'reply': f'Open Weather{f" for {area}" if area else ""} for the current forecast. '
                             'I have kept your planning context; general rain advice is not a live forecast.',
                             'weatherAction': {'destination': area or ''}}}
    if kind == 'place' and rows and re.search(r'\b(?:same|again|repeat)\b', q) and re.search(
            r'\b(?:places|results|options|recommendations)\b', q) and not re.search(r'\b(?:new|different|cheaper)\b', q):
        return {'response': {'reply': 'These are the same recorded results; no new search was needed.', 'placeSuggestions': rows}}
    if lookup and geo.get('destination_area') and re.search(r'\b(?:show|suggest|recommend|give|find)\b', q) and re.search(
            r'\b(?:places|attractions|spots)\b', q) and not re.search(r'\b(?:change|replace|remove|day|plan|itinerary)\b', q):
        from .nlp_extractor import filter_constraint_candidates
        candidates = lookup({'city': geo['destination_area'], 'state': geo.get('destination_state')})
        interests = concepts_for(extract_interests(message))
        candidates = filter_constraint_candidates(candidates, excluded_interests=state.get('excludedInterests'),
            excluded_activity_types=state.get('excludedActivityTypes'), prefer_indoor=state.get('preferIndoor', False))
        unique = {}
        for row in candidates:
            if not interests or candidate_concepts(row) & interests:
                unique.setdefault(result_id(row, 'place') or clean_text(row.get('title')), row)
        count_match = re.search(r'\b([1-5]|one|two|three|four|five) (?:places|attractions|spots)\b', q)
        count = (int(count_match[1]) if count_match[1].isdigit() else
                 {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5}[count_match[1]]) if count_match else 3
        shortlist = list(unique.values())[:count]
        return {'response': {'reply': f'Here are {len(shortlist)} recorded places in {geo["destination_area"]}. Which one interests you?' if shortlist else
                             'I could not verify places matching those constraints.', 'placeSuggestions': shortlist}}
    if re.search(r'\b(?:resume|continue|back to|return to)\b', q):
        if adjustment.get('tripId'):
            return {'message': 'Back to editing my trip'}
        if state.get('guidedQuestion'):
            from .guided_planning import QUESTIONS
            prompt, options = QUESTIONS.get(state['guidedQuestion'], ('What would you like to plan next?', []))
            return {'response': {'reply': prompt, 'suggestedReplies': options}}
        if rows:
            return {'response': {'reply': f'We were reviewing {len(rows)} {kind} results. Which one would you like to inspect?'}}
    if kind == 'package' and not (adjustment and re.search(r'\b(?:day|activity|stop|itinerary|trip|undo|saved|proposed|draft)\b', q)) and not re.search(r'\b(?:first|second|third|fourth|fifth)\b.*\b(?:one|option|better)\b', q) and not (
            focus and re.search(r'\b(?:expensive|why|does it cost)\b', q)):
        return {'commerce': 'packages'}  # Existing package filters/quotes own financial semantics.
    if adjustment.get('tripId'):
        day = extract_itinerary_day(message) or adjustment.get('pendingDay') or adjustment.get('viewDay')
        if re.search(r'\b(?:boring|dull|not fun|change some|change a place)\b', q):
            return {'message': f'Change Day {day}' if day else 'Change some places'}
        if re.search(r'\b(?:walking|walk)\b', q) and re.search(r'\b(?:too much|less|reduce|don t want|dont want)\b', q):
            return {'message': 'Reduce walking' + (f' on Day {day}' if day else '')}
        if (focus is None or extract_itinerary_day(message) is not None) and re.search(r'\b(?:indoor|indoors|sheltered)\b', q) and not re.search(r'\b(?:replace|remove|change|add)\b', q):
            return {'message': 'Prefer indoor activities' + (f' on Day {day}' if day else '')}
        if re.search(r'\b(?:keep|leave)\b.*\b(?:first|second|third|day)\b', q) and day:
            return {'message': f'Keep Day {day} unchanged'}
        if focus is None and re.search(r'\b(?:cheap|cheaper|cheapest)\b', q):
            return {'message': 'Can make it cheaper?'}
        if re.search(r'\b(?:activity|stop|day|saved|proposed|draft|itinerary)\b', q):
            return None  # An explicit itinerary reference outranks a public-result pronoun.
    indices = named or [int(v) for v in re.findall(r'\b([1-5])\b', q)]
    if not indices:
        indices = [i for word, i in [('first', 1), ('second', 2), ('third', 3), ('fourth', 4), ('fifth', 5)]
                   if re.search(r'\b' + word + r'\b', q)]
    reference = bool(re.search(r'\b(?:one|option|result|which|compare|better|prefer)\b', q))
    if rows and re.search(r'\bcompare\b', q) and not indices:
        return {'response': {'reply': 'Which two displayed results would you like to compare?'}}
    if rows and indices and reference and not re.search(r'\b(?:day|activity|stop|budget|rm|adults?|travellers?)\b', q):
        compare = bool(re.search(r'\b(?:compare|versus|vs)\b', q) or (len(indices) == 2 and re.search(r'\b(?:which|better)\b', q)))
        return {'response': _reference_reply(indices[:2] if compare else indices[:1], kind, rows, state, compare)}
    if rows and re.search(r'\b(?:why|expensive|price|cost|cheaper|nearby|not this|different one|indoor|indoors|sheltered|hours|opens|closes)\b', q):
        if focus is None:
            return {'response': {'reply': 'Which result do you mean? Choose its name or displayed number first.'}}
        if re.search(r'\bwhy\b', q):
            matched = focus.get('matchedInterests')
            matched = [v for v in matched[:8] if isinstance(v, str)] if isinstance(matched, list) else []
            matched = matched or display_concepts(candidate_concepts(focus) & concepts_for(state.get('interests') or []))
            recorded = focus.get('recommendationReason')
            reason = (recorded if isinstance(recorded, str) else None) or (f'Matches your interests: {", ".join(matched)}.' if matched else
                'It was returned for this destination; no verified suitability explanation is stored.')
            return {'response': {'reply': f'{focus.get("title") or focus.get("name")}: {reason}'}}
        if re.search(r'\b(?:hours|opens|closes)\b', q):
            hours = focus.get('openingHours')
            if isinstance(hours, str) and hours and focus.get('openingHoursSourceUrl') and focus.get('openingHoursVerifiedAt'):
                return {'response': {'reply': f'Recorded opening hours for {focus.get("title")}: {hours}. Recheck with the venue before travelling.'}}
            return {'response': {'reply': 'Verified opening hours are unavailable for this place; I will not infer them.'}}
        if re.search(r'\b(?:nearby|cheaper|not this|different one|indoor|indoors|sheltered)\b', q):
            if kind != 'place':
                return {'message': 'Find cheaper packages' if 'cheaper' in q else 'Find other packages'}
            cheaper = 'cheaper' in q
            base = activity_pricing(focus, 1)
            if cheaper and (base['pricingIssues'] or focus.get('currency', 'MYR') != 'MYR'):
                return {'response': {'reply': 'I cannot verify which option is cheaper because this place has no reliable price.'}}
            if re.search(r'\b(?:not this|different one)\b', q):
                rejected = state.get('rejectedResults', [])
                entry = {'kind': kind, 'id': result_id(focus, kind)}
                state['rejectedResults'] = (rejected + [entry] if entry not in rejected else rejected)[-10:]
            candidates = lookup(focus) if lookup else rows
            from .nlp_extractor import filter_constraint_candidates
            candidates = filter_constraint_candidates(candidates, excluded_interests=state.get('excludedInterests'),
                excluded_activity_types=state.get('excludedActivityTypes'),
                prefer_indoor=state.get('preferIndoor', False) or bool(re.search(r'\bindoor|indoors|sheltered\b', q)))
            alternatives = []
            for row in candidates:
                if result_id(row, 'place') == result_id(focus, 'place'):
                    continue
                if {'kind': 'place', 'id': result_id(row, 'place')} in state.get('rejectedResults', []):
                    continue
                distance = _known_distance(focus, row)
                price = activity_pricing(row, 1)
                if ('nearby' in q and (distance is None or distance > 5)) or (cheaper and (
                    price['pricingIssues'] or row.get('currency', 'MYR') != 'MYR' or price['pricingUnit'] != base['pricingUnit'] or
                    price['effectiveCost'] >= base['effectiveCost'])):
                    continue
                alternatives.append(row)
            if not alternatives:
                return {'response': {'reply': 'I could not verify suitable alternatives with the available location and price data.'}}
            return {'response': {'reply': 'Here are other recorded options' + (' within 5 km straight-line distance, not walking distance.' if 'nearby' in q else '.'),
                                 'placeSuggestions': alternatives[:5]}}
        return {'response': {'reply': f'{focus.get("title") or focus.get("name")}: {_price(focus, kind)}'}}
    if not rows and re.search(r'\b(?:ticket prices?|opening hours|admission prices?|expensive)\b', q):
        return {'response': {'reply': 'Which place do you mean? Choose a recorded place so I can check its available price or hours.'}}
    # Explicit commands, package budgets and useful short clarification answers stay deterministic.
    explicit = re.search(r'\b(?:adjust|change|replace|remove|add|keep|cancel|stop|undo|compare|plan|find|show|budget|rm|package|flight|hotel|walking|pace|indoor|indoors|relaxing|slower)\b', q)
    if explicit or extract_budget(message) is not None or extract_travellers(message) or conversational_question(message) or classify_detailed_intent(message) in {
            'FEATURE_EXPLANATION', 'BUDGET_ENQUIRY', 'DATE_ADJUSTMENT', 'DURATION_ADJUSTMENT', 'TRAVELLER_COUNT_ADJUSTMENT',
            'DESTINATION_RECOMMENDATION', 'DESTINATION_ENQUIRY', 'ACTIVITY_DISCOVERY', 'INDOOR_ALTERNATIVE'} or extract_itinerary_day(message) is not None or extract_interests(message) or extract_activity_position(message, allow_short=True) or not (
            adjustment.get('tripId') or state.get('guidedActive') or rows):
        return None
    if interpret is None or len(q.split()) < 3 or re.fullmatch(r'(?:hi|hello|hey|hai|thanks|thank you)(?: lah| ah)?', q):
        return None
    prompt = 'Allowed output schema (omit irrelevant optional keys; no nulls or extra fields): ' + json.dumps(SCHEMA) + '\nContext: ' + prompt_context(state, messages) + '\nMessage: ' + redact(message, 600)
    try:
        value = validate_interpretation(interpret(prompt), state, rows)
    except Exception:
        value = None
    if not value or value['intent'] == 'clarify':
        day = adjustment.get('pendingDay') or adjustment.get('viewDay')
        if state.get('guidedQuestion') and not adjustment:
            from .guided_planning import QUESTIONS
            prompt, options = QUESTIONS.get(state['guidedQuestion'], ('Which planning detail would you like to change?', []))
            return {'response': {'reply': prompt, 'suggestedReplies': options}}
        prompt = f'Do you want to inspect or change Day {day}?' if day else 'Would you like to inspect a result or change your trip preferences?'
        if messages and messages[-1].get('reply') == prompt:
            prompt = f'Which activity or theme should I change on Day {day}?' if day else 'Which displayed result or planning detail do you mean?'
        return {'response': {'reply': prompt, 'suggestedReplies': [f'Show Day {day}', 'Nature', 'Food'] if day else []}}
    intent = value['intent']
    day = value.get('day') or adjustment.get('pendingDay') or adjustment.get('viewDay')
    if intent in {'reference', 'compare'}:
        return {'response': _reference_reply(value['resultIndices'], kind, rows, state, intent == 'compare')}
    if intent == 'weather':
        return resolve_turn('What is the weather?', state, messages)
    if intent == 'view_trip':
        if not adjustment.get('tripId'):
            return {'response': {'reply': 'Here is the unconfirmed proposal. It has not been saved.', 'tripPlan': state['activePlan']}}
        return {'message': f'Show Day {day}' if day else 'Show my trip'}
    if intent == 'resume':
        return resolve_turn('Continue what we discussed just now', state, messages)
    theme = ' and '.join(value.get('interests') or [])
    operation = value.get('operation', 'replace')
    if intent == 'edit_day':
        if operation == 'add':
            return {'message': f'Add {theme or "activities"} on Day {day}'}
        return {'message': f'Make Day {day} more relaxing' if operation == 'relax' else f'Change Day {day}' + (f' to {theme}' if theme else '')}
    return {'message': f'{operation.capitalize()} activity {value["activityIndex"]} on Day {day}' + (f' with {theme}' if theme else '')}
