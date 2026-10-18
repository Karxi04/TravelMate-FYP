import pytest
from unittest.mock import patch

PACKAGE_TRIP = {
    'id': 'package_trip_123',
    'travellerId': 'test_traveller_uid',
    'title': '4D3N Penang Heritage & Food Trail',
    'destinationArea': 'Penang',
    'startDate': '2026-11-01',
    'endDate': '2026-11-04',
    'travellerCount': 2,
    'budgetLimit': 1600.0,
    'tripType': 'package',
    'packageTrip': True,
    'packageId': 'pkg_penang_001',
    'checkoutOrderId': 'order_stripe_999',
    'budgetEstimate': {
        'totalBudget': 1600.0,
        'activityCost': 0.0,
        'packageCost': 1600.0,
        'flightCost': 0.0,
        'hotelCost': 0.0,
        'remainingBudget': 0.0,
        'overBudget': False,
    },
    'packageSnapshot': {
        'packageId': 'pkg_penang_001',
        'title': '4D3N Penang Heritage & Food Trail',
        'itineraryDays': [
            {
                'dayNumber': 1,
                'title': 'Arrival & Heritage Exploration',
                'activities': [
                    {
                        'activityName': 'Penang Street Art Walk',
                        'scheduledTime': '10:00 AM',
                        'location': 'George Town',
                    }
                ],
            }
        ],
    },
    'activities': [],
}

PERSONALIZED_TRIP = {
    'id': 'personalized_trip_123',
    'travellerId': 'test_traveller_uid',
    'title': 'My Penang Discovery',
    'destinationArea': 'Penang',
    'startDate': '2026-11-01',
    'endDate': '2026-11-04',
    'travellerCount': 1,
    'budgetLimit': 1000.0,
    'tripType': 'personalized',
    'packageTrip': False,
    'activities': [
        {
            'activityId': 'A1',
            'activityName': 'Kek Lok Si Temple',
            'dayNo': 1,
            'timeSlot': '09:00',
            'estimatedCost': 20.0,
        }
    ],
}


def test_get_itinerary_route_success(client, mock_traveller_auth):
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', return_value=PACKAGE_TRIP):
        res = client.get('/api/fr5/itineraries/package_trip_123', headers={'Authorization': 'Bearer valid_test_token'})
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert data['itinerary']['id'] == 'package_trip_123'
        assert data['itinerary']['tripType'] == 'package'


def test_get_itinerary_route_cross_account_forbidden(client, mock_traveller_auth):
    other_user_trip = {**PACKAGE_TRIP, 'travellerId': 'another_user'}
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', return_value=other_user_trip):
        res = client.get('/api/fr5/itineraries/package_trip_123', headers={'Authorization': 'Bearer valid_test_token'})
        assert res.status_code == 404
        assert res.get_json()['error'] == 'Itinerary not found'


def test_package_trip_mutation_endpoints_rejected_with_409(client, mock_traveller_auth):
    headers = {'Authorization': 'Bearer valid_test_token'}
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', return_value=PACKAGE_TRIP):
        # 1. Update itinerary
        res = client.put('/api/fr5/itineraries/package_trip_123', headers=headers, json={'title': 'Changed Title'})
        assert res.status_code == 409
        assert 'Purchased package trips cannot be modified' in res.get_json()['error']

        # 2. Generate / recalculate itinerary
        res = client.post('/api/fr5/itineraries/package_trip_123/generate', headers=headers, json={})
        assert res.status_code == 409
        assert 'Purchased package trips cannot be modified' in res.get_json()['error']

        # 3. Save itinerary
        res = client.post('/api/fr5/itineraries/package_trip_123/save', headers=headers, json={})
        assert res.status_code == 409
        assert 'Purchased package trips cannot be modified' in res.get_json()['error']

        # 4. Add activity
        res = client.post('/api/fr5/itineraries/package_trip_123/activities', headers=headers, json={'activityName': 'New Activity'})
        assert res.status_code == 409
        assert 'Purchased package trips cannot be modified' in res.get_json()['error']

        # 5. Update activity
        res = client.put('/api/fr5/itineraries/package_trip_123/activities/A1', headers=headers, json={'activityName': 'Updated'})
        assert res.status_code == 409
        assert 'Purchased package trips cannot be modified' in res.get_json()['error']

        # 6. Delete activity
        res = client.delete('/api/fr5/itineraries/package_trip_123/activities/A1', headers=headers)
        assert res.status_code == 409
        assert 'Purchased package trips cannot be modified' in res.get_json()['error']

        # 7. Rearrange activities
        res = client.post('/api/fr5/itineraries/package_trip_123/activities/rearrange', headers=headers, json={'orderedActivityIds': []})
        assert res.status_code == 409
        assert 'Purchased package trips cannot be modified' in res.get_json()['error']

        # 8. Flight adjustment preview
        res = client.post('/api/fr5/itineraries/package_trip_123/flight-adjustment/preview', headers=headers, json={})
        assert res.status_code == 409
        assert 'Purchased package trips cannot be modified' in res.get_json()['error']

        # 9. Flight adjustment apply
        res = client.post('/api/fr5/itineraries/package_trip_123/flight-adjustment/apply', headers=headers, json={'previewId': 'prev_1'})
        assert res.status_code == 409
        assert 'Purchased package trips cannot be modified' in res.get_json()['error']

        # 10. Remove hotel selection
        res = client.post('/api/fr5/itineraries/package_trip_123/hotel-selection/remove', headers=headers, json={})
        assert res.status_code == 409
        assert 'Purchased package trips cannot be modified' in res.get_json()['error']

        # 11. Lower cost alternatives preview
        res = client.post('/api/fr5/itineraries/package_trip_123/lower-cost-alternatives', headers=headers)
        assert res.status_code == 409
        assert 'Purchased package trips cannot be modified' in res.get_json()['error']

        # 12. Lower cost alternatives apply
        res = client.post('/api/fr5/itineraries/package_trip_123/lower-cost-alternatives/apply', headers=headers, json={})
        assert res.status_code == 409
        assert 'Purchased package trips cannot be modified' in res.get_json()['error']

        # 13. Delete itinerary
        res = client.delete('/api/fr5/itineraries/package_trip_123', headers=headers)
        assert res.status_code == 409
        assert 'Purchased package trips cannot be deleted' in res.get_json()['error']


def test_package_trip_budget_preserves_immutable_costs(client, mock_traveller_auth):
    headers = {'Authorization': 'Bearer valid_test_token'}
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', return_value=PACKAGE_TRIP):
        res = client.get('/api/fr5/itineraries/package_trip_123/budget', headers=headers)
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert data['budget']['packageCost'] == 1600.0


def test_personalized_trip_remains_modifiable(client, mock_traveller_auth):
    headers = {'Authorization': 'Bearer valid_test_token'}
    with patch('modules.fr05_smart_itinerary_budget_planner.routes.retrieveRecord', return_value=PERSONALIZED_TRIP), \
         patch('modules.fr05_smart_itinerary_budget_planner.routes.updateRecord', side_effect=lambda _c, _i, d: {**PERSONALIZED_TRIP, **d}):
        res = client.put('/api/fr5/itineraries/personalized_trip_123', headers=headers, json={'title': 'Updated Title'})
        assert res.status_code == 200
        assert res.get_json()['ok'] is True
