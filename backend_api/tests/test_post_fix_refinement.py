import json
import re
from copy import deepcopy
from datetime import date
from pathlib import Path
from unittest.mock import patch
import pytest
from modules.fr11_chatbot_travel_assistant.travel_dates import parse_date_range
from modules.fr11_chatbot_travel_assistant.nlp_extractor import extract_dates, build_structured_trip_plan
from services.flight_airports import AIRPORT_CATALOG, SUPPORTED_AIRPORTS, CITY_TO_IATA, MALAYSIAN_AIRPORT_CATALOG

AUTH = {'Authorization': 'Bearer valid_test_token'}
TODAY = date(2026, 11, 5)

@pytest.mark.parametrize('text,start,end', [
    ('12 Dec until 16 Dec','2026-12-12','2026-12-16'),
    ('from 12 December 2030 to 16 December 2030','2030-12-12','2030-12-16'),
    ('12th Dec until 16th Dec 2030','2030-12-12','2030-12-16'),
    ('2030-12-12 through 2030-12-16','2030-12-12','2030-12-16'),
    ('12/12/2030 until 16/12/2030','2030-12-12','2030-12-16'),
    ('28 Dec to 2 Jan','2026-12-28','2027-01-02'),
    ('28 Dec 2030 to 2 Jan','2030-12-28','2031-01-02'),
    ('28 Dec to 2 Jan 2031','2030-12-28','2031-01-02'),
])
def test_range_parsing(text,start,end):
    assert parse_date_range(text, today=TODAY) == (start,end)

@pytest.mark.parametrize('text', [
    '31 Feb 2030 to 3 Mar 2030', '16 Dec 2030 to 12 Dec 2030',
    '1 Dec 2020 until 3 Dec 2020', '01/02/2030 to 03/04/2030',
    '1 Dec 2030 to 31 Dec 2030', '12 Dec until',
    '12 Dec 2030 and 16 Dec 2030', '12 Dec 2030 to 16 Dec 2030 or 20 Dec 2030',
])
def test_invalid_ambiguous_or_unsupported_ranges_ask_for_clarification(text):
    with pytest.raises(ValueError): parse_date_range(text,today=TODAY)

def test_dates_override_conflicting_duration_through_plan_generation():
    start,end=extract_dates('Plan 2 days in Penang from 12 Dec 2030 until 16 Dec 2030', duration_days=2)
    plan,status=build_structured_trip_plan('Penang','Penang',days=2,start_date=start,end_date=end)
    assert status == 'ready'
    assert plan['startDate'] == '2030-12-12' and plan['endDate'] == '2030-12-16'
    assert plan['title'].startswith('5-Day')
    assert max(row['dayNo'] for row in plan['activities']) == 5

def test_date_range_beyond_seven_days_is_not_silently_truncated():
    plan,status=build_structured_trip_plan('Penang','Penang',days=3,start_date='2030-12-01',end_date='2030-12-10')
    assert status == 'ready' and plan['title'].startswith('10-Day')
    assert max(row['dayNo'] for row in plan['activities']) == 10

@pytest.fixture
def chat_memory(monkeypatch):
    session={'id':'s','travellerId':'test_traveller_uid','messages':[], 'planningState':{'destinationArea':'Penang','destinationState':'Penang','travellerCount':2,'guidedActive':True,'guidedPlanning':True}}
    writes=[]
    def read(collection,identity=None,**kwargs):
        if collection == 'chat_sessions': return deepcopy(session)
        if collection == 'travel_preferences': return {'interests':['Culture'],'travelPace':'relaxed'}
        return []
    def update(collection,identity,data,**kwargs): session.update(deepcopy(data)); return deepcopy(session)
    def store(collection,data,*args,**kwargs): writes.append((collection,deepcopy(data))); return {'id':'stored',**data}
    from modules.fr11_chatbot_travel_assistant import routes
    monkeypatch.setattr(routes,'retrieveRecord',read); monkeypatch.setattr(routes,'updateRecord',update); monkeypatch.setattr(routes,'storeRecord',store)
    return session,writes

