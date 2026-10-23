from copy import deepcopy
from unittest.mock import patch

import pytest

from modules.fr11_chatbot_travel_assistant.nlp_extractor import (
    build_structured_trip_plan,
    extract_excluded_activity_types,
    extract_excluded_interests,
    extract_indoor_preference,
    extract_interests,
)
from modules.fr11_chatbot_travel_assistant.routes import _extract_place_suggestions
from services.gemini_service import generateChatbotResponse


@pytest.mark.parametrize(
    ('message', 'expected'),
    [
        ('Do not include museums or shopping malls.', ['Museum', 'Shopping Mall']),
        ('We enjoy heritage attractions, just not museums.', ['Museum']),
        ("I don't want to visit any shopping mall.", ['Shopping Mall']),
    ],
)
def test_specific_exclusions_are_not_broadened(message, expected):
    assert extract_excluded_activity_types(message) == expected
    assert extract_excluded_interests(message) == []


def test_positive_culture_survives_specific_museum_exclusion():
    message = 'I love cultural heritage, but I do not want museums.'
    assert 'Culture' in extract_interests(message)
    assert extract_excluded_interests(message) == []
    assert extract_excluded_activity_types(message) == ['Museum']


def test_broad_culture_exclusion_remains_supported():
    assert extract_excluded_interests('No cultural attractions at all.') == ['Culture']


def test_latest_explicit_specific_correction_wins():
    previous = ['Museum', 'Shopping Mall']
    updated = extract_excluded_activity_types(
        'Actually museums are okay now, but still no shopping malls.', previous
    )
    assert updated == ['Shopping Mall']


def test_corrected_exclusion_reallows_only_the_requested_activity_type():
    updated = extract_excluded_activity_types(
        'Actually museums are okay now, but still no shopping malls.',
        ['Museum', 'Shopping Mall'],
    )
    catalog = [
        {'destinationId': 'museum', 'title': 'Heritage Museum', 'address': 'Penang',
         'city': 'Penang', 'state': 'Penang', 'category': 'Culture', 'type': 'Museum', 'indoor': True},
        {'destinationId': 'mall', 'title': 'Central Plaza', 'address': 'Penang',
         'city': 'Penang', 'state': 'Penang', 'category': 'Shopping', 'type': 'Shopping mall', 'indoor': True},
    ]
    plan, status = build_structured_trip_plan(
        'Penang', 'Penang', catalog=catalog, prefer_indoor=True,
        excluded_activity_types=updated,
    )
    assert status == 'ready'
    assert [item['destinationId'] for item in plan['activities']] == ['museum']


@pytest.mark.parametrize('message', ['indoor alternatives', 'find indoor places'])
def test_indoor_phrases_enable_hard_indoor_preference(message):
    assert extract_indoor_preference(message, False) is True


def test_planner_enforces_all_constraints_without_duplicate_padding():
    catalog = [
        {'destinationId': 'safe', 'title': 'Covered Food Hall', 'address': 'Penang',
         'city': 'Penang', 'state': 'Penang', 'category': 'Food', 'type': 'Food hall', 'indoor': True},
        {'destinationId': 'museum', 'title': 'History Museum', 'address': 'Penang',
         'city': 'Penang', 'state': 'Penang', 'category': 'Culture Museum', 'type': 'Museum', 'indoor': True},
        {'destinationId': 'mall', 'title': 'Central Shopping Mall', 'address': 'Penang',
         'city': 'Penang', 'state': 'Penang', 'category': 'Shopping', 'type': 'Shopping mall', 'indoor': True},
        {'destinationId': 'hill', 'title': 'Scenic Hill', 'address': 'Penang',
         'city': 'Penang', 'state': 'Penang', 'category': 'Nature', 'type': 'Outdoor', 'indoor': False},
    ]
    plan, status = build_structured_trip_plan(
        'Penang', 'Penang', days=3, catalog=catalog, prefer_indoor=True,
        excluded_activity_types=['Museum', 'Shopping Mall'],
    )
    assert status == 'ready'
    assert [item['destinationId'] for item in plan['activities']] == ['safe']
    assert plan['excludedActivityTypes'] == ['Museum', 'Shopping Mall']
    assert plan['preferIndoor'] is True


