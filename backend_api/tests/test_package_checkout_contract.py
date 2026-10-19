import pytest
from services.package_checkout_contract import (
    create_package_attempt,
    is_package_promotion_active,
    prepare_package_snapshot,
)

def package(**extra):
    return {'id':'p1','operatorId':'op1','approvalStatus':'approved','availabilityStatus':'available','title':'Penang','adultPrice':100,'currency':'MYR','taxIncluded':True,'updatedAt':'v1', 'priceBasis':'per_person', **extra}

def test_snapshot_is_server_owned_and_copies_itinerary():
    raw=package(itineraryDays=[{'dayNumber':1,'activities':['Walk']}])
    snapshot=prepare_package_snapshot(raw, {'id':'op1'})
    raw['itineraryDays'][0]['activities'].append('Changed')
    assert snapshot['price'] == 100 and snapshot['amountMinor'] == 10000
    assert snapshot['participants'] == {'adults': 1, 'children': 0, 'total': 1}
    assert snapshot['itineraryDays'][0]['activities'] == ['Walk']


@pytest.mark.parametrize(('participants', 'expected'), [
    ({'adults': 2, 'children': 0}, 200),
    ({'adults': 3, 'children': 0}, 300),
    ({'adults': 2, 'children': 1}, 250),
])
def test_per_person_group_total_uses_explicit_adult_and_child_prices(participants, expected):
    snapshot = prepare_package_snapshot(
        package(childPrice=50, priceBasis='per_person'), {'id': 'op1'},
        participants=participants,
    )
    assert snapshot['price'] == expected
    assert snapshot['amountMinor'] == expected * 100
    assert snapshot['groupSize'] == participants['adults'] + participants['children']


def test_fixed_group_price_is_not_multiplied_by_participants():
    snapshot = prepare_package_snapshot(
        package(priceBasis='per_group', maximumTravellers=6), {'id': 'op1'},
        participants={'adults': 3, 'children': 2},
    )
    assert snapshot['price'] == 100
    assert snapshot['groupSize'] == 5


@pytest.mark.parametrize('participants', [
    {'adults': 0, 'children': 0}, {'adults': -1, 'children': 0},
    {'adults': 1.5, 'children': 0}, {'adults': 0, 'children': 1},
])
def test_invalid_participant_counts_are_rejected(participants):
    with pytest.raises(ValueError):
        prepare_package_snapshot(package(), {'id': 'op1'}, participants=participants)


def test_child_price_and_package_capacity_are_enforced():
    with pytest.raises(ValueError, match='Child pricing'):
        prepare_package_snapshot(
            package(), {'id': 'op1'}, participants={'adults': 1, 'children': 1}
        )
    with pytest.raises(ValueError, match='capacity'):
        prepare_package_snapshot(
            package(maximumTravellers=2), {'id': 'op1'},
            participants={'adults': 3, 'children': 0},
        )

    with pytest.raises(ValueError, match='smaller'):
        prepare_package_snapshot(
            package(minimumTravellers=3), {'id': 'op1'},
            participants={'adults': 2, 'children': 0},
        )
    boundary = prepare_package_snapshot(
        package(minimumTravellers=3, maximumTravellers=3, childPrice=50), {'id': 'op1'},
        participants={'adults': 2, 'children': 1},
    )
    assert boundary['groupSize'] == 3


def test_myr_rounding_and_unapplied_promotion_remain_server_authoritative():
    snapshot = prepare_package_snapshot(
        package(
            adultPrice='10.005', childPrice='4.994', originalPrice=20,
            promotionalPrice=8, promotionStart='2027-01-01', promotionEnd='2027-12-31',
        ),
        {'id': 'op1'}, participants={'adults': 2, 'children': 1},
    )
    assert snapshot['adultUnitPrice'] == 10.01
    assert snapshot['childUnitPrice'] == 4.99
    assert snapshot['price'] == 25.01
    assert snapshot['amountMinor'] == 2501
    assert 'promotionalPrice' not in snapshot


def test_departure_date_must_be_an_approved_package_date():
    raw = package(departureDates=['2027-01-10', '2027-02-10'])
    with pytest.raises(ValueError, match='Select'):
        prepare_package_snapshot(raw, {'id': 'op1'})
    with pytest.raises(ValueError, match='unavailable'):
        prepare_package_snapshot(raw, {'id': 'op1'}, departure_date='2027-03-10')
    snapshot = prepare_package_snapshot(raw, {'id': 'op1'}, departure_date='2027-02-10')
    assert snapshot['selectedDepartureDate'] == '2027-02-10'

@pytest.mark.parametrize('extra', [{'approvalStatus':'draft'},{'adultPrice':None},{'currency':'USD'},{'taxIncluded':None,'taxNotes':''}])
def test_rejects_ineligible_or_ambiguous_package(extra):
    with pytest.raises(ValueError): prepare_package_snapshot(package(**extra), {'id':'op1'})

