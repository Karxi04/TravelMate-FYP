from copy import deepcopy
from unittest.mock import patch

import pytest

from modules.fr05_smart_itinerary_budget_planner import routes
from sequence_contract.domain_functions import calculateBudget, recalculateItinerary, rearrangeActivity
from services.itinerary_history import history_patch
from services.itinerary_identity import POLICY, consolidate_generated_candidates, same_attraction

AUTH = {'Authorization': 'Bearer valid_test_token'}
PATH = '/api/fr5/itineraries/f2'


def visit(identity='summit', name='Penang Hill', activity_id='A1', day=1, **fields):
    return {'destinationId': identity, 'activityName': name, 'dayNo': day,
            'activityId': activity_id, 'address': 'Air Itam, Penang, Malaysia',
            'estimatedCost': 25, 'unitPrice': 25, 'pricingUnit': 'per_person',
            'costProvenance': 'catalog_estimate', 'recommendedDurationMinutes': 45,
            'gps_coordinates': {'latitude': 5.4244, 'longitude': 100.2684}, **fields}


def trip(days=3, **fields):
    return {'id': 'f2', 'travellerId': 'test_traveller_uid', 'destinationArea': 'Penang',
            'status': 'planned', 'startDate': '2027-01-10', 'endDate': f'2027-01-{9 + days}',
            'travellerCount': 1, 'budgetLimit': 200, 'activities': [], **fields}


@pytest.mark.parametrize('last_day', [1, 2, 3, 5])
def test_trip_wide_partition_deduplicates_even_unscheduled_candidates(last_day):
    hill = visit()
    alternate = visit('base', 'Bukit Bendera', 'A2', last_day,
                      gps_coordinates={'latitude': 5.40846, 'longitude': 100.27733})
    station = visit('station', 'Penang Hill Lower Station', 'A3', last_day)
    viewpoint = visit('view', 'Penang Hill Viewing Area', 'A4', last_day, independentSubAttraction=True)
    raw = trip(max(2, last_day), attractionIdentityPolicy=POLICY, activities=[hill],
               unscheduledSuggestions=[alternate, station, viewpoint])
    before = deepcopy(raw)
    planned = recalculateItinerary(raw)
    assert raw == before
    assert [p['destinationId'] for p in planned['activities']] == ['summit', 'view']
    assert [p['destinationId'] for p in planned['activities'][0]['supportingAccess']] == ['station']
    assert planned['unscheduledSuggestions'] == []
    assert len([v for day in planned['dailySchedule'] for v in day['activities']]) == 2
    assert calculateBudget(planned)['activities'] == 50
    assert recalculateItinerary(planned)['scheduledActivityCount'] == 2
    if last_day == 5:
        assert len([day for day in planned['dailySchedule'] if not day['activities']]) == 3


def test_transitive_provider_identifiers_and_source_repeat_flags():
    rows = [{'title': 'Town Museum', 'destinationId': 'id1', 'place_id': 'providerA'},
            {'title': 'Museum Detail', 'destinationId': 'id2', 'data_id': 'providerB'},
            {'title': 'Different label', 'place_id': 'providerA', 'data_id': 'providerB',
             'intentionalRepeat': True}]
    before = deepcopy(rows)
    result = consolidate_generated_candidates(rows, automatic=True)
    assert len(result) == 1
    assert same_attraction(result[0], rows[1])
    assert rows == before
    assert len(consolidate_generated_candidates([
        {'destinationId': 'local_penang_hill'}, {'destinationId': 'penang_hill'}])) == 1
    assert len(consolidate_generated_candidates([visit(), visit('alt', 'Penang-Hill')])) == 1


@pytest.fixture
def owned():
    state = {}
    def retrieve(collection, doc=None, **kwargs):
        return deepcopy(state.get(doc)) if collection == 'itineraries' else None
    def update(collection, doc, data, expected=None):
        assert collection == 'itineraries'
        if expected is not None and state[doc] != expected:
            raise routes.HistoryConflict('The trip changed.')
        state[doc].update(history_patch(state[doc], data))
        return deepcopy(state[doc])
    with (patch.object(routes, 'retrieveRecord', side_effect=retrieve),
          patch.object(routes, 'updateRecord', side_effect=update) as updater,
          patch.object(routes, '_flight_alternative_options', return_value=[])):
        yield state, updater


