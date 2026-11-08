"""Isolated F-F4C security/consistency regressions; no provider or Firebase access."""
from copy import deepcopy
from unittest.mock import patch

import pytest

from services.package_checkout_contract import derive_required_services
from test_fr12_operator_supplier_fulfillment import _sample_order, AUTH_HEADER, _memory_commit, _trip_for


def test_multi_day_self_guided_itinerary_does_not_imply_supplier_services():
    req = derive_required_services({
        'durationDays': 3, 'durationNights': 2, 'inclusions': ['Digital route map'],
        'exclusions': ['Accommodation', 'Transport', 'Tour guide and entrance tickets'],
        'itineraryDays': [{'activities': ['Self-guided heritage walk']}],
        'accommodation': {}, 'transport': {},
    })
    assert not any(meta['required'] for meta in req.values())


@pytest.mark.parametrize('state', ['trip_ready', 'partially_fulfilled', 'fulfillment_declined'])
def test_payment_recovery_never_resets_supplier_progress(state):
    from modules.fr09_payment.routes import _apply_package_payment
    order = _sample_order(fulfillmentStatus=state)
    order['fulfillmentRecord']['status'] = state
    with patch('modules.fr09_payment.routes._fulfill_package_order', side_effect=AssertionError('must not recreate')), \
         patch('modules.fr09_payment.routes.updateRecord'):
        result = _apply_package_payment(order, {})
    assert 'fulfillmentRecord' not in result
    assert 'fulfillmentStatus' not in result


def test_refunded_payment_is_not_reactivated_by_old_paid_session():
    from modules.fr09_payment.routes import _apply_package_payment
    order = _sample_order(status='refunded', paymentStatus='refunded')
    with patch('modules.fr09_payment.routes._fulfill_package_order', side_effect=AssertionError('must not fulfill')):
        result = _apply_package_payment(order, {'status': 'complete', 'payment_status': 'paid'})
    assert result['status'] == result['paymentStatus'] == 'refunded'


@pytest.mark.parametrize('body', [
    {'serviceType': 'accommodation', 'reference': {'forged': 'reference'}},
    {'serviceType': 'accommodation', 'reference': 'R' * 201},
    {'serviceType': 'accommodation', 'reference': 'R1', 'paymentStatus': 'paid'},
    {'serviceType': 'accommodation', 'reference': 'R1', 'confirmedBy': 'admin'},
])
def test_attestation_payload_types_bounds_and_allowlist(client, mock_operator_auth, body):
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value=_sample_order()), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord',
               side_effect=lambda c, i, data: {**_sample_order(), **data}) as save:
        result = client.post('/api/fr12/bookings/ord-sample-1/fulfillment', headers=AUTH_HEADER, json=body)
    assert result.status_code == 400
    save.assert_not_called()


def test_confirmation_does_not_trust_persisted_required_flags(client, mock_operator_auth):
    order = _sample_order()
    for meta in order['fulfillmentRecord']['requiredServices'].values():
        meta['required'] = False
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value=order), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord',
               side_effect=lambda c, i, data: {**order, **data}):
        result = client.post('/api/fr12/bookings/ord-sample-1/confirm-fulfillment', headers=AUTH_HEADER)
    assert result.status_code == 400


def test_ambiguous_legacy_snapshot_cannot_be_falsely_confirmed(client, mock_operator_auth):
    order = _sample_order(packageSnapshot={'title': 'Legacy'}, fulfillmentRecord=None)
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value=order), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord',
               side_effect=lambda c, i, data: {**order, **data}):
        result = client.post('/api/fr12/bookings/ord-sample-1/confirm-fulfillment', headers=AUTH_HEADER)
    assert result.status_code == 409


def test_payment_terminal_status_blocks_decline(client, mock_operator_auth):
    order = _sample_order(status='refunded', paymentStatus='refunded')
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value=order), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord',
               side_effect=lambda c, i, data: {**order, **data}):
        result = client.post('/api/fr12/bookings/ord-sample-1/decline', headers=AUTH_HEADER,
                             json={'reason': 'Unavailable arrangement'})
    assert result.status_code == 400


