"""Owner-scoped real FR11 conversations; providers and storage are fixture-only."""
from copy import deepcopy

import pytest

from modules.fr11_chatbot_travel_assistant import routes
from test_chatbot_saved_preview import conversation, select
from test_chatbot_context_quality import places, seed_results
from test_chatbot_personal_questions import personal
from test_chatbot_saved_history import revisions, change_and_save, save
from modules.fr11_chatbot_travel_assistant import contextual_intent as context


@pytest.mark.parametrize('question', [
    'What kind of traveller am I?', 'Can explain my prefrences ah?',
    'What are my travel interests?',
])
def test_natural_personal_questions_use_saved_profile_not_generated_personality(conversation, question):
    records, writes, providers, talk = conversation
    records['travel_preferences'] = {'test_traveller_uid': {
        'travellerId': 'test_traveller_uid', 'travelPersonality': 'Explorer', 'interests': ['Nature']}}
    result = talk(question)
    assert result['item']['ownPreferences']['travelPersonality'] == 'Explorer'
    assert not providers and set(writes) <= {'chat_sessions', 'chat_messages'}


def test_semantic_read_tool_works_without_active_plan_and_cannot_choose_a_trip(conversation, monkeypatch):
    records, writes, providers, talk = conversation
    calls = []
    monkeypatch.setattr(routes, 'interpretChatbotIntent', lambda prompt: calls.append(prompt) or {
        'intent': 'capability', 'confidence': .97, 'capability': 'budget', 'mode': 'read'})
    result = talk('The holiday numbers are doing my head in lah')
    assert len(calls) == 1 and not providers
    assert len(result['session']['planningState']['personalContext']['choices']) == 5
    selected = talk('2', result['session']['id'])
    assert selected['item']['budgetReasoning']['available']
    assert selected['session']['planningState']['personalContext']['tripId'] == 'trip2'
    assert len(calls) == 1 and set(writes) <= {'chat_sessions', 'chat_messages'}


@pytest.mark.parametrize('question,expected', [
    ('How does personality-based recommendation work?', '60'),
    ('What does Smart Packing do?', 'checklist'),
    ('Does payment mean the supplier confirmed my reservation?', 'separate'),
    ('What is the difference between a trip and a tourism package?', 'package'),
])
def test_verified_app_help_interrupts_trip_selection_without_losing_it(conversation, question, expected):
    records, _, providers, talk = conversation
    first = talk('Adjust my itinerary')
    sid = first['session']['id']
    before = deepcopy(records['chat_sessions'][sid]['planningState']['adjustment'])
    result = talk(question, sid)
    assert expected in result['reply'].lower()
    assert result['session']['planningState']['adjustment'] == before
    assert not providers
    assert talk('Adjust trip 2', sid)['session']['planningState']['adjustment']['tripId'] == 'trip2'


def test_packing_interrupt_preserves_draft_and_offers_existing_navigation(conversation):
    records, writes, _, talk = conversation
    sid = select(conversation)
    talk('Set the budget to RM700', sid)
    before = deepcopy(records['chat_sessions'][sid]['planningState'])
    result = talk('Should I bring an umbrella?', sid)
    assert 'not a live forecast' in result['reply']
    assert {'kind': 'packing'} in result['item']['assistantActions']
    assert result['session']['planningState']['activePlan'] == before['activePlan']
    assert result['session']['planningState']['adjustment'] == before['adjustment']
    assert 'itineraries' not in writes


def test_return_to_earlier_selected_place_after_other_results_and_weather(conversation, monkeypatch):
    records, writes, _, talk = conversation
    sid = seed_results(conversation)
    monkeypatch.setattr(routes, '_planning_catalog', lambda *args, **kwargs: places())
    talk('The second one', sid)
    talk('Anything cheaper nearby?', sid)  # Next result list differs.
    talk('What if it rains?', sid)
    result = talk('Anyway, back to the second place', sid)
    assert 'Recorded place 2' in result['reply']
    assert result['session']['planningState']['selectedResult']['id'] == 'place2'
    assert 'Recorded place 2' in talk('Why?', sid)['reply']
    assert 'itineraries' not in writes


def test_selected_place_child_suitability_uses_metadata_not_an_inferred_preference(conversation):
    _, _, _, talk = conversation
    selected = places()
    selected[1]['familyFriendly'] = False
    sid = seed_results(conversation, rows=selected)
    talk('The second one', sid)
    result = talk('Is it suitable for children?', sid)
    assert 'not family-friendly' in result['reply']
    assert result['session']['planningState']['selectedResult']['id'] == 'place2'


def test_help_and_personal_reads_do_not_hijack_selected_public_place(conversation):
    _, _, _, talk = conversation
    sid = seed_results(conversation)
    talk('The second one', sid)
    result = talk('This one expensive ah?', sid)
    assert '20.00' in result['reply'] and 'budgetReasoning' not in result['item']


@pytest.mark.parametrize('question', ['Where am I staying?', 'Which flight did I choose?',
    'Did I already select a hotel?'])
