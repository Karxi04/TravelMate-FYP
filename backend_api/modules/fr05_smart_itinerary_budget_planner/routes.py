import hashlib
import os
import re
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
    checkOpeningHoursAndTravelTime, adjustWeatherSensitiveActivities, recalculateItinerary,
)
from services.flight_itinerary_adjustment import (
    apply_preview as apply_flight_adjustment_preview,
    create_preview as create_flight_adjustment_preview,
)

bp = Blueprint('fr05_itineraries', __name__, url_prefix='/api/fr5')


def _fallback_mode():
    return os.getenv('FALLBACK_MODE', 'false').lower() in {'1', 'true', 'yes'}


def _own(iid):
    data = retrieveRecord('itineraries', iid)
    return data if data and data.get('travellerId') == g.uid else None


def _trusted_hotel_update(current, payload):
    hotel_fields = {'selectedHotel', 'hotelCost', 'hotelCurrency', 'hotelBookingId'}
    if not hotel_fields.intersection(payload):
        return payload, None
    booking_id = str(payload.get('hotelBookingId') or current.get('hotelBookingId') or '').strip()
    booking = retrieveRecord('hotel_bookings', booking_id) if booking_id else None
    if not booking or booking.get('travellerId') != g.uid:
        return None, 'Hotel costs must come from an owned validated hotel booking.'
    if booking.get('bookingStatus') not in {'confirmed', 'paid'}:
        return None, 'Only confirmed hotel bookings can be attached to a trip.'
    if str(booking.get('hotelCurrency') or '').upper() != 'MYR' or booking.get('amountSource') != 'validated_offer':
        return None, 'Only validated MYR hotel bookings can be attached to this trip.'
    trusted = dict(payload)
    trusted.update({
        'selectedHotel': booking.get('selectedHotel') or booking.get('validatedOffer') or {},
        'hotelCost': float(booking.get('hotelCost') or 0),
        'hotelCurrency': 'MYR',
        'hotelBookingId': booking_id,
    })
    return trusted, None


def _trusted_flight_update(payload):
    flight_fields = {
        'selectedFlight', 'flightCost', 'flightCurrency', 'flightPriceBasis',
        'flightSearchId', 'flightOptionId', 'flightSelectionSource',
        'flightSelectionStatus',
    }
    if flight_fields.intersection(payload):
        return None, 'Flight selections must be attached through the flight search.'
    return payload, None


_own_itinerary = _own


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


def _normalise_location(value):
    return re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower()).strip()


def _requested_area(value):
    parts = [
        _normalise_location(part)
        for part in str(value or '').split(',')
        if _normalise_location(part)
    ]
    meaningful = [part for part in parts if part not in {'malaysia', 'my'}]
    return meaningful[0] if meaningful else (parts[0] if parts else '')


def _filter_destination_candidates(items, destination_area):
    requested = _requested_area(destination_area)
    if not requested or requested in {'malaysia', 'my'}:
        return [dict(item) for item in (items or []) if isinstance(item, dict)]

    aliases = {requested}
    trimmed = re.sub(r'\b(city|island|state|district|region)\b', ' ', requested)
    trimmed = re.sub(r'\s+', ' ', trimmed).strip()
    if trimmed:
        aliases.add(trimmed)

    relevant = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        values = [
            item.get('title'), item.get('name'), item.get('address'),
            item.get('formatted_address'), item.get('city'), item.get('state'),
            item.get('area'), item.get('neighborhood'), item.get('vicinity'),
            item.get('location'), item.get('requestedDestination'),
        ]
        location_text = _normalise_location(' '.join(str(value or '') for value in values))
        if any(alias and re.search(rf'\b{re.escape(alias)}\b', location_text) for alias in aliases):
            relevant.append(dict(item))
    return relevant


