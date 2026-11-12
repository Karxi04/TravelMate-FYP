"""Isolated lifecycle/readiness HTTP contracts; no external persistence or providers."""
from copy import deepcopy
from threading import Lock
from types import SimpleNamespace

import pytest

from services.package_checkout_contract import build_initial_fulfillment_record, derive_required_services, fulfillment_readiness
from services.public_content_projection import PUBLIC_PACKAGE_COLLECTION
from services.review_service import ReviewConflict


def package(**changes):
    return {'id':'p1', 'operatorId':'op1', 'approvalStatus':'archived', 'schemaVersion':2,
            'title':'Heritage package', 'destination':'Penang', 'fullDescription':'Purchased heritage itinerary.',
            'durationDays':1, 'adultPrice':100, 'currency':'MYR', 'priceBasis':'per_person', 'taxIncluded':True,
            'itineraryDays':[{'title':'Heritage day', 'description':'Explore the heritage district.'}],
            'departureDates':['2027-01-10'], 'updatedAt':'v1', **changes}


@pytest.fixture
def memory(monkeypatch):
    from modules.fr12_tourism_operator_management import routes
    from services import public_content_projection as public
    records = {'tourism_packages': {'p1':package()}, 'users':{
        'op1':{'role':'operator','status':'active','verificationStatus':'approved'},
        'op2':{'role':'operator','status':'active','verificationStatus':'approved'},
        'traveller':{'role':'traveller','status':'active'}, 'admin':{'role':'admin','status':'active'}}}
    lock = Lock()
    def nested(item, field):
        for part in field.split('.'):
            item = item.get(part) if isinstance(item, dict) else None
        return item
    def retrieve(collection, documentId=None, filters=None, limit=None):
        with lock:
            values = deepcopy(records.get(collection, {}))
        if documentId:return values.get(str(documentId))
        items = list(values.values())
        for field, operator, expected in filters or []:
            if operator == 'array_contains':
                items = [item for item in items if expected in (nested(item, field) or [])]
            else:
                assert operator == '=='
                items = [item for item in items if nested(item, field) == expected]
        return items[:limit] if limit else items
    def store(collection, data, documentId=None, merge=False):
        key = documentId or data.get('id') or 'new'
        with lock:records.setdefault(collection, {})[key] = {'id':key, **deepcopy(data)}
        return retrieve(collection, key)
    def delete(collection, documentId, **kwargs):
        with lock:return records.setdefault(collection, {}).pop(documentId, None) is not None
    def update(collection, documentId, data, expected=None):
        with lock:
            current = records.get(collection, {}).get(documentId)
            if not current:return None
            if expected is not None and current != expected:raise ReviewConflict('Changed')
            records[collection][documentId] = {**current, **deepcopy(data)}
            saved = deepcopy(records[collection][documentId])
        public.source_changed(collection, documentId, saved)
        return saved
    monkeypatch.setattr('auth_utils.auth.verify_id_token', lambda token, **kw:{'uid':token})
    monkeypatch.setattr('auth_utils.get_db', lambda:SimpleNamespace(collection=lambda _:SimpleNamespace(document=lambda uid:SimpleNamespace(
        get=lambda:SimpleNamespace(exists=uid in records['users'],to_dict=lambda:deepcopy(records['users'].get(uid)))))))
    for module in ('fr12_tourism_operator_management','fr13_administrator_management','fr15_package_checkout'):
        monkeypatch.setattr(f'modules.{module}.routes.retrieveRecord', retrieve)
    monkeypatch.setattr(routes, 'updateRecord', update)
    monkeypatch.setattr('modules.fr13_administrator_management.routes.updateRecord', update)
    monkeypatch.setattr(public, 'retrieveRecord', retrieve)
    monkeypatch.setattr(public, 'storeRecord', store)
    monkeypatch.setattr(public, 'deleteRecord', delete)
    monkeypatch.setattr(public, '_writes_enabled', lambda:True)
    return records, retrieve, update


AUTH = {'Authorization':'Bearer op1'}


