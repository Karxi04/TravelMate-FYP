"""Owner-scoped turn receipts. Status reads never replay or persist a chat turn."""
import hashlib
import json
import re
from time import monotonic

from flask import current_app, g, jsonify, make_response
from utils import utc_now_iso


def request_key(uid, identity):
    return hashlib.sha256(f'{uid}:{identity}'.encode()).hexdigest()


def valid_identity(identity):
    return isinstance(identity, str) and re.fullmatch(r'[A-Za-z0-9_-]{16,100}', identity) is not None


def status(read, uid, identity):
    record = read('chat_requests', request_key(uid, identity))
    if not isinstance(record, dict) or record.get('travellerId') != uid:
        return {'status': 'unknown'}
    session = read('chat_sessions', record['sessionId']) if record.get('sessionId') else None
    if not isinstance(session, dict) or session.get('travellerId') != uid:
        session = None
    matches = [item for item in (session or {}).get('messages', [])
               if isinstance(item, dict) and item.get('clientRequestId') == identity]
    if matches:
        return {'status': 'completed', 'session': session, 'item': matches[-1], 'reply': matches[-1].get('reply')}
    return {'status': 'rejected' if record.get('state') == 'rejected' else 'pending',
            **({'session': session} if session else {})}


def run(payload, uid, handler, read, claim, update):
    identity = payload.get('clientRequestId') if isinstance(payload, dict) else None
    if identity is None:
        return handler(payload)  # Existing installed clients retain their contract.
    if not valid_identity(identity):
        return jsonify(ok=False, error='Invalid chat request identifier.'), 400
    message = payload.get('message')
    if not isinstance(message, str) or not message.strip() or len(message) > 2000:
        return jsonify(ok=False, error='Use a message of 1 to 2000 characters.'), 400
    if payload.get('sessionId') is not None and (not isinstance(payload['sessionId'], str) or
            re.fullmatch(r'[A-Za-z0-9_-]{1,150}', payload['sessionId']) is None):
        return jsonify(ok=False, error='Invalid chat session identifier.'), 400
    if payload.get('sessionId'):
        session = read('chat_sessions', payload['sessionId'])
        if not session or session.get('travellerId') != uid:
            return jsonify(ok=False, error='Chat session not found.'), 404
    key = request_key(uid, identity)
    fingerprint = hashlib.sha256(json.dumps({k: payload.get(k) for k in
        ('message', 'sessionId', 'guidedPlanning', 'commerceRevision')}, sort_keys=True).encode()).hexdigest()
    record, created = claim('chat_requests', key, {
        'travellerId': uid, 'fingerprint': fingerprint, 'sessionId': payload.get('sessionId'),
        'state': 'pending', 'createdAt': utc_now_iso(),
    })
    if record.get('travellerId') != uid or record.get('fingerprint') != fingerprint:
        return jsonify(ok=False, code='chat_request_mismatch', error='This request identifier belongs to a different message.'), 409
    if not created:
        result = status(read, uid, identity)
        if result['status'] == 'completed':
            return jsonify(ok=True, **result, source=result['item'].get('source'), messageId=result['item'].get('id'))
        return jsonify(ok=False, code='chat_request_pending', error='Check the saved conversation before sending this message again.', **result), 409
    g.chat_client_request_id, g.chat_request_key = identity, key
    started = monotonic()
    try:
        response = make_response(handler(payload))
        data = response.get_json(silent=True) or {}
        state = ('completed' if response.status_code == 200 else
                 'rejected' if response.status_code in (400, 404, 429) or data.get('code') == 'stale_chat_context' else 'pending')
        try:
            update('chat_requests', key, {'state': state, 'updatedAt': utc_now_iso()})
        except Exception:
            # A committed session message is the authoritative receipt if this optional acknowledgement fails.
            current_app.logger.warning('chat_receipt_deferred request=%s', key[:16])
        return response
    except Exception:
        current_app.logger.warning('chat_delivery_unverified request=%s', key[:16])
        return jsonify(ok=False, code='chat_delivery_unknown', error='Message delivery is unconfirmed. Check the conversation before retrying.'), 503
    finally:
        current_app.logger.info('chat_request_finished request=%s elapsed_ms=%s', key[:16], round((monotonic() - started) * 1000))
