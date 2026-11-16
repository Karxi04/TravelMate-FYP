"""Saved-version conversations exercise confirmed saves without live records."""
from copy import deepcopy

import pytest

from modules.fr11_chatbot_travel_assistant import routes
from modules.fr05_smart_itinerary_budget_planner import routes as trips
from services.itinerary_history import history_patch, ensure_restorable
from test_chatbot_saved_preview import conversation, select


@pytest.fixture
def revisions(conversation, monkeypatch):
    records, writes, providers, talk = conversation
    update = routes.updateRecord
    def versioned(collection, key, patch, expected=None):
        if collection == 'itineraries':
            current = records[collection][key]
            if 'restoredFromRevision' in patch:
                ensure_restorable(current)
            patch = history_patch(current, patch)
        return update(collection, key, patch, expected=expected)
    monkeypatch.setattr(routes, 'updateRecord', versioned)
    monkeypatch.setattr(trips, 'updateRecord', versioned)
    monkeypatch.setattr(trips, 'retrieveRecord', routes.retrieveRecord)
    monkeypatch.setattr(routes, 'interpretChatbotIntent', lambda *_: pytest.fail('Known history requests need no model'))
    return conversation


def save(client, sid, item, **extra):
    return client.post('/api/fr11/save-plan', headers={'Authorization': 'Bearer fixture'},
                       json={'sessionId': sid, 'plan': item, 'confirmed': True, **extra})


def change_and_save(revisions, client):
    _, _, _, talk = revisions
    sid = select(revisions)
    plan = talk('Set the budget to RM700', sid)['item']['tripPlan']
    result = save(client, sid, plan)
    assert result.status_code == 200, result.json
    return sid


def test_undo_saved_budget_requires_confirmation_and_is_reversible_and_idempotent(revisions, client):
    records, writes, providers, talk = revisions
    sid = change_and_save(revisions, client)
    before = deepcopy(records['itineraries']['trip5'])
    result = talk('Revert my latest budget update', sid)
    proposal = result['item']['proposedPlan']
    assert proposal['budgetLimit'] == 500 and result['item']['tripPlan']['historyVersion'] == 2
    assert records['itineraries']['trip5'] == before
    response = save(client, sid, proposal, confirmed=False)
    assert response.status_code == 400 and records['itineraries']['trip5'] == before
    response = save(client, sid, proposal)
    assert response.status_code == 200, response.json
    assert response.json['itinerary']['budgetLimit'] == 500
    assert response.json['itinerary']['itineraryHistory'][-1]['state']['budgetLimit'] == 700
    count = writes.count('itineraries')
    repeated = save(client, sid, proposal)
    assert repeated.status_code == 200 and repeated.json['alreadySaved']
    assert writes.count('itineraries') == count and not providers
    assert '700' in talk('Compare version 2 and version 3', sid)['reply']


@pytest.mark.parametrize('message', ['Undo my last saved change', 'Restore the original itinerary'])
def test_saved_restore_words_prepare_drafts_not_writes(revisions, client, message):
    records, writes, _, talk = revisions
    sid = change_and_save(revisions, client)
    before = deepcopy(records['itineraries'])
    count = writes.count('itineraries')
    result = talk(message, sid)
    assert result['item']['tripPlan']['viewOnly']
    assert result['item']['proposedPlan']['restoresVersion'] == 1
    assert records['itineraries'] == before and writes.count('itineraries') == count
    talk('Undo changes', sid)
    assert 'activePlan' not in records['chat_sessions'][sid]['planningState']
    assert records['itineraries'] == before


def test_stale_confirmation_and_foreign_session_cannot_restore(revisions, client):
    records, _, _, talk = revisions
    sid = change_and_save(revisions, client)
    plan = talk('Restore version 1', sid)['item']['proposedPlan']
    records['itineraries']['trip5']['title'] = 'Changed elsewhere'
    before = deepcopy(records['itineraries'])
    assert save(client, sid, plan).status_code == 409
    records['chat_sessions'][sid]['travellerId'] = 'foreign-owner'
    assert save(client, sid, plan).status_code == 404
    assert records['itineraries'] == before


def test_linked_booking_after_preview_blocks_confirmation(revisions, client):
    records, _, _, talk = revisions
    sid = change_and_save(revisions, client)
    plan = talk('Restore version 1', sid)['item']['proposedPlan']
    records['itineraries']['trip5']['selectedFlight'] = {'id': 'real-flight'}
    before = deepcopy(records['itineraries'])
    assert save(client, sid, plan).status_code == 409 and records['itineraries'] == before


