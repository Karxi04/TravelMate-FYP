from flask import Blueprint, request, jsonify, g
from auth_utils import auth_required
from utils import utc_now_iso
from sequence_contract.validators import validateRatingAndComment, validateFeedback
from sequence_contract.firebase_firestore import retrieveRecord, storeRecord, updateRecord, deleteRecord
bp=Blueprint('fr10_feedback',__name__,url_prefix='/api/fr10')
@bp.get('/feedback')
@auth_required(['traveller'])
def own_feedback(): return jsonify({'ok':True,'items':retrieveRecord('feedback',filters=[('travellerId','==',g.uid)])})
@bp.post('/feedback')
@auth_required(['traveller'])
def submit_feedback():
    payload=request.get_json(silent=True) or {}
    if not validateRatingAndComment(payload): return jsonify({'ok':False,'error':'destinationId and rating 1-5 are required'}),400
    profile=retrieveRecord('users',g.uid) or {}
    data={**payload,'travellerId':g.uid,'travellerName':profile.get('name') or profile.get('fullName') or 'Traveller','feedbackStatus':'visible','moderationStatus':'pending_review','submittedAt':utc_now_iso(),'updatedAt':utc_now_iso()}; result=storeRecord('feedback',data); return jsonify({'ok':True,'id':result['id'],'feedback':result}),201
@bp.put('/feedback/<fid>')
@auth_required(['traveller'])
def update_feedback(fid):
    current=retrieveRecord('feedback',fid)
    if not current or current.get('travellerId')!=g.uid:return jsonify({'ok':False,'error':'Feedback not found'}),404
    if current.get('feedbackStatus')=='removed':return jsonify({'ok':False,'error':'This feedback was removed by the Administrator and cannot be republished by editing it'}),409
    payload=request.get_json(silent=True) or {}
    if not validateFeedback(payload):return jsonify({'ok':False,'error':'Invalid feedback'}),400
    payload['feedbackStatus']='visible'; payload['moderationStatus']='pending_review'; payload['updatedAt']=utc_now_iso(); return jsonify({'ok':True,'feedback':updateRecord('feedback',fid,payload)})
@bp.delete('/feedback/<fid>')
@auth_required(['traveller'])
def delete_feedback(fid):
    current=retrieveRecord('feedback',fid)
    if not current or current.get('travellerId')!=g.uid:return jsonify({'ok':False,'error':'Feedback not found'}),404
    deleteRecord('feedback',fid); return jsonify({'ok':True})
