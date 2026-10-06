import uuid

from flask import Blueprint, request, jsonify, g

from auth_utils import auth_required
from utils import utc_now_iso
from services.stripe_service import (
    createPaymentSession,
    normalizePaymentStatus,
    processPaymentAttempt,
    returnPaymentStatus,
)
from services.transaction_reliability import (
    is_ambiguous_provider_error,
    normalize_attempt_id,
    operation_document_id,
    provider_idempotency_key,
)
from sequence_contract.validators import validatePaymentInput
from sequence_contract.firebase_firestore import claimRecord, retrieveRecord, updateRecord

bp = Blueprint('fr09_payments', __name__, url_prefix='/api/fr9')


def _resolve_booking(booking_id):
    if not booking_id:
        return None, None
    bid = str(booking_id).strip()
    rec = retrieveRecord('hotel_bookings', bid)
    if isinstance(rec, dict) and rec:
        return bid, rec
    by_ref = retrieveRecord('hotel_bookings', filters=[('bookingReference', '==', bid)])
    if by_ref and isinstance(by_ref[0], dict):
        return by_ref[0].get('id') or bid, by_ref[0]
    return None, None


def _payment_attempt_id(payload):
    # Legacy callers remain usable, but only a client-retained ID can provide
    # idempotency across a timeout/reconnect boundary.
    raw = payload.get('paymentAttemptId') or f"legacy_{uuid.uuid4().hex}"
    return normalize_attempt_id(raw, 'paymentAttemptId')


def _payment_document_id(attempt_id):
    return operation_document_id('payment', g.uid, attempt_id)


def _payment_response(record, status_code=200, reused=False, **extra):
    status = normalizePaymentStatus(record.get('paymentStatus'))
    payment = {
        key: value for key, value in record.items()
        if key != 'providerIdempotencyKey'
    }
    payment['paymentStatus'] = status
    return jsonify({
        'ok': status != 'failed',
        'payment': payment,
        'paymentAttemptId': payment.get('paymentAttemptId', ''),
        'status': status,
        'reused': reused,
        'reconciliationRequired': status == 'pending',
        **extra,
    }), status_code


def _claim_payment(payload, booking_doc_id):
    attempt_id = _payment_attempt_id(payload)
    document_id = _payment_document_id(attempt_id)
    booking_context = str(payload.get('bookingId') or booking_doc_id or '')
    now = utc_now_iso()
    record = {
        'travellerId': g.uid,
        'paymentAttemptId': attempt_id,
        'bookingId': booking_context,
        'amount': float(payload['amount']),
        'currency': 'myr',
        'paymentStatus': 'pending',
        'operationStage': 'provider_pending',
        'providerIdempotencyKey': provider_idempotency_key(
            'payment', g.uid, attempt_id, 'process'
        ),
        'cardBrand': payload.get('cardBrand', 'Card'),
        'cardLast4': payload.get('cardLast4', ''),
        'cardholderName': payload.get('cardholderName', ''),
        'billingEmail': payload.get('billingEmail', ''),
        'createdAt': now,
        'updatedAt': now,
    }
    claimed, created = claimRecord('payment_records', document_id, record)
    if claimed.get('travellerId') != g.uid:
        raise PermissionError('Payment attempt does not belong to current traveller')
    same_context = (
        str(claimed.get('bookingId') or '') == booking_context
        and float(claimed.get('amount') or 0) == float(payload['amount'])
    )
    if not same_context:
        raise ValueError('paymentAttemptId is already bound to another payment context')
    return document_id, claimed, created


def _finish_payment(document_id, record, intent, booking_doc_id=None):
    intent_id = getattr(intent, 'id', str(intent))
    status = normalizePaymentStatus(getattr(intent, 'status', 'pending'))
    patch = {
        'paymentStatus': status,
        'transactionReference': intent_id,
        'operationStage': 'provider_completed' if status != 'pending' else 'provider_pending',
        'updatedAt': utc_now_iso(),
    }
    updated = updateRecord('payment_records', document_id, patch) or {
        'id': document_id,
        **record,
        **patch,
    }
    if booking_doc_id and status == 'succeeded':
        updateRecord('hotel_bookings', booking_doc_id, {
            'bookingStatus': 'paid',
            'paymentReference': intent_id,
            'paymentAttemptId': record.get('paymentAttemptId'),
            'updatedAt': utc_now_iso(),
        })
    return updated


