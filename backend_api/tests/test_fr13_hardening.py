"""F-F4B HTTP contracts; synthetic records only, no live persistence/providers."""
from copy import deepcopy
from unittest.mock import patch

import pytest

from modules.fr13_administrator_management import routes

AUTH = {'Authorization': 'Bearer synthetic-admin'}
PACKAGE = {'id': 'p', 'operatorId': 'op', 'title': 'Heritage tour', 'destination': 'Penang',
           'fullDescription': 'A guided heritage tour.', 'durationDays': 1, 'adultPrice': 100,
           'currency': 'MYR', 'approvalStatus': 'approved', 'availabilityStatus': 'available'}
CAMPAIGN = {'id': 'c', 'operatorId': 'op', 'packageId': 'p', 'campaignTitle': 'Announcement',
            'startDate': '2020-01-01', 'endDate': '2099-01-01', 'discountType': 'percentage',
            'discountValue': 0, 'reviewStatus': 'pending'}


@pytest.fixture
def records():
    data = {'tourism_packages': [deepcopy(PACKAGE)], 'promotional_campaigns': [deepcopy(CAMPAIGN)]}
    def retrieve(collection, documentId=None, filters=None, limit=None):
        items = data.get(collection, [])
        if documentId:
            return deepcopy(next((v for v in items if v.get('id') == documentId), None))
        return deepcopy(items[:limit] if limit else items)
    with patch.object(routes, 'retrieveRecord', side_effect=retrieve):
        yield data


@pytest.mark.parametrize('changes', [
    {'reviewStatus': 'draft'}, {'discountValue': 101}, {'discountValue': float('inf')},
    {'startDate': 'invalid'}, {'operatorId': 'other'}, {'packageId': 'absent'}])
def test_invalid_campaign_cannot_be_approved(client, mock_admin_auth, records, changes):
    records['promotional_campaigns'][0].update(changes)
    with patch.object(routes, 'updateRecord', return_value={'reviewStatus': 'approved'}) as save:
        response = client.post('/api/fr13/campaigns/c/review', headers=AUTH, json={'decision': 'approved'})
    assert response.status_code in {400, 404, 409}
    save.assert_not_called()


def test_valid_announcement_approval_and_retry(client, mock_admin_auth, records):
    with patch.object(routes, 'updateRecord', side_effect=lambda c, i, v, **kw: {**CAMPAIGN, **v}) as save:
        first = client.post('/api/fr13/campaigns/c/review', headers=AUTH, json={'decision': 'approved'})
    assert first.status_code == 200
    records['promotional_campaigns'][0] = first.get_json()['campaign']
    with patch.object(routes, 'updateRecord', return_value=records['promotional_campaigns'][0]) as again:
        retry = client.post('/api/fr13/campaigns/c/review', headers=AUTH, json={'decision': 'approved'})
    assert retry.status_code == 200 and retry.get_json()['idempotent'] is True
    again.assert_not_called()


def test_invalid_submitted_package_is_not_approved(client, mock_admin_auth, records):
    records['tourism_packages'][0].update(approvalStatus='pending', adultPrice=float('nan'))
    with patch.object(routes, 'updateRecord', return_value={'approvalStatus': 'approved'}) as save:
        response = client.post('/api/fr13/packages/p/review', headers=AUTH, json={'decision': 'approved'})
    assert response.status_code == 400
    save.assert_not_called()


@pytest.mark.parametrize('path', ['/users/absent', '/destinations/absent', '/activities/absent'])
def test_missing_update_target_does_not_report_success(client, mock_admin_auth, records, path):
    with patch.object(routes, 'updateRecord', return_value=None) as save:
        response = client.put('/api/fr13'+path, headers=AUTH, json={'role': 'operator', 'title': 'Title', 'activityName': 'Walk'})
    assert response.status_code == 404
    save.assert_not_called()


@pytest.mark.parametrize('path', ['/users/u', '/campaigns/c/review', '/packages/p/review', '/destinations', '/activities'])
def test_malformed_object_rejected(client, mock_admin_auth, records, path):
    records['tourism_packages'][0]['approvalStatus'] = 'pending'
    response = client.open('/api/fr13'+path, method='PUT' if path.startswith('/users') else 'POST', headers=AUTH, json=['invalid'])
    assert response.status_code == 400


def test_no_false_success_or_exception_disclosure(client, mock_admin_auth, records):
    with patch.object(routes, 'updateRecord', side_effect=RuntimeError('private-credential-sentinel')):
        response = client.post('/api/fr13/campaigns/c/review', headers=AUTH, json={'decision': 'approved'})
    assert response.status_code == 503
    assert 'private-credential' not in response.get_data(as_text=True)
    with patch.object(routes, 'updateRecord', return_value=None):
        missing = client.post('/api/fr13/campaigns/c/review', headers=AUTH, json={'decision': 'approved'})
    assert missing.status_code != 200