def test_attempt_is_idempotent_and_owned_trip_bound():
    records = {}
    def claim(_, key, value):
        if key in records: return records[key], False
        records[key] = value; return value, True
    trip = {'id':'t1','travellerId':'u1','destinationArea':''}
    first, created = create_package_attempt(claim, 'u1', package(), {'id':'op1'}, 'key', trip)
    again, repeated = create_package_attempt(claim, 'u1', package(), {'id':'op1'}, 'key', trip)
    assert created and not repeated and first['packageSnapshot'] == again['packageSnapshot']
    with pytest.raises(ValueError): create_package_attempt(claim, 'u1', package(id='p2'), {'id':'op1'}, 'key', trip)


def test_attempt_idempotency_rejects_changed_group_inputs():
    records = {}
    def claim(_, key, value):
        if key in records: return records[key], False
        records[key] = value; return value, True
    first, created = create_package_attempt(
        claim, 'u1', package(childPrice=50), {'id': 'op1'}, 'group-key',
        participants={'adults': 2, 'children': 0},
    )
    assert created and first['fulfillmentMode'] == 'independent_package_trip'
    with pytest.raises(ValueError, match='another package checkout'):
        create_package_attempt(
            claim, 'u1', package(childPrice=50), {'id': 'op1'}, 'group-key',
            participants={'adults': 2, 'children': 1},
        )


def test_attempt_idempotency_rejects_changed_departure_date():
    records = {}
    def claim(_, key, value):
        if key in records: return records[key], False
        records[key] = value; return value, True

    raw = package(departureDates=['2027-01-10', '2027-02-10'])
    create_package_attempt(
        claim, 'u1', raw, {'id': 'op1'}, 'departure-key',
        departure_date='2027-01-10',
    )
    with pytest.raises(ValueError, match='another package checkout'):
        create_package_attempt(
            claim, 'u1', raw, {'id': 'op1'}, 'departure-key',
            departure_date='2027-02-10',
        )


def test_explicit_repeat_purchase_uses_distinct_attempt_without_mutating_first():
    records = {}
    def claim(_, key, value):
        if key in records: return records[key], False
        records[key] = value; return value, True

    first, first_created = create_package_attempt(
        claim, 'u1', package(departureDates=['2027-01-10']), {'id': 'op1'},
        'purchase-one', participants={'adults': 2, 'children': 0},
        departure_date='2027-01-10',
    )
    second, second_created = create_package_attempt(
        claim, 'u1', package(departureDates=['2027-01-10']), {'id': 'op1'},
        'purchase-two', participants={'adults': 2, 'children': 0},
        departure_date='2027-01-10',
    )

    assert first_created and second_created
    assert first['id'] != second['id']
    assert first['paymentStatus'] == second['paymentStatus'] == 'payment_pending'
    assert records[first['id']]['idempotencyKey'] == 'purchase-one'
    assert records[second['id']]['idempotencyKey'] == 'purchase-two'


def test_default_participants_is_one_adult_zero_children():
    snapshot = prepare_package_snapshot(package(), {'id': 'op1'})
    assert snapshot['participants'] == {'adults': 1, 'children': 0, 'total': 1}
    assert snapshot['groupSize'] == 1


def test_vivo_active_promotion_four_adults_is_rm3196():
    raw = package(
        adultPrice=899,
        originalPrice=899,
        promotionalPrice=799,
        promotionStart='2026-10-20',
        promotionEnd='2026-12-10',
        minimumTravellers=4,
        maximumTravellers=12,
    )
    snapshot = prepare_package_snapshot(
        raw, {'id': 'op1'},
        now='2026-10-25T10:00:00Z',
        participants={'adults': 4, 'children': 0},
    )
    assert snapshot['isPromotionEligible'] is True
    assert snapshot['regularAdultUnitPrice'] == 899
    assert snapshot['adultUnitPrice'] == 799
    assert snapshot['promotionalUnitPrice'] == 799
    assert snapshot['originalPrice'] == 899
    assert snapshot['price'] == 3196
    assert snapshot['amountMinor'] == 319600


def test_vivo_unapplied_future_promotion_four_adults_is_rm3596():
    raw = package(
        adultPrice=899,
        originalPrice=899,
        promotionalPrice=799,
        promotionStart='2026-10-20',
        promotionEnd='2026-12-10',
        minimumTravellers=4,
        maximumTravellers=12,
    )
    snapshot = prepare_package_snapshot(
        raw, {'id': 'op1'},
        now='2026-10-15T12:00:00Z',
        participants={'adults': 4, 'children': 0},
    )
    assert snapshot['isPromotionEligible'] is False
    assert snapshot['regularAdultUnitPrice'] == 899
    assert snapshot['adultUnitPrice'] == 899
    assert snapshot['promotionalUnitPrice'] is None
    assert snapshot['price'] == 3596
    assert snapshot['amountMinor'] == 359600


