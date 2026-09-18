from flask import Blueprint, request, jsonify, g
from auth_utils import auth_required
from utils import utc_now_iso
from services.gemini_service import generateChatbotResponse, generateFollowUpResponse, is_gemini_configured
from sequence_contract.validators import validateQuestion
from sequence_contract.firebase_firestore import retrieveRecord, storeRecord, deleteRecord, updateRecord

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
        reply = generateFollowUpResponse(message, context) if history else generateChatbotResponse(message, context)
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 502

    source = 'gemini' if is_gemini_configured() else 'travelmate-assistant'
    item = {
        'id': 'chat_' + utc_now_iso().replace(':', '').replace('-', '').replace('.', ''),
        'travellerId': g.uid,
        'message': message,
        'reply': reply,
        'source': source,
        'createdAt': utc_now_iso(),
    }
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
