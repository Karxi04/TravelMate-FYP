"""Physical-reported conversations replayed with isolated records and real local data."""
from copy import deepcopy

import pytest

from modules.fr11_chatbot_travel_assistant import routes
from services.local_catalog import DESTINATIONS
from test_chatbot_saved_preview import conversation, editing, select
from test_chatbot_context_quality import places


@pytest.fixture
def browsing(conversation, monkeypatch):
    monkeypatch.setattr(routes, '_planning_catalog', lambda *args, **kwargs: deepcopy(DESTINATIONS))
    monkeypatch.setattr(routes, 'interpretChatbotIntent', lambda *_: pytest.fail('Known place turns must not call Gemini'))
    return conversation


def rows(result):
    return result['item'].get('placeSuggestions', [])


def ids(result):
    return {row['destinationId'] for row in rows(result)}


@pytest.mark.parametrize('other', ['Show me another 3 places', 'Other 3 places lah',
    'othe 3 place', 'more places', 'give me different places', 'Got more?'])
def test_other_pages_are_distinct_and_repeat_is_stable(browsing, other):
    _, _, providers, talk = browsing
    first = talk('Show me 3 places in Penang')
    sid = first['session']['id']
    second = talk(other, sid)
    assert len(ids(first)) == 3 and len(ids(second)) == 3
    assert not ids(first) & ids(second)
    assert all('Penang' in str(row) for row in rows(second))
    assert rows(talk('show me the same results', sid)) == rows(second)
    assert not providers


def test_exact_vivo_followups_have_distinct_grounded_answers(browsing):
    _, writes, providers, talk = browsing
    first = talk('Show me 3 places in Penang')
    sid = first['session']['id']
    second = rows(first)[1]
    talk('The second one', sid)
    price = talk('Is it expensive?', sid)
    why = talk('Why recommend it?', sid)
    assert second['title'] in price['reply'] and second['title'] in why['reply']
    assert 'category' in why['reply'].lower() or 'Nature' in why['reply']
    assert price['reply'] != why['reply']
    assert 'details' in price['reply'].lower()
    about = talk('Tell me about this place', sid)
    assert second['description'] in about['reply'] and 'minutes' in about['reply']
    assert 'Local catalogue' in about['reply']
    assert 'suitability' in talk('Is it suitable for families?', sid)['reply'].lower()
    assert second['title'] in talk('What activities are there?', sid)['reply']
    nearby = talk('Anything cheaper nearby?', sid)
    assert rows(nearby) and 'cannot verify' in nearby['reply'].lower()
    assert 'straight-line' in nearby['reply'] and not ids(nearby) & {second['destinationId']}
    assert not providers and 'itineraries' not in writes


def test_exhaustion_returns_two_then_none_without_recycling(conversation, monkeypatch):
    _, _, _, talk = conversation
    catalogue = places() + [{**places()[0], 'destinationId': 'fifth', 'title': 'Fifth recorded place'}]
    monkeypatch.setattr(routes, '_planning_catalog', lambda *a, **k: deepcopy(catalogue))
    first = talk('Show me 3 places in Penang')
    sid = first['session']['id']
    assert len(rows(talk('other 3 places', sid))) == 2
    exhausted = talk('more places', sid)
    assert not rows(exhausted) and 'no further' in exhausted['reply'].lower()
    assert len(rows(talk('same results', sid))) == 2


def test_reject_all_and_similar_obey_scope_and_interests(browsing):
    _, _, _, talk = browsing
    first = talk('Show me 3 places in Penang')
    sid = first['session']['id']
    rejected = talk("Don't want these places", sid)
    assert not ids(first) & ids(rejected)
    talk('The first one', sid)
    similar = talk('Show another similar place', sid)
    assert not ids(similar) & (ids(first) | ids(rejected))
    filtered = talk('Actually show nature places', sid)
    assert rows(filtered) and all('Nature and outdoors' in row['matchedInterests'] for row in rows(filtered))


