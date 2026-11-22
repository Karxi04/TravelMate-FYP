import hashlib
import os
import re
import json
import logging
from datetime import date, datetime, timezone, timedelta
from time import perf_counter
from flask import Blueprint, request, jsonify, g, current_app
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
from services.itinerary_identity import POLICY, same_attraction, consolidate_generated_candidates
from services.trip_budget_replan import budget_replan_options, preview_budget_replan, protected_activity, planning_alternatives
from services.itinerary_history import history_patch, history_metadata, HistoryConflict
from sequence_contract.validators import validateItineraryInput, validateItineraryForSaving, validateSelectedDestination
from sequence_contract.firebase_firestore import retrieveRecord, storeRecord, updateRecord, deleteRecord, claimRecord
from services.recommendation_snapshot_resolver import SnapshotUnavailable
from sequence_contract.domain_functions import (
    createItinerary, addActivity, removeActivity, rearrangeActivity, updateActivity,
    checkDestinationLimit, calculateBudget, compareBudget,
    generateItinerary, groupNearbyActivities,
    checkOpeningHoursAndTravelTime, adjustWeatherSensitiveActivities, recalculateItinerary,
    LOCAL_ACTIVITY_FIELDS, LOCAL_DAYS_POLICY, plan_intercity_transfer,
    _alternative_savings, _activity_duration, _activity_opening, _distance_km,
    _format_time, _parse_time_minutes, _travel_leg,
)
from services.flight_itinerary_adjustment import (
    apply_preview as apply_flight_adjustment_preview,
    create_preview as create_flight_adjustment_preview,
)

bp = Blueprint('fr05_itineraries', __name__, url_prefix='/api/fr5')


@bp.errorhandler(SnapshotUnavailable)
def snapshot_temporarily_unavailable(error):
    return jsonify(ok=False,error=str(error),code='recommendation_evidence_unavailable',
                   stage='snapshot_validation',retryable=True,requiresExplicitRegeneration=False),503


@bp.errorhandler(HistoryConflict)
def history_conflict(error):
    return jsonify(ok=False, error=str(error)), 409


