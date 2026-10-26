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
         patch(PREFIX + 'retrieveLowerCostFlights', side_effect=AssertionError('No provider calls')):
        yield update, store


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


def test_provider_flight_and_hotel_options_keep_prices_provenance_and_savings():
    flight = {'price': 120, 'currency': 'MYR', 'priceBasis': 'group_total',
              'source': 'fixture_quote', 'quoteId': 'flight-fixture'}
    hotel = {'price': 200, 'currency': 'MYR', 'quoteId': 'hotel-fixture', 'source': 'fixture_quote'}
    original = deepcopy([flight, hotel])
    options = buildLowerCostAlternatives([flight], [hotel], {'overBy': 0},
                                        {'flightCost': 150, 'hotelCost': 240})
    by_type = {item['alternativeType']: item for item in options}
    assert by_type['flight']['data'] == flight
    assert by_type['flight']['estimatedSavings'] == 30
    assert by_type['hotel']['data'] == hotel
    assert by_type['hotel']['estimatedSavings'] == 40
    assert [flight, hotel] == original


def test_non_owner_cannot_apply_even_an_advisory_activity_change(client, mock_traveller_auth):
    data = _trip({'estimatedCost': 100})
    data['travellerId'] = 'another-traveller'
    with _isolated(data) as (update, store):
        response = client.post(PATH + '/apply', headers=HEADERS, json={'type': 'activity', 'saving': 60})
    assert response.status_code == 404
    update.assert_not_called()
    store.assert_not_called()