def test_archived_edit_restore_and_admin_review_keep_purchased_history(client, memory):
    records, _, _ = memory
    old_snapshot = {'packageId':'p1','selectedDepartureDate':'2026-11-28','title':'Original package','price':90}
    records['checkout_orders'] = {'o1':{'id':'o1','packageId':'p1','amount':90,'packageSnapshot':deepcopy(old_snapshot)}}
    records['itineraries'] = {'trip1':{'id':'trip1','packageId':'p1','packageSnapshot':deepcopy(old_snapshot)}}
    before = deepcopy((records['checkout_orders'], records['itineraries']))
    edited = client.put('/api/fr12/packages/p1',headers=AUTH,json={'title':'Updated heritage','adultPrice':120,'departureDates':['2027-02-10'],'approvalStatus':'approved'})
    assert edited.status_code == 200
    saved = edited.get_json()['package']
    assert saved['approvalStatus'] == 'archived' and saved['archiveRequiresReview']
    assert saved['fullDescription'] == package()['fullDescription']
    assert 'p1' not in records.get(PUBLIC_PACKAGE_COLLECTION,{})
    restored = client.post('/api/fr12/packages/p1/restore',headers=AUTH,json={'approvalStatus':'approved','expectedUpdatedAt':saved['updatedAt']})
    assert restored.status_code == 200 and restored.get_json()['package']['approvalStatus'] == 'draft'
    assert 'p1' not in records.get(PUBLIC_PACKAGE_COLLECTION,{})
    denied_checkout = client.post('/api/fr15/package-checkout-attempts',headers={'Authorization':'Bearer traveller'},json={'packageId':'p1','idempotencyKey':'unreviewed'})
    assert denied_checkout.status_code == 409
    assert client.post('/api/fr12/packages/p1/submit',headers=AUTH).status_code == 200
    assert client.post('/api/fr12/packages/p1/restore',headers=AUTH).status_code == 409
    assert 'p1' not in records.get(PUBLIC_PACKAGE_COLLECTION,{})
    approved = client.post('/api/fr13/packages/p1/review',headers={'Authorization':'Bearer admin'},json={'decision':'approved'})
    assert approved.status_code == 200
    assert records[PUBLIC_PACKAGE_COLLECTION]['p1']['title'] == 'Updated heritage'
    assert (records['checkout_orders'], records['itineraries']) == before


def test_unchanged_archive_restore_also_requires_review_and_duplicates_are_idempotent(client,memory):
    records, _, _ = memory
    records['tourism_packages']['p1'] = package(approvalStatus='approved', reviewedAt='prior-review', reviewedBy='admin')
    assert client.post('/api/fr12/packages/p1/archive',headers=AUTH).status_code == 200
    first = deepcopy(records['tourism_packages']['p1'])
    assert client.post('/api/fr12/packages/p1/archive',headers=AUTH).get_json()['idempotent']
    assert records['tourism_packages']['p1'] == first
    assert client.post('/api/fr12/packages/p1/restore',headers=AUTH).get_json()['package']['approvalStatus'] == 'draft'
    restored = deepcopy(records['tourism_packages']['p1'])
    assert client.post('/api/fr12/packages/p1/restore',headers=AUTH).get_json()['idempotent']
    assert records['tourism_packages']['p1'] == restored
    assert restored['reviewedAt'] == 'prior-review' and restored['reviewedBy'] == 'admin'
    assert [event['action'] for event in restored['lifecycleHistory']] == ['archived','restored']


@pytest.mark.parametrize(('method','suffix'), [('put',''),('post','/restore'),('delete','')])
def test_foreign_operator_cannot_manage_package(client,memory,method,suffix):
    records,_,_ = memory
    before = deepcopy(records['tourism_packages'])
    result = getattr(client,method)('/api/fr12/packages/p1'+suffix, headers={'Authorization':'Bearer op2'},json={'title':'Forged'})
    assert result.status_code == 404 and records['tourism_packages'] == before


@pytest.mark.parametrize('suffix', ['/restore','/archive'])
def test_traveller_cannot_change_lifecycle(client,memory,suffix):
    assert client.post('/api/fr12/packages/p1'+suffix,headers={'Authorization':'Bearer traveller'}).status_code == 403


@pytest.mark.parametrize('payload', [{'adultPrice':-1},{'departureDates':['not-a-date']},{'title':''}])
def test_archived_editor_keeps_validation(client,memory,payload):
    records,_,_ = memory
    before = deepcopy(records['tourism_packages'])
    assert client.put('/api/fr12/packages/p1',headers=AUTH,json=payload).status_code == 400
    assert records['tourism_packages'] == before


