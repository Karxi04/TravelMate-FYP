from copy import deepcopy
from unittest.mock import patch

import pytest

from modules.fr04_hybrid_recommendation import routes as recommendations
from modules.fr05_smart_itinerary_budget_planner import routes as itineraries
from sequence_contract.domain_functions import (
    applyCollaborativeFiltering, applyContentBasedFiltering, calculateBudget,
    calculateRecommendationScore, generateItinerary, prepareRecommendationInput, rankRecommendations,
)
from services.activity_pricing import activity_pricing, pricing_snapshot
from services.local_catalog import DESTINATIONS
from services.pricing_registry import REGISTRY, _valid_record, enrich_candidate_pricing


def candidate(venue, **changes):
    record = next(record for record in REGISTRY if record['venueId'] == venue)
    return {'destinationId': venue, 'title': record['aliases'][0],
            'address': 'Penang, Malaysia',
            'gps_coordinates': dict(zip(('latitude', 'longitude'), record['coordinates'])),
            'estimatedCost': 12, 'category': 'Culture Nature', 'rating': 4.5,
            'reviews': 100, 'recommendedDurationMinutes': 45, **changes}


def trip(items, **changes):
    return {'title': 'Synthetic pricing test only', 'destinationArea': 'Penang',
            'startDate': '2026-11-01', 'endDate': '2026-11-03',
            'travellerCount': 4, 'budgetLimit': 1500, 'activities': items,
            'travelMode': 'public_transport', 'accommodationChoice': 'return_home',
            'carRentalChoice': 'not_required', **changes}


@pytest.mark.parametrize('venue', ['local_botanical_gardens', 'local_kek_lok_si'])
def test_explicit_free_admission_is_usable_for_the_group(venue):
    original = candidate(venue)
    before = deepcopy(original)
    priced = enrich_candidate_pricing(original)
    assert priced['unitPrice'] == priced['estimatedCost'] == 0
    assert priced['costProvenance'] == 'verified_ticket'
    assert priced['pricingEvidence']['eligibility'] == 'all_visitors'
    assert priced['priceSourceUrl'] and priced['priceVerifiedAt']
    activity = itineraries._activity_from_destination(priced, 0)
    assert activity_pricing(activity, 4)['pricingIssues'] == []
    budget = calculateBudget(trip([activity]))
    assert budget['activities'] == 0 and budget['completenessStatus'] == 'complete'
    assert budget['food'] == 720 and budget['transport'] == 105
    assert original == before


@pytest.mark.parametrize('venue,price', [('local_peranakan_mansion', 30), ('the_top_penang', 78),
                                       ('local_penang_hill', 40), ('local_wonderfood', 30),
                                       ('local_esc', 184)])
def test_conditional_tariffs_are_metadata_not_group_charges(venue, price):
    raw = candidate(venue)
    priced = enrich_candidate_pricing(raw)
    assert priced['estimatedCost'] == raw['estimatedCost']
    assert 'unitPrice' not in priced and 'pricingUnit' not in priced
    evidence = priced['pricingEvidence']
    assert evidence['unitPrice'] == price and evidence['applicability'] == 'conditional'
    assert evidence['eligibility'] and evidence['ticketProductId'] and evidence['priceSourceUrl']
    budget = calculateBudget(trip([itineraries._activity_from_destination(priced, 0)]))
    assert budget['activities'] == 12  # Preserve the existing untyped numeric estimate.
    assert budget['completenessStatus'] == 'incomplete'
    assert 'conditional_or_unverified_admission' in budget['expenseBreakdown']['activities']['pricingIssues']


@pytest.mark.parametrize('venue', ['local_chew_jetty', 'local_cheong_fatt_tze'])
def test_unverified_evidence_does_not_resolve_an_admission(venue):
    item = enrich_candidate_pricing(candidate(venue, estimatedCost=0))
    assert item['pricingEvidence']['applicability'] == 'unverified'
    assert 'unitPrice' not in item
    budget = calculateBudget(trip([item]))
    assert budget['activities'] == 0 and budget['completenessStatus'] == 'incomplete'