def _recommendation_snapshot(current, payload):
    requested_generation_id = str(payload.get('recommendationGenerationId') or '').strip()
    trip_generation_id = str(current.get('recommendationGenerationId') or '').strip()
    if requested_generation_id and trip_generation_id and requested_generation_id != trip_generation_id:
        return None, 'Recommendation snapshot does not match the snapshot linked to this trip'
    generation_id = trip_generation_id or requested_generation_id
    if not generation_id:
        return None, None

    snapshot = retrieveRecord('recommendation_snapshots', generation_id)
    if not snapshot or snapshot.get('travellerId') != g.uid:
        return None, 'Recommendation snapshot not found for this traveller'

    trip_area = _requested_area(current.get('destinationArea'))
    snapshot_area = _requested_area(
        snapshot.get('requestedDestination') or snapshot.get('destinationArea')
    )
    if not trip_area or trip_area != snapshot_area:
        return None, 'Recommendation snapshot destination does not match this trip'
    return snapshot, None


def _personalised_trip_id(user_id, generation_request_id):
    digest = hashlib.sha256(
        f'{user_id}:{generation_request_id}'.encode('utf-8')
    ).hexdigest()[:24]
    return f'personalised_{digest}'


def _generation_error_text(error):
    message = str(error or '').strip()
    return (message or 'Trip generation failed unexpectedly')[:500]


def _snapshot_activity_error(current, snapshot):
    if not snapshot:
        return None
    generation_id = str(snapshot.get('recommendationGenerationId') or '')
    for activity in current.get('activities', []) or []:
        activity_generation_id = str(activity.get('recommendationGenerationId') or '')
        if activity_generation_id and activity_generation_id != generation_id:
            return 'Itinerary contains recommendations from a different snapshot'
    return None


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
        **({'recommendedDurationMinutes': int(item.get('recommendedDurationMinutes') or 0)}
           if item.get('recommendedDurationMinutes') not in (None, '') else {}),
        'providerDurationMinutes': item.get('providerDurationMinutes'),
        'durationSource': item.get('durationSource') or '',
        'recommendationGenerationId': item.get('recommendationGenerationId') or '',
    }


def _destination_candidates(current, snapshot=None):
    destination = str(current.get('destinationArea') or 'Malaysia').strip()

    # 1. Use only the immutable snapshot explicitly linked to this trip.
    if snapshot:
        items = _filter_destination_candidates(
            snapshot.get('recommendationResults') or snapshot.get('items', []),
            destination,
        )
        generation_id = snapshot.get('recommendationGenerationId') or ''
        return [
            {**item, 'recommendationGenerationId': generation_id}
            for item in items
        ], snapshot.get('source', 'recommendation_snapshot')

    # 2. Try live destination information using the itinerary destination.
    if os.getenv('SERPAPI_KEY', '').strip():
        try:
            result = retrieveDestinationResults(f'top tourist attractions {destination}', destination)
            live = _filter_destination_candidates(result.get('local_results', []) or [], destination)
            if live:
                return live, 'live_provider'
        except Exception:
            pass

    # 3. Interactive deterministic fallback.
    if _fallback_mode():
        fallback = _filter_destination_candidates(DESTINATIONS, destination)
        if fallback:
            return fallback, 'fallback'
    return [], 'none'


def _generate_itinerary_data(current, payload, snapshot=None):
    if snapshot:
        generation_id = str(snapshot.get('recommendationGenerationId') or '')
        for activity in current.get('activities', []) or []:
            activity_generation_id = str(activity.get('recommendationGenerationId') or '')
            if activity_generation_id and activity_generation_id != generation_id:
                raise ValueError('Itinerary contains recommendations from a different snapshot')

    generation_source = snapshot.get('source', 'recommendation_snapshot') if snapshot else 'existing-activities'
    working = {**current}
    if not working.get('activities'):
        candidates, generation_source = _destination_candidates(working, snapshot)
        if not candidates:
            if snapshot:
                raise RuntimeError('Linked recommendation snapshot has no destination-relevant results')
            raise RuntimeError('No destination candidates are available for this trip')
        # Let the constraint-aware planner decide actual capacity. The existing
        # safety limit remains 20, with overflow retained as suggestions.
        max_items = min(len(candidates), 20)
        working['activities'] = [
            _activity_from_destination(item, index)
            for index, item in enumerate(candidates[:max_items])
        ]
    else:
        working['activities'] = [dict(x) for x in working.get('activities', [])]

    selected = [x for x in working.get('activities', []) if x.get('destinationId')]
    locations = retrieveLocationAndTravelTime(selected)
    forecast, coords = _forecast_for(working, payload)

    generated = generateItinerary(locations, forecast, working)
    generated['generationContext'] = {
        **generated.get('generationContext', {}),
        'destinationSource': generation_source,
        'destinationCoordinates': coords,
        'recommendationGenerationId': (
            snapshot.get('recommendationGenerationId') if snapshot else None
        ),
    }
    return generated


