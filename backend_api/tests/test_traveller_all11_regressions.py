from copy import deepcopy
from unittest.mock import patch
import pytest
from services.liteapi_service import attachRoomContent, normalizeHotelContent, normalizeHotelOffers
from modules.fr03_destination_search_information.routes import _merge_destination
from modules.fr11_chatbot_travel_assistant.guided_planning import guided_requirements
from sequence_contract.domain_functions import applyCollaborativeFiltering

AUTH = {'Authorization': 'Bearer valid_test_token'}

@pytest.mark.parametrize('offset,limit', [(-1,50), (0,0), (0,101), (501,50), ('bad',50)])
def test_hotel_bad_page_stops_provider(client, mock_traveller_auth, offset, limit):
    with patch('modules.fr08_hotel_booking.routes.retrieveHotelOffers') as provider:
        response = client.post('/api/fr8/hotels/search', headers=AUTH, json={'destination': 'Penang', 'checkin': '2030-01-01', 'checkout': '2030-01-03', 'adults': 2, 'offset': offset, 'limit': limit})
    assert response.status_code == 400
    provider.assert_not_called()

def test_hotel_name_and_page_keep_stay_contract(client, mock_traveller_auth):
    with patch('modules.fr08_hotel_booking.routes.retrieveHotelOffers', return_value={'data': []}) as provider:
        response = client.post('/api/fr8/hotels/search', headers=AUTH, json={'destination': 'Penang', 'hotelName': 'Heritage', 'checkin': '2030-01-01', 'checkout': '2030-01-03', 'adults': 2, 'offset': 50, 'limit': 50})
    assert response.status_code == 200
    request = provider.call_args.args[0]
    assert request['hotelName'] == 'Heritage'
    assert request['offset'] == 50 and request['limit'] == 50
    assert request['aiSearch'] == 'Penang' and request['currency'] == 'MYR'
    assert request['occupancies'] == [{'adults': 2}]
    assert response.json['nextOffset'] == 100
    assert response.json['noResults'] is True

@pytest.mark.parametrize('ids,property_id,expected', [(['2'],'hotel',['https://cdn.example/room2.jpg']), (['1'],'hotel',[]), (['2'],'other',[]), (['1','2'],'hotel',[])])
def test_room_photos_require_exact_mapping_and_property(ids, property_id, expected):
    offer = {'hotelId': property_id, 'mappedRoomIds': ids, 'roomImageUrls': [], 'roomName': 'Supplier name'}
    content = normalizeHotelContent({'data': {'id': 'hotel', 'mainPhoto': 'https://cdn.example/property.jpg', 'rooms': [{'id': 2, 'photos': [{'url': 'https://cdn.example/room2.jpg'}]}]}})
    attachRoomContent(offer, content)
    assert offer['roomImageUrls'] == expected
    assert offer['roomName'] == 'Supplier name'

@pytest.mark.parametrize('latitude,longitude', [('NaN','1'), ('91','1'), ('1','181'), ('','1'), ('oops','1')])
def test_weather_bad_coordinates_stop_provider(client, mock_traveller_auth, latitude, longitude):
    with patch('modules.fr06_weather_forecast.routes.retrieveSevenDayForecast') as provider:
        response = client.get('/api/fr6/weather', headers=AUTH, query_string={'latitude': latitude, 'longitude': longitude})
    assert response.status_code == 400
    provider.assert_not_called()

def test_weather_single_request_preserves_returned_fields(client, mock_traveller_auth):
    data = {'current': {'apparent_temperature': 32}, 'daily': {'time': ['2030-01-01']}}
    with patch('modules.fr06_weather_forecast.routes.retrieveSevenDayForecast', return_value=data) as provider:
        response = client.get('/api/fr6/weather?latitude=5.4&longitude=100.2', headers=AUTH)
    assert response.status_code == 200 and response.json['weather'] == data
    provider.assert_called_once()

def test_weather_error_does_not_disclose_provider_diagnostic(client, mock_traveller_auth):
    with patch('modules.fr06_weather_forecast.routes.retrieveSevenDayForecast', side_effect=RuntimeError('private-url')):
        response = client.get('/api/fr6/weather?latitude=5.4&longitude=100.2', headers=AUTH)
    assert response.status_code == 502
    assert 'private-url' not in response.json['error']

def test_more_destinations_have_canonical_ids_and_real_page(client, mock_traveller_auth):
    rows = [{'place_id': str(i), 'title': f'Penang Visitor Place {i}', 'address': 'George Town, Penang, Malaysia', 'type': 'Museum'} for i in range(35)]
    with patch('modules.fr03_destination_search_information.routes.retrieveDestinationResults', return_value={'local_results': rows, 'serpapi_pagination': {'next': 'opaque-provider-next'}}) as provider, patch('modules.fr03_destination_search_information.routes.retrieveRecord', return_value=[]), patch('modules.fr03_destination_search_information.routes.storeRecord'):
        response = client.get('/api/fr3/destinations/search?q=museum&location=Penang&offset=20', headers=AUTH)
    assert response.status_code == 200
    assert provider.call_args.kwargs == {'start': 20}
    assert len(response.json['results']) == 35
    assert all(row.get('destinationId') for row in response.json['results'])
    assert response.json['nextOffset'] == 40

