"""Confirmed own edits must update conversation concurrency evidence, not bypass it."""
from copy import deepcopy

from test_chatbot_saved_preview import conversation
from test_chatbot_saved_history import revisions, change_and_save, save


def test_confirmed_edit_then_new_draft_does_not_look_like_an_external_edit(revisions, client):
    records, writes, _, talk = revisions
    sid = change_and_save(revisions, client)
    before = deepcopy(records['itineraries'])
    pending = talk('Set the budget to RM900', sid)
    assert pending['item']['tripPlan']['budgetLimit'] == 900
    assert records['itineraries'] == before
    blocked = talk('Restore version 1', sid)
    assert 'already an unconfirmed proposal' in blocked['reply']
    assert 'proposedPlan' not in blocked['item']
    talk('Undo changes', sid)
    proposal = talk('Restore version 1', sid)['item']['proposedPlan']
    assert save(client, sid, proposal).status_code == 200
    assert records['itineraries']['trip5']['budgetLimit'] == 500
    assert writes.count('itineraries') == 2


def test_external_edit_still_invalidates_draft_after_a_successful_own_save(revisions, client):
    records, _, _, talk = revisions
    sid = change_and_save(revisions, client)
    proposed = talk('Set the budget to RM900', sid)['item']['tripPlan']
    records['itineraries']['trip5']['title'] = 'Changed outside this conversation'
    before = deepcopy(records['itineraries'])
    assert save(client, sid, proposed).status_code == 409
    assert records['itineraries'] == before
