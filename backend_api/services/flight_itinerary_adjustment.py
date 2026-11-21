"""Bounded, preview-first flight adjustment for existing itineraries."""

import hashlib
import json
import math
import os
import threading
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sequence_contract.domain_functions import (
    PACE_WINDOWS,
    _activity_duration,
    _activity_opening,
    _travel_leg,
    calculateBudget,
)


_PREVIEWS = {}
# ponytail: process-local lock keeps preview/apply atomic in this single-worker demo;
# use a Firestore transaction or distributed lock when multiple workers share writes.
_LOCK = threading.RLock()
try:
    PENANG_ZONE = ZoneInfo('Asia/Kuala_Lumpur')
except Exception:
    # Malaysia has a fixed UTC+08:00 offset; this keeps offline Windows tests
    # deterministic when the optional tzdata package is unavailable.
    PENANG_ZONE = timezone(timedelta(hours=8), name='Asia/Kuala_Lumpur')


def reset_flight_adjustment_previews():
    with _LOCK:
        _PREVIEWS.clear()


def _stable(value):
    return json.dumps(value or {}, sort_keys=True, separators=(',', ':'), default=str)


def fingerprint(value):
    return hashlib.sha256(_stable(value).encode('utf-8')).hexdigest()


def flight_selection_change_patch(trip, flight):
    previous = trip.get('selectedFlight') or {}
    if fingerprint(previous) == fingerprint(flight):
        return {}
    patch = {'revision': int(trip.get('revision') or 0) + 1}
    if trip.get('flightAdjustmentPreviewId') or trip.get('flightAdjustmentStatus') in {'applied', 'review_required'}:
        # Keep the last application metadata as provenance, not current synchronization.
        patch.update({
            'flightAdjustmentStatus': 'review_required',
            'flightAdjustmentReviewReason': 'flight_replaced' if flight else 'flight_removed',
        })
        if previous and not trip.get('flightAdjustmentFlightFingerprint'):
            patch['flightAdjustmentFlightFingerprint'] = fingerprint(previous)
    return patch


def _finite_env(name, default, minimum=0, maximum=720):
    try:
        value = float(os.getenv(name, default))
    except (TypeError, ValueError):
        value = float(default)
    if not math.isfinite(value):
        value = float(default)
    return int(max(minimum, min(maximum, round(value))))


def planning_assumptions():
    return {
        'arrivalClearanceMinutes': _finite_env('FLIGHT_ARRIVAL_CLEARANCE_MINUTES', 90),
        'arrivalTransferMinutes': _finite_env('FLIGHT_ARRIVAL_TRANSFER_MINUTES', 90),
        'departureTransferMinutes': _finite_env('FLIGHT_DEPARTURE_TRANSFER_MINUTES', 90),
        'departureCheckinMinutes': _finite_env('FLIGHT_DEPARTURE_CHECKIN_MINUTES', 120),
        'timezone': 'Asia/Kuala_Lumpur',
        'label': 'TravelMate planning assumptions; not official airline requirements.',
        'source': 'configured_planning_assumption',
    }


def _date_time(raw_date, raw_time):
    if not raw_date or not raw_time:
        return None
    try:
        parsed_date = date.fromisoformat(str(raw_date)[:10])
        text = str(raw_time).strip().upper().replace('.', ':')
        parsed_time = datetime.strptime(text, '%H:%M').time()
        return datetime.combine(parsed_date, parsed_time, tzinfo=PENANG_ZONE)
    except (TypeError, ValueError):
        return None


def _segments(flight):
    return [x for x in (flight or {}).get('outboundSegments', []) if isinstance(x, dict)], [
        x for x in (flight or {}).get('returnSegments', []) if isinstance(x, dict)
    ]


def _airport_code(segment, field):
    value = segment.get(f'{field}AirportCode')
    if value is None:
        value = segment.get(f'{field}Airport')
    if isinstance(value, dict):
        value = value.get('id') or value.get('code')
    return str(value or '').upper()


