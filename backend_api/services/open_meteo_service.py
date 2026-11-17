import requests
GEOCODING="https://geocoding-api.open-meteo.com/v1/search"
FORECAST="https://api.open-meteo.com/v1/forecast"

def geocode(name, *, timeout=20, country_code=None, count=5):
    params = {'name':name,'count':count,'language':'en','format':'json'}
    if country_code:
        params['countryCode'] = country_code
    r=requests.get(GEOCODING,params=params,timeout=timeout); r.raise_for_status(); return r.json().get('results',[])


def geocode_id(identity, *, timeout=8):
    identity = str(identity).removeprefix('geonames:')
    if not identity.isdigit() or not 0 < int(identity) < 2**31:
        raise ValueError('Invalid geographic identifier')
    r = requests.get('https://geocoding-api.open-meteo.com/v1/get', params={'id':identity,'language':'en'},timeout=timeout)
    r.raise_for_status()
    return r.json()

def _forecast(latitude, longitude, days=7, *, timeout=25):
    r=requests.get(FORECAST,params={'latitude':latitude,'longitude':longitude,'current':'temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m','daily':'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max','timezone':'auto','forecast_days':days},timeout=timeout); r.raise_for_status(); return r.json()

def retrieveCurrentWeather(destinationCoordinates):
    lat=destinationCoordinates.get('latitude') if isinstance(destinationCoordinates,dict) else destinationCoordinates[0]
    lon=destinationCoordinates.get('longitude') if isinstance(destinationCoordinates,dict) else destinationCoordinates[1]
    return _forecast(lat,lon,1)

def retrieveSevenDayForecast(destinationCoordinates, *, timeout=None):
    lat=destinationCoordinates.get('latitude') if isinstance(destinationCoordinates,dict) else destinationCoordinates[0]
    lon=destinationCoordinates.get('longitude') if isinstance(destinationCoordinates,dict) else destinationCoordinates[1]
    return _forecast(lat,lon,7) if timeout is None else _forecast(lat,lon,7,timeout=timeout)

forecast = lambda latitude, longitude, days=7: _forecast(latitude,longitude,days)