def _transition_to_generating(iid, current):
    now = utc_now_iso()
    patch = {
        'status': 'generating',
        'generationStartedAt': now,
        'updatedAt': now,
        'generationAttempts': int(current.get('generationAttempts') or 0) + 1,
        'lastGenerationError': None,
        'generationFailedAt': None,
        'retryable': False,
    }
    updated = updateRecord('itineraries', iid, patch)
    return updated or {**current, **patch, 'id': iid}


def _run_generation_state_machine(iid, current, payload, snapshot):
    stage = 'itinerary_generation'
    partial = None
    try:
        partial = _generate_itinerary_data(current, payload, snapshot)
        stage = 'budget_calculation'
        budget = calculateBudget(partial)
        budget['comparison'] = compareBudget(budget)

        stage = 'save_generated_trip'
        now = utc_now_iso()
        planned = {
            **partial,
            'budgetEstimate': budget,
            'status': 'planned',
            'plannedAt': now,
            'updatedAt': now,
            'lastGenerationError': None,
            'generationFailedAt': None,
            'retryable': False,
        }
        persisted = updateRecord('itineraries', iid, planned)
        if persisted is None:
            raise RuntimeError('Generated trip could not be saved')
        return persisted, None, None
    except Exception as error:
        message = _generation_error_text(error)
        now = utc_now_iso()
        failure = {
            **(partial or {}),
            'status': 'generation_failed',
            'generationFailureStage': stage,
            'lastGenerationError': message,
            'generationFailedAt': now,
            'updatedAt': now,
            'retryable': True,
        }
        persisted = updateRecord('itineraries', iid, failure)
        return persisted or {**current, **failure, 'id': iid}, message, stage


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
    if not validateItineraryInput(payload) or not str(payload.get('destinationArea') or '').strip():
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
    payload, hotel_error = _trusted_hotel_update(current, payload)
    if hotel_error:
        return jsonify({'ok': False, 'error': hotel_error}), 409
    payload, flight_error = _trusted_flight_update(payload)
    if flight_error:
        return jsonify({'ok': False, 'error': flight_error}), 409
    if not validateItineraryInput({**current, **payload}):
        return jsonify({'ok': False, 'error': 'Use a title, valid date range, positive traveller count and non-negative budget'}), 400
    payload['updatedAt'] = utc_now_iso()
    merged = {**current, **payload}
    payload['budgetEstimate'] = calculateBudget(merged)
    return jsonify({'ok': True, 'itinerary': updateRecord('itineraries', iid, payload)})


def _public_flight_preview(preview):
    result = dict(preview or {})
    for key in ('owner', 'tripFingerprint', 'flightFingerprint'):
        result.pop(key, None)
    return result


@bp.post('/itineraries/<iid>/flight-adjustment/preview')
@auth_required(['traveller'])
def flight_adjustment_preview(iid):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    flight = current.get('selectedFlight') if isinstance(current.get('selectedFlight'), dict) else None
    if not flight:
        return jsonify({'ok': False, 'error': 'Select a flight before requesting an itinerary adjustment preview.'}), 409
    preview = create_flight_adjustment_preview(current, flight, g.uid)
    return jsonify({'ok': True, 'preview': _public_flight_preview(preview)})


