from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services.liteapi_service import (
    ProviderMutationBlocked,
    createBookingReference,
    normalizeHotelOffers,
)
from services.transaction_reliability import operation_document_id
from test_fr08_fr09_hotels_payments import MemoryPersistence


AUTH = {'Authorization': 'Bearer valid_test_token'}
FUTURE = '2099-01-01T00:00:00+00:00'


def _search_payload(**overrides):
    payload = {
        'destination': 'Penang',
        'checkin': '2026-11-10',
        'checkout': '2026-11-12',
        'adults': 2,
        'roomQuantity': 1,
    }
    payload.update(overrides)
    return payload


def _normalised_offer(occupancies):
    return {
        'hotelId': 'hotel_18b',
        'offerId': 'offer_18b',
        'name': 'Penang Test Hotel',
        'price': 420.0,
        'priceStatus': 'available',
        'priceBasis': 'stay_total',
        'currency': 'MYR',
        'currencyStatus': 'known',
        'taxesAndFeesStatus': 'included',
        'cancellation': {'tag': 'RFN', 'status': 'known'},
        'occupancyBreakdown': [
            {
                'occupancyNumber': index,
                'adultCount': room['adults'],
                'childrenAges': room.get('children', []),
                'maxOccupancy': 4,
            }
            for index, room in enumerate(occupancies, start=1)
        ],
    }


def _hotel_patches(memory):
    return (
        patch('modules.fr08_hotel_booking.routes.claimRecord', side_effect=memory.claim),
        patch('modules.fr08_hotel_booking.routes.retrieveRecord', side_effect=memory.retrieve),
        patch('modules.fr08_hotel_booking.routes.updateRecord', side_effect=memory.update),
    )


def _payment_patches(memory):
    return (
        patch('modules.fr09_payment.routes.claimRecord', side_effect=memory.claim),
        patch('modules.fr09_payment.routes.retrieveRecord', side_effect=memory.retrieve),
        patch('modules.fr09_payment.routes.updateRecord', side_effect=memory.update),
    )


def _seed_quote(memory, *, owner='test_traveller_uid', expires_at=FUTURE):
    memory.seed('hotel_offer_quotes', f'{owner}_quote_18b', {
        'quoteId': 'quote_18b',
        'travellerId': owner,
        'expiresAt': expires_at,
        'offer': _normalised_offer([{'adults': 2}]),
        'criteria': {
            'destination': 'Penang',
            'checkin': '2026-11-10',
            'checkout': '2026-11-12',
            'roomQuantity': 1,
            'occupancies': [{'adults': 2}],
            'guestCount': 2,
        },
    })


def _accepted_record(**snapshot_overrides):
    snapshot = {
        'id': 'accepted_18b',
        'status': 'accepted',
        'travellerId': 'test_traveller_uid',
        'provider': 'liteapi',
        'transactionMode': 'provider_sandbox',
        'supplierBookingStatus': 'not_created',
        'hotelBookingAttemptId': 'hotel_attempt_18b',
        'quoteId': 'quote_18b',
        'hotelId': 'hotel_18b',
        'offerId': 'offer_18b',
        'prebookId': 'prebook_18b',
        'checkin': '2026-11-10',
        'checkout': '2026-11-12',
        'roomQuantity': 1,
        'occupancies': [{'adults': 2}],
        'guestCount': 2,
        'amount': 425.0,
        'currency': 'MYR',
        'priceBasis': 'stay_total',
        'taxesAndFeesStatus': 'included',
        'cancellation': {'tag': 'RFN', 'status': 'known'},
        'expiresAt': FUTURE,
    }
    snapshot.update(snapshot_overrides)
    return {
        'travellerId': 'test_traveller_uid',
        'status': 'succeeded',
        'criteria': {
            key: deepcopy(snapshot[key])
            for key in ('checkin', 'checkout', 'roomQuantity', 'occupancies')
        },
        'validatedOffer': {
            'offerId': snapshot['offerId'],
            'price': snapshot['amount'],
            'currency': snapshot['currency'],
        },
        'acceptedPrebookSnapshot': snapshot,
    }