@pytest.mark.parametrize(('collection','record'), [
    ('checkout_orders',{'packageId':'p1'}),('checkout_orders',{'packageSnapshot':{'packageId':'p1'}}),
    ('package_checkout_attempts',{'packageId':'p1'}),('package_checkout_attempts',{'packageSnapshot':{'packageId':'p1'}}),
    ('payment_records',{'packageId':'p1'}),('payment_records',{'bookingId':'p1','bookingType':'package'}),
    ('itineraries',{'packageId':'p1'}),('itineraries',{'packageSnapshot':{'packageId':'p1'}}),
    ('promotional_campaigns',{'packageId':'p1'}),('hotel_bookings',{'packageId':'p1'}),
    ('promotional_campaigns',{'packageIds':['other','p1']}),
])
def test_delete_blocks_every_supported_dependency(client,memory,collection,record):
    records,_,_ = memory
    records[collection] = {'dependent':{'id':'dependent',**record}}
    before = deepcopy(records)
    response = client.delete('/api/fr12/packages/p1',headers=AUTH)
    assert response.status_code == 409 and 'Keep it archived' in response.get_json()['error']
    assert records == before


def test_unreferenced_delete_retains_identity_audit_and_cannot_be_restored(client,memory):
    records,_,_ = memory
    records['tourism_packages']['p1'].update(reviewedBy='admin',reviewedAt='recorded-review')
    records[PUBLIC_PACKAGE_COLLECTION] = {'p1':{'id':'p1','title':'Stale public projection'}}
    response = client.delete('/api/fr12/packages/p1',headers=AUTH)
    assert response.status_code == 200 and response.get_json()['deletionMode'] == 'soft_delete'
    saved = deepcopy(records['tourism_packages']['p1'])
    assert saved['id'] == 'p1' and saved['deletedBy'] == 'op1' and saved['reviewedAt'] == 'recorded-review'
    assert client.get('/api/fr12/packages',headers=AUTH).get_json()['items'] == []
    assert client.post('/api/fr12/packages/p1/restore',headers=AUTH).status_code == 404
    assert client.put('/api/fr12/packages/p1',headers=AUTH,json={'title':'Undelete'}).status_code == 404
    assert client.delete('/api/fr12/packages/p1',headers=AUTH).get_json()['idempotent']
    assert records['tourism_packages']['p1'] == saved
    assert 'p1' not in records.get(PUBLIC_PACKAGE_COLLECTION,{})
    assert client.get('/api/fr13/packages/p1',headers={'Authorization':'Bearer admin'}).get_json()['package']['deletedAt']


def test_delete_fails_closed_when_dependency_lookup_fails(client,memory,monkeypatch):
    records,retrieve,_ = memory
    def fail(collection,*a,**kw):
        if collection == 'payment_records':raise RuntimeError('private storage failure')
        return retrieve(collection,*a,**kw)
    monkeypatch.setattr('modules.fr12_tourism_operator_management.routes.retrieveRecord',fail)
    result = client.delete('/api/fr12/packages/p1',headers=AUTH)
    assert result.status_code == 503 and not records['tourism_packages']['p1'].get('deletedAt')
    assert 'private storage failure' not in result.get_data(as_text=True)


def test_stale_restore_and_write_conflict_cannot_override_new_state(client,memory,monkeypatch):
    records,_,_ = memory
    assert client.post('/api/fr12/packages/p1/restore',headers=AUTH,json={'expectedUpdatedAt':'stale'}).status_code == 409
    def conflict(*a,**kw):raise ReviewConflict('Changed')
    monkeypatch.setattr('modules.fr12_tourism_operator_management.routes.updateRecord',conflict)
    assert client.post('/api/fr12/packages/p1/restore',headers=AUTH).status_code == 409
    assert records['tourism_packages']['p1']['approvalStatus'] == 'archived'


