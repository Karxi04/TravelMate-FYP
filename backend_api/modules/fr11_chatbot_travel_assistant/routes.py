from flask import Blueprint, request, jsonify, g, current_app
from auth_utils import auth_required
from utils import utc_now_iso
from services.gemini_service import generateChatbotResponse, generateFollowUpResponse, interpretChatbotIntent
from sequence_contract.validators import validateQuestion
from sequence_contract.firebase_firestore import retrieveRecord, storeRecord, deleteRecord, updateRecord, claimRecord
from sequence_contract.domain_functions import createItinerary, calculateBudget, recalculateItinerary
from services.activity_pricing import pricing_snapshot, refresh_activity_costs
from services.local_catalog import DESTINATIONS
from services.preference_learning import effective_preference_profile
from services.malaysian_locality import normalize_candidate_geography, normalize_destination_scope
from services.recommendation_taxonomy import candidate_concepts, concepts_for, display_concepts
from services.review_service import published_review
from .nlp_extractor import (
    extract_geographic_entities,
    extract_duration,
    extract_budget,
    extract_travellers,
    extract_dates,
    extract_interests,
    extract_excluded_interests,
    extract_excluded_activity_types,
    extract_indoor_preference,
    extract_day_specific,
    extract_itinerary_day,
    extract_activity_position,
    itinerary_view_request,
    clean_text,
    classify_user_intent,
    classify_detailed_intent,
    conversational_question,
    check_requirement_completeness,
    build_structured_trip_plan,
    validate_save_plan_payload,
    find_matching_catalog_destinations,
    filter_constraint_candidates,
)
from .guided_planning import guided_requirements
from .contextual_intent import resolve_turn, prompt_context, remember_results, decorate_reply, place_cards
from .history_conversation import is_history_request, history_turn
from services.itinerary_history import HistoryConflict, restore_patch
from .travel_dates import malaysian_today
from services.review_service import ReviewConflict
from .package_assistant import respond as commerce_response, public_details
from .personal_questions import respond as personal_response, PersonalReadUnavailable
import re
import os
import json
import hashlib
from copy import deepcopy
from services.serpapi_service import retrieveDestinationResults
from datetime import date, timedelta

bp = Blueprint('fr11_chatbot', __name__, url_prefix='/api/fr11')


@bp.errorhandler(HistoryConflict)
def history_conflict(error):
    return jsonify(ok=False, error=str(error)), 409


def _plan_id(plan):
    content = {key: value for key, value in plan.items() if key != 'draftId'}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode('utf-8')).hexdigest()[:24]


def _show_plan_request(message):
    return itinerary_view_request(message)


def _session_title(message):
    title = ' '.join(str(message or '').strip().split())
    return title[:42] if title else 'New travel chat'


def _constraint_acknowledgement(planning_state):
    labels = list(planning_state.get('excludedInterests') or [])
    labels += list(planning_state.get('excludedActivityTypes') or [])
    if planning_state.get('preferIndoor'):
        labels.append('indoor-only')
    destination = planning_state.get('destinationArea') or 'the selected destination'
    return (
        f"I have applied these hard constraints for {destination}: {', '.join(labels)}. "
        "Every structured plan and place suggestion will enforce them. If no verified activity satisfies "
        "all constraints, I will report a conflict instead of inserting a prohibited substitute."
    )


def _unsupported_road_trip_reply(planning_state):
    origin = planning_state.get('originDestination') or 'the origin'
    target = planning_state.get('targetDestination') or 'the destination'
    return (
        f"I understand that you want a road trip from {origin} to {target}. TravelMate currently creates "
        "verified itineraries for one destination at a time, so I have not generated or exposed a "
        "save-ready single-city plan for this multi-destination request. Please choose which city to plan "
        "first, and I can create separate city itineraries while preserving your other trip preferences."
    )


def _destination_change_reply(planning_state):
    return (
        f"I have changed the active destination to {planning_state.get('destinationArea')} and kept the "
        "other validated trip preferences. The refreshed itinerary now uses that destination."
    )


def _clear_multi_destination_state(planning_state):
    planning_state['tripMode'] = 'single_destination'
    for key in ('multipleDestinations', 'originDestination', 'targetDestination'):
        planning_state.pop(key, None)


def _session_ref(session_id=None):
    if session_id:
        session = retrieveRecord('chat_sessions', session_id)
        if session and session.get('travellerId') == g.uid:
            return session
    return None


def _new_session(title='New travel chat'):
    now = utc_now_iso()
    return storeRecord('chat_sessions', {
        'travellerId': g.uid,
        'title': title or 'New travel chat',
        'messages': [],
        'planningState': {},
        'createdAt': now,
        'updatedAt': now,
    })


def _sorted_sessions():
    sessions = retrieveRecord('chat_sessions', filters=[('travellerId', '==', g.uid)]) or []
    sessions.sort(key=lambda x: str(x.get('updatedAt') or x.get('createdAt') or ''), reverse=True)
    return sessions


def _context(session=None):
    session = session or {}
    return 'Relevant conversation context (not reservation proof): ' + prompt_context(
        session.get('planningState') or {}, session.get('messages') or [])


def _extract_plan_from_message(message, planning_state=None):
    state = dict(planning_state or {})
    geo = extract_geographic_entities(message)

    # Reject foreign destinations from plan generation
    if geo.get('is_foreign') or geo.get('is_multi_destination') or state.get('tripMode') == 'road_trip':
        return None

    dest = geo.get('destination_area') or state.get('destinationArea')
    dest_state = geo.get('destination_state') or state.get('destinationState')

    # If destination is unknown or user query is not planning, do not generate arbitrary plan
    intent = classify_user_intent(message, state)
    if intent not in {'PLANNING_REQUEST', 'PROVISIONAL_EXPLORATION'} and not any(k in message.lower() for k in ['plan', 'itinerary', 'trip']):
        return None

    if not dest:
        # Check if user mentioned Penang specifically or fallback
        if 'penang' in message.lower():
            dest = 'Penang'
            dest_state = 'Penang'
        else:
            return None

    dur = extract_duration(message, state.get('tripDays', 3))
    bud = extract_budget(message, state.get('budgetLimit', 1200.0))
    trav = extract_travellers(message, state.get('travellerCount', 1))
    try:
        s_date, e_date = extract_dates(message, dur or 3, state.get('startDate'), state.get('endDate'))
    except ValueError:
        return None
    if s_date and e_date:
        dur = (date.fromisoformat(e_date) - date.fromisoformat(s_date)).days + 1
    ints = extract_interests(message, state.get('interests', []))
    ex_ints = extract_excluded_interests(message, state.get('excludedInterests', []))
    ex_types = extract_excluded_activity_types(message, state.get('excludedActivityTypes', []))
    indoor = extract_indoor_preference(message, state.get('preferIndoor', False))

    plan, status = build_structured_trip_plan(
        destination_area=dest,
        destination_state=dest_state,
        days=dur or 3,
        budget_limit=bud or 1200.0,
        traveller_count=trav or 1,
        start_date=s_date,
        end_date=e_date,
        interests=ints,
        excluded_interests=ex_ints,
        excluded_activity_types=ex_types,
        prefer_indoor=indoor,
    )
    return plan if status == 'ready' else None


def _extract_place_suggestions(message, destination_area=None, prefer_indoor=False,
                               excluded_interests=None, excluded_activity_types=None):
    q = str(message or '').lower()
    triggers = ['food', 'eat', 'restaurant', 'place', 'attraction', 'visit', 'recommend', 'where', 'suggest', 'sight', 'see', 'things to do', 'activities']
    if not any(t in q for t in triggers):
        return []

    # If destination is known, isolate suggestions strictly to that destination
    if destination_area:
        candidates = find_matching_catalog_destinations(destination_area)
    else:
        candidates = DESTINATIONS

    if not candidates:
        return []

    # Recognize active rain / wet weather / indoor request using bounded word matching or passed preference
    is_rain_indoor = prefer_indoor or bool(re.search(
        r'\b(?:rain|rains|rainy|raining|downpour|thunderstorm|wet\s+weather|indoor|sheltered)\b',
        q
    ))

    candidates = filter_constraint_candidates(
        candidates,
        excluded_interests=excluded_interests,
        excluded_activity_types=excluded_activity_types,
        prefer_indoor=is_rain_indoor,
    )
    if not candidates:
        return []

    matches = []
    ignore_terms = {
        'what', 'where', 'when', 'which', 'there', 'some', 'good', 'best',
        'visit', 'places', 'place', 'attraction', 'attractions', 'recommend',
        'suggest', 'rain', 'rains', 'rainy', 'raining', 'weather', 'indoor'
    }
    substantive_terms = [
        term.strip('?,.!') for term in q.split()
        if len(term.strip('?,.!')) > 3 and term.strip('?,.!') not in ignore_terms
    ]

    for d in candidates:
        combined = f"{d.get('title', '')} {d.get('address', '')} {d.get('category', '')} {d.get('description', '')}".lower()
        if substantive_terms:
            if any(term in combined for term in substantive_terms):
                matches.append(d)
        else:
            matches.append(d)

    if not matches and is_rain_indoor:
        matches = candidates

    return place_cards(matches, {'excludedInterests': excluded_interests,
        'excludedActivityTypes': excluded_activity_types, 'preferIndoor': is_rain_indoor})[:4]