def _checkout_payload(attempt='checkout_18b'):
    return {
        'orderAttemptId': attempt,
        'quoteType': 'hotel',
        'quoteId': 'quote_18b',
        'offerId': 'offer_18b',
        'acceptedPrebookSnapshotId': 'accepted_18b',
        'amount': 0.01,
    }


@pytest.mark.parametrize('occupancies', [
    [{'adults': 2}],
    [{'adults': 2, 'children': [8]}, {'adults': 2, 'children': [12]}],
])
def test_search_sends_exact_room_occupancies_and_persists_ttl(
        client, mock_traveller_auth, occupancies):
    memory = MemoryPersistence()
    provider = {'data': [], 'sandbox': True}
    offer = _normalised_offer(occupancies)
    payload = _search_payload(
        roomQuantity=len(occupancies),
        adults=sum(room['adults'] for room in occupancies),
        children=sum(len(room.get('children', [])) for room in occupancies),
        occupancies=occupancies,
    )
    patches = _hotel_patches(memory)
    with patches[0], patches[1], patches[2], \
            patch('modules.fr08_hotel_booking.routes.retrieveHotelOffers', return_value=provider) as search, \
            patch('modules.fr08_hotel_booking.routes.normalizeHotelOffers', return_value=[offer]):
        response = client.post('/api/fr8/hotels/search', headers=AUTH, json=payload)

    assert response.status_code == 200
    assert search.call_args.args[0]['occupancies'] == occupancies
    item = response.get_json()['items'][0]
    assert item['occupancyValidationStatus'] == 'verified'
    assert item['quoteExpiresAt']
    stored = next(iter(memory.collections['hotel_offer_quotes'].values()))
    assert stored['criteria']['occupancies'] == occupancies
    assert stored['expiresAt'] == item['quoteExpiresAt']


@pytest.mark.parametrize(('overrides', 'message'), [
    ({'roomQuantity': 2, 'adults': 4}, 'Room-by-room occupancy'),
    ({'children': 1, 'childAges': None}, 'one age for every child'),
    ({'roomQuantity': 2, 'adults': 5,
      'occupancies': [{'adults': 2}, {'adults': 2}]}, 'Total adults'),
    ({'roomQuantity': 2, 'adults': 4, 'children': 2,
      'occupancies': [{'adults': 2, 'children': [8]}, {'adults': 2}]},
     'Total children'),
    ({'roomQuantity': 2, 'adults': 4,
      'occupancies': [{'adults': 2}]}, 'exactly one occupancy'),
    ({'checkout': '2026-11-10'}, 'Check-out must be after'),
])
def test_invalid_or_ambiguous_guest_contract_is_rejected(
        client, mock_traveller_auth, overrides, message):
    with patch('modules.fr08_hotel_booking.routes.retrieveHotelOffers') as search:
        response = client.post(
            '/api/fr8/hotels/search', headers=AUTH,
            json=_search_payload(**overrides),
        )
    assert response.status_code == 400
    assert response.get_json()['status'] == 'invalid_occupancy'
    assert message in response.get_json()['error']
    search.assert_not_called()


def test_provider_occupancy_mismatch_is_not_returned(
        client, mock_traveller_auth):
    memory = MemoryPersistence()
    requested = [{'adults': 2}, {'adults': 2}]
    mismatched = _normalised_offer(requested)
    mismatched['occupancyBreakdown'][1]['maxOccupancy'] = 1
    patches = _hotel_patches(memory)
    with patches[0], patches[1], patches[2], \
            patch('modules.fr08_hotel_booking.routes.retrieveHotelOffers',
                  return_value={'data': [], 'sandbox': True}), \
            patch('modules.fr08_hotel_booking.routes.normalizeHotelOffers',
                  return_value=[mismatched]):
        response = client.post('/api/fr8/hotels/search', headers=AUTH, json={
            **_search_payload(roomQuantity=2, adults=4),
            'occupancies': requested,
        })
    assert response.status_code == 200
    assert response.get_json()['items'] == []


