"""Actual portal links/forms with backend state projections; no network calls."""
from copy import deepcopy
from html import unescape
import re

import pytest
from test_operator_management_controls import app,auth_client,portal_data,booking,ids  # noqa: F401


def detail():
    return booking('owned-reference',statusOverview={
        'travellerTrip':{'state':'created','label':'Created'},
        'operatorReadiness':{'state':'needs_review','label':'Needs Review'},
        'supplierArrangements':{'state':'needs_review','label':'Needs Review'}},
        fulfillmentStatus='fulfilled',requiredServices={'transport':{'required':False,'uncertain':True,'reviewReason':'Purchased inclusion and exclusion information conflicts.'}},
        readiness={'canMarkReady':False,'requirementsReliable':False,'requiredCount':0,'completedCount':0,
                   'blockers':['Transportation needs purchase-time evidence.']},
        requirementClarification={'canPropose':True,'revision':0,'legacyReviewed':False,
            'originalEvidence':{'transport':{'inclusions':{'present':True,'value':['Private transfer included']},'exclusions':{'present':True,'value':['Transportation']}}}})


def test_real_clarification_form_submits_exact_order_revision_and_proposal(auth_client,portal_data,monkeypatch):
    monkeypatch.setitem(app.config,'WTF_CSRF_ENABLED',True)
    portal_data['detail']=detail()
    page=auth_client.get('/bookings/owned-reference');html=page.get_data(as_text=True)
    assert page.status_code==200 and 'Private transfer included' in html and 'Transportation needs purchase-time evidence.' in html
    assert 'Supplier requirements need review' in html
    assert 'Reservation Not Created' not in html
    assert 'overflow-wrap:anywhere' in html and 'Mark Arrangements Ready' in html
    request_id=re.search(r'name="requestId" value="([a-f0-9]{32})"',html).group(1)
    action=unescape(re.search(r'action="([^"]+/clarifications)"',html).group(1))
    csrf=re.search(r'name="csrf_token" value="([^"]+)"',html).group(1)
    response=auth_client.post(action,data={'csrf_token':csrf,'requestId':request_id,'expectedRevision':'0','legacyReview':'true',
        'transportResolution':'included','transportPromise':'Original private transfer remains included.',
        'reason':'Conflicting purchased fields require review.','evidenceReference':'original-contract-101',
        'evidenceSummary':'Original signed purchase brochure includes the private transfer.'})
    assert response.status_code==302 and response.location.endswith('/bookings/owned-reference')
    method,path,kwargs=portal_data['calls'][-1]
    assert (method,path)==('POST','/api/fr12/bookings/owned-reference/clarifications')
    payload=kwargs['json'];assert payload['expectedRevision']==0 and payload['requestId']==request_id and payload['legacyReview']
    assert payload['components']=={'transport':{'required':True,'promise':'Original private transfer remains included.'}}


def test_pending_review_is_readonly_and_keeps_ready_blocked(auth_client,portal_data):
    item=detail();item['requirementClarification']['record']={'status':'pending','revision':1,'history':[]}
    portal_data['detail']=item
    html=auth_client.get('/bookings/owned-reference').get_data(as_text=True)
    assert 'Awaiting Administrator review' in html and 'name="transportResolution"' not in html
    assert re.search(r'<button[^>]*id="confirm-fulfillment-btn"[^>]*disabled',html)


def test_clarification_post_has_csrf_gate(auth_client,portal_data):
    app.config['WTF_CSRF_ENABLED']=True
    try:
        result=auth_client.post('/bookings/owned-reference/clarifications',data={'expectedRevision':'0'})
        assert result.status_code==400 and not portal_data['calls']
    finally:app.config['WTF_CSRF_ENABLED']=False


@pytest.mark.parametrize('state,expected',[('needs_review',['review']),('trip_created',['review']),('supplier_not_required',['none']),('fulfilled',['ready'])])
def test_status_filters_use_authoritative_states_and_preserve_combined_filters(auth_client,portal_data,state,expected):
    review=detail();review.update(id='review',orderReference='review')
    none=booking('none',statusOverview={'travellerTrip':{'state':'not_created'},'operatorReadiness':{'state':'awaiting_arrangements'},'supplierArrangements':{'state':'not_required','label':'Not Required'}})
    ready=booking('ready',statusOverview={'travellerTrip':{'state':'unknown'},'operatorReadiness':{'state':'ready'},'supplierArrangements':{'state':'arrangements_recorded'}})
    portal_data['bookings']=[review,none,ready,booking('wrong-package',packageId='other')]
    original=deepcopy(portal_data['bookings'])
    html=auth_client.get('/bookings',query_string={'status':state,'package':'p1','departure':'2027-01-10','q':'heritage','sort':'reference'}).get_data(as_text=True)
    assert ids(html)==expected and portal_data['bookings']==original
