"""Actual portal forms with mocked authenticated Backend responses only."""
from copy import deepcopy
from unittest.mock import MagicMock, patch
import pytest
from test_operator_supplier_fulfillment import auth_client, app, SAMPLE_BOOKING


def response(booking):
    result = MagicMock(ok=True)
    result.json.return_value = {'ok': True, 'booking': booking, 'items': [booking]}
    return result


@pytest.mark.parametrize('service,field', [('transport','providerName'),('guideActivities','supplierName')])
def test_portal_posts_explicit_attestation_without_reference(auth_client, service, field):
    calls = []
    def api(method, path, **kwargs):
        calls.append((method, path, kwargs)); return response(SAMPLE_BOOKING)
    with patch.dict(app.view_functions['operator_fr12.update_booking_fulfillment'].__globals__, {'call_api': api}):
        result = auth_client.post('/bookings/fixture-order/fulfillment', data={
            'serviceType': service, field: 'Fictional test authority', 'notes': 'Confirmed meeting point', 'attestation': 'confirmed'})
    assert result.status_code == 302
    assert len(calls) == 1
    payload = calls[0][2]['json']
    assert 'reference' not in payload
    assert payload['attestation'] == 'confirmed' and payload[field] == 'Fictional test authority'


@pytest.mark.parametrize('data', [
    {'serviceType':'transport','providerName':'Fleet'},
    {'serviceType':'guideActivities','attestation':'confirmed'},
    {'serviceType':'accommodation','supplierName':'Hotel'},
])
def test_invalid_form_never_calls_backend(auth_client, data):
    api = MagicMock()
    with patch.dict(app.view_functions['operator_fr12.update_booking_fulfillment'].__globals__, {'call_api': api}):
        assert auth_client.post('/bookings/fixture-order/fulfillment', data=data).status_code == 302
    api.assert_not_called()


def test_fields_removed_accommodation_retained_and_reference_free_records_visible(auth_client):
    booking = deepcopy(SAMPLE_BOOKING)
    for key, service in booking['fulfillmentRecord']['services'].items():
        service.update(status='confirmed', reference='OLD-ACCOM' if key == 'accommodation' else '',
                       providerName='Fictional fleet', guideOrActivity='Fictional guide',
                       provenance='operator_attested', confirmedBy='operator', confirmedAt='2026-11-22T01:00:00Z')
    booking['readiness'] = {'canMarkReady':True,'requirementsReliable':True,'requiredCount':3,'completedCount':3,
        'blockers':[], 'components':[{'key':key,'label':key,'required':True,'complete':True,'uncertain':False}
                                    for key in ['accommodation','transport','guideActivities']]}
    with patch.dict(app.view_functions['operator_fr12.booking_detail'].__globals__, {'call_api': lambda *a, **k: response(booking)}):
        result = auth_client.get('/bookings/fixture-order')
    assert result.status_code == 200
    html = result.get_data(as_text=True)
    assert 'Transit / Booking Reference' not in html and 'License / Voucher' not in html
    assert html.count('name="reference"') == 1
    assert html.count('name="attestation"') == 2
    saved = html.split('Saved Arrangements', 1)[1]
    assert 'Fictional fleet' in saved and 'Fictional guide' in saved
    assert 'OLD-ACCOM' in saved and '2026-11-22T01:00:00Z' in saved
    assert 'not independently supplier-verified' in saved


@pytest.mark.parametrize('state,label,css', [('ready','Ready','approved'),('awaiting_arrangements','Awaiting Arrangements','pending'),('needs_review','Needs Review','pending')])
def test_list_and_detail_use_identical_authoritative_status(auth_client, state, label, css):
    booking = deepcopy(SAMPLE_BOOKING)
    booking['statusOverview'] = {'operatorReadiness':{'state':state,'label':label},
        'travellerTrip':{'state':'created','label':'Created'},'supplierArrangements':{'state':'pending','label':'Awaiting Arrangements'}}
    with patch.dict(app.view_functions['operator_fr12.booking_detail'].__globals__, {'call_api': lambda *a, **k: response(booking)}):
        detail = auth_client.get('/bookings/fixture-order').get_data(as_text=True)
        listing = auth_client.get('/bookings').get_data(as_text=True)
    assert f'class="status {css}">{label}</strong>' in detail
    assert f'class="status {css}">{label}</span>' in listing