def test_planner_reports_constraint_conflict_instead_of_unsafe_fallback():
    catalog = [
        {'destinationId': 'museum', 'title': 'Only Museum', 'address': 'Penang',
         'city': 'Penang', 'state': 'Penang', 'category': 'Culture Museum', 'type': 'Museum', 'indoor': True},
        {'destinationId': 'park', 'title': 'Only Park', 'address': 'Penang',
         'city': 'Penang', 'state': 'Penang', 'category': 'Nature', 'type': 'Park', 'indoor': False},
    ]
    plan, status = build_structured_trip_plan(
        'Penang', 'Penang', catalog=catalog, prefer_indoor=True,
        excluded_activity_types=['Museum'],
    )
    assert plan is None
    assert status == 'constraint_conflict'


def test_unknown_or_string_indoor_metadata_is_not_treated_as_verified_indoor():
    catalog = [
        {'destinationId': 'unknown', 'title': 'Unknown Venue', 'address': 'Penang',
         'city': 'Penang', 'state': 'Penang', 'category': 'Food', 'type': 'Venue'},
        {'destinationId': 'string', 'title': 'String Venue', 'address': 'Penang',
         'city': 'Penang', 'state': 'Penang', 'category': 'Food', 'type': 'Venue', 'indoor': 'true'},
    ]
    plan, status = build_structured_trip_plan('Penang', 'Penang', catalog=catalog, prefer_indoor=True)
    assert plan is None
    assert status == 'constraint_conflict'


def test_suggestion_cards_use_the_same_hard_constraints():
    suggestions = _extract_place_suggestions(
        'Suggest indoor alternatives in Penang', destination_area='Penang', prefer_indoor=True,
        excluded_activity_types=['Museum', 'Shopping Mall'],
    )
    assert suggestions
    assert all(item.get('indoor') is True for item in suggestions)
    assert all('museum' not in item.get('title', '').lower() for item in suggestions)
    assert all('mall' not in item.get('title', '').lower() for item in suggestions)


def test_deterministic_weather_text_does_not_recommend_excluded_types():
    response = generateChatbotResponse(
        'It is raining heavily, suggest indoor alternatives.',
        with_source=True,
        planning_state={
            'destinationArea': 'Penang',
            'preferIndoor': True,
            'excludedActivityTypes': ['Museum', 'Shopping Mall'],
        },
    )
    assert response['source'] == 'travelmate-assistant'
    assert 'keep Museum, Shopping Mall out' in response['reply']
    assert 'constraint conflict' in response['reply']
    assert 'Wonderfood' not in response['reply']


