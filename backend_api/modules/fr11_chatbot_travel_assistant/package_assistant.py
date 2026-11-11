"""Read-only, allowlisted commerce tools. Catalogue text never selects tools or sets policy."""
from auth_utils import APPROVED_OPERATOR_STATUSES
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import re
from services.campaign_schedule import malaysia_today
from services.package_checkout_contract import prepare_package_snapshot, derive_required_services
from services.public_content_projection import eligible_package, public_package, active_campaign
from services.preference_learning import effective_preference_profile
from services.recommendation_taxonomy import candidate_concepts, concepts_for
from services.commerce_money import record_money, public_pricing_breakdown
from services.booking_requirements import load_context, status_overview
from .nlp_extractor import activity_request, extract_geographic_entities, extract_duration, extract_dates, extract_interests, extract_excluded_interests, NUMBER_WORDS
from .travel_dates import parse_date_range
# shortcut: bounded catalogue scan; add indexed pagination when the live catalogue exceeds this limit.
CATALOGUE_LIMIT = 200
RESULT_LIMIT = 6
_FLAGS = {'accommodation': 'accommodationIncluded', 'transport': 'transportIncluded', 'guideActivities': 'guideActivitiesIncluded'}

def conversation_action(message, state):
    text = message.lower()
    if re.search(r'\b(?:my saved trips|show my trips|list my trips|my bookings|my orders|my purchases|my payment|my package|packages? (?:have i|i have) (?:booked|bought|purchased)|(?:which|what) package (?:did|have) i (?:purchase|book|buy)|my (?:operator|supplier) arrangements?|operator arrangements?|supplier (?:status|arrangements?))\b', text):
        return 'owned'
    if re.search(r'\b(?:plan my own|independent (?:trip|itinerary)|not (?:a |an? )?(?:tourism )?package|(?:plan|create|build|design) .{0,30}(?:trip|itinerary))\b', text) and (not re.search(r'\b(?:find|show|search|compare) .{0,20}packages?\b', text)):
        return 'itinerary'
    if re.search(r'\bdestinations?\b', text) and (not re.search(r'\bpackages?\b', text)):
        return 'itinerary'
    if re.search(r'\b(?:packages?|campaigns?|promotions?|discounted tours?|discounts?)\b', text):
        return 'packages'
    if activity_request(text):
        return 'itinerary'
    if state.get('assistantMode') == 'packages' and (extract_geographic_entities(message).get('destination_area') or extract_duration(message) or extract_interests(message)):
        return 'packages'
    if state.get('assistantMode') == 'packages' and re.search(r'\b(?:under|below|above|budget|actually|instead|only|without|with|cheaper|cheapest|compare|first|second|third|which|show|find|make|adults?|children|child|next|on|reset|start over|code|rm|myr|food|photography|hotel|transport|guided)\b', text):
        return 'packages'
    if re.search(r'\b(?:find|want|looking for|show).{0,25}\btours?\b', text):
        return 'clarify'
    return None

def _dates(message, previous, duration):
    today = malaysia_today()
    weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    weekday = re.search(r'\b(?:next|this) (' + '|'.join(weekdays) + r')\b', message, re.I)
    if weekday:
        ahead = (weekdays.index(weekday[1].lower()) - today.weekday()) % 7 or 7
        return ((today + timedelta(days=ahead)).isoformat(), None)
    if re.search(r'\b(?:tomorrow|today)\b', message, re.I):
        return ((today + timedelta(days=1 if 'tomorrow' in message.lower() else 0)).isoformat(), None)
    interval = parse_date_range(message, today=today)
    if interval:
        return interval
    point = re.search(r'\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:\s+\d{4})?)\b', message, re.I)
    if point:
        start, _ = parse_date_range(f'{point[0]} to {point[0]}', today=today)
        return (start, None)
    start, end = extract_dates(message, duration or 1)
    if start:
        if date.fromisoformat(start) < today:
            raise ValueError('Choose a current or future travel date in Malaysia.')
        return (start, None)
    if re.search(r'\b(?:on|from|until|date)\s+\d', message, re.I):
        raise ValueError('Please give a valid travel date, for example 12 Dec 2026.')
    return (previous.get('startDate'), previous.get('endDate'))

