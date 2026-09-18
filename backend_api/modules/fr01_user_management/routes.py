from flask import Blueprint, request, jsonify, g
from auth_utils import auth_required
from utils import utc_now_iso
from sequence_contract.validators import validateRequiredInformation, validateEmailFormat, validateUpdatedProfile
from sequence_contract.firebase_firestore import retrieveRecord, storeRecord, updateRecord

bp=Blueprint('fr01_users',__name__,url_prefix='/api/fr1')

@bp.post('/profile')
@auth_required()
def create_or_update_profile():
    payload=request.get_json(silent=True) or {}; requested_role=payload.get('role','traveller')
    if requested_role not in {'traveller','operator'}: return jsonify({'ok':False,'error':'Only traveller or operator self-registration is allowed'}),400
    email=g.firebase_user.get('email','')
    required=['name'] + (['companyName','registrationNo'] if requested_role=='operator' else [])
    if not validateRequiredInformation(payload,required) or not validateEmailFormat(email): return jsonify({'ok':False,'error':'Invalid required profile information'}),400
    existing=retrieveRecord('users',g.uid) or {}; role=existing.get('role',requested_role)
    data={'uid':g.uid,'email':email,'name':payload.get('name',existing.get('name','')),'phoneNo':payload.get('phoneNo',existing.get('phoneNo','')),'role':role,'status':existing.get('status','active'),'updatedAt':utc_now_iso(),'createdAt':existing.get('createdAt',utc_now_iso())}
    if role=='operator': data.update({'companyName':payload.get('companyName',existing.get('companyName','')),'businessContact':payload.get('businessContact',existing.get('businessContact','')),'registrationNo':payload.get('registrationNo',existing.get('registrationNo','')),'verificationStatus':existing.get('verificationStatus','pending')})
    result=storeRecord('users',data,g.uid,merge=True)
    return jsonify({'ok':True,'profile':result})

@bp.get('/me')
@auth_required()
def me(): return jsonify({'ok':True,'profile':retrieveRecord('users',g.uid)})

@bp.put('/me')
@auth_required()
def update_me():
    payload=request.get_json(silent=True) or {}
    if not validateUpdatedProfile(payload): return jsonify({'ok':False,'error':'Invalid profile information'}),400
    allowed={k:payload[k] for k in ['name','phoneNo','preferredLanguage','companyName','businessContact'] if k in payload}; allowed['updatedAt']=utc_now_iso()
    result=updateRecord('users',g.uid,allowed)
    return jsonify({'ok':bool(result),'profile':result})
