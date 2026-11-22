"""Validated personal planning preferences; scheduling stays in the existing FR5 engine."""
from copy import deepcopy
from datetime import date, datetime, timedelta
from math import isfinite
import re

MODES = {'smart', 'manual', 'assisted'}
USER_LOCKS = ('fixed', 'locked', 'isLocked', 'userFixed', 'manualTime', 'manualOrder', 'userEdited')


class PlanningConflict(ValueError):
    def __init__(self, message, code='PLANNING_TIME_CONFLICT', action='edit_preferences'):
        super().__init__(message)
        self.code, self.action = code, action


def trip_days(trip):
    try:
        start, end = (date.fromisoformat(str(trip[k])[:10]) for k in ('startDate', 'endDate'))
        days = (end-start).days+1
        if not 1 <= days <= 14:
            raise ValueError()
        return days
    except (KeyError, TypeError, ValueError):
        raise ValueError('Choose a valid trip of 1–14 days.') from None


def clock(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
        raise ValueError('Choose a time in HH:MM format.')
    hour, minute = map(int, value.split(':'))
    return hour*60+minute


def time_text(value):
    return f'{value//60:02d}:{value%60:02d}'


def validate_preferences(value, trip):
    if not isinstance(value, dict) or set(value)-{'arrival', 'departure', 'transport', 'days'}:
        raise ValueError('Choose supported travel-day settings.')
    result = deepcopy(value)
    for kind, choices, field in [('arrival', {'practical', 'rest', 'custom', 'none'}, 'startTime'),
                                  ('departure', {'keep', 'light', 'custom', 'none'}, 'endTime')]:
        row = result.get(kind, {})
        if (not isinstance(row, dict) or set(row)-{'choice', field} or not isinstance(row.get('choice', ''), str)
                or row.get('choice', 'practical' if kind=='arrival' else 'keep') not in choices):
            raise ValueError('Choose a supported arrival or departure preference.')
        if field in row:
            clock(row[field])
        if row.get('choice') in {'rest', 'custom'} and field not in row:
            raise ValueError('Choose your preferred sightseeing time.')
        if field in row and row.get('choice') not in {'rest','custom'}:
            raise ValueError('Choose a custom timing option to supply a sightseeing time.')
    transport = result.get('transport', {})
    if not isinstance(transport, dict) or set(transport)-{'arrivalDate', 'arrivalTime', 'departureDate', 'departureTime', 'bufferMinutes'}:
        raise ValueError('Choose supported estimated transport times.')
    for kind in ('arrival', 'departure'):
        if (kind+'Date' in transport) != (kind+'Time' in transport):
            raise ValueError('Enter both a date and time for estimated transport.')
        if kind+'Date' in transport:
            try:
                day = date.fromisoformat(transport[kind+'Date'])
                if not str(trip['startDate'])[:10] <= day.isoformat() <= str(trip['endDate'])[:10]:
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError('Estimated transport dates must be inside this trip.') from None
            clock(transport[kind+'Time'])
    if 'bufferMinutes' in transport and (type(transport['bufferMinutes']) is not int or not 0 <= transport['bufferMinutes'] <= 720):
        raise ValueError('Choose a travel buffer of 0–720 minutes.')
    if all(key in transport for key in ('arrivalDate','arrivalTime','departureDate','departureTime')) and (
            transport['arrivalDate']+'T'+transport['arrivalTime']>=transport['departureDate']+'T'+transport['departureTime']):
        raise ValueError('Estimated departure must be after arrival.')
    days = result.get('days', [])
    if not isinstance(days, list) or len(days)>trip_days(trip):
        raise ValueError('Choose valid daily sightseeing windows.')
    seen = set()
    for row in days:
        if (not isinstance(row, dict) or set(row)-{'dayNo', 'startTime', 'endTime', 'restDay'}
                or type(row.get('dayNo')) is not int or not 1 <= row['dayNo'] <= trip_days(trip)
                or row['dayNo'] in seen or type(row.get('restDay', False)) is not bool):
            raise ValueError('Choose one valid window per trip day.')
        seen.add(row['dayNo'])
        for field in ('startTime','endTime'):
            if field in row:clock(row[field])
        if row.get('restDay') is not True:
            if clock(row.get('startTime')) >= clock(row.get('endTime')):
                raise ValueError('Sightseeing must start before it ends.')
    return result


def validate_blocks(value, trip):
    if not isinstance(value, list) or len(value)>56:
        raise ValueError('Keep at most 56 personal planning blocks.')
    result, seen = [], set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw)-{'blockId', 'type', 'label', 'dayNo', 'startTime', 'endTime',
                'durationMinutes', 'location', 'notes', 'locked', 'estimatedCost', 'boundary'}:
            raise ValueError('Choose supported personal block fields.')
        row = deepcopy(raw)
        identifier = row.get('blockId')
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', identifier) or identifier in seen:
            raise ValueError('Each personal block needs a unique identifier.')
        seen.add(identifier)
        if (not isinstance(row.get('type'), str) or row.get('type') not in {'rest', 'meal', 'hotel_luggage', 'free_time', 'transfer', 'custom'}
                or type(row.get('dayNo')) is not int or not 1 <= row['dayNo'] <= trip_days(trip)):
            raise ValueError('Choose a supported block and trip day.')
        for field, limit in [('label', 160), ('location', 300), ('notes', 1000)]:
            if field in row and (not isinstance(row[field], str) or len(row[field])>limit):
                raise ValueError('Personal block text is invalid or too long.')
        if not str(row.get('label', '')).strip():
            raise ValueError('Give this personal block a title.')
        if type(row.get('locked', True)) is not bool:
            raise ValueError('Choose whether the personal block is fixed.')
        if 'boundary' in row and row['boundary'] not in ('personal','destination'):
            raise ValueError('Choose a personal or destination planning block.')
        if ('startTime' in row) != ('endTime' in row):
            raise ValueError('Choose both block start and end times, or leave both unset.')
        if 'startTime' in row:
            duration = clock(row['endTime'])-clock(row['startTime'])
            if duration<=0:
                raise ValueError('A personal block must end after it starts.')
            row['durationMinutes'] = duration
        elif 'durationMinutes' in row and (type(row['durationMinutes']) is not int or not 1 <= row['durationMinutes'] <= 1440):
            raise ValueError('Choose a valid personal block duration.')
        cost = row.get('estimatedCost')
        if cost is not None and (type(cost) not in (int, float) or not isfinite(cost) or cost<0 or cost>1000000):
            raise ValueError('Enter a non-negative personal cost estimate in MYR.')
        row.update(estimatedCost=round(cost, 2) if cost is not None else None,
                   costProvenance='user_estimate' if cost is not None else 'unpriced', personal=True)
        result.append(row)
    for index, left in enumerate(result):
        for right in result[index+1:]:
            if (left['dayNo']==right['dayNo'] and 'startTime' in left and 'startTime' in right
                    and clock(left['startTime'])<clock(right['endTime']) and clock(right['startTime'])<clock(left['endTime'])):
                raise ValueError(f"Your {right.get('label', 'personal activity')} overlaps another personal activity on Day {right['dayNo']}.")
    return result


