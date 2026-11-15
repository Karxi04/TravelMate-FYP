"""Saved-trip inspection and interrupted editing use owned, immutable fixture records."""
from copy import deepcopy

import pytest

from modules.fr11_chatbot_travel_assistant import routes


@pytest.mark.parametrize('message,expected', [
    ('Can u show me first the plan?', True), ("What's on Day 2?", True),
    ('Show the second day', True), ('pls shw me the itenary first lah', True),
    ('Show proposed changes', True), ('What have I planned?', True),
    ('Do not show my plan, change Day 2', False), ('Show the weather for Day 2', False),
    ('Remove the second activity', False), ('Show my hotel booking', False),
])
def test_inspection_intent_uses_action_and_context_object(message, expected):
    from modules.fr11_chatbot_travel_assistant.nlp_extractor import itinerary_view_request
    assert itinerary_view_request(message) is expected


@pytest.fixture
def conversation(client, mock_traveller_auth, monkeypatch):
    activities = [{'activityId': f'a{day}{slot}', 'destinationId': f'p{day}{slot}',
                   'activityName': f'Saved stop {day}.{slot}', 'dayNo': day,
                   'timeSlot': '09:00 - 10:00', 'estimatedCost': 0,
                   'gps_coordinates': {'latitude': 5.41, 'longitude': 100.33}}
                  for day in (1, 2, 3) for slot in (1, 2)]
    records = {'itineraries': {f'trip{i}': {
        'id': f'trip{i}', 'travellerId': 'test_traveller_uid',
        'title': f'3-Day Penang Itinerary Plan {i}', 'destinationArea': 'Penang',
        'startDate': '2027-02-10', 'endDate': '2027-02-12', 'budgetLimit': 500,
        'travellerCount': 2, 'activities': deepcopy(activities),
        'dailySchedule': [{'dayNo': day, 'activities': deepcopy([a for a in activities if a['dayNo'] == day])}
                          for day in (1, 2, 3)], 'privateSentinel': 'must-not-appear-in-preview',
    } for i in range(1, 6)}, 'chat_sessions': {}, 'chat_messages': {}}
    writes, providers = [], []

    def read(collection, id=None, **kwargs):
        rows = records.get(collection, {})
        return deepcopy(rows.get(id) if id else list(rows.values()))

    def store(collection, data, *args):
        key = args[0] if args else f'{collection}_{len(records.setdefault(collection, {})) + 1}'
        writes.append(collection)
        records[collection][key] = {'id': key, **deepcopy(data)}
        return deepcopy(records[collection][key])

    def update(collection, id, data, expected=None):
        row = records[collection][id]
        assert expected is None or row == expected
        writes.append(collection)
        if collection == 'chat_sessions' and set(data) == {'planningState'}:
            row['planningState'].update(deepcopy(data['planningState']))
        else:
            row.update(deepcopy(data))
        return deepcopy(row)

    def assistant(message, *args, **kwargs):
        providers.append(message)
        return {'reply': 'TravelMate can help with that topic.', 'source': 'travelmate-assistant'}

    for name, func in [('retrieveRecord', read), ('storeRecord', store), ('updateRecord', update),
                       ('generateChatbotResponse', assistant), ('generateFollowUpResponse', assistant)]:
        monkeypatch.setattr(routes, name, func)
    monkeypatch.setattr(routes, '_planning_catalog', lambda *args, **kwargs: pytest.fail('Viewing must not plan or call providers'))

    def talk(message, sid=None):
        response = client.post('/api/fr11/chat', headers={'Authorization': 'Bearer fixture'},
                               json={'message': message, 'sessionId': sid, 'guidedPlanning': True})
        assert response.status_code == 200, response.json
        return response.json

    return records, writes, providers, talk


def select(conversation):
    _, _, _, talk = conversation
    first = talk('Adjust my itinerary')
    sid = first['session']['id']
    selected = talk('Adjust trip 5', sid)
    assert selected['session']['planningState']['adjustment']['tripId'] == 'trip5'
    return sid


@pytest.mark.parametrize('message', [
    'Show my trip.', 'Show me the itinerary.', 'Can I see the plan first?',
    'Can u show me first the plan?', 'Show me the trip first.', 'What have I planned?',
    'Let me check the itinerary before editing.', 'pls shw me the itenary first lah',
])
def test_saved_preview_paraphrases_are_real_read_only_records(conversation, message):
    records, writes, providers, talk = conversation
    sid = select(conversation)
    before = deepcopy(records['itineraries'])
    result = talk(message, sid)
    plan = result['item']['tripPlan']
    assert plan['viewOnly'] is True and plan['savedTripId'] == 'trip5'
    assert plan['activities'] == before['trip5']['activities']
    assert (plan['startDate'], plan['endDate'], plan['destinationArea'], plan['budgetLimit']) == (
        '2027-02-10', '2027-02-12', 'Penang', 500)
    assert 'privateSentinel' not in plan and 'must-not-appear-in-preview' not in str(result)
    assert 'draftId' not in plan and 'adjustmentTripId' not in plan
    assert records['itineraries'] == before and 'itineraries' not in writes and not providers


