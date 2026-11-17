"""Deterministic owner-scoped read tools. Only the existing chat route persists messages."""
import re
from decimal import Decimal

from services.commerce_money import record_money
from services.preference_learning import effective_preference_profile
from .nlp_extractor import clean_text, extract_itinerary_day, NUMBER_WORDS
from .history_conversation import is_history_request
from .contextual_intent import redact
from .personal_budget import count, explain_budget, money, what_if, cheaper_activity_previews
from .capabilities import personal_intent, READ_TOOLS


class PersonalReadUnavailable(Exception):
    pass


def _order_money(record):
    amount, currency = record_money(record)
    minor = record.get('amountMinor')
    if currency == 'MYR' and type(minor) is int and minor >= 0:
        recorded = money(Decimal(minor) / 100)
        if amount is not None and money(amount) != recorded:
            return None, currency
        return float(recorded), currency
    return amount, currency


def _intent(q, state):
    if is_history_request(q):
        return None
    if re.match(r'(?:please )?(?:plan|create|build|generate|start)\b|i (?:want|need) to (?:plan|create|build)\b', q):
        return None
    natural = personal_intent(q)
    if natural:
        return natural
    if re.search(r'^(?:what|which)\b.*\b(?:remove|cut|skip)\b.*\b(?:save money|costs|spending)\b', q):
        return 'alternatives'
    if re.search(r'\b(?:my|i|saved|selected|attached|this trip)\b', q):
        if 'notifications' in q:
            return 'notifications'
        if re.search(r'\b(?:paid|payment|payments|orders?|purchases?|bookings?|refund)\b', q):
            return 'orders'
        if re.search(r'\b(?:recommendations?|recommended|for you|ranking)\b', q):
            return 'recommendations'
        if re.search(r'\b(?:preferences|personality|travel style|interests)\b', q) and not re.search(r'\b(?:suggest|recommend|find)\b', q) and (not re.search(r'\b(?:change|prefer|instead|plan)\b', q) or re.search(r'\b(?:saved|permanent|questionnaire|profile)\b', q)):
            return 'preferences'
        if re.search(r'\b(?:favourites|favorites|favourite|favorite|saved places|saved items)\b', q):
            return 'saved'
        if (re.search(r'\b(?:selected|attached|my) (?:flight|hotel)\b|\b(?:flight|hotel).{0,15}\b(?:selected|attached)\b', q)
                and not re.search(r'\b(?:change|remove|replace|find|search|add)\b', q)):
            return 'selection'
    if state.get('guidedActive') and not re.search(r'\b(?:saved trip|existing trip|my saved|my existing)\b', q):
        return None
    personal = bool(re.search(r'\b(?:my|saved|trip|itinerary|day|food|transport|spending|spent|breakdown|budget)\b', q))
    if state.get('assistantMode') == 'packages' and not re.search(r'\b(?:saved trip|my trip|my budget|itinerary)\b', q):
        return None
    if (personal or re.search(r'\b(?:rm|myr)\s*\d|\b(?:travellers|people)\b', q)) and re.search(r'\b(?:what if|suppose|would it|(?:can|could) i afford)\b', q):
        return 'what_if'
    if personal and re.search(r'\b(?:cheaper|reduce costs|save money|lower cost alternatives)\b', q) and not re.match(r'(?:please )?(?:make|reduce|change|replace)\b', q):
        return 'alternatives'
    enquiry = bool(re.match(r'(?:what|how|which|why|is|are|does|do|can|could|show|explain|tell|compare|breakdown)\b', q)
                   or re.fullmatch(r'(?:my )?(?:trip )?budget(?: breakdown| summary)?[.!?]?', q))
    if personal and enquiry and re.search(r'\b(?:budget|cost|costs|spending|spent|breakdown|expensive|food|transport)\b', q) and not re.search(r'\b(?:set|change|update|restore|revert|edit|adjust|add|remove|replace)\b', q):
        return 'budget'
    return None


def _action(kind, trip=None):
    return {'kind': kind, **({'tripId': trip['id']} if trip else {})}