@pytest.mark.parametrize('changes', [
    {'title': 'Kek Lok Si Pagoda'}, {'title': 'Kek Lok Si Temple Inclined Lift'},
    {'ticketProductId': 'pagoda_optional_entry'}, {'experienceName': 'Inclined lift ride'},
    {'place_id': 'ChIJunrelated_venue'}, {'destinationId': 'local_unrelated'},
    {'gps_coordinates': {'latitude': 3.1, 'longitude': 101.7}},
    {'gps_coordinates': {}}, {'gps_coordinates': {'latitude': float('nan'), 'longitude': 100}},
    {'costCategory': 'transport'},
])
def test_alias_geography_and_subexperience_conflicts_fail_closed(changes):
    item = candidate('local_kek_lok_si', **changes)
    assert enrich_candidate_pricing(item) == item


def test_alias_and_proximity_alone_cannot_assign_automatic_free_pricing():
    item = candidate('local_botanical_gardens')
    item.pop('destinationId')
    assert enrich_candidate_pricing(item) == item


def test_reported_google_identity_requires_matching_name_and_coordinates():
    record = REGISTRY[0]
    item = candidate(record['venueId'], destinationId=record['googlePlaceId'],
                     place_id=record['googlePlaceId'], title='Botanical Gardens Penang')
    priced = enrich_candidate_pricing(item)
    assert priced['unitPrice'] == 0
    assert priced['pricingEvidence']['identityEvidence'] == 'provider_cache_continuity_only'
    item['title'] = 'Youth Park'
    assert enrich_candidate_pricing(item) == item


@pytest.mark.parametrize('venue,title,place_id', [
    ('local_penang_hill', 'The Habitat Penang Hill', 'ChIJcVQ4gnvCSjARG4IcsNb4dCk'),
    ('the_top_penang', 'Jurassic Research Center', 'ChIJ-8pjzpXDSjARhqQbf7o4ang'),
    ('local_chew_jetty', 'Clan Jetties of Penang', 'ChIJESJTC43DSjARiVDKy9hsY74'),
])
def test_neighbouring_or_shared_complex_experiences_never_inherit_prices(venue, title, place_id):
    item = candidate(venue, title=title, place_id=place_id)
    assert enrich_candidate_pricing(item) == item


@pytest.mark.parametrize('unit', ['per_person', 'per_group', 'already_aggregated'])
def test_existing_specific_prices_and_units_are_not_overwritten(unit):
    item = candidate('local_kek_lok_si', pricingUnit=unit, unitPrice=7,
                     estimatedCost=7, costProvenance='user_entered')
    assert enrich_candidate_pricing(item) == item
    assert activity_pricing(item, 4)['effectiveCost'] == (28 if unit == 'per_person' else 7)


def test_conditional_research_cannot_be_laundered_into_resolved_group_pricing():
    item = enrich_candidate_pricing(candidate('local_peranakan_mansion'))
    item.update({'pricingUnit': 'per_person', 'unitPrice': 30, 'costProvenance': 'verified_ticket'})
    budget = calculateBudget(trip([item]))
    assert budget['activities'] == 120  # Existing numeric arithmetic is unchanged.
    assert budget['completenessStatus'] == 'incomplete'


@pytest.mark.parametrize('change', [
    {'unitPrice': -1}, {'unitPrice': True}, {'unitPrice': float('inf')},
    {'currency': 'USD'}, {'pricingUnit': 'ticket'}, {'priceSourceUrl': ''},
    {'unitPrice': 30}, {'eligibility': 'adults_only'},
])
def test_invalid_or_inapplicable_registry_records_cannot_be_automatic(change):
    assert not _valid_record({**REGISTRY[0], **change})


def test_missing_unverified_zero_stays_unknown():
    item = {'title': 'Unknown park', 'estimatedCost': 0}
    assert enrich_candidate_pricing(item) == item
    assert 'unverified_zero_price' in activity_pricing(item, 4)['pricingIssues']


