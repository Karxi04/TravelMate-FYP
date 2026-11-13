"""Resolve weather for checklist views without altering the saved trip."""
from collections import OrderedDict
from datetime import timedelta
from threading import Event, Lock
from time import monotonic

from services.malaysian_locality import _state_from_coordinates, normalize_destination_scope
from services.open_meteo_service import geocode, retrieveSevenDayForecast
from services.packing_checklist_service import FORECAST_DAYS, MYT, _date, _number, _object, weather_context


_cache = OrderedDict()
_cache_lock = Lock()
_inflight = {}


def _cached(key, load, fetch):
    with _cache_lock:
        cached = _cache.get(key)
        if cached and cached[0] > monotonic():
            _cache.move_to_end(key)
            return cached[1]
        if not fetch:
            return None
        pending = _inflight.get(key)
        if pending is None:
            _inflight[key] = Event()
    if pending is not None:
        return _cached(key, load, False) if pending.wait(6) else None
    value = None
    try:
        value = load()
    except (ValueError, TypeError, KeyError, OSError):
        pass
    finally:
        with _cache_lock:
            _cache[key] = (monotonic() + (1800 if value else 120), value)
            _cache.move_to_end(key)
            if len(_cache) > 128:
                _cache.popitem(last=False)
            _inflight.pop(key).set()
    return value


def _coordinates(value, scope):
    value = _object(value)
    lat, lon = value.get('latitude'), value.get('longitude')
    if not _number(lat, -90, 90) or not _number(lon, -180, 180) or (lat, lon) == (0, 0):
        return None
    state = _state_from_coordinates(lat, lon)
    if state and scope.get('state') and state != scope['state']:
        return None
    return {'latitude': lat, 'longitude': lon}


def _geocoded(scope):
    name = scope.get('city') or scope.get('state')
    if not name:
        return None
    matches = set()
    for row in geocode(name, timeout=3):
        if not isinstance(row, dict) or row.get('country_code') != 'MY':
            continue
        actual = normalize_destination_scope(row.get('name'))
        admin = normalize_destination_scope(row.get('admin1'))
        if row.get('feature_code') == 'AIRP':
            continue
        if ((scope.get('city') and actual['city'] != scope['city'])
                or (not scope.get('city') and actual['state'] != scope['state'])
                or (admin['state'] and admin['state'] != scope['state'])):
            continue
        coords = _coordinates(row, scope)
        if coords:
            matches.add((coords['latitude'], coords['longitude']))
    if len(matches) == 1:
        lat, lon = matches.pop()
        return {'latitude': lat, 'longitude': lon}
    return None


def packing_weather_trip(trip, now, *, fetch=True):
    context = _object(trip.get('generationContext'))
    package = _object(trip.get('packageSnapshot'))
    destination = trip.get('destinationArea') or trip.get('destinationName') or package.get('destination')
    scope = normalize_destination_scope(destination)
    start, end = _date(trip.get('startDate')), _date(trip.get('endDate'))
    today = now.astimezone(MYT).date()

    def unavailable(message):
        return {**trip, 'generationContext': {**context, 'forecastData': {}},
                '_packingWeatherMessage': message + ' Packing suggestions use general precautions.'}

    if not start or not end or end < start or (end - start).days > 365:
        return unavailable('Valid trip dates are needed to find a forecast.')
    if end < today or start >= today + timedelta(days=FORECAST_DAYS):
        return unavailable('These trip dates are outside the seven-day Open-Meteo forecast window.')

    coords = next((value for raw in (
        trip.get('destinationCoordinates'), package.get('destinationCoordinates'),
        context.get('destinationCoordinates'), trip.get('gps_coordinates'),
    ) if (value := _coordinates(raw, scope))), None)
    if not coords and scope.get('state'):
        coords = _cached(('location', scope['scopeKey']), lambda: _geocoded(scope), fetch)
    if not coords:
        return unavailable('The trip destination does not have a confirmed forecast location.')

    view = {**trip, 'generationContext': {**context, 'destinationCoordinates': coords}}
    if weather_context(view, now)[1]:
        return view

    def load():
        data = retrieveSevenDayForecast(coords, timeout=5)
        if not isinstance(data, dict) or not isinstance(data.get('daily'), dict):
            return None
        return {**data, 'source': 'open-meteo', 'fetchedAt': now.isoformat()}

    forecast = _cached(('forecast', coords['latitude'], coords['longitude'], today), load, fetch)
    if forecast:
        view['generationContext']['forecastData'] = forecast
        if weather_context(view, now)[1]:
            return view
        return unavailable('Open-Meteo has no usable measurements for the trip dates.')
    return unavailable('Current Open-Meteo weather is temporarily unavailable.')
