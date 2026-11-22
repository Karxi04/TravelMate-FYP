from copy import deepcopy
import pytest
from test_reference_free_fulfillment import booking
from test_fr12_operator_supplier_fulfillment import AUTH_HEADER
from services.package_checkout_contract import valid_accommodation_provider, fulfillment_readiness, derive_required_services


@pytest.mark.parametrize('name', ['', 'Hotel', 'TBC', 'To Be Confirmed – Teluk Bahang / Batu Ferringhi Area',
                                 'to be confirmed', 'Unknown', 'N/A', '1234', 'A\nHotel'])
def test_placeholder_or_non_meaningful_actual_provider_rejected(client, booking, name):
    store, identity = booking; before = deepcopy(store)
    response = client.post(f'/api/fr12/bookings/{identity}/fulfillment', headers=AUTH_HEADER,
        json={'serviceType':'accommodation','supplierName':name,'attestation':'confirmed'})
    assert response.status_code == 400 and store == before
    assert not valid_accommodation_provider(name)


def test_reference_free_accommodation_preserves_room_notes_audit_and_final_gate(client, booking):
    store, identity = booking
    body = {'serviceType':'accommodation','supplierName':'Fictional Seaside Hotel',
            'attestation':'confirmed','notes':'Three travellers: two rooms, one twin and one single.'}
    before = deepcopy(store[identity])
    response = client.post(f'/api/fr12/bookings/{identity}/fulfillment', headers=AUTH_HEADER, json=body)
    assert response.status_code == 200, response.json
    saved = response.json['booking']['fulfillmentRecord']['services']['accommodation']
    assert saved['reference'] == '' and saved['supplierName'] == body['supplierName']
    assert saved['notes'] == body['notes'] and saved['confirmedBy'] and saved['confirmedAt']
    assert saved['provenance'] == 'operator_attested'
    assert response.json['booking']['fulfillmentStatus'] != 'trip_ready'
    assert client.post(f'/api/fr12/bookings/{identity}/confirm-fulfillment', headers=AUTH_HEADER).status_code == 400
    assert store[identity]['packageSnapshot'] == before['packageSnapshot']
    assert client.post(f'/api/fr12/bookings/{identity}/fulfillment', headers=AUTH_HEADER, json=body).status_code == 200
    assert store[identity]['fulfillmentRecord']['services']['accommodation'] == saved
    old = deepcopy(store[identity]); changed = {**body, 'supplierName':'Fictional Garden Hotel'}
    changed.pop('attestation')
    assert client.post(f'/api/fr12/bookings/{identity}/fulfillment', headers=AUTH_HEADER, json=changed).status_code == 400
    assert store[identity] == old
    store[identity]['fulfillmentRecord']['services']['accommodation']['reference'] = 'HISTORICAL-HOTEL-REF'
    changed['attestation'] = 'confirmed'
    response = client.post(f'/api/fr12/bookings/{identity}/fulfillment', headers=AUTH_HEADER, json=changed)
    assert response.status_code == 200
    saved = response.json['booking']['fulfillmentRecord']['services']['accommodation']
    assert saved['reference'] == 'HISTORICAL-HOTEL-REF'
    assert saved['attestationHistory'][-1]['supplierName'] == body['supplierName']


def test_placeholder_attestation_cannot_satisfy_readiness(booking):
    store, identity = booking; order = store[identity]
    svc = order['fulfillmentRecord']['services']['accommodation']
    svc.update(status='confirmed', supplierName='To Be Confirmed – Beach Area', reference='OLD-REF',
               provenance='operator_attested',confirmedBy='operator',confirmedAt='2026-11-22T01:00:00Z')
    result = fulfillment_readiness(order, derive_required_services(order['packageSnapshot']), order['fulfillmentRecord'], True)
    assert not next(row for row in result['components'] if row['key']=='accommodation')['complete']
    assert not result['canMarkReady']