def _execute_payment(document_id, record, payload, booking_doc_id=None):
    try:
        intent = processPaymentAttempt(
            payload,
            g.uid,
            str(record.get('bookingId') or ''),
            record['providerIdempotencyKey'],
        )
        updated = _finish_payment(document_id, record, intent, booking_doc_id)
        return _payment_response(updated)
    except Exception as exc:
        if is_ambiguous_provider_error(exc):
            patch = {
                'paymentStatus': 'pending',
                'operationStage': 'provider_outcome_unknown',
                'reconciliationRequired': True,
                'updatedAt': utc_now_iso(),
            }
            pending = updateRecord('payment_records', document_id, patch) or {
                'id': document_id,
                **record,
                **patch,
            }
            return _payment_response(pending, 202)
        patch = {
            'paymentStatus': 'failed',
            'operationStage': 'provider_failed',
            'failureReason': str(exc),
            'updatedAt': utc_now_iso(),
        }
        updateRecord('payment_records', document_id, patch)
        return jsonify({
            'ok': False,
            'error': str(exc),
            'paymentAttemptId': record.get('paymentAttemptId'),
            'status': 'failed',
            'newAttemptRequired': True,
        }), 502


def _reconcile_payment_record(record):
    status = normalizePaymentStatus(record.get('paymentStatus'))
    if status != 'pending' or not record.get('transactionReference'):
        return record
    try:
        provider_status = normalizePaymentStatus(
            returnPaymentStatus(record['transactionReference'])
        )
    except Exception:
        return record
    patch = {
        'paymentStatus': provider_status,
        'operationStage': 'provider_completed' if provider_status != 'pending' else 'provider_pending',
        'updatedAt': utc_now_iso(),
    }
    return updateRecord('payment_records', record['id'], patch) or {**record, **patch}


@bp.post('/payments/create-intent')
@auth_required(['traveller'])
def create_payment_intent():
    payload = request.get_json(silent=True) or {}
    _, booking = _resolve_booking(payload.get('bookingId'))
    if booking:
        if booking.get('travellerId') and booking.get('travellerId') != g.uid:
            return jsonify({'ok': False, 'error': 'Unauthorized: booking does not belong to current traveller'}), 403
        authoritative = float(booking.get('hotelCost') or booking.get('price') or booking.get('totalPrice') or 0)
        if authoritative > 0:
            payload['amount'] = authoritative
    if not validatePaymentInput(payload):
        return jsonify({'ok': False, 'error': 'Positive amount is required'}), 400
    try:
        attempt_id = _payment_attempt_id(payload)
        key = provider_idempotency_key('payment', g.uid, attempt_id, 'intent')
        document_id = operation_document_id('payment_intent', g.uid, attempt_id)
        now = utc_now_iso()
        claimed, created = claimRecord('payment_intent_attempts', document_id, {
            'travellerId': g.uid,
            'paymentAttemptId': attempt_id,
            'bookingId': str(payload.get('bookingId', '')),
            'amount': float(payload['amount']),
            'paymentStatus': 'pending',
            'providerIdempotencyKey': key,
            'createdAt': now,
            'updatedAt': now,
        })
        if (
            str(claimed.get('bookingId') or '') != str(payload.get('bookingId', ''))
            or float(claimed.get('amount') or 0) != float(payload['amount'])
        ):
            return jsonify({'ok': False, 'error': 'paymentAttemptId is already bound to another payment context'}), 409
        if not created and claimed.get('transactionReference'):
            return jsonify({
                'ok': True,
                'paymentAttemptId': attempt_id,
                'paymentIntentId': claimed['transactionReference'],
                'clientSecret': claimed.get('clientSecret'),
                'status': claimed.get('providerStatus', 'requires_payment_method'),
                'reused': True,
            })
        session = createPaymentSession(
            payload,
            g.uid,
            str(payload.get('bookingId', '')),
            idempotencyKey=key,
        )
        provider_status = normalizePaymentStatus(
            getattr(session, 'status', 'pending')
        )
        updateRecord('payment_intent_attempts', document_id, {
            'paymentStatus': 'pending',
            'providerStatus': provider_status,
            'transactionReference': getattr(session, 'id', str(session)),
            'clientSecret': getattr(session, 'client_secret', None),
            'updatedAt': utc_now_iso(),
        })
        return jsonify({
            'ok': True,
            'paymentAttemptId': attempt_id,
            'paymentIntentId': getattr(session, 'id', str(session)),
            'clientSecret': getattr(session, 'client_secret', None),
            'status': provider_status,
        })
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        if 'document_id' in locals() and is_ambiguous_provider_error(exc):
            updateRecord('payment_intent_attempts', document_id, {
                'paymentStatus': 'pending',
                'reconciliationRequired': True,
                'updatedAt': utc_now_iso(),
            })
            return jsonify({
                'ok': True,
                'paymentAttemptId': attempt_id,
                'status': 'pending',
                'reconciliationRequired': True,
            }), 202
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
        document_id, record, created = _claim_payment(payload, booking_doc_id)
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 409
    except PermissionError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 403

    status = normalizePaymentStatus(record.get('paymentStatus'))
    if not created:
        if status == 'succeeded':
            return _payment_response(record, reused=True)
        if status == 'cancelled':
            return _payment_response(record, 409, reused=True)
        if status == 'failed':
            return _payment_response(
                record,
                409,
                reused=True,
                newAttemptRequired=True,
            )
        # A repeated pending request uses the exact same opaque Stripe key. The
        # provider therefore reconciles the logical attempt rather than creating
        # another PaymentIntent. Simulation mode is deterministic by the key.
    return _execute_payment(document_id, record, payload, booking_doc_id)