def _planning_catalog(area, state, interests=None, *, allow_provider=True):
    scope = normalize_destination_scope(area)
    cached = retrieveRecord('destination_cache',
                            filters=[('canonicalDestinationScope', '==', scope.get('scopeKey'))],
                            limit=150) or []
    catalog = DESTINATIONS
    if cached:
        from services.activity_pricing import PRICING_FIELDS
        by_id = {str(row.get('destinationId') or row.get('place_id')):
                 {**row, 'ratingSource': 'unverified_local_catalog'} for row in DESTINATIONS}
        for candidate in cached:
            key = str(candidate.get('destinationId') or candidate.get('place_id') or '')
            if not key:
                continue
            base = by_id.get(key, {})
            merged = {**base, **{k: v for k, v in candidate.items() if v not in (None, '', [], {})}}
            if base.get('pricingUnit') or 'unitPrice' in base:
                merged.update({key: base[key] for key in PRICING_FIELDS if key in base})
            by_id[key] = merged
        catalog = list(by_id.values())
    matching = find_matching_catalog_destinations(area, state, catalog)
    food_focus = concepts_for(interests or []) == {'food'}
    needs_search = not matching or (food_focus and not any('food' in candidate_concepts(row) for row in matching))
    if allow_provider and needs_search and os.getenv('SERPAPI_KEY', '').strip():
        try:
            query = 'local food and hawker centres' if food_focus else 'tourist attractions'
            result = retrieveDestinationResults(f'{query} in {area}', area)
            catalog = [*catalog, *(result.get('local_results') or [])]
        except Exception:
            pass
    return catalog


def _activity_preview(state):
    area, region = state['destinationArea'], state.get('destinationState')
    matches = find_matching_catalog_destinations(area, region, _planning_catalog(area, region, state.get('interests')))
    candidates = filter_constraint_candidates(matches, excluded_interests=state.get('excludedInterests'),
        excluded_activity_types=state.get('excludedActivityTypes'), prefer_indoor=state.get('preferIndoor', False))
    if not candidates:
        return f'I don’t have verified activities for {area} that fit these details yet. You can adjust your preferences or choose another destination.', []
    interests = concepts_for(state.get('interests') or [])
    ranked = sorted(candidates, key=lambda row: len(interests & candidate_concepts(row)), reverse=True)
    half_day = state.get('activityWindow') == 'half_day'
    days = state.get('tripDays')
    limit = 2 if half_day else min(6, max(3, days * 2)) if days else 4
    suggestions = []
    seen = set()
    for row in ranked:
        identity = row.get('destinationId') or row.get('place_id')
        if not identity or identity in seen or not (row.get('title') or row.get('name')):
            continue
        seen.add(identity)
        geography = normalize_candidate_geography(row)
        display = {key: row[key] for key in (
            'destinationId', 'place_id', 'title', 'name', 'address', 'category', 'type', 'description',
            'thumbnail', 'imageUrl', 'photoAttribution', 'imageSource', 'estimatedCost', 'currency', 'familyFriendly',
            'openingHoursSourceUrl', 'openingHoursVerifiedAt',
        ) if isinstance(row.get(key), (str, int, float))}
        if geography['latitude'] is not None and geography['longitude'] is not None:
            display['gps_coordinates'] = {'latitude': geography['latitude'], 'longitude': geography['longitude']}
        duration = row.get('recommendedDurationMinutes')
        if type(duration) is int and duration > 0:
            display['recommendedDurationMinutes'] = duration
        display['matchedInterests'] = display_concepts(interests & candidate_concepts(row))
        suggestions.append({**display, **pricing_snapshot(row), 'state': geography['state'], 'city': geography['city']})
        if len(suggestions) >= limit:
            break
    if not suggestions:
        return f'I don’t have a verified activity card for {area} yet. You can choose another destination.', []
    window = 'half-day' if half_day else f'{days}-day' if days else 'flexible'
    reply = f'Here are {window} activity ideas for {area}.'
    if interests and not any(row['matchedInterests'] for row in suggestions):
        reply += ' I found limited matches for your interests, so these are nearby ideas within the selected destination.'
    if half_day:
        reply += ' Start with one stop and add another if you have time.'
    return reply, suggestions


def _destination_discovery(message, planning_state):
    profile = retrieveRecord('travel_preferences', g.uid) or {}
    interests = extract_interests(message)
    if not interests and re.search(r'\b(?:couples?|romantic)\b', message, re.I):
        interests = ['Relaxation']
    interests = interests or planning_state.get('interests') or profile.get('interests') or []
    desired = concepts_for(interests)
    geo = extract_geographic_entities(message)
    scope = geo.get('destination_area') or 'Malaysia'
    if scope == 'Malaysia':
        candidates = [row for row in DESTINATIONS if normalize_candidate_geography(row).get('state')
                      and not normalize_candidate_geography(row).get('conflict')]
    else:
        candidates = find_matching_catalog_destinations(scope, geo.get('destination_state'),
                                                        _planning_catalog(scope, geo.get('destination_state'), interests))
    if not desired:
        return {'reply': 'What would you enjoy most: local food, heritage, nature, or a relaxed outing?',
                'suggestedReplies': ['Recommend somewhere for local food', 'Recommend somewhere peaceful',
                                     'Recommend somewhere for nature']}
    scored = [(candidate_concepts(row) & desired, row) for row in candidates]
    scored.sort(key=lambda match: (-len(match[0]), str(match[1].get('title') or '')))
    matches = []
    for matched, row in scored:
        if not matched or not row.get('destinationId') or not row.get('title'):
            continue
        cards = place_cards([row], planning_state, interests)
        if not cards:
            continue
        matches.append(cards[0])
        matches[-1]['matchedInterests'] = display_concepts(matched)
        if len(matches) == 4:
            break
    return {'reply': ('Here are a few Malaysian places that match those interests. Check each place for hours and costs.'
                      if matches else 'I couldn’t verify places that fit those interests in the requested area. Try another area.'),
            'placeSuggestions': matches}


def _trip_fingerprint(trip):
    return hashlib.sha256(json.dumps(trip, default=str, sort_keys=True).encode()).hexdigest()


def _trip_context(trip):
    return {**{key: trip[key] for key in ('destinationArea', 'destinationState', 'startDate', 'endDate',
                                      'budgetLimit', 'travellerCount') if key in trip},
            'itineraryRevision': trip.get('itineraryRevision', 1),
            'retainedVersions': [r['version'] for r in trip.get('itineraryHistory') or []]}


def _saved_activities(trip):
    activities = trip.get('activities')
    if not isinstance(activities, list) or not activities:
        activities = [{**activity, 'dayNo': row.get('dayNo', row.get('dayNumber'))}
                      for row in (trip.get('dailySchedule') or []) if isinstance(row, dict)
                      for activity in (row.get('activities') or []) if isinstance(activity, dict)]
    return [deepcopy(a) for a in activities if isinstance(a, dict)]


def _comparison_summary(saved, proposed):
    days = sorted({int(a['dayNo']) for trip in (saved, proposed) for a in _saved_activities(trip)
                   if str(a.get('dayNo', '')).isdigit()})
    lines = ['Saved itinerary compared with the unconfirmed proposal:']
    for day in days:
        old = [a for a in _saved_activities(saved) if str(a.get('dayNo')) == str(day)]
        new = [a for a in _saved_activities(proposed) if str(a.get('dayNo')) == str(day)]
        if old == new:
            lines.append(f'Day {day}: unchanged.')
        else:
            def stops(activities):
                return ', '.join(str(a.get('activityName') or 'Unnamed stop') +
                    (f' ({a["timeSlot"]})' if a.get('timeSlot') else '') for a in activities) or 'no stops'
            lines.append(f'Day {day}: changed from {stops(old)} to {stops(new)}. Check the previews for times and details.')
    for key, label in (('budgetLimit', 'Total trip budget'), ('startDate', 'Start date'), ('endDate', 'End date'),
                       ('travellerCount', 'Traveller count'), ('destinationArea', 'Destination')):
        if saved.get(key) != proposed.get(key):
            lines.append(f'{label}: {saved.get(key, "unset")} -> {proposed.get(key, "unset")}.')
    return '\n'.join([*lines, 'Nothing is saved until you explicitly confirm.'])


def _saved_trip_preview(trip, day=None):
    preview = {key: deepcopy(trip[key]) for key in (
        'title', 'destinationArea', 'destinationState', 'startDate', 'endDate', 'budgetLimit',
        'budgetEstimate', 'travellerCount', 'numberOfTravellers', 'tripDays') if key in trip}
    activities = _saved_activities(trip)
    preview.update(viewOnly=True, savedTripId=trip['id'], activities=[deepcopy(a) for a in activities
                   if isinstance(a, dict) and (day is None or str(a.get('dayNo')) == str(day))])
    if day is not None:
        preview['previewDay'] = day
    return preview