def update_filters(message, previous):
    text = message.lower()
    for word, number in NUMBER_WORDS.items():
        text = re.sub(r'\b' + word + r'(?=\s+(?:adults?|children|child|kids?)\b)', str(number), text)
    filters = {} if re.search(r'\b(?:reset|start over|clear filters)\b', text) else deepcopy(previous or {})
    for key in ('resultIds', 'quoteErrors', 'catalogueLimited'):
        filters.pop(key, None)
    geo = extract_geographic_entities(message)
    if geo.get('is_foreign'):
        raise ValueError('I can search published TravelMate packages in Malaysia. Which Malaysian destination would you like?')
    if geo.get('destination_area'):
        filters['destination'] = geo['destination_area']
    if re.search(r'\b(?:anywhere|any destination|all destinations)\b', text):
        filters.pop('destination', None)
    numeric_duration = re.search(r'\b(\d+)\s*(?:-?\s*days?\b|d\s*\d+\s*n\b)', text)
    if numeric_duration and (not 1 <= int(numeric_duration[1]) <= 14):
        raise ValueError('Chat package searches support 1–14 days. Please choose a duration within that range.')
    duration = extract_duration(message)
    if duration:
        filters['days'] = duration
    start, end = _dates(message, filters, duration)
    if start:
        filters['startDate'] = start
    if end:
        filters['endDate'] = end
        filters['days'] = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    elif start and re.search(r'\b(?:next|this|on|from|tomorrow|today)\b', text):
        filters.pop('endDate', None)
    if re.search(r'\b(?:any date|no date preference|flexible dates)\b', text):
        filters.pop('startDate', None)
        filters.pop('endDate', None)
    budget = re.search(r'\b(?:under|below|less than|up to|maximum|max(?:imum)? budget|budget(?: of| is)?)\s*(?:rm|myr)?\s*([\d,]+(?:\.\d{1,2})?)', text)
    if not budget and re.search(r'\b(?:under|below|up to|budget)\s*(?:rm|myr)\b', text):
        raise ValueError('Please give a positive numeric budget in MYR.')
    if budget:
        amount = Decimal(budget[1].replace(',', ''))
        if amount <= 0 or amount > Decimal('100000000'):
            raise ValueError('Please give a positive MYR budget.')
        filters['budgetMax'] = float(amount)
        filters['budgetStrict'] = bool(re.search(r'\b(?:under|below|less than)\b', budget[0]))
    if re.search(r'\b(?:no budget limit|remove budget|any budget)\b', text):
        filters.pop('budgetMax', None)
    if budget and re.search(r'\bper (?:person|adult)\b', text):
        raise ValueError('Should I compare the total party budget? Tell me the adult/child counts and maximum total in MYR so fixed and per-person offers are comparable.')
    if re.search(r'-\d+\s*(?:adults?|children|child|kids?)\b', text):
        raise ValueError('Participant counts cannot be negative.')
    party = dict(filters.get('participants') or {})
    adults = re.search(r'\b(\d+)\s*adults?\b', text)
    children = re.search(r'\b(\d+)\s*(?:children|child|kids?)\b', text)
    if adults:
        party['adults'] = int(adults[1])
        party.setdefault('children', 0)
    if children:
        party['children'] = int(children[1])
    if re.search(r'\b(?:no children|adults only)\b', text):
        party['children'] = 0
    if party:
        if any((value < 0 or value > 50 for value in party.values())) or sum(party.values()) > 50 or party.get('adults') == 0:
            raise ValueError('Package groups need at least one adult and support at most 50 participants.')
        filters['participants'] = party
    if re.search(r'\b\d+\s*(?:people|persons?|travellers?|travelers?|pax)\b', text) and (not adults) and (not children):
        raise ValueError('How many adults and children are in that group? I will use their actual package rates.')
    attribute_question = bool(re.search(r'\b(?:which|compare|cheaper|cheapest|cost more)\b', text)) and (not re.search(r'\bonly\b', text))
    for component, term in [('accommodation', '(?:hotel|accommodation|overnight stay)'), ('transport', '(?:transport(?:ation)?|transfers?)'), ('guideActivities', '(?:guide|guided(?: (?:tours?|experience|sightseeing))?|reserved tickets|admission tickets)')]:
        if re.search(r'\b(?:without|no)\s+(?:a |an |any )?' + term + r'\b', text):
            filters[component] = False
        elif not attribute_question and re.search(r'\b(?:with|includes?|including|require|need|only).{0,20}\b' + term + r'\b', text):
            filters[component] = True
        if re.search(r'\b(?:remove|clear)\s+' + term + r'\s+(?:filter|requirement)\b', text):
            filters.pop(component, None)
    interest_text = re.sub(r'\b\d+\s*(?:adults?|children|child|kids?)\b', '', text, flags=re.I)
    interests = extract_interests(interest_text)
    if interests:
        filters['interests'] = interests
    excluded = extract_excluded_interests(message)
    if excluded:
        filters['excludedInterests'] = excluded
    if re.search(r'\b(?:discounted|discounts?|on sale|special offers?)\b', text) and (not attribute_question):
        filters['discountOnly'] = True
    if re.search(r'\b(?:any offers?|regular prices?|not only discounted|remove discount filter)\b', text):
        filters.pop('discountOnly', None)
    if re.search(r'\b(?:cheap|cheaper|cheapest|lowest price|price comparison)\b', text):
        filters['sort'] = 'price'
    code = re.search(r'\b(?:coupon|promo code|code)\s+([a-z0-9_-]{1,100})\b', text)
    if code:
        filters['promoCode'] = code[1].upper()
    if re.search(r'\b(?:remove|without|no) (?:the )?(?:coupon|code)\b', text):
        filters.pop('promoCode', None)
    return filters