def test_about_retains_real_description_and_true_attributes():
    merged = _merge_destination({'destinationId': 'place'}, {'editorial_summary': {'overview': 'Actual provider description.'}, 'about': {'Accessibility': {'Wheelchair access': True, 'Parking': False}}})
    assert merged['description'] == 'Actual provider description.'
    assert merged['highlights'] == ['Wheelchair access']
    assert _merge_destination({}, {}).get('description') is None

def test_guidance_one_question_and_existing_preferences():
    state = {'destinationArea': 'Penang'}
    prefs = {'interests': ['Culture'], 'travelPace': 'relaxed'}
    assert guided_requirements('plan my trip', state, prefs)['missing'] == ['tripDays']
    assert guided_requirements('3', state, prefs)['missing'] == ['startDate']
    state.update(startDate='2030-12-12', endDate='2030-12-14')
    assert guided_requirements('12 Dec to 14 Dec', state, prefs)['missing'] == ['budgetLimit']
    assert guided_requirements('500', state, prefs)['missing'] == ['travellerCount']
    assert guided_requirements('2', state, prefs)['ready']
    assert state['interests'] == ['Culture'] and state['travelPace'] == 'relaxed'

def test_complete_dated_draft_does_not_require_optional_interests_or_pace():
    state = {'destinationArea': 'Penang', 'tripDays': 3, 'startDate':'2030-12-12','endDate':'2030-12-14', 'budgetLimit': 500, 'travellerCount': 2}
    assert guided_requirements('plan a trip', state, {})['ready']
    assert 'interests' not in state and 'travelPace' not in state

def test_guided_chat_draft_never_saves_trip(client, mock_traveller_auth):
    session = {'id': 's', 'travellerId': 'test_traveller_uid', 'messages': [], 'planningState': {}}
    writes = []
    def read(collection, id=None, **kwargs):
        if collection == 'chat_sessions': return deepcopy(session)
        if collection == 'travel_preferences': return {'interests': ['Culture'], 'travelPace': 'relaxed'}
        return []
    def update(collection, id, data): session.update(deepcopy(data)); return deepcopy(session)
    def store(collection, data, *args, **kwargs): writes.append(collection); return {'id': 'message', **data}
    with patch('modules.fr11_chatbot_travel_assistant.routes.retrieveRecord', side_effect=read), patch('modules.fr11_chatbot_travel_assistant.routes.updateRecord', side_effect=update), patch('modules.fr11_chatbot_travel_assistant.routes.storeRecord', side_effect=store):
        for message in ['Plan a Penang trip', '3', '12 Dec 2030 to 14 Dec 2030', '500', '2']:
            response = client.post('/api/fr11/chat', headers=AUTH, json={'message': message, 'sessionId': 's', 'guidedPlanning': True})
            assert response.status_code == 200
        assert response.json['item'].get('tripPlan')
    assert 'itineraries' not in writes

@pytest.mark.parametrize('rating', [1,3,5])
def test_real_peer_feedback_changes_collaborative_component(rating):
    profile = {'interests': ['Culture'], 'travelPace': 'Relaxed'}
    scored = applyCollaborativeFiltering([{'destinationId': 'place'}], [{'destinationId': 'place', 'travellerId': 'peer', 'rating': rating}], peerPreferences={'peer': profile}, currentPreference=profile, currentTravellerId='owner')[0]
    assert scored['collaborativeRatingCount'] == 1
    assert scored['rawCollaborativeScore'] == rating * 20

def test_recommendation_filters_unpublished_peer_reviews(client, mock_traveller_auth):
    from modules.fr04_hybrid_recommendation import routes
    profile = {'interests': ['Culture'], 'travelPace': 'Relaxed'}
    published = {'destinationId': 'place', 'travellerId': 'peer', 'rating': 5, 'feedbackStatus': 'visible', 'moderationStatus': 'reviewed'}
    def read(collection, id=None, **kwargs):
        if collection == 'travel_preferences': return profile if id else [{'id': 'peer', **profile}]
        if collection == 'learned_preference_profiles': return None
        if collection == 'feedback': return [published, {**published, 'rating': 1, 'moderationStatus': 'pending_review'}]
        return []
    with patch.object(routes, 'retrieveRecord', side_effect=read), patch.object(routes, 'storeRecord', side_effect=lambda c,d,*args,**kw: {'id': 'snapshot', **d}), patch.object(routes, 'applyCollaborativeFiltering', wraps=applyCollaborativeFiltering) as collaborative:
        response = client.post('/api/fr4/recommendations/generate', headers=AUTH, json={'destinationArea': 'Penang'})
    assert response.status_code == 200
    assert collaborative.call_args.args[1] == [published]


def test_details_keep_public_identity_when_provider_returns_an_alias():
    assert _merge_destination({'destinationId': 'public-id'}, {'place_id': 'provider-alias'})['destinationId'] == 'public-id'

def test_guidance_does_not_interrupt_a_weather_question():
    state = {'guidedActive': True, 'destinationArea': 'Penang', 'guidedQuestion': 'budgetLimit'}
    assert guided_requirements('What should I do if it rains?', state, {}) is None
    assert state['guidedQuestion'] == 'budgetLimit'
