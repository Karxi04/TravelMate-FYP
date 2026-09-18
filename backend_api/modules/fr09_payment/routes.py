from flask import Blueprint, request, jsonify, g
from auth_utils import auth_required
from utils import utc_now_iso
from services.stripe_service import createPaymentSession, processSandboxPayment, returnPaymentStatus
from sequence_contract.validators import validatePaymentInput
from sequence_contract.firebase_firestore import retrieveRecord, storeRecord, updateRecord
bp=Blueprint('fr09_payments',__name__,url_prefix='/api/fr9')
def _record(intent, booking_id, amount):
    data={'travellerId':g.uid,'bookingId':booking_id,'amount':amount,'currency':'myr','paymentStatus':intent.status,'transactionReference':intent.id,'createdAt':utc_now_iso()}; storeRecord('payment_records',data,intent.id,merge=True); return data
@bp.post('/payments/create-intent')
@auth_required(['traveller'])
def create_payment_intent():
    payload=request.get_json(silent=True) or {}
    if not validatePaymentInput(payload): return jsonify({'ok':False,'error':'Positive amount is required'}),400
    try: session=createPaymentSession(payload,g.uid,str(payload.get('bookingId',''))); data=_record(session,payload.get('bookingId'),float(payload['amount'])); return jsonify({'ok':True,'paymentIntentId':session.id,'clientSecret':session.client_secret,'status':session.status,'payment':data})
    except Exception as exc:return jsonify({'ok':False,'error':str(exc)}),502
@bp.post('/payments/process')
@auth_required(['traveller'])
def process_payment():
    payload=request.get_json(silent=True) or {}
    if not validatePaymentInput(payload): return jsonify({'ok':False,'error':'Positive amount is required'}),400
    try:
        session=createPaymentSession(payload,g.uid,str(payload.get('bookingId',''))); intent=processSandboxPayment(paymentInput=payload,travellerId=g.uid,bookingId=str(payload.get('bookingId',''))); data=_record(intent,payload.get('bookingId'),float(payload['amount']))
        if payload.get('bookingId'): updateRecord('hotel_bookings',payload['bookingId'],{'bookingStatus':'paid','updatedAt':utc_now_iso()})
        return jsonify({'ok':True,'paymentSessionId':session.id,'payment':data})
    except Exception as exc:return jsonify({'ok':False,'error':str(exc)}),502
@bp.post('/payments/<payment_id>/retry')
@auth_required(['traveller'])
def retry_payment(payment_id):
    existing=retrieveRecord('payment_records',payment_id)
    if not existing or existing.get('travellerId')!=g.uid: return jsonify({'ok':False,'error':'Payment not found'}),404
    try: intent=processSandboxPayment(paymentInput=existing,travellerId=g.uid,bookingId=existing.get('bookingId','')); updateRecord('payment_records',payment_id,{'paymentStatus':intent.status,'transactionReference':intent.id,'updatedAt':utc_now_iso()}); return jsonify({'ok':True,'status':intent.status})
    except Exception as exc:return jsonify({'ok':False,'error':str(exc)}),502
@bp.post('/payments/<payment_id>/cancel')
@auth_required(['traveller'])
def cancel_payment(payment_id):
    existing=retrieveRecord('payment_records',payment_id)
    if not existing or existing.get('travellerId')!=g.uid:return jsonify({'ok':False,'error':'Payment not found'}),404
    status=existing.get('paymentStatus','unknown')
    try: status=returnPaymentStatus(existing.get('transactionReference') or payment_id)
    except Exception: pass
    result=updateRecord('payment_records',payment_id,{'paymentStatus':'cancelled','previousProviderStatus':status,'updatedAt':utc_now_iso()}); return jsonify({'ok':True,'payment':result})
@bp.get('/payments')
@auth_required(['traveller'])
def list_payments(): return jsonify({'ok':True,'items':retrieveRecord('payment_records',filters=[('travellerId','==',g.uid)])})
