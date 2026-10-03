import re
from flask import Blueprint, request, jsonify
from auth_utils import auth_required
from services.open_meteo_service import geocode, retrieveCurrentWeather, retrieveSevenDayForecast
from sequence_contract.validators import validateDestinationInput
from services.local_catalog import DESTINATIONS
from sequence_contract.firebase_firestore import retrieveRecord

bp = Blueprint('fr06_weather', __name__, url_prefix='/api/fr6')

@bp.get('/locations/search')
@auth_required(['traveller'])
def location_search():
    name = request.args.get('q', '').strip()
    if not validateDestinationInput(name):
        return jsonify({'ok': False, 'error': 'q is required'}), 400
    try:
        results = geocode(name)
        if not results:
            lowered = name.lower()
            all_places = list(DESTINATIONS)
            try:
                cached = retrieveRecord('destination_cache', limit=100) or []
                all_places.extend(cached)
            except Exception:
                pass

            for p in all_places:
                p_name = str(p.get('title') or p.get('name') or '').lower()
                if lowered in p_name or p_name in lowered:
                    gps = p.get('gps_coordinates') or {}
                    if isinstance(gps, dict) and gps.get('latitude') and gps.get('longitude'):
                        return jsonify({
                            'ok': True,
                            'results': [{
                                'name': p.get('title') or p.get('name') or name,
                                'latitude': float(gps['latitude']),
                                'longitude': float(gps['longitude']),
                                'country': 'Malaysia',
                                'admin1': p.get('city') or p.get('state') or 'Penang',
                            }]
                        })

            for suffix in ['temple', 'hill', 'beach', 'museum', 'park', 'tower', 'sanctuary', 'mosque', 'resort', 'market']:
                clean = re.sub(rf'\b{suffix}\b', '', lowered, flags=re.I).strip()
                if clean and clean != lowered:
                    results = geocode(clean)
                    if results:
                        break

            if not results:
                for parent in ['George Town', 'Penang', 'Kuala Lumpur', 'Melaka', 'Langkawi', 'Ipoh', 'Kota Kinabalu', 'Kuching', 'Johor Bahru']:
                    if parent.lower() in lowered:
                        results = geocode(parent)
                        if results:
                            break

        return jsonify({'ok': True, 'results': results})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 502
@bp.get('/weather')
@auth_required(['traveller'])
def weather():
    lat=request.args.get('latitude'); lon=request.args.get('longitude')
    if not lat or not lon: return jsonify({'ok':False,'error':'latitude and longitude are required'}),400
    coords={'latitude':lat,'longitude':lon}
    try: return jsonify({'ok':True,'weather':retrieveSevenDayForecast(coords),'current':retrieveCurrentWeather(coords)})
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),502
