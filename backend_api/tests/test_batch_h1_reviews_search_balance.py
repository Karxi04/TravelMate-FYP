from copy import deepcopy
from unittest.mock import patch

import pytest

from services.recommendation_discovery import is_planning_candidate
from services.malaysian_locality import normalize_destination_scope, validate_candidate
from sequence_contract.domain_functions import generateItinerary
from test_batch_h_local_days import make_trip, visit, ids
from test_local_reviews import memory, headers


@pytest.mark.parametrize('category', [
    'gas_station', 'Petrol station', 'residential area', 'Housing development',
    'government office', 'Warehouse', 'Corporate office', 'Industrial supplier', 'Factory',
])
def test_nonvisitor_business_category_exclusion(category):
    assert not is_planning_candidate({'title': 'Local place', 'type_ids': [category], 'type': category})


@pytest.mark.parametrize('name,category', [
    ('Taman Botani', 'Botanical garden'), ('Small-town Kopitiam', 'cafe'),
    ('Government Museum', 'Museum'), ('Local Restaurant', 'restaurant'),
    ('Factory Visitor Museum', 'Museum'), ('Neighbourhood Gallery', 'Art gallery'),
])
def test_visitor_function_survives_ownership_and_neighbourhood(name, category):
    assert is_planning_candidate({'title': name, 'category': category})


def test_cluster_selection_preserves_nature_shopping_instead_of_hill_only_cluster():
    hills = [visit(f'hill{i}', f'Hiking trail {i}', 2.05+i*.001, category='Nature') for i in range(5)]
    mixed = [visit('beach', 'Beach', 1.49, 103.75, category='Nature'),
             visit('garden', 'Botanic Garden', 1.492, 103.75, category='Nature'),
             visit('mall', 'Shopping Mall', 1.493, 103.75, category='Shopping')]
    source = make_trip(hills+mixed, interests=['Nature','Shopping'])
    before = deepcopy(source)
    plan = generateItinerary([], {}, source)
    assert set(ids(plan)) == {'beach','garden','mall'}
    assert plan['interestCoverage']['scheduled'] == {'nature': 2, 'shopping': 1}
    assert source == before
    far = generateItinerary([], {}, make_trip(hills+[mixed[-1]], interests=['Nature','Shopping']))
    assert not ('mall' in ids(far) and any(key.startswith('hill') for key in ids(far)))
    assert far['interestCoverage']['unrepresented']


def test_locality_food_business_uses_explicit_neighbourhood_without_widening():
    scope = normalize_destination_scope('Taman Machang Bubok, Penang, Malaysia')
    assert scope['resolved']
    restaurant = {'title':'Fixture Kopitiam', 'type':'Restaurant',
        'city':'Bukit Mertajam', 'state':'Penang',
        'address':'Taman Machang Bubok, Bukit Mertajam, Penang, Malaysia',
        'gps_coordinates':{'latitude':5.3205,'longitude':100.494}}
    assert validate_candidate(restaurant, scope)[0]
    other = {**restaurant, 'address':'Bukit Mertajam, Penang, Malaysia'}
    assert not validate_candidate(other, scope)[0]
    assert not is_planning_candidate({'title':'Taman Machang Bubok','type':'neighborhood'})


