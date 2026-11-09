from unittest.mock import MagicMock
import re

import pytest
from test_admin_commerce_presentation import app,auth_client,_patch_view_api  # noqa: F401


def response(payload):
    value=MagicMock(ok=True,status_code=200);value.json.return_value={'ok':True,**payload};return value


def test_queue_links_to_exact_owned_order_review(auth_client):
    api=MagicMock(return_value=response({'items':[{'orderId':'paid-reference','operatorId':'operator','revision':1,'updatedAt':'2026-11-09'}]}))
    with _patch_view_api('admin_fr13.booking_clarifications',api):
        page=auth_client.get('/admin/booking-clarifications')
    assert page.status_code==200 and '/admin/bookings/paid-reference/clarification' in page.get_data(as_text=True)
    api.assert_called_once_with('GET','/api/fr12/booking-clarifications')


@pytest.mark.parametrize('decision',['approved','rejected','needs_evidence'])
def test_review_get_and_decision_form_maps_exact_callback(auth_client,decision,monkeypatch):
    monkeypatch.setitem(app.config,'WTF_CSRF_ENABLED',True)
    booking={'orderReference':'paid-reference','packageTitle':'Original package',
        'requiredServices':{'transport':{'uncertain':True,'reviewReason':'Purchased inclusion and exclusion information conflicts.'}},
        'requirementClarification':{'originalEvidence':{'transport':{'inclusions':{'present':True,'value':['Private transfer']}}},
            'record':{'status':'pending','revision':1,'proposal':{'reason':'Private review evidence','components':{'transport':{'required':True,'promise':'Purchased transfer included.'}}},'history':[]}}}
    api=MagicMock(return_value=response({'booking':booking}))
    with _patch_view_api('admin_fr13.booking_clarification_review',api):
        page=auth_client.get('/admin/bookings/paid-reference/clarification');html=page.get_data(as_text=True)
        assert page.status_code==200 and 'Private transfer' in html and 'entitlementVerified' in html
        assert 'Purchased inclusion and exclusion information conflicts.' in html
        assert re.search(r'href="/admin/bookings" class="active"',html)
        nonce=re.search(r'name="requestId" value="([a-f0-9]{32})"',html).group(1)
        csrf=re.search(r'name="csrf_token" value="([^"]+)"',html).group(1)
        posted=auth_client.post('/admin/bookings/paid-reference/clarification',data={'csrf_token':csrf,'requestId':nonce,'expectedRevision':'1','decision':decision,
            'reason':'Original purchase-time evidence was reviewed.','evidenceReference':'purchase-contract-101','entitlementVerified':'true'})
    assert posted.status_code==302
    method,path=api.call_args.args
    assert (method,path)==('POST','/api/fr12/bookings/paid-reference/clarifications/review')
    assert api.call_args.kwargs['json']=={'requestId':nonce,'expectedRevision':1,'decision':decision,
        'reason':'Original purchase-time evidence was reviewed.','evidenceReference':'purchase-contract-101','entitlementVerified':True}


def test_review_post_is_csrf_protected_before_backend_call(auth_client):
    app.config['WTF_CSRF_ENABLED']=True
    try:
        api=MagicMock()
        with _patch_view_api('admin_fr13.booking_clarification_review',api):
            result=auth_client.post('/admin/bookings/paid-reference/clarification',data={'decision':'approved'})
            assert result.status_code==400
            api.assert_not_called()
    finally:app.config['WTF_CSRF_ENABLED']=False