def flight_boundaries(trip, flight, assumptions=None):
    assumptions = assumptions or planning_assumptions()
    outbound, returns = _segments(flight)
    from services.flight_airports import MALAYSIAN_AIRPORT_CATALOG
    from services.malaysian_locality import normalize_destination_scope
    scope = normalize_destination_scope(trip.get('destinationArea'))
    def at_destination(code):
        airport = MALAYSIAN_AIRPORT_CATALOG.get(code, {})
        if not airport:
            return False
        airport_scope = normalize_destination_scope(airport.get('state'))
        return not scope.get('state') or scope['state'] == airport_scope.get('state')
    arrival = None
    for segment in reversed(outbound):
        if at_destination(_airport_code(segment, 'arrival')):
            arrival = _date_time(segment.get('arrivalDate'), segment.get('arrivalTime'))
            if arrival:
                break
    departure = None
    for segment in returns:
        if at_destination(_airport_code(segment, 'departure')):
            departure = _date_time(segment.get('departureDate'), segment.get('departureTime'))
            if departure:
                break
    if arrival is None and not outbound and str((flight or {}).get('arrivalAirport') or '').upper() == 'PEN':
        arrival = _date_time((flight or {}).get('outboundDate'), (flight or {}).get('arrivalTime'))
    if departure is None and not returns and str((flight or {}).get('departureAirport') or '').upper() == 'PEN':
        departure = _date_time((flight or {}).get('outboundDate'), (flight or {}).get('departureTime'))
    return {
        'arrival': arrival,
        'departure': departure,
        'arrivalLocal': arrival.isoformat() if arrival else None,
        'departureLocal': departure.isoformat() if departure else None,
        'timezone': 'Asia/Kuala_Lumpur',
    }


def _trip_dates(trip):
    try:
        start = date.fromisoformat(str(trip.get('startDate'))[:10])
        end = date.fromisoformat(str(trip.get('endDate'))[:10])
        return start, end
    except (TypeError, ValueError):
        return None, None


def _protected(activity):
    from services.trip_budget_replan import protected_activity
    return protected_activity(activity) or any(activity.get(key) is True for key in ('locked', 'isLocked', 'fixed', 'protected', 'userFixed', 'manualTime', 'manualOrder', 'userEdited')) or str(activity.get('editProvenance') or '').lower() in {'manual', 'user'}


def _activity_date(trip, activity):
    start, _ = _trip_dates(trip)
    day_no = int(float(activity.get('dayNo') or 1))
    return start + timedelta(days=max(0, day_no - 1)) if start else None


def _clock(value):
    text = str(value or '').strip()
    try:
        parsed = datetime.strptime(text, '%H:%M')
        return parsed.hour * 60 + parsed.minute
    except ValueError:
        return None


def _format_clock(minutes):
    return f'{minutes // 60:02d}:{minutes % 60:02d}'


def _availability(trip, boundaries, assumptions):
    start_date, end_date = _trip_dates(trip)
    if not start_date or not end_date:
        return {'status': 'unavailable', 'reason': 'Trip dates are missing or invalid.', 'days': {}}
    arrival = boundaries.get('arrival')
    departure = boundaries.get('departure')
    if arrival and arrival.date() < start_date:
        return {'status': 'incompatible', 'reason': 'Flight arrives before the trip starts.', 'days': {}}
    if arrival and arrival.date() > end_date:
        return {'status': 'incompatible', 'reason': 'Flight arrives after the trip ends.', 'days': {}}
    if departure and (departure.date() < start_date or departure.date() > end_date):
        return {'status': 'incompatible', 'reason': 'Flight departs outside the trip dates.', 'days': {}}
    from sequence_contract.domain_functions import _pace_key
    pace = _pace_key(trip)
    base_start, base_end = PACE_WINDOWS[pace]
    rhythm=str(trip.get('sleepingType') or '').lower()
    if rhythm=='early riser':base_start,base_end=max(450,base_start-60),base_end-60
    elif rhythm=='night owl':base_start=max(base_start,660)
    elif rhythm=='comfort-focused':base_start=max(base_start,600)
    days = {}
    for index in range((end_date - start_date).days + 1):
        current = start_date + timedelta(days=index)
        days[current.isoformat()] = {
            'dayNo': index + 1, 'date': current.isoformat(),
            'startMinutes': base_start, 'endMinutes': base_end,
            'baseStartMinutes': base_start, 'baseEndMinutes': base_end,
            'source': 'daily_pace_window',
        }
    if arrival:
        key = arrival.date().isoformat()
        if key in days:
            days[key]['startMinutes'] = max(days[key]['startMinutes'], arrival.hour * 60 + arrival.minute + assumptions['arrivalClearanceMinutes'])
            days[key]['arrival'] = boundaries['arrivalLocal']
    if departure:
        key = departure.date().isoformat()
        if key in days:
            buffer = assumptions['departureTransferMinutes'] + assumptions['departureCheckinMinutes']
            days[key]['endMinutes'] = min(days[key]['endMinutes'], departure.hour * 60 + departure.minute - buffer)
            days[key]['departure'] = boundaries['departureLocal']
    for value in days.values():
        current_date = date.fromisoformat(value['date'])
        if (arrival and current_date < arrival.date()) or (departure and current_date > departure.date()):
            value['endMinutes'] = value['startMinutes']
            value['source'] = 'outside_flight_stay'
        value['availableMinutes'] = max(0, value['endMinutes'] - value['startMinutes'])
        value['availabilityStatus'] = 'available' if value['endMinutes'] > value['startMinutes'] else 'unavailable'
    from services.flexible_planning import apply_preferences
    return apply_preferences(trip, {'status': 'available', 'reason': '', 'days': days}, boundaries, assumptions)