def test_review_test_mode_is_explicit_separate_and_read_only(client, app, memory):
    from modules.fr03_destination_search_information import routes
    source={'id':'real','travellerId':'owner','destinationId':'local_penang_hill',
            'rating':4,'comment':'A lovely visit.','moderationStatus':'reviewed','feedbackStatus':'visible'}
    memory['feedback','real']=source
    app.config['LOCAL_FYP_SAMPLE_REVIEWS']=True
    auth={**headers(), 'X-TravelMate-Review-Context':'fyp-v1'}
    fake={**source,'id':'fiction','travellerId':'fictional','synthetic':True,'rating':1}
    url='/api/fr3/destinations/penang_hill/ratings-reviews'
    with patch.object(routes,'_private_review_dataset',return_value=('ref',{'local_penang_hill':{}})), patch.object(routes,'dataset_reviews',return_value=[fake]):
        normal=client.get(url,headers=auth).json
        demo=client.get(url+'?view=test',headers=auth).json
        assert normal['result']['rating']==4 and normal['result']['reviews']==1
        assert demo['result']['rating']==1 and demo['result']['reviews']==1
        assert demo['disclosure'] and demo['result']['fypPreview']
        assert client.get(url+'?view=test',headers=headers()).status_code==403
    assert memory['feedback','real']==source and len(memory)==1


def test_flag_approval_rejection_and_owner_security(client,memory):
    good=client.post('/api/fr10/feedback',headers=headers(),json={
        'destinationId':'local_penang_hill','rating':5,'comment':'Beautiful scenery and a wonderful visit.'})
    assert good.status_code==201
    second=headers('second')
    flagged=client.post('/api/fr10/feedback',headers=second,json={
        'destinationId':'local_penang_hill','rating':3,'comment':'Click here https://example.invalid for details.'})
    assert flagged.status_code==201
    rid=flagged.json['id']
    assert flagged.json['feedback']['screening']['risk']=='flagged'
    url='/api/fr3/destinations/local_penang_hill/ratings-reviews'
    assert client.get(url,headers=second).json['result']['reviews']==1
    assert client.delete('/api/fr10/feedback/'+rid,headers=headers()).status_code==404
    admin=headers('admin')
    decision=client.post('/api/fr13/feedback/'+rid+'/review',headers=admin,json={'decision':'keep'})
    assert decision.status_code==200
    assert client.get(url,headers=second).json['result']['reviews']==2
    removed=client.post('/api/fr13/feedback/'+rid+'/review',headers=admin,json={'decision':'remove'})
    assert removed.status_code==200
    assert client.get(url,headers=second).json['result']['reviews']==1
    assert memory['feedback',rid]['moderationStatus']=='removed'


def test_explore_food_scope_filters_area_petrol_and_other_towns(client, mock_traveller_auth):
    from modules.fr03_destination_search_information import routes
    food={'title':'Fixture Kopitiam','place_id':'fixture-food','type':'Restaurant',
          'city':'Bukit Mertajam','state':'Penang',
          'address':'Taman Machang Bubok, Bukit Mertajam, Penang, Malaysia',
          'gps_coordinates':{'latitude':5.3205,'longitude':100.494}}
    rows=[food,{**food,'title':'PETRONAS Petrol Station','place_id':'fuel','type':'Gas station'},
          {**food,'title':'Taman Machang Bubok','place_id':'area','type':'Neighborhood'},
          {**food,'title':'Other Town Restaurant','place_id':'other','address':'Bukit Mertajam, Penang, Malaysia'}]
    with patch.object(routes,'retrieveDestinationResults',return_value={'local_results':rows}) as provider, \
         patch.object(routes,'retrieveRecord',return_value=[]), patch.object(routes,'storeRecord'):
        response=client.get('/api/fr3/destinations/search',headers={'Authorization':'Bearer valid_test_token'},
            query_string={'q':'food','location':'Taman Machang Bubok, Penang, Malaysia'})
    assert response.status_code==200, response.json
    assert [row['destinationId'] for row in response.json['results']]==['fixture-food']
    assert 'Machang Bubok' in provider.call_args.args[1]