def test_liteapi_normalizer_preserves_each_rate_occupancy():
    items = normalizeHotelOffers({'data': [{
        'hotelId': 'hotel_18b',
        'roomTypes': [{
            'offerId': 'offer_18b',
            'offerRetailRate': {'amount': 420, 'currency': 'MYR'},
            'rates': [
                {'occupancyNumber': 1, 'adultCount': 2, 'childCount': 1,
                 'childrenAges': [8], 'maxOccupancy': 3,
                 'retailRate': {'taxesAndFees': [{
                     'name': 'Tax', 'amount': 10, 'currency': 'MYR',
                     'included': True,
                 }]}},
                {'occupancyNumber': 2, 'adultCount': 2, 'childCount': 1,
                 'childrenAges': [12], 'maxOccupancy': 3},
            ],
        }],
    }]})
    assert items[0]['occupancyBreakdown'] == [
        {'occupancyNumber': 1, 'rateId': None, 'mappedRoomId': None,
         'adultCount': 2, 'childCount': 1, 'childrenAges': [8], 'maxOccupancy': 3},
        {'occupancyNumber': 2, 'rateId': None, 'mappedRoomId': None,
         'adultCount': 2, 'childCount': 1, 'childrenAges': [12], 'maxOccupancy': 3},
    ]
    assert items[0]['taxesAndFees'] == [{
        'name': 'Tax', 'amount': 10.0, 'currency': 'MYR', 'included': True,
    }]


@pytest.mark.parametrize(('owner', 'expires_at', 'status'), [
    ('other_traveller', FUTURE, 400),
    ('test_traveller_uid', '2020-01-01T00:00:00+00:00', 409),
])
def test_foreign_or_expired_quote_cannot_be_prebooked(
        client, mock_traveller_auth, owner, expires_at, status):
    memory = MemoryPersistence()
    _seed_quote(memory, owner=owner, expires_at=expires_at)
    patches = _hotel_patches(memory)
    with patches[0], patches[1], patches[2], \
            patch('modules.fr08_hotel_booking.routes.validateHotelOffer') as validate:
        response = client.post('/api/fr8/hotels/prebook', headers=AUTH, json={
            'offerId': 'offer_18b', 'quoteId': 'quote_18b',
            'hotelBookingAttemptId': 'prebook_attempt_18b',
        })
    assert response.status_code == status
    validate.assert_not_called()


def test_repriced_offer_requires_acceptance_and_snapshot_is_preserved(
        client, mock_traveller_auth):
    memory = MemoryPersistence()
    _seed_quote(memory)
    validated = {
        'prebookId': 'prebook_18b', 'offerId': 'offer_18b',
        'status': 'prebooked', 'price': 425, 'currency': 'MYR',
        'priceBasis': 'stay_total', 'taxesAndFeesStatus': 'included',
        'cancellation': {'tag': 'RFN', 'status': 'known'},
    }
    patches = _hotel_patches(memory)
    request = {
        'offerId': 'offer_18b', 'quoteId': 'quote_18b',
        'hotelBookingAttemptId': 'prebook_attempt_18b',
    }
    with patch.dict('os.environ', {'LITEAPI_KEY': 'test-fixture'}), \
            patches[0], patches[1], patches[2], \
            patch('modules.fr08_hotel_booking.routes.validateHotelOffer',
                  return_value=validated):
        changed = client.post('/api/fr8/hotels/prebook', headers=AUTH, json=request)
        assert changed.status_code == 409
        assert changed.get_json()['status'] == 'reprice_required'
        accepted = client.post('/api/fr8/hotels/prebook', headers=AUTH, json={
            **request, 'acceptedQuoteVersion': changed.get_json()['quoteVersion'],
        })
        document = next(iter(memory.collections['hotel_prebook_attempts'].values()))
        immutable = deepcopy(document['acceptedPrebookSnapshot'])
        document['validatedOffer']['price'] = 999
        reused = client.post('/api/fr8/hotels/prebook', headers=AUTH, json=request)

    assert accepted.status_code == reused.status_code == 200
    assert immutable['amount'] == 425
    assert document['acceptedPrebookSnapshot'] == immutable
    assert reused.get_json()['acceptedPrebook']['amount'] == 425


