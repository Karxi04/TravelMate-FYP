import hashlib
import os
import re
import json
from datetime import date
from flask import Blueprint, request, jsonify, g
from auth_utils import auth_required
from utils import utc_now_iso
from services.activity_pricing import (
    activity_pricing, pricing_snapshot, refresh_activity_costs, traveller_count,
)
from services.serpapi_service import retrieveLocationAndTravelTime, retrieveDestinationResults
from services.recommendation_discovery import is_planning_candidate
from services.open_meteo_service import retrieveSevenDayForecast, geocode
from services.local_catalog import DESTINATIONS
from services.pricing_registry import enrich_candidate_pricing
from services.budget_aware_generation import generate_with_budget_selection, qualify_selection_budget
from services.itinerary_write_contract import validate_trip_write
from sequence_contract.validators import validateItineraryInput, validateItineraryForSaving, validateSelectedDestination
from sequence_contract.firebase_firestore import retrieveRecord, storeRecord, updateRecord, deleteRecord
from sequence_contract.domain_functions import (
    createItinerary, addActivity, removeActivity, rearrangeActivity, updateActivity,
    checkDestinationExists, checkDestinationLimit, calculateBudget, compareBudget,
    generateItinerary, groupNearbyActivities,
    checkOpeningHoursAndTravelTime, adjustWeatherSensitiveActivities, recalculateItinerary,
    _alternative_savings, _activity_duration, _activity_opening, _distance_km,
    _format_time, _parse_time_minutes, _travel_leg,
)
from services.flight_itinerary_adjustment import (
    apply_preview as apply_flight_adjustment_preview,
    create_preview as create_flight_adjustment_preview,
)

bp = Blueprint('fr05_itineraries', __name__, url_prefix='/api/fr5')


def _fallback_mode():
    return os.getenv('FALLBACK_MODE', 'false').lower() in {'1', 'true', 'yes'}


def _budget_selection_enabled():
    return os.getenv('TRAVELMATE_BUDGET_AWARE_SELECTION_ENABLED', 'false').strip().lower() in {'1', 'true', 'yes', 'on'}


def _own(iid):
    data = retrieveRecord('itineraries', iid)
    return data if data and data.get('travellerId') == g.uid else None


def _is_package_trip(trip):
    if not trip or not isinstance(trip, dict):
        return False
    return trip.get('tripType') == 'package' or bool(trip.get('packageTrip'))


def _trusted_hotel_update(current, payload, booking=None):
    hotel_fields = {'selectedHotel', 'hotelCost', 'hotelCurrency', 'hotelBookingId'}
    if not hotel_fields.intersection(payload):
        return payload, None
    booking_id = str(payload.get('hotelBookingId') or current.get('hotelBookingId') or '').strip()
    booking = booking if booking is not None else (retrieveRecord('hotel_bookings', booking_id) if booking_id else None)
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
        'accommodationChoice': 'paid_hotel',
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


def _trip_date_conflicts(current, proposed):
    """Return only definite conflicts; incomplete historical records remain editable."""
    from datetime import date
    try:
        start = date.fromisoformat(str(proposed['startDate'])[:10])
        end = date.fromisoformat(str(proposed['endDate'])[:10])
    except (KeyError, TypeError, ValueError):
        return []
    conflicts = []
    booking_id = str(current.get('hotelBookingId') or '').strip()
    if booking_id:
        booking = retrieveRecord('hotel_bookings', booking_id) or {}
        criteria = booking.get('stayCriteria') if isinstance(booking.get('stayCriteria'), dict) else {}
        try:
            checkin = date.fromisoformat(str(criteria['checkin'])[:10])
            checkout = date.fromisoformat(str(criteria['checkout'])[:10])
            if not (start <= checkin < checkout <= end):
                conflicts.append({'type': 'hotel_dates', 'message': 'Attached hotel dates would no longer fit this trip.'})
        except (KeyError, TypeError, ValueError):
            pass
    flight = current.get('selectedFlight') if isinstance(current.get('selectedFlight'), dict) else {}
    for segment in list(flight.get('outboundSegments') or []) + list(flight.get('returnSegments') or []):
        if not isinstance(segment, dict):
            continue
        for field in ('departureDate', 'arrivalDate'):
            value = str(segment.get(field) or '')[:10]
            if not value:
                continue
            try:
                if not (start <= date.fromisoformat(value) <= end):
                    conflicts.append({'type': 'flight_dates', 'message': 'Attached flight dates would no longer fit this trip.'})
                    break
            except ValueError:
                continue
    for association in current.get('purchasedPackages') or []:
        snapshot = association.get('packageSnapshot') if isinstance(association, dict) else {}
        days = snapshot.get('itineraryDays') if isinstance(snapshot, dict) else []
        required_days = max((int(day.get('dayNumber') or 0) for day in days if isinstance(day, dict)), default=0)
        if required_days and (end - start).days + 1 < required_days:
            conflicts.append({'type': 'package_duration', 'message': 'Attached package itinerary days would no longer fit this trip.'})
    return conflicts


def _synchronise_daily_schedule(current, proposed):
    """Re-date preserved day records without discarding itinerary content."""
    from datetime import date, timedelta
    try:
        start = date.fromisoformat(str(proposed['startDate'])[:10])
        days = _trip_days(proposed)
    except (KeyError, TypeError, ValueError):
        return None, []

    conflicts = []
    for activity in current.get('activities') or []:
        try:
            activity_day = int(activity.get('dayNo') or 0) if isinstance(activity, dict) else 0
        except (TypeError, ValueError):
            activity_day = 0
        if activity_day > days:
            conflicts.append({
                'type': 'itinerary_schedule',
                'message': 'Trip dates would remove scheduled itinerary activities.',
            })
            break

    stored = current.get('dailySchedule')
    if not isinstance(stored, list):
        return None, conflicts

    by_day = {}
    for raw_day in stored:
        if not isinstance(raw_day, dict):
            continue
        try:
            day_no = int(raw_day.get('dayNo') or 0)
        except (TypeError, ValueError):
            continue
        if day_no < 1:
            continue
        if day_no > days:
            if raw_day.get('activities') or raw_day.get('planningBlocks'):
                conflicts.append({
                    'type': 'itinerary_schedule',
                    'message': 'Trip dates would remove scheduled itinerary activities.',
                })
            continue
        by_day[day_no] = dict(raw_day)

    if conflicts:
        return None, conflicts

    schedule = []
    for day_no in range(1, days + 1):
        day = by_day.get(day_no, {'dayNo': day_no, 'activities': []})
        day['dayNo'] = day_no
        day['dayDate'] = (start + timedelta(days=day_no - 1)).isoformat()
        schedule.append(day)
    return schedule, []


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
    items = [item for item in (items or []) if isinstance(item, dict) and is_planning_candidate(item)]
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


