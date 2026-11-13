"""Deterministic personal suggestions; never acquires weather or alters a Trip."""
import hashlib
import json
import math
import re
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

CATEGORIES = [
    {'id': 'documents', 'name': 'Travel Documents'},
    {'id': 'clothing', 'name': 'Clothing'},
    {'id': 'personal_care', 'name': 'Personal Care & Toiletries'},
    {'id': 'electronics', 'name': 'Electronics'},
    {'id': 'activity', 'name': 'Activity Essentials'},
    {'id': 'weather', 'name': 'Weather Essentials'},
    {'id': 'miscellaneous', 'name': 'Miscellaneous'},
]
CATEGORY_IDS = {category['id'] for category in CATEGORIES}
MAX_ITEMS = 100
RULE_VERSION = 1
FORECAST_DAYS = 7
MYT = timezone(timedelta(hours=8))


class PackingError(Exception):
    def __init__(self, message, status=400, revision=None):
        super().__init__(message)
        self.status = status
        self.revision = revision


def checklist_id(uid, trip_id):
    return hashlib.sha256(json.dumps([uid, trip_id], separators=(',', ':')).encode()).hexdigest()


def valid_trip_id(value):
    return (isinstance(value, str) and 0 < len(value.encode()) <= 512
            and value not in {'.', '..'} and '/' not in value
            and not any(ord(char) < 32 for char in value))


def _date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _object(value):
    return value if isinstance(value, dict) else {}


def _number(value, minimum, maximum):
    return type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum


def _country(value):
    # Deliberately bounded: unknown country text does not prove border crossing.
    names = {'malaysia': 'MY', 'singapore': 'SG', 'thailand': 'TH', 'indonesia': 'ID',
             'brunei': 'BN', 'vietnam': 'VN', 'philippines': 'PH', 'australia': 'AU'}
    text = str(value or '').strip()
    return names.get(text.lower()) or (text.upper() if text.upper() in names.values() else None)


def weather_context(trip, now):
    context = _object(trip.get('generationContext'))
    forecast = _object(context.get('forecastData'))
    unavailable = {'status': 'unavailable', 'source': None, 'dates': [],
                   'message': trip.get('_packingWeatherMessage') or
                   'Current trip weather is unavailable; weather items are general precautions.'}
    source = forecast.get('source')
    if not isinstance(source, str) or source not in {'open-meteo', 'open_meteo'} or forecast.get('unavailable'):
        return unavailable, {}
    try:
        stamp = datetime.fromisoformat(str(forecast.get('fetchedAt') or forecast.get('retrievedAt')).replace('Z', '+00:00'))
        if stamp.tzinfo is None or not -timedelta(minutes=5) <= now - stamp <= timedelta(hours=24):
            return unavailable, {}
    except (TypeError, ValueError):
        return unavailable, {}
    coordinates = _object(context.get('destinationCoordinates'))
    for key, bound in (('latitude', 90), ('longitude', 180)):
        if (not _number(forecast.get(key), -bound, bound)
                or not _number(coordinates.get(key), -bound, bound)
                or abs(forecast[key] - coordinates[key]) > 0.15):
            return unavailable, {}
    start, end = _date(trip.get('startDate')), _date(trip.get('endDate'))
    if not start or not end or end < start or (end - start).days > 365:
        return unavailable, {}
    today = now.astimezone(MYT).date()
    daily = _object(forecast.get('daily'))
    dates = daily.get('time')
    if not isinstance(dates, list):
        return unavailable, {}
    usable = {}
    for index, raw in enumerate(dates[:16]):
        day = _date(raw)
        if not day or not max(start, today) <= day <= end:
            continue
        row = {}
        for key, bounds in [('weather_code', (0, 99)), ('precipitation_probability_max', (0, 100)),
                            ('temperature_2m_max', (-50, 60)), ('temperature_2m_min', (-50, 60))]:
            values = daily.get(key)
            value = values[index] if isinstance(values, list) and index < len(values) else None
            if _number(value, *bounds):
                row[key] = value
        if row:
            usable[day.isoformat()] = row
    if not usable:
        return unavailable, {}
    all_days = (end - start).days + 1
    return {'status': 'available' if len(usable) == all_days else 'partial', 'source': source,
            'fetchedAt': stamp.isoformat(), 'dates': sorted(usable),
            'message': ('Weather suggestions use only the covered trip dates. Other days are outside the available forecast.'
                        if len(usable) < all_days else 'Weather suggestions use the covered trip dates.')}, usable


