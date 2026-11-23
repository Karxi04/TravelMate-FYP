from copy import deepcopy
from unittest.mock import patch
from html.parser import HTMLParser
import pytest
from test_reference_free_arrangements import auth_client, app, SAMPLE_BOOKING, response


class Forms(HTMLParser):
    def __init__(self):
        super().__init__(); self.inputs = []
    def handle_starttag(self, tag, attrs):
        if tag == 'input': self.inputs.append(dict(attrs))


def test_accommodation_brochure_stays_read_only_and_actual_form_starts_empty(auth_client):
    data = deepcopy(SAMPLE_BOOKING)
    placeholder = 'To Be Confirmed – Teluk Bahang / Batu Ferringhi Area'
    data['requiredServices']['accommodation'].update(brochureName=placeholder, clarifiedPromise='Administrator reviewed: suitable rooms for three travellers')
    data['fulfillmentRecord']['services']['accommodation']['supplierName'] = placeholder
    with patch.dict(app.view_functions['operator_fr12.booking_detail'].__globals__, {'call_api': lambda *a, **kw: response(data)}):
        page = auth_client.get('/bookings/fixture-order')
    html = page.get_data(as_text=True); parser = Forms(); parser.feed(html)
    assert page.status_code == 200
    assert placeholder in html and 'Administrator reviewed: suitable rooms for three travellers' in html
    assert 'Actual Accommodation Provider / Hotel *' in html
    assert 'Supplier / Internal Contract Reference *' not in html
    assert not any(row.get('name') == 'reference' for row in parser.inputs)
    hotels = [row for row in parser.inputs if row.get('placeholder') == 'Actual hotel or accommodation provider']
    assert hotels[0]['value'] == '' and 'required' in hotels[0]
    boxes = [row for row in parser.inputs if row.get('name') == 'attestation']
    assert len(boxes) == 3 and all('required' in row and 'checked' not in row for row in boxes)
    assert 'two rooms for three travellers' in html
    assert '✓ Arrangement Confirmed' not in html


def test_all_three_saved_confirmations_persist_on_reopen_without_autocheck_or_post(auth_client):
    data = deepcopy(SAMPLE_BOOKING)
    names = {'accommodation':('supplierName','Fictional Seaside Hotel'), 'transport':('providerName','Fictional fleet'),
             'guideActivities':('guideOrActivity','Fictional guide')}
    for key, (field,name) in names.items():
        data['fulfillmentRecord']['services'][key].update({field:name,'status':'confirmed','reference':'',
            'notes':'Three travellers: two rooms.' if key=='accommodation' else 'Meeting point confirmed',
            'provenance':'operator_attested','confirmedBy':'operator','confirmedAt':'2026-11-22T01:00:00Z'})
    data['readiness'] = {'canMarkReady':True,'requirementsReliable':True,'requiredCount':3,'completedCount':3,
        'blockers':[], 'components':[{'key':key,'label':key,'required':True,'complete':True,'uncertain':False} for key in names]}
    calls = []
    def api(method, path, **kwargs):
        calls.append(method); assert method == 'GET'; return response(data)
    with patch.dict(app.view_functions['operator_fr12.booking_detail'].__globals__, {'call_api': api}):
        for _ in range(2):
            page = auth_client.get('/bookings/fixture-order'); html = page.get_data(as_text=True)
            assert page.status_code == 200 and html.count('✓ Arrangement Confirmed') == 3
            assert html.count('class="status approved">✓ Arrangement Confirmed') == 3
            assert all(name in html for _,name in names.values())
            assert 'Three travellers: two rooms.' in html and 'Attested at 2026-11-22 01:00' in html
            assert html.count('Operator-attested · not independently supplier-verified.') == 3
            parser = Forms(); parser.feed(html)
            assert all('checked' not in row for row in parser.inputs if row.get('name') == 'attestation')
            assert html.count('oninput="if(event.target.name') == 3
    assert calls == ['GET','GET']


@pytest.mark.parametrize('name', ['', 'Hotel', 'TBC', 'To Be Confirmed – Teluk Bahang / Batu Ferringhi Area'])
def test_website_rejects_placeholder_before_backend(auth_client, name):
    with patch.dict(app.view_functions['operator_fr12.update_booking_fulfillment'].__globals__, {'call_api': lambda *a, **k: pytest.fail('Invalid form must not be sent')}):
        assert auth_client.post('/bookings/fixture-order/fulfillment', data={
            'serviceType':'accommodation','supplierName':name,'attestation':'confirmed'}).status_code == 302


def test_website_serializes_reference_free_accommodation_confirmation(auth_client):
    calls = []
    with patch.dict(app.view_functions['operator_fr12.update_booking_fulfillment'].__globals__, {'call_api': lambda *a, **k: calls.append(k['json']) or response(SAMPLE_BOOKING)}):
        result = auth_client.post('/bookings/fixture-order/fulfillment', data={'serviceType':'accommodation',
            'supplierName':'Fictional Seaside Hotel','attestation':'confirmed','notes':'Two rooms for three travellers'})
    assert result.status_code == 302
    assert calls == [{'serviceType':'accommodation','supplierName':'Fictional Seaside Hotel',
                     'attestation':'confirmed','notes':'Two rooms for three travellers'}]