def test_vivo_expired_promotion_four_adults_is_rm3596():
    raw = package(
        adultPrice=899,
        originalPrice=899,
        promotionalPrice=799,
        promotionStart='2026-10-20',
        promotionEnd='2026-12-10',
        minimumTravellers=4,
        maximumTravellers=12,
    )
    snapshot = prepare_package_snapshot(
        raw, {'id': 'op1'},
        now='2026-12-11T00:00:00Z',
        participants={'adults': 4, 'children': 0},
    )
    assert snapshot['isPromotionEligible'] is False
    assert snapshot['adultUnitPrice'] == 899
    assert snapshot['price'] == 3596
    assert snapshot['amountMinor'] == 359600


def test_promotion_boundary_dates_are_inclusive():
    raw = package(
        adultPrice=899,
        promotionalPrice=799,
        promotionStart='2026-10-20',
        promotionEnd='2026-12-10',
    )
    start_boundary = prepare_package_snapshot(
        raw, {'id': 'op1'},
        now='2026-10-20',
        participants={'adults': 1, 'children': 0},
    )
    assert start_boundary['isPromotionEligible'] is True
    assert start_boundary['adultUnitPrice'] == 799

    end_boundary = prepare_package_snapshot(
        raw, {'id': 'op1'},
        now='2026-12-10',
        participants={'adults': 1, 'children': 0},
    )
    assert end_boundary['isPromotionEligible'] is True
    assert end_boundary['adultUnitPrice'] == 799


def test_per_group_active_promotion_and_regular():
    raw = package(
        priceBasis='per_group',
        adultPrice=899,
        promotionalPrice=799,
        promotionStart='2026-10-01',
        promotionEnd='2026-12-31',
        maximumTravellers=10,
    )
    active = prepare_package_snapshot(
        raw, {'id': 'op1'},
        now='2026-10-25',
        participants={'adults': 4, 'children': 2},
    )
    assert active['price'] == 799
    assert active['amountMinor'] == 79900
    assert active['isPromotionEligible'] is True

    inactive = prepare_package_snapshot(
        raw, {'id': 'op1'},
        now='2027-01-01',
        participants={'adults': 4, 'children': 2},
    )
    assert inactive['price'] == 899
    assert inactive['amountMinor'] == 89900
    assert inactive['isPromotionEligible'] is False


def test_equal_adult_and_child_rates_preserved_in_snapshot():
    snapshot = prepare_package_snapshot(
        package(adultPrice=100, childPrice=100),
        {'id': 'op1'},
        participants={'adults': 2, 'children': 2},
    )
    assert snapshot['adultUnitPrice'] == 100
    assert snapshot['childUnitPrice'] == 100
    assert snapshot['price'] == 400
    assert snapshot['amountMinor'] == 40000


def test_missing_or_ambiguous_price_basis_is_rejected():
    with pytest.raises(ValueError, match='verified price basis'):
        prepare_package_snapshot(package(priceBasis=None), {'id': 'op1'})
    with pytest.raises(ValueError, match='verified price basis'):
        prepare_package_snapshot(package(priceBasis=''), {'id': 'op1'})
    with pytest.raises(ValueError, match='verified price basis'):
        prepare_package_snapshot(package(priceBasis='dynamic'), {'id': 'op1'})


def test_promotional_price_not_less_than_regular_price_is_ineligible():
    raw_greater = package(
        adultPrice=800,
        promotionalPrice=850,
        promotionStart='2026-10-01',
        promotionEnd='2026-12-31',
    )
    snapshot = prepare_package_snapshot(raw_greater, {'id': 'op1'}, now='2026-10-25')
    assert snapshot['isPromotionEligible'] is False
    assert snapshot['adultUnitPrice'] == 800

    raw_equal = package(
        adultPrice=800,
        promotionalPrice=800,
        promotionStart='2026-10-01',
        promotionEnd='2026-12-31',
    )
    snapshot_equal = prepare_package_snapshot(raw_equal, {'id': 'op1'}, now='2026-10-25')
    assert snapshot_equal['isPromotionEligible'] is False
    assert snapshot_equal['adultUnitPrice'] == 800


def test_original_price_is_informational_never_overrides_payable_price():
    snapshot = prepare_package_snapshot(
        package(originalPrice=1500, adultPrice=899),
        {'id': 'op1'},
    )
    assert snapshot['originalPrice'] == 1500
    assert snapshot['adultUnitPrice'] == 899
    assert snapshot['price'] == 899
    assert snapshot['amountMinor'] == 89900