def test_selected_travel_paraphrases_reuse_owner_read_tools(personal, question):
    records, writes, providers, talk = personal
    sid = select(personal)
    records['itineraries']['trip5']['selectedHotel'] = {'hotelName': 'Recorded Hotel', 'totalPrice': 240, 'currency': 'MYR'}
    result = talk(question, sid)
    assert 'selectedTravel' in result['item']
    assert 'supplier confirmation' in result['reply']
    assert not providers and set(writes) <= {'chat_sessions', 'chat_messages'}


def test_budget_interrupt_resume_and_natural_group_basis_corrections(personal):
    _, writes, _, talk = personal
    first = talk('Explain my trip budget')
    sid = first['session']['id']
    talk('5', sid)
    assert 'budgetReasoning' in talk('Is that including flights?', sid)['item']
    assert 'budgetReasoning' in talk('Why is the total so high?', sid)['item']
    assert 'budgetReasoning' in talk('Which costs are still unknown?', sid)['item']
    scenario = talk('What if four people go instead?', sid)['item']['budgetReasoning']
    assert scenario['travellerCount'] == 4
    scenario = talk('Actually RM500 each person', sid)['item']['budgetReasoning']
    assert scenario['travellerCount'] == 4 and scenario['budgetLimit'] == 2000
    talk('What if it rains?', sid)
    resumed = talk('Back to my previous question', sid)
    assert resumed['session']['planningState']['personalContext']['tripId'] == 'trip5'
    assert resumed['item']['budgetReasoning']['budgetLimit'] == 2000
    assert 'itineraries' not in writes


def test_natural_budget_corrections_preserve_cents_and_reject_fractional_people(personal):
    _, writes, _, talk = personal
    sid = select(personal)
    result = talk('What if my budget were RM500.50 each person for two people?', sid)
    assert result['item']['budgetReasoning']['budgetLimit'] == 1001
    invalid = talk('What if my trip had 3.5 people?', sid)
    assert 'budgetReasoning' not in invalid['item'] and 'whole' in invalid['reply']
    assert 'itineraries' not in writes


@pytest.mark.parametrize('output', [None, {'intent': 'capability', 'confidence': .7, 'capability': 'budget', 'mode': 'read'},
    {'intent': 'capability', 'confidence': 1, 'capability': 'orders', 'mode': 'refund'},
    {'intent': 'capability', 'confidence': 1, 'capability': 'budget', 'mode': 'read', 'tripId': 'trip1'},
    {'intent': 'capability', 'confidence': 1, 'capability': 'packing', 'mode': 'read'},
    {'intent': 'capability', 'confidence': 1, 'capability': {}, 'mode': 'read'},
    {'intent': 'capability', 'confidence': 1, 'capability': 'orders', 'mode': []},
    {'intent': 'capability', 'confidence': 1, 'capability': 'firebase_admin', 'mode': 'read'},
])
def test_invalid_model_cannot_read_choose_or_mutate_records(conversation, monkeypatch, output):
    records, writes, providers, talk = conversation
    before = deepcopy(records['itineraries'])
    calls = []
    monkeypatch.setattr(routes, 'interpretChatbotIntent', lambda p: calls.append(p) or output)
    result = talk('The holiday numbers are confusing me')
    assert len(calls) == 1 and not providers
    assert 'budgetReasoning' not in result['item'] and 'personalOrders' not in result['item']
    assert set(writes) <= {'chat_sessions', 'chat_messages'} and records['itineraries'] == before


@pytest.mark.parametrize('error', [TimeoutError(), RuntimeError('429'), RuntimeError('503'), RuntimeError('504')])
def test_unavailable_interpretation_gives_grounded_clarification_once(conversation, monkeypatch, error):
    _, _, providers, talk = conversation
    calls = []
    def interpret(prompt):
        calls.append(prompt)
        raise error
    monkeypatch.setattr(routes, 'interpretChatbotIntent', interpret)
    result = talk('The holiday numbers are confusing me lah')
    assert len(calls) == 1 and not providers
    assert 'saved trip' in result['reply'] and 'budget' in result['reply']
    assert '429' not in result['reply'] and '503' not in result['reply']


def test_semantic_discovery_uses_profile_and_grounded_catalogue_without_mutation(conversation, monkeypatch):
    records, writes, providers, talk = conversation
    records['travel_preferences'] = {'test_traveller_uid': {'interests': ['Nature']}}
    monkeypatch.setattr(routes, 'interpretChatbotIntent', lambda p: {'intent': 'discover', 'confidence': .96})
    result = talk('Suggest somewhere suitable for my personality')
    assert result['item']['placeSuggestions']
    from services.recommendation_taxonomy import candidate_concepts, concepts_for
    assert all(candidate_concepts(r) & concepts_for(['Nature']) for r in result['item']['placeSuggestions'])
    assert set(writes) <= {'chat_sessions', 'chat_messages'} and not providers


