import pytest
from services.package_checkout_contract import prepare_package_snapshot

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
