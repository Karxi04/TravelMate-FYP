"""Bounded editable trip versions. Commercial records are never restoration inputs."""
from copy import deepcopy
from datetime import date, timedelta
from hashlib import sha256
import json

from services.itinerary_write_contract import EDITABLE_FIELDS, ACTIVITY_TEXT, ACTIVITY_NUMBERS, EVIDENCE_FIELDS
from services.review_service import ReviewConflict
from utils import utc_now_iso

RETENTION = 5
MAX_SNAPSHOT_BYTES = 48 * 1024
FIELDS = EDITABLE_FIELDS | {'destinationState', 'numberOfTravellers', 'interests', 'excludedInterests',
    'excludedActivityTypes', 'preferIndoor', 'daySpecificPreferences', 'activities', 'foodCost', 'transportCost',
    'confirmedIntercityTransfer'}
ACTIVITY_FIELDS = ACTIVITY_TEXT | ACTIVITY_NUMBERS | {'activityId', 'dayNo', 'sequenceNo', 'indoor',
    'gps_coordinates', 'gpsCoordinates', 'pricingEvidence', 'overlapsAllowance', 'currency',
    'imageUrl', 'thumbnail', 'openingHoursSourceUrl', 'openingHoursVerifiedAt',
    'intentionalRepeat', 'canonicalAttractionId', 'identityConsolidation', 'supportingAccess',
    'independentSubAttraction', 'ticketProductId', 'place_id', 'data_id', 'data_cid'}


class HistoryConflict(ReviewConflict):
    pass


def fingerprint(trip):
    return sha256(json.dumps(trip, sort_keys=True, default=str).encode()).hexdigest()


def editable_snapshot(trip):
    result = {key: deepcopy(trip[key]) for key in FIELDS - {'activities'} if trip.get(key) is not None}
    activities = trip.get('activities')
    if not isinstance(activities, list):
        activities = [a for d in trip.get('dailySchedule') or [] for a in d.get('activities') or []]
    result['activities'] = [{k: deepcopy(v) for k, v in a.items() if k in ACTIVITY_FIELDS}
                            for a in activities if isinstance(a, dict)]
    for activity in result['activities']:
        if isinstance(activity.get('pricingEvidence'), dict):
            activity['pricingEvidence'] = {k: v for k, v in activity['pricingEvidence'].items() if k in EVIDENCE_FIELDS}
    if len(json.dumps(result, default=str).encode()) > MAX_SNAPSHOT_BYTES:
        raise HistoryConflict('This trip is too large for safe editable history. No change was saved.')
    return result


def history_patch(current, patch, now=None):
    """Must be committed with the trip patch, under a transaction or update-time CAS."""
    patch = {k: v for k, v in patch.items() if k not in {'itineraryRevision', 'itineraryHistory', '_restoreVersion'}}
    if not FIELDS.intersection(patch):
        return dict(patch)
    before, after = editable_snapshot(current), editable_snapshot({**current, **patch})
    if before == after:
        return dict(patch)
    number = int(current.get('itineraryRevision') or 1)
    changed = sorted(k for k in FIELDS if before.get(k) != after.get(k))
    entry = {'version': number, 'changedAt': now or utc_now_iso(), 'changedFields': changed,
             'summary': 'Changed ' + ', '.join(changed), 'state': before}
    history = [*deepcopy(current.get('itineraryHistory') or []), entry][-RETENTION:]
    result = {**patch, 'itineraryRevision': number + 1, 'itineraryHistory': history}
    if len(json.dumps({**current, **result}, default=str).encode()) > 900 * 1024:
        raise HistoryConflict('This trip is too large for safe revision storage. No change was saved.')
    return result


def history_metadata(trip):
    return [{k: deepcopy(row[k]) for k in ('version', 'changedAt', 'changedFields', 'summary')}
            for row in trip.get('itineraryHistory') or []]


def version_state(trip, version):
    if version == int(trip.get('itineraryRevision') or 1):
        return editable_snapshot(trip)
    row = next((r for r in trip.get('itineraryHistory') or [] if r.get('version') == version), None)
    if row is None:
        raise HistoryConflict('That version is unavailable. History starts with the first captured edit and keeps only five prior versions.')
    # Whitelist again on read; no historical record can restore a commercial field.
    return editable_snapshot(row['state'])