def test_similar_relaxing_and_single_other_keep_context(browsing):
    _, _, _, talk = browsing
    first = talk('Show me 3 places in Penang')
    sid = first['session']['id']
    talk('The second one', sid)
    different = talk('another one', sid)
    assert len(rows(different)) == 1 and not ids(first) & ids(different)
    talk('The first one', sid)
    relaxed = talk('I prefer something relaxing', sid)
    assert rows(relaxed) and all('Leisure and entertainment' in r['matchedInterests'] for r in rows(relaxed))


@pytest.mark.parametrize('phrase', ["I don't want this one", 'This one boring',
    'Anything more interesting nearby?', 'Can show me somewhere cheaper?', 'Why this place?'])
def test_informal_selected_followups_are_grounded_without_model(browsing, phrase):
    _, _, providers, talk = browsing
    first = talk('Show me 3 places in Penang')
    sid = first['session']['id']
    talk('The second one', sid)
    result = talk(phrase, sid)
    if 'Why' in phrase:
        assert rows(first)[1]['title'] in result['reply']
    else:
        assert rows(result) and rows(first)[1]['destinationId'] not in ids(result)
    assert not providers


def test_duplicate_ids_aliases_wrong_locations_and_rejections_do_not_leak(conversation, monkeypatch):
    _, _, _, talk = conversation
    candidates = places() + [deepcopy(places()[0]),
        {**places()[1], 'destinationId': 'alias'},
        {**places()[0], 'destinationId': 'foreign', 'title': 'Foreign option',
         'city': 'Kuala Lumpur', 'state': 'Kuala Lumpur', 'address': 'Kuala Lumpur, Malaysia'}]
    monkeypatch.setattr(routes, '_planning_catalog', lambda *a, **k: deepcopy(candidates))
    first = talk('Show me 3 places in Penang')
    sid = first['session']['id']
    remaining = talk('other 3 places', sid)
    assert len(rows(remaining)) == 1 and 'foreign' not in ids(remaining)
    assert not {r['title'] for r in rows(first)} & {r['title'] for r in rows(remaining)}
    fresh = talk('Show me 3 places in Penang')
    assert rows(fresh) == rows(first) and fresh['session']['id'] != sid


@pytest.mark.parametrize('missing', ['currency', 'basis', 'coordinates'])
def test_unknown_baseline_never_creates_cheaper_or_distance_claim(conversation, monkeypatch, missing):
    _, _, _, talk = conversation
    catalogue = places()
    catalogue[1].pop({'currency': 'currency', 'basis': 'pricingUnit', 'coordinates': 'gps_coordinates'}[missing])
    monkeypatch.setattr(routes, '_planning_catalog', lambda *a, **k: deepcopy(catalogue))
    first = talk('Show me 3 places in Penang')
    sid = first['session']['id']
    talk('The second one', sid)
    result = talk('Anything cheaper nearby?', sid)
    if missing == 'coordinates':
        assert not rows(result) and 'km' not in result['reply']
    else:
        assert rows(result) and 'cannot verify' in result['reply'] and 'verified cheaper' not in result['reply']


@pytest.mark.parametrize('question', ['The third option', 'How about the first one instead?',
    'Go back to the second place', 'Compare the first and second'])
def test_ordinals_reference_current_records_not_trip_days(browsing, question):
    _, _, _, talk = browsing
    first = talk('Show me 3 places in Penang')
    result = talk(question, first['session']['id'])
    expected = rows(first)[2 if 'third' in question else 1 if 'back' in question else 0]
    assert expected['title'] in result['reply']


def test_incomplete_data_offers_choices_without_distance_or_price_claims(conversation, monkeypatch):
    _, _, _, talk = conversation
    candidates = places()
    for row in candidates:
        row.pop('gps_coordinates')
        row.pop('pricingUnit')
    monkeypatch.setattr(routes, '_planning_catalog', lambda *a, **k: candidates)
    first = talk('Show me 3 places in Penang')
    sid = first['session']['id']
    talk('The second one', sid)
    result = talk('Anything cheaper nearby?', sid)
    assert not rows(result) and 'suggestedReplies' in result['item']
    assert 'km' not in result['reply'] and 'MYR' not in result['reply']