def _operator(package, read):
    oid = package.get('operatorId')
    profile = read('users', oid) if oid else None
    if not isinstance(profile, dict):
        return None
    if profile.get('status', 'active') != 'active' or str(profile.get('role', '')).lower() not in {'operator', 'tourism_operator'} or str(profile.get('verificationStatus', '')).lower() not in {*APPROVED_OPERATOR_STATUSES}:
        return None
    return profile

def _discoverable(package):
    if not isinstance(package, dict) or not eligible_package(package) or package.get('deletedAt'):
        return False
    try:
        today = malaysia_today()
        if package.get('validFrom') and date.fromisoformat(package['validFrom']) > today:
            return False
        if package.get('validUntil') and date.fromisoformat(package['validUntil']) < today:
            return False
        dates = package.get('departureDates') or []
        if not isinstance(dates, list):
            return False
        parsed = [date.fromisoformat(d) for d in dates]
        return not parsed or any((d >= today for d in parsed))
    except (ValueError, TypeError, AttributeError):
        return False

def public_details(package_id, read):
    package = read('tourism_packages', package_id)
    profile = _operator(package, read) if _discoverable(package) else None
    if not profile:
        return None
    campaigns = read('promotional_campaigns', filters=[('operatorId', '==', package['operatorId'])]) or []
    return public_package(package, profile, [c for c in campaigns if active_campaign(c)])

def _concepts(package):
    return candidate_concepts({'title': package.get('title') or package.get('packageTitle'), 'category': package.get('category'), 'description': ' '.join((str(package.get(k) or '') for k in ('shortDescription', 'highlights', 'inclusions')))})

