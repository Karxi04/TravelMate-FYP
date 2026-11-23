"""PR93 cross-module comparisons: real routes, owned in-memory records, no live suppliers."""
from copy import deepcopy
import json

import pytest

from test_budget_provider_discovery import scenario, BASE, discover
from test_fr05_advisory_apply import HEADERS
from modules.fr05_smart_itinerary_budget_planner import routes as r
from modules.fr07_flight_search import routes as fr7


def saved_comparison(client, category, search):
    response = client.post(BASE, headers=HEADERS, json={'searchIds': {category: search['searchId']}})
    assert response.status_code == 200, response.json
    return response.json


@pytest.mark.parametrize('category', ['flight', 'hotel'])
@pytest.mark.parametrize('patch', [
    {'budgetEstimate': {'total': 1465}, 'updatedAt': '2027-01-01T12:00:00Z'},
    {'planningMode': 'assisted', 'itineraryRevision': 2},
    {'travelDayPreferences': {'days': [{'dayNo': 2, 'startTime': '11:00', 'endTime': '17:00'}]}},
    {'planningBlocks': [{'blockId': 'rest-synthetic', 'label': 'Rest', 'type': 'rest',
                         'dayNo': 2, 'startTime': '12:00', 'endTime': '13:00', 'locked': True}]},
    {'foodCost': 370},
])
def test_saved_supplier_evidence_survives_unrelated_changes_but_old_offer_is_stale(client, scenario, category, patch):
    memory, _, flight, returns, hotel, writes, _ = scenario
    search = discover(client, category).json['search']
    before = saved_comparison(client, category, search)
    offer = next(row for row in before['alternatives'] if row['alternativeType'] == category)
    calls = (flight.call_count, returns.call_count, hotel.call_count)
    memory.update('itineraries', 'trip', deepcopy(patch))
    after = saved_comparison(client, category, search)
    summary = after['searches'][category]
    assert summary['searchStatus'] == 'completed', summary
    assert summary['providerReached'] and summary['validQuoteCount'] == 1
    assert after['stateVersion'] != before['stateVersion']
    refreshed = next(row for row in after['alternatives'] if row['alternativeType'] == category)
    assert refreshed['stateVersion'] == after['stateVersion']
    assert client.post(BASE + '/apply', headers=HEADERS, json={'alternative': offer}).status_code == 409
    assert client.post(BASE + '/preview', headers=HEADERS, json={'alternative': refreshed}).status_code == 200
    assert calls == (flight.call_count, returns.call_count, hotel.call_count) and not writes


@pytest.mark.parametrize('category', ['flight', 'hotel'])
def test_changed_supplier_baseline_does_not_reuse_old_search(client, scenario, category):
    memory, trip, _, _, _, writes, _ = scenario
    search = discover(client, category).json['search']
    selected = deepcopy(trip['selectedFlight' if category == 'flight' else 'selectedHotel'])
    selected['price'] += 10
    memory.update('itineraries', 'trip', {f'{category}Cost': selected['price'],
                  'selectedFlight' if category == 'flight' else 'selectedHotel': selected})
    summary = saved_comparison(client, category, search)['searches'][category]
    assert summary['searchStatus'] == 'needs_review' and summary['reasonCode'] == 'search_mismatch'
    assert not writes


@pytest.mark.parametrize('category', ['flight', 'hotel'])
def test_exact_saved_receipts_survive_derived_changes_and_cache_eviction(client, scenario, monkeypatch, category):
    memory, _, _, _, _, writes, _ = scenario
    search = discover(client, category).json['search']
    memory.update('itineraries', 'trip', {'budgetEstimate': {'total': 1465}})
    original = memory.retrieve
    def retrieve(collection, document_id=None, **kwargs):
        # Simulate a bounded collection query omitting the recent records.
        if document_id is None and collection in {'flight_quotes', 'hotel_offer_quotes'}:
            return []
        return original(collection, document_id, **kwargs)
    fr7.reset_flight_quotes()
    from modules.fr08_hotel_booking import routes as fr8
    for module in (r, fr7, fr8):
        monkeypatch.setattr(module, 'retrieveRecord', retrieve)
    body = saved_comparison(client, category, search)
    assert body['searches'][category]['searchStatus'] == 'completed'
    assert len([row for row in body['alternatives'] if row['alternativeType'] == category]) == 1
    assert not writes


@pytest.mark.parametrize('category', ['flight', 'hotel'])
def test_real_planning_apply_then_budget_read_rechecks_saved_quotes(client, scenario, monkeypatch, category):
    memory, _, flight, returns, hotel, writes, _ = scenario
    search = discover(client, category).json['search']
    before = deepcopy(memory.retrieve('itineraries', 'trip'))
    def update(collection, identity, patch, expected=None):
        assert expected == memory.retrieve(collection, identity)
        return memory.update(collection, identity, patch)
    monkeypatch.setattr(r, 'updateRecord', update)
    path = '/api/fr5/itineraries/trip/flight-adjustment'
    preview = client.post(path + '/preview', headers=HEADERS, json={'planningChanges': {
        'planningMode': 'assisted', 'travelDayPreferences': {'days': [
            {'dayNo': 2, 'startTime': '10:00', 'endTime': '17:00'}]}}})
    assert preview.status_code == 200, preview.json
    assert preview.json['preview']['canApply'], preview.json
    assert memory.retrieve('itineraries', 'trip') == before
    applied = client.post(path + '/apply', headers=HEADERS,
                          json={'previewId': preview.json['preview']['previewId']})
    assert applied.status_code == 200, applied.json
    current = deepcopy(memory.retrieve('itineraries', 'trip'))
    assert client.get('/api/fr5/itineraries/trip/budget', headers=HEADERS).status_code == 200
    assert memory.retrieve('itineraries', 'trip') == current
    body = saved_comparison(client, category, search)
    assert body['searches'][category]['searchStatus'] == 'completed'
    assert body['searches'][category]['recheckedForCurrentTrip']
    assert body['searches'][category]['cheaperCandidateCount'] == 1
    assert current['selectedFlight'] == before['selectedFlight']
    assert current['selectedHotel'] == before['selectedHotel']
    assert flight.call_count == returns.call_count == (1 if category == 'flight' else 0)
    assert hotel.call_count == (1 if category == 'hotel' else 0) and not writes