def _day_activities(draft, trip_id, day, operation, position, interests):
    """Prepare only the selected day's activities; reuse the existing verified planner."""
    current = _saved_activities(draft)
    selected = [a for a in current if str(a.get('dayNo')) == str(day)]
    if position is not None and not 1 <= position <= len(selected):
        return None, f'That activity is not on Day {day}. Which saved activity should I change?'
    affected = [selected[position - 1]] if position is not None else selected
    if any(a.get(key) for a in affected for key in ('bookingId', 'supplierArrangementId', 'checkoutOrderId')):
        return None, 'That activity has booking details attached. Review it in Trip Details before changing it.'
    if operation == 'remove':
        revised = [a for a in selected if a not in affected]
    elif operation == 'relax':
        revised = selected[:2]
    else:
        used = {a.get('destinationId') for a in current}
        names = {clean_text(a.get('activityName')) for a in current}
        requested = concepts_for(interests or [])
        catalog = [a for a in _planning_catalog(draft['destinationArea'], draft.get('destinationState'), interests)
                   if (a.get('destinationId') or a.get('place_id')) not in used
                   and clean_text(a.get('title') or a.get('name')) not in names
                   and (not requested or candidate_concepts(a) & requested)]
        target_date = (date.fromisoformat(str(draft['startDate'])[:10]) + timedelta(days=day - 1)).isoformat()
        planned, status = build_structured_trip_plan(
            draft['destinationArea'], draft.get('destinationState'), days=1,
            budget_limit=draft.get('budgetLimit'), traveller_count=draft.get('travellerCount') or 1,
            start_date=target_date, end_date=target_date, interests=interests,
            excluded_interests=draft.get('excludedInterests'), excluded_activity_types=draft.get('excludedActivityTypes'),
            prefer_indoor=draft.get('preferIndoor', False), catalog=catalog,
            preference_profile={key: draft[key] for key in ('travelPace', 'travelPersonality') if key in draft})
        if status != 'ready' or not planned.get('activities'):
            return None, f'I could not verify an unused activity for Day {day} that fits. Your saved trip is unchanged; try another theme.'
        count = 1 if operation in {'add', 'replace'} else max(1, min(len(selected), 3))
        replacements = [{**a, 'dayNo': day, 'activityId': 'chat_' + _plan_id({'trip': trip_id, 'day': day, 'place': a['destinationId']})}
                        for a in planned['activities'][:count]]
        revised = (selected + replacements if operation == 'add' else
                   selected[:position - 1] + replacements + selected[position:] if position is not None else replacements)
    return [a for a in current if str(a.get('dayNo')) != str(day)] + revised, None


