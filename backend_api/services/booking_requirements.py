"""Order-bound entitlement assessment; original purchases and supplier evidence stay immutable."""
from copy import deepcopy
import hashlib
import json
import re

from services.package_checkout_contract import derive_required_services, fulfillment_readiness, is_paid_order
from services.review_service import ReviewConflict

COLLECTION = 'package_requirement_clarifications'
COMPONENTS = {'accommodation':'Accommodation','transport':'Transportation','guideActivities':'Guide / Activities'}
SOURCE_PATHS = {
    'accommodation':['accommodationIncluded','accommodation','accommodationName','roomType','accommodationCategory','accommodationNotes','accommodationHotel','accommodationRoom','inclusions','exclusions'],
    'transport':['transportIncluded','transport','transportTypes','transportNotes','inclusions','exclusions'],
    'guideActivities':['guideActivitiesIncluded','inclusions','exclusions','itineraryDays'],
}


def fingerprint(order):
    fields = ['id','operatorId','travellerId','packageId','packageSnapshot','amount','currency','departureDate','participants']
    encoded = json.dumps({key:order.get(key) for key in fields},sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str,allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def original_evidence(snapshot):
    snapshot = snapshot if isinstance(snapshot,dict) else {}
    return {key:{path:{'present':path in snapshot,'value':deepcopy(snapshot.get(path))}
                 for path in paths} for key,paths in SOURCE_PATHS.items()}


def assessment(order, clarification=None):
    requirements = derive_required_services(order.get('packageSnapshot'))
    snapshot=order.get('packageSnapshot') or {}
    if not isinstance(snapshot,dict):snapshot={}
    accom=snapshot.get('accommodation') or {}
    if not isinstance(accom,dict):accom={}
    hotel=accom.get('accommodationHotel') or snapshot.get('accommodationHotel') or {}
    room=accom.get('accommodationRoom') or snapshot.get('accommodationRoom') or {}
    requirements['accommodation'].update(brochureSource='LiteAPI property / room metadata' if isinstance(hotel,dict) and hotel.get('provider')=='liteapi' else 'Manual accommodation promise',
        brochureProperty=deepcopy(hotel) if isinstance(hotel,dict) else {},brochureRoom=deepcopy(room) if isinstance(room,dict) else {})
    valid = bool(clarification and clarification.get('orderId')==order.get('id') and
                 clarification.get('operatorId')==order.get('operatorId') and
                 clarification.get('purchaseFingerprint')==fingerprint(order))
    accepted = (clarification.get('accepted') or {}) if valid else {}
    if accepted.get('entitlementVerified') is True and accepted.get('approvedBy') and accepted.get('approvedAt'):
        for key,resolution in (accepted.get('resolutions') or {}).items():
            if key in requirements and requirements[key].get('uncertain') and isinstance(resolution.get('required'),bool):
                requirements[key].update(required=resolution['required'],uncertain=False,reviewReason='',
                    clarifiedPromise=resolution['promise'],clarificationRevision=accepted['revision'])
    legacy_reviewed = bool(accepted.get('entitlementVerified') is True and accepted.get('legacyReviewed') and accepted.get('approvedBy') and accepted.get('approvedAt'))
    return {'requirements':requirements,'legacyReviewed':legacy_reviewed,
            'integrityError':bool(clarification and not valid),
            'canPropose':is_paid_order(order) and not (clarification and not valid) and
                (any(meta.get('uncertain') for meta in requirements.values()) or
                 (order.get('fulfillmentStatus')=='fulfilled' and not legacy_reviewed)),
            'revision':clarification.get('revision',0) if valid else 0,
            'originalEvidence':original_evidence(order.get('packageSnapshot')),
            'record':deepcopy(clarification) if valid else None}


def public_clarification(order, clarification):
    context = assessment(order,clarification)
    if not context['record']:return None
    accepted = context['record'].get('accepted') or {}
    if not accepted.get('entitlementVerified') or not accepted.get('approvedBy') or not accepted.get('approvedAt'):return None
    return {'approvedAt':accepted['approvedAt'],'revision':accepted['revision'],
            'components':{key:{'required':value['required'],'promise':value['promise']}
                          for key,value in accepted.get('resolutions',{}).items()}}


def read_public_clarification(order, read):
    try:return public_clarification(order,read(COLLECTION,order['id']))
    except Exception:return None


def trip_status(order, trip=None, unavailable=False):
    tid = order.get('fulfilledTripId')
    if unavailable:return {'state':'unknown','label':'Unavailable'}
    if not tid:
        return {'state':'unknown','label':'Unknown'} if order.get('fulfillmentStatus')=='fulfilled' else {'state':'not_created','label':'Not Created'}
    if not trip:return {'state':'not_created','label':'Not Created'}
    if (trip.get('id')!=tid or trip.get('travellerId')!=order.get('travellerId') or
        trip.get('operatorId')!=order.get('operatorId') or trip.get('checkoutOrderId')!=order.get('id')):
        return {'state':'unknown','label':'Unavailable'}
    return {'state':'created','label':'Created'}


def load_context(order, read):
    try:
        clarification=read(COLLECTION,order['id'])
        context=assessment(order,clarification)
    except Exception:
        context=assessment(order)
        context.update(integrityError=True,canPropose=False)
    try:
        trip=read('itineraries',order['fulfilledTripId']) if order.get('fulfilledTripId') else None
        state=trip_status(order,trip)
    except Exception:
        state=trip_status(order,unavailable=True)
    return context,state


def status_overview(order, context, record, trip):
    paid = is_paid_order(order)
    readiness = fulfillment_readiness(order,context['requirements'],record or {},paid,context['legacyReviewed'],trip['state'])
    if context['integrityError']:
        readiness.update(canMarkReady=False,requirementsReliable=False)
        readiness['blockers'].append('Saved clarification does not match this purchase. Administrator review is required.')
    state = order.get('fulfillmentStatus')
    review = (not readiness['requirementsReliable'] or (state=='fulfilled' and not context['legacyReviewed']))
    operator = ('not_applicable','Not Applicable') if not paid else (
        ('unable_to_fulfil','Unable to Fulfil') if state=='fulfillment_declined' else
        ('ready','Ready') if state=='trip_ready' else ('needs_review','Needs Review') if review else
        ('awaiting_arrangements','Awaiting Arrangements'))
    required, complete = readiness['requiredCount'],readiness['completedCount']
    supplier = ('needs_review','Needs Review') if review else (
        ('not_required','Not Required') if required==0 else
        ('arrangements_recorded','Arrangements Recorded') if complete==required else
        ('partially_recorded','Partially Recorded') if complete else ('pending','Awaiting Arrangements'))
    return {'travellerTrip':trip,'operatorReadiness':{'state':operator[0],'label':operator[1]},
            'supplierArrangements':{'state':supplier[0],'label':supplier[1],
                'requiredCount':required,'completedCount':complete,'independentlyConfirmed':False}},readiness


def _text(value, label, minimum=10, maximum=2000):
    if not isinstance(value,str) or not minimum<=len(value.strip())<=maximum or any(ord(c)<32 and c not in '\n\r\t' for c in value):
        raise ValueError(f'{label} must contain {minimum}–{maximum} characters.')
    return value.strip()


def transition(order, current, payload, actor, role, action, now):
    if action not in {'propose','review'}:raise ValueError('Unsupported clarification action.')
    if not isinstance(payload,dict):raise ValueError('Use a JSON object.')
    allowed = {'expectedRevision','requestId','components','reason','evidenceReference','evidenceSummary','legacyReview'} if action=='propose' else {
        'expectedRevision','requestId','decision','reason','evidenceReference','entitlementVerified'}
    if set(payload)-allowed:raise ValueError('Unsupported clarification fields.')
    nonce=payload.get('requestId');revision=payload.get('expectedRevision')
    if not isinstance(nonce,str) or not re.fullmatch('[a-f0-9]{32}',nonce) or isinstance(revision,bool) or not isinstance(revision,int) or revision<0:
        raise ValueError('A valid request identity and expected revision are required.')
    if order.get('quoteType')!='package' or not isinstance(order.get('packageSnapshot'),dict):
        raise ValueError('Purchased package information is unavailable.')
    snapshot=order['packageSnapshot']
    if any(snapshot.get(key) and snapshot[key]!=order.get(key) for key in ('operatorId','packageId')):
        raise ReviewConflict('Purchased ownership is inconsistent.')
    if action=='propose' and (role!='operator' or order.get('operatorId')!=actor):raise PermissionError('Booking is not owned by this operator.')
    if action=='review' and role!='admin':raise PermissionError('Administrator review is required.')
    context=assessment(order,current)
    if context['integrityError']:raise ReviewConflict('This purchase changed or its clarification is inconsistent. Refresh and request administrative review.')
    data=deepcopy(current or {'orderId':order['id'],'operatorId':order['operatorId'],
        'purchaseFingerprint':fingerprint(order),'originalEvidence':original_evidence(snapshot),'revision':0,'history':[],'operations':{}})
    payload_hash=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    seen=(data.get('operations') or {}).get(nonce)
    if seen:
        if seen.get('actor')==actor and seen.get('payloadHash')==payload_hash:return data
        raise ReviewConflict('This request identity was already used.')
    if revision!=data['revision']:raise ReviewConflict('Clarification changed. Refresh before submitting.')
    reason=_text(payload.get('reason'),'Reason',20)
    if action=='propose':
        if not is_paid_order(order):raise ValueError('Only paid purchased packages may be clarified.')
        if data.get('status')=='pending':raise ReviewConflict('A proposal is already awaiting Administrator review.')
        if not context['canPropose']:raise ReviewConflict('No unresolved purchased requirement needs clarification.')
        components=payload.get('components')
        if not isinstance(components,dict) or set(components)-set(COMPONENTS):raise ValueError('Select valid supplier components.')
        resolutions={}
        for key,value in components.items():
            if not context['requirements'][key].get('uncertain'):raise ReviewConflict('Established purchased requirements cannot be changed through clarification.')
            if not isinstance(value,dict) or set(value)!={'required','promise'} or not isinstance(value['required'],bool):raise ValueError('Each resolution needs an inclusion choice and original service promise.')
            resolutions[key]={'required':value['required'],'promise':_text(value['promise'],'Original entitlement summary',10,500)}
        legacy=payload.get('legacyReview',False)
        if not isinstance(legacy,bool) or (legacy and order.get('fulfillmentStatus')!='fulfilled'):raise ValueError('Invalid legacy workflow review.')
        if not resolutions and not (legacy and not context['legacyReviewed']):raise ValueError('Select an unresolved component or request the legacy workflow review.')
        proposal={'requestId':nonce,'components':resolutions,'legacyReview':legacy,'reason':reason,
            'evidenceReference':_text(payload.get('evidenceReference'),'Purchase evidence reference',5,500),
            'evidenceSummary':_text(payload.get('evidenceSummary'),'Purchase evidence summary',20),
            'proposedBy':actor,'proposedAt':now}
        data.update(status='pending',proposal=proposal)
        event={'action':'proposed',**proposal}
    else:
        if data.get('status')!='pending':raise ReviewConflict('No pending proposal is available for decision.')
        decision=payload.get('decision')
        if decision not in {'approved','rejected','needs_evidence'}:raise ValueError('Select a supported review decision.')
        evidence=payload.get('evidenceReference','')
        if not isinstance(evidence,str) or len(evidence)>500:raise ValueError('Use a valid evidence reference (maximum 500 characters).')
        evidence=evidence.strip()
        if decision=='approved':
            if not is_paid_order(order):raise ValueError('An unpaid or terminal payment order cannot receive an accepted entitlement clarification.')
            if payload.get('entitlementVerified') is not True:raise ValueError('Confirm the contemporaneous evidence preserves the actual purchased entitlement.')
            evidence=_text(evidence,'Administrator purchase evidence reference',5,500)
            accepted=deepcopy(data.get('accepted') or {})
            accepted.update(resolutions={**accepted.get('resolutions',{}),**data['proposal']['components']},
                legacyReviewed=bool(accepted.get('legacyReviewed') or data['proposal']['legacyReview']),
                revision=data['revision']+1,approvedBy=actor,approvedAt=now,entitlementVerified=True)
            data['accepted']=accepted
        data.update(status=decision,decision={'decision':decision,'reason':reason,'evidenceReference':evidence,
                    'reviewedBy':actor,'reviewedAt':now,'entitlementVerified':decision=='approved'})
        event={'action':decision,**data['decision'],'proposalRequestId':data['proposal']['requestId']}
    data['revision']+=1;data['updatedAt']=now
    data['history'].append({'revision':data['revision'],**event})
    data['operations'][nonce]={'actor':actor,'payloadHash':payload_hash,'revision':data['revision']}
    return data
