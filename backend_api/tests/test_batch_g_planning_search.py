from copy import deepcopy
from unittest.mock import patch

import pytest

from modules.fr03_destination_search_information import routes as explore
from modules.fr05_smart_itinerary_budget_planner import routes as trips
from sequence_contract.domain_functions import (
    applyContentBasedFiltering, calculateBudget, calculateRecommendationScore, prepareRecommendationInput,
)
from services.local_catalog import DESTINATIONS
from services.trip_budget_replan import budget_replan_options, preview_budget_replan

AUTH = {'Authorization': 'Bearer valid_test_token'}
POOL = [
    {'destinationId': f'fixture-{index}', 'title': f'Visitor venue {index}',
     'address': 'George Town, Penang, Malaysia', 'type': category,
     'ratingSource': 'provider', 'reviews': reviews, 'rating': 4.4,
     'openingHours': hours, 'recommendedDurationMinutes': 55,
     'gps_coordinates': {'latitude': 5.42 + index * .001, 'longitude': 100.33},
     'purpose': [purpose], 'personality': [personality], 'pace': [pace], 'budgetLevel': cost,
     'estimatedCost': price, 'unitPrice': price, 'pricingUnit': 'per_group', 'costProvenance': 'catalog_estimate'}
    for index, (category, reviews, hours, purpose, personality, pace, cost, price) in enumerate([
        ('Heritage museum', 1500, '08:00-20:00', 'Educational trip', 'Planner', 'Moderate', 'Budget', 10),
        ('Cultural site', 65, '08:00-20:00', 'Family trip', 'Social', 'Relaxed', 'Premium', 90),
        ('Botanical garden', 1200, '08:00-20:00', 'Family trip', 'Relaxed', 'Relaxed', 'Budget', 15),
        ('Shopping mall', 42, '08:00-20:00', 'Solo travel', 'Explorer', 'Packed', 'Premium', 80),
        ('Public park', 66, '08:00-20:00', 'Solo travel', 'Explorer', 'Packed', 'Budget', 0),
        ('Historic site', 530, '08:00-20:00', 'Educational trip', 'Planner', 'Moderate', 'Moderate', 25),
        ('Museum', 10, 'Closed', 'Solo travel', 'Social', 'Relaxed', 'Budget', 0),
    ])
]
TRIP = {
    'destinationArea': 'Penang', 'startDate': '2027-01-12', 'endDate': '2027-01-12',
    'budgetLimit': 140, 'travellerCount': 1, 'travelMode': 'public_transport',
    'accommodationChoice': 'return_home', 'carRentalChoice': 'not_required',
}


def _plan(profile):
    scored = calculateRecommendationScore(applyContentBasedFiltering(prepareRecommendationInput(profile, deepcopy(POOL))))
    rows = sorted(scored, key=lambda row: -row['score'])
    snapshot = {'recommendationGenerationId': 'fixture-generation',
                'recommendationResults': rows, 'planningPreferences': profile}
    with patch.object(trips, '_forecast_for', return_value=({}, None)):
        plan = trips._generate_itinerary_data(TRIP, {}, snapshot)
    return plan, {row['destinationId']: row['contentSignals'] for row in rows}


def test_schedule_obeys_sleep_pace_opening_hours_and_absolute_budget(monkeypatch):
    monkeypatch.setenv('TRAVELMATE_BUDGET_AWARE_SELECTION_ENABLED', 'false')
    early, _ = _plan({'sleepingType': 'Early riser', 'travelPace': 'Packed'})
    late, _ = _plan({'sleepingType': 'Night owl', 'travelPace': 'Packed'})
    comfort, _ = _plan({'sleepingType': 'Comfort-focused', 'travelPace': 'Moderate'})
    easy, _ = _plan({'sleepingType': 'Flexible', 'travelPace': 'Relaxed'})
    assert early['activities'][0]['scheduledStartTime'] == '08:00'
    assert late['activities'][0]['scheduledStartTime'] == '11:00'
    assert comfort['dailySchedule'][0]['planningBlocks'][0]['durationMinutes'] == 90
    assert len(easy['activities']) == 2 < len(early['activities'])
    assert all('fixture-6' not in {row['destinationId'] for row in plan['activities']}
               for plan in (early, late, comfort, easy))
    premium, _ = _plan({'budgetRange': 'Premium', 'travelPace': 'Packed'})
    assert premium['budgetLimit'] == TRIP['budgetLimit']
    assert calculateBudget(premium)['overBy'] > 0