def search_packages(filters, read, uid, selected_ids=None):
    candidates = read('tourism_packages', filters=[('approvalStatus', '==', 'approved')], limit=CATALOGUE_LIMIT + 1) or []
    if not isinstance(candidates, list):
        raise ValueError('The package catalogue could not be verified.')
    limited = len(candidates) > CATALOGUE_LIMIT
    candidates = candidates[:CATALOGUE_LIMIT]
    campaigns = read('promotional_campaigns', filters=[('reviewStatus', '==', 'approved')]) or []
    preference = read('travel_preferences', uid) or {}
    learned = read('learned_preference_profiles', uid) or {}
    preference = effective_preference_profile(preference if isinstance(preference, dict) else {}, learned if isinstance(learned, dict) else {})
    preferred = concepts_for(filters.get('interests') or preference.get('interests') or [])
    excluded = concepts_for(filters.get('excludedInterests') or preference.get('excludedInterests') or [])
    if filters.get('interests') and 'excludedInterests' not in filters:
        excluded -= concepts_for(filters['interests'])
    party = filters.get('participants') or {}
    party_known = isinstance(party.get('adults'), int) and isinstance(party.get('children'), int)
    if party and (not party_known):
        raise ValueError('How many adults are travelling with the children?')
    profiles = {}
    rows = []
    unquotable = 0
    for package in candidates:
        if not isinstance(package, dict):
            continue
        pid = str(package.get('id') or '')
        if not pid:
            continue
        if selected_ids is not None and pid not in selected_ids:
            continue
        if not _discoverable(package):
            continue
        oid = package.get('operatorId')
        if oid not in profiles:
            profiles[oid] = _operator(package, read)
        if not profiles[oid]:
            continue
        location = ' '.join((str(package.get(k) or '') for k in ('destination', 'destinationName', 'destinationArea'))).lower()
        if filters.get('destination') and filters['destination'].lower() not in location:
            continue
        if filters.get('days') and str(package.get('durationDays')) != str(filters['days']):
            continue
        requirements = derive_required_services(package, review_optional_extras=True)
        services = {key: None if value['uncertain'] else value['required'] for key, value in requirements.items()}
        if any((key in filters and services[key] is not filters[key] for key in _FLAGS)):
            continue
        concepts = _concepts(package)
        if concepts & excluded or (filters.get('interests') and (not concepts & preferred)):
            continue
        dates = sorted((d for d in package.get('departureDates') or [] if d >= malaysia_today().isoformat()))
        departure = filters.get('startDate') or (dates[0] if dates else None)
        if filters.get('endDate') and departure and package.get('durationDays'):
            if (date.fromisoformat(departure) + timedelta(days=int(package['durationDays']) - 1)).isoformat() > filters['endDate']:
                continue
        try:
            requested = party if party_known else {'adults': max(1, int(package.get('minimumTravellers') or 1)), 'children': 0}
            snapshot = prepare_package_snapshot(package, profiles[oid], participants=requested, departure_date=departure, campaigns=campaigns, promo_code=filters.get('promoCode', ''))
        except (ValueError, TypeError, OverflowError):
            unquotable += 1
            continue
        quote = snapshot['pricingBreakdown']
        amount = Decimal(str(quote['finalPayable']))
        if 'budgetMax' in filters and (amount >= Decimal(str(filters['budgetMax'])) if filters.get('budgetStrict') else amount > Decimal(str(filters['budgetMax']))):
            continue
        if filters.get('discountOnly') and quote['promotionDiscount'] <= 0:
            continue
        projected = public_package(package, profiles[oid], [c for c in campaigns if active_campaign(c)])
        card = {key: projected[key] for key in ('id', 'title', 'packageTitle', 'destination', 'destinationName', 'destinationArea', 'heroImage', 'imageUrl', 'durationDays', 'durationNights', 'operatorName', 'availabilityStatus', 'priceBasis', 'minimumTravellers', 'maximumTravellers') if key in projected}
        card['inclusions'] = [str(line)[:240] for line in (projected.get('inclusions') or [])[:4]]
        card['inclusionsTruncated'] = len(projected.get('inclusions') or []) > 4 or any(len(str(line)) > 240 for line in projected.get('inclusions') or [])
        quote = deepcopy(quote)
        terms = str(quote['promotion'].get('termsConditions') or '')
        if len(terms) > 700:
            quote['promotion']['termsConditions'] = terms[:700] + '…'
        card.update(chatQuote=quote, quoteContext={'partyKnown': party_known, 'dateKnown': bool(filters.get('startDate')), 'isReference': not party_known or not filters.get('startDate'), 'termsTruncated': len(terms) > 700, 'participants': snapshot['participants'], 'departureDate': departure, 'quotedAt': snapshot['snapshotCreatedAt'], 'pricingVersion': 'campaigns_v1'}, serviceInclusions=services, matchedInterests=sorted(concepts & preferred))
        rows.append(card)
    rows.sort(key=lambda row: (0 if filters.get('sort') == 'price' else -len(row['matchedInterests']), Decimal(str(row['chatQuote']['finalPayable'])), row['id']))
    if selected_ids is not None:
        rows.sort(key=lambda row: selected_ids.index(row['id']))
    return (rows, {'catalogueLimited': limited, 'unquotableCount': unquotable, 'matchedCount': len(rows)})

def owned_context(message, read, uid):
    if re.search(r'\b(?:saved trips|show my trips|list my trips)\b', message, re.I):
        records = read('itineraries', filters=[('travellerId', '==', uid)], limit=21) or []
        trips = [{k: r.get(k) for k in ('id', 'title', 'destinationArea', 'startDate', 'endDate', 'tripType')} for r in records if r.get('travellerId') == uid][:20]
        return {'reply': 'Here are up to 20 of your saved trips.' if trips else 'No saved trips were found for your account.', 'ownedTrips': trips}
    orders = read('checkout_orders', filters=[('travellerId', '==', uid), ('quoteType', '==', 'package')], limit=21) or []
    safe = []
    for order in orders:
        if order.get('travellerId') != uid or order.get('quoteType') != 'package':
            continue
        context, trip = load_context(order, read)
        overview, _ = status_overview(order, context, order.get('fulfillmentRecord'), trip)
        amount, currency = record_money(order)
        snapshot = order.get('packageSnapshot') or {}
        safe.append({'orderId': order['id'], 'title': snapshot.get('title') or 'Package purchase', 'amount': amount, 'currency': currency, 'paymentStatus': order.get('paymentStatus') or 'unknown', 'orderStatus': order.get('status') or 'unknown', 'statusOverview': overview, 'pricingBreakdown': public_pricing_breakdown(snapshot.get('pricingBreakdown')), 'departureDate': snapshot.get('selectedDepartureDate')})
    return {'reply': 'Here are up to 20 of your recorded package orders. Payment, trip creation and supplier arrangements are separate statuses; recorded arrangements are not independent supplier confirmation.' if safe else 'No package orders were found for your account.', 'ownedOrders': safe[:20]}