@pytest.mark.parametrize('original,target,mode', [(1, 1, 'same_cabin'), (3, 3, 'same_cabin'),
                                               (3, 1, 'include_lower'), (3, 2, 'include_lower')])
def test_cabin_and_current_plan_comparison_diagnostic_evidence(client, scenario, original, target, mode, record_property):
    from test_final_travel_workflows import configure_cabin, search as flight_search
    memory, _, outbound, returns, _, writes, _ = scenario
    configure_cabin(memory, original, outbound, returns)
    search = flight_search(client, mode, target).json['search']
    memory.update('itineraries', 'trip', {'planningMode': 'assisted'})
    body = client.post(BASE, headers=HEADERS, json={'cabinComparison': mode, 'comparisonCabin': target,
                                                  'searchIds': {'flight': search['searchId']}}).json
    offer = next(row for row in body['alternatives'] if row['alternativeType'] == 'flight')
    summary = body['searches']['flight']
    assert summary['searchStatus'] == 'completed' and summary['cheaperCandidateCount'] == 1
    assert offer['data']['cabin']['comparisonCabin'] == target
    assert offer['data']['cabin']['cabinDowngrade'] == (target < original)
    assert client.post(BASE + '/preview', headers=HEADERS, json={'alternative': offer}).status_code == 200
    assert not writes
    assert client.post(BASE + '/apply', headers=HEADERS, json={'alternative': offer}).status_code == 200
    saved = client.get('/api/fr5/itineraries/trip', headers=HEADERS).json['itinerary']
    assert saved['flightCost'] == 420 and saved['selectedFlight']['requestedTravelClass'] == target
    assert len(writes) == 1
    record_property('sanitized_supplier_evidence', json.dumps({'synthetic': True, 'category': 'flight',
        'originalCabin': original, 'comparisonCabin': target, 'comparisonMode': mode,
        **{key: summary.get(key) for key in ('searchStatus', 'providerReached', 'requestsAttempted',
           'candidateCount', 'validQuoteCount', 'cheaperCandidateCount', 'timingConflictCount',
           'rejectedCount', 'rejectionCounts', 'comparisonRejectionCounts', 'expiresAt')},
        'originalMYR': 600, 'proposedMYR': 420, 'savingsMYR': 180, 'savedExactlyOnce': True}))


def test_hotel_saved_search_diagnostics_cancel_confirm_reopen(client, scenario, record_property):
    memory, _, flight, returns, hotels, writes, _ = scenario
    search = discover(client, 'hotel').json['search']
    memory.update('itineraries', 'trip', {'planningMode': 'manual', 'budgetEstimate': {'total': 1465}})
    body = saved_comparison(client, 'hotel', search)
    summary = body['searches']['hotel']
    offer = next(row for row in body['alternatives'] if row['alternativeType'] == 'hotel')
    before = deepcopy(memory.retrieve('itineraries', 'trip'))
    assert client.post(BASE + '/preview', headers=HEADERS, json={'alternative': offer}).status_code == 200
    assert memory.retrieve('itineraries', 'trip') == before and not writes
    assert client.post(BASE + '/apply', headers=HEADERS, json={'alternative': offer}).status_code == 200
    saved = client.get('/api/fr5/itineraries/trip', headers=HEADERS).json['itinerary']
    assert saved['hotelCost'] == 250 and saved['selectedHotel']['name'] == 'Cheaper Hotel'
    assert saved['selectedHotel']['planningOnly'] is True
    assert saved['budgetEstimate']['hotel'] == 250 and len(writes) == 1
    assert client.post(BASE + '/apply', headers=HEADERS, json={'alternative': offer}).status_code == 409
    assert hotels.call_count == 1 and not flight.called and not returns.called
    record_property('sanitized_supplier_evidence', json.dumps({'synthetic': True, 'category': 'hotel',
        **{key: summary.get(key) for key in ('searchStatus', 'providerReached', 'requestsAttempted',
           'candidateCount', 'validQuoteCount', 'cheaperCandidateCount', 'timingConflictCount',
           'rejectedCount', 'rejectionCounts', 'comparisonRejectionCounts', 'expiresAt')},
        'originalMYR': 400, 'proposedMYR': 250, 'savingsMYR': 150, 'savedExactlyOnce': True}))


@pytest.mark.parametrize('category', ['flight', 'hotel'])
def test_legacy_receipt_keeps_strict_revision_rule(client, scenario, category):
    memory, _, _, _, _, writes, _ = scenario
    search = discover(client, category).json['search']
    memory.collections['budget_alternative_searches'][search['searchId']].pop('searchContextVersion')
    assert saved_comparison(client, category, search)['searches'][category]['searchStatus'] == 'completed'
    memory.update('itineraries', 'trip', {'planningMode': 'manual'})
    assert saved_comparison(client, category, search)['searches'][category]['reasonCode'] == 'search_mismatch'
    assert not writes