@pytest.mark.parametrize('field,values,signal', [
    ('travelPersonality', ('Planner', 'Explorer'), 'travelPersonality'),
    ('travelType', ('Popular landmarks', 'Lesser-known places'), 'travelType'),
    ('interests', (['Culture', 'Heritage'], ['Nature', 'Shopping']), 'interests'),
    ('budgetRange', ('Budget', 'Premium'), 'budget'),
    ('travelPace', ('Relaxed', 'Packed'), 'pace'),
    ('travelPurpose', ('Family trip', 'Solo travel'), 'travelPurpose'),
])
def test_profiles_use_the_same_candidates_and_evidence(field, values, signal):
    left_plan, left = _plan({field: values[0]})
    right_plan, right = _plan({field: values[1]})
    assert [row['destinationId'] for row in left_plan['activities']] != [
        row['destinationId'] for row in right_plan['activities']]
    assert left.keys() == right.keys()
    assert any(left[key][signal]['score'] != right[key][signal]['score'] for key in left)
    assert all(row['score'] >= 0 for row in left['fixture-0'].values())


@pytest.mark.parametrize('query,identity', [
    ('KLCC', 'local_klcc'), ('Petronas Twin Towers', 'local_klcc'),
    ('Menara Berkembar Petronas', 'local_klcc'), ('LEGOLAND', 'local_legoland_malaysia'),
    ('Bukit Bendera', 'local_penang_hill'), ('Langkawi Sky Bridge', 'local_langkawi_skycab'),
    ('Tunku Abdul Rahman', 'local_tunku_abdul_rahman'),
    ('Sarawak Cultural', 'local_sarawak_cultural_village'),
])
def test_nationwide_named_search_survives_empty_provider(client, app, mock_traveller_auth, query, identity):
    app.config['LOCAL_FYP_SAMPLE_REVIEWS'] = False
    with patch.object(explore, 'retrieveDestinationResults', return_value={'local_results': []}), \
         patch.object(explore, 'retrieveRecord', return_value=[]), patch.object(explore, '_cache'):
        response = client.get('/api/fr3/destinations/search', headers=AUTH,
                              query_string={'q': query, 'location': 'Malaysia'})
    assert response.status_code == 200, response.json
    first = response.json['results'][0]
    assert first['destinationId'] == identity
    assert first['candidateSource'] == 'local_catalog'


def test_sky_bridge_keeps_distinct_places_and_strict_geography(client, mock_traveller_auth):
    candidates = [row for row in DESTINATIONS if row['destinationId'] in {'local_klcc', 'local_langkawi_skycab'}]
    with patch.object(explore, 'retrieveDestinationResults', side_effect=[
            {'local_results': []}, {'local_results': candidates}]), \
         patch.object(explore, 'retrieveRecord', return_value=[]), patch.object(explore, '_cache'):
        common = client.get('/api/fr3/destinations/search?q=Sky+Bridge&location=Malaysia', headers=AUTH)
        state = client.get('/api/fr3/destinations/search?q=Sky+Bridge&location=Kedah', headers=AUTH)
    assert {item['destinationId'] for item in common.json['results']} == {'local_klcc', 'local_langkawi_skycab'}
    assert [item['destinationId'] for item in state.json['results']] == ['local_langkawi_skycab']