def test_manual_repeat_requires_trip_day_and_action_bound_confirmation(client, mock_traveller_auth, owned):
    day = 3
    state, updater = owned
    state['f2'] = recalculateItinerary(trip(activities=[visit()], attractionIdentityPolicy=POLICY))
    state['other'] = {**deepcopy(state['f2']), 'id': 'other'}
    payload = {key: value for key, value in visit('base', 'Bukit Bendera', day=day,
        gps_coordinates={'latitude': 5.40846, 'longitude': 100.27733}).items() if key != 'activityId'}
    payload.update(clientRequestId='repeat-001', intentionalRepeat=True)
    before = deepcopy(state['f2'])
    blocked = client.post(PATH + '/activities', headers=AUTH, json=payload)
    assert blocked.status_code == 409
    assert blocked.json['existingDay'] == 1
    assert blocked.json['code'] == 'revisit_confirmation_required'
    updater.assert_not_called()
    assert state['f2'] == before
    approved = {**payload, 'revisitConfirmation': blocked.json['confirmationToken']}
    assert client.post(PATH + '/activities', headers=AUTH, json={**approved, 'dayNo': 2}).status_code == 409
    assert client.post('/api/fr5/itineraries/other/activities', headers=AUTH, json=approved).status_code == 409
    assert client.post(PATH + '/activities', headers=AUTH, json={
        **approved, 'destinationId': 'unrelated', 'activityName': 'Unrelated Museum'}).status_code == 409
    updater.assert_not_called()
    accepted = client.post(PATH + '/activities', headers=AUTH, json=approved)
    assert accepted.status_code == 200, accepted.json
    reopened = client.get(PATH, headers=AUTH).json['itinerary']
    repeat = next(row for row in reopened['activities'] if row.get('intentionalRepeat'))
    assert repeat['dayNo'] == day and repeat['canonicalAttractionId'] == 'summit'
    assert repeat['activityId'] != 'A1'
    assert calculateBudget(recalculateItinerary(reopened))['activities'] == 50
    recalculated = recalculateItinerary(reopened, respectDayAssignments=False)
    assert [row['dayNo'] for row in recalculated['activities']] == [1, 3]
    assert client.put(PATH + f"/activities/{repeat['activityId']}", headers=AUTH,
                      json={'dayNo': 1}).json['code'] == 'duplicate_attraction_day'
    assert len(reopened['itineraryHistory']) == 1
    retry = client.post(PATH + '/activities', headers=AUTH, json=approved)
    assert retry.json['alreadyAdded'] is True
    assert updater.call_count == 1
    assert len(rearrangeActivity(reopened, ['A1', 'A1'])['activities']) == 2


@pytest.mark.parametrize('identity,name', [
    ('summit', 'Penang Hill'),
    ('alternate-id', 'Bukit Bendera'),
    ('provider-2', 'Penang-Hill'),
])
def test_same_day_add_blocks_exact_id_alias_and_provider_variation(client, mock_traveller_auth, owned, identity, name):
    state, updater = owned
    state['f2'] = recalculateItinerary(trip(activities=[visit()], attractionIdentityPolicy=POLICY))
    original = deepcopy(state['f2'])
    payload = {**visit(identity, name), 'clientRequestId': 'f3-repeat-day1',
               'intentionalRepeat': True, 'revisitConfirmation': 'forged-token'}
    response = client.post(PATH + '/activities', headers=AUTH, json=payload)
    assert response.status_code == 409
    assert response.json['code'] == 'duplicate_attraction_day'
    assert 'Penang Hill is already included on Day 1.' in response.json['error']
    assert 'confirmationToken' not in response.json
    assert state['f2'] == original
    updater.assert_not_called()


def test_recalculation_does_not_create_same_day_pair_or_drop_saved_historical_pair():
    visits = [visit(), visit('other-id', 'Bukit Bendera', 'A2', 1, intentionalRepeat=True)]
    with_repeat = trip(activities=visits, attractionIdentityPolicy=POLICY)
    newly_calculated = recalculateItinerary(with_repeat)
    assert [row['activityId'] for row in newly_calculated['activities']] == ['A1']
    assert [row['activityId'] for row in newly_calculated['unscheduledSuggestions']] == ['A2']
    historical = {**with_repeat, 'dailySchedule': [{'dayNo': 1, 'activities': visits}]}
    original = deepcopy(historical)
    recalculated = recalculateItinerary(historical)
    assert historical == original
    assert [row['activityId'] for row in recalculated['dailySchedule'][0]['activities']] == ['A1', 'A2']


def test_verified_replacement_cannot_duplicate_a_deferred_attraction():
    duplicate = visit('another-pin', 'Bukit Bendera')
    current = trip(activities=[visit('museum', 'Museum')], unscheduledSuggestions=[visit()])
    with pytest.raises(routes._AlternativeConflict, match='unused replacement'):
        routes._resolve_activity_alternative(
            current, {'activityId': 'A1', 'destinationId': 'another-pin'}, {'another-pin': duplicate})


def test_other_owner_and_forged_activity_edit_are_rejected(client, mock_traveller_auth, owned):
    state, updater = owned
    state['f2'] = trip(activities=[visit()])
    assert client.put(PATH + '/activities/A1', headers=AUTH, json={'intentionalRepeat': True}).status_code == 409
    state['f2']['travellerId'] = 'another-user'
    assert client.post(PATH + '/activities', headers=AUTH, json={'destinationId': 'summit'}).status_code == 404
    assert client.post(PATH + '/budget-replan/preview', headers=AUTH, json={'changes': {'foodCost': 20}}).status_code == 404
    updater.assert_not_called()


