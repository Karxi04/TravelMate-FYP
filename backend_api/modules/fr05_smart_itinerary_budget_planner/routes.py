import os
from flask import Blueprint, request, jsonify, g
from auth_utils import auth_required
from utils import utc_now_iso
from services.serpapi_service import retrieveLocationAndTravelTime, retrieveLowerCostFlights, retrieveDestinationResults
from services.open_meteo_service import retrieveSevenDayForecast, geocode
from services.local_catalog import DESTINATIONS, FLIGHTS, LOCAL_HOTEL_ITEMS
from sequence_contract.validators import validateItineraryInput, validateItineraryForSaving, validateSelectedDestination
from sequence_contract.firebase_firestore import retrieveRecord, storeRecord, updateRecord, deleteRecord
from sequence_contract.domain_functions import (
    createItinerary, addActivity, removeActivity, rearrangeActivity, updateActivity,
    checkDestinationExists, checkDestinationLimit, calculateBudget, compareBudget,
    buildLowerCostAlternatives, generateItinerary, groupNearbyActivities,
    checkOpeningHoursAndTravelTime, adjustWeatherSensitiveActivities,
)

bp = Blueprint('fr05_itineraries', __name__, url_prefix='/api/fr5')


def _fallback_mode():
    return os.getenv('FALLBACK_MODE', 'false').lower() in {'1', 'true', 'yes'}


def _own(iid):
    data = retrieveRecord('itineraries', iid)
    return data if data and data.get('travellerId') == g.uid else None


def _trip_days(current):
    from datetime import date
    try:
        if current.get('startDate') and current.get('endDate'):
            start = date.fromisoformat(str(current['startDate'])[:10])
            end = date.fromisoformat(str(current['endDate'])[:10])
            return max(1, (end - start).days + 1)
    except Exception:
        pass
    return 1


def _activity_from_destination(item, index):
    item = dict(item or {})
    gps = item.get('gps_coordinates') or item.get('gpsCoordinates') or {}
    return {
        'activityId': f'A{index + 1}',
        'activityName': item.get('title') or item.get('name') or f'Activity {index + 1}',
        'destinationId': item.get('destinationId') or item.get('place_id') or item.get('data_id') or item.get('id') or f'destination_{index + 1}',
        'address': item.get('address') or '',
        'dayNo': 1,
        'timeSlot': '',
        'estimatedCost': float(item.get('estimatedCost', 0) or 0),
        'gps_coordinates': gps,
        'type': item.get('type') or item.get('category') or '',
        'category': item.get('category') or item.get('type') or '',
        'description': item.get('description') or '',
        'openingHours': item.get('openingHours') or item.get('hours') or '',
        'indoor': bool(item.get('indoor', False)),
        'recommendedDurationMinutes': int(item.get('recommendedDurationMinutes', 90) or 90),
    }


def _destination_candidates(current):
    # 1. Use the traveller's ranked recommendations when available.
    recommendation = retrieveRecord('recommendations', g.uid) or {}
    items = list(recommendation.get('items', []) or [])
    if items:
        return items, recommendation.get('source', 'recommendation')

    # 2. Try live destination information using the itinerary destination.
    destination = str(current.get('destinationArea') or 'Malaysia').strip()
    if os.getenv('SERPAPI_KEY', '').strip():
        try:
            result = retrieveDestinationResults(f'top tourist attractions {destination}', destination)
            live = list(result.get('local_results', []) or [])
            if live:
                return live, 'serpapi'
        except Exception:
            pass

    # 3. Interactive deterministic fallback.
    if _fallback_mode():
        return [dict(x) for x in DESTINATIONS], 'local'
    return [], 'none'


def _forecast_for(current, payload):
    coords = payload.get('destinationCoordinates')
    if not coords:
        destination = str(payload.get('destinationName') or current.get('destinationArea') or '').strip()
        if destination:
            try:
                places = geocode(destination)
                if places:
                    coords = {'latitude': places[0]['latitude'], 'longitude': places[0]['longitude']}
            except Exception:
                coords = None
    if coords:
        try:
            return retrieveSevenDayForecast(coords), coords
        except Exception:
            pass
    return {}, coords


@bp.get('/itineraries')
@auth_required(['traveller'])
def list_itineraries():
    return jsonify({'ok': True, 'items': retrieveRecord('itineraries', filters=[('travellerId', '==', g.uid)])})


@bp.post('/itineraries')
@auth_required(['traveller'])
def create_itinerary_route():
    payload = request.get_json(silent=True) or {}
    if not validateItineraryInput(payload):
        return jsonify({'ok': False, 'error': 'Use a title, valid date range, positive traveller count and non-negative budget'}), 400
    itinerary = createItinerary(payload, g.uid)
    budget = calculateBudget(itinerary)
    itinerary['budgetEstimate'] = budget
    result = storeRecord('itineraries', itinerary)
    return jsonify({'ok': True, 'id': result['id'], 'itinerary': result, 'budget': budget}), 201