@bp.get('/payments/attempts/<attempt_id>')
@auth_required(['traveller'])
def reconcile_payment(attempt_id):
    try:
        attempt_id = normalize_attempt_id(attempt_id, 'paymentAttemptId')
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    record = retrieveRecord('payment_records', _payment_document_id(attempt_id))
    if not record or record.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'Payment attempt not found'}), 404
    reconciled = _reconcile_payment_record(record)
    status_code = 202 if normalizePaymentStatus(reconciled.get('paymentStatus')) == 'pending' else 200
    return _payment_response(reconciled, status_code, reused=True)


@bp.post('/payments/<payment_id>/retry')
@auth_required(['traveller'])
def retry_payment(payment_id):
    existing = retrieveRecord('payment_records', payment_id)
    if not existing or existing.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'Payment not found'}), 404
    status = normalizePaymentStatus(existing.get('paymentStatus'))
    if status == 'succeeded':
        return jsonify({'ok': False, 'error': 'Successful payments cannot be retried'}), 409
    if status == 'failed':
        return jsonify({
            'ok': False,
            'error': 'This payment attempt failed. Start a new payment attempt to try again.',
            'newAttemptRequired': True,
        }), 409
    if status == 'cancelled':
        return jsonify({'ok': False, 'error': 'Cancelled payments cannot be retried'}), 409
    reconciled = _reconcile_payment_record(existing)
    return _payment_response(
        reconciled,
        202 if normalizePaymentStatus(reconciled.get('paymentStatus')) == 'pending' else 200,
        reused=True,
    )


@bp.post('/payments/<payment_id>/cancel')
@auth_required(['traveller'])
def cancel_payment(payment_id):
    existing = retrieveRecord('payment_records', payment_id)
    if not existing or existing.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'Payment not found'}), 404
    if normalizePaymentStatus(existing.get('paymentStatus')) == 'succeeded':
        return jsonify({'ok': False, 'error': 'Successful payments cannot be cancelled'}), 409
    provider_status = existing.get('paymentStatus', 'unknown')
    try:
        if existing.get('transactionReference'):
            provider_status = returnPaymentStatus(existing['transactionReference'])
    except Exception:
        pass
    if normalizePaymentStatus(provider_status) == 'succeeded':
        updateRecord('payment_records', payment_id, {
            'paymentStatus': 'succeeded',
            'updatedAt': utc_now_iso(),
        })
        return jsonify({
            'ok': False,
            'error': 'Provider reports this payment succeeded; it cannot be locally cancelled.',
        }), 409
    result = updateRecord('payment_records', payment_id, {
        'paymentStatus': 'cancelled',
        'cancellationScope': 'travelmate_only',
        'providerCancellationPerformed': False,
        'previousProviderStatus': provider_status,
        'updatedAt': utc_now_iso(),
    })
    return jsonify({
        'ok': True,
        'payment': result,
        'message': 'Payment attempt cancelled in TravelMate. No provider refund was performed.',
    })


@bp.get('/payments')
@auth_required(['traveller'])
def list_payments():
    items = retrieveRecord('payment_records', filters=[('travellerId', '==', g.uid)]) or []
    normalized = [
        {
            **{
                key: value for key, value in item.items()
                if key != 'providerIdempotencyKey'
            },
            'paymentStatus': normalizePaymentStatus(item.get('paymentStatus')),
        }
        for item in items
        if isinstance(item, dict)
    ]
    return jsonify({'ok': True, 'items': normalized})