@pytest.mark.parametrize('limit, estimate, paid', [(200, 285, 0), (900, 971.18, 146.18)])
def test_activity_only_budget_preview_and_confirmed_apply(client, mock_traveller_auth, owned, limit, estimate, paid):
    state, updater = owned
    current = recalculateItinerary(trip(3, budgetLimit=limit, activities=[visit()],
        foodCost=180, transportCost=round(estimate - 205, 2), paidTotal=paid,
        paymentRecordId='owned-existing-payment' if paid else None,
        travelMode='undecided', accommodationChoice='undecided'))
    current['unscheduledSuggestions'] = [visit('museum', 'Museum', 'A8', 2)]
    state['f2'] = current
    untouched = deepcopy(current)
    options = client.post(PATH + '/lower-cost-alternatives', headers=AUTH).json
    assert options['budget']['total'] == estimate
    assert options['budget']['overBy'] == round(estimate - limit, 2)
    assert not options['flightAdvice'] and not options['hotelAdvice']
    assert options['alternatives'] == []
    if paid:
        assert options['budgetReplanOptions']['optionalVisits'] == []
        assert client.post(PATH + '/budget-replan/preview', headers=AUTH,
                           json={'changes': {'removeActivityIds': ['A1']}}).status_code == 409
    else:
        assert options['budgetReplanOptions']['optionalVisits'][0]['activityId'] == 'A1'
    changes = {'foodCost': 100, 'transportCost': current['transportCost'] - 5}
    if not paid:
        changes['removeActivityIds'] = ['A1']
    reduction = 85 if paid else 110
    payload = {'changes': changes}
    trip_options = client.get(PATH + '/budget-replan', headers=AUTH).json
    assert trip_options['budget'] == options['budget']
    assert trip_options['budgetReplanOptions'] == options['budgetReplanOptions']
    assert trip_options['stateVersion'] == options['stateVersion']
    preview = client.post(PATH + '/budget-replan/preview', headers=AUTH, json=payload)
    assert preview.status_code == 200, preview.json
    assert preview.json['estimatedReduction'] == reduction
    assert bool(any(day['activities'] for day in preview.json['dailySchedule'])) == bool(paid)
    assert 'hotel' in preview.json['budget']['pendingExpenseCategories']
    assert state['f2'] == untouched
    updater.assert_not_called()
    command = {**payload, 'previewToken': preview.json['previewToken'], 'confirmed': True}
    assert client.post(PATH + '/budget-replan/apply', headers=AUTH, json={
        **command, 'changes': {'foodCost': 10}}).status_code == 409
    assert client.post(PATH + '/budget-replan/apply', headers=AUTH, json={
        **command, 'confirmed': False}).status_code == 409
    state['f2'] = {**state['f2'], 'itineraryRevision': 2}
    assert client.get(PATH + '/budget-replan', headers=AUTH).json['stateVersion'] != trip_options['stateVersion']
    stale = client.post(PATH + '/budget-replan/preview', headers=AUTH,
                        json={**payload, 'stateVersion': trip_options['stateVersion']})
    assert stale.status_code == 409 and stale.json['code'] == 'STALE_BUDGET_PLAN'
    assert client.post(PATH + '/budget-replan/apply', headers=AUTH, json=command).status_code == 409
    updater.assert_not_called()
    preview = client.post(PATH + '/budget-replan/preview', headers=AUTH, json=payload)
    command['previewToken'] = preview.json['previewToken']
    saved = client.post(PATH + '/budget-replan/apply', headers=AUTH, json=command)
    assert saved.status_code == 200, saved.json
    revised = saved.json['itinerary']
    assert revised['budgetEstimate']['total'] == round(estimate - reduction, 2)
    assert revised['paidTotal'] == paid and revised['paymentRecordId'] == current['paymentRecordId']
    assert revised['unscheduledSuggestions'][0]['activityId'] == 'A8'
    assert revised['itineraryHistory'][0]['state']['foodCost'] == 180
    assert client.post(PATH + '/budget-replan/apply', headers=AUTH, json=command).status_code == 409
    assert updater.call_count == 1


@pytest.mark.parametrize('activity_state, trip_fields', [
    ('paid', {}),
    ('completed', {}),
    ('planned', {'purchasedPackages': [{'checkoutOrderId': 'existing-package'}]}),
    ('planned', {'manualExpenses': [{'type': 'actual', 'category': 'Activities', 'amountMinor': 2500}]}),
])
def test_budget_replan_never_changes_protected_visit(
        client, mock_traveller_auth, owned, activity_state, trip_fields):
    state, updater = owned
    state['f2'] = trip(activities=[visit(status=activity_state)], foodCost=150, **trip_fields)
    before = deepcopy(state['f2'])
    payload = {'changes': {'removeActivityIds': ['A1']}}
    assert client.post(PATH + '/budget-replan/preview', headers=AUTH, json=payload).status_code == 409
    assert state['f2'] == before
    assert client.post(PATH + '/budget-replan/preview', headers=AUTH,
                       json={'changes': {'foodCost': 100}}).status_code == 200
    updater.assert_not_called()