def settings_patch(changes, trip):
    if not isinstance(changes, dict) or set(changes)-{'planningMode', 'travelMode', 'travelDayPreferences', 'planningBlocks'}:
        raise ValueError('Choose supported personal planning settings.')
    patch = deepcopy(changes)
    if 'planningMode' in patch and (not isinstance(patch['planningMode'], str) or patch['planningMode'] not in MODES):
        raise ValueError('Choose Smart, Manual or Assisted Planning.')
    if 'travelMode' in patch:
        from sequence_contract.validators import TRAVEL_MODES
        if not isinstance(patch['travelMode'],str) or patch['travelMode'] not in TRAVEL_MODES:
            raise ValueError('Choose a supported travel arrangement.')
        if patch['travelMode']!=trip.get('travelMode') and (trip.get('selectedFlight') or any(trip.get(key) for key in ('flightBookingId','flightPaymentId','flightOrderId'))):
            raise ValueError('Manage or remove the original flight selection before changing travel arrangements.')
    if 'travelDayPreferences' in patch:
        patch['travelDayPreferences'] = validate_preferences(patch['travelDayPreferences'], trip)
    if 'planningBlocks' in patch:
        patch['planningBlocks'] = validate_blocks(patch['planningBlocks'], trip)
    return patch


def active(trip):
    return bool(trip.get('planningMode') or trip.get('travelDayPreferences') is not None or trip.get('planningBlocks'))


