import requests
GEOCODING="https://geocoding-api.open-meteo.com/v1/search"
FORECAST="https://api.open-meteo.com/v1/forecast"

def geocode(name):
    r=requests.get(GEOCODING,params={'name':name,'count':5,'language':'en','format':'json'},timeout=20); r.raise_for_status(); return r.json().get('results',[])

def _forecast(latitude, longitude, days=7):
    r=requests.get(FORECAST,params={'latitude':latitude,'longitude':longitude,'current':'temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m','daily':'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max','timezone':'auto','forecast_days':days},timeout=25); r.raise_for_status(); return r.json()

def retrieveCurrentWeather(destinationCoordinates):
    lat=destinationCoordinates.get('latitude') if isinstance(destinationCoordinates,dict) else destinationCoordinates[0]
    lon=destinationCoordinates.get('longitude') if isinstance(destinationCoordinates,dict) else destinationCoordinates[1]
    return _forecast(lat,lon,1)

def retrieveSevenDayForecast(destinationCoordinates):
    lat=destinationCoordinates.get('latitude') if isinstance(destinationCoordinates,dict) else destinationCoordinates[0]
    lon=destinationCoordinates.get('longitude') if isinstance(destinationCoordinates,dict) else destinationCoordinates[1]
    return _forecast(lat,lon,7)

forecast = lambda latitude, longitude, days=7: _forecast(latitude,longitude,days)