def test_checkout_uses_accepted_amount_and_duplicate_is_idempotent(
        client, mock_traveller_auth):
    memory = MemoryPersistence()
    memory.seed('hotel_prebook_attempts', 'accepted_18b', _accepted_record())
    session = SimpleNamespace(id='cs_18b', url='https://checkout.stripe.test/cs_18b')
    patches = _payment_patches(memory)
    with patch.dict('os.environ', {'STRIPE_SECRET_KEY': 'sk_test_fixture'}), \
            patches[0], patches[1], patches[2], \
            patch('modules.fr09_payment.routes.createCheckoutSession',
                  return_value=session) as create, \
            patch('modules.fr09_payment.routes.retrieveCheckoutSession',
                  return_value=SimpleNamespace(
                      status='open', payment_status='unpaid',
                      amount_total=42500, currency='myr', payment_intent=None)):
        first = client.post('/api/fr9/checkout/session', headers=AUTH,
                            json=_checkout_payload())
        duplicate = client.post('/api/fr9/checkout/session', headers=AUTH,
                                json=_checkout_payload())

    assert first.status_code == duplicate.status_code == 200
    assert first.get_json()['order']['amount'] == 425.0
    assert create.call_args.args[0:2] == (425.0, 'MYR')
    assert create.call_count == 1
    assert duplicate.get_json()['reused'] is True


@pytest.mark.parametrize(('snapshot_overrides', 'record_patch', 'message'), [
    ({'expiresAt': '2020-01-01T00:00:00+00:00'}, {}, 'expired'),
    ({'currency': 'USD'}, {}, 'validated MYR'),
    ({'amount': 426.0}, {'validatedOffer': {
        'offerId': 'offer_18b', 'price': 425.0, 'currency': 'MYR'}},
     'no longer matches'),
    ({'travellerId': 'other_traveller'}, {}, 'not eligible'),
])
def test_checkout_fails_closed_for_stale_mismatched_or_foreign_snapshot(
        client, mock_traveller_auth, snapshot_overrides, record_patch, message):
    memory = MemoryPersistence()
    record = _accepted_record(**snapshot_overrides)
    record.update(record_patch)
    memory.seed('hotel_prebook_attempts', 'accepted_18b', record)
    patches = _payment_patches(memory)
    with patches[0], patches[1], patches[2], \
            patch('modules.fr09_payment.routes.createCheckoutSession') as create:
        response = client.post('/api/fr9/checkout/session', headers=AUTH,
                               json=_checkout_payload())
    assert response.status_code == 409
    assert message in response.get_json()['error']
    create.assert_not_called()
    assert 'checkout_orders' not in memory.collections


def test_legacy_hotel_checkout_cannot_bypass_accepted_prebook(
        client, mock_traveller_auth):
    memory = MemoryPersistence()
    _seed_quote(memory)
    patches = _payment_patches(memory)
    payload = _checkout_payload()
    payload.pop('acceptedPrebookSnapshotId')
    with patches[0], patches[1], patches[2], \
            patch('modules.fr09_payment.routes.createCheckoutSession') as create:
        response = client.post('/api/fr9/checkout/session', headers=AUTH, json=payload)
    assert response.status_code == 409
    assert 'accepted hotel prebook snapshot' in response.get_json()['error']
    create.assert_not_called()


def test_real_supplier_booking_remains_disabled_outside_tests():
    with patch.dict('os.environ', {'TRAVELMATE_TESTING': 'false'}, clear=False), \
            patch('services.liteapi_service.requests.post') as provider:
        with pytest.raises(ProviderMutationBlocked):
            createBookingReference({'prebookId': 'prebook_18b'})
    provider.assert_not_called()


