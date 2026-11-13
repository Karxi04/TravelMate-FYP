from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock

import pytest

from services import packing_weather, packing_checklist_service as service
from test_packing_checklist import NOW, forecast, trip, weather_trip


@pytest.fixture(autouse=True)
def isolated_provider(monkeypatch):
    monkeypatch.setattr(packing_weather, '_cache', OrderedDict())
    geocode = Mock(return_value=[{'name': 'Butterworth', 'country_code': 'MY',
                                 'admin1': 'Penang', 'latitude': 5.4, 'longitude': 100.36}])
    provider = Mock(return_value=forecast(latitude=5.4, longitude=100.36))
    monkeypatch.setattr(packing_weather, 'geocode', geocode)
    monkeypatch.setattr(packing_weather, 'retrieveSevenDayForecast', provider)
    return geocode, provider


def test_stale_forecast_refreshes_and_cached_result_survives_second_read(isolated_provider):
    geo, provider = isolated_provider
    value = weather_trip(forecast(fetchedAt=(NOW - timedelta(days=2)).isoformat()))
    before = deepcopy(value)
    fresh = packing_weather.packing_weather_trip(value, NOW)
    cached = packing_weather.packing_weather_trip(value, NOW, fetch=False)
    assert service.weather_context(fresh, NOW)[0]['status'] == 'available'
    assert service.weather_context(cached, NOW)[0]['status'] == 'available'
    assert value == before
    provider.assert_called_once_with({'latitude': 5.4, 'longitude': 100.3}, timeout=5)
    geo.assert_not_called()


def test_valid_trip_forecast_is_reused_without_provider(isolated_provider):
    value = weather_trip(forecast())
    assert service.weather_context(packing_weather.packing_weather_trip(value, NOW), NOW)[0]['status'] == 'available'
    for mock in isolated_provider:
        mock.assert_not_called()


def test_purchased_package_uses_scoped_geocode_and_itinerary_evidence(isolated_provider):
    geo, provider = isolated_provider
    value = trip(packageTrip=True, destinationArea='Butterworth, Penang', activities=[],
                 packageSnapshot={'amount': 100, 'itineraryDays': [{'activities': ['City heritage walk']}]})
    before = deepcopy(value)
    fresh = packing_weather.packing_weather_trip(value, NOW)
    items, _, weather, _ = service.suggestions(fresh, None, NOW)
    assert weather['status'] == 'available'
    assert any(row['itemId'] == 'walking_shoes' and row['source'] == 'activity' for row in items)
    assert value == before
    geo.assert_called_once_with('Butterworth', timeout=3)
    provider.assert_called_once_with({'latitude': 5.4, 'longitude': 100.36}, timeout=5)


def test_future_or_unresolved_trip_has_specific_advice_and_no_provider(isolated_provider):
    for value, phrase in [
        (trip(startDate='2026-12-02', endDate='2026-12-04'), 'outside the seven-day'),
        (trip(destinationArea='Unknown place'), 'confirmed forecast location'),
    ]:
        items, _, weather, _ = service.suggestions(packing_weather.packing_weather_trip(value, NOW), None, NOW)
        assert weather['status'] == 'unavailable' and phrase in weather['message']
        assert all(row['source'] != 'weather' for row in items)
    for mock in isolated_provider:
        mock.assert_not_called()


def test_provider_failure_is_cached_and_unverified_forecasts_stay_unavailable(isolated_provider):
    geo, provider = isolated_provider
    value = trip(destinationArea='Butterworth')
    provider.side_effect = OSError('sanitized failure')
    for _ in range(2):
        view = packing_weather.packing_weather_trip(value, NOW)
        assert 'temporarily unavailable' in service.weather_context(view, NOW)[0]['message']
    provider.assert_called_once()
    geo.assert_called_once()


def test_conflicting_geocode_is_rejected(isolated_provider):
    geo, provider = isolated_provider
    geo.return_value = [{'name': 'Butterworth', 'country_code': 'MY',
                         'admin1': 'Kedah', 'latitude': 5.4, 'longitude': 100.36}]
    view = packing_weather.packing_weather_trip(trip(destinationArea='Butterworth'), NOW)
    assert 'confirmed forecast location' in service.weather_context(view, NOW)[0]['message']
    provider.assert_not_called()


def test_langkawi_matches_the_islands_and_excludes_the_airport(isolated_provider):
    geo, provider = isolated_provider
    geo.return_value = [
        {'name': 'Langkawit', 'country_code': 'MY', 'admin1': 'Sabah',
         'feature_code': 'PPL', 'latitude': 5.68333, 'longitude': 115.93333},
        {'name': 'Langkawi Islands', 'country_code': 'MY', 'admin1': 'Kedah',
         'feature_code': 'ISLS', 'latitude': 6.34567, 'longitude': 99.86349},
        {'name': 'Langkawi International Airport', 'country_code': 'MY', 'admin1': 'Kedah',
         'feature_code': 'AIRP', 'latitude': 6.32973, 'longitude': 99.72867},
    ]
    provider.return_value = forecast(latitude=6.34567, longitude=99.86349)
    view = packing_weather.packing_weather_trip(trip(destinationArea='Langkawi, Kedah'), NOW)
    assert service.weather_context(view, NOW)[0]['status'] == 'available'
    provider.assert_called_once_with({'latitude': 6.34567, 'longitude': 99.86349}, timeout=5)


def test_concurrent_reads_share_the_same_forecast_request(isolated_provider):
    _, provider = isolated_provider
    value = weather_trip(forecast(fetchedAt=(NOW - timedelta(days=2)).isoformat()))
    start = Barrier(2)

    def check():
        start.wait(timeout=3)
        view = packing_weather.packing_weather_trip(value, NOW)
        return service.weather_context(view, NOW)[0]['status']

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda _: check(), range(2))) == ['available', 'available']
    provider.assert_called_once()