@pytest.mark.parametrize('query,identity', [
    ('Petronas','local_klcc'),('Petronas Twin Towers','local_klcc'),
    ('KLCC','local_klcc'),('LEGOLAND','local_legoland_malaysia'),
    ('Langkawi Sky Bridge','local_langkawi_skycab'),
])
def test_named_attraction_precedes_nonvisitor_name_collision(client,mock_traveller_auth,query,identity):
    from modules.fr03_destination_search_information import routes
    with patch.object(routes,'retrieveDestinationResults',return_value={'local_results':[
        {'title':query+' Petrol Station','type':'Gas station','place_id':'fuel',
         'address':'Kuala Lumpur, Malaysia','state':'Kuala Lumpur',
         'gps_coordinates':{'latitude':3.157,'longitude':101.712}}]}), \
         patch.object(routes,'retrieveRecord',return_value=[]), patch.object(routes,'storeRecord'):
        response=client.get('/api/fr3/destinations/search',headers={'Authorization':'Bearer valid_test_token'},
                            query_string={'q':query,'location':'Malaysia'})
    assert response.status_code==200, response.json
    assert response.json['results'][0]['destinationId']==identity
    assert all(row['destinationId']!='fuel' for row in response.json['results'])


def test_verified_provider_alias_reuses_canonical_review_and_submission(client,mock_traveller_auth):
    from services.local_catalog import DESTINATIONS
    from modules.fr03_destination_search_information import routes as explore
    from modules.fr10_feedback_rating import routes as feedback
    known=next(row for row in DESTINATIONS if row['destinationId']=='local_penang_hill')
    provider={**known,'destinationId':'fixture-provider-hill','place_id':'fixture-provider-hill'}
    assert explore._review_identity(provider)=='local_penang_hill'
    assert explore._review_identity({**provider,'title':'Penang Hill Hotel'}) is None
    assert explore._review_identity({**provider,'gps_coordinates':{'latitude':1.49,'longitude':103.75}}) is None
    def read(collection,identity=None,**kwargs):
        if collection=='destination_cache': return provider
        if collection=='feedback': return []
        if collection=='users': return {'name':'Test account'}
    def claim(collection,identity,data):
        assert collection=='feedback'
        return {**data,'id':identity},True
    with patch.object(feedback,'retrieveRecord',side_effect=read),patch.object(feedback,'claimRecord',side_effect=claim):
        response=client.post('/api/fr10/feedback',headers={'Authorization':'Bearer valid_test_token'},json={
          'destinationId':'fixture-provider-hill','rating':5,'comment':'Beautiful scenery and a wonderful visit.'})
    assert response.status_code==201
    assert response.json['feedback']['destinationId']=='local_penang_hill'


def test_multi_interest_selection_keeps_numerical_budget_limit():
    rows=[visit('garden','Botanic Garden',2.055,category='Nature',estimatedCost=0,unitPrice=0,
                pricingUnit='per_group',costProvenance='catalog_estimate'),
          visit('mall','Shopping Mall',2.057,category='Shopping',estimatedCost=500,unitPrice=500,
                pricingUnit='per_group',costProvenance='catalog_estimate')]
    plan=generateItinerary([],{},make_trip(rows,interests=['Nature','Shopping'],budgetLimit=100))
    assert ids(plan)==['garden']
    assert 'shopping' in plan['interestCoverage']['unrepresented']
    assert 'budget' in plan['unscheduledSuggestions'][0]['unscheduledReason']


def test_budget_quality_repair_cannot_remove_an_already_represented_interest():
    from services.budget_aware_selection import _improve_once
    from test_budget_aware_selection import activity, trip
    mall=activity('mall',100,70,'per_group',activityName='Shopping Mall',category='Shopping')
    gardens=[activity(f'garden{i}',0,90,'per_group',activityName='Botanic Garden',category='Nature') for i in range(2)]
    base=trip(budgetLimit=250,geographyPlanningPolicy='local-days-v1',
              planningPreferences={'interests':['Nature','Shopping']})
    excluded=[{'activity':row,'reasonCode':'known_budget_exceeded'} for row in gardens]
    result,_,_,_= _improve_once(base,[mall],excluded,{'mall':70,'garden0':90,'garden1':90},{},250)
    assert [row['activityId'] for row in result]==['mall']