def test_financial_totals_use_finite_myr_canonical_paid_records(client, mock_admin_auth, records):
    paid = {'quoteType': 'package', 'operatorId': 'op', 'paymentStatus': 'paid', 'status': 'paid',
            'currency': 'MYR', 'provider': 'stripe_checkout_test', 'amount': 100}
    records['checkout_orders'] = [
        {**paid, 'id': 'one', 'checkoutSessionId': 'synthetic-settlement'},
        {**paid, 'id': 'duplicate', 'checkoutSessionId': 'synthetic-settlement'},
        {**paid, 'id': 'cancelled', 'status': 'checkout_cancelled', 'amount': 900},
        {**paid, 'id': 'foreign', 'currency': 'USD', 'amount': 700},
        {**paid, 'id': 'unknown', 'currency': None, 'amount': 600},
        {**paid, 'id': 'invalid', 'amount': float('inf')}]
    response = client.get('/api/fr13/reports/summary', headers=AUTH)
    assert response.status_code == 200
    summary = response.get_json()['payments']
    assert summary['totalPaidRevenue'] == summary['testPaidTotal'] == 100
    bookings = client.get('/api/fr13/bookings?type=package', headers=AUTH).get_json()['items']
    assert len(bookings) == 5


def test_report_filter_scope_campaign_dates_and_public_feedback(client, mock_admin_auth, records):
    records['checkout_orders'] = [
        {'id': 'old', 'amount': 100, 'currency': 'MYR', 'paymentStatus': 'paid', 'createdAt': '2000-01-01'},
        {'id': 'new', 'amount': 20, 'currency': 'MYR', 'paymentStatus': 'paid', 'createdAt': '2030-01-01'}]
    response = client.get('/api/fr13/reports/summary?reportType=payments&startDate=2030-01-01&endDate=2030-12-31', headers=AUTH)
    assert response.get_json()['payments']['totalPaidRevenue'] == 20
    records['promotional_campaigns'][0].update(reviewStatus='approved', campaignStatus='active', endDate='2000-01-01')
    records['feedback'] = [{'id': 'pending', 'feedbackStatus': 'visible', 'moderationStatus': 'pending_review', 'rating': 5}]
    data = client.get('/api/fr13/reports/summary', headers=AUTH).get_json()
    assert data['campaigns']['active'] == data['feedback']['visible'] == 0


def test_large_dataset_disclosure_and_export_redaction(client, mock_admin_auth, records):
    records['checkout_orders'] = [{'id': str(i), 'paymentStatus': 'paid', 'currency': 'MYR', 'amount': 1,
        'metadata': {'clientSecret': 'nested-private-sentinel'}, 'orderTitle': '=HYPERLINK("unsafe")'} for i in range(502)]
    data = client.get('/api/fr13/payments', headers=AUTH).get_json()
    assert data['dataLimited'] is True and data['recordLimit'] == 500
    report = client.get('/api/fr13/reports/summary?reportType=payments', headers=AUTH).get_json()['report']
    assert report['dataLimited'] is True and report['recordsLimited'] is True
    csv = client.get('/api/fr13/reports/export.csv?reportType=payments', headers=AUTH).get_data(as_text=True)
    assert 'nested-private-sentinel' not in csv
    assert "'=HYPERLINK" in csv


@pytest.mark.parametrize('collection,field,path', [('admin_destinations','title','destinations'), ('admin_activities','activityName','activities')])
def test_content_partial_updates_preserve_fields_and_reject_bad_cost(client, mock_admin_auth, records, collection, field, path):
    original = {'id': 'x', field: 'Original', 'estimatedCost': 20, 'description': 'Keep this', 'address': 'Keep address'}
    records[collection] = [original]
    with patch.object(routes, 'updateRecord', side_effect=lambda c, i, v, **kw: {**original, **v}):
        response = client.put('/api/fr13/'+path+'/x', headers=AUTH, json={field: 'Updated'})
    saved = response.get_json()['destination' if path=='destinations' else 'activity']
    assert saved['estimatedCost'] == 20 and saved['description'] == 'Keep this'
    with patch.object(routes, 'storeRecord') as store:
        bad = client.post('/api/fr13/'+path, headers=AUTH, json={field: 'Invalid', 'estimatedCost': 'not-money'})
    assert bad.status_code == 400
    store.assert_not_called()


@pytest.mark.parametrize('method,path',[
    ('GET','/users'),('PUT','/users/u'),('POST','/packages/p/review'),('POST','/packages/p/suspend'),
    ('POST','/campaigns/c/review'),('POST','/feedback/f/review'),('DELETE','/feedback/f'),
    ('POST','/destinations'),('PUT','/activities/a'),('GET','/bookings'),('GET','/payments'),
    ('GET','/reports/summary'),('GET','/reports/export.csv')])
@pytest.mark.parametrize('role',['none','traveller','operator'])
def test_privileged_routes_enforce_server_role(client,request,method,path,role):
    if role != 'none':request.getfixturevalue('mock_'+role+'_auth')
    response=client.open('/api/fr13'+path,method=method,headers=AUTH if role!='none' else {},json={})
    assert response.status_code == (401 if role=='none' else 403)