def test_exact_vivo_conversation_view_interrupts_day_question(conversation):
    records, writes, providers, talk = conversation
    sid = select(conversation)
    before = deepcopy(records['itineraries'])
    assert 'which' in talk('no, just change some place', sid)['reply'].lower()
    assert talk('can u show me first the plan', sid)['item']['tripPlan']['savedTripId'] == 'trip5'
    assert 'Day 2' in talk('change second day', sid)['reply']
    result = talk('show me the trip first', sid)
    assert result['item']['tripPlan']['viewOnly']
    assert result['session']['planningState']['adjustment']['pendingDay'] == 2
    day = talk("What's on Day 2?", sid)['item']['tripPlan']
    assert day['previewDay'] == 2
    assert [a['activityName'] for a in day['activities']] == ['Saved stop 2.1', 'Saved stop 2.2']
    assert records['itineraries'] == before and 'itineraries' not in writes and not providers


def test_historical_missing_and_schedule_only_previews_do_not_generate(conversation):
    records, _, _, talk = conversation
    sid = select(conversation)
    trip = records['itineraries']['trip5']
    trip.update(startDate='2020-02-10', endDate='2020-02-12')
    trip.pop('activities')
    result = talk('Show the second day', sid)['item']['tripPlan']
    assert result['startDate'] == '2020-02-10'
    assert len(result['activities']) == 2 and result['previewDay'] == 2
    trip['dailySchedule'] = []
    result = talk('Show my trip', sid)['item']['tripPlan']
    assert result['activities'] == []


def test_missing_dates_and_null_optional_fields_remain_honest(conversation):
    records, writes, _, talk = conversation
    sid = select(conversation)
    trip = records['itineraries']['trip5']
    trip.pop('startDate')
    trip.pop('endDate')
    trip['activities'] = None
    trip['dailySchedule'] = None
    plan = talk('Show my trip', sid)['item']['tripPlan']
    assert plan['activities'] == [] and 'startDate' not in plan and 'endDate' not in plan
    response = talk('Show Day 2', sid)
    assert 'outside' in response['reply'] and 'tripPlan' not in response['item']
    assert 'itineraries' not in writes


@pytest.mark.parametrize('change', ['deleted', 'foreign'])
def test_unavailable_owned_selection_never_leaks_even_an_existing_draft(conversation, change):
    records, _, _, talk = conversation
    sid = select(conversation)
    talk('Set the budget to RM400', sid)
    if change == 'deleted':
        del records['itineraries']['trip5']
    else:
        records['itineraries']['trip5']['travellerId'] = 'someone-else'
    response = talk('Show me the trip first', sid)
    assert 'tripPlan' not in response['item']
    assert 'adjustment' not in response['session']['planningState']
    assert 'activePlan' not in response['session']['planningState']


def test_external_edit_invalidates_draft_but_view_uses_current_details(conversation):
    records, writes, _, talk = conversation
    sid = select(conversation)
    old = talk('Set the budget to RM400', sid)['item']['tripPlan']
    records['itineraries']['trip5']['budgetLimit'] = 600
    response = talk('Show me the trip first', sid)
    assert response['item']['tripPlan']['budgetLimit'] == 600
    assert 'activePlan' not in response['session']['planningState']
    assert 'changed' in response['reply'].lower() and 'itineraries' not in writes


@pytest.mark.parametrize('message', ['Cancel changes', 'Never mind', 'nvm', 'leave it unchanged'])
def test_cancellation_never_saves(conversation, message):
    records, writes, _, talk = conversation
    sid = select(conversation)
    before = deepcopy(records['itineraries'])
    talk('Set the budget to RM400', sid)
    result = talk(message, sid)
    assert 'adjustment' not in result['session']['planningState']
    assert 'activePlan' not in result['session']['planningState']
    assert records['itineraries'] == before and 'itineraries' not in writes