def personal_blocks(trip):
    """Read legacy personal blocks without treating generated breaks as user plans."""
    if isinstance(trip.get('planningBlocks'), list):
        return deepcopy(trip['planningBlocks'])
    from hashlib import sha256
    import json
    blocks = []
    fields = {'blockId','type','label','dayNo','startTime','endTime','durationMinutes',
              'location','notes','locked','estimatedCost','boundary'}
    for day in trip.get('dailySchedule') or []:
        for index, raw in enumerate(day.get('planningBlocks') or []):
            if raw.get('type') in {'meal_rest','intercity_transfer'}:
                continue
            row = {key:deepcopy(value) for key,value in raw.items() if key in fields}
            row.setdefault('dayNo',day.get('dayNo'))
            identity = json.dumps([row,index],sort_keys=True,default=str).encode()
            row.setdefault('blockId','legacy-'+sha256(identity).hexdigest()[:24])
            row.setdefault('type','custom')
            row.setdefault('label','Personal plan')
            blocks.append(row)
    return blocks


def transport_boundaries(trip, flight=None):
    from services.flight_itinerary_adjustment import flight_boundaries, _date_time
    if flight:
        return {**flight_boundaries(trip, flight), 'source':'selected_flight'}
    value = (trip.get('travelDayPreferences') or {}).get('transport') or {}
    arrival = _date_time(value.get('arrivalDate'), value.get('arrivalTime'))
    departure = _date_time(value.get('departureDate'), value.get('departureTime'))
    return {'arrival':arrival, 'departure':departure, 'arrivalLocal':arrival.isoformat() if arrival else None,
            'departureLocal':departure.isoformat() if departure else None, 'timezone':'Asia/Kuala_Lumpur',
            'source':'user_estimate' if arrival or departure else 'undecided'}


def confirmation_fingerprint(trip):
    from services.flight_itinerary_adjustment import fingerprint
    boundaries = transport_boundaries(trip, trip.get('selectedFlight'))
    return fingerprint({'start':trip.get('startDate'), 'end':trip.get('endDate'), 'mode':trip.get('travelMode'),
                        'arrival':boundaries.get('arrivalLocal'), 'departure':boundaries.get('departureLocal'),
                        'transport':(trip.get('travelDayPreferences') or {}).get('transport')})


def confirmation_status(trip):
    boundaries=transport_boundaries(trip,trip.get('selectedFlight'))
    confirmed=(trip.get('travelDayPreferences') or {}).get('confirmedFor')
    if boundaries.get('source')=='undecided' or not boundaries.get('arrival'):
        return 'provisional'
    if confirmed==confirmation_fingerprint(trip):return 'confirmed'
    return 'needs_review' if confirmed else 'provisional'


