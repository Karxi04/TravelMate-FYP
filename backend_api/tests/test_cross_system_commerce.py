"""Synthetic commerce contracts: no Firebase, Stripe or supplier network calls."""
from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services.campaign_schedule import campaign_schedule_error, malaysia_today
from services.package_checkout_contract import prepare_package_snapshot
from services.public_content_projection import active_campaign
from test_package_checkout_contract import package
from test_fr15_package_checkout_stripe import package_payment  # noqa: F401


NOW = '2026-11-08T10:00:00+00:00'


def campaign(**changes):
    return {'id': 'c1', 'operatorId': 'op1', 'packageId': 'p1', 'campaignTitle': 'November offer',
            'reviewStatus': 'approved', 'campaignStatus': 'approved',
            'startDate': '2026-11-08', 'endDate': '2026-11-09',
            'discountType': 'percentage', 'discountValue': 15, **changes}


@pytest.mark.parametrize(('kind', 'value', 'basis', 'expected'), [
    ('percentage', 15, 'per_person', 340), ('fixed', 60, 'per_person', 340),
    ('percentage', 15, 'per_group', 85), ('fixed', 15, 'per_group', 85),
])
def test_discount_uses_original_party_subtotal(kind, value, basis, expected):
    snapshot = prepare_package_snapshot(package(childPrice=100, priceBasis=basis), {'id': 'op1'}, now=NOW,
        participants={'adults': 2, 'children': 2}, campaigns=[campaign(discountType=kind, discountValue=value)])
    assert snapshot['price'] == expected
    assert snapshot['amountMinor'] == expected * 100
    assert snapshot['pricingBreakdown']['finalPayable'] == expected
    assert snapshot['pricingBreakdown']['originalSubtotal'] == (400 if basis == 'per_person' else 100)
    assert snapshot['groupSize'] == 4


@pytest.mark.parametrize('changes', [
    {'reviewStatus': 'rejected'}, {'reviewStatus': 'pending'}, {'campaignStatus': 'draft'},
    {'packageId': 'other'}, {'operatorId': 'other'}, {'startDate': '2026-11-09'},
    {'endDate': '2026-11-07'}, {'startDate': 'bad'}, {'endDate': ''},
    {'discountValue': -1}, {'discountValue': 'NaN'}, {'discountValue': 'Infinity'},
    {'discountValue': 101}, {'discountType': 'invented'},
    {'promoCode': 'REQUIRED'},
])
def test_ineligible_campaign_never_changes_price(changes):
    snapshot = prepare_package_snapshot(package(), {'id': 'op1'}, now=NOW, campaigns=[campaign(**changes)])
    assert snapshot['amountMinor'] == 10000
    assert snapshot['pricingBreakdown']['promotionDiscount'] == 0


def test_code_validation_and_non_stacking():
    raw = package(promotionalPrice=80, promotionStart='2026-11-01', promotionEnd='2026-11-30')
    snapshot = prepare_package_snapshot(raw, {'id': 'op1'}, now=NOW, promo_code=' save ',
        campaigns=[campaign(promoCode='SAVE'), campaign(id='c2', discountType='fixed', discountValue=30)])
    assert snapshot['price'] == 70  # best single offer, not 80 minus 30
    assert snapshot['pricingBreakdown']['promotion']['id'] == 'c2'
    with pytest.raises(ValueError, match='Promo code'):
        prepare_package_snapshot(raw, {'id': 'op1'}, now=NOW, promo_code='WRONG', campaigns=[campaign(promoCode='SAVE')])


def test_malaysia_midnight_and_historical_schedule():
    assert malaysia_today('2026-11-07T16:00:00Z') == date(2026, 11, 8)
    assert malaysia_today('2026-11-07T15:59:59Z') == date(2026, 11, 7)
    old = campaign(startDate='2020-01-01', endDate='2020-02-01')
    assert campaign_schedule_error(old, new=True, now=NOW)
    assert campaign_schedule_error(old, previous=old, now=NOW) is None
    assert campaign_schedule_error(old, publishing=True, now=NOW)
    assert campaign_schedule_error(campaign(endDate='2026-11-07'), new=True, now=NOW)
    assert active_campaign(campaign(), malaysia_today(NOW))