def _schedule_day(trip, activities, day_info):
    current = day_info['startMinutes']
    previous = None
    scheduled = []
    unscheduled = []
    protected_conflicts = []
    for index, activity in enumerate(activities):
        if _protected(activity):
            start = _clock(activity.get('scheduledStartTime') or activity.get('timeSlot'))
            end = _clock(activity.get('scheduledEndTime'))
            if start is None or end is None or start < max(current, day_info['startMinutes']) or end > day_info['endMinutes']:
                protected_conflicts.append({'activityId': activity.get('activityId'), 'message': 'Protected activity conflicts with flight availability; manual review required.', 'type': 'protected_activity'})
            opening = _activity_opening(activity, date.fromisoformat(day_info['date']))
            from services.flexible_planning import reservations, skip_reservations
            if start is not None and end is not None and skip_reservations(start,end-start,reservations(trip,day_info['dayNo'],activity.get('activityId')))!=start:
                protected_conflicts.append({'activityId':activity.get('activityId'),'message':'Your fixed visit overlaps personal reserved time.','type':'protected_activity'})
            if opening['status'] == 'closed' or (opening.get('periods') and start is not None and end is not None
                    and not any(left <= start and end <= right for left, right in opening['periods'])):
                protected_conflicts.append({'activityId': activity.get('activityId'), 'message': 'Protected visit conflicts with venue hours; manual review required.', 'type': 'protected_activity'})
            scheduled.append(dict(activity))
            if start is not None and end is not None:
                current = max(current, end)
                previous = activity
            continue
        bounded = dict(day_info)
        from services.flexible_planning import reservations
        bounded['reservedIntervals']=reservations(trip,day_info['dayNo'],activity.get('activityId'))
        following_fixed = next((row for row in activities[index + 1:] if _protected(row)), None)
        if following_fixed:
            fixed_start = _clock(following_fixed.get('scheduledStartTime') or following_fixed.get('timeSlot'))
            transfer = _travel_leg(activity, following_fixed)[0]
            if fixed_start is not None:
                bounded['endMinutes'] = min(bounded['endMinutes'], fixed_start - transfer)
        planned, reason = _schedule_candidate(activity, previous, current, bounded)
        if planned is None:
            unscheduled.append({**activity, 'unscheduledReason': reason})
            continue
        scheduled.append(planned)
        previous = planned
        current = planned['_endMinutes']
    for sequence, activity in enumerate(scheduled, 1):
        if _protected(activity):
            continue
        activity.pop('_startMinutes', None)
        activity.pop('_endMinutes', None)
        activity['sequenceNo'] = sequence
    return scheduled, unscheduled, protected_conflicts


