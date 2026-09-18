from flask import Blueprint, request, jsonify
from auth_utils import auth_required
from services.open_meteo_service import geocode, retrieveCurrentWeather, retrieveSevenDayForecast
from sequence_contract.validators import validateDestinationInput
bp=Blueprint('fr06_weather',__name__,url_prefix='/api/fr6')
@bp.get('/locations/search')
@auth_required(['traveller'])
def location_search():
    name=request.args.get('q','').strip()
    if not validateDestinationInput(name): return jsonify({'ok':False,'error':'q is required'}),400
    try: return jsonify({'ok':True,'results':geocode(name)})
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),502
@bp.get('/weather')
@auth_required(['traveller'])
def weather():
    lat=request.args.get('latitude'); lon=request.args.get('longitude')
    if not lat or not lon: return jsonify({'ok':False,'error':'latitude and longitude are required'}),400
    coords={'latitude':lat,'longitude':lon}
    try: return jsonify({'ok':True,'weather':retrieveSevenDayForecast(coords),'current':retrieveCurrentWeather(coords)})
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}),502
