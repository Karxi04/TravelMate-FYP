from flask import Blueprint, request, jsonify, g
from auth_utils import auth_required
from sequence_contract.validators import validatePreferenceAnswers, validateUpdatedPreferences
from sequence_contract.firebase_firestore import retrieveRecord, storeRecord, updateRecord
from sequence_contract.domain_functions import createPreferenceProfile, updatePreferenceProfile, applyHomepageCategoryMatching
bp=Blueprint('fr02_preferences',__name__,url_prefix='/api/fr2')
@bp.get('/preferences')
@auth_required(['traveller'])
def get_preferences(): return jsonify({'ok':True,'preferences':retrieveRecord('travel_preferences',g.uid)})
@bp.put('/preferences')
@auth_required(['traveller'])
def save_preferences():
    payload=request.get_json(silent=True) or {}; existing=retrieveRecord('travel_preferences',g.uid)
    valid=validateUpdatedPreferences(payload) if existing else validatePreferenceAnswers(payload)
    if not valid: return jsonify({'ok':False,'error':'Missing or invalid preference fields'}),400
    profile=updatePreferenceProfile(existing,payload) if existing else createPreferenceProfile(payload); profile['travellerId']=g.uid; profile['homepageCategories']=applyHomepageCategoryMatching(profile)
    result=updateRecord('travel_preferences',g.uid,profile) if existing else storeRecord('travel_preferences',profile,g.uid)
    return jsonify({'ok':True,'preferences':result})