def respond(message, state, read, uid):
    action = conversation_action(message, state)
    if action == 'itinerary':
        if state.get('assistantMode') in {'packages', 'owned', 'clarify'}:
            preserved = {k: state[k] for k in ('savedPlans', 'activePlan', 'commerceRevision') if k in state}
            state.clear()
            state.update(preserved)
        state['assistantMode'] = 'itinerary'
        state.pop('packageSearch', None)
        return None
    if action is None:
        return None
    revision = state.get('commerceRevision', 0)
    state['commerceRevision'] = (revision if isinstance(revision, int) else 0) + 1
    if action == 'clarify':
        state['assistantMode'] = 'clarify'
        state.pop('packageSearch', None)
        return {'reply': 'Would you like to find an actual Operator tourism package, or plan your own independent itinerary?', 'assistantMode': 'clarify'}
    if action == 'owned':
        state['assistantMode'] = 'owned'
        try:
            return {**owned_context(message, read, uid), 'assistantMode': 'owned'}
        except Exception:
            return {'reply': 'I could not verify your saved records just now. Please retry. No booking or payment has been changed.', 'assistantMode': 'owned', 'dataUnavailable': True}
    previous = state.get('packageSearch') if state.get('assistantMode') == 'packages' else {}
    previous = previous if isinstance(previous, dict) else {}
    state['assistantMode'] = 'packages'
    try:
        filters = update_filters(message, previous)
    except ValueError as error:
        return {'reply': str(error), 'assistantMode': 'packages', 'clarificationRequired': True}
    state['packageSearch'] = filters
    compare = bool(re.search(r'\b(?:compare|which|cheaper|cheapest|cost more)\b', message, re.I)) and bool(previous.get('resultIds'))
    selected = None
    if compare:
        ids = previous['resultIds']
        ordinals = [index for word, index in [('first', 0), ('second', 1), ('third', 2)] if re.search(r'\b' + word + r'\b', message, re.I)]
        selected = [ids[i] for i in ordinals if i < len(ids)] if ordinals else ids
    try:
        rows, meta = search_packages(filters, read, uid, selected)
    except ValueError as error:
        return {'reply': str(error), 'assistantMode': 'packages', 'clarificationRequired': True}
    except Exception:
        return {'reply': 'The live package catalogue or prices could not be verified. Please retry; I have not invented any package or offer.', 'assistantMode': 'packages', 'dataUnavailable': True, 'packages': []}
    filters['resultIds'] = [row['id'] for row in rows[:RESULT_LIMIT]]
    reply = f"I found {len(rows)} matching published package{('s' if len(rows) != 1 else '')}. Prices come from TravelMate's current package quote contract."
    if len(rows) > RESULT_LIMIT:
        reply += f' Showing the first {RESULT_LIMIT}; comparisons refer to these displayed packages.'
    if not rows:
        reply = 'No published packages match all verified filters. Try another area, travel date, party size or budget, or remove an inclusion requirement.'
    if meta['unquotableCount']:
        reply += ' Some packages could not supply a supported quote for this selection and were excluded.'
    if meta['catalogueLimited']:
        reply += f' This search inspected at most {CATALOGUE_LIMIT} approved records; further matches may exist outside this scan.'
    if rows and any((r['quoteContext']['isReference'] for r in rows)):
        reply += ' Reference party/departure conditions are shown on each card; tell me your adults, children and travel date for a specific quote.'
    if compare and selected is not None and (len(rows) != len(selected)):
        reply += ' An earlier selection is no longer eligible; it has not been replaced with a different package.'
    elif compare and rows:
        reply += ' Inclusion comparisons are shown on each card as included, not included or unknown. Package inclusions are promises, not evidence of supplier reservations.'
        if not all((r['quoteContext']['partyKnown'] for r in rows)):
            reply += ' These reference parties may differ; give adult/child counts for a like-for-like price comparison.'
        else:
            cheapest = min(rows, key=lambda row: (Decimal(str(row['chatQuote']['finalPayable'])), row['id']))
            reply += f" The lowest current party total among these is {cheapest['title']}: MYR {cheapest['chatQuote']['finalPayable']:.2f}."
    return {'reply': reply, 'assistantMode': 'packages', 'packages': rows[:RESULT_LIMIT], 'packageSearch': filters, 'searchEvidence': meta, 'priceNotice': 'Quotes reflect this response. View Details refreshes the public record; checkout revalidates prices and offer terms. No booking, supplier reservation or payment session was created.'}
