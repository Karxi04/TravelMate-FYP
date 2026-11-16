"""History queries and restoration drafts; persistence stays in confirmed save-plan."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re

from services.itinerary_history import (
    HistoryConflict, editable_snapshot, fingerprint, history_metadata, restore_patch, version_state,
)
from .nlp_extractor import clean_text, extract_itinerary_day


def is_history_request(message):
    q = clean_text(message)
    return bool(re.search(r'\b(?:restore|revert|history)\b|\b(?:earlier|previous|original) (?:itinerary|version|day)\b|'
                          r'\bversions? \d+\b|\bundo\b.*\bsaved\b|\bchang(?:e|ed|es) yesterday\b', q))


def _preview(trip, snapshot, version):
    from sequence_contract.domain_functions import calculateBudget
    count = snapshot.get('travellerCount', snapshot.get('numberOfTravellers'))
    budget = (calculateBudget({**snapshot, 'travellerCount': count}) if type(count) is int and count > 0 else
              {'incomplete': True, 'limitations': ['Historical traveller count is unknown; a cost total cannot be confirmed.']})
    return {**snapshot, 'title': snapshot.get('title') or trip.get('title') or 'Earlier itinerary',
            'viewOnly': True, 'savedTripId': trip['id'], 'historyVersion': version,
            'budgetEstimate': budget}


def history_turn(message, trip, state, *, compare, read):
    pending_day = (state.get('adjustment') or {}).get('pendingHistoryDay')
    q = clean_text(message)
    historical = is_history_request(message)
    if pending_day and not historical and re.search(r'\b(?:change|replace|remove|add|prefer|budget)\b', q):
        state['adjustment'].pop('pendingHistoryDay', None)
        return None
    if pending_day and re.search(r'\b(?:resume|continue|back to)\b', q):
        return {'reply': 'Which itinerary day contains the activity you want to restore from saved history?'}
    if not historical and not (pending_day and extract_itinerary_day(message)):
        return None
    history = trip.get('itineraryHistory') or []
    if not history:
        return {'reply': 'No saved revision history is available for this trip yet. History starts with its next supported saved edit; I cannot recover a pre-feature version.'}
    if 'yesterday' in q:
        yesterday = (datetime.now(timezone(timedelta(hours=8))).date() - timedelta(days=1)).isoformat()
        events = [r for r in history if datetime.fromisoformat(r['changedAt'].replace('Z', '+00:00')).astimezone(
            timezone(timedelta(hours=8))).date().isoformat() == yesterday]
        return {'reply': '\n'.join(f"Version {r['version']} -> {r['version'] + 1}: {r['summary']}" for r in events)
                or 'There are no retained changes recorded for yesterday (Malaysia time).',
                'revisionHistory': history_metadata(trip)}
    numbers = [int(v) for v in re.findall(r'\bversions? (\d+)\b', q)]
    if 'compare' in q:
        # Also accept "version 2 and 3" without treating either number as a trip day.
        numbers = [int(v) for v in re.findall(r'\b\d+\b', q)]
        if len(numbers) != 2:
            return {'reply': 'Which two retained version numbers would you like to compare?', 'revisionHistory': history_metadata(trip)}
        try:
            old, new = [version_state(trip, n) for n in numbers]
        except HistoryConflict as error:
            return {'reply': str(error)}
        return {'reply': compare(old, new), 'tripPlan': _preview(trip, old, numbers[0]),
                'proposedPlan': _preview(trip, new, numbers[1]),
                'comparisonLabel': f'Itinerary version {numbers[1]} (read-only)'}
    if 'history' in q and not re.search(r'\b(?:restore|revert|undo)\b', q):
        rows = history_metadata(trip)
        return {'reply': f"Current version: {trip.get('itineraryRevision', 1)}. Five prior versions are retained at most.\n" +
                '\n'.join(f"Version {r['version']} -> {r['version'] + 1}: {r['summary']} ({r['changedAt']})" for r in rows),
                'revisionHistory': rows}
    day = extract_itinerary_day(message)
    if re.search(r'\bwrong (?:place|stop|activity)\b', q) and day is None:
        if not any('activities' in r.get('changedFields', []) for r in history):
            return {'reply': 'No activity change is present in the retained history. Which saved version or other change do you want to inspect?'}
        state['adjustment']['pendingHistoryDay'] = True
        return {'reply': 'Which itinerary day contains the activity you want to restore? The saved trip will stay unchanged until you confirm a preview.'}
    scope = 'budget' if 'budget' in q else 'day' if day else 'trip'
    target = numbers[0] if len(numbers) == 1 else None
    if 'original' in q:
        target = 1
    if target is None:
        current = editable_snapshot(trip)
        for record in reversed(history):
            old = record['state']
            if scope == 'budget' and old.get('budgetLimit') == current.get('budgetLimit'):
                continue
            if scope == 'day' and [a for a in old.get('activities') or [] if str(a.get('dayNo')) == str(day)] == [
                    a for a in current['activities'] if str(a.get('dayNo')) == str(day)]:
                continue
            target = record['version']
            break
    if target is None:
        return {'reply': 'No retained version contains a different value for that part of the itinerary.'}
    try:
        snapshot = version_state(trip, target)
        if re.search(r'\b(?:show|view|earlier)\b', q) and not re.search(r'\b(?:restore|revert|undo|prefer)\b', q):
            return {'reply': f'Here is retained version {target}. Nothing has been restored.',
                    'tripPlan': _preview(trip, snapshot, target)}
        # Do not overwrite an in-progress draft with an implicit restoration target.
        if state.get('activePlan'):
            return {'reply': 'There is already an unconfirmed proposal. Compare or discard it with Undo changes before preparing a saved-version restoration.'}
        for collection in ('hotel_bookings', 'checkout_orders'):
            linked = read(collection, filters=[('travellerId', '==', trip['travellerId']), ('itineraryId', '==', trip['id'])], limit=1) or []
            if any(r.get('travellerId') == trip['travellerId'] and r.get('itineraryId') == trip['id'] for r in linked):
                raise HistoryConflict('This trip has linked booking or order records. Restoration is blocked.')
        patch = restore_patch(trip, target, scope=scope, day=day)
    except (HistoryConflict, ValueError, TypeError, KeyError) as error:
        return {'reply': str(error) if isinstance(error, HistoryConflict) else 'The retained version is incomplete; safe restoration is unavailable.'}
    except Exception:
        return {'reply': 'Revision or booking data is temporarily unavailable. No itinerary was restored; please retry.'}
    plan = {**editable_snapshot({**trip, **patch}),
            'activities': patch.get('activities', trip.get('activities') or []),
            'budgetEstimate': patch['budgetEstimate'], 'adjustmentTripId': trip['id'],
            'restoresVersion': target, 'restorationScope': scope, 'restorationDay': day,
            'restorationBaseVersion': trip.get('itineraryRevision', 1)}
    plan['draftId'] = sha256(json.dumps(plan, sort_keys=True, default=str).encode()).hexdigest()[:32]
    state['activePlan'] = plan
    state['adjustment'].pop('pendingHistoryDay', None)
    state['adjustment'].update(patch=patch, fingerprint=fingerprint(trip))
    return {'reply': f'Restore supported {scope} fields from retained version {target}? Review the comparison, then explicitly confirm. '
                     'Version 1 is the first captured state, not a guaranteed pre-feature original.\n' + compare(trip, {**trip, **patch}),
            'tripPlan': _preview(trip, editable_snapshot(trip), trip.get('itineraryRevision', 1)),
            'proposedPlan': plan, 'comparisonLabel': f'Restoration proposal from version {target} (not saved)'}