def _schedule_candidate(activity, previous, current, day_info):
    duration, duration_source = _activity_duration(activity)
    travel_minutes, distance, travel_source = _travel_leg(previous, activity)
    opening = _activity_opening(activity, date.fromisoformat(day_info['date']))
    if opening.get('status') == 'closed':
        return None, 'Attraction is closed on this trip day.'
    start = current + travel_minutes
    periods = opening.get('periods') or []
    if periods:
        feasible = [max(start, left) for left, right in periods if max(start, left) + duration <= right]
        if not feasible:
            return None, 'Could not fit within attraction opening hours after flight availability.'
        start = min(feasible)
    if start < 13 * 60 + 30 and start + duration > 12 * 60 + 30:
        start = 13 * 60 + 30
    end = start + duration
    from services.flexible_planning import skip_reservations
    start = skip_reservations(start,duration,day_info.get('reservedIntervals',()))
    end = start+duration
    if periods and not any(left <= start and end <= right for left, right in periods):
        return None, 'Could not fit within attraction opening hours after flight availability.'
    if end > day_info['endMinutes']:
        return None, 'Could not fit within the flight-constrained availability window.'
    return {
        **activity, 'dayNo': day_info['dayNo'], 'dayDate': day_info['date'],
        'timeSlot': _format_clock(start), 'scheduledStartTime': _format_clock(start),
        'scheduledEndTime': _format_clock(end), 'timeRangeLabel': f'{_format_clock(start)} - {_format_clock(end)}',
        'recommendedDurationMinutes': duration, 'durationSource': duration_source,
        'durationEstimated': duration_source != 'provider', 'travelBufferMinutes': travel_minutes,
        'travelDurationMinutes': travel_minutes, 'travelDistanceKm': distance,
        'travelTimeSource': travel_source, '_startMinutes': start, '_endMinutes': end,
        'openingHoursStatus': opening['status'], 'openingHoursEvidence': opening['evidence'],
        'scheduleNotes': [*(activity.get('scheduleNotes') or []), 'Adjusted within flight-derived availability.'],
    }, None


