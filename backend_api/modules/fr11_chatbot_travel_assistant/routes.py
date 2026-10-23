from flask import Blueprint, request, jsonify, g
from auth_utils import auth_required
from utils import utc_now_iso
from services.gemini_service import generateChatbotResponse, generateFollowUpResponse
from sequence_contract.validators import validateQuestion
from sequence_contract.firebase_firestore import retrieveRecord, storeRecord, deleteRecord, updateRecord
from sequence_contract.domain_functions import createItinerary, calculateBudget
from services.local_catalog import DESTINATIONS
from .nlp_extractor import (
    extract_geographic_entities,
    extract_duration,
    extract_budget,
    extract_travellers,
    extract_dates,
    extract_interests,
    extract_day_specific,
    classify_user_intent,
    check_requirement_completeness,
    build_structured_trip_plan,
    validate_save_plan_payload,
    find_matching_catalog_destinations,
)
import re
from datetime import date, timedelta

bp = Blueprint('fr11_chatbot', __name__, url_prefix='/api/fr11')


def _session_title(message):
    title = ' '.join(str(message or '').strip().split())
    return title[:42] if title else 'New travel chat'


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
    preference = retrieveRecord('travel_preferences', g.uid) or {}
    itineraries = retrieveRecord('itineraries', filters=[('travellerId', '==', g.uid)], limit=5) or []
    latest = itineraries[-1] if itineraries else {}
    base_context = (
        f"Traveller preferences: personality={preference.get('travelPersonality')}, "
        f"interests={preference.get('interests')}, budget={preference.get('budgetRange')}, "
        f"pace={preference.get('travelPace')}, purpose={preference.get('travelPurpose')}.\n"
        f"Current/latest itinerary: title={latest.get('title')}, destination={latest.get('destinationArea')}, "
        f"budgetLimit={latest.get('budgetLimit')}, budgetEstimate={latest.get('budgetEstimate')}, "
        f"activities={[x.get('activityName') for x in latest.get('activities', [])[:8]]}."
    )
    planning = (session or {}).get('planningState') or {}
    if planning:
        parts = []
        if planning.get('destinationArea'):
            parts.append(f"Destination: {planning.get('destinationArea')} ({planning.get('destinationState', 'Malaysia')})")
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
        if planning.get('daySpecificPreferences'):
            parts.append(f"Day preferences: {planning.get('daySpecificPreferences')}")
        base_context += f"\nActive trip planning state: {'; '.join(parts)}."
    return base_context


def _extract_plan_from_message(message, planning_state=None):
    state = dict(planning_state or {})
    geo = extract_geographic_entities(message)

    # Reject foreign destinations from plan generation
    if geo.get('is_foreign'):
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
    s_date, e_date = extract_dates(message, dur or 3, state.get('startDate'), state.get('endDate'))
    ints = extract_interests(message, state.get('interests', []))

    plan, status = build_structured_trip_plan(
        destination_area=dest,
        destination_state=dest_state,
        days=dur or 3,
        budget_limit=bud or 1200.0,
        traveller_count=trav or 1,
        start_date=s_date,
        end_date=e_date,
        interests=ints,
    )
    return plan if status == 'ready' else None