def _adjust_trip(message, state):
    request_adjustment = bool(re.search(
        r'\b(?:adjust|edit|revise|modify) (?:my|an existing|a saved) (?:itinerary|trip)\b', message, re.I))
    if request_adjustment:
        saved = state.get('savedPlans')
        revision = state.get('commerceRevision')
        state.clear()
        if saved:
            state['savedPlans'] = saved
        if revision is not None:
            state['commerceRevision'] = revision
        trips = retrieveRecord('itineraries', filters=[('travellerId', '==', g.uid)], limit=20) or []
        eligible = [trip for trip in trips if trip.get('travellerId') == g.uid
                    and trip.get('id') and not trip.get('packageTrip') and trip.get('tripType') != 'package']
        if not eligible:
            return {'reply': 'You have no editable saved trips. Open Trips to create or find a plan.'}
        if len(eligible) > 1:
            state['adjustment'] = {'choices': [trip['id'] for trip in eligible]}
            labels = [f"{i}. {trip.get('title') or 'Trip'} ({trip.get('startDate') or 'dates unset'})"
                      for i, trip in enumerate(eligible, 1)]
            return {'reply': 'Which saved trip do you want to adjust? Reply with its number.\n' + '\n'.join(labels),
                    'suggestedReplies': [f'Adjust trip {i}' for i in range(1, min(5, len(labels)) + 1)]}
        state['adjustment'] = {'tripId': eligible[0]['id'], 'fingerprint': _trip_fingerprint(eligible[0]),
                               'tripContext': _trip_context(eligible[0])}
        return {'reply': f"What would you like to change in {eligible[0].get('title') or 'your saved trip'}? "
                         'You can change the budget, dates, duration, activities, destination or pace.'}
    adjustment = state.get('adjustment')
    if not adjustment:
        if is_history_request(message):
            return {'reply': 'Select the saved trip whose history you want to inspect or restore.',
                    'suggestedReplies': ['Adjust my saved trip']}
        return None
    if re.match(r'(?:plan|create|start) (?:a )?new (?:trip|itinerary)', message, re.I):
        state.pop('adjustment', None)
        state.pop('activePlan', None)
        return None
    if re.fullmatch(r'(?:cancel|stop)(?: (?:the )?(?:adjustment|changes|editing))?[.!]?|'
                    r'(?:never\s*mind|nvm|leave it unchanged)[.!]?', message, re.I):
        state.pop('adjustment', None)
        state.pop('activePlan', None)
        return {'reply': 'The adjustment draft was discarded. Your saved trip is unchanged.'}
    if 'choices' in adjustment:
        match = re.fullmatch(r'(?:adjust trip\s+)?(\d{1,2})[.!]?', message, re.I)
        if not match or not 1 <= int(match[1]) <= len(adjustment['choices']):
            return {'reply': 'Reply with the number of the saved trip you want to adjust.'}
        state['adjustment'] = adjustment = {'tripId': adjustment['choices'][int(match[1]) - 1]}
        selected_now = True
    else:
        selected_now = False
    trip = retrieveRecord('itineraries', adjustment['tripId'])
    if not trip or trip.get('travellerId') != g.uid or trip.get('packageTrip') or trip.get('tripType') == 'package':
        state.pop('adjustment', None)
        state.pop('activePlan', None)
        return {'reply': 'That trip is no longer available for editing.'}
    if selected_now:
        adjustment['fingerprint'] = _trip_fingerprint(trip)
        adjustment['tripContext'] = _trip_context(trip)
        return {'reply': f"What would you like to change in {trip.get('title') or 'this trip'}?"}
    fingerprint = _trip_fingerprint(trip)
    changed_elsewhere = adjustment.get('fingerprint', fingerprint) != fingerprint
    if changed_elsewhere:
        state['adjustment'] = adjustment = {'tripId': trip['id'], 'fingerprint': fingerprint, 'tripContext': _trip_context(trip)}
        state.pop('activePlan', None)
    if (state.get('activePlan') or {}).get('draftId') == trip.get('lastChatAdjustmentId') and trip.get('lastChatAdjustmentId'):
        state.pop('activePlan', None)
        adjustment.pop('patch', None)
    historical = history_turn(message, trip, state, compare=_comparison_summary, read=retrieveRecord)
    if historical is not None:
        return historical
    if re.search(r'\b(?:undo|discard (?:the )?(?:draft|unconfirmed changes))\b', message, re.I):
        had_draft = bool(state.get('activePlan') or adjustment.get('patch'))
        state.pop('activePlan', None)
        state['adjustment'] = {key: value for key, value in adjustment.items()
                               if key not in {'patch', 'pendingPreferences', 'pendingActivity', 'pendingOperation', 'pendingExplanation', 'pendingHistoryDay'}}
        return {'reply': ('The unconfirmed changes were discarded. Your saved trip is unchanged.' if had_draft else
                          'There is no unconfirmed proposal to undo. Your saved trip is unchanged.'),
                'tripPlan': _saved_trip_preview(trip)}
    if re.search(r'\bcompare\b', message, re.I) and re.search(r'\b(?:saved|old|original|proposed|revision)\b', message, re.I):
        if not changed_elsewhere and state.get('activePlan'):
            return {'reply': _comparison_summary(trip, state['activePlan']),
                    'tripPlan': _saved_trip_preview(trip), 'proposedPlan': state['activePlan']}
        return {'reply': 'There is no current proposal to compare. Your saved trip is unchanged.', 'tripPlan': _saved_trip_preview(trip)}
    if _show_plan_request(message):
        if re.search(r'\b(?:draft|revision|proposed changes)\b', message, re.I) and not changed_elsewhere:
            if state.get('activePlan'):
                return {'reply': 'Here are the proposed changes. Your saved trip has not been updated.',
                        'tripPlan': state['activePlan']}
            return {'reply': 'There is no proposed revision yet. What would you like to change?'}
        day = extract_itinerary_day(message)
        if day is not None:
            try:
                count = (date.fromisoformat(str(trip['endDate'])[:10]) - date.fromisoformat(str(trip['startDate'])[:10])).days + 1
            except (KeyError, ValueError, TypeError):
                count = max([extract_itinerary_day('day ' + str(a.get('dayNo'))) or 0
                             for a in _saved_trip_preview(trip)['activities']] or [0])
            if not 1 <= day <= count:
                return {'reply': 'That day is outside the saved trip. Which itinerary day would you like to see?'}
            adjustment['viewDay'] = day
        prefix = 'The saved trip changed elsewhere; the earlier draft was discarded. ' if changed_elsewhere else ''
        return {'reply': prefix + (f'Here is the saved Day {day} itinerary.' if day else 'Here is your saved itinerary.')
                         + ' This is read-only; nothing has been changed.',
                'tripPlan': _saved_trip_preview(trip, day)}
    if changed_elsewhere:
        return {'reply': 'The saved trip changed elsewhere. Tell me what to revise using its latest details.'}
    if re.search(r'\bwhy\b', message, re.I) and re.search(r'\b(?:activity|stop|place|recommended|picked|chosen)\b', message, re.I):
        day = extract_itinerary_day(message) or adjustment.get('pendingDay') or adjustment.get('viewDay')
        position = extract_activity_position(message) or adjustment.get('pendingActivity')
        source = {**trip, **adjustment.get('patch', {})} if re.search(r'\b(?:proposed|draft|new)\b', message, re.I) else trip
        options = [a for a in _saved_activities(source) if day is None or str(a.get('dayNo')) == str(day)]
        if day is None or position is None or not 1 <= position <= len(options):
            adjustment['pendingExplanation'] = {'day': day, 'position': position}
            return {'reply': f'Which activity on Day {day} would you like me to explain?' if day else
                             'Which itinerary day would you like me to explain?'}
        if state.get('activePlan') and not re.search(r'\b(?:saved|original|old|proposed|draft|new)\b', message, re.I):
            proposed = [a for a in _saved_activities({**trip, **adjustment.get('patch', {})}) if str(a.get('dayNo')) == str(day)]
            if len(proposed) != len(options) or proposed[position - 1].get('destinationId') != options[position - 1].get('destinationId'):
                adjustment['pendingExplanation'] = {'day': day, 'position': position}
                return {'reply': 'Do you mean the saved activity or its proposed replacement?'}
        adjustment.pop('pendingExplanation', None)
        activity = options[position - 1]
        reason = activity.get('recommendationReason')
        if not isinstance(reason, str) or not reason:
            matched = display_concepts(candidate_concepts(activity) & concepts_for(source.get('interests') or []))
            reason = f'Matches the recorded interests: {", ".join(matched)}.' if matched else 'No specific recommendation reason is stored.'
        return {'reply': f'{activity.get("activityName") or "This saved activity"}: {reason}'}
    if re.search(r'\b(?:back|return|resume|continue)\b.*\b(?:trip|editing|adjustment|day)\b', message, re.I):
        day = adjustment.get('pendingDay') or adjustment.get('viewDay')
        return {'reply': f'What would you like to change on Day {day}?' if day else
                         'Which day or activity would you like to change?'}
    if conversational_question(message) or classify_detailed_intent(message) in {
            'WEATHER_ENQUIRY', 'HOTEL_ENQUIRY', 'FLIGHT_ENQUIRY', 'CAR_RENTAL_ENQUIRY', 'FEATURE_EXPLANATION'}:
        return None
    if (re.search(r'\b(?:packages?|tourism packages?)\b', message, re.I)
            or (classify_detailed_intent(message) == 'GENERAL_CONVERSATION'
                and not re.search(r'\b(?:change|replace|remove|reduce|keep|relax|walking|cancel)\b', message, re.I)
                and not extract_interests(message) and extract_budget(message) is None
                and extract_itinerary_day(message) is None
                and extract_activity_position(message, allow_short=bool(adjustment.get('pendingOperation'))) is None
                and not extract_travellers(message) and not re.fullmatch(r'\d+(?:\.\d+)?', message))):
        return None

    previous_adjustment = deepcopy(adjustment)
    patch = dict(adjustment.get('patch') or {})
    draft = {**trip, **patch}
    change = {}
    budget = extract_budget(message)
    if budget is None and adjustment.get('pendingBudget') and re.fullmatch(r'\d+(?:\.\d{1,2})?', message):
        budget = float(message)
    if budget is not None and not 0 < budget <= 1_000_000:
        return {'reply': 'Enter a total budget between MYR 0.01 and MYR 1,000,000.'}
    if budget:
        change['budgetLimit'] = budget
    elif re.search(r'\bcheaper\b', message, re.I):
        adjustment['pendingBudget'] = True
        return {'reply': 'What total budget in MYR should I use? I’ll keep the saved trip until you confirm.'}
    people = extract_travellers(message)
    if people:
        change.update(travellerCount=people, numberOfTravellers=people)
    duration = extract_duration(message)
    try:
        old_start = date.fromisoformat(str(draft.get('startDate'))[:10])
        old_end = date.fromisoformat(str(draft.get('endDate'))[:10])
        start, end = extract_dates(message, duration or (old_end - old_start).days + 1)
        if duration and not start:
            start, end = old_start.isoformat(), (old_start + timedelta(days=duration - 1)).isoformat()
        if start and end:
            if date.fromisoformat(start) < malaysian_today() or not 1 <= (date.fromisoformat(end) - date.fromisoformat(start)).days + 1 <= 14:
                return {'reply': 'Choose a future date range of 1 to 14 days.'}
            change.update(startDate=start, endDate=end)
    except ValueError:
        return {'reply': 'This trip needs valid dates before I can revise it.'}

    geo = extract_geographic_entities(message)
    if geo.get('is_foreign') or geo.get('is_multi_destination'):
        return {'reply': 'Choose one Malaysian destination for this revision.'}
    area = geo.get('destination_area')
    if area and area != draft.get('destinationArea') and re.search(r'\b(?:change|switch|move|instead)\b', message, re.I):
        change.update(destinationArea=area, destinationState=geo.get('destination_state') or '', destinationCountry='Malaysia')
    booking_fields = {'startDate', 'endDate', 'destinationArea', 'travellerCount'}
    if any(change[key] != draft.get(key) for key in booking_fields & change.keys()) and any(
            trip.get(key) for key in ('selectedFlight', 'selectedHotel', 'hotelBookingId', 'checkoutOrderId')):
        return {'reply': 'This trip has travel or payment details attached. Review them in Trip Details before changing its dates, destination or guest count.'}
    interests = extract_interests(message)
    if interests:
        change['interests'] = interests
    if extract_excluded_interests(message):
        change['excludedInterests'] = extract_excluded_interests(message, draft.get('excludedInterests'))
    if extract_excluded_activity_types(message):
        change['excludedActivityTypes'] = extract_excluded_activity_types(message, draft.get('excludedActivityTypes'))
    indoor = extract_indoor_preference(message)
    if indoor is not None:
        change['preferIndoor'] = indoor
    if re.search(r'\b(?:relaxing|relaxed|slower|reduce walking|less walking|not too much walking|peaceful)\b', message, re.I):
        change['travelPace'] = 'relaxed'
    if re.search(r'\b(?:more active|faster|active pace)\b', message, re.I):
        change['travelPace'] = 'active'
    preference_fields = ('interests', 'excludedInterests', 'excludedActivityTypes', 'preferIndoor', 'travelPace')
    preferences = {key: change[key] for key in preference_fields if key in change}
    if preferences:
        adjustment['pendingPreferences'] = {**adjustment.get('pendingPreferences', {}), **preferences}
    if budget is None:
        change = {**adjustment.get('pendingPreferences', {}), **change}
        interests = change.get('interests')

    day_target = extract_itinerary_day(message)
    if day_target is not None and re.search(r'\bkeep\b.*\bunchanged\b', message, re.I):
        adjustment['protectedDays'] = sorted(set(adjustment.get('protectedDays', [])) | {day_target})
        if not change:
            return {'reply': f'I will keep Day {day_target} unchanged. Which other day or activity should I change?'}
        day_target = None
    operation = re.search(r'\b(replace|remove|delete|add)\b', message, re.I)
    if operation:
        adjustment['pendingOperation'] = 'remove' if operation[1].lower() == 'delete' else operation[1].lower()
    position = extract_activity_position(message, allow_short=bool(adjustment.get('pendingOperation')))
    if position is not None:
        adjustment['pendingActivity'] = position
        adjustment.setdefault('pendingOperation', 'replace')
    named = [a for a in _saved_activities(draft) if len(clean_text(a.get('activityName'))) > 2
             and clean_text(a.get('activityName')) in clean_text(message)] if operation else []
    if len(named) == 1:
        day_target = int(named[0].get('dayNo') or 1)
        adjustment['pendingActivity'] = [a for a in _saved_activities(draft)
                                         if str(a.get('dayNo')) == str(day_target)].index(named[0]) + 1
    if day_target is not None:
        if not 1 <= day_target <= (old_end - old_start).days + 1:
            return {'reply': 'That day is outside the saved trip. Which itinerary day should I change?'}
        if day_target in adjustment.get('protectedDays', []):
            state['adjustment'] = previous_adjustment
            return {'reply': f'You asked to keep Day {day_target} unchanged. Which other day should I edit?'}
        if day_target != adjustment.get('pendingDay') and re.search(r'\b(?:no|actually|instead|sorry)\b', message, re.I):
            for key in ('activities', 'dailySchedule', 'unscheduledSuggestions', 'budgetEstimate'):
                patch.pop(key, None)
            draft = {**trip, **patch}
            adjustment['patch'] = patch
            state.pop('activePlan', None)
        adjustment['pendingDay'] = day_target
    activity_change = bool(interests or operation or position is not None or day_target or
                           {'travelPace', 'excludedInterests', 'excludedActivityTypes', 'preferIndoor'} & change.keys()
                           or adjustment.get('pendingOperation'))
    if change and set(change) <= {'budgetLimit', 'travellerCount', 'numberOfTravellers'} and not (interests or operation or position is not None or day_target):
        activity_change = False
    day = (adjustment.get('pendingDay') or adjustment.get('viewDay')) if activity_change else None
    if activity_change and not day and 'destinationArea' not in change:
        return {'reply': 'Which day would you like to change? You can ask to see the saved plan first.'}
    if adjustment.get('protectedDays') and {'destinationArea', 'startDate', 'endDate'} & change.keys():
        state['adjustment'] = previous_adjustment
        return {'reply': 'Those changes could affect the days you asked to keep. Please review that restriction before changing the destination or dates.'}
    if day and day in adjustment.get('protectedDays', []):
        state['adjustment'] = previous_adjustment
        return {'reply': f'You asked to keep Day {day} unchanged. Which other day should I edit?'}
    local_operation = adjustment.get('pendingOperation', 'day')
    if change.get('travelPace') == 'relaxed' and not operation and not (concepts_for(interests or []) - {'leisure'}):
        local_operation = 'relax'
    if day and local_operation in {'replace', 'remove'} and adjustment.get('pendingActivity') is None:
        return {'reply': f'Which activity on Day {day} should I {local_operation}? Reply with its name or position.'}
    if day and not interests and not {'travelPace', 'excludedInterests', 'excludedActivityTypes', 'preferIndoor'} & change.keys() and local_operation != 'remove':
        return {'reply': f'What kind of activities would you like for Day {day}?'}
    if not change and not day:
        known_day = adjustment.get('pendingDay') or adjustment.get('viewDay')
        if known_day:
            return {'reply': f'Which activity or preference would you like to change on Day {known_day}?'}
        return {'reply': 'Which day or activity would you like to change? You can ask to see the saved plan first.'}

    draft = {**draft, **change}
    if day and 'destinationArea' not in change:
        activities, error = _day_activities(draft, trip['id'], day, local_operation,
                                           adjustment.get('pendingActivity'), interests)
        if error:
            return {'reply': error}
        change['activities'] = activities
        change.pop('interests', None)
        draft = {**trip, **patch, **change}
    elif 'destinationArea' in change:
        planned, status = build_structured_trip_plan(
            draft['destinationArea'], draft.get('destinationState'), budget_limit=draft.get('budgetLimit'),
            traveller_count=draft.get('travellerCount') or draft.get('numberOfTravellers') or 1,
            start_date=draft['startDate'], end_date=draft['endDate'],
            interests=draft.get('interests'), excluded_interests=draft.get('excludedInterests'),
            excluded_activity_types=draft.get('excludedActivityTypes'), prefer_indoor=draft.get('preferIndoor', False),
            preference_profile={key: draft[key] for key in ('travelPace', 'travelPersonality') if key in draft},
            catalog=_planning_catalog(draft['destinationArea'], draft.get('destinationState'), draft.get('interests')))
        if status != 'ready' or planned.get('coverageStatus') != 'complete':
            return {'reply': 'I could not verify enough activities for those changes. Your saved trip is unchanged.'}
        change['activities'] = planned['activities']
        draft = {**trip, **patch, **change}
    if {'startDate', 'destinationArea', 'activities', 'travelPace'} & change.keys():
        revised = recalculateItinerary(draft)
        if day and 'destinationArea' not in change:
            other_days = [row for row in (draft.get('dailySchedule') or []) if str(row.get('dayNo')) != str(day)]
            if other_days:
                revised['dailySchedule'] = sorted(
                    other_days + [row for row in revised['dailySchedule'] if row.get('dayNo') == day],
                    key=lambda row: int(row['dayNo']))
            revised['activities'] = [row for row in draft['activities'] if str(row.get('dayNo')) != str(day)] + [
                row for row in revised['activities'] if row.get('dayNo') == day]
            for key in preference_fields:
                change.pop(key, None)
        for key in ('dailySchedule', 'activities', 'unscheduledSuggestions', 'tripDays', 'durationDays'):
            if key in revised:
                change[key] = revised[key]
    if 'travellerCount' in change:
        change.update(refresh_activity_costs({**draft, **change}))
    if day and local_operation != 'remove' and calculateBudget({**draft, **change}).get('overBy', 0) > 0:
        return {'reply': 'Those activities would exceed your trip budget. Your saved trip is unchanged; try a lower-cost theme or remove a stop.'}
    patch.update(change)
    draft = {**trip, **patch}
    patch['budgetEstimate'] = draft['budgetEstimate'] = calculateBudget(draft)
    preview = {key: draft[key] for key in (
        'title', 'destinationArea', 'destinationState', 'startDate', 'endDate', 'budgetLimit', 'activities',
        'dailySchedule', 'budgetEstimate', 'travellerCount', 'numberOfTravellers', 'tripDays',
        'interests', 'excludedInterests', 'travelPace') if key in draft}
    preview['adjustmentTripId'] = trip['id']
    preview['adjustmentRevision'] = fingerprint
    preview['draftId'] = _plan_id(preview)
    state['activePlan'] = preview
    adjustment.update(tripId=trip['id'], fingerprint=fingerprint, patch=patch)
    if day:
        for key in ('pendingOperation', 'pendingActivity', 'pendingPreferences'):
            adjustment.pop(key, None)
    if budget is not None:
        adjustment.pop('pendingBudget', None)
    state['adjustment'] = adjustment
    return {'reply': 'Review the revised itinerary below. Confirm to update the same Trip.', 'tripPlan': preview}


