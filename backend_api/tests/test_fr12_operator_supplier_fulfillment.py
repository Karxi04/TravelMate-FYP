from copy import deepcopy
from unittest.mock import patch
import pytest

from services.package_checkout_contract import (
    derive_required_services,
    build_initial_fulfillment_record,
)


def _read_order(value):
    return lambda collection, identity=None, **kwargs: (None if collection == 'package_requirement_clarifications' else
        _trip_for(value) if collection == 'itineraries' else deepcopy(value))


AUTH_HEADER = {'Authorization': 'Bearer valid_test_token'}


def _memory_commit(store):
    """Atomic persistence double; real SDK transaction is verified separately."""
    from threading import Lock
    from services.review_service import ReviewConflict
    lock = Lock()

    def commit(document_id, expected, patch):
        with lock:
            current = store.get(document_id)
            if current != expected:
                raise ReviewConflict('Changed')
            trip = store.get(current.get('fulfilledTripId'))
            if not trip or trip.get('checkoutOrderId') != document_id:
                raise ReviewConflict('Missing linked Trip')
            updated = {**current, **deepcopy(patch)}
            store[document_id] = updated
            trip.update({k: deepcopy(updated[k]) for k in
                         ('fulfillmentStatus', 'supplierReservationStatus', 'fulfillmentRecord')})
            return deepcopy(updated)
    return commit


def _trip_for(order):
    return {'id': order['fulfilledTripId'], 'checkoutOrderId': order['id'],
            'travellerId': order['travellerId'], 'operatorId': order['operatorId']}


def _sample_order(order_ref='ord-sample-1', operator_id='test_operator_uid', **extra):
    snapshot = {
        'packageId': 'pkg-penang-heritage',
        'title': 'Penang Heritage & Beach Experience',
        'destination': 'Penang',
        'durationDays': 3,
        'durationNights': 2,
        'selectedDepartureDate': '2027-04-15',
        'accommodation': {
            'accommodationName': 'Eastern & Oriental Hotel',
            'roomType': 'Heritage Suite',
            'accommodationCategory': 'Hotel',
            'accommodationNotes': 'Includes daily breakfast for 2',
        },
        'transport': {
            'transportTypes': ['Airport Van Transfer', 'Heritage Ferry'],
            'transportNotes': 'Private air-conditioned minivan',
        },
        'inclusions': [
            '2 nights 5-star heritage hotel accommodation',
            'Licensed MOTAC English-speaking tour docent',
            'Pinang Peranakan Mansion entrance tickets',
        ],
        'itineraryDays': [
            {'dayNumber': 1, 'activities': ['Arrival and check-in', 'Evening street food walk']},
            {'dayNumber': 2, 'activities': ['Guided colonial quarter tour', 'Mansion visit']},
            {'dayNumber': 3, 'activities': ['Morning beach walk', 'Airport transfer']},
        ],
        'priceBasis': 'per_person',
        'adultUnitPrice': 650.00,
        'participants': {'adults': 2, 'children': 0, 'total': 2},
        'groupSize': 2,
        'price': 1300.00,
        'amountMinor': 130000,
        'currency': 'MYR',
    }
    initial_record = build_initial_fulfillment_record(snapshot)
    base = {
        'id': order_ref,
        'orderReference': order_ref,
        'quoteType': 'package',
        'packageId': 'pkg-penang-heritage',
        'packageTitle': snapshot['title'],
        'operatorId': operator_id,
        'travellerId': 'traveller-usr-101',
        'fulfilledTripId': 'trip-pkg-101',
        'departureDate': '2027-04-15',
        'amount': 1300.00,
        'currency': 'MYR',
        'status': 'paid',
        'paymentStatus': 'paid',
        'fulfillmentStatus': 'awaiting_operator_fulfillment',
        'supplierReservationStatus': 'not_created',
        'packageSnapshot': snapshot,
        'fulfillmentRecord': initial_record,
        'testMode': True,
        'createdAt': '2026-11-01T10:00:00Z',
        'updatedAt': '2026-11-01T10:00:00Z',
    }
    base.update(extra)
    return base


# =========================================================================
# 1. DYNAMIC SERVICE REQUIREMENT RULES
# =========================================================================

def test_derive_required_services_multi_day_package():
    snapshot = {
        'durationDays': 3,
        'durationNights': 2,
        'accommodation': {'accommodationName': 'Beach Resort', 'roomType': 'Deluxe Sea View'},
        'transport': {'transportTypes': ['Minivan']},
        'inclusions': ['Tour guide fee', 'Theme park pass'],
        'itineraryDays': [{'dayNumber': 1}],
    }
    req = derive_required_services(snapshot)
    assert req['accommodation']['required'] is True
    assert req['accommodation']['brochureName'] == 'Beach Resort'
    assert req['accommodation']['brochureRoomType'] == 'Deluxe Sea View'
    assert req['transport']['required'] is True
    assert 'Minivan' in req['transport']['brochureTypes']
    assert req['guideActivities']['required'] is True
    assert len(req['guideActivities']['inclusions']) == 2