def test_missing_persistence_never_returns_false_success(client, mock_operator_auth):
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value=_sample_order()), \
         patch('modules.fr12_tourism_operator_management.routes.commitPackageFulfillment', return_value=None):
        result = client.post('/api/fr12/bookings/ord-sample-1/fulfillment', headers=AUTH_HEADER,
                             json={'serviceType': 'accommodation', 'reference': 'R1'})
    assert result.status_code in {409, 503}


@pytest.fixture
def memory_flow(monkeypatch):
    from modules.fr12_tourism_operator_management import routes
    order = _sample_order()
    store = {order['id']: deepcopy(order), order['fulfilledTripId']: _trip_for(order)}
    monkeypatch.setattr(routes, 'retrieveRecord', lambda c, i: deepcopy(store.get(i)))
    monkeypatch.setattr(routes, 'commitPackageFulfillment', _memory_commit(store))
    return store


def attest_all(client):
    for key in ('accommodation', 'transport', 'guideActivities'):
        result = client.post('/api/fr12/bookings/ord-sample-1/fulfillment', headers=AUTH_HEADER,
                             json={'serviceType': key, 'reference': 'R-' + key, 'providerName':'Synthetic Fleet'})
        assert result.status_code == 200


def test_repeat_confirmation_is_idempotent_and_immutable(client, mock_operator_auth, memory_flow):
    original = deepcopy(memory_flow['ord-sample-1'])
    attest_all(client)
    path = '/api/fr12/bookings/ord-sample-1/confirm-fulfillment'
    assert client.post(path, headers=AUTH_HEADER).status_code == 200
    saved = deepcopy(memory_flow['ord-sample-1'])
    assert client.post(path, headers=AUTH_HEADER).status_code == 200
    assert memory_flow['ord-sample-1'] == saved
    assert memory_flow['trip-pkg-101']['fulfillmentRecord'] == saved['fulfillmentRecord']
    for key in ('amount', 'currency', 'travellerId', 'packageSnapshot', 'testMode', 'createdAt'):
        assert saved[key] == original[key]
    assert client.post('/api/fr12/bookings/ord-sample-1/fulfillment', headers=AUTH_HEADER,
                       json={'serviceType': 'accommodation', 'reference': 'changed'}).status_code == 409


def test_repeat_attestation_and_decline_preserve_audit_metadata(client, mock_operator_auth, memory_flow):
    path = '/api/fr12/bookings/ord-sample-1/fulfillment'
    body = {'serviceType': 'accommodation', 'reference': 'R1'}
    assert client.post(path, headers=AUTH_HEADER, json=body).status_code == 200
    saved = deepcopy(memory_flow['ord-sample-1'])
    assert client.post(path, headers=AUTH_HEADER, json=body).status_code == 200
    assert memory_flow['ord-sample-1'] == saved
    path = '/api/fr12/bookings/ord-sample-1/decline'
    assert client.post(path, headers=AUTH_HEADER, json={'reason': 'Unavailable partner'}).status_code == 200
    saved = deepcopy(memory_flow['ord-sample-1'])
    assert client.post(path, headers=AUTH_HEADER, json={'reason': 'Unavailable partner'}).status_code == 200
    assert memory_flow['ord-sample-1'] == saved
    assert client.post('/api/fr12/bookings/ord-sample-1/confirm-fulfillment', headers=AUTH_HEADER).status_code == 409


@pytest.mark.parametrize('failure', [None, RuntimeError('sensitive persistence detail')])
def test_commit_failure_is_generic_503(client, mock_operator_auth, failure):
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value=_sample_order()), \
         patch('modules.fr12_tourism_operator_management.routes.commitPackageFulfillment',
               return_value=failure, side_effect=failure):
        result = client.post('/api/fr12/bookings/ord-sample-1/fulfillment', headers=AUTH_HEADER,
                             json={'serviceType': 'accommodation', 'reference': 'R1'})
    assert result.status_code == 503
    assert 'sensitive' not in result.get_data(as_text=True)