@bp.get('/itineraries/<iid>/history')
@auth_required(['traveller'])
def itinerary_history(iid):
    current = _own(iid)
    if not current:
        return jsonify(ok=False, error='Itinerary not found'), 404
    return jsonify(ok=True, currentVersion=current.get('itineraryRevision', 1),
                   retention=5, versions=history_metadata(current),
                   limitation='History begins with the first captured edit; pre-feature versions are unavailable.')


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

    from services.recommendation_snapshot_resolver import resolve_snapshot
    snapshot, error = resolve_snapshot(generation_id, current.get('destinationArea'), retrieveRecord)
    if error:
        return None, error
    if snapshot.get('recommendationEvidenceMode') == 'fyp_evaluation':
        return snapshot, None  # The shared resolver already checked canonical scope.

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
    from services.itinerary_identity import IDENTITY_FIELDS
    item = dict(item or {})
    gps = item.get('gps_coordinates') or item.get('gpsCoordinates') or {}
    return {
        **{key: item[key] for key in (*IDENTITY_FIELDS, *LOCAL_ACTIVITY_FIELDS) if key in item},
        'activityId': f'A{index + 1}',
        'planningOrigin': 'generated',
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
    started = perf_counter()
    if snapshot:
        generation_id = str(snapshot.get('recommendationGenerationId') or '')
        for activity in current.get('activities', []) or []:
            activity_generation_id = str(activity.get('recommendationGenerationId') or '')
            if activity_generation_id and activity_generation_id != generation_id:
                raise ValueError('Itinerary contains recommendations from a different snapshot')

    generation_source = snapshot.get('source', 'recommendation_snapshot') if snapshot else 'existing-activities'
    working = {**current, 'geographyPlanningPolicy': LOCAL_DAYS_POLICY}
    profile = current.get('planningPreferences') or (snapshot or {}).get('planningPreferences') or {}
    if profile:
        working.update(planningPreferences=profile,
                       travelPace=current.get('travelPace') or profile.get('travelPace'),
                       sleepingType=current.get('sleepingType') or profile.get('sleepingType'))
    selection_enabled = _budget_selection_enabled()
    apply_selection = False
    selection_skip_reason = 'existing_activities_preserved'
    if not working.get('activities'):
        candidates, generation_source = _destination_candidates(working, snapshot)
        candidates = consolidate_generated_candidates(candidates, automatic=True)
        from sequence_contract.domain_functions import diversifyRecommendations
        if profile.get('interests'):
            candidates = diversifyRecommendations(candidates, profile, limit=len(candidates), coverageAware=True)
        working['attractionIdentityPolicy'] = POLICY
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
    candidates_done = perf_counter()
    locations = retrieveLocationAndTravelTime(selected)
    locations_done = perf_counter()
    forecast, coords = _forecast_for(working, payload)
    weather_done = perf_counter()

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
    timings = {'candidates': round((candidates_done - started) * 1000),
               'locations': round((locations_done - candidates_done) * 1000),
               'weather': round((weather_done - locations_done) * 1000),
               'scheduling': round((perf_counter() - weather_done) * 1000)}
    logging.getLogger(__name__).info('itinerary_stage_timings_ms=%s', timings,
                                   extra={'planning_timings_ms': timings})
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
    updated = updateRecord('itineraries', iid, patch, expected=current)
    return updated or {**current, **patch, 'id': iid}


def _run_generation_state_machine(iid, current, payload, snapshot):
    stage = 'itinerary_generation'
    partial = None
    started = perf_counter()
    try:
        partial = _generate_itinerary_data(current, payload, snapshot)
        stage = 'budget_calculation'
        budget_started = perf_counter()
        budget = calculateBudget(partial)
        if partial.get('generationContext', {}).get('budgetAwareSelectionApplied') is True:
            budget = qualify_selection_budget(budget, partial['budgetAwareSelection'])
        budget['comparison'] = compareBudget(budget)
        budget_ms = round((perf_counter() - budget_started) * 1000)

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
        save_started = perf_counter()
        persisted = updateRecord('itineraries', iid, planned)
        if persisted is None:
            raise RuntimeError('Generated trip could not be saved')
        current_app.logger.info('itinerary_generation_completed total_ms=%d save_ms=%d budget_ms=%d',
                                round((perf_counter() - started) * 1000),
                                round((perf_counter() - save_started) * 1000),
                                budget_ms)
        return persisted, None, None
    except Exception as error:
        current_app.logger.warning('itinerary_generation_failed stage=%s elapsed_ms=%d type=%s',
                                   stage, round((perf_counter() - started) * 1000), type(error).__name__)
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
    try:
        start = date.fromisoformat(str(current.get('startDate') or payload.get('startDate'))[:10])
        if start > datetime.now(timezone(timedelta(hours=8))).date() + timedelta(days=7):
            return {}, None  # A seven-day forecast cannot describe a later trip.
    except ValueError:
        pass
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
    from services.flexible_planning import confirmation_status,active
    rows=retrieveRecord('itineraries', filters=[('travellerId', '==', g.uid)]) or []
    return jsonify({'ok': True, 'items': [{**row,'travelDayStatus':confirmation_status(row)}
        if not _is_package_trip(row) and (active(row) or row.get('selectedFlight')) else row for row in rows]})


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
    from services.flexible_planning import availability_for, personal_blocks
    planning = None
    if not _is_package_trip(current) and current.get('startDate') and current.get('endDate'):
        from services.flight_itinerary_adjustment import planning_assumptions
        planning={'availability':availability_for({**current,'planningMode':current.get('planningMode') or 'smart'}),
                  'assumptions':planning_assumptions(), 'personalBlocks':personal_blocks(current)}
    return jsonify({'ok': True, 'itinerary': current, **({'planning':planning} if planning else {})})


@bp.post('/itineraries')
@auth_required(['traveller'])
def create_itinerary_route():
    try:
        payload = validate_trip_write(request.get_json(silent=True))
    except ValueError as error:
        return jsonify({'ok': False, 'error': str(error)}), 400
    if not validateItineraryInput(payload) or not str(payload.get('destinationArea') or '').strip():
        return jsonify({'ok': False, 'error': 'Use a title, valid date range, positive traveller count and non-negative budget'}), 400
    activities = payload.get('activities', [])
    if any(same_attraction(row, earlier) for index, row in enumerate(activities)
           for earlier in activities[:index]):
        return jsonify(ok=False, error='Add repeat visits to the saved trip and confirm each revisit.'), 409
    itinerary = createItinerary(payload, g.uid)
    from services.flexible_planning import active, trip_days
    if active(itinerary):
        try:
            itinerary['tripDays'] = trip_days(itinerary)
        except ValueError as error:
            return jsonify(ok=False,error=str(error)),400
        initial = itinerary.get('activities') or []
        itinerary['activities'] = []
        for row in initial:
            itinerary = addActivity(itinerary, row)
        itinerary = recalculateItinerary(itinerary, preserveOrder=True, respectDayAssignments=True)
        itinerary['status'] = 'planned'
    budget = calculateBudget(itinerary)
    itinerary['budgetEstimate'] = budget
    if payload.get('generationRequestId'):
        from services.transaction_reliability import normalize_attempt_id
        try:
            identity = normalize_attempt_id(payload['generationRequestId'], 'generationRequestId')
        except ValueError as error:
            return jsonify(ok=False,error=str(error)),400
        key = _personalised_trip_id(g.uid, identity)
        itinerary.update(id=key, creationFingerprint=_alternative_state(payload))
        result, created = claimRecord('itineraries', key, itinerary)
        if result.get('travellerId')!=g.uid or result.get('creationFingerprint')!=itinerary['creationFingerprint']:
            return jsonify(ok=False,error='This creation request was used for another trip. Review the existing result.'),409
    else:
        result, created = storeRecord('itineraries', itinerary), True
    return jsonify({'ok': True, 'id': result['id'], 'itinerary': result, 'budget': result.get('budgetEstimate',budget)}), 201 if created else 200


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
    expected_revision = payload.pop('expectedItineraryRevision', None)
    if expected_revision is not None and expected_revision != int(current.get('itineraryRevision') or 1):
        return jsonify(ok=False, error='This trip changed. Reopen it before saving your edits.',
                       code='STALE_ITINERARY'), 409
    payload, hotel_error = _trusted_hotel_update(current, payload)
    if hotel_error:
        return jsonify({'ok': False, 'error': hotel_error}), 409
    payload, flight_error = _trusted_flight_update(payload)
    if flight_error:
        return jsonify({'ok': False, 'error': flight_error}), 409
    if not validateItineraryInput({**current, **payload}):
        return jsonify({'ok': False, 'error': 'Use a title, valid date range, positive traveller count and non-negative budget'}), 400
    if 'startDate' in payload or 'endDate' in payload:
        from services.flexible_planning import active, validate_preferences, public_preferences, validate_blocks
        if active(current):
            try:
                validate_preferences(public_preferences(current.get('travelDayPreferences')), {**current,**payload})
                block_fields={'blockId','type','label','dayNo','startTime','endTime','durationMinutes','location','notes','locked','estimatedCost','boundary'}
                validate_blocks([{k:v for k,v in row.items() if k in block_fields} for row in current.get('planningBlocks') or []],{**current,**payload})
            except ValueError as error:
                return jsonify(ok=False,error=f'Update planning settings before changing these dates. {error}'),409
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
    return jsonify({'ok': True, 'itinerary': updateRecord('itineraries', iid, payload, expected=current)})


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
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload,dict):
        return jsonify(ok=False,error='Choose valid planning settings.'),400
    planning = payload if 'planningChanges' in payload or 'action' in payload else None
    if not flight and planning is None:
        return jsonify({'ok': False, 'error': 'Select a flight before requesting an itinerary adjustment preview.'}), 409
    candidates = None
    if planning and planning.get('action')=='regenerate':
        generation=planning.get('recommendationGenerationId')
        if generation is not None and (not isinstance(generation,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',generation)):
            return jsonify(ok=False,error='Choose a valid saved recommendation generation.'),400
        snapshot, error = _recommendation_snapshot(current,planning)
        if error:return jsonify(ok=False,error=error),409
        if snapshot:
            rows = _filter_destination_candidates(snapshot.get('recommendationResults') or snapshot.get('items') or [],current.get('destinationArea'))
            candidates = [{**_activity_from_destination(row,index), 'recommendationGenerationId':
                current.get('recommendationGenerationId') or generation} for index,row in enumerate(rows)
                if str(row.get('title') or row.get('name') or '').strip()]
    try:
        preview = (create_flight_adjustment_preview(current, flight or {}, g.uid, planning=planning, candidates=candidates)
                   if planning is not None else create_flight_adjustment_preview(current, flight, g.uid))
    except ValueError as error:
        return jsonify(ok=False,error=str(error)),400
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
        lambda _iid, patch: updateRecord('itineraries', _iid, patch, expected=current),
    )
    if error:
        return jsonify({'ok': False, 'error': error}), 404 if error == 'Preview not found' else 409
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


@bp.post('/itineraries/<iid>/intercity-transfer')
@auth_required(['traveller'])
def confirm_intercity_transfer(iid):
    current = _own(iid)
    if not current:
        return jsonify(ok=False, error='Itinerary not found'), 404
    if _is_package_trip(current):
        return jsonify(ok=False, error='Purchased package trips cannot be modified or recalculated.'), 409
    if current.get('confirmedIntercityTransfer'):
        return jsonify(ok=False, error='This itinerary already has a confirmed intercity transfer.'), 409
    try:
        revised = plan_intercity_transfer(current, request.get_json(silent=True))
    except ValueError as error:
        return jsonify(ok=False, error=str(error)), 409
    for activity in current.get('activities') or []:
        if protected_activity(activity):
            return jsonify(ok=False, error='This change would replan protected visits.'), 409
    revised['budgetEstimate'] = calculateBudget(revised)
    revised['budgetEstimate']['comparison'] = compareBudget(revised['budgetEstimate'])
    saved = updateRecord('itineraries', iid, revised, expected=current)
    if saved is None:
        return jsonify(ok=False, error='Itinerary not found'), 404
    return jsonify(ok=True, itinerary=saved)


def _travel_edit_conflict(original, planned, activity_id):
    discarded = {row.get('activityId'): row.get('unscheduledReason', '')
                 for row in planned.get('unscheduledSuggestions') or []}
    affected = [activity_id, *(row.get('activityId') for row in original.get('activities', []))]
    for identifier in affected:
        reason = discarded.get(identifier, '')
        if reason.startswith(('This stop is too far', 'Could not establish a reliable journey',
                              'This day already includes similar')):
            return jsonify(ok=False, error=reason, code='itinerary_travel_conflict'), 409
    return None


def _edit_planning_policy(current, activities):
    # Legacy coordinate-free manual trips keep their existing edit behaviour.
    # Establish the local policy when there is real distance evidence to check.
    geocoded = sum(bool(row.get('gps_coordinates') or row.get('gpsCoordinates')) for row in activities)
    return LOCAL_DAYS_POLICY if geocoded >= 2 else current.get('geographyPlanningPolicy')


@bp.post('/itineraries/<iid>/activities')
@auth_required(['traveller'])
def add_activity_route(iid):
    current = _own(iid)
    payload = request.get_json(silent=True) or {}
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    if _is_package_trip(current):
        return jsonify({'ok': False, 'error': 'Purchased package trips cannot be modified or recalculated.'}), 409
    if str(current.get('status') or '').lower() in {'completed', 'cancelled'}:
        return jsonify(ok=False, error='This itinerary no longer accepts new visits.'), 409
    if not isinstance(payload, dict):
        return jsonify(ok=False, error='Choose a valid activity.'), 400
    if payload.get('destinationId') and not validateSelectedDestination(payload.get('destinationId')):
        return jsonify({'ok': False, 'error': 'Invalid destination'}), 400
    request_id = payload.get('clientRequestId')
    if request_id is not None and (not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', request_id)):
        return jsonify(ok=False, error='Invalid activity request identifier.'), 400
    try:
        day = int(str(payload.get('dayNo', 1)))
        cost = float(payload.get('estimatedCost', 0) or 0)
        duration = int(payload.get('recommendedDurationMinutes') or 0)
        if (not 1 <= day <= _trip_days(current) or not 0 <= cost < float('inf')
                or duration < 0):
            raise ValueError()
    except (TypeError, ValueError, OverflowError):
        return jsonify(ok=False, error='Choose a valid trip day and activity amount.'), 400

    activity = {
        'activityName': payload.get('activityName') or payload.get('title') or 'New activity',
        **{key: payload[key] for key in ('city', 'state', 'country') if isinstance(payload.get(key), str)},
        'destinationId': payload.get('destinationId', ''),
        'address': payload.get('address', ''),
        'dayNo': day,
        'timeSlot': payload.get('timeSlot', ''),
        'estimatedCost': cost,
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
    activity['planningOrigin'] = 'user_selected'
    try:
        from services.flexible_planning import clock, time_text
        if 'fixed' in payload and type(payload['fixed']) is not bool:raise ValueError('Choose Fixed or Flexible.')
        if payload.get('timeSlot'):
            start=clock(payload['timeSlot']);length=duration or 90
            if start+length>=1440:raise ValueError('This activity must finish on its selected day.')
            activity.update(scheduledStartTime=time_text(start),scheduledEndTime=time_text(start+length))
            if payload.get('fixed',True):activity.update(fixed=True,manualTime=True)
    except ValueError as error:
        return jsonify(ok=False,error=str(error)),400
    payload_hash = _alternative_state(activity)
    receipts = current.get('activityAddReceipts') or {}
    if request_id and request_id in receipts:
        receipt = receipts[request_id]
        if receipt['payloadHash'] != payload_hash:
            return jsonify(ok=False, error='This activity request was already used for a different visit.'), 409
        return jsonify(ok=True, itinerary=current, activities=current.get('activities', []),
                       budget=current.get('budgetEstimate'), alreadyAdded=True)

    matching = [row for row in [*current.get('activities', []),
                *(current.get('unscheduledSuggestions') or [])] if same_attraction(row, activity)]
    same_day = next((row for row in matching if str(row.get('dayNo')) == str(day)), None)
    if same_day:
        return _same_day_visit(same_day, day)
    existing = next(iter(matching), None)
    confirmation = payload.get('revisitConfirmation')
    if existing:
        # Bind the confirmation to this owner, trip revision, action, exact payload and request ID.
        token = _alternative_state({'action': 'add-revisit', 'owner': g.uid, 'trip': iid,
            'state': _alternative_state(current), 'payload': payload_hash, 'request': request_id})
        if not request_id or confirmation != token:
            return jsonify(ok=False, code='revisit_confirmation_required',
                           error='This attraction is already included in your itinerary.',
                           confirmationToken=token, existingDay=existing.get('dayNo'),
                           activityName=existing.get('activityName') or activity['activityName']), 409
        activity['intentionalRepeat'] = True
        identity = existing.get('canonicalAttractionId') or existing.get('destinationId')
        if identity:
            activity['canonicalAttractionId'] = identity
    elif confirmation is not None:
        return jsonify(ok=False, error='This repeat-visit confirmation is out of date.'), 409
    if not checkDestinationLimit(current):
        return jsonify(ok=False, error='Itinerary destination limit reached'), 409

    updated = addActivity(current, activity)
    policy = _edit_planning_policy(current, updated['activities'])
    recalculated = recalculateItinerary(
        {**current, **updated, 'geographyPlanningPolicy': policy},
        preserveOrder=True,
        respectDayAssignments=True,
    )
    patch = {
        key: recalculated[key]
        for key in ('activities', 'unscheduledSuggestions', 'scheduledActivityCount',
                    'unscheduledActivityCount', 'dailySchedule', 'totalScheduledMinutes',
                    'paceApplied', 'dailyPlanningWindow', 'tripDays',
                    'tripDateRangeLabel', 'updatedAt', 'nextActivitySeq', 'intercityTransferStatus')
        if key in recalculated
    }
    scheduled = {row.get('activityId'): row for row in patch['activities']}
    for old in current.get('activities') or []:
        if protected_activity(old):
            after = scheduled.get(old.get('activityId'))
            if not after or any(after.get(key) != old.get(key)
                                for key in ('dayNo', 'scheduledStartTime', 'scheduledEndTime')):
                return jsonify(ok=False, error='Adding this visit would change a protected stop.'), 409
    new_id = updated['activities'][-1]['activityId']
    if any(row.get('activityId') not in scheduled for row in current.get('activities') or []):
        return jsonify(ok=False,error='Adding this place would displace another visit. Review the schedule first.'),409
    conflict = _travel_edit_conflict(current, recalculated, new_id)
    if conflict:
        return conflict
    if policy:
        patch['geographyPlanningPolicy'] = policy
    if new_id not in scheduled or scheduled[new_id].get('dayNo') != day:
        return jsonify(ok=False, error='Another visit cannot fit on the selected day.'), 409
    if request_id:
        patch['activityAddReceipts'] = dict(list({**receipts, request_id: {
            'payloadHash': payload_hash, 'activityId': new_id}}.items())[-80:])
    patch['budgetEstimate'] = calculateBudget({**current, **patch})
    saved = updateRecord('itineraries', iid, patch, expected=current)
    if saved is None:
        return jsonify(ok=False, error='Itinerary not found'), 404
    return jsonify(ok=True, itinerary=saved, activities=saved['activities'], budget=saved['budgetEstimate'])



@bp.delete('/itineraries/<iid>/activities/<activity_id>')
@auth_required(['traveller'])
def remove_activity_route(iid, activity_id):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    if _is_package_trip(current):
        return jsonify({'ok': False, 'error': 'Purchased package trips cannot be modified or recalculated.'}), 409
    from services.flexible_planning import commercial_activity
    original = next((row for row in current.get('activities',[])+list(current.get('unscheduledSuggestions') or []) if str(row.get('activityId'))==activity_id),None)
    if not original:return jsonify(ok=False,error='Activity not found.'),404
    if commercial_activity(original):return jsonify(ok=False,error='This protected arrangement cannot be removed here.'),409
    updated = removeActivity(current, activity_id)
    recalculated = recalculateItinerary(
        {**current, **updated},
        preserveOrder=True,
        respectDayAssignments=True,
    )
    from services.flexible_planning import preservation_error
    error=preservation_error(current,recalculated,activity_id)
    if error:return jsonify(ok=False,error=error),409
    patch = {key: recalculated[key] for key in (
        'activities', 'unscheduledSuggestions', 'scheduledActivityCount',
        'unscheduledActivityCount', 'dailySchedule', 'totalScheduledMinutes',
        'paceApplied', 'dailyPlanningWindow', 'tripDays',
        'tripDateRangeLabel', 'updatedAt', 'nextActivitySeq', 'intercityTransferStatus') if key in recalculated}
    patch['budgetEstimate'] = calculateBudget({**current, **patch})
    updateRecord('itineraries', iid, patch, expected=current)
    return jsonify({'ok': True, 'itinerary': {**current, **patch}, 'activities': patch['activities'], 'budget': patch['budgetEstimate']})


def _same_day_visit(visit, day):
    name = visit.get('activityName') or 'This place'
    return jsonify(ok=False, code='duplicate_attraction_day',
                   error=f'{name} is already included on Day {day}. '
                         'You cannot add the same place twice on the same day. '
                         'Choose another day if you want to visit again.'), 409


@bp.put('/itineraries/<iid>/activities/<activity_id>')
@auth_required(['traveller'])
def update_activity_route(iid, activity_id):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    if _is_package_trip(current):
        return jsonify({'ok': False, 'error': 'Purchased package trips cannot be modified or recalculated.'}), 409
    changes = request.get_json(silent=True) or {}
    from services.itinerary_identity import IDENTITY_FIELDS
    rows = [*current.get('activities', []), *(current.get('unscheduledSuggestions') or [])]
    original = next((row for row in rows if str(row.get('activityId')) == activity_id), None)
    if not isinstance(changes, dict):
        return jsonify(ok=False, error='Invalid activity changes.'), 400
    from services.flexible_planning import commercial_activity, clock, time_text, USER_LOCKS
    expected=changes.pop('expectedItineraryRevision',None)
    if expected is not None and (type(expected) is not int or expected!=int(current.get('itineraryRevision') or 1)):
        return jsonify(ok=False,error='This trip changed. Reopen it before editing.',code='STALE_ITINERARY'),409
    if not original:return jsonify(ok=False,error='Activity not found.'),404
    if original and (commercial_activity(original) or any(
            key in changes and changes[key] != original.get(key)
            for key in (*IDENTITY_FIELDS, 'activityId', 'destinationId'))):
        return jsonify(ok=False, error='Use Add Places to change the attraction or confirm a repeat visit.'), 409
    if original and any(same_attraction({**original, **changes}, row) and not same_attraction(original, row)
                        for row in rows if row is not original):
        return jsonify(ok=False, error='Use Add Places to confirm a repeat visit.'), 409
    if set(changes)-{'dayNo','timeSlot','recommendedDurationMinutes','notes','estimatedCost','fixed'}:
        return jsonify(ok=False,error='Choose supported activity edits.'),409
    try:
        if 'notes' in changes and (not isinstance(changes['notes'],str) or len(changes['notes'])>1000):raise ValueError('Keep notes within 1000 characters.')
        if 'fixed' in changes and type(changes['fixed']) is not bool:raise ValueError('Choose Fixed or Flexible.')
        if 'recommendedDurationMinutes' in changes and (type(changes['recommendedDurationMinutes']) is not int or not 1<=changes['recommendedDurationMinutes']<=1440):raise ValueError('Choose a valid activity duration.')
        if 'estimatedCost' in changes:
            cost = changes['estimatedCost']
            if type(cost) not in (int,float) or not 0<=cost<1000000:raise ValueError('Choose a non-negative cost estimate.')
            changes.update(unitPrice=round(cost,2),pricingUnit='per_group',currency='MYR',costProvenance='user_entered',
                           pricingEvidence=None,priceSourceUrl=None,priceVerifiedAt=None)
        if 'timeSlot' in changes or changes.get('fixed') is True:
            start = clock(changes.get('timeSlot') or original.get('scheduledStartTime') or original.get('timeSlot'))
            duration = changes.get('recommendedDurationMinutes') or original.get('recommendedDurationMinutes') or 90
            if start+duration>=1440:raise ValueError('This activity must finish on the selected day.')
            changes.update(scheduledStartTime=time_text(start),scheduledEndTime=time_text(start+duration))
        if changes.get('fixed') is False:
            changes.update({key:False for key in USER_LOCKS})
            changes['editProvenance']='flexible'
        elif {'timeSlot','recommendedDurationMinutes','notes'} & changes.keys() or changes.get('fixed') is True or 'dayNo' in changes and original.get('scheduledStartTime'):
            changes.update(fixed=True,userEdited=True,editProvenance='user')
    except (ValueError,TypeError,OverflowError) as error:
        return jsonify(ok=False,error=str(error)),400
    if original and 'dayNo' in changes:
        try:
            day = int(str(changes['dayNo']))
            if not 1 <= day <= _trip_days(current):
                raise ValueError()
        except ValueError:
            return jsonify(ok=False, error='Choose a valid trip day.'), 400
        changes['dayNo'] = day
        if str(original.get('dayNo')) != str(day):
            duplicate = next((row for row in rows if row is not original
                              and str(row.get('dayNo')) == str(day)
                              and same_attraction(original, row)), None)
            if duplicate:
                return _same_day_visit(duplicate, day)
    updated = updateActivity(current, activity_id, changes)
    working=updated
    if changes.get('fixed') is False and 'timeSlot' in changes:
        working={**updated,'activities':[{**row,'manualTime':True} if str(row.get('activityId'))==activity_id else row for row in updated.get('activities',[])],
                 'unscheduledSuggestions':[{**row,'manualTime':True} if str(row.get('activityId'))==activity_id else row for row in updated.get('unscheduledSuggestions') or []]}
    policy = _edit_planning_policy(current, updated['activities'])
    recalculated = recalculateItinerary(
        {**current, **working, 'geographyPlanningPolicy': policy},
        preserveOrder=True,
        respectDayAssignments=True,
    )
    patch = {key: recalculated[key] for key in (
        'activities', 'unscheduledSuggestions', 'scheduledActivityCount',
        'unscheduledActivityCount', 'dailySchedule', 'totalScheduledMinutes',
        'paceApplied', 'dailyPlanningWindow', 'tripDays',
        'tripDateRangeLabel', 'updatedAt', 'nextActivitySeq', 'intercityTransferStatus') if key in recalculated}
    if changes.get('fixed') is False:
        for row in patch['activities']:
            if str(row.get('activityId'))==activity_id:row.update({**{key:False for key in USER_LOCKS},'editProvenance':'flexible'})
    conflict = _travel_edit_conflict(current, recalculated, activity_id)
    if conflict:
        return conflict
    if policy:
        patch['geographyPlanningPolicy'] = policy
    scheduled = {row.get('activityId'):row for row in patch['activities']}
    if activity_id not in scheduled:
        return jsonify(ok=False,error='This activity cannot fit on the selected day. Review a different day or time.'),409
    for row in updated.get('activities') or []:
        after = scheduled.get(row.get('activityId'))
        if not after or protected_activity(row) and any(after.get(key)!=row.get(key) for key in ('dayNo','scheduledStartTime','scheduledEndTime')):
            return jsonify(ok=False,error='This edit cannot fit while preserving your other visits and fixed times.'),409
    patch['budgetEstimate'] = calculateBudget({**current, **patch})
    saved = updateRecord('itineraries', iid, patch, expected=current)
    return jsonify({'ok': True, 'itinerary': saved, 'activities': patch['activities'], 'budget': patch['budgetEstimate']})


@bp.post('/itineraries/<iid>/activities/rearrange')
@auth_required(['traveller'])
def rearrange_activity_route(iid):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    if _is_package_trip(current):
        return jsonify({'ok': False, 'error': 'Purchased package trips cannot be modified or recalculated.'}), 409
    command=request.get_json(silent=True) or {}
    ids=command.get('orderedActivityIds') if isinstance(command,dict) else None
    if not isinstance(ids,list) or not all(isinstance(value,str) for value in ids) or len(ids)!=len(set(ids)):
        return jsonify(ok=False,error='Choose a valid activity order.'),400
    expected=command.get('expectedItineraryRevision')
    if expected is not None and (type(expected) is not int or expected!=int(current.get('itineraryRevision') or 1)):
        return jsonify(ok=False,error='This trip changed. Reopen it before rearranging.',code='STALE_ITINERARY'),409
    updated = rearrangeActivity(current, ids)
    recalculated = recalculateItinerary(
        {**current, **updated},
        preserveOrder=True,
        respectDayAssignments=True,
    )
    from services.flexible_planning import preservation_error
    error=preservation_error(current,recalculated)
    if error:return jsonify(ok=False,error=error),409
    patch = {key: recalculated[key] for key in (
        'activities', 'unscheduledSuggestions', 'scheduledActivityCount',
        'unscheduledActivityCount', 'dailySchedule', 'totalScheduledMinutes',
        'paceApplied', 'dailyPlanningWindow', 'tripDays',
        'tripDateRangeLabel', 'updatedAt', 'nextActivitySeq', 'intercityTransferStatus') if key in recalculated}
    patch['budgetEstimate'] = calculateBudget({**current, **patch})
    updateRecord('itineraries', iid, patch, expected=current)
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
    return jsonify({'ok': True, 'budget': budget})


class _AlternativeConflict(ValueError):
    def __init__(self, message, *, timing_preview=None, code='comparison_unavailable', criteria=None):
        super().__init__(message)
        self.timing_preview = timing_preview
        self.code=code
        self.criteria=criteria


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
        patch = history_patch(current, patch)
        ref.update(patch, option=db.write_option(last_update_time=snapshot.update_time))
    except (FailedPrecondition, NotFound) as error:
        raise _AlternativeConflict(stale) from error
    return {**current, **patch}


def _activity_identity(row):
    from services.review_destination import review_destination_id
    return review_destination_id(str(row.get('destinationId') or row.get('place_id') or row.get('id') or ''))


def _activity_options(current):
    from services.recommendation_taxonomy import candidate_concepts, concepts_for, preference_concepts
    profile = current.get('planningPreferences') or {}
    excluded = concepts_for(profile.get('excludedInterests', []))
    preferred = preference_concepts(profile.get('interests', []))
    raw = list(DESTINATIONS)
    if current.get('recommendationGenerationId'):
        snapshot, _ = _recommendation_snapshot(current, {})
    else:
        snapshot = None
    if snapshot:
        raw.extend(snapshot.get('recommendationResults') or snapshot.get('items') or [])
    candidates = {}
    for row in _filter_destination_candidates(raw, current.get('destinationArea')):
        if excluded.intersection(candidate_concepts(row)):
            continue
        enriched = enrich_candidate_pricing(row)
        evidence = enriched.get('pricingEvidence')
        if isinstance(evidence, dict) and evidence.get('applicability') == 'applicable':
            candidates.setdefault(_activity_identity(enriched), enriched)
    return dict(sorted(candidates.items(), key=lambda item: -len(preferred.intersection(candidate_concepts(item[1])))))


def _resolve_activity_alternative(current, data, candidates):
    from services.malaysian_locality import filter_candidates, normalize_destination_scope

    activities = current.get('activities') or []
    requested = data.get('activityId')
    original = next((row for row in activities if row.get('activityId') == requested), None)
    candidate = candidates.get(str(data.get('destinationId') or ''))
    if not original or not candidate or any(
            same_attraction(row, candidate)
            for row in [*activities, *(current.get('unscheduledSuggestions') or [])]):
        raise _AlternativeConflict('Choose an unused replacement for an existing activity.')
    scope = normalize_destination_scope(current.get('destinationArea'))
    if not scope['state'] or not filter_candidates([candidate], scope)[0]:
        raise _AlternativeConflict('The replacement location is not verified for this trip.')
    before = activity_pricing(original, current.get('travellerCount'))
    if original.get('costCategory') not in (None, '', 'admission') or protected_activity(original):
        raise _AlternativeConflict('Only unpaid, incomplete planned admissions can be replaced.')
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
    if protected_activity(slot):
        raise _AlternativeConflict('An already paid or completed visit cannot be replaced.')
    start, old_end = (_parse_time_minutes(slot.get(key)) for key in ('scheduledStartTime', 'scheduledEndTime'))
    try:
        day_date = date.fromisoformat(day.get('dayDate') or day.get('date') or slot.get('dayDate'))
        if not date.fromisoformat(current['startDate'][:10]) <= day_date <= date.fromisoformat(current['endDate'][:10]):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise _AlternativeConflict('The selected day does not match the saved trip dates.') from None
    duration, duration_source = _activity_duration(replacement)
    evidence = candidate.get('pricingEvidence') or {}
    registry_hours = evidence.get('openingHours')
    opening = _activity_opening(
        {**replacement, 'openingHours': registry_hours} if registry_hours else replacement, day_date)
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
    from services.flight_itinerary_adjustment import flight_boundaries, planning_assumptions, _availability
    if current.get('selectedFlight'):
        boundaries = flight_boundaries(current, current['selectedFlight'])
        if not boundaries.get('arrival'):
            raise _AlternativeConflict('Flight arrival timing is needed to verify the replacement visit.')
        availability = _availability(current, boundaries, planning_assumptions())
        bounds = availability['days'].get(day_date.isoformat())
        if not bounds or start < bounds['startMinutes'] or start + duration > bounds['endMinutes']:
            raise _AlternativeConflict('The replacement conflicts with the selected flight window.')
    if any(activity_pricing(row, current.get('travellerCount'))['pricingIssues'] for row in new_day_rows):
        day_patch['estimatedCost'] = None
    return replacement, patch, savings


def _flight_cabin(current):
    flight = current.get('selectedFlight') or {}
    saved = flight.get('requestedTravelClass')
    labels = {'economy': 1, 'premium economy': 2, 'business': 3, 'first': 4, 'first class': 4}
    cabins = {labels.get(str(leg.get('travelClass') or '').strip().lower())
              for leg in [*(flight.get('outboundSegments') or []),*(flight.get('returnSegments') or [])]}
    known = cabins - {None}
    if saved is not None:
        # The server-saved search cabin survives quote expiry; conflicting evidence does not.
        return saved if type(saved) is int and saved in {1, 2, 3, 4} and (not known or known == {saved}) else None
    if len(cabins) == 1 and None not in cabins:
        return next(iter(cabins))
    from modules.fr07_flight_search.routes import _load_quote
    if current.get('flightSearchId'):
        quote = _load_quote(current['flightSearchId'])
        if quote:
            return (quote.get('criteria') or {}).get('travel_class')
    return None


def _flight_comparison_diagnostics(current):
    """Eligibility evidence only; no provider searches, writes or quote repricing."""
    flight = current.get('selectedFlight') or {}
    reasons = []
    if not flight:
        reasons.append('No selected flight is available to compare. Search Flights for this trip.')
    else:
        if protected_activity(flight) or any(current.get(key) for key in (
                'flightBookingId', 'flightPaymentId', 'flightOrderId', 'paymentId', 'paymentRecordId', 'paidTotal')):
            reasons.append('This flight has a paid or booking reference; manage the original arrangement.')
        if current.get('travelMode') != 'flight':
            reasons.append('The saved travel mode is not flight.')
        legs = flight.get('outboundSegments') or []
        if not legs:
            reasons.append('The selected flight is missing its outbound route and dates.')
        else:
            from sequence_contract.validators import flightSearchValidationError
            returns = flight.get('returnSegments') or []
            route = {'departure_id': legs[0].get('departureAirportCode') or '',
                     'arrival_id': legs[-1].get('arrivalAirportCode') or '',
                     'outbound_date': legs[0].get('departureDate') or '',
                     'return_date': returns[0].get('departureDate') if returns else None}
            if flightSearchValidationError(route):
                reasons.append('The selected route or travel dates are invalid or no longer searchable.')
        if current.get('flightCurrency') != 'MYR' or not current.get('flightPriceBasis'):
            reasons.append('The saved flight currency or total-fare price basis is missing.')
        if not current.get('flightCost') or flight.get('price') != current.get('flightCost'):
            reasons.append('The selected flight amount does not match the saved trip estimate.')
        if flight.get('travellerCount') != traveller_count(current.get('travellerCount')):
            reasons.append('The selected flight passenger count is missing or does not match this trip.')
        if _flight_cabin(current) not in {1, 2, 3, 4}:
            reasons.append('The selected cabin class cannot be established from its saved quote or segments.')
    return {'status': 'eligible' if not reasons else 'needs_review', 'reasons': reasons,
            'originalCabin':_flight_cabin(current),
            'explanation': 'Comparable fares must retain the route, dates, cabin, passenger count and complete MYR price basis.'}


def _flight_alternative_options(current):
    """Use existing owned complete quotes only. Discovery never purchases provider searches."""
    from modules.fr07_flight_search.routes import _FLIGHT_QUOTES, _quote_expiry_status, _quote_doc_id
    if _flight_comparison_diagnostics(current)['status'] != 'eligible':
        return []
    saved = retrieveRecord('flight_quotes', filters=[('travellerId', '==', g.uid)], limit=40) or []
    quotes = {}
    for row in saved:
        if not isinstance(row, dict) or not row.get('id') or row.get('travellerId') != g.uid:
            continue
        # Collection reads expose the document ID; FR7 references use the search ID.
        identity = row['id'].removeprefix(_quote_doc_id(g.uid, ''))
        quotes[identity] = {**row, 'id': identity}
    quotes.update({key: row for key, row in _FLIGHT_QUOTES.items() if row.get('travellerId') == g.uid})
    options = []
    for identity, quote in quotes.items():
        if _quote_expiry_status(quote):
            continue
        _FLIGHT_QUOTES[identity] = quote
        rows = list((quote.get('completedOptions') or {}).values()) + list(quote.get('items') or [])
        for row in rows:
            if row.get('quoteCompleteness') == 'complete' and row.get('optionId'):
                options.append({'searchId': identity, 'optionId': row['optionId']})
    return options


def _hotel_baseline_evidence(record):
    """Use only consistent server-validated evidence at the saved MYR amount."""
    from math import isfinite
    accepted = record.get('acceptedPrebookSnapshot') or {}
    selected = record.get('selectedHotel') or record.get('offer') or {}
    validated = record.get('validatedOffer') or {}
    sources = (selected, validated, accepted)
    amount = record.get('hotelCost', selected.get('price'))
    try:
        if isinstance(amount, bool) or not isfinite(float(amount)) or float(amount) <= 0:
            raise ValueError
        for source, field in ((selected, 'price'), (validated, 'price'), (accepted, 'amount')):
            value = source.get(field)
            if value is not None and (isinstance(value, bool) or float(value) != float(amount)):
                raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise _AlternativeConflict('The saved hotel pricing evidence is inconsistent.',code='amount_mismatch') from None
    currencies = {str(row.get('currency')).strip().upper() for row in sources if row.get('currency')}
    if record.get('hotelCurrency'):
        currencies.add(str(record['hotelCurrency']).strip().upper())
    if currencies - {'MYR'}:
        raise _AlternativeConflict('The saved hotel currency evidence is inconsistent.',code='currency_mismatch')
    bases = {row.get('priceBasis') for row in sources if row.get('priceBasis') not in (None, '', 'unknown')}
    taxes = {row.get('taxesAndFeesStatus') for row in sources if row.get('taxesAndFeesStatus') not in (None, '', 'unknown')}
    if bases != {'stay_total'} or taxes != {'included'}:
        raise _AlternativeConflict('A consistent total-stay price with verified included charges is needed.',code='incomplete_stay_total')
    offer = {**selected, **{key: value for key, value in validated.items() if value is not None}}
    criteria = dict(record.get('stayCriteria') or record.get('criteria') or {})
    for key in ('checkin', 'checkout', 'roomQuantity', 'occupancies', 'guestCount'):
        saved, snapshot = criteria.get(key), accepted.get(key)
        if saved not in (None, '', []) and snapshot not in (None, '', []) and saved != snapshot:
            raise _AlternativeConflict('The saved hotel stay evidence is inconsistent.',code='stay_mismatch')
        if saved in (None, '', []) and snapshot not in (None, '', []):
            criteria[key] = snapshot
    occupancies = criteria.get('occupancies') or []
    if occupancies:
        if criteria.get('adults') in (None, ''):
            criteria['adults'] = sum(room.get('adults', 0) for room in occupancies)
        if criteria.get('children') in (None, ''):
            criteria['children'] = sum(len(room.get('children') or []) for room in occupancies)
    if not criteria.get('destination'):
        criteria['destination'] = offer.get('address') or ''
    return criteria


def _hotel_discovery_baseline(current):
    """Resolve a planning-only stay, without releasing any supplier obligation."""
    from modules.fr08_hotel_booking.routes import _quote_document_id, _normalise_occupancies, _hotel_trip_compatibility, _is_expired
    if any(current.get(key) for key in ('hotelPaymentId', 'hotelOrderId', 'paymentId', 'paymentRecordId',
                                       'paidTotal', 'checkoutOrderId', 'purchasedPackages')):
        raise _AlternativeConflict('This hotel is paid or linked to a protected arrangement.',code='protected_arrangement')
    booking_id = current.get('hotelBookingId')
    if booking_id:
        record = retrieveRecord('hotel_bookings', booking_id) or {}
        if (record.get('travellerId') != g.uid or record.get('saveDetailsOnly') is not True
                or record.get('bookingStatus') != 'confirmed'
                or any(record.get(key) for key in ('providerMutationCalled', 'bookingId', 'hotelConfirmationCode',
                                                    'reconciliationRequired', 'verificationRequired'))
                or record.get('itineraryId') not in (None, '', current.get('id'))):
            raise _AlternativeConflict('Only an owned unpaid planning selection can be compared here.',code='protected_or_unowned_selection')
        orders = retrieveRecord('checkout_orders', filters=[('travellerId', '==', g.uid),
                                 ('hotelBookingId', '==', booking_id)], limit=20) or []
        if any(row.get('paymentStatus') == 'paid' or row.get('status') in
               {'paid', 'checkout_open', 'checkout_pending', 'payment_pending', 'payment_mismatch'} for row in orders):
            raise _AlternativeConflict('An active hotel checkout protects this selection.',code='payment_pending')
        if record.get('amountSource') != 'validated_offer' or record.get('hotelCost') != current.get('hotelCost'):
            raise _AlternativeConflict('The original hotel amount cannot be compared.',code='amount_mismatch')
    else:
        identity = current.get('hotelOfferQuoteId')
        record = retrieveRecord('hotel_offer_quotes', _quote_document_id(identity)) if identity else None
        if not record or record.get('travellerId') != g.uid:
            raise _AlternativeConflict('The selected hotel has no owned validated total-stay quote.',code='missing_quote')
        if _is_expired(record):
            raise _AlternativeConflict('The original hotel quote has expired. Revalidate the selected stay in Hotels.',code='expired_quote',criteria=record.get('criteria'))
        original = record.get('offer') or {}
        if original.get('price') != current.get('hotelCost'):
            raise _AlternativeConflict('The original hotel amount cannot be compared.',code='amount_mismatch')
    if protected_activity(current.get('selectedHotel') or {}) or current.get('hotelCurrency') != 'MYR':
        raise _AlternativeConflict('The saved hotel selection is protected or its currency is not MYR.',code='protected_or_currency_mismatch')
    accepted=record.get('acceptedPrebookSnapshot') or {}
    if accepted.get('expiresAt') and _is_expired(accepted):
        raise _AlternativeConflict('The original hotel quote has expired. Revalidate the selected stay in Hotels.',code='expired_quote',criteria=record.get('stayCriteria'))
    criteria = _hotel_baseline_evidence(record)
    if _hotel_trip_compatibility(current, criteria)[1]:
        raise _AlternativeConflict('The stay dates or destination do not match this trip.',code='dates_or_location_mismatch')
    try:
        rooms = _normalise_occupancies(criteria, criteria['roomQuantity'])
        if sum(room['adults'] + len(room.get('children') or []) for room in rooms) != traveller_count(current.get('travellerCount')):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise _AlternativeConflict('The guest or room configuration cannot be compared with this trip.',code='occupancy_mismatch') from None
    return criteria


def _hotel_comparison_diagnostics(current):
    try:
        criteria=_hotel_discovery_baseline(current)
        return {'status':'eligible','reasons':[],'reasonCode':None,'searchCriteria':criteria}
    except _AlternativeConflict as error:
        defaults={'destination':current.get('destinationArea'),'checkin':current.get('startDate'),
                  'checkout':current.get('endDate'),'adults':traveller_count(current.get('travellerCount'))}
        known=error.criteria or current.get('hotelStayCriteria') or {}
        criteria={**defaults,**{key:known[key] for key in ('destination','checkin','checkout','guestNationality') if known.get(key)}}
        from modules.fr08_hotel_booking.routes import _normalise_occupancies
        try:
            rooms=_normalise_occupancies(known,known.get('roomQuantity'))
            criteria.update(occupancies=rooms,roomQuantity=len(rooms),adults=sum(room['adults'] for room in rooms),
                            children=sum(len(room.get('children') or []) for room in rooms))
        except (ValueError,TypeError,KeyError):
            pass  # Missing configuration needs explicit confirmation in Hotels, never invented child ages.
        return {'status':'needs_review','reasons':[str(error)],'reasonCode':error.code,'nextAction':'search_hotels',
                'searchCriteria':criteria}
    except Exception:
        return {'status':'unavailable','reasons':['The hotel quote store is unavailable. Try again later.'],
                'reasonCode':'storage_unavailable'}


def _resolve_hotel_rate(current, data):
    from modules.fr08_hotel_booking.routes import _resolve_quote, _normalise_occupancies, _offer_matches_occupancies
    from services.malaysian_locality import normalize_destination_scope
    criteria = _hotel_discovery_baseline(current)
    quote, error, _ = _resolve_quote({'quoteId': data.get('hotelOfferQuoteId')}, str(data.get('offerId') or ''))
    if error:
        raise _AlternativeConflict(error, code='expired_quote' if 'expired' in error else 'invalid_quote')
    proposed = quote.get('criteria') or {}
    keys = ('checkin', 'checkout', 'roomQuantity')
    if any(proposed.get(key) != criteria.get(key) for key in keys):
        raise _AlternativeConflict('Compare the same hotel dates and room count.')
    rooms = _normalise_occupancies(criteria, criteria['roomQuantity'])
    if _normalise_occupancies(proposed, proposed['roomQuantity']) != rooms:
        raise _AlternativeConflict('Compare identical adult/child room occupancy.')
    offer = quote.get('offer') or {}
    location = normalize_destination_scope(offer.get('address'))
    destination = normalize_destination_scope(current.get('destinationArea'))
    if (not location.get('state') or location['state'] != destination.get('state')
            or location.get('city') and destination.get('city') and location['city'] != destination['city']):
        raise _AlternativeConflict('The hotel location could not be verified for this trip.')
    if (quote.get('source') != 'liteapi' or offer.get('priceBasis') != 'stay_total'
            or offer.get('priceStatus') != 'available' or offer.get('currency') != 'MYR'
            or offer.get('taxesAndFeesStatus') != 'included' or offer.get('roomQuantity') != criteria['roomQuantity']
            or not _offer_matches_occupancies(offer, rooms)):
        raise _AlternativeConflict('A complete comparable MYR hotel rate is required.')
    selected = {**offer, 'planningOnly': True, 'transactionMode': 'planning_reference'}
    patch = {'selectedHotel': selected, 'hotelOfferQuoteId': quote['quoteId'], 'hotelBookingId': None,
             'hotelCost': offer.get('price'), 'hotelCurrency': 'MYR', 'accommodationChoice': 'paid_hotel',
             'hotelSelectionStatus': 'selected', 'hotelStayCriteria': proposed}
    comparison = {key: criteria.get(key) for key in ('checkin', 'checkout', 'adults', 'children', 'occupancies', 'roomQuantity')}
    trusted = {'name': offer.get('name'), 'roomName': offer.get('roomName'), 'address': offer.get('address'),
               'price': offer.get('price'), 'currency': 'MYR', 'source': 'liteapi',
               'hotelOfferQuoteId': quote['quoteId'], 'offerId': offer.get('offerId'),
               'selectedHotel': selected, 'comparisonCriteria': comparison, '_validatedAlternative': True}
    return trusted, patch, 'hotel-rate:' + quote['quoteId'], {**current, '_hotelComparisonCriteria': comparison}


@bp.post('/itineraries/<iid>/lower-cost-alternatives/discover')
@auth_required(['traveller'])
def discover_cost_alternatives(iid):
    current = _own(iid)
    if not current:
        return jsonify(ok=False, error='Itinerary not found'), 404
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload,dict):
        return jsonify(ok=False,error='Choose valid search settings.'),400
    kind = payload.get('category')
    if kind not in {'flight', 'hotel'} or payload.get('providerSearchConfirmed') is not True:
        return jsonify(ok=False, error='Confirm a flight or hotel provider search.'), 400
    from services.transaction_reliability import normalize_attempt_id
    try:
        search_request_id = normalize_attempt_id(payload.get('searchRequestId'), 'searchRequestId')
    except ValueError as error:
        return jsonify(ok=False, error=str(error)), 400
    if not _can_replan(current) or calculateBudget(current).get('overBy', 0) <= 0:
        return jsonify(ok=False, error='This trip does not need an eligible budget replacement.'), 409
    state = _alternative_state(current)
    if payload.get('stateVersion') != state:
        return jsonify(ok=False, error='This trip changed. Refresh alternatives first.', code='STALE_ALTERNATIVE'), 409
    from services.budget_provider_discovery import run_search, flight_search, hotel_search, flight_comparison, DiscoveryError
    comparison=None
    try:
        if kind == 'hotel':
            criteria = _hotel_discovery_baseline(current)
            search = lambda invoke: hotel_search(criteria, invoke)
        else:
            if (_flight_comparison_diagnostics(current)['status'] != 'eligible'
                    or protected_activity(current.get('selectedFlight') or {})
                    or any(current.get(key) for key in ('flightBookingId', 'flightPaymentId', 'flightOrderId',
                                                        'paymentId', 'paymentRecordId', 'paidTotal'))):
                raise _AlternativeConflict('The selected flight cannot safely be compared.')
            comparison=flight_comparison(current,payload.get('cabinComparison','same_cabin'),payload.get('comparisonCabin'))
            search = lambda invoke: flight_search(current, invoke, comparison)
        result = run_search(g.uid, current, kind, state, search, request_id=search_request_id,comparison=comparison)
    except (DiscoveryError, _AlternativeConflict) as error:
        logging.getLogger(__name__).info('budget_discovery_blocked category=%s reason=%s', kind, str(error))
        diagnostic={'status':'needs_review','reasonCode':getattr(error,'code','invalid_cabin_comparison'),
                    'reasons':[str(error)],'nextAction':'search_hotels' if kind=='hotel' else 'search_flights'}
        return jsonify(ok=False, error=f'{kind.title()} search has not run. {error}',
                       code='DISCOVERY_COMPARISON_UNAVAILABLE',eligibility=diagnostic,providerReached=False), 409
    except Exception:
        return jsonify(ok=False, error='Search state could not be verified. No automatic retry was made.'), 503
    return jsonify(ok=True, search=result, stateVersion=state)


def _resolve_cost_alternative(kind, data, current):
    """Resolve existing owned references; never accept client replacement prices."""
    if kind == 'flight':
        if protected_activity(current.get('selectedFlight') or {}) or any(current.get(key) for key in (
                'flightBookingId', 'flightPaymentId', 'flightOrderId', 'paymentId', 'paymentRecordId', 'paidTotal')):
            raise _AlternativeConflict('A paid or booked flight cannot be replaced here. Manage the original arrangement.')
        if current.get('travelMode') != 'flight' or not (current.get('selectedFlight') or {}).get('outboundSegments'):
            raise _AlternativeConflict('This itinerary has no comparable selected flight.')
        from modules.fr07_flight_search.routes import (
            _quote_item, _flight_trip_date_error, _flight_conflicts, _sanitize_flight_snapshot, _return_segments,
        )
        quote, option, error = _quote_item({
            'searchId': data.get('searchId') or data.get('flightSearchId'),
            'optionId': data.get('optionId') or data.get('flightOptionId'),
        })
        if error or not quote or not option:
            raise _AlternativeConflict('Flight reference is missing, invalid or expired. Search again.',
                                       code='expired_quote' if error == 'flight_quote_expired' else 'invalid_quote')
        criteria = quote.get('criteria') or {}
        selected = current.get('selectedFlight') or {}
        from services.budget_provider_discovery import flight_comparison, DiscoveryError
        try:
            comparison=flight_comparison(current,data.get('cabinComparison','same_cabin'),criteria.get('travel_class'))
        except DiscoveryError as error:
            raise _AlternativeConflict(str(error)) from None
        if ((criteria.get('travel_class') is None)
                or criteria.get('traveller_count') != traveller_count(current.get('travellerCount'))
                or option.get('travellerCount') != criteria.get('traveller_count')
                or option.get('quoteCompleteness') != 'complete'
                or option.get('budgetEligible') is False
                or (criteria.get('return_date') and not _return_segments(option, criteria))):
            raise _AlternativeConflict('Flight quote is incomplete or its traveller count no longer matches this trip.', code='incomplete_fare_or_passengers')
        for field, segments, segment_field in (
                ('outbound_date', 'outboundSegments', 'departureDate'),
                ('return_date', 'returnSegments', 'departureDate')):
            old_segments = selected.get(segments) or []
            old_date = old_segments[0].get(segment_field) if old_segments else None
            if (criteria.get(field) or None) != (old_date or None):
                raise _AlternativeConflict('Compare flight prices for the same travel dates.', code='date_mismatch')
        for field, segment, airport in (
                ('departure_id', 0, 'departureAirportCode'),
                ('arrival_id', -1, 'arrivalAirportCode')):
            old_segments = selected.get('outboundSegments') or []
            if not old_segments or criteria.get(field) != old_segments[segment].get(airport):
                raise _AlternativeConflict('Compare flight prices for the same route.', code='route_mismatch')
        if _flight_trip_date_error(current, option):
            raise _AlternativeConflict('The flight dates do not match this trip.')
        if selected.get('price') != current.get('flightCost'):
            raise _AlternativeConflict('The existing flight price is not comparable.')
        # A quote's cabin and segment evidence must agree; a client field cannot grant a downgrade.
        if _flight_cabin({'selectedFlight':{**option,'requestedTravelClass':criteria['travel_class']}})!=criteria['travel_class']:
            raise _AlternativeConflict('The provider cabin evidence conflicts with the selected comparison.')
        trusted = _sanitize_flight_snapshot({**option, 'searchId': quote['id'],
                    'travellerCount': criteria['traveller_count'], '_validatedAlternative': True})
        trusted.update(cabinComparison=comparison['mode'],cabin=comparison)
        patch = {
            'selectedFlight': _sanitize_flight_snapshot({**option, 'requestedTravelClass':criteria['travel_class'],'flightSearchId': quote['id'],
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
        from services.flight_itinerary_adjustment import flight_selection_change_patch
        patch.update(flight_selection_change_patch(current, patch['selectedFlight']))
        if current.get('activities') or current.get('planningBlocks'):
            from services.flight_itinerary_adjustment import build_preview, fingerprint
            schedule = build_preview({**current, **patch}, patch['selectedFlight'], g.uid, 'budget-preview')
            reason = (schedule.get('reason') or 'No feasible sightseeing plan fits this flight.'
                      if not schedule['canApply'] or current.get('activities') and not schedule['after'].get('activities')
                      else 'This flight cannot retain all planned visits safely. Review the flight or trip dates first.'
                      if schedule['newlyUnscheduled'] else None)
            if reason:
                raise _AlternativeConflict(reason, timing_preview={
                    'title': f"{trusted.get('airline') or 'Flight'} · requires schedule adjustment", 'reason': reason,
                    'reference':f"flight:{quote['id']}:{patch['flightOptionId']}",
                    'data':{**trusted,'searchId':quote['id'],'optionId':patch['flightOptionId']},
                    'originalFlight':selected,'proposedFlight':patch['selectedFlight'],
                    'affectedDays':sorted({row.get('dayNo') for row in current.get('activities',[]) if row.get('dayNo') and
                        any(change.get('activityId')==row.get('activityId') and change.get('kind')!='retained' for change in schedule.get('changes',[]))}),
                    'remainingConflicts':schedule.get('remainingConflicts',[]),
                    'currentCost': current.get('flightCost'), 'proposedCost': option.get('price'),
                    'currency': 'MYR', 'canApply': False, 'itineraryChanges': schedule.get('changes') or [],
                } if _alternative_savings('flight', trusted, current) is not None else None, code='schedule_conflict')
            patch.update({key: schedule['after'][key] for key in (
                'activities', 'dailySchedule', 'unscheduledSuggestions', 'scheduledActivityCount', 'unscheduledActivityCount', 'travelDayPreferences'
            ) if key in schedule['after']})
            patch.update(flightAdjustmentStatus='applied', flightAdjustmentFlightFingerprint=fingerprint(patch['selectedFlight']),
                         flightAdjustmentAssumptions=schedule['assumptions'], flightAdjustmentReviewReason=None)
            trusted['itineraryChanges'] = schedule['changes']
            trusted['requiresScheduleAdjustment']=any(change.get('kind')=='moved' for change in schedule['changes'])
        reference = f"flight:{quote['id']}:{patch['flightOptionId']}"
        return trusted, patch, reference, current
    if kind == 'hotel' and data.get('hotelOfferQuoteId'):
        return _resolve_hotel_rate(current, data)
    if kind == 'hotel':
        from modules.fr08_hotel_booking.routes import _hotel_trip_compatibility, _is_expired
        from services.malaysian_locality import normalize_destination_scope
        booking_id = str(data.get('hotelBookingId') or '').strip()
        booking = retrieveRecord('hotel_bookings', booking_id) if booking_id else None
        patch, error = _trusted_hotel_update(current, {'hotelBookingId': booking_id}, booking=booking or {})
        if error:
            raise _AlternativeConflict(error)
        criteria = booking.get('stayCriteria') or {}
        old_booking = retrieveRecord('hotel_bookings', current.get('hotelBookingId')) if current.get('hotelBookingId') else None
        if any(record and (record.get('bookingStatus') == 'paid' or record.get('providerMutationCalled') is True)
               for record in (booking, old_booking)):
            raise _AlternativeConflict('Paid or supplier-booked stays must be managed through the original booking.')
        if any(current.get(key) for key in ('hotelPaymentId', 'hotelOrderId', 'paymentId', 'paymentRecordId', 'paidTotal')):
            raise _AlternativeConflict('Paid or pending hotel arrangements cannot be replaced here.')
        for record in (booking, old_booking):
            if record and (protected_activity(record.get('selectedHotel') or {})
                           or record.get('bookingId') or record.get('hotelConfirmationCode')
                           or record.get('reconciliationRequired') or record.get('verificationRequired')):
                raise _AlternativeConflict('Supplier-linked hotel arrangements cannot be replaced here.')
        for record, reference in ((booking, booking_id), (old_booking, current.get('hotelBookingId'))):
            if record and record.get('saveDetailsOnly') is True and record.get('itineraryId') not in (None, '', current.get('id')):
                raise _AlternativeConflict('The hotel selection belongs to another trip.')
            if reference and record:
                orders = retrieveRecord('checkout_orders', filters=[
                    ('travellerId', '==', g.uid), ('hotelBookingId', '==', reference),
                ], limit=20) or []
                if any(order.get('quoteType') == 'hotel' and (order.get('paymentStatus') == 'paid'
                       or order.get('status') in {'paid', 'checkout_open', 'checkout_pending', 'payment_pending',
                                                 'payment_mismatch'})
                       for order in orders):
                    raise _AlternativeConflict('An active or paid hotel checkout must be managed through the original selection.')
        snapshot = booking.get('acceptedPrebookSnapshot') or {}
        if booking.get('saveDetailsOnly') is True and (
                snapshot.get('id') != booking.get('acceptedPrebookSnapshotId')
                or not snapshot.get('id') or snapshot.get('status') != 'accepted' or _is_expired(snapshot)
                or snapshot.get('priceBasis') != 'stay_total' or snapshot.get('currency') != 'MYR'
                or snapshot.get('amount') != booking.get('hotelCost')):
            raise _AlternativeConflict('The validated replacement hotel price expired or no longer matches.')
        old_criteria = (old_booking or {}).get('stayCriteria') or {}
        _, old_error = _trusted_hotel_update(current, {'hotelBookingId': current.get('hotelBookingId')}, booking=old_booking or {})
        for record in (booking, old_booking):
            selected = (record or {}).get('selectedHotel') or {}
            accepted = (record or {}).get('acceptedPrebookSnapshot') or {}
            if (accepted.get('priceBasis') or selected.get('priceBasis')) != 'stay_total' or selected.get('currency') not in (None, 'MYR'):
                raise _AlternativeConflict('Hotel total-stay currency and price basis must match.')
            if (accepted.get('taxesAndFeesStatus') or selected.get('taxesAndFeesStatus')) != 'included':
                raise _AlternativeConflict('A comparable stay total including known taxes and fees is required.')
            if selected.get('roomQuantity') not in (None, (record.get('stayCriteria') or {}).get('roomQuantity')):
                raise _AlternativeConflict('Hotel room counts do not match.')
            if record.get('saveDetailsOnly') and accepted.get('amount') != record.get('hotelCost'):
                raise _AlternativeConflict('Hotel total no longer matches the accepted stay price.')
        required = ('checkin', 'checkout', 'adults', 'roomQuantity')
        from modules.fr08_hotel_booking.routes import _normalise_occupancies
        try:
            rooms = _normalise_occupancies(criteria, criteria.get('roomQuantity'))
            guests = sum(room['adults'] + len(room.get('children') or []) for room in rooms)
            if guests != traveller_count(current.get('travellerCount')):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise _AlternativeConflict('Hotel room occupancy must match the trip traveller count.') from None
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
        old_scope = normalize_destination_scope(old_criteria.get('destination'))
        if (not compatible or _hotel_trip_compatibility(current, criteria)[1]
                or not stay_scope.get('resolved') or not trip_scope.get('resolved')
                or (stay_scope.get('state'), stay_scope.get('city')) != (old_scope.get('state'), old_scope.get('city'))):
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


def _flight_comparison_identity(flight, cabin=None):
    legs = tuple(tuple(row.get(key) for key in ('departureAirportCode', 'arrivalAirportCode', 'flightNumber',
                 'departureDate', 'departureTime', 'arrivalDate', 'arrivalTime'))
                 for name in ('outboundSegments', 'returnSegments') for row in flight.get(name) or [])
    return (legs, cabin or flight.get('requestedTravelClass'), flight.get('price'))


def _comparison_searches(current, search_ids, cabin_settings):
    """Read submitted searches by exact ID, never infer a fresh search from cached quotes."""
    summaries, references = {}, {'flight': [], 'hotel': []}
    for kind in references:
        summary = {'searchStatus': 'not_started', 'providerReached': None, 'requestsAttempted': 0,
                   'reasonCode': 'search_not_started'}
        identity = search_ids.get(kind)
        if identity:
            record = (retrieveRecord('budget_alternative_searches', identity)
                      if isinstance(identity, str) and len(identity) <= 200 and '/' not in identity else None)
            result = (record or {}).get('result') or {}
            if (record and record.get('travellerId') == g.uid and record.get('tripId') == current['id']
                    and record.get('stateVersion') == _alternative_state(current) and record.get('category') == kind
                    and (kind != 'flight' or result.get('comparison', record.get('comparison')) == cabin_settings)):
                summary = {key: result[key] for key in ('providerReached', 'requestsAttempted', 'candidateCount',
                    'validQuoteCount', 'rejectedCount', 'rejectionCounts', 'failureCode', 'retryAt', 'expiresAt',
                    'outboundCandidateCount', 'returnCandidateCount') if key in result}
                summary.update(searchStatus=record['status'], searchId=identity,
                               reasonCode=result.get('failureCode'), cheaperCandidateCount=0, timingConflictCount=0)
                if record['status'] == 'completed':
                    references[kind] = [row for row in result.get('references', []) if isinstance(row, dict)]
            else:
                summary.update(searchStatus='needs_review', reasonCode='search_mismatch')
        summaries[kind] = summary
    return summaries, references


@bp.post('/itineraries/<iid>/lower-cost-alternatives')
@auth_required(['traveller'])
def lower_cost_alternatives(iid):
    current = _own(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    if _is_package_trip(current):
        return jsonify({'ok': False, 'error': 'Purchased package trips cannot be modified or recalculated.'}), 409
    payload=request.get_json(silent=True) or {}
    if not isinstance(payload,dict):
        return jsonify(ok=False,error='Choose valid comparison settings.'),400
    if not isinstance(payload.get('searchIds', {}), dict):
        return jsonify(ok=False,error='Choose valid saved searches.'),400
    from services.budget_provider_discovery import flight_comparison,DiscoveryError
    cabin_settings=None
    if current.get('selectedFlight') and _flight_cabin(current) in {1,2,3,4}:
        try:
            cabin_settings=flight_comparison(current,payload.get('cabinComparison','same_cabin'),payload.get('comparisonCabin'))
        except DiscoveryError as error:
            return jsonify(ok=False,error=str(error)),400
    budget = calculateBudget(current)
    if budget.get('overBy', 0) <= 0:
        return jsonify(ok=True, budget=budget, alternatives=[], planningAlternatives=[],
                       stateVersion=_alternative_state(current),
                       budgetReplanOptions=budget_replan_options(current, budget) if _can_replan(current) else None)
    flight_advice = None
    try:
        flights = _flight_alternative_options(current)
    except Exception:
        flights = []
        flight_advice = 'The flight provider or quote store could not verify comparable fares. Try searching again.'

    hotels = []
    if (current.get('accommodationChoice') == 'paid_hotel' and current.get('hotelBookingId')
            and current.get('hotelCurrency') == 'MYR' and current.get('hotelCost')):
        try:
            owned = retrieveRecord('hotel_bookings', filters=[('travellerId', '==', g.uid)], limit=40) or []
        except Exception:
            owned = []
        hotels = [{'hotelBookingId': row['id']} for row in owned
                  if row.get('id') and row['id'] != current['hotelBookingId']
                  and row.get('bookingStatus') in {'confirmed', 'paid'}]

    hotel_diagnostics=_hotel_comparison_diagnostics(current)
    try:
        if hotel_diagnostics['status']!='eligible':
            raise _AlternativeConflict('The original hotel selection needs review.')
        cached = retrieveRecord('hotel_offer_quotes', filters=[('travellerId', '==', g.uid)], limit=40) or []
        hotels += [{'hotelOfferQuoteId': row['quoteId'], 'offerId': (row.get('offer') or {}).get('offerId')}
                   for row in cached if row.get('quoteId')]
    except Exception:
        pass
    searches, searched = _comparison_searches(current, payload.get('searchIds', {}), cabin_settings)
    flights = searched['flight'] + flights
    hotels = searched['hotel'] + hotels
    budget = calculateBudget(current)
    alternatives = []
    seen = set()
    duplicate_count = 0
    travel_rejections = {}
    timing_previews = []
    timing_seen=set()
    category_rejections={'flight':{},'hotel':{}}
    for kind, options in (('flight', flights), ('hotel', hotels)):
        checked = set()
        search_keys = {json.dumps(row, sort_keys=True) for row in searched[kind]}
        for option in options:
            option_key = json.dumps(option, sort_keys=True)
            if option_key in checked:
                duplicate_count += 1
                continue
            checked.add(option_key)
            from_search = option_key in search_keys
            if kind=='flight' and cabin_settings:
                option={**option,'cabinComparison':cabin_settings['mode']}
                # A comparison searches one chosen cabin within the unchanged two-call cap.
                from modules.fr07_flight_search.routes import _load_quote
                quote=_load_quote(option.get('searchId')) or {}
                if (quote.get('criteria') or {}).get('travel_class')!=cabin_settings['comparisonCabin']:
                    if not from_search:
                        continue
            try:
                trusted, _, reference, comparison = _resolve_cost_alternative(kind, option, current)
            except Exception as error:
                reason = str(error) if isinstance(error, _AlternativeConflict) else 'Incomplete comparison metadata.'
                travel_rejections[reason] = travel_rejections.get(reason, 0) + 1
                category_rejections[kind][reason]=category_rejections[kind].get(reason,0)+1
                if from_search:
                    codes = searches[kind].setdefault('comparisonRejectionCounts', {})
                    code = getattr(error, 'code', 'comparison_unavailable')
                    codes[code] = codes.get(code, 0) + 1
                if (kind == 'flight' and isinstance(error, _AlternativeConflict)
                        and error.timing_preview
                        and (error.timing_preview.get('proposedCost') or float('inf')) < current.get('flightCost', 0)):
                    timing_key=_flight_comparison_identity(error.timing_preview['proposedFlight'])
                    if timing_key not in timing_seen:
                        timing_seen.add(timing_key)
                        timing_previews.append(error.timing_preview)
                        if from_search:
                            searches[kind]['timingConflictCount'] += 1
                            searches[kind]['cheaperCandidateCount'] += 1
                continue
            savings = _alternative_savings(kind, trusted, comparison)
            if savings is None:
                reason = 'No lower verified MYR total with the same passenger count and price basis.'
                travel_rejections[reason] = travel_rejections.get(reason, 0) + 1
                category_rejections[kind][reason] = category_rejections[kind].get(reason, 0) + 1
                if from_search:
                    codes = searches[kind].setdefault('comparisonRejectionCounts', {})
                    codes['not_cheaper'] = codes.get('not_cheaper', 0) + 1
                continue
            if kind == 'flight':
                identity = _flight_comparison_identity(trusted, trusted.get('cabin',{}).get('comparisonCabin'))
            else:
                selection = trusted.get('selectedHotel') or {}
                identity = (selection.get('hotelId'), selection.get('offerId')) if selection.get('offerId') else reference
            key = (kind, trusted.get('source'), identity)
            if key in seen:
                duplicate_count += 1
                continue
            seen.add(key)
            if from_search:
                searches[kind]['cheaperCandidateCount'] += 1
            original = current.get('selectedFlight' if kind == 'flight' else 'selectedHotel') or {}
            name = trusted.get('airline' if kind == 'flight' else 'name') or kind.title()
            original_name = original.get('airline' if kind == 'flight' else 'name') or f'selected {kind}'
            comparison_basis = (('Explicit cabin downgrade; same travel dates, route and traveller count.'
                                 if trusted.get('cabin',{}).get('cabinDowngrade') else 'Same travel dates, route, cabin and traveller count.') if kind == 'flight'
                                else 'Same stay dates, guests and rooms.')
            alternatives.append({
                'alternativeType': kind, 'alternativeId': reference, 'canApply': True, 'isAdvisory': False,
                'title': f'Lower-cost {kind}: {name}',
                'description': f'Replace {original_name}. {comparison_basis}',
                'estimatedSavings': savings, 'currentEstimatedCost': current[f'{kind}Cost'],
                'replacementEstimatedCost': trusted['price'],
                'source': 'SerpApi planning fare' if kind == 'flight' and trusted.get('source') == 'serpapi'
                else trusted.get('source'),
                'data': {key: value for key, value in trusted.items() if key != '_validatedAlternative'},
                'comparisonStatus':'requires_schedule_adjustment' if trusted.get('requiresScheduleAdjustment') else 'ready_to_preview',
                'originalSelection':original,
            })
    for summary in searches.values():
        if summary['searchStatus'] != 'completed':
            continue
        codes = summary.get('comparisonRejectionCounts', {})
        summary['reasonCode'] = ('cheaper_offers' if summary['cheaperCandidateCount'] > summary['timingConflictCount'] else
            'schedule_conflict' if summary['timingConflictCount'] else
            'expired_quote' if codes.get('expired_quote') else
            'evidence_unavailable' if summary.get('candidateCount') is None else
            'no_offers' if summary.get('candidateCount') == 0 else
            'no_cheaper_comparable_offers' if codes.get('not_cheaper') else 'quotes_rejected')
    activity_items = []
    rejection_reasons = {}
    activities = current.get('activities') or []
    try:
        candidates = _activity_options(current) if activities else {}
    except Exception:
        candidates = {}
    if not current.get('dailySchedule'):
        activity_advice = 'A saved visit time and comparable pricing unit are needed; savings cannot be calculated.'
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
                    'source': replacement.get('priceSourceUrl'),
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
        if 'pricing unit' not in activity_advice:
            activity_advice += ' A comparable pricing unit is required.'

    alternatives = sorted(activity_items + alternatives, key=lambda item: -item['estimatedSavings'])
    for alternative in alternatives:
        alternative['stateVersion'] = _alternative_state(current)
        alternative['remainingOverBy'] = round(max(0, budget['overBy'] - alternative['estimatedSavings']), 2)
    return jsonify({
        'ok': True, 'budget': budget, 'alternatives': alternatives,
        'planningAlternatives': planning_alternatives(current, budget) if _can_replan(current) else [],
        'stateVersion': _alternative_state(current),
        'activityAlternativeStatus': 'available' if activity_items else 'priced_replacement_unavailable',
        'activityAdvice': None if activity_items else activity_advice,
        'flightComparison': _flight_comparison_diagnostics(current),
        'cabinComparison':cabin_settings,
        'hotelComparison':hotel_diagnostics,
        'searches': searches,
        'categoryRejectionCounts':category_rejections,
        'travelRejectionCounts': travel_rejections,
        'flightTimingPreviews': timing_previews,
        'flightCandidateCount': len(flights),
        'hotelCandidateCount':len(hotels),
        'flightAdvice': (
            flight_advice or ' '.join(_flight_comparison_diagnostics(current)['reasons']) or 'No cheaper complete flight quote matched this trip. Search Flights for more options.'
            if current.get('selectedFlight') and not any(item['alternativeType'] == 'flight' for item in alternatives)
            else None
        ),
        'hotelAdvice': (
            'No cheaper validated hotel selection matched these dates, guests and rooms. Use Hotels to validate another stay.'
            if current.get('hotelBookingId') and not any(item['alternativeType'] == 'hotel' for item in alternatives)
            else None
        ),
        'budgetReplanOptions': budget_replan_options(current, budget) if _can_replan(current) else None,
        'activityCandidateCount': len(candidates),
        'duplicateAlternativeCount': duplicate_count,
        'activityRejectionCounts': rejection_reasons,
    })


def _can_replan(trip):
    return (not _is_package_trip(trip)
            and str(trip.get('status') or '').lower() not in {'completed', 'cancelled', 'generating'})


@bp.get('/itineraries/<iid>/budget-replan')
@auth_required(['traveller'])
def budget_replan_state(iid):
    current = _own(iid)
    if not current:
        return jsonify(ok=False, error='Itinerary not found'), 404
    budget = calculateBudget(current)
    return jsonify(ok=True, budget=budget, stateVersion=_alternative_state(current),
                   planningAlternatives=planning_alternatives(current, budget) if _can_replan(current) else [],
                   flightComparison=_flight_comparison_diagnostics(current),
                   hotelComparison=_hotel_comparison_diagnostics(current),
                   budgetReplanOptions=budget_replan_options(current, budget) if _can_replan(current) else None)


@bp.post('/itineraries/<iid>/budget-replan/preview')
@bp.post('/itineraries/<iid>/budget-replan/apply')
@auth_required(['traveller'])
def budget_replan(iid):
    current = _own(iid)
    if not current:
        return jsonify(ok=False, error='Itinerary not found'), 404
    if not _can_replan(current):
        return jsonify(ok=False, error='This itinerary cannot be replanned.'), 409
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(ok=False, error='Choose valid budget changes.'), 400
    changes = payload.get('changes')
    state = _alternative_state(current)
    if payload.get('stateVersion') not in (None, state):
        return jsonify(ok=False, code='STALE_BUDGET_PLAN',
                       error='This trip changed. Reopen budget options to review the current costs.'), 409
    try:
        patch, preview = preview_budget_replan(current, changes)
    except ValueError as error:
        return jsonify(ok=False, error=str(error)), 409
    token = _alternative_state({'action': 'budget-replan', 'owner': g.uid, 'trip': iid,
                                'state': state, 'changes': changes})
    if request.path.endswith('/preview'):
        return jsonify(ok=True, **preview, previewToken=token)
    if payload.get('confirmed') is not True or payload.get('previewToken') != token:
        return jsonify(ok=False, error='Review and confirm a current budget preview.'), 409
    saved = updateRecord('itineraries', iid, patch, expected=current)
    if saved is None:
        return jsonify(ok=False, error='Itinerary not found'), 404
    return jsonify(ok=True, itinerary=saved, budget=saved['budgetEstimate'])


@bp.post('/itineraries/<iid>/lower-cost-alternatives/preview')
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
                if kind == 'flight' else (current.get('hotelOfferQuoteId') == patch['hotelOfferQuoteId'] if patch.get('hotelOfferQuoteId')
                      else current.get('hotelBookingId') == patch.get('hotelBookingId'))
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
    if request.path.endswith('/preview'):
        return jsonify(ok=True, before=calculateBudget(current), budget=patch['budgetEstimate'],
                       estimatedReduction=savings, dailySchedule=patch.get('dailySchedule', current.get('dailySchedule', [])),
                       stateVersion=_alternative_state(current), itineraryChanges=trusted.get('itineraryChanges', []),
                       originalSelection=current.get('selectedFlight' if kind=='flight' else 'selectedHotel'),
                       proposedSelection=trusted,cabinComparison=trusted.get('cabin'))
    try:
        updated = _commit_cost_alternative(iid, current, patch)
        if not updated:
            raise RuntimeError('No updated itinerary returned')
    except _AlternativeConflict as error:
        return jsonify({'ok': False, 'error': str(error), 'code': 'STALE_ALTERNATIVE'}), 409
    except Exception:
        return jsonify({'ok': False, 'error': 'The itinerary update could not be confirmed. Reload the trip before trying again.'}), 503
    return jsonify({'ok': True, 'itinerary': updated, 'budget': patch['budgetEstimate'], 'applied': applied})


@bp.get('/personalised-trips/status')
@auth_required(['traveller'])
def personalised_generation_status():
    request_id = request.args.get('generationRequestId', '').strip()
    if not 8 <= len(request_id) <= 128:
        return jsonify(ok=False, error='A valid generation request ID is required.'), 400
    iid = _personalised_trip_id(g.uid, request_id)
    current = retrieveRecord('itineraries', iid)
    if not current or current.get('travellerId') != g.uid:
        return jsonify(ok=False, status='not_found'), 404
    return jsonify(ok=True, tripId=iid, status=current.get('status'),
                   stage=current.get('generationFailureStage'),
                   retryable=current.get('retryable') is True,
                   itinerary=current)


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

    # Recovery of an owned completed/in-flight operation does not reload a large snapshot.
    if existing and existing.get('status') in {'planned', 'generating'}:
        in_progress = existing['status'] == 'generating'
        return jsonify(ok=True, id=iid, tripId=iid, status=existing['status'],
                       itinerary=existing, inProgress=in_progress, reused=True), (202 if in_progress else 200)

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
        from services.recommendation_taxonomy import planning_preferences
        profile = snapshot.get('planningPreferences') or planning_preferences(
            retrieveRecord('travel_preferences', g.uid) or {})
        initial = createItinerary({
            **payload,
            **({'planningPreferences': profile} if profile else {}),
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
            current, created = claimRecord('itineraries', iid, initial)
            if not created:
                if current.get('travellerId') != g.uid:
                    return jsonify(ok=False, error='Trip generation request conflict'), 409
                return jsonify(ok=True, id=iid, tripId=iid, status=current.get('status'),
                               itinerary=current, reused=True,
                               inProgress=current.get('status') == 'generating'), (200 if current.get('status') == 'planned' else 202)
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
    if current.get('planningMode') or any(protected_activity(row) or row.get('planningOrigin')=='user_selected' for row in current.get('activities') or []):
        return jsonify(ok=False,error='Use Improve schedule to preview changes without overwriting your saved plan.',code='PLANNING_PREVIEW_REQUIRED'),409
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