def test_derive_required_services_single_day_walking_tour():
    snapshot = {
        'durationDays': 1,
        'durationNights': 0,
        'accommodation': {},
        'transport': {'transportTypes': []},
        'inclusions': ['Licensed English-speaking tour docent'],
        'itineraryDays': [{'dayNumber': 1, 'activities': ['Walking tour']}],
    }
    req = derive_required_services(snapshot)
    assert req['accommodation']['required'] is False
    assert req['transport']['required'] is False
    assert req['guideActivities']['required'] is True


def test_derive_required_services_self_guided_single_day():
    snapshot = {
        'durationDays': 1,
        'durationNights': 0,
        'accommodation': {},
        'transport': {},
        'inclusions': [],
        'itineraryDays': [],
    }
    req = derive_required_services(snapshot)
    assert req['accommodation']['required'] is False
    assert req['transport']['required'] is False
    assert req['guideActivities']['required'] is False


# =========================================================================
# 2. COMPONENT ATTESTATION WORKFLOW
# =========================================================================

def test_operator_attests_accommodation_component(client, mock_operator_auth):
    store = {}
    order = _sample_order()
    store[order['id']] = deepcopy(order)
    store[order['fulfilledTripId']] = _trip_for(order)

    def mock_retrieve(col, doc_id=None, **k):
        if doc_id:
            return None if col == 'package_requirement_clarifications' else deepcopy(store.get(doc_id))
        return list(store.values())

    def mock_update(col, doc_id, data):
        store.setdefault(doc_id, {})
        store[doc_id].update(deepcopy(data))
        return deepcopy(store[doc_id])

    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', side_effect=mock_retrieve), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord', side_effect=mock_update), \
         patch('modules.fr12_tourism_operator_management.routes.commitPackageFulfillment', side_effect=_memory_commit(store)):

        payload = {
            'serviceType': 'accommodation',
            'supplierName': 'Eastern & Oriental Hotel',
            'reference': 'EO-PEN-88992',
            'notes': 'Late check-in requested for 22:00',
        }
        res = client.post(
            f"/api/fr12/bookings/{order['id']}/fulfillment",
            headers=AUTH_HEADER,
            json=payload,
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        booking = data['booking']
        assert booking['fulfillmentStatus'] == 'partially_fulfilled'

        ful = booking['fulfillmentRecord']
        accom = ful['services']['accommodation']
        assert accom['status'] == 'confirmed'
        assert accom['reference'] == 'EO-PEN-88992'
        assert accom['supplierName'] == 'Eastern & Oriental Hotel'
        assert accom['provenance'] == 'operator_attested'
        assert accom['confirmedBy'] == 'test_operator_uid'
        assert accom['confirmedAt'] is not None


def test_attestation_validation_rejects_missing_reference_or_bad_type(client, mock_operator_auth):
    order = _sample_order()
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', side_effect=_read_order(order)):
        # Missing reference
        res1 = client.post(
            f"/api/fr12/bookings/{order['id']}/fulfillment",
            headers=AUTH_HEADER,
            json={'serviceType': 'accommodation', 'reference': ''},
        )
        assert res1.status_code == 400
        assert 'reference is required' in res1.get_json()['error']

        # Invalid service type
        res2 = client.post(
            f"/api/fr12/bookings/{order['id']}/fulfillment",
            headers=AUTH_HEADER,
            json={'serviceType': 'spaceship', 'reference': 'REF-123'},
        )
        assert res2.status_code == 400
        assert 'Invalid serviceType' in res2.get_json()['error']


# =========================================================================
# 3. CONFIRMATION GATE (TRIP READY)
# =========================================================================

def test_confirmation_gate_blocks_when_required_services_incomplete(client, mock_operator_auth):
    order = _sample_order()
    # Accommodation and transport are required, but neither is confirmed yet
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', side_effect=_read_order(order)):
        res = client.post(
            f"/api/fr12/bookings/{order['id']}/confirm-fulfillment",
            headers=AUTH_HEADER,
        )
        assert res.status_code == 400
        error_msg = res.get_json()['error']
        assert 'arrangements have not been attested' in error_msg


def test_confirmation_gate_succeeds_when_all_required_attested(client, mock_operator_auth):
    store = {}
    order = _sample_order()
    # Complete all 3 required services
    ful = order['fulfillmentRecord']
    now = '2026-11-01T11:00:00Z'
    for k in ('accommodation', 'transport', 'guideActivities'):
        ful['services'][k].update({
            'status': 'confirmed',
            'reference': f'REF-{k.upper()}-001',
            'providerName': 'Synthetic Fleet',
            'provenance': 'operator_attested',
            'confirmedBy': 'test_operator_uid',
            'confirmedAt': now,
        })
    order['fulfillmentStatus'] = 'partially_fulfilled'
    store[order['id']] = deepcopy(order)
    store['trip-pkg-101'] = {**_trip_for(order), 'supplierReservationStatus': 'not_created'}

    def mock_retrieve(col, doc_id=None, **k):
        if doc_id:
            return None if col == 'package_requirement_clarifications' else deepcopy(store.get(doc_id))
        return list(store.values())

    def mock_update(col, doc_id, data):
        store.setdefault(doc_id, {})
        store[doc_id].update(deepcopy(data))
        return deepcopy(store[doc_id])

    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', side_effect=mock_retrieve), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord', side_effect=mock_update), \
         patch('modules.fr12_tourism_operator_management.routes.commitPackageFulfillment', side_effect=_memory_commit(store)):

        res = client.post(
            f"/api/fr12/bookings/{order['id']}/confirm-fulfillment",
            headers=AUTH_HEADER,
        )
        assert res.status_code == 200
        booking = res.get_json()['booking']
        assert booking['fulfillmentStatus'] == 'trip_ready'
        assert booking['supplierReservationStatus'] == 'operator_attested'
        assert booking['fulfillmentRecord']['status'] == 'trip_ready'

        # Check itinerary was updated
        assert store['trip-pkg-101']['supplierReservationStatus'] == 'operator_attested'
        assert store['trip-pkg-101']['fulfillmentStatus'] == 'trip_ready'


