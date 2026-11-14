from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch

import pytest

from sequence_contract.domain_functions import buildLowerCostAlternatives, calculateBudget
from services.activity_pricing import activity_pricing


PREFIX = 'modules.fr05_smart_itinerary_budget_planner.routes.'
HEADERS = {'Authorization': 'Bearer valid_test_token'}
PATH = '/api/fr5/itineraries/historical-trip/lower-cost-alternatives'


def _trip(activity, count=2):
    return {
        'id': 'historical-trip', 'travellerId': 'test_traveller_uid',
        'title': 'Existing trip', 'startDate': '2026-11-01', 'endDate': '2026-11-01',
        'travellerCount': count, 'budgetLimit': 10,
        'activities': [{'activityId': 'A1', 'destinationId': 'original-venue',
                        'activityName': 'Original attraction', **activity}],
    }


@contextmanager
def _isolated(data):
    with patch(PREFIX + 'retrieveRecord', return_value=data), \
         patch(PREFIX + 'updateRecord') as update, \
         patch(PREFIX + 'storeRecord') as store, \
         patch(PREFIX + '_fallback_mode', return_value=False), \
         patch('services.serpapi_service.retrieveFlightOptions', side_effect=AssertionError('No provider calls')):
        yield update, store


def test_own_vehicle_pending_hotel_has_no_fixture_alternatives(client, mock_traveller_auth):
    trip = {**_trip({'estimatedCost': 100}), 'travelMode': 'own_vehicle',
            'destinationArea': 'Penang', 'accommodationChoice': 'undecided'}
    with _isolated(trip) as (update, store), patch(PREFIX + '_fallback_mode', return_value=True):
        response = client.post(PATH, headers=HEADERS, json={
            'departure_id': 'KUL', 'arrival_id': 'PEN', 'outbound_date': '2026-11-15',
        })
    assert response.status_code == 200
    assert response.json['alternatives'] == []
    assert response.json['duplicateAlternativeCount'] == 0
    assert response.json['activityAdvice']
    update.assert_not_called()
    store.assert_not_called()


@pytest.mark.parametrize('activity', [
    {},
    {'estimatedCost': None},
    {'estimatedCost': 100},
    {'estimatedCost': 0, 'pricingUnit': 'unknown'},
    {'estimatedCost': 30, 'unitPrice': 30, 'pricingUnit': 'per_person',
     'costProvenance': 'verified_ticket', 'priceSourceUrl': 'https://example.test/venue',
     'priceVerifiedAt': '2026-10-26'},
    {'estimatedCost': 30, 'unitPrice': 30, 'pricingUnit': 'per_group',
     'costProvenance': 'catalog_estimate'},
    {'estimatedCost': 0, 'unitPrice': 0, 'pricingUnit': 'per_person',
     'costProvenance': 'verified_ticket', 'priceSourceUrl': 'https://example.test/free',
     'priceVerifiedAt': '2026-10-26'},
])
def test_preview_never_invents_rm60_discount_or_mutates_historical_price(
        client, mock_traveller_auth, activity):
    data = _trip(activity)
    original = deepcopy(data)
    expected_budget = calculateBudget(data)
    with _isolated(data) as (update, store):
        response = client.post(PATH, headers=HEADERS, json={})
    assert response.status_code == 200
    body = response.get_json()
    assert not any(item['alternativeType'] in {'activity', 'activities'} for item in body['alternatives'])
    assert body['activityAlternativeStatus'] == 'priced_replacement_unavailable'
    assert 'savings cannot be calculated' in body['activityAdvice']
    assert 'pricing unit' in body['activityAdvice']
    assert body['budget'] == expected_budget
    assert body['budget']['affordabilityStatus'] == 'over_budget'
    assert data == original
    update.assert_not_called()
    store.assert_not_called()


@pytest.mark.parametrize('alternative', [
    {'type': 'activity', 'saving': 60},
    {'alternativeType': 'activities', 'estimatedSavings': 99999},
    {'alternativeType': 'activity', 'estimatedSavings': 'invalid'},
    {'alternativeType': 'activity', 'data': {'destinationId': 'original-venue', 'price': 0}},
    {'alternativeType': 'activity', 'data': {
        'destinationId': 'new-venue', 'pricingUnit': 'per_person', 'unitPrice': 5,
        'currency': 'MYR', 'costProvenance': 'verified_ticket',
        'priceSourceUrl': 'https://example.test/tickets', 'priceVerifiedAt': '2026-10-26',
    }},
    {'alternativeType': 'activity', 'data': {
        'destinationId': 'new-venue', 'pricingUnit': 'per_group', 'unitPrice': 0,
        'currency': 'USD', 'costProvenance': 'verified_ticket',
    }},
])
def test_apply_rejects_discount_and_unvalidated_replacement_claims_without_writes(
        client, mock_traveller_auth, alternative):
    data = _trip({'estimatedCost': 100})
    original = deepcopy(data)
    before = calculateBudget(data)
    with _isolated(data) as (update, store):
        response = client.post(PATH + '/apply', headers=HEADERS, json={'alternative': alternative})
    assert response.status_code == 409
    assert response.get_json()['code'] == 'ACTIVITY_REPLACEMENT_UNAVAILABLE'
    assert response.get_json()['canApply'] is False
    assert data == original
    assert calculateBudget(data) == before
    update.assert_not_called()
    store.assert_not_called()


