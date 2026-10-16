import pytest
from services.package_checkout_contract import create_package_attempt, prepare_package_snapshot

def package(**extra):
    return {'id':'p1','operatorId':'op1','approvalStatus':'approved','availabilityStatus':'available','title':'Penang','adultPrice':100,'currency':'MYR','taxIncluded':True,'updatedAt':'v1', **extra}

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
