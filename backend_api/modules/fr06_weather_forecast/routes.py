import math
from flask import Blueprint, request, jsonify
from auth_utils import auth_required
from services.open_meteo_service import geocode, retrieveCurrentWeather, retrieveSevenDayForecast
from services.malaysia_boundary import coordinate_state
from services.weather_locations import weather_locations, search_weather_locations, selected_weather_point

bp = Blueprint('fr06_weather', __name__, url_prefix='/api/fr6')


@bp.get('/locations')
@auth_required(['traveller'])
def local_locations():
    return jsonify({'ok': True, 'results': weather_locations()})


@bp.get('/locations/search')
@auth_required(['traveller'])
def location_search():
    name = request.args.get('q', '').strip()
    if not 2 <= len(name) <= 150:
        return jsonify({'ok': False, 'error': 'Enter a Malaysian city or locality.'}), 400
    try:
        return jsonify({'ok': True, 'results': search_weather_locations(
            name, remote=request.args.get('remote') == 'true')})
    except Exception:
        return jsonify({'ok': False, 'error': 'Location search is unavailable. Please try again.'}), 502


@bp.get('/weather')
@auth_required(['traveller'])
def weather():
    try:
        lat, lon = float(request.args.get('latitude')), float(request.args.get('longitude'))
        if not (math.isfinite(lat) and math.isfinite(lon) and coordinate_state(lat, lon)):
            raise ValueError
        identity = request.args.get('locationId')
        if request.args.get('locationName') and not identity:
            raise ValueError
        if identity:
            point = selected_weather_point(identity)
            if (not point or point['requiresCity'] or abs(point['latitude'] - lat) > .00001
                    or abs(point['longitude'] - lon) > .00001
                    or (request.args.get('locationName') and request.args['locationName'] != point['label'])):
                raise ValueError
    except (ValueError, TypeError, OverflowError):
        return jsonify({'ok': False, 'error': 'Choose a verified Malaysian city or locality for weather.'}), 400
    try:
        forecast = retrieveSevenDayForecast({'latitude': lat, 'longitude': lon})
        return jsonify({'ok': True, 'weather': forecast, 'current': forecast})
    except Exception:
        return jsonify({'ok': False, 'error': 'Weather provider is unavailable. Please try again.'}), 502
