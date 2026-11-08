from flask import Blueprint, request, jsonify, g
from auth_utils import auth_required
from utils import utc_now_iso
from services.gemini_service import generateChatbotResponse, generateFollowUpResponse
from sequence_contract.validators import validateQuestion
from sequence_contract.firebase_firestore import retrieveRecord, storeRecord, deleteRecord, updateRecord, claimRecord
from sequence_contract.domain_functions import createItinerary, calculateBudget
from services.activity_pricing import pricing_snapshot
from services.local_catalog import DESTINATIONS
from services.preference_learning import effective_preference_profile
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
    classify_user_intent,
    classify_detailed_intent,
    check_requirement_completeness,
    build_structured_trip_plan,
    validate_save_plan_payload,
    find_matching_catalog_destinations,
    filter_constraint_candidates,
)
from .guided_planning import guided_requirements
import re
import os
import json
import hashlib
from services.serpapi_service import retrieveDestinationResults
from datetime import date, timedelta

bp = Blueprint('fr11_chatbot', __name__, url_prefix='/api/fr11')


def _plan_id(plan):
    content = {key: value for key, value in plan.items() if key != 'draftId'}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode('utf-8')).hexdigest()[:24]


def _show_plan_request(message):
    return bool(re.search(r'\b(?:show (?:my |the )?(?:plan|itinerary|trip)|where (?:is |are )?(?:my |the )?trips?|can i see my trip)\b', message, re.I))


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
    preference = effective_preference_profile(retrieveRecord('travel_preferences', g.uid) or {}, retrieveRecord('learned_preference_profiles', g.uid))
    itineraries = retrieveRecord('itineraries', filters=[('travellerId', '==', g.uid)], limit=5) or []
    latest = itineraries[-1] if itineraries else {}
    base_context = (
        f"Traveller preferences: personality={preference.get('travelPersonality')}, "
        f"interests={preference.get('interests')}, budget={preference.get('budgetRange')}, "
        f"pace={preference.get('travelPace')}, purpose={preference.get('travelPurpose')}.\n"
        f"Learned concept affinities (bounded; questionnaire unchanged): {preference.get('learnedAffinities')}.\n"
        f"Current/latest itinerary: title={latest.get('title')}, destination={latest.get('destinationArea')}, "
        f"budgetLimit={latest.get('budgetLimit')}, budgetEstimate={latest.get('budgetEstimate')}, "
        f"activities={[x.get('activityName') for x in latest.get('activities', [])[:8]]}."
    )
    planning = (session or {}).get('planningState') or {}
    if planning:
        parts = []
        if planning.get('destinationArea'):
            parts.append(f"Destination: {planning.get('destinationArea')} ({planning.get('destinationState', 'Malaysia')})")
        if planning.get('tripMode') == 'road_trip':
            parts.append(
                f"Road trip: {planning.get('originDestination')} to {planning.get('targetDestination')} "
                f"via {planning.get('multipleDestinations')}"
            )
        if planning.get('tripDays'):
            parts.append(f"Duration: {planning.get('tripDays')} days")
        if planning.get('budgetLimit'):
            parts.append(f"Budget: RM{planning.get('budgetLimit')}")
        if planning.get('travellerCount'):
            parts.append(f"Travellers: {planning.get('travellerCount')}")
        if planning.get('startDate'):
            parts.append(f"Dates: {planning.get('startDate')} to {planning.get('endDate')}")
        if planning.get('interests'):
            parts.append(f"Interests: {', '.join(planning.get('interests'))}")
        if planning.get('excludedInterests'):
            parts.append(f"Excluded/Disliked: {', '.join(planning.get('excludedInterests'))}")
        if planning.get('excludedActivityTypes'):
            parts.append(f"Excluded activity types: {', '.join(planning.get('excludedActivityTypes'))}")
        if planning.get('preferIndoor'):
            parts.append("Weather preference: Prefers indoor / rain-safe activities")
        if planning.get('daySpecificPreferences'):
            parts.append(f"Day preferences: {planning.get('daySpecificPreferences')}")
        base_context += f"\nActive trip planning state: {'; '.join(parts)}."
    return base_context


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

    return matches[:4]