def test_preview_does_not_replace_draft_and_cannot_be_saved(client, conversation):
    records, _, _, talk = conversation
    sid = select(conversation)
    draft = talk('Set the budget to RM400', sid)['item']['tripPlan']
    result = talk('Show my trip', sid)
    preview = result['item']['tripPlan']
    assert preview['budgetLimit'] == 500
    assert result['session']['planningState']['activePlan'] == draft
    assert talk('Show proposed changes', sid)['item']['tripPlan'] == draft
    for with_session in (False, True):
        response = client.post('/api/fr11/save-plan', headers={'Authorization': 'Bearer fixture'}, json={
            'plan': preview, 'confirmed': True, **({'sessionId': sid} if with_session else {})})
        assert response.status_code == 400
    saved = client.post('/api/fr11/save-plan', headers={'Authorization': 'Bearer fixture'},
                        json={'sessionId': sid, 'plan': draft, 'confirmed': True})
    assert saved.status_code == 200 and records['itineraries']['trip5']['budgetLimit'] == 400


def test_weather_greeting_and_package_interruption_preserve_selected_day(conversation):
    records, _, _, talk = conversation
    sid = select(conversation)
    talk('Change Day 2', sid)
    for message in ('hi', 'What is the weather like?', 'Find a Penang package under RM500'):
        reply = talk(message, sid)
        adjustment = reply['session']['planningState']['adjustment']
        assert adjustment['tripId'] == 'trip5' and adjustment['pendingDay'] == 2
        assert 'tripPlan' not in reply['item']
    result = talk('Back to editing my trip', sid)
    assert 'Day 2' in result['reply']
    assert result['session']['planningState']['adjustment']['pendingDay'] == 2


@pytest.fixture
def editing(conversation, monkeypatch):
    catalog = [{'destinationId': f'new_{category}_{i}', 'title': f'Verified {category} {i}',
                'category': category, 'state': 'Penang', 'city': 'George Town',
                'address': 'George Town, Penang, Malaysia',
                'gps_coordinates': {'latitude': 5.414 + i / 10000, 'longitude': 100.33},
                'openingHours': '09:00-20:00', 'recommendedDurationMinutes': 45,
                'indoor': i == 1,
                'openingHoursSourceUrl': 'https://example.test/hours', 'openingHoursVerifiedAt': '2026-11-15',
                'unitPrice': 0, 'pricingUnit': 'free', 'currency': 'MYR', 'costProvenance': 'fixture'}
               for category in ('Nature', 'Food') for i in range(1, 4)]
    monkeypatch.setattr(routes, '_planning_catalog', lambda *args, **kwargs: deepcopy(catalog))
    return conversation


def assert_other_days_unchanged(plan, trip, day=2):
    assert [a for a in plan['activities'] if a['dayNo'] != day] == [a for a in trip['activities'] if a['dayNo'] != day]
    assert [d for d in plan['dailySchedule'] if d['dayNo'] != day] == [d for d in trip['dailySchedule'] if d['dayNo'] != day]
    ids = [a['activityId'] for a in plan['activities']]
    destinations = [a['destinationId'] for a in plan['activities']]
    assert len(ids) == len(set(ids)) and len(destinations) == len(set(destinations))


def test_day_view_then_nature_replacement_retains_first_activity_and_other_days(editing):
    records, writes, _, talk = editing
    sid = select(editing)
    before = deepcopy(records['itineraries']['trip5'])
    talk('Change Day 2', sid)
    talk('Show me Day 2 first', sid)
    reply = talk('Replace the second activity with something related to nature', sid)
    plan = reply['item']['tripPlan']
    day = [a for a in plan['activities'] if a['dayNo'] == 2]
    assert day[0]['destinationId'] == 'p21'
    assert len(day) == 2 and day[1]['destinationId'].startswith('new_Nature_')
    assert_other_days_unchanged(plan, before)
    assert reply['session']['planningState']['adjustment']['pendingDay'] == 2
    assert talk('Show my trip', sid)['item']['tripPlan']['activities'] == before['activities']
    assert records['itineraries']['trip5'] == before and 'itineraries' not in writes


def test_add_food_carries_theme_through_short_day_answer(editing):
    records, _, _, talk = editing
    sid = select(editing)
    before = deepcopy(records['itineraries']['trip5'])
    assert 'Which day' in talk('Add more food activities', sid)['reply']
    plan = talk('Day 2', sid)['item']['tripPlan']
    day = [a for a in plan['activities'] if a['dayNo'] == 2]
    assert {'p21', 'p22'} <= {a['destinationId'] for a in day}
    assert len(day) == 3 and any(a['destinationId'].startswith('new_Food_') for a in day)
    assert_other_days_unchanged(plan, before)