def _extract_place_suggestions(message, destination_area=None):
    q = str(message or '').lower()
    triggers = ['food', 'eat', 'restaurant', 'place', 'attraction', 'visit', 'recommend', 'where', 'suggest', 'sight', 'see']
    if not any(t in q for t in triggers):
        return []

    # If destination is known, isolate suggestions strictly to that destination
    if destination_area:
        candidates = find_matching_catalog_destinations(destination_area)
    else:
        candidates = DESTINATIONS

    if not candidates:
        return []

    # Recognize active rain / wet weather / indoor request using bounded word matching
    is_rain_indoor = bool(re.search(
        r'\b(?:rain|rains|rainy|raining|downpour|thunderstorm|wet\s+weather|indoor|sheltered)\b',
        q
    ))

    if is_rain_indoor:
        candidates = [d for d in candidates if bool(d.get('indoor', False))]
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

    # Extract NLP requirements from user message
    geo = extract_geographic_entities(message)
    dur = extract_duration(message, planning_state.get('tripDays'))
    bud = extract_budget(message, planning_state.get('budgetLimit'))
    trav = extract_travellers(message, planning_state.get('travellerCount'))
    s_date, e_date = extract_dates(message, dur or 3, planning_state.get('startDate'), planning_state.get('endDate'))
    ints = extract_interests(message, planning_state.get('interests'))
    day_pref = extract_day_specific(message)

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
    if day_pref:
        cur_day = dict(planning_state.get('daySpecificPreferences') or {})
        cur_day.update(day_pref)
        planning_state['daySpecificPreferences'] = cur_day

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
    req_check = check_requirement_completeness(message, planning_state)
    if req_check.get('clarification_needed'):
        clarification_reply = req_check.get('clarification_prompt')
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

    try:
        response = (
            generateFollowUpResponse(message, context, with_source=True, planning_state=planning_state)
            if history else generateChatbotResponse(message, context, with_source=True, planning_state=planning_state)
        )
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 502

    reply, source = response['reply'], response['source']
    item = {
        'id': 'chat_' + utc_now_iso().replace(':', '').replace('-', '').replace('.', ''),
        'travellerId': g.uid,
        'message': message,
        'reply': reply,
        'source': source,
        'createdAt': utc_now_iso(),
    }

    # Extract structured plan and suggestions
    dest_for_planning = planning_state.get('destinationArea') or geo.get('destination_area')
    dest_state_for_planning = planning_state.get('destinationState') or geo.get('destination_state')
    plan = None
    if classify_user_intent(message, planning_state) == 'PLANNING_REQUEST' and dest_for_planning:
        dur_val = planning_state.get('tripDays') or 3
        bud_val = planning_state.get('budgetLimit') or 1200.0
        trav_val = planning_state.get('travellerCount') or 1
        s_date_val = planning_state.get('startDate')
        e_date_val = planning_state.get('endDate')
        ints_val = planning_state.get('interests')

        plan, plan_status = build_structured_trip_plan(
            destination_area=dest_for_planning,
            destination_state=dest_state_for_planning,
            days=dur_val,
            budget_limit=bud_val,
            traveller_count=trav_val,
            start_date=s_date_val,
            end_date=e_date_val,
            interests=ints_val,
        )
        if plan and plan_status == 'ready':
            item['tripPlan'] = plan
        elif plan_status == 'coverage_gap':
            item['dataCoverage'] = {
                'status': 'coverage_gap',
                'destinationArea': dest_for_planning,
                'destinationState': dest_state_for_planning or '',
                'destinationCountry': 'Malaysia',
                'message': f"Structured activity data for {dest_for_planning} is currently undergoing verified catalog ingestion. General travel advice has been provided."
            }

    suggestions = _extract_place_suggestions(message, destination_area=dest_for_planning)
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
            'gps_coordinates': act.get('gps_coordinates') or act.get('gpsCoordinates') or {},
            'type': act.get('type') or act.get('category') or '',
            'category': act.get('category') or act.get('type') or '',
            'description': act.get('description') or '',
            'indoor': bool(act.get('indoor', False)),
            'openingHours': act.get('openingHours') or '',
            'recommendedDurationMinutes': int(act.get('recommendedDurationMinutes') or act.get('durationMinutes') or 90),
            'travelBufferMinutes': int(act.get('travelBufferMinutes') or 15),
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
        'budgetLimit': limit,
        'activities': clean_activities,
        'transportCost': float(plan.get('transportCost') or 0.0),
        'accommodationCost': float(plan.get('accommodationCost') or 0.0),
        'miscCost': float(plan.get('miscCost') or 0.0),
        'status': plan.get('status', 'draft'),
    }

    itinerary = createItinerary(itinerary_data, g.uid)
    budget = calculateBudget(itinerary)
    itinerary['budgetEstimate'] = budget
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