def test_legoland_provider_identity_preserves_genuine_ratings_in_all_modes(client, app, mock_traveller_auth):
    venue = next(row for row in DESTINATIONS if row['destinationId'] == 'local_legoland_malaysia')
    provider = {**venue, 'destinationId': 'mock-provider-resort', 'place_id': 'mock-provider-resort'}
    assert explore._review_identity(provider) == 'local_legoland_malaysia'
    assert explore._review_identity({**provider, 'title': 'LEGOLAND Hotel'}) is None
    assert explore._review_identity({**provider, 'gps_coordinates': {'latitude': 3.15, 'longitude': 101.7}}) is None
    historic = {'id': 'genuine', 'travellerId': 'test-author', 'rating': 4,
                'moderationStatus': 'reviewed', 'feedbackStatus': 'visible', 'comment': 'Genuine review.'}
    def read(collection, *args, filters=None, **kwargs):
        if collection == 'destination_cache':
            return provider
        return [historic] if collection == 'feedback' and filters == [('destinationId', '==', 'mock-provider-resort')] else []
    auth = {**AUTH, 'X-TravelMate-Review-Context': 'fyp-v1'}
    path = '/api/fr3/destinations/mock-provider-resort/ratings-reviews?view=unified'
    with patch.object(explore, 'retrieveRecord', side_effect=read):
        app.config['LOCAL_FYP_SAMPLE_REVIEWS'] = True
        combined = client.get(path, headers=auth).json['result']
        app.config['LOCAL_FYP_SAMPLE_REVIEWS'] = False
        public = client.get(path, headers=auth).json['result']
    assert (combined['rating'], combined['reviews']) == (public['rating'], public['reviews'])
    assert combined['user_reviews'][:1] == public['user_reviews']
    assert combined['sampleSummary'] == {'rating': 3.7, 'reviews': 3}
    assert all(row['synthetic'] and row['source'] == 'fyp_private' for row in combined['user_reviews'][1:])
    assert 'sampleSummary' not in public
    assert [row['id'] for row in public['user_reviews']] == ['genuine']
    assert [row['id'] for row in combined['user_reviews'] if not row.get('synthetic')] == ['genuine']
    assert combined['reviews'] == public['reviews'] == 1
    assert combined['rating'] == public['rating'] == 4
    assert 'sampleSummary' not in public


def test_trip_estimates_remove_only_explicit_unpaid_unlinked_selections():
    trip = {**TRIP, 'id': 'fixture', 'budgetLimit': 800,
            'selectedFlight': {'planningOnly': True, 'price': 282}, 'flightPriceBasis': 'total',
            'flightCurrency': 'MYR', 'flightCost': 282, 'travelMode': 'flight',
            'selectedHotel': {'price': 504.92, 'currency': 'MYR'}, 'hotelBookingId': 'historic',
            'hotelCost': 504.92, 'hotelCurrency': 'MYR', 'accommodationChoice': 'paid_hotel',
            'foodCost': 400, 'transportCost': 170}
    before = deepcopy(trip)
    options = budget_replan_options(trip, calculateBudget(trip))['travelSelections']
    assert options == {'flight': {'amount': 282, 'canDetach': True}, 'hotel': {'amount': 504.92, 'canDetach': False}}
    patch_data, preview = preview_budget_replan(trip, {'detachFlight': True})
    assert preview['before']['total'] == 1356.92
    assert preview['budget']['total'] == 1074.92
    assert preview['budget']['overBy'] == 274.92
    assert preview['detachedSelections'] == ['flight']
    assert trip == before and 'hotelBookingId' not in patch_data
    with pytest.raises(ValueError, match='unpaid'):
        preview_budget_replan(trip, {'detachHotel': True})
    with pytest.raises(ValueError, match='unpaid'):
        preview_budget_replan({**trip, 'paidTotal': 146.18}, {'detachFlight': True})