def test_concurrent_restore_commits_one_transition(client,app,memory,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    records,retrieve,_ = memory
    barrier = Barrier(2)
    def same_revision(collection,documentId=None,**kw):
        value = retrieve(collection,documentId,**kw)
        if collection == 'tourism_packages' and documentId == 'p1':barrier.wait(timeout=5)
        return value
    monkeypatch.setattr('modules.fr12_tourism_operator_management.routes.retrieveRecord',same_revision)
    def restore(_):
        with app.test_client() as request_client:return request_client.post('/api/fr12/packages/p1/restore',headers=AUTH).status_code
    with ThreadPoolExecutor(2) as pool:assert sorted(pool.map(restore,range(2))) == [200,409]
    assert len(records['tourism_packages']['p1']['lifecycleHistory']) == 1


@pytest.mark.parametrize(('snapshot','required'), [
    ({'inclusions':['Digital map'],'accommodation':{},'transport':{}},0),
    ({'inclusions':['Airport transfer'],'accommodation':{},'transport':{'transportTypes':['Private van']}},1),
    ({'inclusions':['Hotel accommodation','Private transport','Guided tour'],'accommodation':{},'transport':{}},3),
])
def test_readiness_components_and_completion_are_derived_from_purchased_snapshot(snapshot,required):
    requirements = derive_required_services(snapshot)
    record = build_initial_fulfillment_record(snapshot)
    order = {'fulfillmentStatus':'awaiting_operator_fulfillment'}
    result = fulfillment_readiness(order,requirements,record,True)
    assert result['requiredCount'] == required
    assert result['canMarkReady'] is (required == 0)
    for service in record['services'].values():
        service.update(status='confirmed',reference='genuine-fixture-ref',providerName='Synthetic Fleet',provenance='operator_attested',confirmedBy='op1',confirmedAt='2026-11-08T10:00:00Z')
    assert fulfillment_readiness(order,requirements,record,True)['canMarkReady']
    assert not fulfillment_readiness(order,requirements,record,False)['canMarkReady']


def test_readiness_explains_missing_transport_provider_reference_and_attestation():
    snapshot = {'inclusions':['Airport transfer'],'accommodation':{},'transport':{'transportTypes':['Very long purchased brochure description']}}
    requirements = derive_required_services(snapshot)
    record = build_initial_fulfillment_record(snapshot)
    assert record['services']['transport']['providerName'] == ''
    result = fulfillment_readiness({},requirements,record,True)
    assert 'Actual transport provider / fleet is missing.' in result['blockers']
    assert 'Transportation booking reference is missing.' in result['blockers']
    assert result['completedCount'] == 0


@pytest.mark.parametrize('state', ['fulfilled','fulfillment_declined','trip_ready'])
def test_terminal_readiness_explanations_never_enable_action(state):
    snapshot = {'inclusions':[],'accommodation':{},'transport':{}}
    result = fulfillment_readiness({'fulfillmentStatus':state},derive_required_services(snapshot),build_initial_fulfillment_record(snapshot),True)
    assert not result['canMarkReady'] and result['blockers']


@pytest.mark.parametrize(('provider','expected'), [('',400),('Actual synthetic fleet',200)])
def test_transport_attestation_requires_actual_provider_and_preserves_financial_snapshot(client,mock_operator_auth,monkeypatch,provider,expected):
    from test_fr12_operator_supplier_fulfillment import _sample_order, _trip_for, _memory_commit, AUTH_HEADER
    from modules.fr12_tourism_operator_management import routes
    order = _sample_order()
    store = {order['id']:deepcopy(order),order['fulfilledTripId']:_trip_for(order)}
    before = deepcopy(order['packageSnapshot'])
    monkeypatch.setattr(routes,'retrieveRecord',lambda c,i: None if c == 'package_requirement_clarifications' else deepcopy(store.get(i)))
    monkeypatch.setattr(routes,'commitPackageFulfillment',_memory_commit(store))
    response = client.post('/api/fr12/bookings/'+order['id']+'/fulfillment',headers=AUTH_HEADER,
        json={'serviceType':'transport','reference':'DISPATCH-42','providerName':provider})
    assert response.status_code == expected
    assert store[order['id']]['packageSnapshot'] == before and store[order['id']]['amount'] == order['amount']
    if provider:
        service = store[order['id']]['fulfillmentRecord']['services']['transport']
        assert service['providerName'] == provider and service['reference'] == 'DISPATCH-42'
        assert service['confirmedBy'] == 'test_operator_uid' and service['provenance'] == 'operator_attested'
    else:
        assert 'actual transport provider' in response.get_json()['error']
