"""Order-bound workflow, actual Flask actions and staged SDK transactions, all offline."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import RLock
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

import pytest

from services import booking_requirements as service
from services.package_checkout_contract import build_initial_fulfillment_record
from services.review_service import ReviewConflict
from sequence_contract import firebase_firestore as persistence
from test_fr12_operator_supplier_fulfillment import _sample_order, _trip_for

OP='test_operator_uid'
ADMIN='test_admin_uid'
TRAVELLER='test_traveller_uid'
NOW='2026-11-09T10:00:00Z'


def order(legacy=False):
    value=_sample_order(travellerId=TRAVELLER)
    if legacy:
        value['fulfillmentStatus']='fulfilled'
        value['packageSnapshot'].update(accommodationIncluded=False,accommodation={},
            inclusions=['Private van transport and guided tour tickets'],
            exclusions=['Transport and guided tour tickets'])
        value['fulfillmentRecord']=build_initial_fulfillment_record(value['packageSnapshot'])
    return value


def propose(revision=0,components=None,legacy=True,**changes):
    return {'expectedRevision':revision,'requestId':uuid4().hex,
        'components':components if components is not None else {
            'transport':{'required':True,'promise':'Purchased private van transfers remain included.'},
            'guideActivities':{'required':True,'promise':'Purchased guide and reserved tickets remain included.'}},
        'legacyReview':legacy,'reason':'Conflicting purchase fields need evidence-backed interpretation.',
        'evidenceReference':'PRIVATE-contract-2026-101',
        'evidenceSummary':'Signed purchase-time brochure lists all included services and the accepted quotation.',**changes}


def review(revision=1,decision='approved',**changes):
    return {'expectedRevision':revision,'requestId':uuid4().hex,'decision':decision,
        'reason':'Verified original signed brochure and paid quotation preserve the purchased entitlements.',
        'evidenceReference':'PRIVATE-admin-proof-101','entitlementVerified':True,**changes}


def accepted(value=None):
    value=value or order(True)
    pending=service.transition(value,None,propose(),OP,'operator','propose',NOW)
    return service.transition(value,pending,review(),ADMIN,'admin','review',NOW)


@pytest.mark.parametrize('required',[(),('accommodation',),('transport',),('guideActivities',),tuple(service.COMPONENTS)])
def test_explicit_purchased_requirements_and_actual_progress(required):
    value=order()
    value['packageSnapshot']={key+'Included':key in required for key in service.COMPONENTS}
    value['fulfillmentRecord']=build_initial_fulfillment_record(value['packageSnapshot'])
    context=service.assessment(value)
    overview,readiness=service.status_overview(value,context,value['fulfillmentRecord'],service.trip_status(value,_trip_for(value)))
    assert overview['travellerTrip']['state']=='created'
    assert overview['operatorReadiness']['state']=='awaiting_arrangements'
    assert overview['supplierArrangements']['state']==('pending' if required else 'not_required')
    assert readiness['requiredCount']==len(required) and readiness['completedCount']==0
    assert readiness['canMarkReady']==(not required)
    assert overview['supplierArrangements']['independentlyConfirmed'] is False


@pytest.mark.parametrize('payment,status',[('pending','checkout_open'),('failed','checkout_failed'),('unpaid','checkout_expired'),('refunded','refunded')])
def test_unpaid_or_terminal_payment_never_ready(payment,status):
    value=order();value.update(paymentStatus=payment,status=status)
    overview,readiness=service.status_overview(value,service.assessment(value),{},service.trip_status(value,_trip_for(value)))
    assert overview['operatorReadiness']['state']=='not_applicable' and not readiness['canMarkReady']
    assert 'Awaiting traveller payment.' in readiness['blockers']


@pytest.mark.parametrize('mode,state',[('none','not_created'),('missing','not_created'),('foreign','unknown'),('unavailable','unknown')])
def test_trip_status_needs_real_owned_link(mode,state):
    value=order();trip=_trip_for(value)
    if mode=='none':value.pop('fulfilledTripId')
    if mode=='missing':trip=None
    if mode=='foreign':trip['travellerId']='another'
    actual=service.trip_status(value,trip,unavailable=mode=='unavailable')
    assert actual['state']==state
    assert not service.status_overview(value,service.assessment(value),{},actual)[1]['canMarkReady']


@pytest.mark.parametrize('liteapi',[False,True])
def test_accommodation_metadata_is_a_promise_never_reservation(liteapi):
    value=order();snapshot=value['packageSnapshot'];snapshot['accommodationIncluded']=True
    if liteapi:snapshot['accommodation']['accommodationHotel']={'id':'hotel1','provider':'liteapi','name':'Purchased Hotel'}
    context=service.assessment(value)
    assert context['requirements']['accommodation']['required']
    assert ('LiteAPI' in context['requirements']['accommodation']['brochureSource'])==liteapi
    assert not service.status_overview(value,context,value['fulfillmentRecord'],service.trip_status(value,_trip_for(value)))[1]['canMarkReady']


def test_clarification_keeps_purchase_and_supplier_evidence_exactly_unchanged():
    value=order(True);before=deepcopy(value);record=accepted(value)
    context=service.assessment(value,record)
    assert context['legacyReviewed'] and not context['canPropose']
    assert context['requirements']['transport']['required'] and context['requirements']['guideActivities']['required']
    assert not context['requirements']['accommodation']['required']
    assert value==before and record['originalEvidence']==service.original_evidence(before['packageSnapshot'])
    assert record['history'][0]['proposedBy']==OP and record['history'][1]['reviewedBy']==ADMIN
    public=service.public_clarification(value,record)
    assert set(public)=={'approvedAt','revision','components'} and 'PRIVATE' not in str(public)
    assert not service.status_overview(value,context,value['fulfillmentRecord'],service.trip_status(value,_trip_for(value)))[1]['canMarkReady']


@pytest.mark.parametrize('decision',['rejected','needs_evidence'])
def test_rejected_or_insufficient_evidence_stays_blocked(decision):
    value=order(True);pending=service.transition(value,None,propose(),OP,'operator','propose',NOW)
    record=service.transition(value,pending,review(decision=decision),ADMIN,'admin','review',NOW)
    context=service.assessment(value,record)
    assert context['canPropose'] and not context['legacyReviewed']
    assert context['requirements']['transport']['uncertain']
    assert service.public_clarification(value,record) is None


def test_partial_resolution_keeps_other_requirement_unresolved():
    value=order(True)
    pending=service.transition(value,None,propose(components={'transport':{'required':True,'promise':'Private transfers were purchased.'}}),OP,'operator','propose',NOW)
    record=service.transition(value,pending,review(),ADMIN,'admin','review',NOW)
    context=service.assessment(value,record)
    assert not context['requirements']['transport']['uncertain'] and context['requirements']['guideActivities']['uncertain']
    assert not service.status_overview(value,context,{},service.trip_status(value,_trip_for(value)))[1]['canMarkReady']


@pytest.mark.parametrize('change',[{'entitlementVerified':False},{'evidenceReference':''},{'reason':'short'}])
def test_approval_requires_explicit_entitlement_verification_and_evidence(change):
    value=order(True);pending=service.transition(value,None,propose(),OP,'operator','propose',NOW)
    with pytest.raises(ValueError):service.transition(value,pending,review(**change),ADMIN,'admin','review',NOW)


def test_duplicate_stale_and_known_entitlement_protection():
    value=order(True);payload=propose()
    pending=service.transition(value,None,payload,OP,'operator','propose',NOW)
    assert service.transition(value,pending,payload,OP,'operator','propose',NOW)==pending
    with pytest.raises(ReviewConflict):service.transition(value,pending,{**payload,'reason':'Changed duplicate payload must conflict.'},OP,'operator','propose',NOW)
    with pytest.raises(ReviewConflict):service.transition(value,pending,review(revision=0),ADMIN,'admin','review',NOW)
    with pytest.raises(ReviewConflict):service.transition(value,None,propose(components={'accommodation':{'required':True,'promise':'Trying to replace an established exclusion.'}}),OP,'operator','propose',NOW)
    value['amount']+=1
    assert service.assessment(value,pending)['integrityError']
    with pytest.raises(ReviewConflict):service.transition(value,pending,review(),ADMIN,'admin','review',NOW)


class Database:
    """Stages writes; commits only after a successful serialized SDK callback."""
    def __init__(self):self.rows={};self.lock=RLock();self.writes=[]
    def read(self,collection,identity=None,**kwargs):
        if identity is not None:return deepcopy(self.rows.get((collection,identity)))
        values=[deepcopy(v) for (c,_),v in self.rows.items() if c==collection]
        for field,op,value in kwargs.get('filters') or []:
            assert op=='=='
            values=[v for v in values if v.get(field)==value]
        return values[:kwargs.get('limit',len(values))]
    def collection(self,name):return SimpleNamespace(document=lambda identity:Reference(self,name,identity))
    def transaction(self):return Transaction(self)
    def transactional(self,callback):
        def run(transaction):
            with self.lock:
                result=callback(transaction)
                for kind,ref,value in transaction.pending:
                    if kind=='set':self.rows[ref.key]=deepcopy(value)
                    else:self.rows[ref.key].update(deepcopy(value))
                    self.writes.append((kind,ref.key))
                return result
        return run


class Reference:
    def __init__(self,db,collection,identity):self.db=db;self.key=(collection,identity);self.id=identity
    def get(self,transaction=None):
        value=deepcopy(self.db.rows.get(self.key))
        return SimpleNamespace(id=self.id,exists=value is not None,to_dict=lambda:value)


class Transaction:
    def __init__(self,db):self.pending=[]
    def set(self,ref,value):self.pending.append(('set',ref,deepcopy(value)))
    def update(self,ref,value):self.pending.append(('update',ref,deepcopy(value)))


@pytest.fixture
def database(monkeypatch):
    from modules.fr12_tourism_operator_management import routes
    from modules.fr05_smart_itinerary_budget_planner import routes as trips
    from modules.fr09_payment import routes as payments
    import auth_utils
    db=Database();value=order(True)
    db.rows[('checkout_orders',value['id'])]=value
    db.rows[('itineraries',value['fulfilledTripId'])]={**_trip_for(value),'tripType':'package','packageSnapshot':deepcopy(value['packageSnapshot'])}
    for uid,role in [(OP,'operator'),('other_operator','operator'),(ADMIN,'admin'),(TRAVELLER,'traveller'),('other_traveller','traveller')]:
        db.rows[('users',uid)]={'uid':uid,'role':role,'status':'active','verificationStatus':'approved'}
    monkeypatch.setattr(persistence,'get_db',lambda:db)
    monkeypatch.setattr(auth_utils,'get_db',lambda:db)
    monkeypatch.setattr(auth_utils.auth,'verify_id_token',lambda token,**kw:{'uid':token})
    monkeypatch.setattr('google.cloud.firestore.transactional',db.transactional)
    for module in (routes,trips,payments):monkeypatch.setattr(module,'retrieveRecord',db.read)
    return db


def headers(uid=OP):return {'Authorization':'Bearer '+uid}
URL='/api/fr12/bookings/ord-sample-1'


def test_actual_actions_admin_approval_arrangements_ready_and_no_read_or_replay_notification(client,database):
    db=database;original=deepcopy(db.rows[('checkout_orders','ord-sample-1')])
    from services.traveller_notifications import derive_events
    with patch.object(persistence,'_notify_committed') as notify:
        pending=client.post(URL+'/clarifications',json=propose(),headers=headers())
        assert pending.status_code==200,pending.json
        assert client.post(URL+'/confirm-fulfillment',headers=headers()).status_code==409
        assert client.post(URL+'/clarifications/review',json=review(),headers=headers(ADMIN)).status_code==200
        assert db.rows[('checkout_orders','ord-sample-1')]==original
        assert client.get(URL,headers=headers()).json['booking']['statusOverview']['operatorReadiness']['state']=='awaiting_arrangements'
        notify.assert_not_called()
        assert client.post(URL+'/confirm-fulfillment',headers=headers()).status_code==400
        for key in ('transport','guideActivities'):
            response=client.post(URL+'/fulfillment',headers=headers(),json={'serviceType':key,'reference':'internal-contract-'+key,'providerName':'Actual contracted supplier'})
            assert response.status_code==200,response.json
        state=response.json['booking']['statusOverview']['supplierArrangements']
        assert state['state']=='arrangements_recorded' and state['completedCount']==state['requiredCount']==2
        notify.reset_mock()
        result=client.post(URL+'/confirm-fulfillment',headers=headers())
        assert result.status_code==200,result.json
        assert result.json['booking']['statusOverview']['operatorReadiness']['state']=='ready'
        notify.assert_called_once()
        saved=deepcopy(db.rows[('checkout_orders','ord-sample-1')]);writes=len(db.writes)
        assert client.post(URL+'/confirm-fulfillment',headers=headers()).status_code==200
        assert client.get(URL,headers=headers()).status_code==200
        assert len(db.writes)==writes and notify.call_count==1
        events=derive_events(TRAVELLER,[saved],[db.read('itineraries',saved['fulfilledTripId'])])
        assert any(e['category']=='arrangements_ready' for e in events)
    for key in ('amount','currency','packageSnapshot','paymentStatus','status'):
        assert saved[key]==original[key]


@pytest.mark.parametrize('uid,path',[('other_operator','/clarifications'),(TRAVELLER,'/clarifications'),(OP,'/clarifications/review'),(TRAVELLER,'/clarifications/review')])
def test_actual_actions_cross_operator_and_role_isolation(client,database,uid,path):
    before=deepcopy(database.rows)
    result=client.post(URL+path,headers=headers(uid),json=review() if path.endswith('review') else propose())
    assert result.status_code==403 and database.rows==before


def test_atomic_admin_race_replay_and_purchase_staleness(database):
    payload=propose()
    persistence.commitRequirementClarification('ord-sample-1',OP,'operator','propose',payload)
    writes=len(database.writes)
    persistence.commitRequirementClarification('ord-sample-1',OP,'operator','propose',payload)
    assert len(database.writes)==writes
    def decide(_):
        try:return persistence.commitRequirementClarification('ord-sample-1',ADMIN,'admin','review',review())['status']
        except ReviewConflict:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(decide,range(2)))
    assert sorted(results)==['approved','conflict']
    current=database.read('checkout_orders','ord-sample-1')
    with patch.object(persistence,'_notify_committed'):
        with pytest.raises(ReviewConflict):persistence.commitPackageFulfillment('ord-sample-1',current,{'updatedAt':NOW},clarification_revision=1)
    database.rows[('checkout_orders','ord-sample-1')]['packageSnapshot']['title']='Changed purchase'
    with pytest.raises(ReviewConflict):persistence.commitRequirementClarification('ord-sample-1',OP,'operator','propose',propose(revision=2))


def test_authorized_traveller_only_sees_approved_public_summary(client,database):
    persistence.commitRequirementClarification('ord-sample-1',OP,'operator','propose',propose())
    assert 'approvedRequirementClarification' not in client.get('/api/fr9/orders/ord-sample-1',headers=headers(TRAVELLER)).json['order']
    persistence.commitRequirementClarification('ord-sample-1',ADMIN,'admin','review',review())
    for path,key in [('/api/fr9/orders/ord-sample-1','order'),('/api/fr5/itineraries/trip-pkg-101','itinerary')]:
        response=client.get(path,headers=headers(TRAVELLER))
        assert response.status_code==200,response.json
        assert response.json[key]['approvedRequirementClarification']['components']['transport']['required']
        assert 'PRIVATE' not in response.get_data(as_text=True)
        foreign=client.get(path,headers=headers('other_traveller'))
        assert foreign.status_code in {403,404} and 'approvedRequirementClarification' not in foreign.get_data(as_text=True)


def test_no_required_suppliers_path_and_manual_internal_reference(client,database):
    value=order();value['packageSnapshot']={key+'Included':False for key in service.COMPONENTS}
    database.rows[('checkout_orders',value['id'])]=value
    with patch.object(persistence,'_notify_committed'):
        response=client.post(URL+'/confirm-fulfillment',headers=headers())
    assert response.status_code==200,response.json
    assert response.json['booking']['supplierReservationStatus']=='not_required'
    value=order();value['packageSnapshot'].update(accommodationIncluded=True,transportIncluded=False,guideActivitiesIncluded=False,inclusions=[])
    database.rows[('checkout_orders',value['id'])]=value
    with patch.object(persistence,'_notify_committed'):
        result=client.post(URL+'/fulfillment',headers=headers(),json={'serviceType':'accommodation','reference':'internal-contract-101','supplierName':'Manual Homestay'})
    assert result.status_code==200,result.json
    assert result.json['booking']['statusOverview']['supplierArrangements']['state']=='arrangements_recorded'


@pytest.mark.parametrize('complete_count,state',[(0,'pending'),(1,'partially_recorded'),(3,'arrangements_recorded')])
def test_three_required_services_count_only_attested_arrangements(complete_count,state):
    value=order();context=service.assessment(value);record=value['fulfillmentRecord']
    for key in list(service.COMPONENTS)[:complete_count]:
        record['services'][key].update(status='confirmed',reference='internal-contract',providerName='Actual fleet',
            provenance='operator_attested',confirmedBy=OP,confirmedAt=NOW)
    overview,readiness=service.status_overview(value,context,record,service.trip_status(value,_trip_for(value)))
    assert overview['supplierArrangements']['state']==state
    assert readiness['requiredCount']==3 and readiness['completedCount']==complete_count
    assert readiness['canMarkReady']==(complete_count==3)


def test_review_queue_role_boundaries_and_direct_detail_isolation(client,database):
    assert client.get(URL,headers=headers('other_operator')).status_code==404
    assert client.get('/api/fr12/booking-clarifications',headers=headers()).status_code==403
    assert client.get('/api/fr12/booking-clarifications',headers=headers(ADMIN)).json['items']==[]
    assert client.post(URL+'/clarifications',json=propose(),headers=headers()).status_code==200
    response=client.get('/api/fr12/booking-clarifications',headers=headers(ADMIN))
    assert response.status_code==200 and response.json['items'][0]['orderId']=='ord-sample-1'
    assert 'PRIVATE' not in response.get_data(as_text=True)


def test_failed_transaction_rolls_back_and_decision_replay_does_not_write(database,monkeypatch):
    before=deepcopy(database.rows)
    original_set=Transaction.set
    def fail_after_staging(self,ref,value):
        original_set(self,ref,value)
        raise RuntimeError('simulated aborted transaction')
    with monkeypatch.context() as scope:
        scope.setattr(Transaction,'set',fail_after_staging)
        with pytest.raises(RuntimeError):persistence.commitRequirementClarification('ord-sample-1',OP,'operator','propose',propose())
    assert database.rows==before and not database.writes
    persistence.commitRequirementClarification('ord-sample-1',OP,'operator','propose',propose())
    payload=review();persistence.commitRequirementClarification('ord-sample-1',ADMIN,'admin','review',payload)
    writes=len(database.writes)
    persistence.commitRequirementClarification('ord-sample-1',ADMIN,'admin','review',payload)
    assert len(database.writes)==writes


def test_missing_or_inconsistent_clarification_storage_fails_closed():
    value=order()
    def unavailable(*args):raise RuntimeError('offline')
    context,trip=service.load_context(value,unavailable)
    assert context['integrityError'] and not context['canPropose'] and trip['state']=='unknown'
    overview,readiness=service.status_overview(value,context,value['fulfillmentRecord'],trip)
    assert overview['supplierArrangements']['state']=='needs_review' and not readiness['canMarkReady']


def test_requirement_evidence_preserves_absent_and_explicit_empty_fields():
    evidence=service.original_evidence({'transport':{},'transportIncluded':False,'inclusions':[]})['transport']
    assert evidence['transport']=={'present':True,'value':{}}
    assert evidence['transportIncluded']=={'present':True,'value':False}
    assert evidence['exclusions']=={'present':False,'value':None}


def test_optional_clarification_outage_does_not_hide_owned_original_trip(client,database,monkeypatch):
    from modules.fr05_smart_itinerary_budget_planner import routes
    def read(collection,identity):
        if collection=='checkout_orders':raise RuntimeError('optional review storage offline')
        return database.read(collection,identity)
    monkeypatch.setattr(routes,'retrieveRecord',read)
    response=client.get('/api/fr5/itineraries/trip-pkg-101',headers=headers(TRAVELLER))
    assert response.status_code==200 and response.json['itinerary']['packageSnapshot']==order(True)['packageSnapshot']
    assert 'approvedRequirementClarification' not in response.json['itinerary']