@bp.post('/chat')
@auth_required(['traveller'])
def chat():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload,dict):
        return jsonify({'ok':False,'error':'Chat data must be an object.'}),400
    message = str(payload.get('message', '')).strip()
    user_message = message
    if not validateQuestion(message):
        return jsonify({'ok': False, 'error': 'message is required'}), 400

    if len(message) > 2000:
        return jsonify({'ok': False, 'error': 'Message exceeds 2000 character limit'}), 400

    try:
        session = _session_ref(payload.get('sessionId'))
        if payload.get('sessionId') and not session:
            return jsonify({'ok':False,'error':'Chat session not found.'}),404
        session = session or _new_session(_session_title(message))
    except Exception:
        return jsonify({'ok':False,'error':'Your conversation could not be loaded. Please retry.'}),503
    messages = [dict(x) for x in session.get('messages', []) if isinstance(x, dict)]
    if len(messages) >= 30:
        return jsonify({'ok': False, 'error': 'Chat session limit reached. Start a new chat session to continue.'}), 429

    expected_session = deepcopy(session)
    planning_state = dict(session.get('planningState') or {})
    if payload.get('commerceRevision') is not None and payload['commerceRevision'] != planning_state.get('commerceRevision',0):
        return jsonify({'ok':False,'error':'This conversation changed. Reopen the chat before sending the next message.','code':'stale_chat_context'}),409
    try:
        def nearby_catalog(focus):
            area = focus.get('city') or planning_state.get('destinationArea') or focus.get('state')
            if not area:
                return []
            return find_matching_catalog_destinations(area, focus.get('state'),
                _planning_catalog(area, focus.get('state'), allow_provider=False))
        personal = personal_response(message, planning_state, retrieveRecord, g.uid)
        routing = ({'response': personal} if personal is not None else
                   resolve_turn(message, planning_state, messages, interpret=interpretChatbotIntent, lookup=nearby_catalog))
        if routing and routing.get('message'):
            message = routing['message']
        if routing and routing.get('response') is not None:
            adjustment = routing['response']
        elif routing and routing.get('commerce'):
            adjustment = None
        else:
            adjustment = _adjust_trip(message, planning_state)
        commerce = adjustment if adjustment is not None else commerce_response(message, planning_state, retrieveRecord, g.uid)
        if commerce is None and routing and routing.get('commerce'):
            commerce = {'reply': 'I cannot verify a booking or payment from conversation text. Open Trips or Orders for the verified record.'
                        if routing['commerce'] == 'records' else
                        'Which published package would you like to filter or compare? Please use its displayed name or number.'}
    except PersonalReadUnavailable:
        return jsonify(ok=False, error='Your saved records are temporarily unavailable. Please retry; no trip or financial data was changed.'), 503
    except (ValueError, TypeError, KeyError, OverflowError):
        return jsonify(ok=False, error='The saved trip or conversation could not be read. Reopen it and try again.'), 409
    discovery = False
    if (commerce is None and not planning_state.get('guidedActive')
            and classify_detailed_intent(message, planning_state) == 'DESTINATION_RECOMMENDATION'):
        commerce = _destination_discovery(message, planning_state)
        discovery = True
    if commerce is not None:
        item = {'message':user_message,'createdAt':utc_now_iso(),'travellerId':g.uid,'source':'travelmate-assistant' if adjustment is not None or discovery else 'travelmate-data',**commerce}
        decorate_reply(item, planning_state)
        try:
            record=storeRecord('chat_messages',{**item,'sessionId':session['id']})
            item['id']=record['id']
            remember_results(planning_state, item)
            messages.append(item)
            session=updateRecord('chat_sessions',session['id'],{'messages':messages,'planningState':planning_state,'updatedAt':utc_now_iso()},expected=expected_session)
        except Exception:
            return jsonify({'ok':False,'error':'The conversation could not be saved. Reopen the chat and retry.'}),409
        return jsonify({'ok':True,'reply':item['reply'],'source':item['source'],'item':item,'session':session})
    original_planning_state = dict(planning_state)
    previous_requirements = {key: planning_state.get(key) for key in (
        'destinationArea', 'startDate', 'endDate', 'tripDays', 'budgetLimit', 'travellerCount',
        'interests', 'excludedInterests', 'excludedActivityTypes', 'preferIndoor', 'travelPace',
        'budgetRange', 'avoidCrowds', 'activityWindow', 'planningGoal', 'daySpecificPreferences')}

    # Extract NLP requirements from user message
    geo = extract_geographic_entities(message)
    explicit_duration = extract_duration(message)
    dur = explicit_duration or planning_state.get('tripDays')
    half_day = bool(re.search(r'\bhalf[ -](?:a[ -])?day\b', message, re.I))
    bud = extract_budget(message, planning_state.get('budgetLimit'))
    trav = extract_travellers(message, planning_state.get('travellerCount'))
    date_error = None
    try:
        guided = payload.get('guidedPlanning') is True or planning_state.get('guidedPlanning')
        s_date, e_date = extract_dates(message, dur if guided else dur or 3)
    except ValueError as error:
        s_date = e_date = None
        date_error = str(error)
    dates_supplied = bool(s_date and e_date)
    if date_error:
        planning_state['dateClarification'] = date_error
    elif s_date and e_date:
        dur = (date.fromisoformat(e_date) - date.fromisoformat(s_date)).days + 1
        planning_state.pop('dateClarification', None)
        planning_state.pop('activityWindow', None)
    elif half_day:
        dur = None
        planning_state['activityWindow'] = 'half_day'
        for key in ('tripDays', 'startDate', 'endDate', 'dateClarification'):
            planning_state.pop(key, None)
    elif explicit_duration is not None:
        planning_state.pop('activityWindow', None)
        if planning_state.pop('dateClarification', None) or (
            planning_state.get('endDate') and explicit_duration != planning_state.get('tripDays')
        ):
            planning_state.pop('startDate', None)
            planning_state.pop('endDate', None)
    if not date_error and not s_date and not e_date:
        s_date, e_date = planning_state.get('startDate'), planning_state.get('endDate')
        if s_date and e_date:
            dur = (date.fromisoformat(e_date) - date.fromisoformat(s_date)).days + 1
        elif s_date and dur:
            e_date = (date.fromisoformat(s_date) + timedelta(days=dur - 1)).isoformat()
    explicit_interests = extract_interests(message)
    if explicit_interests and (not planning_state.get('chatInterests') or re.search(r'\b(?:instead|only|more|focus on)\b', message, re.I)):
        ints = explicit_interests
    else:
        ints = extract_interests(message, planning_state.get('interests'))
    if explicit_interests:
        planning_state['chatInterests'] = True
    ex_ints = extract_excluded_interests(message, planning_state.get('excludedInterests'))
    ex_types = extract_excluded_activity_types(message, planning_state.get('excludedActivityTypes'))
    indoor_pref = extract_indoor_preference(message, planning_state.get('preferIndoor'))
    if re.search(r'\b(relaxing|relaxed|slower|slow[- ]paced|easy pace|take it easy|leisurely|not rushed|less walking|not too much walking)\b', message, re.I):
        planning_state['travelPace'] = 'relaxed'
    if re.search(r'\b(active pace|busy pace|packed trip)\b', message, re.I):
        planning_state['travelPace'] = 'active'
    if re.search(r'\b(affordable|low[- ]cost|cheap|inexpensive|budget[- ]friendly|on a budget|tight budget)\b', message, re.I):
        planning_state['budgetRange'] = 'Budget'
    if re.search(r"\b(?:(?:avoid|don't want|do not want|no)\b.{0,20}\bcrowd|less crowded)\b", message, re.I):
        planning_state['avoidCrowds'] = True
    day_pref = extract_day_specific(message)
    detailed_intent = classify_detailed_intent(message, planning_state)

    # Update accumulated planning state
    if geo.get('destination_area') and detailed_intent not in {
        'WEATHER_ENQUIRY', 'HOTEL_ENQUIRY', 'FLIGHT_ENQUIRY', 'CAR_RENTAL_ENQUIRY',
        'BUDGET_ENQUIRY', 'FEATURE_EXPLANATION',
    }:
        planning_state['destinationArea'] = geo['destination_area']
        planning_state['destinationState'] = geo['destination_state']
        planning_state['destinationCountry'] = 'Malaysia'
    if dur:
        planning_state['tripDays'] = dur
    if bud:
        planning_state['budgetLimit'] = bud
    if trav:
        planning_state['travellerCount'] = trav
    if s_date:
        planning_state['startDate'] = s_date
        if e_date:
            planning_state['endDate'] = e_date
        else:
            planning_state.pop('endDate', None)
    if ints:
        planning_state['interests'] = ints
    if ex_ints:
        planning_state['excludedInterests'] = ex_ints
        # Purge excluded interests from positive interests if present
        if planning_state.get('interests'):
            planning_state['interests'] = [i for i in planning_state['interests'] if i not in ex_ints]
    if ex_types or 'excludedActivityTypes' in planning_state:
        planning_state['excludedActivityTypes'] = ex_types
    if indoor_pref is not None:
        planning_state['preferIndoor'] = indoor_pref
    if day_pref:
        cur_day = dict(planning_state.get('daySpecificPreferences') or {})
        cur_day.update({str(day): preference for day, preference in day_pref.items()})
        planning_state['daySpecificPreferences'] = cur_day
    if detailed_intent:
        planning_state['lastIntent'] = detailed_intent
    is_conversational = conversational_question(message) and not geo.get('is_destination_change')
    if is_conversational:
        planning_state = original_planning_state
    requirements_changed = any(planning_state.get(key) != value for key, value in previous_requirements.items())
    if requirements_changed or date_error:
        planning_state.pop('activePlan', None)
    active_plan = planning_state.get('activePlan') or {}
    saved_regeneration = (message.casefold() == 'regenerate itinerary'
                          and active_plan.get('draftId') in (planning_state.get('savedPlans') or {}))
    existing_plan = active_plan if (_show_plan_request(message) or saved_regeneration) and not planning_state.get('dateClarification') else None
    if not is_conversational and geo.get('is_multi_destination'):
        planning_state['tripMode'] = 'road_trip'
        planning_state['multipleDestinations'] = list(geo.get('multiple_destinations') or [])
        planning_state['originDestination'] = geo.get('origin_destination')
        planning_state['targetDestination'] = geo.get('target_destination')
    elif not is_conversational and geo.get('destination_area') and (
        geo.get('is_destination_change') or detailed_intent == 'ITINERARY_PLANNING'
    ):
        _clear_multi_destination_state(planning_state)

    if not is_conversational and (payload.get('guidedPlanning') is True or detailed_intent == 'ACTIVITY_DISCOVERY'
            or re.fullmatch(r'(?:please )?plan (?:a|my) trip[.!?]*', message.strip(), re.I)):
        planning_state['guidedPlanning'] = True
    guided_check = None
    if (detailed_intent == 'BUDGET_ADJUSTMENT' and re.search(r'\bcheaper\b', message, re.I)
            and not extract_budget(message)):
        planning_state['guidedQuestion'] = 'budgetLimit'
        planning_state['guidedPlanning'] = planning_state['guidedActive'] = True
        guided_check = {'clarification_needed': True, 'ready': False,
                        'clarification_prompt': 'What total budget in MYR should I use for this trip?'}
    elif existing_plan:
        guided_check = {'clarification_needed': False, 'ready': False}
    elif not is_conversational and (planning_state.get('guidedPlanning') or detailed_intent == 'ACTIVITY_DISCOVERY'):
        preferences = retrieveRecord('travel_preferences', g.uid) or {}
        guided_check = guided_requirements(message, planning_state, preferences, dates_supplied=dates_supplied)
    guided_ready = bool(guided_check and guided_check.get('ready'))
    guided_activities = bool(guided_check and guided_check.get('activities'))
    if any(planning_state.get(key) != value for key, value in previous_requirements.items()):
        planning_state.pop('activePlan', None)
    session['planningState'] = planning_state

    # Handle foreign destination boundary
    if geo.get('is_foreign'):
        foreign_reply = (
            f"TravelMate is dedicated exclusively to travel planning within Malaysia. "
            f"I cannot create a travel plan for {geo.get('unsupported_foreign')}, but I would be glad to help you "
            f"plan an exciting trip to Kuala Lumpur, Penang, Langkawi, Melaka, Sabah, Sarawak, or anywhere across Malaysia!"
        )
        item = {
            'id': 'chat_' + utc_now_iso().replace(':', '').replace('-', '').replace('.', ''),
            'travellerId': g.uid,
            'message': user_message,
            'reply': foreign_reply,
            'source': 'travelmate-assistant',
            'createdAt': utc_now_iso(),
        }
        record = storeRecord('chat_messages', {**item, 'sessionId': session['id']})
        item['id'] = record['id']
        messages.append(item)
        updates = {
            'messages': messages,
            'planningState': planning_state,
            'updatedAt': utc_now_iso(),
        }
        session = updateRecord('chat_sessions', session['id'], updates)
        return jsonify({'ok': True, 'reply': foreign_reply, 'source': 'travelmate-assistant', 'messageId': record['id'], 'item': item, 'session': session})

    # Check requirement completeness for planning requests
    req_check = {}
    if not is_conversational:
        if planning_state.get('dateClarification'):
            req_check = {'clarification_needed': True, 'clarification_prompt': planning_state['dateClarification']}
        else:
            req_check = guided_check or check_requirement_completeness(message, planning_state)
    if req_check.get('clarification_needed'):
        clarification_reply = req_check.get('clarification_prompt')
        previews = []
        if req_check.get('preview'):
            intro, previews = _activity_preview(planning_state)
            clarification_reply = f'{intro} {clarification_reply}'
        if not planning_state.get('dateClarification') and s_date and e_date and re.search(r'\b(?:until|to|through|till)\b|\d{4}-\d{2}-\d{2}|[–—]', message, re.I):
            clarification_reply = f'Travel dates: {s_date} to {e_date} ({dur} calendar days, {dur - 1} nights). ' + clarification_reply
        item = {
            'id': 'chat_' + utc_now_iso().replace(':', '').replace('-', '').replace('.', ''),
            'travellerId': g.uid,
            'message': user_message,
            'reply': clarification_reply,
            'source': 'travelmate-assistant',
            'createdAt': utc_now_iso(),
        }
        if req_check.get('suggestedReplies'):
            item['suggestedReplies'] = req_check['suggestedReplies']
        if previews:
            item['placeSuggestions'] = previews
        record = storeRecord('chat_messages', {**item, 'sessionId': session['id']})
        item['id'] = record['id']
        messages.append(item)
        updates = {
            'messages': messages,
            'planningState': planning_state,
            'updatedAt': utc_now_iso(),
        }
        session = updateRecord('chat_sessions', session['id'], updates)
        return jsonify({'ok': True, 'reply': clarification_reply, 'source': 'travelmate-assistant', 'messageId': record['id'], 'item': item, 'session': session})

    road_trip_unsupported = (
        not is_conversational and planning_state.get('tripMode') == 'road_trip'
        and classify_user_intent(message, planning_state) == 'PLANNING_REQUEST'
    )
    if road_trip_unsupported:
        response = {'reply': _unsupported_road_trip_reply(planning_state), 'source': 'travelmate-assistant'}
    elif re.search(r'\bmore (?:places )?like this\b', message, re.I):
        response = {'reply':'Choose More like this on a specific For You destination card so the selected place can be identified. Casual chat does not overwrite your saved questionnaire.', 'source':'travelmate-assistant'}
    elif existing_plan:
        response = {'reply': 'Here is your existing itinerary. Review the day-by-day card below.', 'source': 'travelmate-assistant'}
    elif guided_activities:
        activity_reply, activity_suggestions = _activity_preview(planning_state)
        response = {'reply': activity_reply, 'source': 'travelmate-assistant'}
    elif guided_ready:
        response = {'reply': 'Here is a draft based on your trip details and saved preferences. Review its dates, budget and activities before choosing Save. No trip or booking has been created.', 'source': 'travelmate-assistant'}
    elif geo.get('is_destination_change'):
        response = {'reply': _destination_change_reply(planning_state), 'source': 'travelmate-assistant'}
    else:
        try:
            history = [item for item in messages[-20:] if item.get('source') != 'travelmate-data']
            context = _context({**session, 'planningState': planning_state, 'messages': messages})
            response = (
                generateFollowUpResponse(message, context, with_source=True, planning_state=planning_state)
                if history else generateChatbotResponse(message, context, with_source=True, planning_state=planning_state)
            )
        except Exception:
            return jsonify({'ok': False, 'error': 'The travel assistant is temporarily unavailable. Please retry.'}), 502

    reply, source = response['reply'], response['source']
    if not guided_activities and not is_conversational and detailed_intent in {'INTEREST_MODIFICATION', 'INDOOR_ALTERNATIVE'} and (
        planning_state.get('excludedInterests')
        or planning_state.get('excludedActivityTypes')
        or planning_state.get('preferIndoor')
    ):
        reply = _constraint_acknowledgement(planning_state)
        source = 'travelmate-assistant'
    item = {
        'id': 'chat_' + utc_now_iso().replace(':', '').replace('-', '').replace('.', ''),
        'travellerId': g.uid,
        'message': user_message,
        'reply': reply,
        'source': source,
        'createdAt': utc_now_iso(),
    }
    if guided_activities and activity_suggestions and planning_state.get('activityWindow') != 'half_day':
        item['suggestedReplies'] = ['Make a dated itinerary']
    if road_trip_unsupported:
        item['constraintConflict'] = {
            'status': 'unsupported_multi_destination',
            'message': reply,
            'tripMode': 'road_trip',
            'multipleDestinations': list(planning_state.get('multipleDestinations') or []),
            'originDestination': planning_state.get('originDestination'),
            'targetDestination': planning_state.get('targetDestination'),
        }

    # Extract structured plan and suggestions
    dest_for_planning = planning_state.get('destinationArea') or geo.get('destination_area')
    dest_state_for_planning = planning_state.get('destinationState') or geo.get('destination_state')
    plan = existing_plan
    if existing_plan:
        item['tripPlan'] = existing_plan
        saved_id = (planning_state.get('savedPlans') or {}).get(existing_plan.get('draftId'))
        if saved_id:
            item['savedTripId'] = saved_id
            reply = item['reply'] = 'This plan was saved to Trips. You can reopen it from Trips.'
    if (
        not existing_plan and not guided_activities and not is_conversational
        and (guided_ready or (guided_check is None and classify_user_intent(message, planning_state) == 'PLANNING_REQUEST'))
        and dest_for_planning
        and planning_state.get('tripMode') != 'road_trip'
    ):
        dur_val = planning_state.get('tripDays') or 3
        bud_val = planning_state.get('budgetLimit') or 1200.0
        trav_val = planning_state.get('travellerCount') or 1
        s_date_val = planning_state.get('startDate')
        e_date_val = planning_state.get('endDate')
        ints_val = planning_state.get('interests')
        ex_ints_val = planning_state.get('excludedInterests')
        ex_types_val = planning_state.get('excludedActivityTypes')
        indoor_val = planning_state.get('preferIndoor', False)

        catalog = _planning_catalog(dest_for_planning, dest_state_for_planning, ints_val)
        plan, plan_status = build_structured_trip_plan(
            destination_area=dest_for_planning,
            destination_state=dest_state_for_planning,
            days=dur_val,
            budget_limit=bud_val,
            traveller_count=trav_val,
            start_date=s_date_val,
            end_date=e_date_val,
            interests=ints_val,
            excluded_interests=ex_ints_val,
            excluded_activity_types=ex_types_val,
            prefer_indoor=indoor_val,
            catalog=catalog,
            preference_profile={**effective_preference_profile(retrieveRecord('travel_preferences', g.uid) or {},
                retrieveRecord('learned_preference_profiles', g.uid)),
                **{key:planning_state[key] for key in ('travelPace','travelPersonality','budgetRange') if key in planning_state}},
            collaborative_data=[row for row in (retrieveRecord('feedback',limit=500) or []) if isinstance(row,dict) and published_review(row)],
            peer_preferences={str(row.get('travellerId') or row.get('id')):row for row in (retrieveRecord('travel_preferences',limit=500) or []) if isinstance(row,dict)},
            current_traveller_id=g.uid,
        )
        if plan and plan_status == 'ready':
            if planning_state.get('avoidCrowds'):
                plan['planningLimitations'] = ['Verified crowd-level data is unavailable; quieter conditions cannot be guaranteed.']
            if guided_ready and not planning_state.get('budgetLimit'):
                plan.setdefault('planningLimitations', []).append('The budget field uses a default planning estimate of MYR 1,200.')
            if guided_ready and not planning_state.get('travellerCount'):
                plan.setdefault('planningLimitations', []).append('Cost estimates are for one traveller.')
            if guided_ready and plan.get('planningLimitations'):
                reply = item['reply'] = ' '.join([reply, *plan['planningLimitations']])
            plan['travelPace'] = planning_state.get('travelPace', '')
            plan['travelPersonality'] = planning_state.get('travelPersonality', '')
            plan['draftId'] = _plan_id(plan)
            item['tripPlan'] = plan
            planning_state['activePlan'] = plan
            if plan.get('coverageStatus') == 'partial':
                reply = item['reply'] = 'This is an incomplete itinerary preview: some days have no verified activities. Choose a shorter trip or another destination before saving. No trip has been created.'
                source = item['source'] = 'travelmate-assistant'
        elif plan_status in {'coverage_gap', 'insufficient_activities'}:
            reply = item['reply'] = f'I do not have enough verified, distinct attractions in {dest_for_planning} to fill {dur_val} itinerary days. No complete draft or trip has been created. Try a shorter trip or another Malaysian destination.'
            source = item['source'] = 'travelmate-assistant'
            item['dataCoverage'] = {
                'status': 'coverage_gap',
                'destinationArea': dest_for_planning,
                'destinationState': dest_state_for_planning or '',
                'destinationCountry': 'Malaysia',
                'message': reply,
            }
        elif plan_status == 'constraint_conflict':
            active_constraints = list(ex_ints_val or []) + list(ex_types_val or [])
            if indoor_val:
                active_constraints.append('indoor-only')
            constraint_text = ', '.join(active_constraints) or 'the requested restrictions'
            reply = (
                f"I could not find enough verified activities in {dest_for_planning} that satisfy all active "
                f"constraints ({constraint_text}). I have not inserted prohibited or outdoor substitutes. "
                "Please relax one constraint or choose another destination."
            )
            source = 'travelmate-assistant'
            item['reply'] = reply
            item['source'] = source
            item['constraintConflict'] = {
                'status': 'constraint_conflict',
                'message': reply,
                'excludedInterests': list(ex_ints_val or []),
                'excludedActivityTypes': list(ex_types_val or []),
                'preferIndoor': bool(indoor_val),
            }

    suggestions = activity_suggestions if guided_activities else []
    if not guided_activities and not is_conversational:
        suggestions = _extract_place_suggestions(
            message,
            destination_area=dest_for_planning,
            prefer_indoor=planning_state.get('preferIndoor', False),
            excluded_interests=planning_state.get('excludedInterests'),
            excluded_activity_types=planning_state.get('excludedActivityTypes'),
        )
    if suggestions and not plan:
        item['placeSuggestions'] = suggestions

    decorate_reply(item, planning_state)
    record = storeRecord('chat_messages', {**item, 'sessionId': session['id']})
    item['id'] = record['id']
    remember_results(planning_state, item)
    messages.append(item)
    updates = {
        'messages': messages,
        'planningState': planning_state,
        'updatedAt': utc_now_iso(),
    }
    if session.get('title') in {None, '', 'New travel chat'}:
        updates['title'] = _session_title(message)
    session = updateRecord('chat_sessions', session['id'], updates)
    return jsonify({'ok': True, 'reply': reply, 'source': source, 'messageId': record['id'], 'item': item, 'session': session})


