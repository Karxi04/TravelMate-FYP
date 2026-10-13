import pytest
from services.package_checkout_contract import create_package_attempt, prepare_package_snapshot

def package(**extra):
    return {'id':'p1','operatorId':'op1','approvalStatus':'approved','availabilityStatus':'available','title':'Penang','adultPrice':100,'currency':'MYR','taxIncluded':True,'updatedAt':'v1', **extra}

def test_snapshot_is_server_owned_and_copies_itinerary():
    raw=package(itineraryDays=[{'dayNumber':1,'activities':['Walk']}])
    snapshot=prepare_package_snapshot(raw, {'id':'op1'})
    raw['itineraryDays'][0]['activities'].append('Changed')
    assert snapshot['price'] == 100 and snapshot['itineraryDays'][0]['activities'] == ['Walk']

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