@pytest.mark.parametrize('message', ['Remove the second activity', 'Remove Saved stop 2.2'])
def test_remove_ordinal_or_named_activity_is_draft_only(editing, message):
    records, writes, _, talk = editing
    sid = select(editing)
    before = deepcopy(records['itineraries']['trip5'])
    talk('Show Day 2', sid)
    plan = talk(message, sid)['item']['tripPlan']
    assert [a['destinationId'] for a in plan['activities'] if a['dayNo'] == 2] == ['p21']
    assert_other_days_unchanged(plan, before)
    assert records['itineraries']['trip5'] == before and 'itineraries' not in writes


def test_replace_one_attraction_asks_only_missing_scope_and_remembers_nature(editing):
    _, _, _, talk = editing
    sid = select(editing)
    assert 'Which day' in talk('Replace one attraction with nature', sid)['reply']
    assert 'Which activity on Day 2' in talk('Day 2', sid)['reply']
    plan = talk('second', sid)['item']['tripPlan']
    assert [a for a in plan['activities'] if a['dayNo'] == 2][1]['destinationId'].startswith('new_Nature_')


def test_day_pace_and_protected_days_do_not_change_whole_trip(editing):
    records, _, _, talk = editing
    trip = records['itineraries']['trip5']
    extra = {**trip['activities'][2], 'activityId': 'a23', 'destinationId': 'p23', 'activityName': 'Saved stop 2.3'}
    trip['activities'].append(extra)
    trip['dailySchedule'][1]['activities'].append(deepcopy(extra))
    trip['travelPace'] = 'moderate'
    before = deepcopy(trip)
    sid = select(editing)
    assert 'keep Day 1' in talk('Keep Day 1 unchanged', sid)['reply']
    reply = talk('Make Day 2 more relaxing', sid)
    plan = reply['item']['tripPlan']
    assert len([a for a in plan['activities'] if a['dayNo'] == 2]) == 2
    assert plan['travelPace'] == 'moderate'
    assert_other_days_unchanged(plan, before)
    blocked = talk('Change Day 1 to nature', sid)
    assert 'keep Day 1' in blocked['reply']
    assert blocked['session']['planningState']['adjustment']['pendingDay'] == 2
    assert 'restriction' in talk('Change destination to Melaka', sid)['reply']


def test_budget_interrupt_does_not_regenerate_pending_day(editing):
    _, _, _, talk = editing
    sid = select(editing)
    talk('Change Day 2', sid)
    reply = talk('Stay within RM500', sid)
    assert reply['item']['tripPlan']['budgetLimit'] == 500
    assert reply['session']['planningState']['adjustment']['pendingDay'] == 2


def test_budget_correction_during_activity_question_retains_operation_and_theme(editing):
    records, _, _, talk = editing
    records['itineraries']['trip5']['budgetLimit'] = 900
    sid = select(editing)
    talk('Replace one attraction with nature', sid)
    talk('Day 2', sid)
    result = talk('Stay within RM700', sid)
    assert result['item']['tripPlan']['budgetLimit'] == 700
    assert result['session']['planningState']['adjustment']['pendingOperation'] == 'replace'
    result = talk('second', sid)
    assert 'tripPlan' in result['item'], result['reply']
    plan = result['item']['tripPlan']
    assert plan['budgetLimit'] == 700
    assert [a for a in plan['activities'] if a['dayNo'] == 2][1]['destinationId'].startswith('new_Nature_')


def test_correcting_day_discards_only_earlier_activity_draft(editing):
    records, _, _, talk = editing
    sid = select(editing)
    talk('Change Day 2', sid)
    talk('Nature', sid)
    reply = talk('Actually Day 3 instead', sid)
    assert reply['session']['planningState']['adjustment']['pendingDay'] == 3
    assert 'activePlan' not in reply['session']['planningState']
    plan = talk('Nature', sid)['item']['tripPlan']
    assert_other_days_unchanged(plan, records['itineraries']['trip5'], day=3)


def test_no_verified_candidate_keeps_saved_trip_and_draft_unchanged(editing, monkeypatch):
    records, writes, _, talk = editing
    sid = select(editing)
    before = deepcopy(records['itineraries'])
    talk('Change Day 2', sid)
    monkeypatch.setattr(routes, '_planning_catalog', lambda *args, **kwargs: [])
    reply = talk('Nature', sid)
    assert 'could not verify' in reply['reply'] and 'tripPlan' not in reply['item']
    assert records['itineraries'] == before and 'itineraries' not in writes


