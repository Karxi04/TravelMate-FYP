from contextlib import ExitStack
from copy import deepcopy
from unittest.mock import patch

import pytest

from modules.fr11_chatbot_travel_assistant.nlp_extractor import (
    extract_duration,
    extract_excluded_interests,
    extract_indoor_preference,
    extract_interests,
    extract_travellers,
)


@pytest.mark.parametrize(
    'message',
    [
        'Suggest rain-safe alternatives in George Town.',
        'Suggest rain safe alternatives in George Town.',
        'Suggest indoor alternatives in George Town.',
        'Suggest sheltered attractions in George Town.',
        'Avoid outdoor activities in George Town.',
    ],
)
def test_indoor_constraint_phrases_are_recognized(message):
    assert extract_indoor_preference(message) is True


def test_weather_forecast_alone_does_not_enable_indoor_only_mode():
    assert extract_indoor_preference('What is the weather forecast for George Town?') is None


@pytest.mark.parametrize(
    'message',
    [
        'I do not want outdoor beach activities.',
        'Avoid beach activities.',
        'No beaches, please.',
    ],
)
def test_beach_negation_is_extracted(message):
    assert extract_excluded_interests(message) == ['Beach']


def test_positive_beach_preference_is_not_excluded():
    assert extract_excluded_interests('I enjoy beaches.') == []


def test_swimming_exclusion_does_not_overstate_beach_taxonomy():
    message = 'I like coastal views but want to avoid swimming.'
    assert extract_interests(message) == ['Beach']
    assert extract_excluded_interests(message) == []


@pytest.mark.parametrize(
    ('message', 'expected_duration', 'expected_travellers'),
    [
        ('George Town for 2 days.', 2, None),
        ('Penang for 3 nights.', 4, None),
        ('Plan a trip for 2 people.', None, 2),
        ('Book for 3 adults.', None, 3),
        ('There are 4 travellers.', None, 4),
        ('Five days for two people.', 5, 2),
        ('Plan 3 days in Melaka for 2 adults and 1 child.', 3, 3),
    ],
)
def test_duration_numbers_are_not_mistaken_for_travellers(
    message, expected_duration, expected_travellers
):
    assert extract_duration(message) == expected_duration
    assert extract_travellers(message) == expected_travellers


@pytest.fixture
def offline_chat(client, mock_traveller_auth):
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
        database[collection][record_id].update(deepcopy(changes))
        return deepcopy(database[collection][record_id])

    service_result = {'reply': 'Mocked offline response', 'source': 'travelmate-assistant'}
    with ExitStack() as stack:
        stack.enter_context(patch(
            'modules.fr11_chatbot_travel_assistant.routes.storeRecord', side_effect=store
        ))
        stack.enter_context(patch(
            'modules.fr11_chatbot_travel_assistant.routes.retrieveRecord', side_effect=retrieve
        ))
        stack.enter_context(patch(
            'modules.fr11_chatbot_travel_assistant.routes.updateRecord', side_effect=update
        ))
        stack.enter_context(patch(
            'modules.fr11_chatbot_travel_assistant.routes.generateChatbotResponse',
            return_value=service_result,
        ))
        stack.enter_context(patch(
            'modules.fr11_chatbot_travel_assistant.routes.generateFollowUpResponse',
            return_value=service_result,
        ))

        def send(message, session_id=None):
            payload = {'message': message}
            if session_id:
                payload['sessionId'] = session_id
            response = client.post(
                '/api/fr11/chat',
                headers={'Authorization': 'Bearer valid_test_token'},
                json=payload,
            )
            assert response.status_code == 200
            return response.get_json()

        yield send


def test_route_persists_rain_safe_preference_without_losing_constraints(offline_chat):
    first = offline_chat(
        'Plan 3 days in Penang for 2 people with RM1500 and no museums.'
    )
    result = offline_chat(
        'Suggest rain-safe alternatives.', first['session']['id']
    )

    state = result['session']['planningState']
    assert state['destinationArea'] == 'Penang'
    assert state['tripDays'] == 3
    assert state['travellerCount'] == 2
    assert state['budgetLimit'] == 1500.0
    assert state['excludedActivityTypes'] == ['Museum']
    assert state['preferIndoor'] is True
    assert 'tripPlan' not in result['item']


def test_route_persists_beach_exclusion_across_turns(offline_chat):
    first = offline_chat(
        'Plan a weekend in Langkawi for 2 people with RM1200. We enjoy beaches.'
    )
    excluded = offline_chat(
        'I do not want outdoor beach activities.', first['session']['id']
    )
    retained = offline_chat('Make it 3 days.', excluded['session']['id'])

    state = retained['session']['planningState']
    assert state['destinationArea'] == 'Langkawi'
    assert state['budgetLimit'] == 1200.0
    assert state['travellerCount'] == 2
    assert state['excludedInterests'] == ['Beach']
    assert 'Beach' not in state.get('interests', [])
    plan = retained['item']['tripPlan']
    assert plan['excludedInterests'] == ['Beach']
    assert all(item.get('category') != 'Beach' for item in plan['activities'])


def test_route_does_not_store_trip_duration_as_traveller_count(offline_chat):
    result = offline_chat('Plan a trip to George Town for 2 days with RM500.')

    state = result['session']['planningState']
    assert state['destinationArea'] == 'George Town'
    assert state['tripDays'] == 2
    assert state['budgetLimit'] == 500.0
    assert 'travellerCount' not in state
