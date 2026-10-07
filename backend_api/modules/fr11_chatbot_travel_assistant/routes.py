from flask import Blueprint, request, jsonify, g
from auth_utils import auth_required
from utils import utc_now_iso
from services.gemini_service import generateChatbotResponse, generateFollowUpResponse
from sequence_contract.validators import validateQuestion
from sequence_contract.firebase_firestore import retrieveRecord, storeRecord, deleteRecord, updateRecord
from sequence_contract.domain_functions import createItinerary, calculateBudget
from services.local_catalog import DESTINATIONS
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
        'createdAt': now,
        'updatedAt': now,
    })


def _sorted_sessions():
    sessions = retrieveRecord('chat_sessions', filters=[('travellerId', '==', g.uid)]) or []
    sessions.sort(key=lambda x: str(x.get('updatedAt') or x.get('createdAt') or ''), reverse=True)
    return sessions


def _context():
    preference = retrieveRecord('travel_preferences', g.uid) or {}
    itineraries = retrieveRecord('itineraries', filters=[('travellerId', '==', g.uid)], limit=5) or []
    latest = itineraries[-1] if itineraries else {}
    return (
        f"Traveller preferences: personality={preference.get('travelPersonality')}, "
        f"interests={preference.get('interests')}, budget={preference.get('budgetRange')}, "
        f"pace={preference.get('travelPace')}, purpose={preference.get('travelPurpose')}.\n"
        f"Current/latest itinerary: title={latest.get('title')}, destination={latest.get('destinationArea')}, "
        f"budgetLimit={latest.get('budgetLimit')}, budgetEstimate={latest.get('budgetEstimate')}, "
        f"activities={[x.get('activityName') for x in latest.get('activities', [])[:8]]}."
    )


def _extract_plan_from_message(message):
    q = str(message or '').lower()
    planning_triggers = ['plan', 'itinerary', 'trip', 'schedule', 'arrange', 'visit']
    if not any(t in q for t in planning_triggers):
        return None

    dest = 'Penang'
    for city in ['kuala lumpur', 'penang', 'langkawi', 'melaka', 'malacca', 'sabah', 'sarawak', 'johor']:
        if city in q:
            dest = 'Melaka' if city == 'malacca' else city.title()
            break

    days = 3
    day_match = re.search(r'(\d+)\s*(?:-| )?\s*day', q)
    if day_match:
        try:
            days = max(1, min(7, int(day_match.group(1))))
        except Exception:
            days = 3

    matching = [
        d for d in DESTINATIONS
        if dest.lower() in str(d.get('address', '')).lower() or dest.lower() in str(d.get('title', '')).lower()
    ]
    if not matching:
        matching = DESTINATIONS[:6]

    activities = []
    time_slots = ['Morning (09:00 - 12:00)', 'Afternoon (13:30 - 16:30)', 'Evening (18:00 - 20:30)']
    idx = 0
    for day_no in range(1, days + 1):
        for slot in time_slots:
            if not matching:
                break
            d = matching[idx % len(matching)]
            idx += 1
            activities.append({
                'activityId': f'A{len(activities) + 1}',
                'activityName': d.get('title') or d.get('name') or f'Stop {len(activities) + 1}',
                'destinationId': d.get('destinationId') or d.get('place_id') or f'dest_{len(activities) + 1}',
                'address': d.get('address', ''),
                'dayNo': day_no,
                'timeSlot': slot,
                'timeRangeLabel': slot,
                'estimatedCost': float(d.get('estimatedCost', 0) or 0),
                'gps_coordinates': d.get('gps_coordinates', {}),
                'type': d.get('type') or d.get('category') or '',
                'category': d.get('category') or d.get('type') or '',
                'description': d.get('description', ''),
                'indoor': bool(d.get('indoor', False)),
                'recommendedDurationMinutes': int(d.get('recommendedDurationMinutes', 90) or 90),
                'travelBufferMinutes': 15,
                'scheduleNotes': [f"Recommended stop for Day {day_no}"],
            })

    start_date = date.today()
    end_date = start_date + timedelta(days=days - 1)
    return {
        'title': f"{days}-Day {dest} Itinerary Plan",
        'destinationArea': dest,
        'startDate': start_date.isoformat(),
        'endDate': end_date.isoformat(),
        'budgetLimit': 1200.0,
        'activities': activities,
        'numberOfTravellers': 1,
    }


def _extract_place_suggestions(message):
    q = str(message or '').lower()
    triggers = ['food', 'eat', 'restaurant', 'place', 'attraction', 'visit', 'recommend', 'where', 'suggest']
    if not any(t in q for t in triggers):
        return []
    matches = []
    for d in DESTINATIONS:
        combined = f"{d.get('title', '')} {d.get('address', '')} {d.get('category', '')} {d.get('description', '')}".lower()
        if any(term in combined for term in q.split() if len(term) > 3):
            matches.append(d)
    return matches[:4]


@bp.post('/chat')
@auth_required(['traveller'])
def chat():
    payload = request.get_json(silent=True) or {}
    message = str(payload.get('message', '')).strip()
    if not validateQuestion(message):
        return jsonify({'ok': False, 'error': 'message is required'}), 400

    session = _session_ref(payload.get('sessionId')) or _new_session(_session_title(message))
    messages = [dict(x) for x in session.get('messages', []) if isinstance(x, dict)]
    if len(messages) >= 30:
        return jsonify({'ok': False, 'error': 'Chat session limit reached. Start a new chat session to continue.'}), 429
    history = messages[-20:] or retrieveRecord('chat_messages', filters=[('travellerId', '==', g.uid)], limit=20) or []
    system_context = _context()
    recent_context = ''
    if history:
        recent = history[-3:]
        recent_context = '\n'.join(f"Traveller: {x.get('message')}\nTravelMate: {x.get('reply')}" for x in recent)
    context = system_context + ('\nRecent conversation:\n' + recent_context if recent_context else '')

    try:
        response = (
            generateFollowUpResponse(message, context, with_source=True)
            if history else generateChatbotResponse(message, context, with_source=True)
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
    plan = _extract_plan_from_message(message)
    if plan:
        item['tripPlan'] = plan
    suggestions = _extract_place_suggestions(message)
    if suggestions and not plan:
        item['placeSuggestions'] = suggestions

    record = storeRecord('chat_messages', {**item, 'sessionId': session['id']})
    item['id'] = record['id']
    messages.append(item)
    updates = {
        'messages': messages,
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
    if not plan or not isinstance(plan, dict):
        return jsonify({'ok': False, 'error': 'No trip plan is available to save.'}), 400

    dest = plan.get('destinationArea') or plan.get('destination') or ''
    if not dest:
        title = str(plan.get('title', ''))
        for known in ['Penang', 'Kuala Lumpur', 'Langkawi', 'Melaka', 'Sabah', 'Sarawak', 'Johor']:
            if known.lower() in title.lower():
                dest = known
                break
        if not dest:
            dest = 'Penang'

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