def respond(message, state, read, uid, *, tool=None):
    q = clean_text(message)
    context = state.get('personalContext') or {}
    intent = tool if tool in READ_TOOLS.values() else _intent(q, state)
    if intent is not None and context.get('pendingIntent') not in (None, intent):
        for key in ('choices', 'choiceKind', 'pendingIntent', 'pendingMessage'):
            context.pop(key, None)
    number = re.fullmatch(r'(?:trip|order|option)?\s*(\d{1,2})[.!]?', q)
    followup = bool(re.search(r'\b(?:per person|per pax|day \d+|which day|most expensive|and food|what about food|and transport)\b', q))
    if intent is None and context.get('choices') and number:
        intent = context.get('pendingIntent')
        message = context.get('pendingMessage', message)
    elif intent is None and context.get('tripId') and followup:
        intent = 'budget'
    elif (intent is None and context.get('tripId') and context.get('lastReadIntent') in {'budget', 'what_if', 'alternatives'}
          and not state.get('selectedResult')
          and re.search(r'\b(?:including|included|enough|unknown|unavailable|estimates|actually spent|total so high)\b', q)):
        intent = 'budget'
    elif intent is None and context.get('tripId') and re.search(r'\b(?:is it|was it|has it been) paid\b', q):
        intent = 'orders'
    elif (intent is None and context.get('tripId') and context.get('lastReadIntent') == 'what_if'
          and re.search(r'\b(?:rm|myr)\s*\d|\b\d+ (?:travellers|people)\b', q)
          and not re.search(r'\b(?:set|save|update|apply)\b', q)):
        intent = 'what_if'
    elif (intent is None and context.get('lastReadIntent') == 'recommendations'
          and (number or re.search(r'\b(?:first|second|third)\b', q))):
        intent = 'recommendations'
    if intent is None:
        if re.search(r'\b(?:adjust|edit|restore|revert|new trip|new itinerary)\b', q):
            for key in ('choices', 'pendingIntent', 'pendingMessage', 'choiceKind'):
                context.pop(key, None)
        if re.search(r'\b(?:adjust|edit|modify|revise) (?:my|an existing|a saved) (?:trip|itinerary)\b|\bnew (?:trip|itinerary)\b', q):
            for key in ('tripId', 'tripOptions', 'scenarioInputs'):
                context.pop(key, None)
        return None
    state['personalContext'] = context
    raw_read = read

    def read(*args, **kwargs):
        try:
            return raw_read(*args, **kwargs)
        except Exception as error:
            raise PersonalReadUnavailable() from error

    def own(collection, key):
        row = read(collection, key)
        return row if isinstance(row, dict) and row.get('travellerId') == uid else None

    def rows(collection):
        result = read(collection, filters=[('travellerId', '==', uid)], limit=51) or []
        return [r for r in result if isinstance(r, dict) and r.get('travellerId') == uid][:50]

    def reply(text, actions=(), **extra):
        context['lastReadIntent'] = intent
        return {'reply': text, 'readOnlyAnswer': True, 'assistantActions': list(actions), **extra}

    def orders():
        checkout = rows('checkout_orders')
        ids = {r['id'] for r in checkout}
        legacy = [r for r in rows('payment_records') if (r.get('checkoutOrderId') or r.get('orderId')) not in ids]
        return [(r, 'checkout_orders') for r in checkout] + [(r, 'payment_records') for r in legacy]

    if intent == 'trips':
        trips = rows('itineraries')[:20]
        safe = [{'id': r['id'], 'title': redact(r.get('title') or 'Saved trip', 120),
                 'startDate': redact(r.get('startDate'), 30), 'endDate': redact(r.get('endDate'), 30)} for r in trips]
        return reply('Your saved trips (up to 20):\n' + ('\n'.join(
            f'{r["title"]}: {r["startDate"] or "dates unset"} – {r["endDate"] or "dates unset"}' for r in safe) or 'No saved trips found.')
            + '\nOpen a trip to inspect it, or ask to adjust a saved itinerary for a confirmation-gated preview.',
            [_action('trips')], savedTrips=safe, ownedTrips=safe)
    if intent == 'notifications':
        return reply('Open Home → Notifications (the bell) to inspect your inbox. That workflow reconciles events and can write notification/cache records, so I have not called it as a read-only assistant lookup.')
    if intent == 'preferences':
        pref = read('travel_preferences', uid)
        if not isinstance(pref, dict) or pref.get('travellerId', uid) != uid:
            return reply('No saved preferences are available for your account.', [_action('preferences')])
        learned = read('learned_preference_profiles', uid)
        if isinstance(learned, dict) and learned.get('travellerId', uid) != uid:
            learned = None
        effective = effective_preference_profile(pref, learned)
        fields = ('travelPersonality', 'travelType', 'interests', 'travelPace', 'budgetRange', 'travelPurpose')
        safe = {key: [redact(v, 100) for v in effective[key][:12] if isinstance(v, str)] if isinstance(effective[key], list)
                else redact(effective[key], 100) for key in fields if key in effective and isinstance(effective[key], (str, list))}
        text = '\n'.join(f'{key}: {", ".join(map(str, value)) if isinstance(value, list) else value}' for key, value in safe.items())
        return reply('Your recorded preferences:\n' + text + '\nThese answers have not changed your permanent preferences. Use Preferences to review and explicitly save permanent changes.', [_action('preferences')], ownPreferences=safe)
    if intent == 'saved':
        saved = rows('favourites')
        safe = [{'destinationId': r.get('destinationId'), 'title': r.get('title') or r.get('name') or 'Saved place'} for r in saved[:20]]
        return reply('Your saved places (up to 20):\n' + ('\n'.join(r['title'] for r in safe) or 'No saved places found.') + '\nNo saved item was changed or deleted. Open Saved Places to make a deliberate change.', [_action('saved')], savedPlaces=safe)
    if intent == 'recommendations':
        reference = bool(context.get('generationId') and context.get('lastReadIntent') == 'recommendations'
                         and (number or re.search(r'\b(?:first|second|third)\b', q)))
        if reference:
            snapshot = own('recommendation_snapshots', context['generationId'])
        else:
            from services.recommendation_snapshot_storage import latest_snapshot
            try:
                snapshot = latest_snapshot(raw_read, lambda header: raw_read('recommendation_snapshots', header['id']), uid)
            except Exception as error:
                raise PersonalReadUnavailable() from error
        if not snapshot:
            return reply('No saved recommendations are available. Open Home → For You to deliberately generate recommendations; I have not generated a snapshot.')
        from modules.fr04_hybrid_recommendation.routes import _profile_fingerprint, _preference_version
        pref = read('travel_preferences', uid) or {}
        learned = read('learned_preference_profiles', uid)
        if pref.get('travellerId', uid) != uid or (isinstance(learned, dict) and learned.get('travellerId', uid) != uid):
            return reply('The saved recommendation context is unavailable for your account.')
        stale = snapshot.get('preferenceFingerprint') != _profile_fingerprint(pref) or snapshot.get('preferenceProfileVersion') != _preference_version(pref, learned)
        safe = [{key: r.get(key) for key in ('destinationId', 'title', 'name', 'finalScore', 'contentScore', 'collaborativeScore', 'popularityScore', 'recommendationReason')}
                for r in snapshot.get('recommendationResults', [])[:10] if isinstance(r, dict)]
        if reference:
            index = int(number[1]) - 1 if number else next(i for i, word in enumerate(('first', 'second', 'third')) if word in q)
            if not 0 <= index < len(safe):
                return reply('That recommendation number is outside the displayed saved results.')
            safe = [safe[index]]
        context['generationId'] = snapshot['id']
        return reply(('These saved results are stale for your current preferences.\n' if stale else '') +
                     f"Saved results recorded at {snapshot.get('generatedAt') or 'an unavailable time'} (bounded owner-scoped history). "
                     'TravelMate uses 60% content, 30% collaborative and 10% popularity scores; personal match is a different measure.\n' +
                     '\n'.join(f"{r.get('title') or r.get('name') or 'Destination'}: {r.get('recommendationReason') or 'No recorded reason available.'}" for r in safe) +
                     '\nNo preferences, scores or snapshots were changed. Open Home → For You if you want a refresh.',
                     savedRecommendations=safe, recommendationStale=stale)
    if intent == 'orders':
        available = orders()
        if context.get('tripId') and re.search(r'\b(?:is it|was it|has it been) paid\b', q):
            available = [(r, c) for r, c in available if context['tripId'] in
                         {r.get('itineraryId'), r.get('fulfilledTripId'), r.get('tripId')}]
        kind = next((kind for kind in ('hotel', 'flight', 'package') if re.search(r'\b' + kind + r'\b', q)), None)
        if kind:
            available = [(r, c) for r, c in available if r.get('quoteType', r.get('bookingType')) == kind]
        if number and context.get('choiceKind') == 'orders':
            index = int(number[1]) - 1
            choices = context.get('choices', [])
            if not 0 <= index < len(choices):
                return reply('Choose a displayed order number.', [_action('payments')])
            choice = choices[index]
            row = own(choice['collection'], choice['id'])
            available = [(row, choice['collection'])] if row else []
        from modules.fr09_payment.routes import _payment_history_item
        safe = []
        for row, collection in available[:20]:
            item = _payment_history_item(row, 'checkout_order' if collection == 'checkout_orders' else 'legacy_payment')
            amount, currency = _order_money(row)
            safe.append({key: item.get(key) for key in ('id', 'bookingType', 'productTitle', 'paymentStatus', 'orderStatus', 'fulfillmentStatus', 'supplierBookingStatus')})
            safe[-1].update(amount=amount, currency=currency)
        context.update(choiceKind='orders', choices=[{'collection': c, 'id': r['id']} for r, c in available[:20]], pendingIntent='orders', pendingMessage=message)
        package_records = []
        if any(r.get('quoteType') == 'package' for r, _ in available):
            from .package_assistant import owned_context
            def selected_packages(collection, key=None, **kwargs):
                if collection == 'checkout_orders' and key is None:
                    return [r for r, c in available if c == 'checkout_orders' and r.get('quoteType') == 'package']
                return read(collection, key, **kwargs)
            package_records = owned_context('my orders', selected_packages, uid)['ownedOrders']
        lines = [f"{i}. {r.get('productTitle') or r['bookingType']}: recorded payment {r['paymentStatus'] or 'unknown'}, order {r['orderStatus'] or 'unknown'}; "
                 f"{r['currency']} {r['amount'] if r['amount'] is not None else 'amount unavailable'}; supplier {r.get('supplierBookingStatus') or 'confirmation not established'}." for i, r in enumerate(safe, 1)]
        return reply(('Recorded payment/order history (up to 20). Reply with a number for one order.\n' + '\n'.join(lines) if lines else 'No matching owned payment/order records were found.') +
                     '\nSelection, payment and supplier confirmation are separate. This is saved status, not live provider verification. Open Payment History for reconciliation, cancellation or refund guidance; chat has performed none of those actions.',
                     [_action('payments')], personalOrders=safe, **({'ownedOrders': package_records} if package_records else {}))

    # Trip tools re-read ownership every turn. Neither choice lists nor conversation IDs confer access.
    trip = None
    named_options = [r for r in context.get('tripOptions', []) if len(r.get('title') or '') >= 4 and
                     re.search(r'(?<!\w)' + re.escape(r['title']) + r'(?!\w)', message, re.I)]
    if len(named_options) == 1:
        trip = own('itineraries', named_options[0]['id'])
        if not trip:
            return reply('That named trip is no longer available for your account.')
    elif number and context.get('choiceKind') == 'trips':
        choices = context.get('choices', [])
        index = int(number[1]) - 1
        if not 0 <= index < len(choices):
            return reply('Choose a displayed trip number.')
        trip = own('itineraries', choices[index])
        if not trip:
            context.pop('choices', None)
            return reply('That trip is no longer available for your account.')
    else:
        selected = context.get('tripId') or (state.get('adjustment') or {}).get('tripId')
        if selected and not re.search(r'\b(?:another|different|which) trip\b', q):
            trip = own('itineraries', selected)
            if not trip:
                context.pop('tripId', None)
                return reply('That trip is no longer available for your account.')
    if trip is None:
        choices = rows('itineraries')[:20]
        context['tripOptions'] = [{'id': r['id'], 'title': str(r.get('title') or '')} for r in choices]
        named = [r for r in choices if len(str(r.get('title') or '')) >= 4 and str(r['title']).lower() in message.lower()]
        if len(named) == 1:
            trip = named[0]
        elif len(choices) == 1:
            trip = own('itineraries', choices[0]['id'])
        else:
            context.update(choiceKind='trips', choices=[r['id'] for r in choices], pendingIntent=intent, pendingMessage=message)
            return reply('Which saved trip should I inspect? Reply with its number.\n' +
                         '\n'.join(f"{i}. {r.get('title') or 'Saved trip'} ({r.get('startDate') or 'dates unavailable'})" for i, r in enumerate(choices, 1))
                         if choices else 'No owned saved trips are available.', [_action('trips')])
    if not trip:
        return reply('The selected trip is unavailable.')
    context['tripId'] = trip['id']
    for key in ('choices', 'choiceKind', 'pendingIntent', 'pendingMessage'):
        context.pop(key, None)
    actions = [_action('trip', trip), _action('budget', trip)]
    if intent == 'selection':
        lines, safe = [], {}
        for kind in ('flight', 'hotel'):
            selection = trip.get('selected' + kind.title())
            booking = own('hotel_bookings', trip['hotelBookingId']) if kind == 'hotel' and trip.get('hotelBookingId') else None
            if not selection and booking:
                selection = booking.get('hotelSnapshot') or {'name': booking.get('hotelName')}
            if not isinstance(selection, dict) or not selection:
                lines.append(f'No selected {kind} is recorded for this trip.')
                continue
            fields = ('name', 'hotelName', 'roomName', 'airline', 'origin', 'destination', 'checkin', 'checkout', 'outboundDate', 'returnDate', 'roomQuantity', 'travellerCount', 'price', 'currency', 'priceBasis', 'expiresAt')
            safe[kind] = {key: redact(selection[key]) if isinstance(selection[key], str) else selection[key]
                          for key in fields if key in selection and isinstance(selection[key], (str, int, float))}
            legs = []
            if kind == 'flight':
                segment_fields = ('departureAirport', 'arrivalAirport', 'departureDate', 'arrivalDate',
                                  'departureTime', 'arrivalTime', 'airline', 'flightNumber')
                for leg in ('outboundSegments', 'returnSegments'):
                    safe[kind][leg] = [{key: redact(segment[key], 100) for key in segment_fields if isinstance(segment.get(key), str)}
                                      for segment in (selection.get(leg) or [])[:8] if isinstance(segment, dict)]
                    legs += [f"{leg} {i}: " + '; '.join(f'{key}: {value}' for key, value in segment.items())
                             for i, segment in enumerate(safe[kind][leg], 1)]
            if booking:
                safe[kind]['recordedBookingStatus'] = str(booking.get('bookingStatus') or 'unknown')
            lines.append(f'Selected {kind}: ' + '; '.join(f'{k}: {v}' for k, v in safe[kind].items() if not isinstance(v, list)) +
                         ('\n' + '\n'.join(legs) if legs else '') + '. This saved offer may be stale; selection is not proof of payment, a ticket or supplier confirmation.')
        return reply('\n'.join(lines) + '\nOpen Trip Details to review or search through the existing controls; no quote was refreshed.', actions, selectedTravel=safe)
    if trip.get('packageTrip') or trip.get('tripType') == 'package':
        order = own('checkout_orders', trip.get('checkoutOrderId')) if trip.get('checkoutOrderId') else None
        amount, currency = _order_money(order) if order else (None, 'UNKNOWN')
        return reply(f'Purchased package trip: recorded purchase amount {currency} {amount if amount is not None else "unavailable"}. '
                     'This is the purchase-time group amount, not a new per-person quote. Package inclusions are not added again as separate food, hotel or activity estimates. Extra spending and supplier confirmation are separate.', [_action('trip', trip), _action('payments')])
    if intent == 'what_if':
        if re.search(r'\b(?:food|meal|hotel|flight|daily|per day)\b', q):
            return reply('Do you mean the total group budget, a per-person trip budget, or a daily food allowance? I have not changed or repriced anything.', actions)
        # Keep punctuation here: clean_text removes decimal points and changes money/counts.
        match = re.search(r'\b(?:rm|myr)\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)(?![\w.,])', message, re.I)
        traveller_nouns = r'(?:travellers|travelers|people|persons|pax)\b'
        travellers = re.search(r'(?<![\w.,+-])(' + '|'.join(NUMBER_WORDS) + r'|\d{1,3})\s+' + traveller_nouns, message, re.I)
        if re.search(r'[\d.,+-]+\s+' + traveller_nouns, message, re.I) and not travellers:
            return reply('Use a whole traveller count from 1 to 100 for this comparison.', actions)
        if re.search(r'\b(?:rm|myr)\s*[\d+-]', message, re.I) and not match:
            return reply('Use a non-negative MYR amount with at most two decimal places.', actions)
        previous = context.get('scenarioInputs') or {}
        if previous.get('tripId') != trip['id']:
            previous = {}
        if not match and not travellers and not previous:
            return reply('What total budget in MYR or traveller count should I compare? This will be a read-only scenario.', actions)
        party = (int(travellers[1]) if travellers[1].isdigit() else NUMBER_WORDS[travellers[1].lower()]) if travellers else previous.get('travellers')
        if party is not None and not 1 <= party <= 100:
            return reply('Use a traveller count from 1 to 100 for this comparison.', actions)
        budget = money(match[1].replace(',', '')) if match else money(previous.get('budget'))
        per_person = bool(re.search(r'(?:per|each) (?:person|pax)', clean_text(message))) if match else previous.get('perPerson', False)
        context['scenarioInputs'] = {'tripId': trip['id'], 'budget': str(budget) if budget is not None else None,
                                     'perPerson': per_person, 'travellers': party}
        result = what_if(trip, budget=budget, per_person=per_person, travellers=party)
    else:
        result = explain_budget(trip)
    if not result['available']:
        return reply(result['reply'], actions, budgetReasoning=result)
    if intent == 'alternatives':
        from services.local_catalog import DESTINATIONS
        candidates = list(DESTINATIONS)
        if trip.get('recommendationGenerationId'):
            snapshot = own('recommendation_snapshots', trip['recommendationGenerationId'])
            if snapshot:
                candidates += snapshot.get('recommendationResults') or []
        previews = cheaper_activity_previews(trip, candidates)
        result['pricedAlternatives'] = previews
        result['reply'] += '\n' + ('\n'.join(f"{a['replacement']} instead of {a['original']}: recorded admission estimate lower by MYR {a['estimatedSavings']:.2f}. {a['basis']} Nothing was applied." for a in previews)
                                   if previews else 'No compatible lower-priced activity replacement could be verified in the available recorded candidates.')
        result['reply'] += '\n' + '\n'.join(a['description'] for a in result['advisoryAlternatives'])
        result['reply'] += '\nOpen Trip Details → Lower-Cost Alternatives for compatible priced replacements and explicit confirmation. I have not searched providers or applied a change; no saving is guaranteed.'
    day = extract_itinerary_day(message)
    if day or re.search(r'\b(?:day by day|each day|which day|daily|most expensive)\b', q):
        daily = result['daily']
        if day is not None and not 1 <= day <= len(daily):
            return reply('That day is outside the saved itinerary.', actions)
        selected = [daily[day - 1]] if day else daily
        result['reply'] += '\n' + '\n'.join(f"Day {r['day']}: MYR {r['modelledSubtotal']:.2f} modelled subtotal; {r['unknownActivities']} unverified activity prices." for r in selected)
        peak = max(r['modelledSubtotal'] for r in daily)
        result['highestModelledDays'] = [r['day'] for r in daily if r['modelledSubtotal'] == peak]
        result['reply'] += f"\nHighest modelled day subtotal: MYR {peak:.2f}, on day(s) {', '.join(map(str, result['highestModelledDays']))}."
        result['reply'] += '\n' + result['dailyBasis'] + f" Shared travel/stay: MYR {result['sharedTravelAndStay']:.2f}; unassigned activities: MYR {result['unassignedActivitySubtotal']:.2f}. These are not recorded daily actual spending and not a guaranteed cheapest-day ranking."
    manual = trip.get('manualExpenses') or []
    if isinstance(manual, list) and all(isinstance(e, dict) and type(e.get('amountMinor')) is int and e['amountMinor'] >= 0 and e.get('type') in {'actual', 'planned'} and e.get('currency', 'MYR') == 'MYR' for e in manual):
        from modules.fr05_smart_itinerary_budget_planner.expense_routes import expense_overview, recorded_costs
        paid, committed, _ = recorded_costs(trip, trip['id'], uid, read)
        ledger = expense_overview({**trip, 'travellerCount': count(trip)}, paid, committed)
        result['recordedExpenses'] = {k: ledger[k] for k in ('currency', 'actualMinor', 'plannedMinor', 'verifiedMinor', 'committedHotelMinor')}
        result['reply'] += f"\nRecorded manual actual spending: MYR {ledger['actualMinor'] / 100:.2f}; manual planned expenses: MYR {ledger['plannedMinor'] / 100:.2f}; linked recorded paid orders: MYR {ledger['verifiedMinor'] / 100:.2f}. These use the same linked-record rules as Trip Budget, not a scan of all account purchases. They are separate views, not additions to the modelled subtotal. No manual entries does not mean no spending occurred."
    else:
        result['reply'] += '\nRecorded manual expenses could not be safely interpreted; open Trip Budget to inspect them.'
    return reply(result['reply'], actions, budgetReasoning={k: v for k, v in result.items() if k not in {'reply', 'advisoryAlternatives'}})