@bp.post('/save-plan')
@auth_required(['traveller'])
def save_plan():
    payload = request.get_json(silent=True) or {}
    plan = payload.get('plan')
    if isinstance(plan, dict) and (plan.get('viewOnly') is True or 'savedTripId' in plan):
        return jsonify(ok=False, error='This is a read-only saved-trip preview, not a revision to save.'), 400
    save_session = None
    if payload.get('sessionId'):
        save_session = _session_ref(payload['sessionId'])
        if not save_session:
            return jsonify({'ok': False, 'error': 'Chat session not found'}), 404
        current_state = save_session.get('planningState') or {}
        active = current_state.get('activePlan')
        if current_state.get('dateClarification') or not isinstance(plan, dict) or not active or _plan_id(active) != _plan_id(plan):
            return jsonify({'ok': False, 'error': 'This draft is out of date. Review the current itinerary before saving.'}), 409
        if payload.get('confirmed') is not True:
            return jsonify({'ok': False, 'error': 'Confirm the itinerary before saving.'}), 400
        adjustment = current_state.get('adjustment') or {}
        if active.get('adjustmentTripId'):
            iid = active['adjustmentTripId']
            if current_state.get('savedPlans', {}).get(active['draftId']) == iid:
                current = retrieveRecord('itineraries', iid)
                if current and current.get('travellerId') == g.uid:
                    return jsonify(ok=True, id=iid, itinerary=current, budget=current.get('budgetEstimate'), alreadySaved=True)
            trip = retrieveRecord('itineraries', iid)
            if (not trip or trip.get('travellerId') != g.uid or trip.get('packageTrip')
                    or trip.get('tripType') == 'package' or adjustment.get('tripId') != iid):
                return jsonify(ok=False, error='This trip changed. Review it before applying the revision.'), 409
            draft_id = active['draftId']
            already_saved = trip.get('lastChatAdjustmentId') == draft_id
            updated = trip
            if not already_saved:
                if adjustment.get('fingerprint') != _trip_fingerprint(trip):
                    return jsonify(ok=False, error='This trip changed. Review it before applying the revision.'), 409
                try:
                    patch = adjustment['patch']
                    if active.get('restoresVersion') is not None:
                        verified = restore_patch(trip, active['restoresVersion'],
                            scope=active['restorationScope'], day=active.get('restorationDay'))
                        if verified != patch:
                            raise HistoryConflict('The restoration preview changed. Review it again before confirming.')
                        patch = {**patch, 'restoredFromRevision': active['restoresVersion'], '_restoreVersion': active['restoresVersion']}
                    updated = updateRecord('itineraries', iid, {**patch,
                                           'lastChatAdjustmentId': draft_id, 'updatedAt': utc_now_iso()}, expected=trip)
                except HistoryConflict as error:
                    return jsonify(ok=False, error=str(error)), 409
                except ReviewConflict:
                    return jsonify(ok=False, error='This trip changed. Review it before applying the revision.'), 409
                except Exception:
                    if active.get('restoresVersion') is not None:
                        current_app.logger.warning('Restoration result unavailable; reopen the trip before retrying.')
                        return jsonify(ok=False, error='The restoration outcome could not be verified. Reopen the trip before retrying.'), 503
                    raise
                if not updated:
                    return jsonify(ok=False, error='The trip could not be updated.'), 409
            try:
                if active.get('restoresVersion') is not None:
                    receipt_state = {**current_state,
                        'savedPlans': {**(current_state.get('savedPlans') or {}), draft_id: iid},
                        'adjustment': {'tripId': iid, 'fingerprint': _trip_fingerprint(updated), 'tripContext': _trip_context(updated)}}
                    updateRecord('chat_sessions', save_session['id'],
                        {'messages': save_session.get('messages') or [], 'planningState': receipt_state}, expected=save_session)
                else:
                    updateRecord('chat_sessions', save_session['id'], {'planningState': {'savedPlans': {draft_id: iid}}})
            except Exception:
                current_app.logger.warning('Trip adjustment saved. Conversation receipt is temporarily unavailable.')
            return jsonify(ok=True, id=iid, itinerary=updated, budget=updated.get('budgetEstimate'),
                           alreadySaved=already_saved)
    if isinstance(plan, dict) and plan.get('adjustmentTripId'):
        return jsonify(ok=False, error='Reopen the saved trip adjustment before applying.'), 400
    if isinstance(plan, dict) and (
        plan.get('tripMode') == 'road_trip'
        or len(plan.get('multipleDestinations') or []) > 1
    ):
        return jsonify({
            'ok': False,
            'error': 'Multi-destination road-trip plans are not saveable until route planning is supported.',
        }), 400
    valid, err_msg = validate_save_plan_payload(plan)
    if not valid:
        return jsonify({'ok': False, 'error': err_msg}), 400

    dest = str(plan.get('destinationArea') or plan.get('destination') or '').strip()
    raw_activities = plan.get('activities') or []
    clean_activities = []
    for idx, act in enumerate(raw_activities):
        if not isinstance(act, dict):
            continue
        clean_activities.append({
            'activityId': act.get('activityId') or f'A{idx + 1}',
            'activityName': act.get('activityName') or act.get('name') or act.get('title') or f'Activity {idx + 1}',
            'destinationId': act.get('destinationId') or act.get('place_id') or f'dest_{idx + 1}',
            'address': act.get('address') or '',
            'state': act.get('state') or '',
            'city': act.get('city') or '',
            'dayNo': int(act.get('dayNo') or 1),
            'timeSlot': act.get('timeSlot') or act.get('timeRangeLabel') or '',
            'timeRangeLabel': act.get('timeRangeLabel') or act.get('timeSlot') or '',
            'estimatedCost': float(act.get('estimatedCost') or 0.0),
            **pricing_snapshot(act),
            'gps_coordinates': act.get('gps_coordinates') or act.get('gpsCoordinates') or {},
            'type': act.get('type') or act.get('category') or '',
            'category': act.get('category') or act.get('type') or '',
            'description': act.get('description') or '',
            'indoor': bool(act.get('indoor', False)),
            'openingHours': act.get('openingHours') or '',
            'recommendedDurationMinutes': int(act.get('recommendedDurationMinutes') or act.get('durationMinutes') or 0),
            'travelBufferMinutes': int(act.get('travelBufferMinutes') or 0),
            'scheduleNotes': act.get('scheduleNotes') or [],
        })

    start_str = str(plan.get('startDate') or date.today().isoformat())[:10]
    end_str = str(plan.get('endDate') or (date.today() + timedelta(days=2)).isoformat())[:10]
    limit = float(plan.get('budgetLimit') or 1200.0)

    itinerary_data = {
        'title': plan.get('title') or f'Trip to {dest}',
        'destinationArea': dest,
        'destinationCountry': 'Malaysia',
        'startDate': start_str,
        'endDate': end_str,
        'numberOfTravellers': int(plan.get('numberOfTravellers') or 1),
        **({'travellerCount': plan.get('travellerCount', plan.get('numberOfTravellers', 1))}
           if any(act.get('pricingUnit') for act in clean_activities) else {}),
        'budgetLimit': limit,
        **{field: plan[field] for field in (
            'originLocation', 'travelMode', 'accommodationChoice', 'carRentalChoice'
        ) if field in plan},
        'activities': clean_activities,
        'transportCost': float(plan.get('transportCost') or 0.0),
        'accommodationCost': float(plan.get('accommodationCost') or 0.0),
        'miscCost': float(plan.get('miscCost') or 0.0),
        'status': plan.get('status', 'draft'),
    }

    itinerary = createItinerary(itinerary_data, g.uid)
    budget = calculateBudget(itinerary)
    itinerary['budgetEstimate'] = budget
    if save_session:
        draft_id = _plan_id(plan)
        trip_id = 'chat_' + hashlib.sha256(f'{g.uid}:{save_session["id"]}:{draft_id}'.encode('utf-8')).hexdigest()[:32]
        itinerary['id'] = trip_id
        result, created = claimRecord('itineraries', trip_id, itinerary)
        updateRecord('chat_sessions', save_session['id'],
                     {'planningState': {'savedPlans': {draft_id: result['id']}}})
        return jsonify({'ok': True, 'id': result['id'], 'itinerary': result, 'budget': result.get('budgetEstimate'), 'alreadySaved': not created}), 201 if created else 200
    result = storeRecord('itineraries', itinerary)
    return jsonify({'ok': True, 'id': result['id'], 'itinerary': result, 'budget': budget}), 201