@bp.post('/itineraries/<iid>/flight-adjustment/apply')
@auth_required(['traveller'])
def flight_adjustment_apply(iid):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    payload = request.get_json(silent=True) or {}
    preview_id = str(payload.get('previewId') or '').strip()
    if not preview_id:
        return jsonify({'ok': False, 'error': 'previewId is required'}), 400
    flight = current.get('selectedFlight') if isinstance(current.get('selectedFlight'), dict) else {}
    result, error = apply_flight_adjustment_preview(
        preview_id, current, flight, g.uid,
        lambda _iid, patch: updateRecord('itineraries', _iid, patch),
    )
    if error:
        return jsonify({'ok': False, 'error': error}), 409 if 'stale' in error.lower() else 404
    return jsonify(result)


@bp.post('/itineraries/<iid>/hotel-selection/remove')
@auth_required(['traveller'])
def remove_hotel_selection(iid):
    """Remove the trip association while retaining the hotel booking history."""
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    patch = {
        'selectedHotel': None,
        'hotelCost': 0,
        'hotelCurrency': None,
        'hotelBookingId': None,
        'hotelSelectionStatus': 'removed',
        'hotelSelectionRemovedAt': utc_now_iso(),
        'updatedAt': utc_now_iso(),
    }
    merged = {**current, **patch}
    patch['budgetEstimate'] = calculateBudget(merged)
    return jsonify({'ok': True, 'itinerary': updateRecord('itineraries', iid, patch)})


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
        **({'recommendedDurationMinutes': int(payload.get('recommendedDurationMinutes') or 0)}
           if payload.get('recommendedDurationMinutes') not in (None, '') else {}),
        'providerDurationMinutes': payload.get('providerDurationMinutes'),
        'durationSource': payload.get('durationSource') or '',
    }
    updated = addActivity(current, activity)
    recalculated = recalculateItinerary(
        {**current, 'activities': updated['activities']},
        preserveOrder=True,
        respectDayAssignments=True,
    )
    patch = {
        key: recalculated[key]
        for key in ('activities', 'unscheduledSuggestions', 'scheduledActivityCount',
                    'unscheduledActivityCount', 'dailySchedule', 'totalScheduledMinutes',
                    'paceApplied', 'dailyPlanningWindow', 'tripDays',
                    'tripDateRangeLabel', 'updatedAt')
        if key in recalculated
    }
    patch['budgetEstimate'] = calculateBudget({**current, **patch})
    updateRecord('itineraries', iid, patch)
    return jsonify({'ok': True, 'itinerary': {**current, **patch}, 'activities': patch['activities'], 'budget': patch['budgetEstimate']})


@bp.delete('/itineraries/<iid>/activities/<activity_id>')
@auth_required(['traveller'])
def remove_activity_route(iid, activity_id):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    updated = removeActivity(current, activity_id)
    recalculated = recalculateItinerary(
        {**current, 'activities': updated['activities']},
        preserveOrder=True,
        respectDayAssignments=True,
    )
    patch = {key: recalculated[key] for key in (
        'activities', 'unscheduledSuggestions', 'scheduledActivityCount',
        'unscheduledActivityCount', 'dailySchedule', 'totalScheduledMinutes',
        'paceApplied', 'dailyPlanningWindow', 'tripDays',
        'tripDateRangeLabel', 'updatedAt') if key in recalculated}
    patch['budgetEstimate'] = calculateBudget({**current, **patch})
    updateRecord('itineraries', iid, patch)
    return jsonify({'ok': True, 'itinerary': {**current, **patch}, 'activities': patch['activities'], 'budget': patch['budgetEstimate']})


@bp.put('/itineraries/<iid>/activities/<activity_id>')
@auth_required(['traveller'])
def update_activity_route(iid, activity_id):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    updated = updateActivity(current, activity_id, request.get_json(silent=True) or {})
    recalculated = recalculateItinerary(
        {**current, 'activities': updated['activities']},
        preserveOrder=True,
        respectDayAssignments=True,
    )
    patch = {key: recalculated[key] for key in (
        'activities', 'unscheduledSuggestions', 'scheduledActivityCount',
        'unscheduledActivityCount', 'dailySchedule', 'totalScheduledMinutes',
        'paceApplied', 'dailyPlanningWindow', 'tripDays',
        'tripDateRangeLabel', 'updatedAt') if key in recalculated}
    patch['budgetEstimate'] = calculateBudget({**current, **patch})
    updateRecord('itineraries', iid, patch)
    return jsonify({'ok': True, 'itinerary': {**current, **patch}, 'activities': patch['activities'], 'budget': patch['budgetEstimate']})


