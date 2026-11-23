"""Source-proven audit cases. Authentication and persistence are isolated."""
from copy import deepcopy
import pytest
from modules.fr05_smart_itinerary_budget_planner import routes as trips
from modules.fr01_user_management import routes as profiles
from services.itinerary_history import HistoryConflict, history_patch

AUTH={'Authorization':'Bearer isolated-token'}

@pytest.fixture
def isolated_trip(monkeypatch,mock_traveller_auth):
    records={'trip':{'id':'trip','travellerId':'test_traveller_uid','title':'Original',
        'destinationArea':'Penang','startDate':'2027-02-10','endDate':'2027-02-12',
        'travellerCount':2,'budgetLimit':1000,'foodCost':360,'transportCost':105,
        'activities':[],'status':'planned','itineraryRevision':2}}
    writes=[]
    def retrieve(collection,identity=None,**kwargs):
        return deepcopy(records.get(identity)) if collection=='itineraries' else None
    def update(collection,identity,patch,expected=None):
        current=records[identity]
        if expected is not None and current!=expected:raise HistoryConflict('Trip changed.')
        records[identity].update(history_patch(current,patch))
        writes.append(deepcopy(patch))
        return deepcopy(records[identity])
    monkeypatch.setattr(trips,'retrieveRecord',retrieve)
    monkeypatch.setattr(trips,'updateRecord',update)
    return records,writes,update

def test_edit_rejects_stale_client_revision(client,isolated_trip):
    records,writes,_=isolated_trip
    before=deepcopy(records)
    reply=client.put('/api/fr5/itineraries/trip',headers=AUTH,
        json={'title':'Stale screen','expectedItineraryRevision':1})
    assert reply.status_code==409
    assert records==before and not writes

def test_matching_revision_saves_without_persisting_command(client,isolated_trip):
    records,writes,_=isolated_trip
    reply=client.put('/api/fr5/itineraries/trip',headers=AUTH,
        json={'title':'Latest screen','expectedItineraryRevision':2})
    assert reply.status_code==200
    assert records['trip']['title']=='Latest screen'
    assert records['trip']['itineraryRevision']==3
    assert 'expectedItineraryRevision' not in records['trip']

def test_generic_edit_cannot_overwrite_derived_budget_during_concurrent_change(client,isolated_trip,monkeypatch):
    records,writes,update=isolated_trip
    def concurrent(collection,identity,patch,expected=None):
        records[identity].update(foodCost=99,itineraryRevision=3)
        return update(collection,identity,patch,expected)
    monkeypatch.setattr(trips,'updateRecord',concurrent)
    reply=client.put('/api/fr5/itineraries/trip',headers=AUTH,json={'title':'Another editor'})
    assert reply.status_code==409
    assert records['trip']['foodCost']==99 and records['trip']['title']=='Original'
    assert not writes

@pytest.mark.parametrize('payload',[['bad'],{'name':'12345'},{'name':'Valid Name','phoneNo':42},
    {'name':'N'*101}])
def test_profile_registration_uses_same_validation_as_profile_edits(client,mock_traveller_auth,monkeypatch,payload):
    writes=[]
    monkeypatch.setattr(profiles,'retrieveRecord',lambda *a,**k:{})
    monkeypatch.setattr(profiles,'claimRecord',lambda c,uid,data:writes.append(data) or ({'id':uid,**data},True))
    reply=client.post('/api/fr1/profile',headers=AUTH,json=payload)
    assert reply.status_code==400 and not writes



@pytest.mark.parametrize('revision',[0,-1,True,'2',2.5])
def test_invalid_trip_revision_never_writes(client,isolated_trip,revision):
    records,writes,_=isolated_trip
    before=deepcopy(records)
    reply=client.put('/api/fr5/itineraries/trip',headers=AUTH,
        json={'title':'Invalid revision','expectedItineraryRevision':revision})
    assert reply.status_code==400 and records==before and not writes


@pytest.mark.parametrize('method,path',[
    ('post','/api/fr11/sessions'),
    ('put','/api/fr2/preferences'),('post','/api/fr8/hotels/search')])
def test_authenticated_json_mutations_require_an_object(client,mock_traveller_auth,method,path):
    reply=getattr(client,method)(path,headers=AUTH,json=['not-an-object'])
    assert reply.status_code==400


def test_flight_search_rejects_unsupported_post_method(client, mock_traveller_auth):
    # Flight search uses GET; malformed JSON must not invent a POST contract.
    reply = client.post('/api/fr7/flights/search', headers=AUTH, json=['bad'])
    assert reply.status_code == 405