@pytest.mark.parametrize(('instant', 'expected'), [('2026-11-07T15:59:59Z', 100), ('2026-11-07T16:00:00Z', 80)])
def test_brochure_price_uses_same_malaysia_day_as_campaigns(instant, expected):
    snapshot = prepare_package_snapshot(package(promotionalPrice=80, promotionStart='2026-11-08', promotionEnd='2026-11-08'),
                                        {'id':'op1'}, now=instant)
    assert snapshot['price'] == expected


@pytest.mark.parametrize(('record', 'expected'), [
    ({'hotelCost': 105.24, 'hotelCurrency': 'MYR'}, (105.24, 'MYR')),
    ({'hotelCost': 105.24, 'hotelCurrency': 'MYR', 'currency': 'USD'}, (105.24, 'MYR')),
    ({'amount': 105.24, 'currency': 'USD', 'hotelCurrency': 'MYR'}, (105.24, 'USD')),
    ({'amount': 105.24}, (105.24, 'UNKNOWN')),
    ({'amount': 105.24, 'packageSnapshot': {'price': 105.24, 'currency': 'MYR'}}, (105.24, 'MYR')),
    ({'amount': 105.24, 'packageSnapshot': {'price': 999, 'currency': 'MYR'}}, (105.24, 'UNKNOWN')),
])
def test_currency_is_paired_with_recorded_amount(record, expected):
    from modules.fr13_administrator_management.routes import _record_money
    before = deepcopy(record)
    assert _record_money(record) == expected
    assert record == before


def test_currency_join_requires_link_owner_and_matching_amount():
    from modules.fr13_administrator_management.routes import _record_money
    record = {'orderId': 'o', 'travellerId': 't', 'amount': 105.24}
    orders = {'o': {'travellerId': 't', 'amount': 105.24, 'currency': 'MYR'}}
    assert _record_money(record, orders) == (105.24, 'MYR')
    orders['o']['travellerId'] = 'someone-else'
    assert _record_money(record, orders) == (105.24, 'UNKNOWN')


@pytest.mark.parametrize(('kind', 'value'), [('percentage', 100), ('fixed', 100), ('fixed', 101)])
def test_free_or_over_subtotal_discounts_cannot_silently_charge_full_price(kind, value):
    with pytest.raises(ValueError, match='Free package checkout is not supported'):
        prepare_package_snapshot(package(), {'id':'op1'}, now=NOW, campaigns=[campaign(discountType=kind, discountValue=value)])