@bp.get('/sessions')
@auth_required(['traveller'])
def sessions():
    return jsonify({'ok': True, 'items': _sorted_sessions()})


@bp.post('/sessions')
@auth_required(['traveller'])
def create_session():
    payload = request.get_json(silent=True) or {}
    session = _new_session(str(payload.get('title') or 'New travel chat').strip() or 'New travel chat')
    return jsonify({'ok': True, 'session': session}), 201


@bp.get('/sessions/<session_id>')
@auth_required(['traveller'])
def get_session(session_id):
    session = _session_ref(session_id)
    if not session:
        return jsonify({'ok': False, 'error': 'Chat session not found'}), 404
    return jsonify({'ok': True, 'session': session})


@bp.delete('/sessions/<session_id>')
@auth_required(['traveller'])
def delete_session(session_id):
    session = _session_ref(session_id)
    if not session:
        return jsonify({'ok': False, 'error': 'Chat session not found'}), 404
    deleteRecord('chat_sessions', session_id)
    messages = retrieveRecord('chat_messages', filters=[('sessionId', '==', session_id)]) or []
    for item in messages:
        deleteRecord('chat_messages', item['id'])
    return jsonify({'ok': True, 'deletedMessages': len(messages)})


@bp.get('/history')
@auth_required(['traveller'])
def history():
    return jsonify({'ok': True, 'items': retrieveRecord('chat_messages', filters=[('travellerId', '==', g.uid)])})


@bp.delete('/history')
@auth_required(['traveller'])
def clear_history():
    items = retrieveRecord('chat_messages', filters=[('travellerId', '==', g.uid)])
    for item in items:
        deleteRecord('chat_messages', item['id'])
    sessions = retrieveRecord('chat_sessions', filters=[('travellerId', '==', g.uid)]) or []
    for session in sessions:
        deleteRecord('chat_sessions', session['id'])
    return jsonify({'ok': True, 'deleted': len(items), 'deletedSessions': len(sessions)})


@bp.get('/packages/<package_id>')
@auth_required(['traveller'])
def package_details(package_id):
    try:
        item=public_details(package_id,retrieveRecord)
    except Exception:
        return jsonify({'ok':False,'error':'Package details are temporarily unavailable.'}),503
    if not item:return jsonify({'ok':False,'error':'This package is no longer available.'}),404
    return jsonify({'ok':True,'package':item})