def test_real_cache_callback_reads_without_provider_search(conversation, monkeypatch):
    _, _, _, talk = conversation
    # Use the real catalogue loader with its existing read-only cache contract.
    monkeypatch.setattr(routes, '_planning_catalog', REAL_CATALOG)
    monkeypatch.setattr(routes, 'retrieveDestinationResults', lambda *_: pytest.fail('No live lookup'))
    first = talk('Show me 3 places in Penang')
    talk('The second one', first['session']['id'])
    result = talk('Anything nearby?', first['session']['id'])
    assert rows(result)


REAL_CATALOG = routes._planning_catalog


@pytest.mark.parametrize('with_places', [False, True])
def test_physical_compare_undo_sequence_is_draft_only(editing, with_places):
    records, writes, providers, talk = editing
    sid = select(editing)
    before = deepcopy(records['itineraries'])
    talk('Change Day 2', sid)
    proposed = talk('I prefer nature, less walking', sid)
    assert 'tripPlan' in proposed['item']
    if with_places:
        talk('Show me 3 places in Penang', sid)
    comparison = talk('Compare old and new', sid)
    assert comparison['item']['tripPlan']['viewOnly']
    assert comparison['item']['proposedPlan']['activities'] == proposed['item']['tripPlan']['activities']
    assert 'Day 2' in comparison['reply'] and 'unchanged' in comparison['reply']
    undone = talk('Undo changes', sid)
    state = undone['session']['planningState']
    assert 'activePlan' not in state and not state['adjustment'].get('patch')
    assert state['adjustment']['tripId'] == 'trip5'
    assert records['itineraries'] == before and 'itineraries' not in writes and not providers
    assert talk('Show my trip', sid)['item']['tripPlan']['activities'] == before['trip5']['activities']


def test_no_draft_compare_and_undo_are_explicit(conversation):
    _, _, _, talk = conversation
    sid = select(conversation)
    assert 'no current proposal' in talk('Compare old and new', sid)['reply']
    assert 'no unconfirmed proposal' in talk('Undo changes', sid)['reply']


def test_price_product_limits_and_missing_currency_are_not_dropped():
    from modules.fr11_chatbot_travel_assistant.contextual_intent import _price, place_cards
    row = places()[0]
    row['pricingEvidence'] = {'applicability': 'applicable', 'ticketProduct': 'Grounds admission',
                             'limitations': 'Optional lift excluded.'}
    card = place_cards([row], {})[0]
    assert 'Grounds admission' in _price(card, 'place') and 'Optional lift excluded' in _price(card, 'place')
    card.pop('currency')
    assert 'unavailable' in _price(card, 'place')


def test_legacy_six_card_page_is_fully_excluded_from_other_requests(conversation, monkeypatch):
    records, _, _, talk = conversation
    catalogue = [{**places()[0], 'destinationId': f'd{i}', 'title': f'Legacy venue {i}'} for i in range(8)]
    monkeypatch.setattr(routes, '_planning_catalog', lambda *a, **k: deepcopy(catalogue))
    first = talk('Show me 3 places in Penang')
    sid = first['session']['id']
    records['chat_sessions'][sid]['messages'][-1]['placeSuggestions'] = deepcopy(catalogue[:6])
    result = talk('Other 3 places', sid)
    assert ids(result) == {'d6', 'd7'}


def test_question_with_ordinal_does_not_use_previous_selected_price(conversation, monkeypatch):
    _, _, _, talk = conversation
    monkeypatch.setattr(routes, '_planning_catalog', lambda *a, **k: places())
    first = talk('Show me 3 places in Penang')
    sid = first['session']['id']
    talk('The first one', sid)
    reply = talk('Is the third option expensive?', sid)
    assert '30.00' in reply['reply'] and 'Recorded place 3' in reply['reply']
    assert reply['session']['planningState']['selectedResult']['id'] == 'place3'