def ensure_restorable(trip):
    protected = ('packageTrip', 'selectedFlight', 'selectedHotel', 'hotelBookingId', 'checkoutOrderId',
                 'purchasedPackages', 'paymentId', 'paymentRecordId', 'supplierArrangementId',
                 'flightBookingId', 'bookingReference', 'paidTotal')
    commercial_status = any(str(trip.get(k) or '').lower() in {'paid', 'booked', 'confirmed', 'succeeded'}
                            for k in ('status', 'paymentStatus', 'bookingStatus'))
    if commercial_status or trip.get('tripType') == 'package' or any(trip.get(k) for k in protected) or any(
            a.get(k) for a in trip.get('activities') or [] for k in
            ('bookingId', 'supplierArrangementId', 'checkoutOrderId', 'hotelBookingId')):
        raise HistoryConflict('This trip has travel, booking or payment arrangements. Restore is blocked; review them in Trip Details.')


def restore_patch(trip, version, *, scope='trip', day=None):
    from sequence_contract.domain_functions import recalculateItinerary, calculateBudget
    ensure_restorable(trip)
    prior = version_state(trip, version)
    current = editable_snapshot(trip)
    if scope == 'budget':
        if 'budgetLimit' not in prior:
            raise HistoryConflict('No budget is recorded in that version.')
        patch = {'budgetLimit': prior['budgetLimit']}
    elif scope == 'day':
        if type(day) is not int or not 1 <= day <= 14:
            raise HistoryConflict('Choose an itinerary day to restore.')
        old = [a for a in prior['activities'] if str(a.get('dayNo')) == str(day)]
        if not old:
            raise HistoryConflict('That version has no recorded activities for this day.')
        patch = {'activities': [a for a in current['activities'] if str(a.get('dayNo')) != str(day)] + old}
    elif scope == 'trip':
        patch = {k: deepcopy(prior.get(k)) for k in FIELDS if prior.get(k) != current.get(k)}
    else:
        raise HistoryConflict('Choose trip, day or budget restoration.')
    if 'travellerCount' in patch and patch['travellerCount'] is None:
        legacy_count = prior.get('numberOfTravellers')
        if type(legacy_count) is not int or legacy_count < 1:
            raise HistoryConflict('The historical traveller count is unknown. Restore a specific day or budget instead.')
        patch['travellerCount'] = legacy_count
    if all(current.get(k) == v for k, v in patch.items()):
        raise HistoryConflict('Those supported fields already match this version. Nothing needs restoring.')
    merged = {**trip, **patch}
    if {'activities', 'startDate', 'endDate', 'destinationArea', 'travelPace',
        'transportMode', 'confirmedIntercityTransfer'} & patch.keys():
        ids = [a.get('activityId') for a in merged['activities']]
        if any(not key for key in ids) or len(ids) != len(set(ids)):
            raise HistoryConflict('Historical activity identifiers are incomplete or duplicated; safe restoration is unavailable.')
        planning = merged
        if scope == 'day':
            start = (date.fromisoformat(str(trip['startDate'])[:10]) + timedelta(days=day - 1)).isoformat()
            if start > str(trip['endDate'])[:10]:
                raise HistoryConflict('That day is outside the current trip.')
            planning = {**merged, 'startDate': start, 'endDate': start, 'tripDays': 1,
                        'activities': [{**a, 'dayNo': 1} for a in merged['activities'] if str(a.get('dayNo')) == str(day)]}
        planned = recalculateItinerary({**planning, 'unscheduledSuggestions': []})
        if {a['activityId'] for a in planned['activities']} != {a['activityId'] for a in planning['activities']}:
            raise HistoryConflict('The historical activities cannot fit safely in the schedule. No restoration was saved.')
        if scope == 'day':
            label = f'Day {day} - {start}'
            restored = [{**a, 'dayNo': day, 'dayLabel': label} for a in planned['activities']]
            patch['activities'] = sorted([a for a in trip['activities'] if str(a.get('dayNo')) != str(day)] + restored,
                                         key=lambda a: int(a['dayNo']))
            daily = [{**d, 'dayNo': day, 'dayLabel': label, 'activities': restored} for d in planned['dailySchedule']]
            patch['dailySchedule'] = sorted([d for d in trip.get('dailySchedule') or [] if str(d.get('dayNo')) != str(day)] + daily,
                                            key=lambda d: int(d['dayNo']))
        else:
            patch.update({key: planned[key] for key in ('activities', 'dailySchedule', 'tripDays', 'coverageStatus',
                'unscheduledSuggestions', 'routeWarnings') if key in planned})
            if 'confirmedIntercityTransfer' in patch:
                patch['intercityTransferStatus'] = planned.get('intercityTransferStatus') if patch['confirmedIntercityTransfer'] else None
        merged = {**trip, **patch}
    if 'travellerCount' in patch:
        from services.activity_pricing import refresh_activity_costs
        patch.update(refresh_activity_costs(merged))
        merged = {**trip, **patch}
    patch['budgetEstimate'] = calculateBudget(merged)
    if editable_snapshot(merged) == current:
        raise HistoryConflict('Those supported fields already match this version. Nothing needs restoring.')
    return patch
