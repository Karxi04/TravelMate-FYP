"""Local logic-only smoke test. Does not need Firebase or provider API keys."""
from services.local_catalog import DESTINATIONS, FLIGHTS, LOCAL_HOTEL_ITEMS
from sequence_contract.domain_functions import (
    prepareRecommendationInput, applyContentBasedFiltering, applyCollaborativeFiltering,
    calculateRecommendationScore, rankRecommendations, generateItinerary,
    groupNearbyActivities, checkOpeningHoursAndTravelTime, adjustWeatherSensitiveActivities,
    calculateBudget, compareBudget, buildLowerCostAlternatives,
)

pref = {
    'interests': ['Culture', 'Food', 'Heritage'],
    'travelType': 'Culture',
    'travelPurpose': 'Holiday',
    'travelPersonality': 'Explorer',
    'travelPace': 'Moderate',
    'budgetRange': 'Moderate',
}

prepared = prepareRecommendationInput(pref, DESTINATIONS, [])
ranked = rankRecommendations(
    calculateRecommendationScore(
        applyCollaborativeFiltering(
            applyContentBasedFiltering(prepared), [], currentPreference=pref
        )
    )
)
assert len(ranked) >= 5
assert ranked[0]['rankNo'] == 1
assert 'scoreBreakdown' in ranked[0]

trip = {
    'title': 'Functional test',
    'startDate': '2026-09-05',
    'endDate': '2026-09-07',
    'travellerCount': 1,
    'budgetLimit': 500,
    'flightCost': 129,
    'hotelCost': 238,
    'activities': [
        {
            'activityId': f'A{i+1}',
            'activityName': d['title'],
            'destinationId': d['destinationId'],
            'estimatedCost': d['estimatedCost'],
            'gps_coordinates': d['gps_coordinates'],
            'type': d['type'],
            'indoor': d['indoor'],
        }
        for i, d in enumerate(DESTINATIONS[:7])
    ],
}
forecast = {
    'daily': {
        'time': ['2026-09-05', '2026-09-06', '2026-09-07'],
        'precipitation_probability_max': [20, 80, 35],
        'weather_code': [1, 63, 2],
    }
}
plan = adjustWeatherSensitiveActivities(
    checkOpeningHoursAndTravelTime(
        groupNearbyActivities(generateItinerary([], forecast, trip))
    )
)
assert plan['tripDays'] == 3
assert plan['generationContext']['weatherConsideration'] is True
assert 2 in plan['generationContext']['rainyDayNumbers']

budget = calculateBudget(plan)
assert budget['status'] == 'over_budget'
assert budget['overBy'] > 0
assert compareBudget(budget)
alternatives = buildLowerCostAlternatives(FLIGHTS, LOCAL_HOTEL_ITEMS, budget, plan)
assert alternatives

print('PASS: recommendation engine')
print('PASS: smart itinerary generator')
print('PASS: weather consideration')
print('PASS: budget estimation/comparison')
print('PASS: lower-cost alternatives')