@bp.post('/chat')
@auth_required(['traveller'])
def chat():
    payload = request.get_json(silent=True) or {}
    message = str(payload.get('message', '')).strip()
    if not validateQuestion(message):
        return jsonify({'ok': False, 'error': 'message is required'}), 400

    if len(message) > 2000:
        return jsonify({'ok': False, 'error': 'Message exceeds 2000 character limit'}), 400

    session = _session_ref(payload.get('sessionId')) or _new_session(_session_title(message))
    messages = [dict(x) for x in session.get('messages', []) if isinstance(x, dict)]
    if len(messages) >= 30:
        return jsonify({'ok': False, 'error': 'Chat session limit reached. Start a new chat session to continue.'}), 429

    planning_state = dict(session.get('planningState') or {})
    previous_requirements = {key: planning_state.get(key) for key in ('destinationArea', 'startDate', 'endDate', 'tripDays', 'budgetLimit', 'travellerCount', 'interests', 'excludedInterests', 'excludedActivityTypes', 'preferIndoor', 'travelPace', 'budgetRange', 'avoidCrowds')}

    # Extract NLP requirements from user message
    geo = extract_geographic_entities(message)
    dur = extract_duration(message, planning_state.get('tripDays'))
    bud = extract_budget(message, planning_state.get('budgetLimit'))
    trav = extract_travellers(message, planning_state.get('travellerCount'))
    date_error = None
    try:
        s_date, e_date = extract_dates(message, dur or 3)
    except ValueError as error:
        s_date = e_date = None
        date_error = str(error)
    dates_supplied = bool(s_date and e_date)
    if date_error:
        planning_state['dateClarification'] = date_error
    elif s_date and e_date:
        dur = (date.fromisoformat(e_date) - date.fromisoformat(s_date)).days + 1
        planning_state.pop('dateClarification', None)
    elif extract_duration(message) is not None:
        if planning_state.pop('dateClarification', None):
            planning_state.pop('startDate', None)
            planning_state.pop('endDate', None)
    if not date_error and not s_date and not e_date:
        s_date, e_date = planning_state.get('startDate'), planning_state.get('endDate')
        if s_date and e_date:
            dur = (date.fromisoformat(e_date) - date.fromisoformat(s_date)).days + 1
    ints = extract_interests(message, planning_state.get('interests'))
    ex_ints = extract_excluded_interests(message, planning_state.get('excludedInterests'))
    ex_types = extract_excluded_activity_types(message, planning_state.get('excludedActivityTypes'))
    indoor_pref = extract_indoor_preference(message, planning_state.get('preferIndoor'))
    if re.search(r'\b(relaxing|relaxed|slow[- ]paced|easy pace)\b', message, re.I):
        planning_state['travelPace'] = 'relaxed'
    if re.search(r'\b(active pace|busy pace|packed trip)\b', message, re.I):
        planning_state['travelPace'] = 'active'
    if re.search(r'\b(affordable|low[- ]cost|cheap)\b', message, re.I):
        planning_state['budgetRange'] = 'Budget'
    if re.search(r"\b(avoid|don't want|do not want|no)\b.{0,20}\bcrowd", message, re.I):
        planning_state['avoidCrowds'] = True
    day_pref = extract_day_specific(message)
    detailed_intent = classify_detailed_intent(message, planning_state)

    # Update accumulated planning state
    if geo.get('destination_area'):
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
        planning_state['endDate'] = e_date
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
        cur_day.update(day_pref)
        planning_state['daySpecificPreferences'] = cur_day
    if detailed_intent:
        planning_state['lastIntent'] = detailed_intent
    requirements_changed = any(planning_state.get(key) != value for key, value in previous_requirements.items())
    if requirements_changed or date_error:
        planning_state.pop('activePlan', None)
    existing_plan = planning_state.get('activePlan') if _show_plan_request(message) and not planning_state.get('dateClarification') else None
    if geo.get('is_multi_destination'):
        planning_state['tripMode'] = 'road_trip'
        planning_state['multipleDestinations'] = list(geo.get('multiple_destinations') or [])
        planning_state['originDestination'] = geo.get('origin_destination')
        planning_state['targetDestination'] = geo.get('target_destination')
    elif geo.get('destination_area') and (
        geo.get('is_destination_change') or detailed_intent == 'ITINERARY_PLANNING'
    ):
        _clear_multi_destination_state(planning_state)

    if payload.get('guidedPlanning') is True:
        planning_state['guidedPlanning'] = True
    guided_check = None
    if existing_plan:
        guided_check = {'clarification_needed': False, 'ready': False}
    elif planning_state.get('guidedPlanning'):
        preferences = retrieveRecord('travel_preferences', g.uid) or {}
        guided_check = guided_requirements(message, planning_state, preferences, dates_supplied=dates_supplied)
    guided_ready = bool(guided_check and guided_check.get('ready'))
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
            'message': message,
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
    req_check = ({'clarification_needed': True, 'clarification_prompt': planning_state['dateClarification']}
                 if planning_state.get('dateClarification') else guided_check or check_requirement_completeness(message, planning_state))
    if req_check.get('clarification_needed'):
        clarification_reply = req_check.get('clarification_prompt')
        if not planning_state.get('dateClarification') and s_date and e_date and re.search(r'\b(?:until|to|through|till)\b|\d{4}-\d{2}-\d{2}|[–—]', message, re.I):
            clarification_reply = f'Travel dates: {s_date} to {e_date} ({dur} calendar days, {dur - 1} nights). ' + clarification_reply
        item = {
            'id': 'chat_' + utc_now_iso().replace(':', '').replace('-', '').replace('.', ''),
            'travellerId': g.uid,
            'message': message,
            'reply': clarification_reply,
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
        return jsonify({'ok': True, 'reply': clarification_reply, 'source': 'travelmate-assistant', 'messageId': record['id'], 'item': item, 'session': session})

    history = messages[-20:] or retrieveRecord('chat_messages', filters=[('travellerId', '==', g.uid)], limit=20) or []
    system_context = _context(session)
    recent_context = ''
    if history:
        recent = history[-3:]
        recent_context = '\n'.join(f"Traveller: {x.get('message')}\nTravelMate: {x.get('reply')}" for x in recent)
    context = system_context + ('\nRecent conversation:\n' + recent_context if recent_context else '')

    road_trip_unsupported = (
        planning_state.get('tripMode') == 'road_trip'
        and classify_user_intent(message, planning_state) == 'PLANNING_REQUEST'
    )
    if road_trip_unsupported:
        response = {'reply': _unsupported_road_trip_reply(planning_state), 'source': 'travelmate-assistant'}
    elif re.search(r'\bmore (?:places )?like this\b', message, re.I):
        response = {'reply':'Choose More like this on a specific For You destination card so the selected place can be identified. Casual chat does not overwrite your saved questionnaire.', 'source':'travelmate-assistant'}
    elif existing_plan:
        response = {'reply': 'Here is your existing itinerary. Review the day-by-day card below.', 'source': 'travelmate-assistant'}
    elif guided_ready:
        response = {'reply': 'Here is a draft based on your trip details and saved preferences. Review its dates, budget and activities before choosing Save. No trip or booking has been created.', 'source': 'travelmate-assistant'}
    elif geo.get('is_destination_change'):
        response = {'reply': _destination_change_reply(planning_state), 'source': 'travelmate-assistant'}
    else:
        try:
            response = (
                generateFollowUpResponse(message, context, with_source=True, planning_state=planning_state)
                if history else generateChatbotResponse(message, context, with_source=True, planning_state=planning_state)
            )
        except Exception as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 502

    reply, source = response['reply'], response['source']
    if detailed_intent in {'INTEREST_MODIFICATION', 'INDOOR_ALTERNATIVE'} and (
        planning_state.get('excludedInterests')
        or planning_state.get('excludedActivityTypes')
        or planning_state.get('preferIndoor')
    ):
        reply = _constraint_acknowledgement(planning_state)
        source = 'travelmate-assistant'
    item = {
        'id': 'chat_' + utc_now_iso().replace(':', '').replace('-', '').replace('.', ''),
        'travellerId': g.uid,
        'message': message,
        'reply': reply,
        'source': source,
        'createdAt': utc_now_iso(),
    }
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
        not existing_plan and (guided_ready or classify_user_intent(message, planning_state) == 'PLANNING_REQUEST')
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

        catalog = DESTINATIONS
        if not find_matching_catalog_destinations(dest_for_planning, dest_state_for_planning) and os.getenv('SERPAPI_KEY', '').strip():
            try:
                result = retrieveDestinationResults(f'tourist attractions {dest_for_planning}', dest_for_planning)
                catalog = result.get('local_results') or []
            except Exception:
                catalog = []
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

    suggestions = _extract_place_suggestions(
        message,
        destination_area=dest_for_planning,
        prefer_indoor=planning_state.get('preferIndoor', False),
        excluded_interests=planning_state.get('excludedInterests'),
        excluded_activity_types=planning_state.get('excludedActivityTypes'),
    )
    if suggestions and not plan:
        item['placeSuggestions'] = suggestions

    record = storeRecord('chat_messages', {**item, 'sessionId': session['id']})
    item['id'] = record['id']
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
        state = dict(save_session.get('planningState') or {})
        state['savedPlans'] = {**(state.get('savedPlans') or {}), draft_id: result['id']}
        updateRecord('chat_sessions', save_session['id'], {'planningState': state})
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