@pytest.mark.parametrize('count', [1, 4])
@pytest.mark.parametrize('unit', ['per_person', 'per_group', 'already_aggregated'])
def test_unit_prices_and_group_costs_remain_unchanged_when_no_replacement_exists(count, unit):
    activity = {'estimatedCost': 30, 'unitPrice': 30, 'pricingUnit': unit,
                'costProvenance': 'verified_ticket',
                'priceSourceUrl': 'https://example.test/tickets', 'priceVerifiedAt': '2026-10-26'}
    data = _trip(activity, count)
    before = deepcopy(data)
    expected = 30 * count if unit == 'per_person' else 30
    assert calculateBudget(data)['activities'] == expected
    alternatives = buildLowerCostAlternatives([], [], calculateBudget(data), data)
    assert not any(item['alternativeType'] == 'activity' for item in alternatives)
    assert calculateBudget(data)['activities'] == expected
    assert data == before


def test_unknown_zero_is_not_verified_free_and_verified_free_is_not_discounted():
    unknown = activity_pricing({'estimatedCost': 0})
    free = activity_pricing({'estimatedCost': 0, 'unitPrice': 0, 'pricingUnit': 'per_group',
                             'costProvenance': 'verified_ticket',
                             'priceSourceUrl': 'https://example.test/free', 'priceVerifiedAt': '2026-10-26'})
    assert 'unknown_pricing_unit' in unknown['pricingIssues']
    assert 'unverified_zero_price' in unknown['pricingIssues']
    assert free['effectiveCost'] == 0 and free['pricingIssues'] == []


def test_missing_price_budget_stays_incomplete_instead_of_becoming_affordable():
    data = _trip({})
    data['budgetLimit'] = 1500
    before = calculateBudget(data)
    buildLowerCostAlternatives([], [], before, data)
    assert calculateBudget(data) == before
    assert before['completenessStatus'] == before['affordabilityStatus'] == 'incomplete'


def test_raw_flight_and_hotel_options_keep_provenance_without_unvalidated_savings():
    flight = {'price': 120, 'currency': 'MYR', 'priceBasis': 'group_total',
              'source': 'fixture_quote', 'quoteId': 'flight-fixture'}
    hotel = {'price': 200, 'currency': 'MYR', 'quoteId': 'hotel-fixture', 'source': 'fixture_quote'}
    original = deepcopy([flight, hotel])
    options = buildLowerCostAlternatives([flight], [hotel], {'overBy': 0},
                                        {'flightCost': 150, 'hotelCost': 240})
    by_type = {item['alternativeType']: item for item in options}
    assert by_type['flight']['data'] == flight
    assert 'estimatedSavings' not in by_type['flight']
    assert by_type['flight']['canApply'] is False
    assert by_type['hotel']['data'] == hotel
    assert 'estimatedSavings' not in by_type['hotel']
    assert by_type['hotel']['canApply'] is False
    assert [flight, hotel] == original


def test_non_owner_cannot_apply_even_an_advisory_activity_change(client, mock_traveller_auth):
    data = _trip({'estimatedCost': 100})
    data['travellerId'] = 'another-traveller'
    with _isolated(data) as (update, store):
        response = client.post(PATH + '/apply', headers=HEADERS, json={'type': 'activity', 'saving': 60})
    assert response.status_code == 404
    update.assert_not_called()
    store.assert_not_called()


def _planned_trip():
    original = {
        'activityName': 'Paid attraction', 'address': 'Penang', 'estimatedCost': 40,
        'pricingUnit': 'per_person', 'unitPrice': 40, 'costProvenance': 'user_entered',
        'gps_coordinates': {'latitude': 5.42, 'longitude': 100.30},
        'scheduledStartTime': '09:00', 'scheduledEndTime': '11:30', 'timeSlot': '09:00',
        'dayNo': 1, 'dayDate': '2026-11-01', 'sequenceNo': 1,
    }
    value = _trip(original)
    other = {'activityId': 'A2', 'destinationId': 'separate-day', 'activityName': 'Second day'}
    value.update(destinationArea='Penang', endDate='2026-11-02', checkoutOrderId='retained',
                 activities=[*value['activities'], other])
    value['dailySchedule'] = [
        {'dayNo': 1, 'dayDate': '2026-11-01', 'activities': [deepcopy(value['activities'][0])]},
        {'dayNo': 2, 'dayDate': '2026-11-02', 'activities': [other]},
    ]
    return value