def apply_preferences(trip, availability, boundaries, assumptions):
    """Personal choices narrow hard transport bounds; they never override them."""
    if not active(trip) or availability['status']!='available':
        return availability
    prefs = trip.get('travelDayPreferences') or {}
    result = deepcopy(availability)
    overrides = {row['dayNo']:row for row in prefs.get('days', [])}
    arrival, departure = boundaries.get('arrival'), boundaries.get('departure')
    flight = boundaries.get('source') != 'user_estimate' and bool(trip.get('selectedFlight'))
    buffer = (prefs.get('transport') or {}).get('bufferMinutes', 0)
    arrival_buffer = assumptions['arrivalClearanceMinutes']+assumptions.get('arrivalTransferMinutes', 90) if flight else buffer
    departure_buffer = assumptions['departureTransferMinutes']+assumptions['departureCheckinMinutes'] if flight else buffer
    arrival_ready=arrival+timedelta(minutes=arrival_buffer) if arrival else None
    departure_ready=departure-timedelta(minutes=departure_buffer) if departure else None
    conflicts = []
    if trip.get('selectedFlight') and (not arrival or (trip['selectedFlight'].get('returnSegments') and not departure)):
        conflicts.append({'message':'Selected flight local times are incomplete. Travel-day timing remains provisional.'})
    for key, row in result['days'].items():
        day = row['dayNo']
        override = overrides.get(day, {})
        start, end = row['baseStartMinutes'], row['baseEndMinutes']
        if override and not override.get('restDay'):
            start, end = clock(override['startTime']), clock(override['endTime'])
        arrival_day = key==arrival.date().isoformat() if arrival else day==1
        departure_day = key==departure.date().isoformat() if departure else day==len(result['days'])
        hard_start = (1440 if key<arrival_ready.date().isoformat() else arrival_ready.hour*60+arrival_ready.minute
                      if key==arrival_ready.date().isoformat() else 0) if arrival_ready else 0
        hard_end = (0 if key>departure_ready.date().isoformat() else departure_ready.hour*60+departure_ready.minute
                    if key==departure_ready.date().isoformat() else 1440) if departure_ready else 1440
        requested_start = (prefs.get('arrival') or {}).get('startTime') if arrival_day else None
        requested_end = (prefs.get('departure') or {}).get('endTime') if departure_day else None
        if requested_start is not None:start=max(start,clock(requested_start))
        if requested_end is not None:end=min(end,clock(requested_end))
        rest = (override.get('restDay') is True or arrival_day and (prefs.get('arrival') or {}).get('choice')=='none'
                or departure_day and (prefs.get('departure') or {}).get('choice')=='none')
        if not rest:
            if start >= end and (requested_start is not None or requested_end is not None):
                conflicts.append({'dayNo':day, 'message':f'Day {day}: sightseeing must end after it starts on the same day.'})
            if (requested_start is not None and clock(requested_start)<hard_start) or (override and start<hard_start):
                earliest=arrival_ready.strftime('%d %b %H:%M') if arrival_ready and key!=arrival_ready.date().isoformat() else time_text(min(1439,hard_start))
                conflicts.append({'dayNo':day, 'message':f'Day {day}: sightseeing can start no earlier than {earliest} after travel buffers.'})
            if (requested_end is not None and clock(requested_end)>hard_end) or (override and end>hard_end):
                latest=departure_ready.strftime('%d %b %H:%M') if departure_ready and key!=departure_ready.date().isoformat() else time_text(max(0,hard_end))
                conflicts.append({'dayNo':day, 'message':f'Day {day}: sightseeing must finish by {latest} before departure buffers.'})
        start, end = max(start, hard_start), min(end, hard_end)
        if rest or (arrival and key<arrival.date().isoformat()) or (departure and key>departure.date().isoformat()):end=start
        row.update(startMinutes=start,endMinutes=end,availableMinutes=max(0,end-start),
                   earliestStartMinutes=hard_start,latestEndMinutes=hard_end,
                   availabilityStatus='available' if end>start else 'unavailable',
                   source='personal_and_transport_window',restDay=rest,
                   reservations=[deepcopy(block) for block in trip.get('planningBlocks') or [] if block.get('dayNo')==day])
        for block in row['reservations']:
            if not block.get('startTime'):continue
            context=block.get('boundary') or ('destination' if block.get('type') in {'custom','hotel_luggage'} else 'personal')
            if context!='destination':continue
            left,right=clock(block['startTime']),clock(block['endTime'])
            physical_start,physical_end=hard_start,hard_end
            if left<physical_start or right>physical_end:
                conflicts.append({'dayNo':day,'blockId':block.get('blockId'),
                    'message':f"Day {day}: personal block '{block.get('label','Personal plan')}' conflicts with travel buffers. Review its time; it will not be moved automatically."})
    result['preferenceConflicts']=conflicts
    result['confirmationStatus']=('confirmed' if prefs.get('confirmedFor')==confirmation_fingerprint(trip)
                                  and boundaries.get('source')!='undecided' and not conflicts else 'provisional')
    return result


