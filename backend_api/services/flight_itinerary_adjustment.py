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
    _opening_window,
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
    arrival = None
    for segment in reversed(outbound):
        if _airport_code(segment, 'arrival') == 'PEN':
            arrival = _date_time(segment.get('arrivalDate'), segment.get('arrivalTime'))
            if arrival:
                break
    departure = None
    for segment in returns:
        if _airport_code(segment, 'departure') == 'PEN':
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
    return any(activity.get(key) is True for key in ('locked', 'isLocked', 'fixed', 'protected', 'userFixed', 'manualTime', 'manualOrder', 'userEdited')) or str(activity.get('editProvenance') or '').lower() in {'manual', 'user'}


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
    pace = str(trip.get('travelPace') or trip.get('pace') or 'moderate').lower()
    pace = 'relaxed' if 'relax' in pace else ('active' if 'active' in pace else 'moderate')
    base_start, base_end = PACE_WINDOWS[pace]
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
        value['availableMinutes'] = max(0, value['endMinutes'] - value['startMinutes'])
        value['availabilityStatus'] = 'available' if value['endMinutes'] > value['startMinutes'] else 'unavailable'
    return {'status': 'available', 'reason': '', 'days': days}


def _schedule_day(trip, activities, day_info):
    current = day_info['startMinutes']
    previous = None
    scheduled = []
    unscheduled = []
    protected_conflicts = []
    for activity in activities:
        if _protected(activity):
            start = _clock(activity.get('scheduledStartTime') or activity.get('timeSlot'))
            end = _clock(activity.get('scheduledEndTime'))
            if start is None or end is None or start < day_info['startMinutes'] or end > day_info['endMinutes']:
                protected_conflicts.append({'activityId': activity.get('activityId'), 'message': 'Protected activity conflicts with flight availability; manual review required.', 'type': 'protected_activity'})
            scheduled.append(dict(activity))
            if start is not None and end is not None:
                current = max(current, end)
                previous = activity
            continue
        planned, reason = _schedule_candidate(activity, previous, current, day_info)
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
    opening = _opening_window(activity.get('openingHours'), date.fromisoformat(day_info['date']))
    if opening.get('status') == 'closed':
        return None, 'Attraction is closed on this trip day.'
    start = current + travel_minutes
    if opening.get('window'):
        start = max(start, opening['window'][0])
    if start < 13 * 60 + 30 and start + duration > 12 * 60 + 30:
        start = 13 * 60 + 30
    end = start + duration
    if opening.get('window') and end > opening['window'][1]:
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
        'scheduleNotes': [*(activity.get('scheduleNotes') or []), 'Adjusted within flight-derived availability.'],
    }, None


def build_preview(trip, flight, owner, preview_id):
    assumptions = planning_assumptions()
    boundaries = flight_boundaries(trip, flight, assumptions)
    availability = _availability(trip, boundaries, assumptions)
    current = deepcopy(trip)
    proposed = deepcopy(trip)
    changes = []
    newly_unscheduled = []
    remaining_conflicts = []
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
    affected_dates = {key for key, value in availability['days'].items() if value.get('arrival') or value.get('departure')}
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
        proposed['activities'] = [
            by_id.get(str(x.get('activityId')), x)
            for x in activities
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
    proposed['scheduledActivityCount'] = len(proposed.get('activities', []))
    proposed['unscheduledActivityCount'] = len(proposed.get('unscheduledSuggestions', []) or [])
    proposed['budgetEstimate'] = calculateBudget(proposed)
    current_fingerprint = fingerprint(current)
    flight_fingerprint = fingerprint(flight)
    return {
        'previewId': preview_id, 'tripId': trip.get('id'), 'status': 'ready', 'canApply': True,
        'reason': '', 'assumptions': assumptions,
        'boundaries': {k: v for k, v in boundaries.items() if k not in {'arrival', 'departure'}},
        'availability': availability, 'before': current, 'after': proposed,
        'changes': changes, 'newlyUnscheduled': newly_unscheduled, 'remainingConflicts': remaining_conflicts,
        'budgetBefore': calculateBudget(current), 'budgetAfter': proposed['budgetEstimate'],
        'tripFingerprint': current_fingerprint, 'flightFingerprint': flight_fingerprint,
        'owner': owner,
    }


def create_preview(trip, flight, owner):
    preview_id = f'flight_adjustment_{hashlib.sha256(f"{owner}:{trip.get("id")}:{fingerprint(flight)}:{fingerprint(trip)}".encode()).hexdigest()[:24]}'
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
        proposed['revision'] = int(trip.get('revision') or 0) + 1
        patch = {key: proposed[key] for key in ('activities', 'unscheduledSuggestions', 'scheduledActivityCount', 'unscheduledActivityCount', 'budgetEstimate') if key in proposed}
        patch.update({key: proposed[key] for key in ('flightAdjustmentPreviewId', 'flightAdjustmentAppliedAt', 'flightAdjustmentAssumptions', 'flightAdjustmentStatus', 'revision')})
        updated = update(trip.get('id'), patch)
        if updated is None:
            return None, 'The itinerary could not be saved.'
        result = {'ok': True, 'itinerary': updated, 'previewId': preview_id, 'idempotent': False}
        preview['status'] = 'applied'
        preview['appliedResult'] = result
        return result, None