@bp.put('/itineraries/<iid>')
@auth_required(['traveller'])
def update_itinerary_route(iid):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    payload = request.get_json(silent=True) or {}
    if not validateItineraryInput({**current, **payload}):
        return jsonify({'ok': False, 'error': 'Use a title, valid date range, positive traveller count and non-negative budget'}), 400
    payload['updatedAt'] = utc_now_iso()
    merged = {**current, **payload}
    payload['budgetEstimate'] = calculateBudget(merged)
    return jsonify({'ok': True, 'itinerary': updateRecord('itineraries', iid, payload)})


@bp.post('/itineraries/<iid>/activities')
@auth_required(['traveller'])
def add_activity_route(iid):
    current = _own(iid)
    payload = request.get_json(silent=True) or {}
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    if payload.get('destinationId') and not validateSelectedDestination(payload.get('destinationId')):
        return jsonify({'ok': False, 'error': 'Invalid destination'}), 400
    if payload.get('destinationId') and checkDestinationExists(current, payload.get('destinationId')):
        return jsonify({'ok': False, 'error': 'Destination already exists in itinerary'}), 409
    if not checkDestinationLimit(current):
        return jsonify({'ok': False, 'error': 'Itinerary destination limit reached'}), 409
    activity = {
        'activityName': payload.get('activityName') or payload.get('title') or 'New activity',
        'destinationId': payload.get('destinationId', ''),
        'address': payload.get('address', ''),
        'dayNo': int(payload.get('dayNo', 1) or 1),
        'timeSlot': payload.get('timeSlot', ''),
        'estimatedCost': float(payload.get('estimatedCost', 0) or 0),
        'gps_coordinates': payload.get('gps_coordinates') or payload.get('gpsCoordinates') or {},
        'type': payload.get('type') or payload.get('category') or '',
        'category': payload.get('category') or payload.get('type') or '',
        'description': payload.get('description', ''),
        'openingHours': payload.get('openingHours', ''),
        'indoor': bool(payload.get('indoor', False)),
        'recommendedDurationMinutes': int(payload.get('recommendedDurationMinutes', 105) or 105),
    }
    updated = addActivity(current, activity)
    patch = {'activities': updated['activities'], 'updatedAt': updated['updatedAt']}
    patch['budgetEstimate'] = calculateBudget({**current, **patch})
    updateRecord('itineraries', iid, patch)
    return jsonify({'ok': True, 'activities': updated['activities'], 'budget': patch['budgetEstimate']})


@bp.delete('/itineraries/<iid>/activities/<activity_id>')
@auth_required(['traveller'])
def remove_activity_route(iid, activity_id):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    updated = removeActivity(current, activity_id)
    patch = {'activities': updated['activities'], 'updatedAt': updated['updatedAt']}
    patch['budgetEstimate'] = calculateBudget({**current, **patch})
    updateRecord('itineraries', iid, patch)
    return jsonify({'ok': True, 'activities': updated['activities'], 'budget': patch['budgetEstimate']})


@bp.put('/itineraries/<iid>/activities/<activity_id>')
@auth_required(['traveller'])
def update_activity_route(iid, activity_id):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    updated = updateActivity(current, activity_id, request.get_json(silent=True) or {})
    patch = {'activities': updated['activities'], 'updatedAt': updated['updatedAt']}
    patch['budgetEstimate'] = calculateBudget({**current, **patch})
    updateRecord('itineraries', iid, patch)
    return jsonify({'ok': True, 'activities': updated['activities'], 'budget': patch['budgetEstimate']})


@bp.post('/itineraries/<iid>/activities/rearrange')
@auth_required(['traveller'])
def rearrange_activity_route(iid):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    updated = rearrangeActivity(current, (request.get_json(silent=True) or {}).get('orderedActivityIds', []))
    updateRecord('itineraries', iid, {'activities': updated['activities'], 'updatedAt': updated['updatedAt']})
    return jsonify({'ok': True, 'activities': updated['activities']})


@bp.get('/itineraries/<iid>/budget')
@auth_required(['traveller'])
def budget_comparison(iid):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    budget = calculateBudget(current)
    budget['comparison'] = compareBudget(budget)
    updateRecord('itineraries', iid, {'budgetEstimate': budget})
    return jsonify({'ok': True, 'budget': budget})


@bp.post('/itineraries/<iid>/lower-cost-alternatives')
@auth_required(['traveller'])
def lower_cost_alternatives(iid):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    payload = request.get_json(silent=True) or {}
    flights = []
    if all(payload.get(k) for k in ['departure_id', 'arrival_id', 'outbound_date']):
        try:
            flights = retrieveLowerCostFlights(
                payload['departure_id'], payload['arrival_id'], payload['outbound_date'], payload.get('return_date')
            )
        except Exception:
            flights = []
    if not flights and _fallback_mode():
        current_price = float(current.get('flightCost', 999999) or 999999)
        flights = [dict(x) for x in FLIGHTS if float(x.get('price', 0) or 0) < current_price][:3]

    hotels = []
    if _fallback_mode():
        current_hotel = float(current.get('hotelCost', 999999) or 999999)
        hotels = [dict(x) for x in LOCAL_HOTEL_ITEMS if float(x.get('price', 0) or 0) < current_hotel][:3]

    budget = calculateBudget(current)
    alternatives = buildLowerCostAlternatives(flights, hotels, budget, current)
    return jsonify({'ok': True, 'budget': budget, 'alternatives': alternatives})