def test_model_prompt_has_capabilities_pending_read_state_but_no_personal_records(conversation, monkeypatch):
    records, _, _, talk = conversation
    first = talk('Explain my trip budget')
    sid = first['session']['id']
    calls = []
    monkeypatch.setattr(routes, 'interpretChatbotIntent', lambda p: calls.append(p) or {
        'intent': 'capability', 'confidence': .99, 'capability': 'packing', 'mode': 'help'})
    talk('Can you help me prepare what I need?', sid)
    assert len(calls) == 1 and len(calls[0]) <= 6000
    assert 'Verified capabilities' in calls[0] and 'choiceCount' in calls[0] and 'budget' in calls[0]
    assert 'trip1' not in calls[0] and 'must-not-appear' not in calls[0] and 'test_traveller_uid' not in calls[0]
    assert records['chat_sessions'][sid]['planningState']['personalContext']['choices']


def test_long_interpretation_context_retains_the_actual_message_within_provider_limit():
    import json
    calls = []
    state = {'destinationArea': 'Penang', 'interests': ['Nature'] * 8,
             'excludedInterests': ['Shopping'] * 8, 'guidedActive': True}
    messages = [{'message': 'Details ' * 500, 'reply': 'Context ' * 500} for _ in range(5)]
    context.resolve_turn('The holiday vibe is puzzling me', state, messages,
                         interpret=lambda p: calls.append(p))
    assert len(calls) == 1 and len(calls[0]) <= 6000
    assert calls[0].endswith('The holiday vibe is puzzling me')
    assert isinstance(json.loads(calls[0].split('\nContext: ')[1].split('\nMessage: ')[0]), dict)


def test_capability_reads_recheck_account_and_sessions_after_reopening(conversation, monkeypatch, client):
    records, _, _, talk = conversation
    first = talk('Explain my trip budget')
    sid = first['session']['id']
    talk('5', sid)
    records['itineraries']['trip5']['travellerId'] = 'different-account'
    calls = []
    monkeypatch.setattr(routes, 'interpretChatbotIntent', lambda p: calls.append(p) or {
        'intent': 'capability', 'confidence': .98, 'capability': 'budget', 'mode': 'read'})
    reopened = client.get('/api/fr11/sessions/' + sid, headers={'Authorization': 'Bearer fixture'})
    assert reopened.status_code == 200
    result = talk('Those holiday figures still puzzle me', sid)
    assert 'no longer available' in result['reply'] and 'budgetReasoning' not in result['item']
    other = talk('Hi')['session']['id']
    assert 'personalContext' not in records['chat_sessions'][other]['planningState']
    records['chat_sessions'][sid]['travellerId'] = 'different-account'
    assert client.get('/api/fr11/sessions/' + sid, headers={'Authorization': 'Bearer fixture'}).status_code == 404


def test_bookmarks_are_bounded_and_ambiguous_earlier_lists_do_not_guess():
    state = {}
    messages = []
    for i in range(6):
        item = {'id': str(i), 'placeSuggestions': [{**r, 'destinationId': f'p{i}_{j}'} for j, r in enumerate(places())]}
        context.remember_results(state, item)
        state['selectedResult'] = {'kind': 'place', 'id': item['placeSuggestions'][1]['destinationId']}
        messages.append(item)
    assert len(state['recentSelections']) == 3
    assert len(str(state['recentSelections'])) < 350
    result = context.resolve_turn('Back to the second place', state, messages)
    assert 'will not guess' in result['response']['reply']


@pytest.mark.parametrize('condition', ['pending_draft', 'missing_history', 'commercial_selection'])
def test_reported_restore_blocks_are_safe_setup_conditions_not_implicit_writes(revisions, client, condition):
    records, writes, _, talk = revisions
    sid = change_and_save(revisions, client)
    if condition == 'pending_draft':
        pending = talk('Set the budget to RM900', sid)
        assert pending['session']['planningState'].get('activePlan'), pending['reply']
        assert pending['session']['planningState']['adjustment']['fingerprint'] == routes._trip_fingerprint(records['itineraries']['trip5'])
    elif condition == 'missing_history':
        records['itineraries']['trip5'].pop('itineraryHistory')
    else:
        records['itineraries']['trip5']['selectedHotel'] = {'hotelId': 'fixture-hotel'}
    before = deepcopy(records['itineraries'])
    write_count = writes.count('itineraries')
    result = talk('Restore version 1', sid)
    assert 'proposedPlan' not in result['item']
    assert records['itineraries'] == before and writes.count('itineraries') == write_count


def test_restoration_cancel_confirm_and_reopen_use_existing_batch_a_flow(revisions, client):
    records, _, _, talk = revisions
    sid = change_and_save(revisions, client)
    proposed = talk('Restore version 1', sid)['item']['proposedPlan']
    assert save(client, sid, proposed, confirmed=False).status_code == 400
    talk('Undo changes', sid)
    assert records['itineraries']['trip5']['budgetLimit'] == 700
    proposed = talk('Restore version 1', sid)['item']['proposedPlan']
    assert save(client, sid, proposed).status_code == 200
    assert talk('Show my trip', sid)['item']['tripPlan']['budgetLimit'] == 500
    reopened = client.get('/api/fr5/itineraries/trip5', headers={'Authorization': 'Bearer fixture'})
    assert reopened.status_code == 200 and reopened.json['itinerary']['budgetLimit'] == 500