def build_preview(trip, flight, owner, preview_id):
    assumptions = planning_assumptions()
    boundaries = flight_boundaries(trip, flight, assumptions)
    boundaries['source']='selected_flight'
    availability = _availability(trip, boundaries, assumptions)
    current = deepcopy(trip)
    proposed = deepcopy(trip)
    changes = []
    newly_unscheduled = []
    remaining_conflicts = list(availability.get('preferenceConflicts') or [])
    outbound_segments, return_segments = _segments(flight)
    missing_boundary = (bool(return_segments) and (not boundaries.get('arrival') or not boundaries.get('departure'))) or (not return_segments and not boundaries.get('arrival') and not boundaries.get('departure'))
    if missing_boundary:
        availability = {'status': 'no_flight_boundary', 'reason': 'Flight local date and time data is incomplete; no safe adjustment was proposed.', 'days': {}}
    if availability['status'] != 'available':
        return {
            'previewId': preview_id, 'tripId': trip.get('id'), 'status': availability['status'],
            'canApply': False, 'reason': availability['reason'], 'assumptions': assumptions,
            'boundaries': {k: v for k, v in boundaries.items() if k not in {'arrival', 'departure'}},
            'availability': availability, 'before': current, 'after': current,
            'changes': [], 'newlyUnscheduled': [], 'remainingConflicts': [{'message': availability['reason']}],
            'budgetBefore': calculateBudget(current), 'budgetAfter': calculateBudget(current),
        }
    activities = [dict(x) for x in current.get('activities', []) or []]
    proposed_activities = [dict(x) for x in activities]
    affected_dates = {key for key, value in availability['days'].items()
                      if value.get('arrival') or value.get('departure') or value.get('source') == 'outside_flight_stay'}
    if not affected_dates:
        return {
            'previewId': preview_id, 'tripId': trip.get('id'), 'status': 'no_flight_boundary',
            'canApply': False, 'reason': 'Flight dates or local times are incomplete.', 'assumptions': assumptions,
            'boundaries': {k: v for k, v in boundaries.items() if k not in {'arrival', 'departure'}},
            'availability': availability, 'before': current, 'after': current,
            'changes': [], 'newlyUnscheduled': [], 'remainingConflicts': [{'message': 'Flight dates or local times are incomplete.'}],
            'budgetBefore': calculateBudget(current), 'budgetAfter': calculateBudget(current),
        }
    for date_key in affected_dates:
        day_info = availability['days'][date_key]
        day_items = [x for x in activities if _activity_date(current, x) and _activity_date(current, x).isoformat() == date_key]
        if not day_items:
            continue
        scheduled, unscheduled, protected_conflicts = _schedule_day(current, day_items, day_info)
        remaining_conflicts.extend(protected_conflicts)
        ids = {str(x.get('activityId')) for x in day_items}
        by_id = {str(x.get('activityId')): x for x in scheduled}
        unscheduled_ids = {str(x.get('activityId')) for x in unscheduled}
        proposed_activities = [
            by_id.get(str(x.get('activityId')), x)
            for x in proposed_activities
            if str(x.get('activityId')) not in unscheduled_ids
        ]
        proposed['unscheduledSuggestions'] = [x for x in proposed.get('unscheduledSuggestions', []) if str(x.get('activityId')) not in ids] + unscheduled
        newly_unscheduled.extend(unscheduled)
        for before in day_items:
            after = next((x for x in scheduled if str(x.get('activityId')) == str(before.get('activityId'))), None)
            if after is None:
                changes.append({'activityId': before.get('activityId'), 'activityName': before.get('activityName'), 'kind': 'unscheduled', 'reason': next((x.get('unscheduledReason') for x in unscheduled if str(x.get('activityId')) == str(before.get('activityId'))), 'Could not fit.'), 'protected': _protected(before)})
            elif any(str(before.get(key)) != str(after.get(key)) for key in ('dayNo', 'scheduledStartTime', 'scheduledEndTime')):
                changes.append({'activityId': before.get('activityId'), 'activityName': before.get('activityName'), 'kind': 'moved', 'from': {key: before.get(key) for key in ('dayNo', 'scheduledStartTime', 'scheduledEndTime')}, 'to': {key: after.get(key) for key in ('dayNo', 'scheduledStartTime', 'scheduledEndTime')}, 'protected': _protected(before)})
            else:
                changes.append({'activityId': before.get('activityId'), 'activityName': before.get('activityName'), 'kind': 'retained', 'protected': _protected(before)})
    proposed['activities'] = proposed_activities
    # Keep the saved day cards in sync with the flight-constrained activity list.
    if isinstance(current.get('dailySchedule'), list):
        from services.activity_pricing import activity_pricing
        days = []
        for day in current['dailySchedule']:
            day_rows = [row for row in proposed_activities if row.get('dayNo') == day.get('dayNo')]
            prices = [activity_pricing(row, current.get('travellerCount')) for row in day_rows]
            blocks = [row for row in current.get('planningBlocks') or [] if row.get('dayNo') == day.get('dayNo')]
            known = round(sum(price['effectiveCost'] for price in prices)
                          + sum(float(row.get('estimatedCost') or 0) for row in blocks), 2)
            unpriced = sum(bool(price['pricingIssues']) for price in prices)
            unpriced_blocks = sum(row.get('estimatedCost') is None for row in blocks)
            days.append({**day, 'activities': deepcopy(day_rows),
                         'knownEstimatedCost': known,
                         'unpricedActivityCount': unpriced, 'unpricedPersonalBlockCount': unpriced_blocks,
                         'estimatedCost': None if unpriced or unpriced_blocks else known,
                         'estimatedMinutes': sum(_activity_duration(row)[0] + int(row.get('travelDurationMinutes') or 0)
                                                 for row in day_rows)})
        proposed['dailySchedule'] = days
    proposed['scheduledActivityCount'] = len(proposed.get('activities', []))
    proposed['unscheduledActivityCount'] = len(proposed.get('unscheduledSuggestions', []) or [])
    proposed['budgetEstimate'] = calculateBudget(proposed)
    from services.flexible_planning import active, confirmation_fingerprint
    if active(proposed) and not remaining_conflicts:
        proposed['travelDayPreferences']={**(proposed.get('travelDayPreferences') or {}),'confirmedFor':confirmation_fingerprint(proposed)}
    current_fingerprint = fingerprint(current)
    flight_fingerprint = fingerprint(flight)
    no_window = not any(day['availableMinutes'] > 0 for day in availability['days'].values())
    blocked_window = no_window and (bool(activities) or not active(proposed))
    reason = ('No sightseeing window remains between these flights after the configured airport buffers. Change the flight times or trip dates.'
              if blocked_window else 'Protected activities conflict with the flight. Review the arrangement before adjusting.'
              if remaining_conflicts else '')
    if remaining_conflicts and availability.get('preferenceConflicts'):
        reason=availability['preferenceConflicts'][0]['message']
    return {
        'previewId': preview_id, 'tripId': trip.get('id'), 'status': 'ready',
        'canApply': not blocked_window and not remaining_conflicts,
        'scheduleFeasibility': 'no_sightseeing_window' if no_window else 'protected_conflict' if remaining_conflicts else 'fits_flight_window',
        'reason': reason, 'assumptions': assumptions,
        'boundaries': {k: v for k, v in boundaries.items() if k not in {'arrival', 'departure'}},
        'availability': availability, 'before': current, 'after': proposed,
        'changes': changes, 'newlyUnscheduled': newly_unscheduled, 'remainingConflicts': remaining_conflicts,
        'budgetBefore': calculateBudget(current), 'budgetAfter': proposed['budgetEstimate'],
        'tripFingerprint': current_fingerprint, 'flightFingerprint': flight_fingerprint,
        'owner': owner,
    }