_PLACE_IMAGE_FIELDS = (
    'thumbnail', 'image', 'imageUrl', 'mainPhoto', 'main_photo', 'photo',
    'photos', 'images', 'heroImage', 'galleryImages',
)


def _safe_image_value(value):
    if isinstance(value, str):
        value = value.strip()
        return value if value.startswith(('https://', 'http://')) else None
    if isinstance(value, list):
        values = [_safe_image_value(item) for item in value[:8]]
        return [item for item in values if item not in (None, [], {})]
    if isinstance(value, dict):
        allowed = ('thumbnail', 'image', 'link', 'url', 'source')
        result = {key: _safe_image_value(value.get(key)) for key in allowed if key in value}
        return {key: item for key, item in result.items() if item not in (None, [], {})}
    return None


def _place_image_snapshot(item):
    snapshot = {}
    for field in _PLACE_IMAGE_FIELDS:
        value = _safe_image_value(item.get(field))
        if value not in (None, [], {}):
            snapshot[field] = value
    return snapshot


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
        **pricing_snapshot(item),
        'gps_coordinates': gps,
        'type': item.get('type') or item.get('category') or '',
        'category': item.get('category') or item.get('type') or '',
        'description': item.get('description') or '',
        'openingHours': item.get('openingHours') or item.get('hours') or '',
        **{key: item[key] for key in (
            'operating_hours', 'opening_hours', 'hours', 'openingHoursSource',
            'openingHoursUpdatedAt', 'openingHoursFetchedAt', 'openingHoursStale',
            'permanently_closed', 'business_status',
        ) if key in item},
        'indoor': bool(item.get('indoor', False)),
        **({'recommendedDurationMinutes': int(item.get('recommendedDurationMinutes') or 0)}
           if item.get('recommendedDurationMinutes') not in (None, '') else {}),
        'providerDurationMinutes': item.get('providerDurationMinutes'),
        'durationSource': item.get('durationSource') or '',
        'recommendationGenerationId': item.get('recommendationGenerationId') or '',
        **_place_image_snapshot(item),
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
                return [enrich_candidate_pricing(item) for item in live], 'live_provider'
        except Exception:
            pass

    # 3. Interactive deterministic fallback.
    if _fallback_mode():
        fallback = _filter_destination_candidates(DESTINATIONS, destination)
        if fallback:
            return [enrich_candidate_pricing(item) for item in fallback], 'fallback'
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
    selection_enabled = _budget_selection_enabled()
    apply_selection = False
    selection_skip_reason = 'existing_activities_preserved'
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
        if selection_enabled:
            # Only the linked server-owned FR04 snapshot supplies personality scores.
            apply_selection = bool(snapshot) and all(
                item.get('score', item.get('finalScore')) is not None for item in candidates[:max_items])
            selection_skip_reason = 'linked_recommendation_scores_required'
            if apply_selection:
                working['activities'] = [
                    {**_activity_from_destination(enrich_candidate_pricing(item), index),
                     **{key: item[key] for key in (
                         'score', 'finalScore', 'contentScore', 'collaborativeScore', 'popularityScore',
                         'currency', 'providerTravelDurationMinutes', 'travelTimeSource',
                     ) if key in item}}
                    for index, item in enumerate(candidates[:max_items])
                ]
    else:
        working['activities'] = [dict(x) for x in working.get('activities', [])]

    selected = [x for x in working.get('activities', []) if x.get('destinationId')]
    locations = retrieveLocationAndTravelTime(selected)
    forecast, coords = _forecast_for(working, payload)

    if apply_selection:
        generated = generate_with_budget_selection(working, forecast, locations)
    else:
        generated = generateItinerary(locations, forecast, working)
        if selection_enabled:
            generated['budgetAwareSelection'] = {'enabled': True, 'applied': False, 'reason': selection_skip_reason}
        elif 'budgetAwareSelection' in working:
            # An explicit regeneration must not claim the previous run's selection.
            generated['budgetAwareSelection'] = {'enabled': False, 'applied': False, 'reason': 'feature_disabled'}
    generated['generationContext'] = {
        **generated.get('generationContext', {}),
        'destinationSource': generation_source,
        'destinationCoordinates': coords,
        'recommendationGenerationId': (
            snapshot.get('recommendationGenerationId') if snapshot else None
        ),
        **({'budgetAwareSelectionApplied': apply_selection} if selection_enabled else {}),
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
        if partial.get('generationContext', {}).get('budgetAwareSelectionApplied') is True:
            budget = qualify_selection_budget(budget, partial['budgetAwareSelection'])
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


@bp.get('/itineraries/<iid>')
@auth_required(['traveller'])
def get_itinerary_route(iid):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    if _is_package_trip(current) and current.get('checkoutOrderId'):
        from services.booking_requirements import read_public_clarification
        try:
            order=retrieveRecord('checkout_orders',current['checkoutOrderId'])
        except Exception:
            order=None
        if order and order.get('travellerId')==g.uid and order.get('fulfilledTripId')==iid:
            summary=read_public_clarification(order,retrieveRecord)
            if summary:current={**current,'approvedRequirementClarification':summary}
    return jsonify({'ok': True, 'itinerary': current})


@bp.post('/itineraries')
@auth_required(['traveller'])
def create_itinerary_route():
    try:
        payload = validate_trip_write(request.get_json(silent=True))
    except ValueError as error:
        return jsonify({'ok': False, 'error': str(error)}), 400
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
    if _is_package_trip(current):
        return jsonify({'ok': False, 'error': 'Purchased package trips cannot be modified or recalculated.'}), 409
    try:
        payload = validate_trip_write(request.get_json(silent=True), update=True)
    except ValueError as error:
        return jsonify({'ok': False, 'error': str(error)}), 400
    payload, hotel_error = _trusted_hotel_update(current, payload)
    if hotel_error:
        return jsonify({'ok': False, 'error': hotel_error}), 409
    payload, flight_error = _trusted_flight_update(payload)
    if flight_error:
        return jsonify({'ok': False, 'error': flight_error}), 409
    if not validateItineraryInput({**current, **payload}):
        return jsonify({'ok': False, 'error': 'Use a title, valid date range, positive traveller count and non-negative budget'}), 400
    if 'startDate' in payload or 'endDate' in payload:
        conflicts = _trip_date_conflicts(current, {**current, **payload})
        daily_schedule, schedule_conflicts = _synchronise_daily_schedule(
            current, {**current, **payload}
        )
        conflicts.extend(schedule_conflicts)
        if conflicts:
            return jsonify({'ok': False, 'error': 'Trip dates conflict with saved travel or itinerary activities.', 'conflicts': conflicts}), 409
        payload['tripDays'] = _trip_days({**current, **payload})
        if daily_schedule is not None:
            payload['dailySchedule'] = daily_schedule
    payload['updatedAt'] = utc_now_iso()
    merged = {**current, **payload}
    if 'travellerCount' in payload:
        payload.update(refresh_activity_costs(merged))
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
    if _is_package_trip(current):
        return jsonify({'ok': False, 'error': 'Purchased package trips cannot be modified or recalculated.'}), 409
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
    if _is_package_trip(current):
        return jsonify({'ok': False, 'error': 'Purchased package trips cannot be modified or recalculated.'}), 409
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
    if _is_package_trip(current):
        return jsonify({'ok': False, 'error': 'Purchased package trips cannot be modified or recalculated.'}), 409
    patch = {
        'selectedHotel': None,
        'hotelCost': 0,
        'hotelCurrency': None,
        'hotelBookingId': None,
        'accommodationChoice': 'undecided',
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
    if _is_package_trip(current):
        return jsonify({'ok': False, 'error': 'Purchased package trips cannot be modified or recalculated.'}), 409
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
        **pricing_snapshot(payload),
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
        **_place_image_snapshot(payload),
    }
    updated = addActivity(current, activity)
    recalculated = recalculateItinerary(
        {**current, **updated},
        preserveOrder=True,
        respectDayAssignments=True,
    )
    patch = {
        key: recalculated[key]
        for key in ('activities', 'unscheduledSuggestions', 'scheduledActivityCount',
                    'unscheduledActivityCount', 'dailySchedule', 'totalScheduledMinutes',
                    'paceApplied', 'dailyPlanningWindow', 'tripDays',
                    'tripDateRangeLabel', 'updatedAt', 'nextActivitySeq')
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
    if _is_package_trip(current):
        return jsonify({'ok': False, 'error': 'Purchased package trips cannot be modified or recalculated.'}), 409
    updated = removeActivity(current, activity_id)
    recalculated = recalculateItinerary(
        {**current, **updated},
        preserveOrder=True,
        respectDayAssignments=True,
    )
    patch = {key: recalculated[key] for key in (
        'activities', 'unscheduledSuggestions', 'scheduledActivityCount',
        'unscheduledActivityCount', 'dailySchedule', 'totalScheduledMinutes',
        'paceApplied', 'dailyPlanningWindow', 'tripDays',
        'tripDateRangeLabel', 'updatedAt', 'nextActivitySeq') if key in recalculated}
    patch['budgetEstimate'] = calculateBudget({**current, **patch})
    updateRecord('itineraries', iid, patch)
    return jsonify({'ok': True, 'itinerary': {**current, **patch}, 'activities': patch['activities'], 'budget': patch['budgetEstimate']})


@bp.put('/itineraries/<iid>/activities/<activity_id>')
@auth_required(['traveller'])
def update_activity_route(iid, activity_id):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    if _is_package_trip(current):
        return jsonify({'ok': False, 'error': 'Purchased package trips cannot be modified or recalculated.'}), 409
    updated = updateActivity(current, activity_id, request.get_json(silent=True) or {})
    recalculated = recalculateItinerary(
        {**current, **updated},
        preserveOrder=True,
        respectDayAssignments=True,
    )
    patch = {key: recalculated[key] for key in (
        'activities', 'unscheduledSuggestions', 'scheduledActivityCount',
        'unscheduledActivityCount', 'dailySchedule', 'totalScheduledMinutes',
        'paceApplied', 'dailyPlanningWindow', 'tripDays',
        'tripDateRangeLabel', 'updatedAt', 'nextActivitySeq') if key in recalculated}
    patch['budgetEstimate'] = calculateBudget({**current, **patch})
    updateRecord('itineraries', iid, patch)
    return jsonify({'ok': True, 'itinerary': {**current, **patch}, 'activities': patch['activities'], 'budget': patch['budgetEstimate']})


@bp.post('/itineraries/<iid>/activities/rearrange')
@auth_required(['traveller'])
def rearrange_activity_route(iid):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    if _is_package_trip(current):
        return jsonify({'ok': False, 'error': 'Purchased package trips cannot be modified or recalculated.'}), 409
    updated = rearrangeActivity(current, (request.get_json(silent=True) or {}).get('orderedActivityIds', []))
    recalculated = recalculateItinerary(
        {**current, **updated},
        preserveOrder=True,
        respectDayAssignments=True,
    )
    patch = {key: recalculated[key] for key in (
        'activities', 'unscheduledSuggestions', 'scheduledActivityCount',
        'unscheduledActivityCount', 'dailySchedule', 'totalScheduledMinutes',
        'paceApplied', 'dailyPlanningWindow', 'tripDays',
        'tripDateRangeLabel', 'updatedAt', 'nextActivitySeq') if key in recalculated}
    patch['budgetEstimate'] = calculateBudget({**current, **patch})
    updateRecord('itineraries', iid, patch)
    return jsonify({'ok': True, 'itinerary': {**current, **patch}, 'activities': patch['activities'], 'budget': patch['budgetEstimate']})


@bp.get('/itineraries/<iid>/budget')
@auth_required(['traveller'])
def budget_comparison(iid):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    if _is_package_trip(current):
        budget = current.get('budgetEstimate') or {
            'total': current.get('paidTotal', 0),
            'currency': current.get('currency', 'MYR'),
            'source': 'verified_package_payment',
        }
        return jsonify({'ok': True, 'budget': budget})
    budget = calculateBudget(current)
    selection = current.get('budgetAwareSelection') or {}
    if selection.get('applied') is True and (
        {item.get('activityId') for item in current.get('activities', [])}
        == {item.get('activityId') for item in selection.get('selectionRationale', [])}
    ):
        budget = qualify_selection_budget(budget, selection)
    budget['comparison'] = compareBudget(budget)
    updateRecord('itineraries', iid, {'budgetEstimate': budget})
    return jsonify({'ok': True, 'budget': budget})


class _AlternativeConflict(ValueError):
    pass


def _alternative_state(current):
    return hashlib.sha256(json.dumps(current, sort_keys=True, default=str).encode()).hexdigest()


def _commit_cost_alternative(iid, expected, patch):
    from google.api_core.exceptions import FailedPrecondition, NotFound
    from sequence_contract.firebase_firestore import get_db
    db = get_db()
    ref = db.collection('itineraries').document(iid)
    snapshot = ref.get()
    current = {'id': snapshot.id, **(snapshot.to_dict() or {})}
    stale = 'This itinerary changed during verification. Reload alternatives.'
    if (not snapshot.exists or current.get('travellerId') != g.uid
            or _alternative_state(current) != _alternative_state(expected)):
        raise _AlternativeConflict(stale)
    try:
        ref.update(patch, option=db.write_option(last_update_time=snapshot.update_time))
    except (FailedPrecondition, NotFound) as error:
        raise _AlternativeConflict(stale) from error
    return {**current, **patch}


def _activity_identity(row):
    from services.review_destination import review_destination_id
    return review_destination_id(str(row.get('destinationId') or row.get('place_id') or row.get('id') or ''))


def _activity_options(current):
    raw = list(DESTINATIONS)
    if current.get('recommendationGenerationId'):
        snapshot, _ = _recommendation_snapshot(current, {})
    else:
        snapshot = None
    if snapshot:
        raw.extend(snapshot.get('recommendationResults') or snapshot.get('items') or [])
    candidates = {}
    for row in _filter_destination_candidates(raw, current.get('destinationArea')):
        enriched = enrich_candidate_pricing(row)
        evidence = enriched.get('pricingEvidence')
        if isinstance(evidence, dict) and evidence.get('applicability') == 'applicable':
            candidates.setdefault(_activity_identity(enriched), enriched)
    return candidates


def _resolve_activity_alternative(current, data, candidates):
    from services.malaysian_locality import filter_candidates, normalize_destination_scope

    activities = current.get('activities') or []
    requested = data.get('activityId')
    original = next((row for row in activities if row.get('activityId') == requested), None)
    candidate = candidates.get(str(data.get('destinationId') or ''))
    if not original or not candidate or any(
            _activity_identity(row) == _activity_identity(candidate) for row in activities):
        raise _AlternativeConflict('Choose an unused replacement for an existing activity.')
    scope = normalize_destination_scope(current.get('destinationArea'))
    if not scope['state'] or not filter_candidates([candidate], scope)[0]:
        raise _AlternativeConflict('The replacement location is not verified for this trip.')
    before = activity_pricing(original, current.get('travellerCount'))
    if original.get('costCategory') not in (None, '', 'admission') or original.get('paymentStatus') in {'paid', 'succeeded'}:
        raise _AlternativeConflict('Only a comparable planning admission cost can be replaced.')
    replacement = _activity_from_destination(candidate, 0)
    after = activity_pricing(replacement, current.get('travellerCount'))
    if (before['pricingIssues'] or after['pricingIssues'] or before['overlapsAllowance'] or after['overlapsAllowance']
            or before['costProvenance'] not in {'verified_ticket', 'user_entered'}
            or after['costProvenance'] != 'verified_ticket'
            or (candidate.get('currency') or (candidate.get('pricingEvidence') or {}).get('currency')) != 'MYR'
            or original.get('currency', 'MYR') != 'MYR'):
        raise _AlternativeConflict('Comparable MYR admission prices are unavailable.')
    savings = round(before['effectiveCost'] - after['effectiveCost'], 2)
    if savings <= 0:
        raise _AlternativeConflict('The replacement is not a lower estimated cost.')

    schedule = current.get('dailySchedule') or []
    matching_days = [day for day in schedule if any(
        row.get('activityId') == requested for row in day.get('activities', []))]
    if len(matching_days) != 1:
        raise _AlternativeConflict('A saved day and visit time are needed for this replacement.')
    day = matching_days[0]
    day_rows = day['activities']
    positions = [i for i, row in enumerate(day_rows) if row.get('activityId') == requested]
    if len(positions) != 1:
        raise _AlternativeConflict('The saved day contains duplicate activity identities.')
    index = positions[0]
    slot = day_rows[index]
    if _activity_identity(slot) != _activity_identity(original):
        raise _AlternativeConflict('The saved itinerary and daily schedule do not match.')
    start, old_end = (_parse_time_minutes(slot.get(key)) for key in ('scheduledStartTime', 'scheduledEndTime'))
    try:
        day_date = date.fromisoformat(day.get('dayDate') or day.get('date') or slot.get('dayDate'))
        if not date.fromisoformat(current['startDate'][:10]) <= day_date <= date.fromisoformat(current['endDate'][:10]):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise _AlternativeConflict('The selected day does not match the saved trip dates.') from None
    duration, duration_source = _activity_duration(replacement)
    opening = _activity_opening(replacement, day_date)
    distance = _distance_km(slot, replacement)
    if (start is None or old_end is None or distance is None or not 0 <= distance <= 10
            or opening['provisional'] or not any(a <= start and start + duration <= b for a, b in opening.get('periods', []))
            or start + duration > old_end):
        raise _AlternativeConflict('The replacement cannot be confirmed for the saved visit time and location.')
    for block in day.get('planningBlocks') or []:
        block_start, block_end = (_parse_time_minutes(block.get(key)) for key in ('startTime', 'endTime'))
        if block_start is not None and block_end is not None and start < block_end and start + duration > block_start:
            raise _AlternativeConflict('The replacement would overlap another planned block.')
    previous = day_rows[index - 1] if index else None
    following = day_rows[index + 1] if index + 1 < len(day_rows) else None
    inbound = _travel_leg(previous, replacement)
    outbound = _travel_leg(replacement, {**following, 'travelTimeSource': ''}) if following else None
    for neighbor, leg, time_key, boundary in (
        (previous, inbound, 'scheduledEndTime', start),
        (following, outbound, 'scheduledStartTime', start + duration),
    ):
        if neighbor:
            neighbor_time = _parse_time_minutes(neighbor.get(time_key))
            if (neighbor_time is None or leg[1] is None or
                    (boundary - neighbor_time if neighbor is previous else neighbor_time - boundary) < leg[0]):
                raise _AlternativeConflict('Estimated travel would conflict with another activity on this day.')
    replacement.update({key: slot[key] for key in ('activityId', 'dayNo', 'dayDate', 'dayLabel', 'sequenceNo', 'timeSlot', 'scheduledStartTime') if key in slot})
    replacement.update(
        currency='MYR', effectiveCost=after['effectiveCost'], scheduledEndTime=_format_time(start + duration),
        timeRangeLabel=f'{_format_time(start)} - {_format_time(start + duration)}',
        recommendedDurationMinutes=duration, durationSource=duration_source,
        travelBufferMinutes=inbound[0], travelDurationMinutes=inbound[0],
        travelDistanceKm=inbound[1], travelTimeSource=inbound[2], durationEstimated=duration_source != 'provider',
        openingHoursStatus=opening['status'], openingHoursEvidence=opening['evidence'],
        scheduleFeasibility='feasible_with_reported_hours',
        scheduleNotes=['Check venue hours and admission before visiting.'],
    )
    new_day_rows = list(day_rows)
    new_day_rows[index] = replacement
    if following:
        buffer, distance, source = outbound
        new_day_rows[index + 1] = {**following, 'travelBufferMinutes': buffer, 'travelDurationMinutes': buffer,
                                   'travelDistanceKm': distance, 'travelTimeSource': source}
    changed = {row['activityId']: row for row in new_day_rows[index:index + 2]}
    day_patch = {**day, 'activities': new_day_rows, 'estimatedMinutes': sum(
        int(row.get('recommendedDurationMinutes') or 0) + int(row.get('travelDurationMinutes') or 0)
        for row in new_day_rows
    ), 'estimatedCost': round(sum(
        activity_pricing(row, current.get('travellerCount'))['effectiveCost'] for row in new_day_rows
    ), 2)}
    patch = {'activities': [changed.get(row.get('activityId'), row) for row in activities],
             'dailySchedule': [day_patch if row is day else row for row in schedule]}
    return replacement, patch, savings


def _flight_cabin(current):
    from modules.fr07_flight_search.routes import _load_quote
    if current.get('flightSearchId'):
        quote = _load_quote(current['flightSearchId'])
        if quote:
            return (quote.get('criteria') or {}).get('travel_class', 1)
    flight = current.get('selectedFlight') or {}
    labels = {'economy': 1, 'premium economy': 2, 'business': 3, 'first': 4, 'first class': 4}
    cabins = {labels.get(str(leg.get('travelClass') or '').strip().lower())
              for leg in flight.get('outboundSegments') or []}
    return next(iter(cabins)) if len(cabins) == 1 else None


def _flight_alternative_options(current):
    from modules.fr07_flight_search.routes import _criteria, _provider_route_matches, _store_quote
    from services.serpapi_service import retrieveFlightOptions
    from sequence_contract.validators import flightSearchValidationError

    flight = current.get('selectedFlight') or {}
    legs = flight.get('outboundSegments') or []
    if (current.get('travelMode') != 'flight' or not legs or flight.get('returnSegments')
            or current.get('flightCurrency') != 'MYR' or not current.get('flightPriceBasis')
            or not current.get('flightCost') or flight.get('price') != current.get('flightCost')):
        return []
    route = {'departure_id': legs[0].get('departureAirportCode') or '',
             'arrival_id': legs[-1].get('arrivalAirportCode') or '',
             'outbound_date': legs[0].get('departureDate') or '', 'return_date': None}
    if flightSearchValidationError(route):
        return []
    count = traveller_count(current.get('travellerCount'))
    travel_class = _flight_cabin(current)
    if travel_class not in {1, 2, 3, 4}:
        return []
    result = retrieveFlightOptions(route['departure_id'], route['arrival_id'], route['outbound_date'],
                                   currency='MYR', travelClass=travel_class, adults=count)
    criteria = _criteria(route, 'MYR', count, travel_class, None)
    items = [{**row, 'source': 'serpapi', 'planningOnly': True}
             for row in result.get('items', []) if _provider_route_matches(row, criteria)][:5]
    if not items:
        return []
    search_id, options = _store_quote(criteria, items, 'serpapi')
    return [{**row, 'searchId': search_id} for row in options]


def _resolve_cost_alternative(kind, data, current):
    """Resolve existing owned references; never accept client replacement prices."""
    if kind == 'flight':
        if current.get('travelMode') != 'flight' or not (current.get('selectedFlight') or {}).get('outboundSegments'):
            raise _AlternativeConflict('This itinerary has no comparable selected flight.')
        from modules.fr07_flight_search.routes import (
            _quote_item, _flight_trip_date_error, _flight_conflicts, _sanitize_flight_snapshot,
        )
        quote, option, error = _quote_item({
            'searchId': data.get('searchId') or data.get('flightSearchId'),
            'optionId': data.get('optionId') or data.get('flightOptionId'),
        })
        if error or not quote or not option:
            raise _AlternativeConflict('Flight reference is missing, invalid or expired. Search again.')
        criteria = quote.get('criteria') or {}
        selected = current.get('selectedFlight') or {}
        if ((criteria.get('travel_class') is not None and criteria['travel_class'] != _flight_cabin(current))
                or criteria.get('traveller_count') != traveller_count(current.get('travellerCount'))
                or option.get('travellerCount') != criteria.get('traveller_count')
                or option.get('quoteCompleteness') != 'complete'
                or option.get('budgetEligible') is False
                or (criteria.get('return_date') and not option.get('returnSegments'))):
            raise _AlternativeConflict('Flight quote is incomplete or its traveller count no longer matches this trip.')
        for field, segments, segment_field in (
                ('outbound_date', 'outboundSegments', 'departureDate'),
                ('return_date', 'returnSegments', 'departureDate')):
            old_segments = selected.get(segments) or []
            old_date = old_segments[0].get(segment_field) if old_segments else None
            if (criteria.get(field) or None) != (old_date or None):
                raise _AlternativeConflict('Compare flight prices for the same travel dates.')
        for field, segment, airport in (
                ('departure_id', 0, 'departureAirportCode'),
                ('arrival_id', -1, 'arrivalAirportCode')):
            old_segments = selected.get('outboundSegments') or []
            if not old_segments or criteria.get(field) != old_segments[segment].get(airport):
                raise _AlternativeConflict('Compare flight prices for the same route.')
        if _flight_trip_date_error(current, option) or _flight_conflicts(current, option):
            raise _AlternativeConflict('Review flight date/activity conflicts through flight selection first.')
        if selected.get('price') != current.get('flightCost'):
            raise _AlternativeConflict('The existing flight price is not comparable.')
        trusted = _sanitize_flight_snapshot({**option, 'searchId': quote['id'],
                    'travellerCount': criteria['traveller_count'], '_validatedAlternative': True})
        patch = {
            'selectedFlight': _sanitize_flight_snapshot({**option, 'flightSearchId': quote['id'],
                                                        'flightOptionId': option.get('optionId') or option.get('id')}),
            'flightCost': option.get('price'), 'flightCurrency': option.get('currency'),
            'flightPriceBasis': option.get('priceBasis'), 'flightSearchId': quote['id'],
            'flightOptionId': option.get('optionId') or option.get('id'),
            'flightSelectionSource': option.get('source') or quote.get('source'),
            'flightSelectionStatus': 'selected', 'travelMode': 'flight',
            'flightQuoteCompleteness': option.get('quoteCompleteness'),
            'flightQuoteVersion': quote.get('quoteVersion'), 'flightQuoteRetrievedAt': quote.get('retrievedAt'),
            'flightPriceScope': option.get('priceScope'),
            'flightPriceSemanticsStatus': option.get('priceSemanticsStatus'),
            'flightSelectedAt': utc_now_iso(), 'flightConflicts': [], 'flightConflictStatus': 'none',
        }
        reference = f"flight:{quote['id']}:{patch['flightOptionId']}"
        return trusted, patch, reference, current
    if kind == 'hotel':
        from services.malaysian_locality import normalize_destination_scope
        booking_id = str(data.get('hotelBookingId') or '').strip()
        booking = retrieveRecord('hotel_bookings', booking_id) if booking_id else None
        patch, error = _trusted_hotel_update(current, {'hotelBookingId': booking_id}, booking=booking or {})
        if error:
            raise _AlternativeConflict(error)
        criteria = booking.get('stayCriteria') or {}
        old_booking = retrieveRecord('hotel_bookings', current.get('hotelBookingId')) if current.get('hotelBookingId') else None
        old_criteria = (old_booking or {}).get('stayCriteria') or {}
        _, old_error = _trusted_hotel_update(current, {'hotelBookingId': current.get('hotelBookingId')}, booking=old_booking or {})
        required = ('checkin', 'checkout', 'adults', 'roomQuantity')
        scope_fields = (*required, 'occupancies', 'children')
        comparison_criteria = {key: criteria.get(key) for key in scope_fields}
        old_comparison = {key: old_criteria.get(key) for key in scope_fields}
        if (old_error or not all(criteria.get(key) for key in required) or comparison_criteria != old_comparison
                or (old_booking or {}).get('travellerId') != g.uid
                or old_booking.get('hotelCost') != current.get('hotelCost')):
            raise _AlternativeConflict('Compare validated hotel costs for the same stay dates, guests and rooms.')
        try:
            compatible = date.fromisoformat(current['startDate']) <= date.fromisoformat(criteria['checkin']) < date.fromisoformat(criteria['checkout']) <= date.fromisoformat(current['endDate'])
        except (KeyError, TypeError, ValueError):
            compatible = False
        stay_scope = normalize_destination_scope(criteria.get('destination'))
        trip_scope = normalize_destination_scope(current.get('destinationArea'))
        if (not compatible or not stay_scope.get('resolved') or not trip_scope.get('resolved')
                or stay_scope.get('state') != trip_scope.get('state')):
            raise _AlternativeConflict('The hotel stay no longer matches this trip. Use hotel attachment to review compatibility.')
        trusted = {'price': patch['hotelCost'], 'currency': patch['hotelCurrency'],
                   'name': (patch['selectedHotel'] or {}).get('name') or 'Hotel',
                   'roomName': (patch['selectedHotel'] or {}).get('roomName') or 'Room',
                   'hotelBookingId': booking_id, 'stayCriteria': criteria,
                   'comparisonCriteria': comparison_criteria,
                   'source': booking.get('source') or 'validated_offer',
                   'selectedHotel': patch['selectedHotel'], '_validatedAlternative': True}
        return trusted, patch, f'hotel:{booking_id}', {**current, '_hotelComparisonCriteria': old_comparison}
    raise _AlternativeConflict('Unsupported alternative type. Use the corresponding validated selection workflow.')


@bp.post('/itineraries/<iid>/lower-cost-alternatives')
@auth_required(['traveller'])
def lower_cost_alternatives(iid):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    if _is_package_trip(current):
        return jsonify({'ok': False, 'error': 'Purchased package trips cannot be modified or recalculated.'}), 409
    try:
        flights = _flight_alternative_options(current)
    except Exception:
        flights = []

    hotels = []
    if (current.get('accommodationChoice') == 'paid_hotel' and current.get('hotelBookingId')
            and current.get('hotelCurrency') == 'MYR' and current.get('hotelCost')):
        owned = retrieveRecord('hotel_bookings', filters=[('travellerId', '==', g.uid)], limit=40) or []
        hotels = [{'hotelBookingId': row['id']} for row in owned
                  if row.get('id') and row['id'] != current['hotelBookingId']
                  and row.get('bookingStatus') in {'confirmed', 'paid'}]

    budget = calculateBudget(current)
    alternatives = []
    seen = set()
    duplicate_count = 0
    for kind, options in (('flight', flights), ('hotel', hotels)):
        for option in options:
            try:
                trusted, _, reference, comparison = _resolve_cost_alternative(kind, option, current)
            except (ValueError, KeyError, TypeError):
                continue
            savings = _alternative_savings(kind, trusted, comparison)
            if savings is None:
                continue
            if kind == 'flight':
                identity = tuple(
                    tuple(segment.get(key) for key in (
                        'flightNumber', 'departureDate', 'departureTime', 'arrivalDate', 'arrivalTime'))
                    for segment in trusted.get('outboundSegments') or []
                )
                identity = identity if any(any(segment) for segment in identity) else reference
            else:
                selection = trusted.get('selectedHotel') or {}
                identity = (selection.get('hotelId'), selection.get('offerId')) if selection.get('offerId') else reference
            key = (kind, trusted.get('source'), identity)
            if key in seen:
                duplicate_count += 1
                continue
            seen.add(key)
            original = current.get('selectedFlight' if kind == 'flight' else 'selectedHotel') or {}
            name = trusted.get('airline' if kind == 'flight' else 'name') or kind.title()
            original_name = original.get('airline' if kind == 'flight' else 'name') or f'selected {kind}'
            comparison_basis = ('Same travel dates, route and traveller count.' if kind == 'flight'
                                else 'Same stay dates, guests and rooms.')
            alternatives.append({
                'alternativeType': kind, 'alternativeId': reference, 'canApply': True, 'isAdvisory': False,
                'title': f'Lower-cost {kind}: {name}',
                'description': f'Replace {original_name}. {comparison_basis}',
                'estimatedSavings': savings, 'currentEstimatedCost': current[f'{kind}Cost'],
                'replacementEstimatedCost': trusted['price'],
                'data': {key: value for key, value in trusted.items() if key != '_validatedAlternative'},
            })
    activity_items = []
    rejection_reasons = {}
    activities = current.get('activities') or []
    candidates = _activity_options(current) if activities else {}
    if not current.get('dailySchedule'):
        activity_advice = 'A saved day and visit time are needed before a replacement can be checked; savings cannot be calculated.'
    elif not candidates:
        activity_advice = 'There are no activities with verified replacement admission prices in this destination.'
    else:
        for row in activities:
            for identity in candidates:
                data = {'activityId': row.get('activityId'), 'destinationId': identity}
                try:
                    replacement, _, savings = _resolve_activity_alternative(current, data, candidates)
                except (ValueError, TypeError, KeyError) as error:
                    reason = str(error) if isinstance(error, _AlternativeConflict) else 'The saved activity information is incomplete.'
                    rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                    continue
                current_cost = activity_pricing(row, current.get('travellerCount'))['effectiveCost']
                reference = f"activity:{data['activityId']}:{identity}"
                if reference in seen:
                    duplicate_count += 1
                    continue
                seen.add(reference)
                activity_items.append({
                    'alternativeType': 'activity', 'canApply': True, 'isAdvisory': False,
                    'title': f"Visit {replacement['activityName']} instead",
                    'description': f"Replace {row.get('activityName', 'this activity')} on day {replacement.get('dayNo')} at {replacement.get('scheduledStartTime')}. "
                                   'Savings compare estimated admission only. Check opening hours before visiting.',
                    'estimatedSavings': savings, 'data': data,
                    'currentEstimatedCost': current_cost, 'replacementEstimatedCost': replacement['effectiveCost'],
                    'alternativeId': reference,
                })
                if len(activity_items) == 8:
                    break
            if len(activity_items) == 8:
                break
        activity_advice = 'No comparable priced activity replacement is available here; savings cannot be calculated.'
    if not activity_items:
        reasons = ' '.join(sorted(rejection_reasons, key=rejection_reasons.get, reverse=True)[:2])
        activity_advice += (' ' + reasons) if reasons else ''
        activity_advice += ' Check the admission price, pricing unit and suitability before changing a visit.'
        if budget.get('expenseBreakdown', {}).get('hotel', {}).get('state') in {'undecided', 'not_selected'}:
            activity_advice += ' Choose accommodation before comparing hotel costs.'
    alternatives = sorted(activity_items + alternatives, key=lambda item: -item['estimatedSavings'])
    for alternative in alternatives:
        alternative['stateVersion'] = _alternative_state(current)
    return jsonify({
        'ok': True, 'budget': budget, 'alternatives': alternatives,
        'activityAlternativeStatus': 'available' if activity_items else 'priced_replacement_unavailable',
        'activityAdvice': None if activity_items else activity_advice,
        'activityCandidateCount': len(candidates),
        'duplicateAlternativeCount': duplicate_count,
        'activityRejectionCounts': rejection_reasons,
    })


@bp.post('/itineraries/<iid>/lower-cost-alternatives/apply')
@auth_required(['traveller'])
def apply_lower_cost_alternative(iid):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    if _is_package_trip(current):
        return jsonify({'ok': False, 'error': 'Purchased package trips cannot be modified or recalculated.'}), 409
    payload = request.get_json(silent=True) or {}
    alternative = payload.get('alternative') if isinstance(payload.get('alternative'), dict) else payload
    kind = str(alternative.get('alternativeType') or alternative.get('type') or '').lower()
    if kind in {'activity', 'activities'} and not (
            alternative.get('stateVersion') and alternative.get('alternativeId')
            and alternative.get('canApply') is True):
        # A client-supplied price is never a validated replacement.
        return jsonify({
            'ok': False,
            'error': 'No validated priced activity replacement is available. Existing activity prices have not been changed.',
            'code': 'ACTIVITY_REPLACEMENT_UNAVAILABLE',
            'canApply': False,
        }), 409
    if kind in {'transport', 'food', 'schedule', 'car', 'car_rental', 'rental'} or alternative.get('isAdvisory') is True or alternative.get('canApply') is False:
        return jsonify({'ok': False, 'error': 'This is advisory guidance, not a validated priced change. The trip budget has not changed.',
                        'code': 'ADVISORY_ALTERNATIVE', 'canApply': False}), 409
    if kind not in {'flight', 'hotel', 'activity'}:
        return jsonify({'ok': False, 'error': 'Unsupported lower-cost alternative'}), 400
    if alternative.get('stateVersion') and alternative['stateVersion'] != _alternative_state(current):
        return jsonify({'ok': False, 'error': 'This itinerary has changed. Reload alternatives before applying.',
                        'code': 'STALE_ALTERNATIVE'}), 409
    data = alternative.get('data') if isinstance(alternative.get('data'), dict) else {}
    try:
        if kind == 'activity':
            trusted, patch, savings = _resolve_activity_alternative(current, data, _activity_options(current))
            reference = f"activity:{data['activityId']}:{data['destinationId']}"
        else:
            trusted, patch, reference, comparison = _resolve_cost_alternative(kind, data, current)
            already_applied = (
                current.get('flightSearchId') == patch.get('flightSearchId')
                and current.get('flightOptionId') == patch.get('flightOptionId')
                if kind == 'flight' else current.get('hotelBookingId') == patch.get('hotelBookingId')
            )
            if already_applied and current.get(f'{kind}Cost') == trusted.get('price'):
                if alternative.get('alternativeId') and alternative['alternativeId'] != reference:
                    raise _AlternativeConflict('Alternative reference does not match the selected option.')
                return jsonify({'ok': True, 'itinerary': current, 'budget': calculateBudget(current), 'reused': True})
            savings = _alternative_savings(kind, trusted, comparison)
    except _AlternativeConflict as error:
        return jsonify({'ok': False, 'error': str(error), 'code': 'INVALID_ALTERNATIVE_REFERENCE'}), 409
    except Exception:
        return jsonify({'ok': False, 'error': 'Alternative verification is unavailable. Please try again later.'}), 503
    if alternative.get('alternativeId') and alternative['alternativeId'] != reference:
        return jsonify({'ok': False, 'error': 'Alternative reference does not match the selected option.'}), 409
    if alternative.get('stateVersion') and alternative.get('estimatedSavings') != savings:
        return jsonify({'ok': False, 'error': 'The estimated savings changed. Review the latest alternatives.',
                        'code': 'STALE_ALTERNATIVE'}), 409
    if savings is None:
        return jsonify({'ok': False, 'error': 'A lower comparable MYR total could not be established. Use the validated selection workflow.'}), 409
    if kind != 'activity':
        patch[f'{kind}Cost'] = float(trusted['price'])
    applied = {'alternativeType': kind, 'alternativeId': reference, 'estimatedSavings': savings,
               'data': {key: value for key, value in trusted.items() if key != '_validatedAlternative'}}
    patch.update({'updatedAt': utc_now_iso(), 'lastAppliedLowerCostAlternative': applied})
    updated_input = {**current, **patch}
    patch['budgetEstimate'] = calculateBudget(updated_input)
    patch['budgetEstimate']['comparison'] = compareBudget(patch['budgetEstimate'])
    try:
        updated = _commit_cost_alternative(iid, current, patch)
        if not updated:
            raise RuntimeError('No updated itinerary returned')
    except _AlternativeConflict as error:
        return jsonify({'ok': False, 'error': str(error), 'code': 'STALE_ALTERNATIVE'}), 409
    except Exception:
        return jsonify({'ok': False, 'error': 'The itinerary update could not be confirmed. Reload the trip before trying again.'}), 503
    return jsonify({'ok': True, 'itinerary': updated, 'budget': patch['budgetEstimate'], 'applied': applied})


@bp.post('/personalised-trips/generate')
@auth_required(['traveller'])
def generate_personalised_trip_route():
    try:
        payload = validate_trip_write(request.get_json(silent=True), generation=True)
    except ValueError as error:
        return jsonify({'ok': False, 'error': str(error), 'stage': 'input_validation',
                        'retryable': False}), 400
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
    if _is_package_trip(current):
        return jsonify({'ok': False, 'error': 'Purchased package trips cannot be modified or recalculated.'}), 409
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
    if _is_package_trip(current):
        return jsonify({'ok': False, 'error': 'Purchased package trips cannot be modified or recalculated.'}), 409
    if not validateItineraryForSaving(current):
        return jsonify({'ok': False, 'error': 'Itinerary cannot be saved'}), 400
    return jsonify({'ok': True, 'itinerary': updateRecord('itineraries', iid, {'status': 'planned', 'plannedAt': utc_now_iso(), 'updatedAt': utc_now_iso()})})


@bp.delete('/itineraries/<iid>')
@auth_required(['traveller'])
def delete_itinerary_route(iid):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    if _is_package_trip(current):
        return jsonify({'ok': False, 'error': 'Purchased package trips cannot be deleted.'}), 409
    deleteRecord('itineraries', iid)
    return jsonify({'ok': True})