def test_multiturn_route_preserves_constraints_and_returns_explicit_conflict(client, mock_traveller_auth):
    database = {}
    counters = {}

    def store(collection, data):
        counters[collection] = counters.get(collection, 0) + 1
        record_id = f'{collection}_{counters[collection]}'
        record = {'id': record_id, **deepcopy(data)}
        database.setdefault(collection, {})[record_id] = record
        return deepcopy(record)

    def retrieve(collection, record_id=None, filters=None, limit=None):
        if record_id is not None:
            value = database.get(collection, {}).get(record_id)
            return deepcopy(value) if value else None
        values = list(database.get(collection, {}).values())
        for field, operator, expected in filters or []:
            assert operator == '=='
            values = [value for value in values if value.get(field) == expected]
        return deepcopy(values[:limit] if limit else values)

    def update(collection, record_id, changes):
        current = database[collection][record_id]
        current.update(deepcopy(changes))
        return deepcopy(current)

    service_result = {'reply': 'Mocked offline response', 'source': 'travelmate-assistant'}
    with patch('modules.fr11_chatbot_travel_assistant.routes.storeRecord', side_effect=store), \
         patch('modules.fr11_chatbot_travel_assistant.routes.retrieveRecord', side_effect=retrieve), \
         patch('modules.fr11_chatbot_travel_assistant.routes.updateRecord', side_effect=update), \
         patch('modules.fr11_chatbot_travel_assistant.routes.generateChatbotResponse', return_value=service_result), \
         patch('modules.fr11_chatbot_travel_assistant.routes.generateFollowUpResponse', return_value=service_result):
        first = client.post(
            '/api/fr11/chat', headers={'Authorization': 'Bearer valid_test_token'},
            json={'message': 'Plan 3 days in Penang for 2 people with RM1500.'},
        ).get_json()
        session_id = first['session']['id']

        second = client.post(
            '/api/fr11/chat', headers={'Authorization': 'Bearer valid_test_token'},
            json={'sessionId': session_id, 'message': 'Do not include museums or shopping malls.'},
        ).get_json()
        second_plan = second['item']['tripPlan']
        assert second['source'] == 'travelmate-assistant'
        assert 'Museum, Shopping Mall' in second['reply']
        second_text = ' '.join(item['activityName'] for item in second_plan['activities']).lower()
        assert 'museum' not in second_text
        assert 'mall' not in second_text

        third_response = client.post(
            '/api/fr11/chat', headers={'Authorization': 'Bearer valid_test_token'},
            json={'sessionId': session_id, 'message': 'It is raining heavily, suggest indoor alternatives.'},
        )

    assert third_response.status_code == 200
    third = third_response.get_json()
    state = third['session']['planningState']
    assert state['destinationArea'] == 'Penang'
    assert state['tripDays'] == 3
    assert state['travellerCount'] == 2
    assert state['budgetLimit'] == 1500.0
    assert state['excludedActivityTypes'] == ['Museum', 'Shopping Mall']
    assert state['preferIndoor'] is True
    assert third['source'] == 'travelmate-assistant'
    third_plan = third['item']['tripPlan']
    assert third_plan['preferIndoor'] is True
    assert third_plan['excludedActivityTypes'] == ['Museum', 'Shopping Mall']
    assert third_plan['activities']
    assert all(item['indoor'] is True for item in third_plan['activities'])
    third_text = ' '.join(item['activityName'] for item in third_plan['activities']).lower()
    assert 'museum' not in third_text
    assert 'mall' not in third_text


def test_route_exposes_constraint_conflict_without_a_saveable_plan(client, mock_traveller_auth):
    service_result = {'reply': 'Unsafe provider wording', 'source': 'gemini'}
    with patch('modules.fr11_chatbot_travel_assistant.routes.retrieveRecord', return_value=[]), \
         patch('modules.fr11_chatbot_travel_assistant.routes.storeRecord') as store, \
         patch('modules.fr11_chatbot_travel_assistant.routes.updateRecord') as update, \
         patch('modules.fr11_chatbot_travel_assistant.routes.generateChatbotResponse', return_value=service_result), \
         patch('modules.fr11_chatbot_travel_assistant.routes.build_structured_trip_plan', return_value=(None, 'constraint_conflict')):
        store.side_effect = lambda collection, data: {'id': f'{collection}_1', **data}
        update.side_effect = lambda collection, record_id, data: {'id': record_id, **data}
        response = client.post(
            '/api/fr11/chat', headers={'Authorization': 'Bearer valid_test_token'},
            json={'message': 'Plan an indoor only Penang trip with no museums.'},
        )

    assert response.status_code == 200
    data = response.get_json()
    assert data['source'] == 'travelmate-assistant'
    assert data['item']['constraintConflict']['status'] == 'constraint_conflict'
    assert data['item']['constraintConflict']['excludedActivityTypes'] == ['Museum']
    assert data['item']['constraintConflict']['preferIndoor'] is True
    assert 'tripPlan' not in data['item']
    assert 'prohibited or outdoor substitutes' in data['reply']