def availability_for(trip):
    from services.flight_itinerary_adjustment import _availability, planning_assumptions
    return _availability(trip, transport_boundaries(trip, trip.get('selectedFlight')), planning_assumptions())


def reservations(trip, day, exclude=None):
    rows = [row for row in trip.get('planningBlocks') or [] if row.get('dayNo')==day and row.get('startTime')]
    from services.trip_budget_replan import protected_activity
    rows += [{'startTime':row.get('scheduledStartTime') or row.get('timeSlot'), 'endTime':row.get('scheduledEndTime')}
             for row in trip.get('activities') or [] if row.get('dayNo')==day and row.get('activityId')!=exclude
             and protected_activity(row) and row.get('scheduledEndTime')]
    return sorted([(clock(row['startTime']),clock(row['endTime'])) for row in rows if row.get('startTime')])


def skip_reservations(start, duration, windows):
    for left, right in windows:
        if start<right and start+duration>left:start=right
    return start


def public_preferences(raw):
    return {key:deepcopy(value) for key,value in (raw or {}).items() if key in {'arrival','departure','days','transport'}}


def commercial_activity(row):
    from services.trip_budget_replan import protected_activity
    return protected_activity({k:v for k,v in row.items() if k not in {*USER_LOCKS,'editProvenance'}})


def time_fixed(row):
    from services.trip_budget_replan import protected_activity
    return protected_activity(row) and (bool(row.get('scheduledStartTime'))
        or any(row.get(key) for key in USER_LOCKS) or row.get('editProvenance') in {'manual','user'}
        or commercial_activity({k:v for k,v in row.items() if k not in {'required','packageIncluded'}}))


def preservation_error(before, after, exclude=None):
    from services.trip_budget_replan import protected_activity
    by_id={row.get('activityId'):row for row in after.get('activities') or []}
    for row in before.get('activities') or []:
        if str(row.get('activityId'))==exclude:continue
        proposed=by_id.get(row.get('activityId'))
        if not proposed:return 'This change would displace another saved visit. Review a schedule proposal first.'
        if protected_activity(row) and any(row.get(k)!=proposed.get(k) for k in ('dayNo','scheduledStartTime','scheduledEndTime')):
            return 'This change would alter a fixed or protected visit. Review it manually first.'
    return None