@bp.post('/itineraries/<iid>/activities/rearrange')
@auth_required(['traveller'])
def rearrange_activity_route(iid):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    updated = rearrangeActivity(current, (request.get_json(silent=True) or {}).get('orderedActivityIds', []))
    recalculated = recalculateItinerary(
        {**current, 'activities': updated['activities']},
        preserveOrder=True,
        respectDayAssignments=True,
    )
    patch = {key: recalculated[key] for key in (
        'activities', 'unscheduledSuggestions', 'scheduledActivityCount',
        'unscheduledActivityCount', 'dailySchedule', 'totalScheduledMinutes',
        'paceApplied', 'dailyPlanningWindow', 'tripDays',
        'tripDateRangeLabel', 'updatedAt') if key in recalculated}
    patch['budgetEstimate'] = calculateBudget({**current, **patch})
    updateRecord('itineraries', iid, patch)
    return jsonify({'ok': True, 'itinerary': {**current, **patch}, 'activities': patch['activities'], 'budget': patch['budgetEstimate']})


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
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    payload = request.get_json(silent=True) or {}
    alternative = payload.get('alternative') if isinstance(payload.get('alternative'), dict) else payload
    kind = str(alternative.get('alternativeType') or alternative.get('type') or '').lower()
    data = alternative.get('data') if isinstance(alternative.get('data'), dict) else {}
    savings = float(alternative.get('estimatedSavings') or alternative.get('saving') or 0)
    patch = {'updatedAt': utc_now_iso(), 'lastAppliedLowerCostAlternative': alternative}

    if kind == 'flight' and data:
        if not os.getenv('TRAVELMATE_TESTING', '').lower() in {'1', 'true', 'yes'}:
            return jsonify({'ok': False, 'error': 'Choose a flight from a completed flight search.'}), 409
        patch['selectedFlight'] = data
        patch['flightCost'] = float(data.get('price') or 0)
        patch['flightCurrency'] = str(data.get('currency') or 'MYR').upper()
        patch['flightPriceBasis'] = data.get('priceBasis') or 'legacy_test_fixture'
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


