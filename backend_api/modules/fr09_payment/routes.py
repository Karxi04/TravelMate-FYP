from flask import Blueprint, request, jsonify, g
from auth_utils import auth_required
from utils import utc_now_iso
from services.stripe_service import createPaymentSession, processSandboxPayment, returnPaymentStatus
from sequence_contract.validators import validatePaymentInput
from sequence_contract.firebase_firestore import retrieveRecord, storeRecord, updateRecord

bp = Blueprint('fr09_payments', __name__, url_prefix='/api/fr9')


def _resolve_booking(booking_id):
    if not booking_id:
        return None, None
    bid = str(booking_id).strip()
    # 1. Direct document ID
    rec = retrieveRecord('hotel_bookings', bid)
    if isinstance(rec, dict) and rec:
        return bid, rec
    # 2. Query by bookingReference
    by_ref = retrieveRecord('hotel_bookings', filters=[('bookingReference', '==', bid)])
    if by_ref and isinstance(by_ref[0], dict):
        return by_ref[0].get('id') or bid, by_ref[0]
    return None, None


def _record(intent, booking_id, amount):
    intent_id = getattr(intent, 'id', str(intent))
    status = getattr(intent, 'status', 'succeeded')
    data = {
        'travellerId': g.uid,
        'bookingId': booking_id or '',
        'amount': amount,
        'currency': 'myr',
        'paymentStatus': status,
        'transactionReference': intent_id,
        'createdAt': utc_now_iso(),
    }
    storeRecord('payment_records', data, intent_id, merge=True)
    return data


@bp.post('/payments/create-intent')
@auth_required(['traveller'])
def create_payment_intent():
    payload = request.get_json(silent=True) or {}
    booking_doc_id, booking = _resolve_booking(payload.get('bookingId'))

    if booking:
        if booking.get('travellerId') and booking.get('travellerId') != g.uid:
            return jsonify({'ok': False, 'error': 'Unauthorized: booking does not belong to current traveller'}), 403
        authoritative = float(booking.get('hotelCost') or booking.get('price') or booking.get('totalPrice') or 0)
        if authoritative > 0:
            payload['amount'] = authoritative

    if not validatePaymentInput(payload):
        return jsonify({'ok': False, 'error': 'Positive amount is required'}), 400

    try:
        session = createPaymentSession(payload, g.uid, str(payload.get('bookingId', '')))
        data = _record(session, payload.get('bookingId'), float(payload['amount']))
        return jsonify({
            'ok': True,
            'paymentIntentId': getattr(session, 'id', str(session)),
            'clientSecret': getattr(session, 'client_secret', None),
            'status': getattr(session, 'status', 'requires_payment_method'),
            'payment': data,
        })
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 502


@bp.post('/payments/process')
@auth_required(['traveller'])
def process_payment():
    payload = request.get_json(silent=True) or {}
    booking_doc_id, booking = _resolve_booking(payload.get('bookingId'))

    if booking:
        if booking.get('travellerId') and booking.get('travellerId') != g.uid:
            return jsonify({'ok': False, 'error': 'Unauthorized: booking does not belong to current traveller'}), 403
        authoritative = float(booking.get('hotelCost') or booking.get('price') or booking.get('totalPrice') or 0)
        if authoritative > 0:
            payload['amount'] = authoritative

    if not validatePaymentInput(payload):
        return jsonify({'ok': False, 'error': 'Positive amount is required'}), 400

    try:
        session = createPaymentSession(payload, g.uid, str(payload.get('bookingId', '')))
        intent = processSandboxPayment(paymentInput=payload, travellerId=g.uid, bookingId=str(payload.get('bookingId', '')))
        data = _record(intent, payload.get('bookingId'), float(payload['amount']))

        if booking_doc_id:
            updateRecord('hotel_bookings', booking_doc_id, {
                'bookingStatus': 'paid',
                'paymentReference': getattr(intent, 'id', str(intent)),
                'updatedAt': utc_now_iso(),
            })

        return jsonify({
            'ok': True,
            'paymentSessionId': getattr(session, 'id', str(session)),
            'payment': data,
        })
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 502


@bp.post('/payments/<payment_id>/retry')
@auth_required(['traveller'])
def retry_payment(payment_id):
    existing = retrieveRecord('payment_records', payment_id)
    if not existing or existing.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'Payment not found'}), 404
    try:
        intent = processSandboxPayment(paymentInput=existing, travellerId=g.uid, bookingId=existing.get('bookingId', ''))
        intent_id = getattr(intent, 'id', str(intent))
        status = getattr(intent, 'status', 'succeeded')
        updateRecord('payment_records', payment_id, {
            'paymentStatus': status,
            'transactionReference': intent_id,
            'updatedAt': utc_now_iso(),
        })
        return jsonify({'ok': True, 'status': status})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 502


@bp.post('/payments/<payment_id>/cancel')
@auth_required(['traveller'])
def cancel_payment(payment_id):
    existing = retrieveRecord('payment_records', payment_id)
    if not existing or existing.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'Payment not found'}), 404
    status = existing.get('paymentStatus', 'unknown')
    try:
        status = returnPaymentStatus(existing.get('transactionReference') or payment_id)
    except Exception:
        pass
    result = updateRecord('payment_records', payment_id, {
        'paymentStatus': 'cancelled',
        'previousProviderStatus': status,
        'updatedAt': utc_now_iso(),
    })
    return jsonify({'ok': True, 'payment': result})


@bp.get('/payments')
@auth_required(['traveller'])
def list_payments():
    return jsonify({'ok': True, 'items': retrieveRecord('payment_records', filters=[('travellerId', '==', g.uid)]) or []})