def test_booked_activity_cannot_be_removed_in_chat(editing):
    records, writes, _, talk = editing
    sid = select(editing)
    records['itineraries']['trip5']['activities'][3]['bookingId'] = 'do-not-touch'
    talk('Show Day 2', sid)
    reply = talk('Remove the second activity', sid)
    assert 'booking details' in reply['reply'] and 'tripPlan' not in reply['item']
    assert 'itineraries' not in writes


def test_activity_revision_requires_confirmation_and_duplicate_save_is_idempotent(client, editing):
    records, writes, _, talk = editing
    sid = select(editing)
    before = deepcopy(records['itineraries']['trip5'])
    talk('Change Day 2', sid)
    plan = talk('Nature', sid)['item']['tripPlan']
    headers = {'Authorization': 'Bearer fixture'}
    body = {'sessionId': sid, 'plan': plan}
    assert client.post('/api/fr11/save-plan', headers=headers, json=body).status_code == 400
    assert records['itineraries']['trip5'] == before
    body['confirmed'] = True
    saved = client.post('/api/fr11/save-plan', headers=headers, json=body)
    assert saved.status_code == 200
    assert_other_days_unchanged(saved.json['itinerary'], before)
    count = writes.count('itineraries')
    repeated = client.post('/api/fr11/save-plan', headers=headers, json=body)
    assert repeated.status_code == 200 and repeated.json['alreadySaved']
    assert writes.count('itineraries') == count


def test_stale_activity_revision_cannot_overwrite_an_external_edit(client, editing):
    records, writes, _, talk = editing
    sid = select(editing)
    talk('Change Day 2', sid)
    plan = talk('Nature', sid)['item']['tripPlan']
    records['itineraries']['trip5']['budgetLimit'] = 750
    response = client.post('/api/fr11/save-plan', headers={'Authorization': 'Bearer fixture'},
                           json={'sessionId': sid, 'plan': plan, 'confirmed': True})
    assert response.status_code == 409
    assert records['itineraries']['trip5']['budgetLimit'] == 750 and 'itineraries' not in writes


def test_local_candidate_planning_uses_actual_day_date(editing, monkeypatch):
    _, _, _, talk = editing
    sid = select(editing)
    original = routes.build_structured_trip_plan
    dates = []

    def capture(*args, **kwargs):
        dates.append((kwargs['start_date'], kwargs['end_date']))
        return original(*args, **kwargs)

    monkeypatch.setattr(routes, 'build_structured_trip_plan', capture)
    talk('Change Day 2', sid)
    assert 'tripPlan' in talk('Nature', sid)['item']
    assert dates == [('2027-02-11', '2027-02-11')]


def test_local_constraints_survive_questions_without_rewriting_global_preferences(editing):
    records, _, _, talk = editing
    trip = records['itineraries']['trip5']
    trip.update(interests=['Culture'], preferIndoor=False)
    sid = select(editing)
    talk('Replace one attraction with nature, indoors only, no museums', sid)
    talk('Day 2', sid)
    result = talk('second', sid)
    assert 'tripPlan' in result['item'], result['reply']
    plan = result['item']['tripPlan']
    replacement = [a for a in plan['activities'] if a['dayNo'] == 2][1]
    assert replacement['indoor'] is True and replacement['destinationId'].startswith('new_Nature_')
    assert plan['interests'] == ['Culture']
    patch = result['session']['planningState']['adjustment']['patch']
    assert not {'preferIndoor', 'excludedActivityTypes', 'excludedInterests', 'interests'} & patch.keys()
    assert records['itineraries']['trip5']['preferIndoor'] is False


def test_empty_or_closed_planner_results_do_not_become_fabricated_changes(editing, monkeypatch):
    records, writes, _, talk = editing
    sid = select(editing)
    talk('Change Day 2', sid)
    monkeypatch.setattr(routes, 'build_structured_trip_plan', lambda *args, **kwargs: (
        {'activities': [], 'coverageStatus': 'partial'}, 'ready'))
    result = talk('Nature', sid)
    assert 'could not verify' in result['reply'] and 'tripPlan' not in result['item']
    assert 'itineraries' not in writes


def test_over_budget_local_revision_is_not_offered_for_confirmation(editing, monkeypatch):
    _, writes, _, talk = editing
    sid = select(editing)
    talk('Change Day 2', sid)
    monkeypatch.setattr(routes, 'calculateBudget', lambda *args, **kwargs: {'overBy': 1})
    result = talk('Nature', sid)
    assert 'exceed your trip budget' in result['reply'] and 'tripPlan' not in result['item']
    assert 'activePlan' not in result['session']['planningState'] and 'itineraries' not in writes