def create_preview(trip, flight, owner, planning=None, candidates=None):
    preview_key = f"{owner}:{trip.get('id')}:{fingerprint(flight)}:{fingerprint(trip)}:{fingerprint(planning)}"
    preview_id = f"flight_adjustment_{hashlib.sha256(preview_key.encode()).hexdigest()[:24]}"
    if planning is not None:
        from services.flexible_planning import build_planning_preview
        preview = build_planning_preview(trip, flight, owner, preview_id, planning, candidates)
    else:
        preview = build_preview(trip, flight, owner, preview_id)
    with _LOCK:
        _PREVIEWS[preview_id] = deepcopy(preview)
    return preview


def apply_preview(preview_id, trip, flight, owner, update):
    with _LOCK:
        preview = _PREVIEWS.get(preview_id)
        if not preview or preview.get('owner') != owner:
            return None, 'Preview not found'
        if preview.get('status') == 'applied':
            if (preview.get('appliedTripFingerprint') != fingerprint(trip)
                    or preview.get('flightFingerprint') != fingerprint(flight)):
                return None, 'This preview is stale because the trip or selected flight changed. Create a new preview.'
            result = deepcopy(preview.get('appliedResult'))
            if isinstance(result, dict):
                result['idempotent'] = True
            return result, None
        if preview.get('tripFingerprint') != fingerprint(trip) or preview.get('flightFingerprint') != fingerprint(flight):
            return None, 'This preview is stale because the trip or selected flight changed. Create a new preview.'
        if not preview.get('canApply'):
            return None, preview.get('reason') or 'This preview cannot be applied safely.'
        proposed = deepcopy(preview['after'])
        proposed['flightAdjustmentPreviewId'] = preview_id
        proposed['flightAdjustmentAppliedAt'] = datetime.now(PENANG_ZONE).isoformat()
        proposed['flightAdjustmentAssumptions'] = preview['assumptions']
        proposed['flightAdjustmentStatus'] = 'applied'
        proposed['flightAdjustmentFlightFingerprint'] = fingerprint(flight)
        proposed['flightAdjustmentReviewReason'] = None
        proposed['revision'] = int(trip.get('revision') or 0) + 1
        patch = {key: proposed[key] for key in ('activities', 'dailySchedule', 'unscheduledSuggestions', 'scheduledActivityCount', 'unscheduledActivityCount', 'budgetEstimate') if key in proposed}
        if 'travelDayPreferences' in proposed:patch['travelDayPreferences']=proposed['travelDayPreferences']
        patch.update({key: proposed[key] for key in ('flightAdjustmentPreviewId', 'flightAdjustmentAppliedAt', 'flightAdjustmentAssumptions', 'flightAdjustmentStatus', 'flightAdjustmentFlightFingerprint', 'flightAdjustmentReviewReason', 'revision')})
        if preview.get('kind')=='planning':
            patch = {key:proposed[key] for key in ('planningMode','travelMode','travelDayPreferences','planningBlocks','activities',
                'dailySchedule','unscheduledSuggestions','scheduledActivityCount','unscheduledActivityCount','budgetEstimate',
                'nextActivitySeq','recommendationGenerationId') if key in proposed}
            patch.update(planningAdjustmentPreviewId=preview_id,planningAdjustmentStatus='applied',revision=proposed['revision'])
        updated = update(trip.get('id'), patch)
        if updated is None:
            return None, 'The itinerary could not be saved.'
        result = {'ok': True, 'itinerary': updated, 'previewId': preview_id, 'idempotent': False}
        preview['status'] = 'applied'
        preview['appliedTripFingerprint'] = fingerprint(updated)
        preview['appliedResult'] = deepcopy(result)
        return result, None