def test_real_catalog_activity_preview_apply_reload_and_replay(client, mock_traveller_auth):
    data = _planned_trip()
    original = deepcopy(data)
    with _isolated(data), patch(PREFIX + '_commit_cost_alternative') as write:
        def commit(iid, expected, patch):
            assert iid == original['id'] and expected == data
            data.update(deepcopy(patch))
            return deepcopy(data)
        write.side_effect = commit
        result = client.post(PATH, headers=HEADERS, json={}).json
        assert result['activityAlternativeStatus'] == 'available'
        offer = next(row for row in result['alternatives']
                     if row['data'].get('destinationId') == 'local_botanical_gardens')
        assert offer['estimatedSavings'] == 80
        applied = client.post(PATH + '/apply', headers=HEADERS, json={'alternative': offer})
        assert applied.status_code == 200, applied.json
        reloaded = client.get(PATH.rsplit('/', 1)[0], headers=HEADERS).json['itinerary']
        replacement = reloaded['activities'][0]
        assert replacement['destinationId'] == 'local_botanical_gardens'
        assert replacement['activityId'] == 'A1'
        assert reloaded['dailySchedule'][0]['activities'][0] == replacement
        assert reloaded['dailySchedule'][1] == original['dailySchedule'][1]
        assert reloaded['activities'][1] == original['activities'][1]
        assert reloaded['checkoutOrderId'] == 'retained'
        assert reloaded['budgetEstimate']['total'] == calculateBudget(original)['total'] - 80
        replay = client.post(PATH + '/apply', headers=HEADERS, json={'alternative': offer})
        assert replay.status_code == 409 and replay.json['code'] == 'STALE_ALTERNATIVE'
        write.assert_called_once()


def test_activity_mismatch_stale_and_failed_commit_preserve_trip(client, mock_traveller_auth):
    data = _planned_trip()
    with _isolated(data), patch(PREFIX + '_commit_cost_alternative', side_effect=OSError) as write:
        offer = next(row for row in client.post(PATH, headers=HEADERS).json['alternatives']
                     if row['alternativeType'] == 'activity')
        wrong = {**offer, 'alternativeId': 'wrong-activity'}
        assert client.post(PATH + '/apply', headers=HEADERS, json={'alternative': wrong}).status_code == 409
        data['title'] = 'Changed after preview'
        assert client.post(PATH + '/apply', headers=HEADERS, json={'alternative': offer}).status_code == 409
        assert not write.called
        before = deepcopy(data)
        fresh = next(row for row in client.post(PATH, headers=HEADERS).json['alternatives']
                     if row['alternativeType'] == 'activity')
        changed_price = {**fresh, 'estimatedSavings': 99}
        assert client.post(PATH + '/apply', headers=HEADERS, json={'alternative': changed_price}).json['code'] == 'STALE_ALTERNATIVE'
        write.assert_not_called()
        assert client.post(PATH + '/apply', headers=HEADERS, json={'alternative': fresh}).status_code == 503
        assert data == before


@pytest.mark.parametrize('start,end', [('03:00', '05:00'), ('09:00', '09:10')])
def test_activity_without_a_suitable_opening_period_or_duration_is_advisory(client, mock_traveller_auth, start, end):
    data = _planned_trip()
    data['dailySchedule'][0]['activities'][0].update(scheduledStartTime=start, scheduledEndTime=end)
    with _isolated(data):
        result = client.post(PATH, headers=HEADERS).json
    assert result['activityAlternativeStatus'] == 'priced_replacement_unavailable'


@pytest.mark.parametrize('changes', [
    {'paymentStatus': 'paid'}, {'status': 'completed'}, {'currency': 'USD'},
    {'unitPrice': 0}, {'pricingUnit': 'unknown'},
])
def test_activity_without_comparable_replaceable_admission(client, mock_traveller_auth, changes):
    data = _planned_trip()
    data['activities'][0].update(changes)
    with _isolated(data):
        response = client.post(PATH, headers=HEADERS)
    assert response.status_code == 200
    assert response.json['alternatives'] == []


def test_registry_opening_hours_override_wider_local_hours_for_alternatives(client, mock_traveller_auth):
    data = _planned_trip()
    data['dailySchedule'][0]['activities'][0].update(
        scheduledStartTime='17:40', scheduledEndTime='19:50')
    with _isolated(data):
        response = client.post(PATH, headers=HEADERS)
    assert response.status_code == 200
    assert not response.json['alternatives']