def test_metadata_survives_provider_snapshot_activity_schedule_and_budget():
    raw = candidate('local_botanical_gardens')
    with patch.object(recommendations, 'retrieveDestinationResults',
                      return_value={'local_results': [raw]}):
        provider = recommendations._provider_destinations('parks', 'Penang')[0]
    snapshot = recommendations._snapshot_item(provider, 'live_provider')
    original_snapshot = deepcopy(snapshot)
    activity = itineraries._activity_from_destination(snapshot, 0)
    plan = generateItinerary([], {}, trip([activity]))
    scheduled = plan['dailySchedule'][0]['activities'][0]
    assert pricing_snapshot(scheduled) == pricing_snapshot(snapshot)
    assert calculateBudget(plan)['activities'] == 0
    assert calculateBudget(plan)['completenessStatus'] == 'complete'
    scheduled['pricingEvidence']['limitations'] = 'Changed copy'
    assert snapshot == original_snapshot


def test_new_live_and_catalog_candidates_are_enriched_but_old_snapshots_are_not(monkeypatch):
    old = candidate('local_kek_lok_si')
    before = deepcopy(old)
    candidates, _ = itineraries._destination_candidates(trip([]), {'recommendationResults': [old]})
    assert candidates[0]['estimatedCost'] == 12 and 'unitPrice' not in candidates[0]
    assert old == before
    monkeypatch.setenv('SERPAPI_KEY', 'offline-fixture-not-a-key')
    with patch.object(itineraries, 'retrieveDestinationResults', return_value={'local_results': [old]}):
        candidates, source = itineraries._destination_candidates(trip([]))
    assert source == 'live_provider' and candidates[0]['unitPrice'] == 0
    monkeypatch.setenv('SERPAPI_KEY', '')
    with patch.object(itineraries, '_fallback_mode', return_value=True):
        candidates, source = itineraries._destination_candidates(trip([]))
    assert source == 'fallback'
    assert next(item for item in candidates if item['destinationId'] == 'local_kek_lok_si')['unitPrice'] == 0
    assert all('pricingUnit' not in item for item in DESTINATIONS)


def test_existing_budget_reads_do_not_enrich_historical_records():
    historical = trip([candidate('local_kek_lok_si')])
    before = deepcopy(historical)
    assert calculateBudget(historical)['activities'] == 12
    assert historical == before and historical['activities'][0].get('pricingUnit') is None


def test_one_free_activity_cannot_complete_unknown_activity_or_fuel_costs():
    free = itineraries._activity_from_destination(enrich_candidate_pricing(candidate('local_botanical_gardens')), 0)
    budget = calculateBudget(trip([free, {'estimatedCost': 0}]))
    assert budget['completenessStatus'] == 'incomplete' and 'activities' in budget['pendingExpenseCategories']
    budget = calculateBudget(trip([free], travelMode='own_vehicle'))
    assert budget['completenessStatus'] == 'incomplete'
    assert 'ownVehicleFuelAndTolls' in budget['excludedExpenseCategories']


def test_ranking_and_weights_are_unchanged_by_pricing_projection():
    items = [candidate('local_botanical_gardens'), candidate('local_peranakan_mansion')]
    profile = {'interests': ['Culture', 'Nature'], 'travelPace': 'Moderate'}

    def scores(candidates):
        content = applyContentBasedFiltering(prepareRecommendationInput(profile, candidates, []))
        combined = applyCollaborativeFiltering(content, [], peerPreferences={}, currentPreference=profile)
        return rankRecommendations(calculateRecommendationScore(combined))

    original = scores(items)
    enriched = scores([enrich_candidate_pricing(item) for item in items])
    assert [(x['destinationId'], x['score']) for x in original] == [(x['destinationId'], x['score']) for x in enriched]
    projected = [recommendations._snapshot_item(item, 'fallback') for item in original]
    assert [(x['destinationId'], x['score']) for x in projected] == [(x['destinationId'], x['score']) for x in original]
