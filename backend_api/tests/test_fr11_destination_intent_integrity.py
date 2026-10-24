from contextlib import ExitStack
from copy import deepcopy
from unittest.mock import patch

import pytest

from modules.fr11_chatbot_travel_assistant.nlp_extractor import (
    classify_detailed_intent,
    extract_geographic_entities,
)


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

        yield send, database


def test_parser_preserves_road_trip_order_and_destination_change_distinction():
    road_trip = extract_geographic_entities('Plan a road trip from Penang to Melaka.')
    assert road_trip['is_multi_destination'] is True
    assert road_trip['multiple_destinations'] == ['Penang', 'Melaka City']
    assert road_trip['origin_destination'] == 'Penang'
    assert road_trip['target_destination'] == 'Melaka City'

    replacement = extract_geographic_entities('Change our destination from Penang to Melaka.')
    assert replacement['is_destination_change'] is True
    assert replacement['is_multi_destination'] is False
    assert replacement['destination_area'] == 'Melaka City'


def test_destination_replacement_updates_state_without_flight_guidance(offline_chat):
    send, _ = offline_chat
    initial = send('Plan 3 days in Penang for 2 people with RM1500.')
    with patch(
        'modules.fr11_chatbot_travel_assistant.routes.generateFollowUpResponse',
        side_effect=AssertionError('destination replacement must be deterministic'),
    ):
        changed = send(
            'Change our destination from Penang to Melaka.',
            initial['session']['id'],
        )

    state = changed['session']['planningState']
    assert state['destinationArea'] == 'Melaka City'
    assert state['destinationState'] == 'Melaka'
    assert state['tripMode'] == 'single_destination'
    assert 'multipleDestinations' not in state
    assert state['budgetLimit'] == 1500.0
    assert state['travellerCount'] == 2
    assert changed['item']['tripPlan']['destinationArea'] == 'Melaka City'
    assert 'changed the active destination' in changed['reply']
    assert 'Flights' not in changed['reply']


def test_road_trip_state_is_ordered_and_never_exposes_single_city_plan(offline_chat):
    send, _ = offline_chat
    with patch(
        'modules.fr11_chatbot_travel_assistant.routes.generateChatbotResponse',
        side_effect=AssertionError('unsupported road trip must be deterministic'),
    ):
        result = send('Plan a road trip from Penang to Melaka.')

    state = result['session']['planningState']
    assert state['tripMode'] == 'road_trip'
    assert state['multipleDestinations'] == ['Penang', 'Melaka City']
    assert state['originDestination'] == 'Penang'
    assert state['targetDestination'] == 'Melaka City'
    assert 'tripPlan' not in result['item']
    assert result['item']['constraintConflict']['status'] == 'unsupported_multi_destination'
    assert 'one destination at a time' in result['reply']
    assert result['source'] == 'travelmate-assistant'


def test_normal_penang_plan_and_valid_airport_route_keep_distinct_intents(offline_chat):
    send, _ = offline_chat
    plan = send('Plan three days in Penang.')
    assert plan['session']['planningState']['destinationArea'] == 'Penang'
    assert plan['item']['tripPlan']['destinationArea'] == 'Penang'
    assert 'Flights' not in plan['reply']

    flight = send('How can I search for flights from PEN to KUL?')
    assert classify_detailed_intent('How can I search for flights from PEN to KUL?') == 'FLIGHT_ENQUIRY'
    assert 'Home → Flights' in flight['reply']
    assert 'tripPlan' not in flight['item']


@pytest.mark.parametrize(
    'message',
    [
        'Change our destination from Penang to Melaka.',
        'Tell me about Penang heritage.',
        'Plan three days in Penang.',
    ],
)
def test_place_names_do_not_trigger_airport_code_flight_intent(message):
    assert classify_detailed_intent(message) != 'FLIGHT_ENQUIRY'


def test_road_trip_can_transition_to_single_destination_without_losing_constraints(offline_chat):
    send, _ = offline_chat
    road_trip = send(
        'Plan an indoor only 3-day road trip from Penang to Melaka for 2 people with RM1500 and no museums.'
    )
    single = send('Plan three days in Penang.', road_trip['session']['id'])

    state = single['session']['planningState']
    assert state['tripMode'] == 'single_destination'
    assert state['destinationArea'] == 'Penang'
    assert 'multipleDestinations' not in state
    assert 'originDestination' not in state
    assert 'targetDestination' not in state
    assert state['budgetLimit'] == 1500.0
    assert state['travellerCount'] == 2
    assert state['preferIndoor'] is True
    assert state['excludedActivityTypes'] == ['Museum']
    assert single['item']['tripPlan']['excludedActivityTypes'] == ['Museum']


def test_latest_destination_change_overrides_stale_single_destination(offline_chat):
    send, _ = offline_chat
    initial = send('Plan three days in Penang.')
    changed = send('Change our destination from Penang to Melaka.', initial['session']['id'])
    changed_again = send('Change our destination from Melaka to Kuala Lumpur.', changed['session']['id'])
    assert changed_again['session']['planningState']['destinationArea'] == 'Kuala Lumpur'
    assert changed_again['item']['tripPlan']['destinationArea'] == 'Kuala Lumpur'


def test_explicit_road_trip_payload_is_rejected_before_persistence(client, mock_traveller_auth):
    road_trip_plan = {
        'tripMode': 'road_trip',
        'multipleDestinations': ['Penang', 'Melaka City'],
        'title': 'Penang to Melaka road trip',
        'destinationArea': 'Melaka City',
        'startDate': '2026-11-01',
        'endDate': '2026-11-03',
        'budgetLimit': 1500,
        'numberOfTravellers': 2,
        'activities': [{'activityName': 'Misleading single-city activity', 'dayNo': 1}],
    }
    with patch('modules.fr11_chatbot_travel_assistant.routes.storeRecord') as store, \
         patch('modules.fr11_chatbot_travel_assistant.routes.createItinerary') as create_itinerary:
        response = client.post(
            '/api/fr11/save-plan',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'plan': road_trip_plan},
        )
    assert response.status_code == 400
    assert 'not saveable' in response.get_json()['error']
    store.assert_not_called()
    create_itinerary.assert_not_called()


def test_chat_sessions_do_not_share_road_trip_state(offline_chat):
    send, database = offline_chat
    road_trip = send('Plan a road trip from Penang to Melaka.')
    separate = send('Plan three days in Penang.')

    assert road_trip['session']['id'] != separate['session']['id']
    assert road_trip['session']['planningState']['tripMode'] == 'road_trip'
    assert separate['session']['planningState']['tripMode'] == 'single_destination'
    assert 'multipleDestinations' not in separate['session']['planningState']
    assert len(database['chat_sessions']) == 2