@pytest.mark.parametrize(('kind', 'value'), [('percentage', 15), ('fixed', 60)])
def test_same_promoted_transaction_stripe_and_all_role_projections(client, package_payment, monkeypatch, kind, value):
    memory, headers = package_payment
    memory.seed('users', 'op1', {'role': 'operator', 'status': 'active', 'verificationStatus': 'approved'})
    memory.seed('users', 'a1', {'role': 'admin', 'status': 'active'})
    memory.seed('tourism_packages', 'p1', package(adultPrice=200))
    for module in ('fr15_package_checkout', 'fr12_tourism_operator_management', 'fr13_administrator_management'):
        monkeypatch.setattr(f'modules.{module}.routes.retrieveRecord', memory.retrieve)
    monkeypatch.setattr('modules.fr15_package_checkout.routes.claimRecord', memory.claim)
    for module in ('fr12_tourism_operator_management', 'fr13_administrator_management'):
        monkeypatch.setattr(f'modules.{module}.routes.updateRecord', memory.update)
    def store(collection, data):
        cid = data.get('id') or 'created-campaign'
        memory.seed(collection, cid, data)
        return memory.retrieve(collection, cid)
    monkeypatch.setattr('modules.fr12_tourism_operator_management.routes.storeRecord', store)
    op_headers = {'Authorization': 'Bearer op1'}
    admin_headers = {'Authorization': 'Bearer a1'}
    payload = {'campaignTitle':'November offer', 'packageId':'p1', 'startDate':malaysia_today().isoformat(),
               'endDate':'2099-01-01', 'discountType':kind, 'discountValue':value}
    created = client.post('/api/fr12/campaigns', headers=op_headers, json=payload)
    assert created.status_code == 201, created.get_json()
    cid = created.get_json()['id']
    submitted = client.post(f'/api/fr12/campaigns/{cid}/submit', headers=op_headers, json={})
    assert submitted.status_code == 200, submitted.get_json()
    approved = client.post(f'/api/fr13/campaigns/{cid}/review', headers=admin_headers, json={'decision':'approved'})
    assert approved.status_code == 200, approved.get_json()
    from services.public_content_projection import public_package
    public = public_package(memory.retrieve('tourism_packages', 'p1'), campaigns=[approved.get_json()['campaign']])
    assert public['activeCampaigns'][0]['discountValue'] == value
    attempt = client.post('/api/fr15/package-checkout-attempts', headers=headers,
        json={'packageId': 'p1', 'participants': {'adults': 2}, 'idempotencyKey': 'cross-role', 'amount': 1}).get_json()['attempt']
    assert attempt['amount'] == 340
    provider = SimpleNamespace(id='cs_synthetic', url='https://checkout.stripe.test/synthetic', status='open', payment_status='unpaid')
    with patch('modules.fr09_payment.routes.createCheckoutSession', return_value=provider) as stripe:
        response = client.post(f"/api/fr9/package-checkout-attempts/{attempt['id']}/checkout/session", headers=headers, json={})
    assert response.status_code == 200, response.get_json()
    assert stripe.call_args.args[:2] == (340, 'MYR')
    order_id = response.get_json()['order']['id']
    # Payment verification itself has dedicated signature/idempotency suites; seed only this fixture's result.
    memory.update('checkout_orders', order_id, {'status': 'paid', 'paymentStatus': 'paid', 'testMode': True,
        'fulfilledTripId': 'package-trip-1', 'fulfillmentStatus': 'awaiting_operator_fulfillment', 'supplierReservationStatus': 'not_created'})
    persisted = deepcopy(memory.collections['checkout_orders'])
    history = client.get('/api/fr9/payments', headers=headers).get_json()['items'][0]
    op_headers = {'Authorization': 'Bearer op1'}
    operator_response = client.get('/api/fr12/bookings', headers=op_headers)
    assert operator_response.status_code == 200, operator_response.get_json()
    operator = operator_response.get_json()['items'][0]
    admin_headers = {'Authorization': 'Bearer a1'}
    admin = client.get('/api/fr13/payments', headers=admin_headers).get_json()['items'][0]
    booking = client.get('/api/fr13/bookings?type=package', headers=admin_headers).get_json()['items'][0]
    for item in (history, operator, admin, booking):
        assert item['amount'] == 340 and item['currency'] == 'MYR'
        assert item['paymentStatus'] == 'paid'
    assert operator['groupSize'] == 2 and operator['packageTripId'] == 'package-trip-1'
    assert operator['supplierReservationStatus'] == booking['supplierReservationStatus'] == 'not_created'
    assert history['pricingBreakdown'] == operator['pricingBreakdown'] == admin['packageSnapshot']['pricingBreakdown']
    assert memory.collections['checkout_orders'] == persisted
    memory.update('promotional_campaigns', cid, {'discountValue': 1})
    retry = client.post('/api/fr15/package-checkout-attempts', headers=headers,
        json={'packageId':'p1', 'participants':{'adults':2}, 'idempotencyKey':'cross-role'})
    assert retry.get_json()['reused'] and retry.get_json()['attempt']['amount'] == 340
    with patch('modules.fr09_payment.routes.createCheckoutSession') as no_new_payment:
        paid_retry = client.post(f"/api/fr9/package-checkout-attempts/{attempt['id']}/checkout/session", headers=headers, json={})
    assert paid_retry.status_code == 409 and 'already been paid' in paid_retry.get_json()['error']
    no_new_payment.assert_not_called()
    assert memory.collections['checkout_orders'] == persisted