def test_historical_prebook_recovery_anchors_timestamp_and_marks_expired(
        client, mock_traveller_auth):
    memory = MemoryPersistence()
    _seed_quote(memory)
    historical_time = '2026-10-18T10:00:00+00:00'
    op_id = operation_document_id('hotel_prebook', 'test_traveller_uid', 'historical_attempt_18b')
    historical_doc = {
        'id': op_id,
        'travellerId': 'test_traveller_uid',
        'hotelBookingAttemptId': 'historical_attempt_18b',
        'offerId': 'offer_18b',
        'quoteId': 'quote_18b',
        'status': 'succeeded',
        'stage': 'validated_local_demo',
        'createdAt': historical_time,
        'updatedAt': historical_time,
        'criteria': {
            'checkin': '2026-11-10',
            'checkout': '2026-11-12',
            'roomQuantity': 1,
            'occupancies': [{'adults': 2}],
            'guestCount': 2,
        },
        'validatedOffer': {
            'offerId': 'offer_18b',
            'hotelId': 'hotel_18b',
            'name': 'Penang Test Hotel',
            'price': 420.0,
            'currency': 'MYR',
            'priceBasis': 'stay_total',
            'taxesAndFeesStatus': 'included',
        },
    }
    memory.seed('hotel_prebook_attempts', op_id, historical_doc)

    patches = _hotel_patches(memory)
    with patches[0], patches[1], patches[2]:
        response = client.post('/api/fr8/hotels/prebook', headers=AUTH, json={
            'offerId': 'offer_18b',
            'quoteId': 'quote_18b',
            'hotelBookingAttemptId': 'historical_attempt_18b',
        })

    assert response.status_code == 200
    data = response.get_json()
    assert data['ok'] is True
    assert data['reused'] is True
    accepted = data['acceptedPrebook']
    assert accepted is not None
    assert accepted['status'] == 'expired'
    assert accepted['checkoutEligible'] is False
    assert accepted['expiresAt'] == '2026-10-18T10:15:00+00:00'

    pay_patches = _payment_patches(memory)
    with pay_patches[0], pay_patches[1], pay_patches[2]:
        checkout_resp = client.post('/api/fr9/checkout/session', headers=AUTH, json={
            'orderAttemptId': 'order_hist_18b',
            'quoteType': 'hotel',
            'quoteId': 'quote_18b',
            'offerId': 'offer_18b',
            'acceptedPrebookSnapshotId': op_id,
            'amount': 420.0,
        })
    assert checkout_resp.status_code == 409
    assert 'expired' in checkout_resp.get_json()['error']


def test_prebook_attempt_reuse_rejects_different_quote_id(
        client, mock_traveller_auth):
    memory = MemoryPersistence()
    _seed_quote(memory)
    memory.seed('hotel_offer_quotes', 'test_traveller_uid_quote_second', {
        'quoteId': 'quote_second',
        'travellerId': 'test_traveller_uid',
        'expiresAt': FUTURE,
        'offer': _normalised_offer([{'adults': 2}]),
        'criteria': {
            'destination': 'Penang',
            'checkin': '2026-11-10',
            'checkout': '2026-11-12',
            'roomQuantity': 1,
            'occupancies': [{'adults': 2}],
            'guestCount': 2,
        },
    })
    op_id = operation_document_id('hotel_prebook', 'test_traveller_uid', 'attempt_bound')
    memory.seed('hotel_prebook_attempts', op_id, {
        'id': op_id,
        'travellerId': 'test_traveller_uid',
        'hotelBookingAttemptId': 'attempt_bound',
        'offerId': 'offer_18b',
        'quoteId': 'quote_18b',
        'status': 'succeeded',
    })

    patches = _hotel_patches(memory)
    with patches[0], patches[1], patches[2]:
        response = client.post('/api/fr8/hotels/prebook', headers=AUTH, json={
            'offerId': 'offer_18b',
            'quoteId': 'quote_second',
            'hotelBookingAttemptId': 'attempt_bound',
        })
    assert response.status_code == 409
    assert 'already bound to another quote' in response.get_json()['error']


def test_prebook_attempt_foreign_traveller_is_blocked(
        client, mock_traveller_auth):
    memory = MemoryPersistence()
    _seed_quote(memory)
    op_id = operation_document_id('hotel_prebook', 'test_traveller_uid', 'foreign_attempt')
    memory.seed('hotel_prebook_attempts', op_id, {
        'id': op_id,
        'travellerId': 'different_traveller_uid',
        'hotelBookingAttemptId': 'foreign_attempt',
        'offerId': 'offer_18b',
        'quoteId': 'quote_18b',
        'status': 'succeeded',
    })

    patches = _hotel_patches(memory)
    with patches[0], patches[1], patches[2]:
        response = client.post('/api/fr8/hotels/prebook', headers=AUTH, json={
            'offerId': 'offer_18b',
            'quoteId': 'quote_18b',
            'hotelBookingAttemptId': 'foreign_attempt',
        })
    assert response.status_code == 404
    assert 'Prebook attempt not found' in response.get_json()['error']