def test_concurrent_attestations_have_one_cas_winner(app, mock_operator_auth, memory_flow, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from modules.fr12_tourism_operator_management import routes
    barrier = Barrier(2)
    def retrieve(c, i):
        snapshot = deepcopy(memory_flow.get(i))
        barrier.wait(timeout=5)
        return snapshot
    monkeypatch.setattr(routes, 'retrieveRecord', retrieve)
    def request(key):
        with app.test_client() as client:
            return client.post('/api/fr12/bookings/ord-sample-1/fulfillment', headers=AUTH_HEADER,
                               json={'serviceType': key, 'reference': 'R-' + key, 'providerName':'Synthetic Fleet'}).status_code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(request, ('accommodation', 'transport'))) == [200, 409]
    saved = memory_flow['ord-sample-1']
    assert sum(v['status'] == 'confirmed' for v in saved['fulfillmentRecord']['services'].values()) == 1


@pytest.mark.parametrize('endpoint', ['fulfillment', 'confirm-fulfillment', 'decline'])
def test_missing_and_invalid_auth_are_denied(client, endpoint):
    path = '/api/fr12/bookings/ord-sample-1/' + endpoint
    assert client.post(path, json={}).status_code == 401
    with patch('auth_utils.auth.verify_id_token', side_effect=ValueError('invalid token')):
        assert client.post(path, headers=AUTH_HEADER, json={}).status_code == 401


@pytest.mark.parametrize('role', ['traveller', 'pending_operator'])
def test_real_role_boundary(client, monkeypatch, role):
    from types import SimpleNamespace
    profile = {'role': 'operator' if role == 'pending_operator' else role,
               'status': 'active', 'verificationStatus': 'pending'}
    monkeypatch.setattr('auth_utils.auth.verify_id_token', lambda *a, **k: {'uid': 'u'})
    snap = SimpleNamespace(exists=True, to_dict=lambda: profile)
    doc = SimpleNamespace(get=lambda: snap)
    db = SimpleNamespace(collection=lambda c: SimpleNamespace(document=lambda i: doc))
    monkeypatch.setattr('auth_utils.get_db', lambda: db)
    for endpoint in ('fulfillment', 'confirm-fulfillment', 'decline'):
        assert client.post('/api/fr12/bookings/ord-sample-1/' + endpoint,
                           headers=AUTH_HEADER, json={}).status_code == 403


@pytest.mark.parametrize('snapshot', [
    {'inclusions': []}, {'inclusions': ['Digital map']}, {'title': 'Historical package'},
])
def test_partial_legacy_brochure_is_not_a_verified_no_services_contract(snapshot):
    assert any(v.get('uncertain') for v in derive_required_services(snapshot).values())


def test_no_services_package_requires_no_fictitious_reservation(client, mock_operator_auth, memory_flow):
    memory_flow['ord-sample-1']['packageSnapshot'] = {
        'contractVersion': 2, 'inclusions': ['Digital map'], 'exclusions': [],
        'accommodation': {}, 'transport': {}, 'itineraryDays': [{'activities': ['Self-guided walk']}]}
    result = client.post('/api/fr12/bookings/ord-sample-1/confirm-fulfillment', headers=AUTH_HEADER)
    assert result.status_code == 200
    assert result.json['booking']['supplierReservationStatus'] == 'not_required'


@pytest.mark.parametrize('case', [
    ({'inclusions': ['Tour guide and admission tickets']}, 'guideActivities', True),
    ({'inclusions': ['Self-guided tour and no tickets included']}, 'guideActivities', False),
    ({'inclusions': ['Self-guided walk; entrance tickets included']}, 'guideActivities', True),
    ({'inclusions': ['Hotel accommodation included']}, 'accommodation', True),
    ({'inclusions': ['Private airport transfer']}, 'transport', True),
])
def test_only_promised_services_are_required(case):
    fields, key, required = case
    snapshot = {'accommodation': {}, 'transport': {}, **fields}
    assert derive_required_services(snapshot)[key]['required'] is required


@pytest.mark.parametrize('status', ['operator_attested', 'declined', 'not_required'])
def test_admin_projection_preserves_recorded_supplier_provenance(client, mock_admin_auth, status):
    order = _sample_order(supplierReservationStatus=status, fulfillmentStatus='trip_ready')
    with patch('modules.fr13_administrator_management.routes.retrieveRecord',
               side_effect=lambda c, *a, **k: [order] if c == 'checkout_orders' else []):
        response = client.get('/api/fr13/bookings?type=package', headers=AUTH_HEADER)
    assert response.status_code == 200
    assert response.json['items'][0]['supplierReservationStatus'] == status