def test_past_campaign_create_is_rejected_before_write(client, mock_operator_auth):
    with patch('modules.fr12_tourism_operator_management.routes.storeRecord') as save:
        response = client.post('/api/fr12/campaigns', headers={'Authorization': 'Bearer test'},
            json={'campaignTitle': 'Old', 'startDate': '2000-01-01', 'endDate': '2000-02-01'})
    assert response.status_code == 400
    assert 'Malaysia' in response.get_json()['error']
    save.assert_not_called()


def test_historical_campaign_title_edit_preserves_dates_but_date_changes_are_validated(client, mock_operator_auth):
    old = campaign(operatorId='test_operator_uid', reviewStatus='draft', startDate='2000-01-01', endDate='2000-02-01')
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value=old), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord', side_effect=lambda c, i, updates: {**old, **updates}) as save:
        response = client.put('/api/fr12/campaigns/c1', headers={'Authorization':'Bearer test'}, json={'campaignTitle':'Historical title'})
        assert response.status_code == 200
        assert response.get_json()['campaign']['startDate'] == old['startDate']
        save.reset_mock()
        changed = client.put('/api/fr12/campaigns/c1', headers={'Authorization':'Bearer test'}, json={'startDate':'2000-01-02'})
        assert changed.status_code == 400
        save.assert_not_called()


def test_expired_campaign_cannot_be_submitted(client, mock_operator_auth):
    old = campaign(operatorId='test_operator_uid', reviewStatus='draft', startDate='2000-01-01', endDate='2000-02-01')
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value=old), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord') as save:
        response = client.post('/api/fr12/campaigns/c1/submit', headers={'Authorization':'Bearer test'}, json={})
    assert response.status_code == 400 and 'expired' in response.get_json()['error']
    save.assert_not_called()


def test_expired_campaign_cannot_be_approved(client, mock_admin_auth):
    old = campaign(reviewStatus='pending', startDate='2000-01-01', endDate='2000-02-01')
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', return_value=old), \
         patch('modules.fr13_administrator_management.routes.updateRecord') as save:
        response = client.post('/api/fr13/campaigns/c1/review', headers={'Authorization':'Bearer test'}, json={'decision':'approved'})
    assert response.status_code == 400 and 'expired' in response.get_json()['error']
    save.assert_not_called()


@pytest.mark.parametrize(('fields', 'label'), [
    ({'isSimulated':True, 'confirmationLabel':'Simulated confirmation'}, 'Hotel Details Saved'),
    ({'bookingStatus':'confirmed'}, 'Reservation Not Confirmed'),
    ({'sandbox':True}, 'Provider Sandbox Record'),
    ({'source':'liteapi', 'providerMutationCalled':True, 'bookingStatus':'confirmed',
      'bookingReference':'supplier-ref', 'providerResult':{'bookingId':'supplier-ref'}}, 'Provider Confirmation Recorded'),
])
def test_hotel_booking_projection_preserves_currency_and_actual_provenance(client, mock_admin_auth, fields, label):
    record = {'id':'h1', 'hotelCost':105.24, 'hotelCurrency':'MYR', **fields}
    original = deepcopy(record)
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', side_effect=lambda collection, **kw: [record] if collection == 'hotel_bookings' else []):
        response = client.get('/api/fr13/bookings?type=hotel', headers={'Authorization':'Bearer test'})
    item = response.get_json()['items'][0]
    assert item['amount'] == 105.24 and item['currency'] == 'MYR'
    assert item['confirmationLabel'] == label
    assert record == original
