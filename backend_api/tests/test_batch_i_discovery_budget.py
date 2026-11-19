from collections import Counter
from copy import deepcopy
from unittest.mock import Mock

import pytest

from test_local_reviews import memory, headers
from sequence_contract.domain_functions import diversifyRecommendations, calculateBudget
from services.destination_candidates import same_place, merge_candidates
from services.destination_research import attraction_identities, named_attractions, attraction_identity
from services.trip_budget_replan import budget_replan_options, preview_budget_replan
from services.recommendation_taxonomy import experience_types


def test_nationwide_identity_sources_and_honest_coverage_boundary():
    rows = attraction_identities()
    assert len(rows) == 400
    assert len({row['destinationId'] for row in rows}) == 400
    assert set(Counter(row['state'] for row in rows).values()) == {25}
    assert len({row['state'] for row in rows}) == 16
    for row in rows:
        assert (row['destinationId'].startswith('local_') or row['destinationId'] == 'demo_penang_street_art') and row['city']
        assert row['identitySourceUrl'].startswith('https://')
        assert set(row) - {'gps_coordinates', 'coordinatesSourceUrl'} == {'destinationId', 'title', 'city', 'state', 'country', 'category', 'identitySourceUrl'}
        assert attraction_identity(row['destinationId'])['state'] == row['state']
        assert attraction_identity(row['destinationId'])['destinationId'] == row['destinationId']
        if row.get('gps_coordinates'):
            from services.malaysia_boundary import coordinate_state
            assert coordinate_state(**row['gps_coordinates']) == row['state']
            assert row['coordinatesSourceUrl'].startswith('https://')
    from services.local_catalog import DESTINATIONS
    assert len(DESTINATIONS) == 36  # Missing pins/prices are not injected into scheduling pools.


def test_new_attraction_discovery_details_and_review_identity_need_no_live_provider(client, memory, monkeypatch):
    from modules.fr03_destination_search_information import routes
    provider = Mock(side_effect=AssertionError('Named sourced identities require no paid request'))
    monkeypatch.setattr(routes, 'retrieveDestinationResults', provider)
    monkeypatch.setattr(routes, 'retrieveDestinationDetails', provider)
    monkeypatch.setattr(routes, '_private_review_dataset', lambda **kwargs: None)
    for name in ['Gua Kelam Recreational Park', 'Taman Seri Empangan', 'Labuan Marine Museum']:
        response = client.get('/api/fr3/destinations/search', headers=headers(), query_string={'q': name, 'location': 'Malaysia'})
        assert response.status_code == 200, response.json
        rows = response.json['results']
        assert len(rows) == 1 and rows[0]['title'] == name
        assert rows[0]['metadataStatus'] in {'identity_only', 'identity_and_coordinates'}
        assert rows[0].get('rating') is None
        assert rows[0].get('gps_coordinates') == named_attractions(name)[0].get('gps_coordinates')
        did = rows[0]['destinationId']
        detail = client.get('/api/fr3/destinations/' + did, headers=headers())
        assert detail.json['destination']['reviewDestinationId'] == did
        assert detail.json['destination']['materialWarning']
        for account in ['owner', 'second', 'new-registration']:
            body = client.get('/api/fr3/destinations/' + did + '/ratings-reviews', headers=headers(account)).json['result']
            assert body['rating'] is None and body['reviews'] == 0 and body['user_reviews'] == []
    provider.assert_not_called()
    assert not memory


def test_batu_caves_address_variants_aliases_and_distinct_sites():
    a = {'destinationId': 'provider-a', 'title': 'Batu Caves', 'address': 'Batu Caves, Gombak, Selangor',
         'gps_coordinates': {'latitude': 3.2379, 'longitude': 101.6840}}
    b = {**a, 'destinationId': 'provider-b', 'address': 'Batu Caves, Kampung Laksamana, Selangor',
         'openingHours': 'Daily 08:00-18:00'}
    assert same_place(a, b)
    merged = merge_candidates([a], [b])
    assert len(merged) == 1 and merged[0]['openingHours'] == b['openingHours']
    assert set(merged[0]['identityAliases']) == {'provider-a', 'provider-b'}
    assert same_place(merged[0], {'destinationId': 'provider-b'})
    assert not same_place(a, {**b, 'title': 'Batu Caves Car Park'})
    assert not same_place(a, {**b, 'title': 'Sri Venkatachalapathi Temple'})
    assert not same_place(a, {**b, 'gps_coordinates': {'latitude': 3.5, 'longitude': 101.9}})
    for invalid in [None, 'not-an-alias-list', [{}]]:
        assert not same_place({**a, 'identityAliases': invalid}, {'destinationId': 'unrelated'})


def test_near_score_experience_variety_does_not_change_hybrid_scores_or_label_hills_as_hiking():
    rows = [{'destinationId': f'hill-{i}', 'title': f'Hill {i}', 'category': 'Nature',
             'score': 90 - i, 'destinationConcepts': ['nature']} for i in range(7)]
    rows += [{'destinationId': name, 'title': name, 'category': 'Nature', 'score': 85,
              'destinationConcepts': ['nature']} for name in ['Beach', 'Botanic Garden', 'Waterfall']]
    original = deepcopy(rows)
    ranked = diversifyRecommendations(rows, {'interests': ['Nature']}, limit=10, coverageAware=True)
    assert len([row for row in ranked[:5] if 'hill_visit' in experience_types(row)]) <= 2
    assert len({kind for row in ranked[:5] for kind in experience_types(row)}) >= 3
    assert all(row['score'] == next(source['score'] for source in rows if source['destinationId'] == row['destinationId']) for row in ranked)
    assert all('hiking' not in experience_types(row) for row in rows[:7])
    assert rows == original and len({row['destinationId'] for row in ranked}) == len(rows)


@pytest.mark.parametrize('limit', [200, 900, 800])
def test_budget_adjustments_are_meaningful_read_only_and_do_not_touch_paid_visits(limit):
    trip = {'title': 'Synthetic budget scenario', 'budgetLimit': limit, 'travellerCount': 1,
            'startDate': '2030-12-12', 'endDate': '2030-12-13', 'foodCost': 100, 'transportCost': 50,
            'activities': [
                {'activityId': 'paid', 'activityName': 'Protected visit', 'dayNo': 1, 'paid': True, 'estimatedCost': 20, 'pricingUnit': 'per_group', 'currency': 'MYR'},
                {'activityId': 'optional', 'activityName': 'Optional visit', 'dayNo': 2, 'estimatedCost': 30, 'pricingUnit': 'per_group', 'currency': 'MYR'},
            ]}
    before = deepcopy(trip)
    options = budget_replan_options(trip, calculateBudget(trip))
    assert [row['activityId'] for row in options['optionalVisits']] == ['optional']
    patch, preview = preview_budget_replan(trip, {'foodCost': 70, 'transportCost': 40})
    assert preview['estimatedReduction'] == 40
    assert patch['activities'] == trip['activities'] if 'activities' in patch else True
    assert trip == before
    with pytest.raises(ValueError, match='unpaid'):
        preview_budget_replan(trip, {'removeActivityIds': ['paid']})