def test_missing_history_no_trip_and_read_only_versions_are_honest(revisions, client):
    _, _, _, talk = revisions
    first = talk('Restore the original itinerary')
    assert 'Select the saved trip' in first['reply']
    sid = select(revisions)
    result = talk('Undo my last saved change', sid)
    assert 'No saved revision history' in result['reply'] and 'proposedPlan' not in result['item']
    sid = change_and_save(revisions, client)
    earlier = talk('Show the earlier version', sid)
    assert earlier['item']['tripPlan']['viewOnly'] and earlier['item']['tripPlan']['budgetLimit'] == 500
    assert 'proposedPlan' not in earlier['item']


def test_fr5_edit_and_chat_share_history_and_block_forged_fields(revisions, client):
    records, _, _, talk = revisions
    response = client.put('/api/fr5/itineraries/trip5', headers={'Authorization': 'Bearer fixture'},
                          json={'title': 'Edited in trip screen'})
    assert response.status_code == 200, response.json
    assert records['itineraries']['trip5']['itineraryHistory'][0]['state']['title'].endswith('5')
    sid = select(revisions)
    result = talk('Show itinerary history', sid)
    assert result['item']['revisionHistory'][0]['changedFields'] == ['title']
    history = client.get('/api/fr5/itineraries/trip5/history', headers={'Authorization': 'Bearer fixture'})
    assert history.status_code == 200 and history.json['currentVersion'] == 2
    assert 'state' not in history.json['versions'][0]
    forged = client.put('/api/fr5/itineraries/trip5', headers={'Authorization': 'Bearer fixture'},
                        json={'itineraryHistory': [], 'restoredFromRevision': 1})
    assert forged.status_code == 400


def test_ambiguous_model_can_prepare_but_never_confirm_restoration(revisions, client, monkeypatch):
    records, writes, _, talk = revisions
    sid = change_and_save(revisions, client)
    calls = []
    monkeypatch.setattr(routes, 'interpretChatbotIntent', lambda prompt: calls.append(prompt) or
                        {'intent': 'restore_version', 'version': 1, 'confidence': .95})
    count = writes.count('itineraries')
    result = talk('The earlier setup felt much better to us', sid)
    assert len(calls) == 1 and 'proposedPlan' in result['item']
    assert records['itineraries']['trip5']['budgetLimit'] == 700 and writes.count('itineraries') == count


def test_previous_day_restoration_preserves_current_budget_and_other_days(revisions, client):
    records, writes, _, talk = revisions
    old = deepcopy(records['itineraries']['trip5'])
    activities = deepcopy(old['activities'])
    activities[2]['activityName'] = 'Wrong day 2 place'
    activities[2]['destinationId'] = 'wrong-place'
    routes.updateRecord('itineraries', 'trip5', {'activities': activities, 'budgetLimit': 800})
    sid = select(revisions)
    before = deepcopy(records['itineraries']['trip5'])
    result = talk('I prefer the previous Day 2', sid)
    plan = result['item']['proposedPlan']
    assert plan['budgetLimit'] == 800 and records['itineraries']['trip5'] == before
    response = save(client, sid, plan)
    assert response.status_code == 200, response.json
    saved = records['itineraries']['trip5']
    assert [a for a in saved['activities'] if a['dayNo'] != 2] == [a for a in before['activities'] if a['dayNo'] != 2]
    assert next(a for a in saved['activities'] if a['activityId'] == 'a21')['activityName'] == old['activities'][2]['activityName']


def test_history_queries_and_booking_failure_never_save(revisions, client, monkeypatch):
    records, writes, _, talk = revisions
    sid = change_and_save(revisions, client)
    before = deepcopy(records['itineraries'])
    count = writes.count('itineraries')
    assert 'retained' in talk('What did I change yesterday?', sid)['reply'].lower()
    assert talk('Show version 1', sid)['item']['tripPlan']['viewOnly']
    assert 'unavailable' in talk('Show version 999', sid)['reply']
    reader = routes.retrieveRecord
    def failed(collection, *args, **kwargs):
        if collection == 'hotel_bookings': raise RuntimeError('PRIVATE_DATABASE_DETAIL')
        return reader(collection, *args, **kwargs)
    monkeypatch.setattr(routes, 'retrieveRecord', failed)
    result = talk('Restore version 1', sid)
    assert 'temporarily unavailable' in result['reply'] and 'PRIVATE_DATABASE_DETAIL' not in str(result)
    assert records['itineraries'] == before and writes.count('itineraries') == count


def test_history_api_rejects_another_owner(revisions, client):
    records, _, _, _ = revisions
    records['itineraries']['trip5']['travellerId'] = 'another-owner'
    response = client.get('/api/fr5/itineraries/trip5/history', headers={'Authorization': 'Bearer fixture'})
    assert response.status_code == 404 and 'versions' not in response.json