# =========================================================================
# 4. AUTHORIZATION & ACCESS CONTROL
# =========================================================================

def test_unowned_booking_fulfillment_rejected(client, mock_operator_auth):
    order = _sample_order(operator_id='another_operator_uid')
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', side_effect=_read_order(order)):
        res = client.post(
            f"/api/fr12/bookings/{order['id']}/fulfillment",
            headers=AUTH_HEADER,
            json={'serviceType': 'accommodation', 'reference': 'REF-123'},
        )
        assert res.status_code == 403


def test_unpaid_booking_fulfillment_rejected(client, mock_operator_auth):
    order = _sample_order(status='checkout_open', paymentStatus='unpaid')
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', side_effect=_read_order(order)):
        res = client.post(
            f"/api/fr12/bookings/{order['id']}/fulfillment",
            headers=AUTH_HEADER,
            json={'serviceType': 'accommodation', 'reference': 'REF-123'},
        )
        assert res.status_code == 400
        assert 'unpaid' in res.get_json()['error']


# =========================================================================
# 5. DECLINE WORKFLOW
# =========================================================================

def test_decline_workflow_requires_detailed_reason_and_updates_status(client, mock_operator_auth):
    store = {}
    order = _sample_order()
    store[order['id']] = deepcopy(order)
    store['trip-pkg-101'] = _trip_for(order)

    def mock_retrieve(col, doc_id=None, **k):
        if doc_id:
            return None if col == 'package_requirement_clarifications' else deepcopy(store.get(doc_id))
        return list(store.values())

    def mock_update(col, doc_id, data):
        store.setdefault(doc_id, {})
        store[doc_id].update(deepcopy(data))
        return deepcopy(store[doc_id])

    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', side_effect=mock_retrieve), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord', side_effect=mock_update), \
         patch('modules.fr12_tourism_operator_management.routes.commitPackageFulfillment', side_effect=_memory_commit(store)):

        # Short reason fails
        res_short = client.post(
            f"/api/fr12/bookings/{order['id']}/decline",
            headers=AUTH_HEADER,
            json={'reason': 'No'},
        )
        assert res_short.status_code == 400
        assert 'at least 5 characters' in res_short.get_json()['error']

        # Valid reason succeeds
        reason_text = 'Partner hotel fully booked, unable to secure heritage rooms.'
        res_valid = client.post(
            f"/api/fr12/bookings/{order['id']}/decline",
            headers=AUTH_HEADER,
            json={'reason': reason_text},
        )
        assert res_valid.status_code == 200
        booking = res_valid.get_json()['booking']
        assert booking['fulfillmentStatus'] == 'fulfillment_declined'
        assert booking['supplierReservationStatus'] == 'declined'
        assert booking['fulfillmentRecord']['declineReason'] == reason_text
        assert store['trip-pkg-101']['supplierReservationStatus'] == 'declined'