@bp.post('/itineraries/<iid>/lower-cost-alternatives/apply')
@auth_required(['traveller'])
def apply_lower_cost_alternative(iid):
    current = _own_itinerary(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    payload = request.get_json(silent=True) or {}
    alternative = payload.get('alternative') if isinstance(payload.get('alternative'), dict) else payload
    kind = str(alternative.get('alternativeType') or alternative.get('type') or '').lower()
    data = alternative.get('data') if isinstance(alternative.get('data'), dict) else {}
    savings = float(alternative.get('estimatedSavings') or alternative.get('saving') or 0)
    patch = {'updatedAt': utc_now_iso(), 'lastAppliedLowerCostAlternative': alternative}

    if kind == 'flight' and data:
        patch['selectedFlight'] = data
        patch['flightCost'] = float(data.get('price') or 0)
    elif kind == 'hotel' and data:
        patch['selectedHotel'] = data
        patch['hotelCost'] = float(data.get('price') or 0)
    elif kind in {'car', 'car_rental', 'rental'} and data:
        patch['selectedCarRental'] = data
        patch['carRentalCost'] = float(data.get('totalPrice') or data.get('price') or data.get('dailyRate') or 0)
    elif kind == 'transport':
        patch['transportCost'] = max(0.0, float(current.get('transportCost') or 35.0 * max(1, int(current.get('tripDays') or 1))) - savings)
    elif kind == 'food':
        current_food = float(current.get('foodCost') or 0)
        if current_food <= 0:
            current_food = float(calculateBudget(current).get('food') or 0)
        patch['foodCost'] = max(0.0, current_food - savings)
    elif kind in {'activity', 'activities'}:
        activities = [dict(x) for x in current.get('activities', [])]
        if activities:
            expensive = max(activities, key=lambda x: float(x.get('estimatedCost') or 0))
            expensive['estimatedCost'] = max(0.0, float(expensive.get('estimatedCost') or 0) - savings)
            expensive['budgetNote'] = 'Lower-cost alternative applied'
            patch['activities'] = activities
    elif kind == 'schedule':
        patch['transportCost'] = max(0.0, float(calculateBudget(current).get('transport') or 0) - savings)
        patch['scheduleOptimisationApplied'] = True
    else:
        return jsonify({'ok': False, 'error': 'Unsupported lower-cost alternative'}), 400

    updated_input = {**current, **patch}
    patch['budgetEstimate'] = calculateBudget(updated_input)
    patch['budgetEstimate']['comparison'] = compareBudget(patch['budgetEstimate'])
    updated = updateRecord('itineraries', iid, patch)
    return jsonify({'ok': True, 'itinerary': updated, 'budget': patch['budgetEstimate'], 'applied': alternative})


@bp.post('/itineraries/<iid>/generate')
@auth_required(['traveller'])
def generate_itinerary_route(iid):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    payload = request.get_json(silent=True) or {}

    # Destination Planning: if the traveller has not manually added activities, use the
    # ranked recommendation set, live destination search, or rich local fallback candidates.
    generation_source = 'existing-activities'
    if not current.get('activities'):
        candidates, generation_source = _destination_candidates(current)
        max_items = min(max(3, _trip_days(current) * 3), 9)
        current['activities'] = [_activity_from_destination(item, index) for index, item in enumerate(candidates[:max_items])]
    else:
        current['activities'] = [dict(x) for x in current.get('activities', [])]

    selected = [x for x in current.get('activities', []) if x.get('destinationId')]
    locations = retrieveLocationAndTravelTime(selected)
    forecast, coords = _forecast_for(current, payload)

    generated = generateItinerary(locations, forecast, current)
    generated = groupNearbyActivities(generated)
    generated = checkOpeningHoursAndTravelTime(generated)
    generated = adjustWeatherSensitiveActivities(generated)
    generated['generationContext'] = {
        **generated.get('generationContext', {}),
        'destinationSource': generation_source,
        'destinationCoordinates': coords,
    }
    generated['budgetEstimate'] = calculateBudget(generated)
    generated['budgetEstimate']['comparison'] = compareBudget(generated['budgetEstimate'])

    updateRecord('itineraries', iid, generated)
    return jsonify({'ok': True, 'itinerary': generated, 'smartFeatures': generated.get('generationContext', {})})


@bp.post('/itineraries/<iid>/save')
@auth_required(['traveller'])
def save_itinerary_route(iid):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    if not validateItineraryForSaving(current):
        return jsonify({'ok': False, 'error': 'Itinerary cannot be saved'}), 400
    return jsonify({'ok': True, 'itinerary': updateRecord('itineraries', iid, {'status': 'saved', 'updatedAt': utc_now_iso()})})


@bp.delete('/itineraries/<iid>')
@auth_required(['traveller'])
def delete_itinerary_route(iid):
    if not _own(iid):
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    deleteRecord('itineraries', iid)
    return jsonify({'ok': True})