def test_wrong_place_clarifies_the_day_without_losing_history_intent(revisions):
    records, _, _, talk = revisions
    before = deepcopy(records['itineraries']['trip5'])
    changed = deepcopy(before['activities'])
    changed[2]['activityName'] = 'Wrong replacement'
    routes.updateRecord('itineraries', 'trip5', {'activities': changed})
    sid = select(revisions)
    assert 'Which itinerary day' in talk('I changed the wrong place; restore it', sid)['reply']
    talk('What if it rains?', sid)
    result = talk('Day 2', sid)
    assert result['item']['proposedPlan']['restorationScope'] == 'day'
    assert records['itineraries']['trip5']['activities'] == changed


@pytest.mark.parametrize('value', [True, 0, -1, 1.5, None])
def test_invalid_model_version_cannot_authorize_restoration(value):
    from modules.fr11_chatbot_travel_assistant.contextual_intent import validate_interpretation
    assert validate_interpretation({'intent': 'restore_version', 'confidence': 1, 'version': value},
                                   {'adjustment': {'tripId': 'owned'}}, []) is None


def test_lost_restoration_receipt_does_not_duplicate_history(revisions, client, monkeypatch):
    records, writes, _, talk = revisions
    sid = change_and_save(revisions, client)
    plan = talk('Revert my latest budget update', sid)['item']['proposedPlan']
    update = routes.updateRecord
    def lose_receipt(collection, key, patch, expected=None):
        result = update(collection, key, patch, expected=expected)
        if collection == 'itineraries': raise RuntimeError('simulated lost response after commit')
        return result
    monkeypatch.setattr(routes, 'updateRecord', lose_receipt)
    response = save(client, sid, plan)
    assert response.status_code == 503 and 'outcome' in response.json['error']
    assert records['itineraries']['trip5']['budgetLimit'] == 500
    count = writes.count('itineraries')
    retry = save(client, sid, plan)
    assert retry.status_code == 200 and retry.json['alreadySaved']
    assert writes.count('itineraries') == count and len(records['itineraries']['trip5']['itineraryHistory']) == 2


def test_late_transaction_booking_guard_explains_rejection(revisions, client, monkeypatch):
    from services.itinerary_history import HistoryConflict
    records, _, _, talk = revisions
    sid = change_and_save(revisions, client)
    plan = talk('Restore version 1 budget', sid)['item']['proposedPlan']
    before = deepcopy(records['itineraries'])
    update = routes.updateRecord
    def blocked(collection, key, patch, expected=None):
        if collection == 'itineraries': raise HistoryConflict('This trip has linked booking or order records. Restoration is blocked.')
        return update(collection, key, patch, expected=expected)
    monkeypatch.setattr(routes, 'updateRecord', blocked)
    response = save(client, sid, plan)
    assert response.status_code == 409 and 'linked booking' in response.json['error']
    assert records['itineraries'] == before


def test_historical_preview_uses_recorded_legacy_count_or_withholds_total(monkeypatch):
    from modules.fr11_chatbot_travel_assistant.history_conversation import _preview
    monkeypatch.setattr('sequence_contract.domain_functions.calculateBudget', lambda row: {'evaluatedCount': row['travellerCount']})
    assert _preview({'id': 'owned'}, {'numberOfTravellers': 4}, 1)['budgetEstimate']['evaluatedCount'] == 4
    unknown = _preview({'id': 'owned'}, {}, 1)['budgetEstimate']
    assert unknown['incomplete'] and 'total' not in unknown and 'evaluatedCount' not in unknown


def test_restore_same_target_after_a_later_edit_is_a_new_operation(revisions, client):
    records, _, _, talk = revisions
    sid = change_and_save(revisions, client)
    first = talk('Restore version 1 budget', sid)['item']['proposedPlan']
    assert save(client, sid, first).status_code == 200
    assert 'no unconfirmed proposal' in talk('Undo changes', sid)['reply']
    edit = talk('Set the budget to RM700', sid)['item']['tripPlan']
    assert save(client, sid, edit).status_code == 200
    # Firestore merges receipt maps; keep the older receipt present in this fixture too.
    records['chat_sessions'][sid]['planningState']['savedPlans'][first['draftId']] = 'trip5'
    second = talk('Restore version 1 budget', sid)['item']['proposedPlan']
    assert second['draftId'] != first['draftId']
    result = save(client, sid, second)
    assert result.status_code == 200 and result.json['itinerary']['budgetLimit'] == 500
    assert not result.json['alreadySaved']