def test_user_verification_and_privilege_transitions(client,mock_admin_auth,records):
    records['users']=[{'id':'u','role':'operator','verificationStatus':'pending','status':'active'}]
    with patch.object(routes,'updateRecord',side_effect=lambda c,i,v,**kw:{**records['users'][0],**v}) as update:
        approved=client.put('/api/fr13/users/u',headers=AUTH,json={'verificationStatus':'approved'})
    assert approved.status_code == 200 and approved.get_json()['user']['verificationStatus']=='approved'
    assert update.call_args.kwargs['expected']['verificationStatus']=='pending'
    records['users'][0]['role']='traveller'
    denied=client.put('/api/fr13/users/u',headers=AUTH,json={'verificationStatus':'approved'})
    assert denied.status_code == 400
    with patch.object(routes,'updateRecord',side_effect=lambda c,i,v,**kw:{**records['users'][0],**v}):
        # Existing authorized Administrator provisioning remains available.
        promoted=client.put('/api/fr13/users/u',headers=AUTH,json={'role':'admin'})
    assert promoted.status_code == 200 and promoted.get_json()['user']['role']=='admin'


def test_conditional_persistence_rejects_real_concurrent_stale_writes():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier,Lock,local
    from types import SimpleNamespace
    from google.api_core.exceptions import FailedPrecondition
    from services.review_service import ReviewConflict
    from sequence_contract import firebase_firestore as persistence
    state={'value':{'approvalStatus':'pending','price':100},'version':1}
    barrier,lock,tls=Barrier(2),Lock(),local()
    def get():
        with lock:
            value,version=deepcopy(state['value']),state['version']
        if not getattr(tls,'read',False):
            tls.read=True;barrier.wait(timeout=5)
        return SimpleNamespace(id='p',exists=True,to_dict=lambda:value,update_time=version)
    def update(data,option):
        with lock:
            if state['version'] != option:raise FailedPrecondition('Synthetic version conflict')
            state['value'].update(data);state['version']+=1
    reference=SimpleNamespace(get=get,update=update)
    db=SimpleNamespace(collection=lambda name:SimpleNamespace(document=lambda key:reference),write_option=lambda **kw:kw['last_update_time'])
    def attempt(decision):
        try:
            persistence.updateRecord('tourism_packages','p',{'approvalStatus':decision},expected={'id':'p','approvalStatus':'pending','price':100})
            return 'saved'
        except ReviewConflict:return 'conflict'
    with patch.object(persistence,'get_db',return_value=db),patch.object(persistence,'_revoke_public_projection'),patch.object(persistence,'_public_projection_changed'):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(attempt,['approved','rejected']))
    assert sorted(results)==['conflict','saved'] and state['version']==2


def test_same_timestamp_content_edit_is_detected_before_mutation():
    from types import SimpleNamespace
    from sequence_contract import firebase_firestore as persistence
    from services.review_service import ReviewConflict
    snapshot=SimpleNamespace(id='p',exists=True,to_dict=lambda:{'price':200,'updatedAt':'same'})
    db=SimpleNamespace(collection=lambda name:SimpleNamespace(document=lambda key:SimpleNamespace(get=lambda:snapshot)))
    with patch.object(persistence,'get_db',return_value=db),patch.object(persistence,'_revoke_public_projection') as revoke:
        with pytest.raises(ReviewConflict):
            persistence.updateRecord('tourism_packages','p',{'approvalStatus':'approved'},expected={'id':'p','price':100,'updatedAt':'same'})
    revoke.assert_not_called()


def test_retry_does_not_claim_success_when_publication_recovery_fails(client,mock_admin_auth,records):
    records['promotional_campaigns'][0].update(reviewStatus='approved',reviewComment='')
    with patch('services.public_content_projection.source_changed',side_effect=RuntimeError('synthetic projection outage')):
        response=client.post('/api/fr13/campaigns/c/review',headers=AUTH,json={'decision':'approved'})
    assert response.status_code == 503


def test_admin_pdf_escapes_profile_and_filter_markup():
    from io import BytesIO
    from services.report_service import export_system_report_pdf
    target=BytesIO()
    export_system_report_pdf({'criteria':{'filter':'<img src="file:///forbidden">'},'dataLimited':True,'recordsLimited':True},
        target,admin_profile={'name':'<img src="file:///forbidden">','email':'synthetic@example.invalid'})
    assert target.getvalue().startswith(b'%PDF')


def test_legacy_campaign_without_parent_does_not_break_admin_queue(client,mock_admin_auth,records):
    records['promotional_campaigns']=[{'id':'legacy','campaignTitle':'Unlinked draft','reviewStatus':'draft'}]
    response=client.get('/api/fr13/campaigns?status=all',headers=AUTH)
    assert response.status_code == 200 and response.get_json()['items'][0]['packageTitle']=='-'
