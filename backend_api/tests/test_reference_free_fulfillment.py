"""Owner-scoped in-memory attestations; never read or update actual bookings."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from test_fr12_operator_supplier_fulfillment import _sample_order, _trip_for, _memory_commit, AUTH_HEADER
from modules.fr12_tourism_operator_management import routes


@pytest.fixture
def booking(monkeypatch, mock_operator_auth):
    order = _sample_order()
    store = {order['id']: order, order['fulfilledTripId']: _trip_for(order)}
    def read(collection, identity=None, **kwargs):
        if collection == 'package_requirement_clarifications': return None
        return deepcopy(store.get(identity)) if identity else [deepcopy(store[order['id']])]
    monkeypatch.setattr(routes, 'retrieveRecord', read)
    monkeypatch.setattr(routes, 'commitPackageFulfillment', _memory_commit(store))
    return store, order['id']


@pytest.mark.parametrize('service,name_field', [('transport','providerName'),('guideActivities','guideOrActivity')])
def test_reference_free_attestation_is_saved_and_visible(client, booking, service, name_field):
    store, identity = booking
    before = deepcopy(store[identity])
    body = {'serviceType': service, name_field: 'Fictional demonstration authority', 'attestation': 'confirmed', 'notes': 'Meeting point confirmed'}
    result = client.post(f'/api/fr12/bookings/{identity}/fulfillment', headers=AUTH_HEADER, json=body)
    assert result.status_code == 200, result.json
    record = result.json['booking']['fulfillmentRecord']['services'][service]
    assert record['reference'] == '' and record['provenance'] == 'operator_attested'
    assert record['confirmedBy'] and record['confirmedAt'] and record[name_field]
    assert result.json['booking']['readiness']['completedCount'] == 1
    assert store[identity]['packageSnapshot'] == before['packageSnapshot']
    for field in ['amount','currency','paymentStatus','fulfilledTripId','travellerId']:
        assert store[identity][field] == before[field]
    assert client.post(f'/api/fr12/bookings/{identity}/fulfillment', headers=AUTH_HEADER, json=body).status_code == 200
    assert store[identity]['fulfillmentRecord']['services'][service] == record


@pytest.mark.parametrize('body', [
    {'serviceType':'transport','providerName':'Fleet'},
    {'serviceType':'transport','providerName':'Fleet','reference':'EXTERNAL-REF'},
    {'serviceType':'transport','attestation':'confirmed'},
    {'serviceType':'guideActivities','attestation':'confirmed'},
    {'serviceType':'guideActivities','guideOrActivity':'Guide','attestation':'no'},
    {'serviceType':'accommodation','supplierName':'Hotel','attestation':'confirmed'},
])
def test_missing_details_or_confirmation_rejected(client, booking, body):
    store, identity = booking; before = deepcopy(store)
    assert client.post(f'/api/fr12/bookings/{identity}/fulfillment', headers=AUTH_HEADER, json=body).status_code == 400
    assert store == before


def test_historical_reference_and_prior_attestation_retained(client, booking):
    store, identity = booking
    record = store[identity]['fulfillmentRecord']['services']['transport']
    record.update(reference='HISTORICAL-REF', status='confirmed', providerName='Former fleet',
                  confirmedAt='2026-11-01T10:00:00Z', confirmedBy='test_operator_uid', provenance='operator_attested')
    result = client.post(f'/api/fr12/bookings/{identity}/fulfillment', headers=AUTH_HEADER,
        json={'serviceType':'transport','providerName':'Replacement fleet','attestation':'confirmed'})
    assert result.status_code == 200
    service = result.json['booking']['fulfillmentRecord']['services']['transport']
    assert service['reference'] == 'HISTORICAL-REF'
    assert service['attestationHistory'][-1]['providerName'] == 'Former fleet'


def test_all_attestations_enable_ready_but_payment_alone_does_not(client, booking):
    store, identity = booking
    assert client.post(f'/api/fr12/bookings/{identity}/confirm-fulfillment', headers=AUTH_HEADER).status_code == 400
    for body in [{'serviceType':'accommodation','supplierName':'Fictional hotel','attestation':'confirmed'},
                 {'serviceType':'transport','providerName':'Fictional fleet','attestation':'confirmed'},
                 {'serviceType':'guideActivities','guideOrActivity':'Fictional guide','attestation':'confirmed'}]:
        result = client.post(f'/api/fr12/bookings/{identity}/fulfillment', headers=AUTH_HEADER, json=body)
        assert result.status_code == 200, result.json
    before = deepcopy(store[identity])
    ready = client.post(f'/api/fr12/bookings/{identity}/confirm-fulfillment', headers=AUTH_HEADER)
    assert ready.status_code == 200, ready.json
    overview = ready.json['booking']['statusOverview']
    assert overview['operatorReadiness']['state'] == 'ready'
    assert overview['supplierArrangements']['state'] == 'arrangements_recorded'
    assert overview['supplierArrangements']['independentlyConfirmed'] is False
    assert store[identity]['packageSnapshot'] == before['packageSnapshot']


def test_ten_isolated_demo_orders_use_actual_projection(monkeypatch):
    data = json.loads((Path(__file__).parent/'fixtures/operator_fulfillment_demo.json').read_text(encoding='utf-8'))
    assert data['synthetic'] is True and data['deployment'] == 'isolated-fixture-only'
    from services.booking_requirements import load_context, status_overview
    states = []
    for order in data['orders']:
        assert order['synthetic'] and order['testMode'] and order['id'].startswith('demo-')
        read = lambda collection, identity=None: _trip_for(order) if collection == 'itineraries' else None
        context, trip = load_context(order, read)
        overview, readiness = status_overview(order, context, order['fulfillmentRecord'], trip)
        states.append(overview['operatorReadiness']['state'])
        assert overview['supplierArrangements']['independentlyConfirmed'] is False
    assert states.count('ready') == 8
    assert states.count('awaiting_arrangements') == 1
    assert states.count('needs_review') == 1


@pytest.mark.parametrize('mutation,expected', [({},'awaiting_arrangements'), ({'paymentStatus':'pending','status':'pending'},'not_applicable')])
def test_historical_ready_flag_cannot_falsely_complete_missing_arrangements(mutation, expected):
    from services.booking_requirements import load_context, status_overview
    order = _sample_order(fulfillmentStatus='trip_ready', **mutation)
    context, trip = load_context(order, lambda c,i: _trip_for(order) if c == 'itineraries' else None)
    overview, readiness = status_overview(order, context, order['fulfillmentRecord'], trip)
    assert overview['operatorReadiness']['state'] == expected
    assert readiness['completedCount'] == 0
    assert not readiness['canMarkReady']