@bp.post('/personalised-trips/generate')
@auth_required(['traveller'])
def generate_personalised_trip_route():
    payload = request.get_json(silent=True) or {}
    generation_request_id = str(payload.get('generationRequestId') or '').strip()
    recommendation_generation_id = str(payload.get('recommendationGenerationId') or '').strip()

    if not validateItineraryInput(payload) or not str(payload.get('destinationArea') or '').strip():
        return jsonify({
            'ok': False,
            'error': 'Use a title, destination, valid date range, positive traveller count and non-negative budget',
            'stage': 'input_validation',
            'retryable': False,
        }), 400
    if not recommendation_generation_id:
        return jsonify({
            'ok': False,
            'error': 'A recommendation generation ID is required for a personalised trip',
            'stage': 'snapshot_validation',
            'retryable': False,
        }), 400
    if len(generation_request_id) < 8 or len(generation_request_id) > 128:
        return jsonify({
            'ok': False,
            'error': 'A valid generation request ID is required',
            'stage': 'input_validation',
            'retryable': False,
        }), 400

    iid = _personalised_trip_id(g.uid, generation_request_id)
    existing = retrieveRecord('itineraries', iid)
    if existing and existing.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'Trip generation request conflict'}), 409
    if existing and _requested_area(existing.get('destinationArea')) != _requested_area(payload.get('destinationArea')):
        return jsonify({
            'ok': False,
            'error': 'Generation request is already linked to a different destination',
            'tripId': iid,
        }), 409

    candidate = existing or {
        **payload,
        'travellerId': g.uid,
        'recommendationGenerationId': recommendation_generation_id,
        'activities': [],
    }
    snapshot, snapshot_error = _recommendation_snapshot(candidate, payload)
    if snapshot_error:
        return jsonify({
            'ok': False,
            'error': snapshot_error,
            'tripId': iid if existing else None,
            'stage': 'snapshot_validation',
            'retryable': False,
        }), 409
    activity_error = _snapshot_activity_error(candidate, snapshot)
    if activity_error:
        return jsonify({
            'ok': False,
            'error': activity_error,
            'tripId': iid if existing else None,
            'stage': 'snapshot_validation',
            'retryable': False,
        }), 409

    if existing and existing.get('status') == 'planned':
        return jsonify({
            'ok': True,
            'id': iid,
            'tripId': iid,
            'status': 'planned',
            'itinerary': existing,
            'reused': True,
        })
    if existing and existing.get('status') == 'generating':
        return jsonify({
            'ok': True,
            'id': iid,
            'tripId': iid,
            'status': 'generating',
            'itinerary': existing,
            'inProgress': True,
            'reused': True,
        }), 202

    if existing:
        current = _transition_to_generating(iid, existing)
    else:
        now = utc_now_iso()
        initial = createItinerary({
            **payload,
            'activities': [],
            'status': 'generating',
            'planningFlow': 'personalised',
            'generationRequestId': generation_request_id,
            'recommendationGenerationId': recommendation_generation_id,
            'generationStartedAt': now,
            'generationAttempts': 1,
            'retryable': False,
        }, g.uid)
        try:
            current = storeRecord('itineraries', initial, iid)
        except Exception as error:
            return jsonify({
                'ok': False,
                'error': _generation_error_text(error),
                'stage': 'trip_creation',
                'status': 'not_created',
                'retryable': True,
            }), 500

    planned, error, stage = _run_generation_state_machine(
        iid,
        current,
        {
            **payload,
            'recommendationGenerationId': recommendation_generation_id,
        },
        snapshot,
    )
    if error:
        return jsonify({
            'ok': False,
            'error': error,
            'id': iid,
            'tripId': iid,
            'status': 'generation_failed',
            'stage': stage,
            'retryable': True,
            'itinerary': planned,
        }), 500

    return jsonify({
        'ok': True,
        'id': iid,
        'tripId': iid,
        'status': 'planned',
        'itinerary': planned,
        'reused': bool(existing),
    })


@bp.post('/itineraries/<iid>/generate')
@auth_required(['traveller'])
def generate_itinerary_route(iid):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    payload = request.get_json(silent=True) or {}
    snapshot, snapshot_error = _recommendation_snapshot(current, payload)
    if snapshot_error:
        return jsonify({'ok': False, 'error': snapshot_error}), 409
    activity_error = _snapshot_activity_error(current, snapshot)
    if activity_error:
        return jsonify({'ok': False, 'error': activity_error}), 409
    generating = _transition_to_generating(iid, current)
    planned, error, stage = _run_generation_state_machine(
        iid, generating, payload, snapshot
    )
    if error:
        return jsonify({
            'ok': False,
            'error': error,
            'id': iid,
            'tripId': iid,
            'status': 'generation_failed',
            'stage': stage,
            'retryable': True,
            'itinerary': planned,
        }), 500
    return jsonify({
        'ok': True,
        'id': iid,
        'tripId': iid,
        'status': 'planned',
        'itinerary': planned,
        'smartFeatures': planned.get('generationContext', {}),
    })


@bp.post('/itineraries/<iid>/save')
@auth_required(['traveller'])
def save_itinerary_route(iid):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    if not validateItineraryForSaving(current):
        return jsonify({'ok': False, 'error': 'Itinerary cannot be saved'}), 400
    return jsonify({'ok': True, 'itinerary': updateRecord('itineraries', iid, {'status': 'planned', 'plannedAt': utc_now_iso(), 'updatedAt': utc_now_iso()})})


@bp.delete('/itineraries/<iid>')
@auth_required(['traveller'])
def delete_itinerary_route(iid):
    if not _own(iid):
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    deleteRecord('itineraries', iid)
    return jsonify({'ok': True})