def test_date_only_reply_advances_to_budget_and_exact_dates_survive_save(client,mock_traveller_auth,chat_memory):
    session,writes=chat_memory
    response=client.post('/api/fr11/chat',headers=AUTH,json={'sessionId':'s','guidedPlanning':True,'message':'12 Dec 2030 until 16 Dec 2030'})
    assert response.status_code == 200
    assert session['planningState']['tripDays'] == 5
    assert session['planningState']['startDate'] == '2030-12-12'
    assert session['planningState']['endDate'] == '2030-12-16'
    assert session['planningState']['guidedQuestion'] == 'budgetLimit'
    assert '5 calendar days' in response.json['reply']
    assert 'How many days' not in response.json['reply']
    response=client.post('/api/fr11/chat',headers=AUTH,json={'sessionId':'s','guidedPlanning':True,'message':'1000'})
    plan=response.json['item']['tripPlan']
    assert plan['startDate'] == '2030-12-12' and plan['endDate'] == '2030-12-16'
    assert not [row for row in writes if row[0] == 'itineraries']
    saved=client.post('/api/fr11/save-plan',headers=AUTH,json={'plan':plan,'confirmed':True})
    assert saved.status_code == 201
    assert saved.json['itinerary']['startDate'] == '2030-12-12'
    assert saved.json['itinerary']['endDate'] == '2030-12-16'


def test_bad_range_does_not_generate_using_previous_or_default_dates(client,mock_traveller_auth,chat_memory):
    session,writes=chat_memory
    session['planningState'].update(startDate='2030-12-01',endDate='2030-12-03',budgetLimit=1000,tripDays=3)
    bad=client.post('/api/fr11/chat',headers=AUTH,json={'sessionId':'s','guidedPlanning':True,'message':'31 Feb 2030 until 3 Mar 2030'})
    assert bad.status_code == 200 and 'invalid' in bad.json['reply'].lower()
    assert 'tripPlan' not in bad.json['item']
    assert not [row for row in writes if row[0] == 'itineraries']
    unrelated=client.post('/api/fr11/chat',headers=AUTH,json={'sessionId':'s','guidedPlanning':True,'message':'budget RM 2000'})
    assert 'tripPlan' not in unrelated.json['item']
    assert session['planningState']['dateClarification']
    corrected=client.post('/api/fr11/chat',headers=AUTH,json={'sessionId':'s','guidedPlanning':True,'message':'12 Dec 2030 until 16 Dec 2030'})
    assert corrected.json['item']['tripPlan']['endDate'] == '2030-12-16'
    assert 'dateClarification' not in session['planningState']


def test_duration_can_replace_a_rejected_range_without_reusing_old_dates(client,mock_traveller_auth,chat_memory):
    session,_=chat_memory
    session['planningState'].update(startDate='2030-12-01',endDate='2030-12-03',tripDays=3,dateClarification='Please correct the dates.')
    response=client.post('/api/fr11/chat',headers=AUTH,json={'sessionId':'s','guidedPlanning':True,'message':'5 days instead'})
    assert response.status_code == 200
    assert session['planningState']['tripDays'] == 5
    assert not any(key in session['planningState'] for key in ('startDate','endDate','dateClarification'))

def test_frontend_backend_catalogue_parity_and_real_regional_expansion():
    repo=Path(__file__).resolve().parents[2]
    source=(repo/'traveller_mobile/lib/modules/fr07_flight_search/flight_airport_catalog.dart').read_text(encoding='utf-8')
    labels={json.loads(code):json.loads(label.replace(r'\$', '$')) for code,label in re.findall(r'^  ("[A-Z]{3}"): (".*"),$',source.split('const Map<String, String> flightAirportAliases')[0],re.M)}
    expected={code:', '.join([item['city'],item['name'],item['state'],'Malaysia']) for code,item in MALAYSIAN_AIRPORT_CATALOG.items()}
    assert labels == expected
    assert len(SUPPORTED_AIRPORTS) == 4008
    assert sum(row['country']=='MY' for row in AIRPORT_CATALOG.values()) == 34
    assert set(CITY_TO_IATA.values()) <= SUPPORTED_AIRPORTS | MALAYSIAN_AIRPORT_CATALOG.keys()
    assert {'SZB','KBR','TGG','KUA','MYY','SBW','TWU','SDK','LBU','SFO','JFK','CDG','DEL','LAX'} <= SUPPORTED_AIRPORTS
    assert 'ZZZ' not in SUPPORTED_AIRPORTS

@pytest.mark.parametrize('code',['SZB','KBR','TGG','MYY','BTU','SDK','LBU','AOR','TOD'])
def test_new_catalogue_codes_preserve_provider_search_contract(client,mock_traveller_auth,code):
    with patch('modules.fr07_flight_search.routes.retrieveFlightOptions',return_value={'items':[]}) as provider, patch('modules.fr07_flight_search.routes.storeRecord'):
        response=client.get('/api/fr7/flights/search',headers=AUTH,query_string={'departure_id':'KUL','arrival_id':code,'outbound_date':'2030-12-12'})
    assert response.status_code == 200 and response.json['items'] == []
    assert provider.call_args.args[:2] == ('KUL',code)
    assert provider.call_args.kwargs['currency'] == 'MYR'
