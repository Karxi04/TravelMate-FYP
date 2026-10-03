import pytest
from unittest.mock import patch

def test_weather_landmark_lookup_finds_coordinates(client, mock_traveller_auth):
    with patch('modules.fr06_weather_forecast.routes.geocode') as mock_geocode:
        # Open-Meteo returns empty for landmark name
        mock_geocode.return_value = []

        res = client.get(
            '/api/fr6/locations/search?q=Kek Lok Si Temple',
            headers={'Authorization': 'Bearer valid_test_token'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert len(data['results']) > 0
        assert data['results'][0]['name'] == 'Kek Lok Si Temple'
        assert abs(data['results'][0]['latitude'] - 5.3992) < 0.01

def test_weather_forecast_valid_coords(client, mock_traveller_auth):
    sample_weather = {
        'daily': {'time': ['2026-09-05'], 'temperature_2m_max': [31.5]},
        'current': {'temperature_2m': 29.0}
    }
    with patch('modules.fr06_weather_forecast.routes.retrieveSevenDayForecast') as mock_seven, \
         patch('modules.fr06_weather_forecast.routes.retrieveCurrentWeather') as mock_current:
        mock_seven.return_value = sample_weather['daily']
        mock_current.return_value = sample_weather['current']

        res = client.get(
            '/api/fr6/weather?latitude=5.3992&longitude=100.2736',
            headers={'Authorization': 'Bearer valid_test_token'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert 'weather' in data
        assert 'current' in data