def suggestions(trip, preferences, now):
    start, end = _date(trip.get('startDate')), _date(trip.get('endDate'))
    days = (end - start).days + 1 if start and end and end >= start else None
    if days is None:
        duration = trip.get('tripDays') or trip.get('durationDays')
        days = duration if type(duration) is int and 1 <= duration <= 365 else 1
    days = min(days, 365)
    activities = [row for row in (trip.get('activities') or []) if isinstance(row, dict)] if isinstance(trip.get('activities'), list) else []
    for day in trip.get('dailySchedule', []) if isinstance(trip.get('dailySchedule'), list) else []:
        if isinstance(day, dict) and isinstance(day.get('activities'), list):
            activities.extend(row for row in day['activities'] if isinstance(row, dict))
    snapshot = _object(trip.get('packageSnapshot'))
    days_in_snapshot = snapshot.get('itineraryDays')
    if isinstance(days_in_snapshot, list):
        for day in days_in_snapshot:
            if isinstance(day, dict) and isinstance(day.get('activities'), list):
                activities.extend(row for row in day['activities'] if isinstance(row, (dict, str)))
    text = ' '.join((row[:300] if isinstance(row, str) else ' '.join(
        str(row.get(key) or '')[:300] for key in ('activityName', 'title', 'name', 'category', 'type')
    )) for row in activities[:500]).lower()
    pref = _object(preferences)
    interests = pref.get('interests')
    preference_text = ' '.join(str(x)[:100] for x in interests[:30]).lower() if isinstance(interests, list) else ''
    themes = {}
    for theme, pattern in [('beach', r'\b(beach|swimming|snorkel\w*|pantai)\b'),
                           ('hiking', r'\b(hik\w*|trek\w*|trail|nature)\b'),
                           ('city', r'\b(city|heritage|culture|cultural|museum|walking|sightseeing)\b')]:
        if re.search(pattern, text):
            themes[theme] = 'activity'
        elif re.search(pattern, preference_text):
            themes[theme] = 'preference'
    items = {}

    def add(key, name, category, quantity=1, source='general', reason='General travel suggestion.'):
        if key not in items:
            items[key] = {'itemId': key, 'name': name, 'category': category, 'quantity': quantity,
                          'isPacked': False, 'isCustom': False, 'source': source, 'reason': reason,
                          'suppressed': False, 'applicable': True, 'userEditedFields': []}

    add('travel_documents', 'Identification and travel confirmations', 'documents')
    add('clothing_changes', 'Clothing changes', 'clothing', min(days, 14), 'trip',
        f'Approximately one change per day for your {days}-day trip; adjust for laundry.')
    add('toiletries', 'Everyday toiletries', 'personal_care')
    add('phone_charger', 'Phone charger', 'electronics')
    for theme, origin in themes.items():
        reason = f'Suggested for {theme} activities in your itinerary.' if origin == 'activity' else f'Suggested for your declared {theme} interest.'
        if theme == 'beach':
            add('swimwear', 'Swimwear', 'activity', source=origin, reason=reason)
            add('towel', 'Towel', 'activity', source=origin, reason=reason)
            add('sunscreen', 'Sunscreen', 'personal_care', source=origin, reason=reason)
            add('beach_footwear', 'Suitable beach footwear', 'activity', source=origin, reason=reason)
        if theme in {'hiking', 'city'}:
            add('walking_shoes', 'Comfortable walking shoes', 'activity', source=origin, reason=reason)
            add('water_bottle', 'Refillable water bottle', 'activity', source=origin, reason=reason)
        if theme == 'hiking':
            add('outdoor_clothing', 'Comfortable outdoor clothing', 'clothing', source=origin, reason=reason)
        if theme == 'city':
            add('day_bag', 'Small day bag', 'activity', source=origin, reason=reason)
            add('power_bank', 'Power bank', 'electronics', source=origin, reason=reason)
    origin_country = _country(trip.get('originCountry') or _object(trip.get('originLocation')).get('country'))
    destination_country = _country(trip.get('destinationCountry'))
    international = bool(origin_country and destination_country and origin_country != destination_country)
    if international:
        add('passport', 'Passport and border-entry documents', 'documents', source='trip',
            reason='Your declared origin and destination countries differ; check entry requirements.')
        add('adapter', 'Check whether a travel adapter is needed', 'electronics', source='trip',
            reason='Check socket compatibility for your international journey.')
    weather, rows = weather_context(trip, now)
    if any(r.get('precipitation_probability_max', -1) >= 55 or r.get('weather_code', -1) in range(51, 100) for r in rows.values()):
        add('rain_protection', 'Umbrella or raincoat', 'weather', source='weather', reason='Rain is forecast on a covered trip date.')
    else:
        add('rain_protection', 'Compact umbrella or raincoat', 'weather', reason='General rain precaution; not a forecast.')
    if any(r.get('temperature_2m_max', -99) >= 30 for r in rows.values()):
        add('water_bottle', 'Refillable water bottle', 'weather', source='weather', reason='Hot conditions are forecast on a covered trip date.')
    if any(r.get('temperature_2m_min', 99) <= 20 for r in rows.values()):
        add('light_jacket', 'Light jacket', 'weather', source='weather', reason='Cooler conditions are forecast on a covered trip date.')
    if themes and any(r.get('weather_code') in (0, 1) for r in rows.values()):
        add('sun_hat', 'Sun hat', 'weather', source='weather', reason='Sunny conditions are forecast; useful for outdoor activities.')
        add('sunscreen', 'Sunscreen', 'weather', source='weather', reason='Sunny conditions are forecast; useful for outdoor activities.')
    context = {'destination': str(trip.get('destinationArea') or trip.get('destinationName') or snapshot.get('destination') or '')[:160],
               'startDate': start.isoformat() if start else None, 'endDate': end.isoformat() if end else None,
               'durationDays': days, 'international': international}
    fingerprint = hashlib.sha256(json.dumps([RULE_VERSION, context, list(items.values()), weather],
                                           sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return list(items.values()), context, weather, fingerprint


def _revision(payload, current):
    revision = payload.get('expectedRevision')
    if type(revision) is not int or revision < 1:
        raise PackingError('A positive expectedRevision is required.')
    if revision != current['revision']:
        raise PackingError('Checklist changed. Reload and try again.', 409, current['revision'])


def mutate(current, trip, preferences, uid, trip_id, payload, now):
    action = payload.get('action', 'generate')
    if action in {'generate', 'refresh'}:
        allowed = {'action'} if action == 'generate' else {'action', 'expectedRevision'}
        if not set(payload) <= allowed:
            raise PackingError('Unsupported checklist fields.')
        if current and action == 'generate':
            return current, {'created': False, 'added': 0, 'inactive': 0}
        if action == 'refresh':
            if not current:
                raise PackingError('Generate a checklist first.', 404)
            _revision(payload, current)
        generated, context, weather, fingerprint = suggestions(trip, preferences, now)
        previous = deepcopy(current['items']) if current else []
        by_id = {item['itemId']: item for item in previous}
        merged = []
        for item in generated:
            old = by_id.pop(item['itemId'], None)
            if old:
                for key in old.get('userEditedFields', []):
                    item[key] = old[key]
                item.update(isPacked=old['isPacked'], suppressed=old['suppressed'],
                            userEditedFields=old.get('userEditedFields', []))
            merged.append(item)
        for old in by_id.values():
            if not old['isCustom']:
                old['applicable'] = False
            merged.append(old)
        if len(merged) > MAX_ITEMS:
            raise PackingError('Checklist item limit reached. Remove unused custom items first.')
        record = {**(current or {}), 'id': checklist_id(uid, trip_id), 'travellerId': uid, 'tripId': trip_id, 'schemaVersion': 1,
                  'ruleVersion': RULE_VERSION, 'tripContext': context, 'weatherContext': weather,
                  'contextFingerprint': fingerprint, 'items': merged}
        summary = {'created': not bool(current), 'added': sum(i['itemId'] not in {x['itemId'] for x in previous} for i in merged),
                   'inactive': sum(not i['applicable'] and not i['isCustom'] for i in merged)}
        if current and record == current:
            return current, summary
        record.update(revision=(current['revision'] + 1 if current else 1), updatedAt=now.isoformat(),
                      generatedAt=now.isoformat(), createdAt=current['createdAt'] if current else now.isoformat())
        return record, summary
    if action not in {'add', 'update', 'remove', 'restore'}:
        raise PackingError('Unsupported checklist action.')
    if not current:
        raise PackingError('Generate a checklist first.', 404)
    _revision(payload, current)
    fields = {'name', 'category', 'quantity', 'isPacked'}
    allowed = {'action', 'expectedRevision', 'itemId'} | (fields if action in {'add', 'update'} else set())
    if not set(payload) <= allowed:
        raise PackingError('Unsupported or protected item fields.')
    item_id = payload.get('itemId')
    if not isinstance(item_id, str) or len(item_id) > 80:
        raise PackingError('A valid itemId is required.')
    updates = {k: v for k, v in payload.items() if k in fields}
    if action in {'add', 'update'}:
        if not updates or (action == 'add' and not {'name', 'category'} <= set(updates)):
            raise PackingError('Provide supported item fields.')
        if 'name' in updates:
            name = updates['name']
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100 or any(ord(c) < 32 or c in '<>' for c in name):
                raise PackingError('Use a plain item name of 1–100 characters.')
            updates['name'] = name.strip()
        if 'category' in updates and (not isinstance(updates['category'], str) or updates['category'] not in CATEGORY_IDS):
            raise PackingError('Choose a supported category.')
        if 'quantity' in updates and (type(updates['quantity']) is not int or not 1 <= updates['quantity'] <= 30):
            raise PackingError('Quantity must be a whole number from 1 to 30.')
        if 'isPacked' in updates and type(updates['isPacked']) is not bool:
            raise PackingError('isPacked must be true or false.')
    record = deepcopy(current)
    item = next((i for i in record['items'] if i['itemId'] == item_id), None)
    if action == 'add':
        if not re.fullmatch(r'custom_[A-Za-z0-9_-]{1,64}', item_id):
            raise PackingError('Custom itemId must begin custom_ and use letters, numbers, _ or -.')
        if item:
            raise PackingError('Item already exists.', 409, current['revision'])
        if len(record['items']) >= MAX_ITEMS:
            raise PackingError('Checklist item limit reached.')
        record['items'].append({'itemId': item_id, 'name': updates['name'], 'category': updates['category'],
                                'quantity': updates.get('quantity', 1), 'isPacked': updates.get('isPacked', False),
                                'isCustom': True, 'source': 'custom', 'reason': 'Added by you.',
                                'applicable': True, 'suppressed': False, 'userEditedFields': [],})
    else:
        if not item:
            raise PackingError('Packing item not found.', 404)
        if action == 'update':
            item.update(updates)
            item['userEditedFields'] = sorted(set(item['userEditedFields']) | (set(updates) - {'isPacked'}))
        elif action == 'remove' and item['isCustom']:
            record['items'].remove(item)
        else:
            item['suppressed'] = action == 'remove'
    if record != current:
        record.update(revision=current['revision'] + 1, updatedAt=now.isoformat())
    return record, {'created': False, 'added': int(action == 'add'), 'inactive': 0}


def response_dto(current, trip, preferences, now):
    _, _, weather, fingerprint = suggestions(trip, preferences, now)
    if current is None:
        return {'state': 'not_generated', 'checklist': None, 'categories': CATEGORIES,
                'progress': {'totalItems': 0, 'packedItems': 0, 'unpackedItems': 0, 'completionPercentage': 0},
                'weatherContext': weather, 'needsRefresh': False}
    items = deepcopy(current['items'])
    for item in items:
        if item['source'] == 'weather' and current.get('contextFingerprint') != fingerprint:
            item.update(source='general', reason='General precaution; refresh to reassess current trip weather.')
    active = [i for i in items if i['applicable'] and not i['suppressed']]
    packed = sum(i['isPacked'] for i in active)
    record = {k: v for k, v in current.items() if k not in {'items', 'contextFingerprint', 'travellerId', 'id'}}
    record.update(checklistId=current['id'], items=items)
    return {'state': 'ready' if active else 'empty', 'checklist': record, 'categories': CATEGORIES,
            'progress': {'totalItems': len(active), 'packedItems': packed, 'unpackedItems': len(active) - packed,
                         'completionPercentage': round(100 * packed / len(active), 1) if active else 0},
            'weatherContext': weather, 'needsRefresh': current.get('contextFingerprint') != fingerprint}