def build_planning_preview(trip, flight, owner, preview_id, command, candidates=None):
    """Use the authoritative constraint planner, then merge only the selected days."""
    from sequence_contract.domain_functions import recalculateItinerary, calculateBudget, addActivity
    from services.flight_itinerary_adjustment import fingerprint, planning_assumptions
    from services.trip_budget_replan import protected_activity
    from services.itinerary_identity import same_attraction
    if not isinstance(command, dict) or set(command)-{'planningChanges','action','scope','dayNo','expectedItineraryRevision','recommendationGenerationId','refreshSuggestions','expectedLinkedGenerationId'}:
        raise ValueError('Choose supported planning options.')
    action, scope = command.get('action','settings'), command.get('scope','full')
    if not isinstance(action,str) or not isinstance(scope,str) or action not in {'settings','improve','regenerate'} or scope not in {'day','remaining','full'}:
        raise ValueError('Choose a supported scheduling action and scope.')
    count = trip_days(trip)
    day = command.get('dayNo', 1)
    if type(day) is not int or not 1 <= day <= count:
        raise ValueError('Choose a valid trip day.')
    expected = command.get('expectedItineraryRevision')
    if expected is not None and (type(expected) is not int or expected!=int(trip.get('itineraryRevision') or 1)):
        from services.itinerary_history import HistoryConflict
        raise HistoryConflict('This trip changed. Reopen it before previewing changes.')
    patch = settings_patch(command.get('planningChanges',{}), trip)
    if scope!='full' and patch:
        raise ValueError('Use the full planning-settings preview for changes that affect the whole trip.')
    proposed = {**deepcopy(trip), **patch}
    if 'planningBlocks' not in proposed:
        legacy = personal_blocks(trip)
        if legacy:
            proposed['planningBlocks'] = validate_blocks(legacy,trip)
    proposed.setdefault('travelDayPreferences',{})
    available = availability_for(proposed)
    targets = {day} if scope=='day' else set(range(day if scope=='remaining' else 1,count+1))
    before_rows = [*trip.get('activities',[]), *(trip.get('unscheduledSuggestions') or [])]
    target_rows = [deepcopy(row) for row in before_rows if row.get('dayNo',1) in targets]
    regenerated_ids = set()
    if action=='regenerate':
        if not candidates:
            raise PlanningConflict('No suitable replacement activities were found.', 'NO_REGENERATION_CANDIDATES', 'keep_current')
        generation = next((row.get('recommendationGenerationId') for row in candidates if row.get('recommendationGenerationId')),None)
        if generation:proposed['recommendationGenerationId']=generation
        target_rows = [row for row in target_rows if protected_activity(row)
                       or not (row.get('planningOrigin')=='generated' or row.get('recommendationGenerationId'))]
        working = {**proposed,'activities':deepcopy(before_rows)}
        for candidate in candidates:
            if any(same_attraction(candidate,row) for row in [*target_rows,
                    *(row for row in before_rows if row.get('dayNo',1) not in targets)]):continue
            prior = next((row for row in before_rows if same_attraction(candidate,row)),None)
            if prior:
                target_rows.append({**deepcopy(candidate),'activityId':prior['activityId'],'dayNo':min(targets),'planningOrigin':'generated'})
            else:
                working = addActivity(working,{**deepcopy(candidate),'dayNo':min(targets),'planningOrigin':'generated'})
                target_rows.append(working['activities'][-1])
            regenerated_ids.add(target_rows[-1]['activityId'])
            if len(target_rows)>=30:break
        proposed['nextActivitySeq'] = working.get('nextActivitySeq',trip.get('nextActivitySeq',1))
    mode_only = action=='settings' and not (set(patch)-{'planningMode'}) and (
        proposed.get('planningMode')=='manual' or proposed.get('planningMode')==trip.get('planningMode'))
    if not mode_only:
        prefs = public_preferences(proposed.get('travelDayPreferences'))
        overrides = {row['dayNo']:row for row in prefs.get('days',[])}
        for number in set(range(1,count+1))-targets:overrides[number]={'dayNo':number,'restDay':True}
        prefs['days'] = list(overrides.values())
        working = {**proposed,'activities':target_rows,'unscheduledSuggestions':[], 'travelDayPreferences':prefs}
        planned = recalculateItinerary(working,preserveOrder=action=='settings',respectDayAssignments=scope=='day' or action=='settings')
        proposed['activities'] = [deepcopy(row) for row in trip.get('activities',[]) if row.get('dayNo',1) not in targets]+planned['activities']
        proposed['unscheduledSuggestions'] = [deepcopy(row) for row in trip.get('unscheduledSuggestions') or [] if row.get('dayNo',1) not in targets]+planned.get('unscheduledSuggestions',[])
        original_days = {row['dayNo']:row for row in trip.get('dailySchedule') or []}
        proposed['dailySchedule'] = []
        for row in planned.get('dailySchedule',[]):
            number=row['dayNo']
            if number not in targets:
                row=deepcopy(original_days.get(number) or {**row,'activities':[
                    deepcopy(item) for item in trip.get('activities',[]) if item.get('dayNo',1)==number]})
                if number not in original_days:
                    from services.activity_pricing import activity_pricing
                    prices=[activity_pricing(item,trip.get('travellerCount')) for item in row['activities']]
                    row['knownEstimatedCost']=round(sum(item['effectiveCost'] for item in prices),2)
                    row['unpricedActivityCount']=sum(bool(item['pricingIssues']) for item in prices)
                    row['estimatedCost']=None if row['unpricedActivityCount'] else row['knownEstimatedCost']
            proposed['dailySchedule'].append(row)
    elif not proposed.get('dailySchedule'):
        proposed.update({k:v for k,v in recalculateItinerary(proposed).items() if k in {'dailySchedule','tripDays'}})
    conflicts = [row for row in available.get('preferenceConflicts') or [] if row.get('dayNo') in targets or row.get('dayNo') is None]
    if available['status']!='available':conflicts.append({'message':available.get('reason') or 'Travel timing is unavailable.'})
    after_by_id = {row.get('activityId'):row for row in proposed.get('activities',[])}
    changes = []
    for row in trip.get('activities',[]):
        after = after_by_id.get(row.get('activityId'))
        changed = not after or any(row.get(k)!=after.get(k) for k in ('dayNo','scheduledStartTime','scheduledEndTime'))
        if protected_activity(row) and changed:
            conflicts.append({'activityId':row.get('activityId'),'message':f"Your fixed or protected activity '{row.get('activityName','Visit')}' cannot be changed automatically."})
        changes.append({'activityId':row.get('activityId'),'activityName':row.get('activityName'),
            'kind':('removed' if action=='regenerate' and row.get('activityId') not in {x.get('activityId') for x in proposed.get('unscheduledSuggestions') or []} else 'unscheduled') if not after else 'moved' if changed else 'retained','protected':protected_activity(row),
            'from':{k:row.get(k) for k in ('dayNo','scheduledStartTime','scheduledEndTime')},
            'to':{k:after.get(k) for k in ('dayNo','scheduledStartTime','scheduledEndTime')} if after else None})
    old_ids = {row.get('activityId') for row in trip.get('activities',[])}
    changes += [{'activityId':row.get('activityId'),'activityName':row.get('activityName'),'kind':'added',
                 'to':{k:row.get(k) for k in ('dayNo','scheduledStartTime','scheduledEndTime')}}
                for row in proposed.get('activities',[]) if row.get('activityId') not in old_ids]
    for key in patch:
        if trip.get(key)!=proposed.get(key):changes.append({'activityName':{'planningMode':'Planning style','travelMode':'Travel arrangements','travelDayPreferences':'Travel-day preferences','planningBlocks':'Personal planning blocks'}[key],'kind':'updated'})
    prefs = deepcopy(proposed.get('travelDayPreferences') or {})
    if not mode_only:prefs['confirmedFor'] = confirmation_fingerprint(proposed)
    proposed['travelDayPreferences'] = prefs
    proposed['scheduledActivityCount']=len(proposed.get('activities',[]))
    proposed['unscheduledActivityCount']=len(proposed.get('unscheduledSuggestions') or [])
    proposed['budgetEstimate']=calculateBudget(proposed)
    if action=='regenerate' and (not regenerated_ids.intersection(after_by_id) or
            not any(row['kind'] in {'added','moved','removed'} for row in changes)):
        raise PlanningConflict('No suitable replacement activities were found.', 'NO_REGENERATION_CANDIDATES', 'keep_current')
    code = ('PROTECTED_ACTIVITY_CONFLICT' if any(row.get('activityId') for row in conflicts) else
            'FLIGHT_TIMING_INCOMPLETE' if any('incomplete' in row.get('message','').lower() for row in conflicts) else
            'PLANNING_TIME_CONFLICT') if conflicts else None
    return {'kind':'planning','previewId':preview_id,'tripId':trip['id'],'owner':owner,'status':'ready',
        'code':code,'nextAction': 'review_fixed_activity' if code=='PROTECTED_ACTIVITY_CONFLICT' else 'review_flight' if code=='FLIGHT_TIMING_INCOMPLETE' else 'edit_preferences' if conflicts else None,
        'canApply':not conflicts,'reason':' '.join(row['message'] for row in conflicts),
        'tripFingerprint':fingerprint(trip),'flightFingerprint':fingerprint(flight or {}),'before':deepcopy(trip),'after':proposed,
        'changes':changes,'newlyUnscheduled':proposed.get('unscheduledSuggestions',[]),'remainingConflicts':conflicts,
        'availability':available,'assumptions':planning_assumptions(),'scope':scope,'dayNo':day,'action':action,
        'budgetBefore':calculateBudget(trip),'budgetAfter':proposed['budgetEstimate'],
        'boundaries':{k:v for k,v in transport_boundaries(proposed,flight).items() if k not in {'arrival','departure'}},
        'verification':'Opening hours, local transfer durations and weather remain provisional where verified evidence is unavailable.'}
