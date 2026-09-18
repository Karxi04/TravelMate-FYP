import os
import re
import requests

SERP_ENDPOINT = "https://serpapi.com/search"


def _key():
    return os.getenv("SERPAPI_KEY", "").strip()


def _request(params):
    key = _key()
    if not key:
        raise RuntimeError("SERPAPI_KEY is not configured")
    response = requests.get(
        SERP_ENDPOINT,
        params={**params, 'api_key': key},
        timeout=40,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and data.get('error'):
        raise RuntimeError(str(data['error']))
    return data


def retrieveDestinationResults(searchInput, location="Malaysia"):
    return _request({
        'engine': 'google_maps',
        'q': searchInput,
        'location': location,
        'hl': 'en',
    })


def retrieveDestinationDetails(placeId, referenceType='place_id'):
    """Retrieve the full Google Maps place result for one destination.

    `placeId` is kept as the public sequence-contract parameter name. Search results can
    expose either `place_id` or `data_cid`, so the backend may tell this adapter which
    provider reference it is passing without changing the sequence function name.
    """
    params = {
        'engine': 'google_maps',
        'type': 'place',
        'hl': 'en',
    }
    if referenceType == 'data_cid':
        params['data_cid'] = placeId
    else:
        params['place_id'] = placeId
    return _request(params)


def retrieveRatingsAndReviews(placeId, referenceType='place_id'):
    data = retrieveDestinationDetails(placeId, referenceType)
    place = data.get('place_results', {}) if isinstance(data, dict) else {}
    return {
        'rating': place.get('rating'),
        'reviews': place.get('reviews'),
        'user_reviews': place.get('user_reviews', []),
        'review_summary': (place.get('user_reviews') or {}).get('summary') if isinstance(place.get('user_reviews'), dict) else None,
        'raw': data,
    }


def retrieveLocationAndTravelTime(selectedDestinations):
    """Return location metadata already carried by selected destination records.

    SerpApi Maps results frequently include GPS coordinates. The smart itinerary engine can
    use those coordinates for an explainable nearby-grouping heuristic without requiring a
    second paid directions request for every pair of activities.
    """
    return [
        {
            'destinationId': x.get('destinationId') or x.get('place_id'),
            'gps_coordinates': x.get('gps_coordinates') or x.get('gpsCoordinates'),
            'title': x.get('activityName') or x.get('title') or x.get('name'),
        }
        for x in (selectedDestinations or [])
    ]


def _airport_id(value):
    if isinstance(value, dict):
        return str(value.get('id') or value.get('name') or '')
    return str(value or '')


def _time(value):
    if isinstance(value, dict):
        return str(value.get('time') or '')
    return str(value or '')


def _stops_from_legs(legs):
    if not legs:
        return 0
    return max(0, len(legs) - 1)


def normalizeFlightResult(item, index=0, currency='MYR'):
    item = dict(item or {})
    legs = item.get('flights') or []
    first = dict(legs[0]) if legs else {}
    last = dict(legs[-1]) if legs else first
    dep = first.get('departure_airport') or {}
    arr = last.get('arrival_airport') or {}
    stops = _stops_from_legs(legs)
    airline = first.get('airline') or item.get('airline') or 'Flight'
    flight_number = first.get('flight_number') or item.get('flight_number') or ''
    duration = item.get('total_duration') or first.get('duration') or 0
    booking_token = item.get('booking_token') or item.get('departure_token') or ''
    raw_id = f"{airline}-{flight_number}-{_time(dep)}-{index}"
    safe_id = re.sub(r'[^a-zA-Z0-9_-]+', '_', raw_id).strip('_')
    return {
        'id': safe_id or f'flight_{index}',
        'airline': airline,
        'flightNumber': flight_number,
        'departureAirport': _airport_id(dep),
        'arrivalAirport': _airport_id(arr),
        'departureTime': _time(dep),
        'arrivalTime': _time(arr),
        'durationMinutes': duration,
        'stops': stops,
        'stopText': 'Nonstop' if stops == 0 else f'{stops} stop' + ('s' if stops != 1 else ''),
        'price': item.get('price') or 0,
        'currency': item.get('currency') or currency,
        'bookingToken': booking_token,
        'departureToken': item.get('departure_token') or '',
        'carbonEmissions': item.get('carbon_emissions'),
        'raw': item,
    }


def normalizeFlightResults(data, currency='MYR'):
    raw = list((data or {}).get('best_flights', []) or []) + list((data or {}).get('other_flights', []) or [])
    return [normalizeFlightResult(item, index, currency) for index, item in enumerate(raw)]


def retrieveFlightOptions(departureId, arrivalId, outboundDate, returnDate=None, currency='MYR', travelClass=1, stops=None):
    # SerpApi requires type=2 for a one-way search. Round trip type=1 requires return_date.
    params = {
        'engine': 'google_flights',
        'departure_id': departureId,
        'arrival_id': arrivalId,
        'outbound_date': outboundDate,
        'currency': currency,
        'hl': 'en',
        'type': 1 if returnDate else 2,
        'travel_class': int(travelClass or 1),
    }
    if returnDate:
        params['return_date'] = returnDate
    if stops not in (None, ''):
        params['stops'] = stops
    data = _request(params)
    return {
        'items': normalizeFlightResults(data, currency),
        'search_metadata': data.get('search_metadata', {}),
        'search_parameters': data.get('search_parameters', {}),
        'raw': data,
    }


def retrieveFlightDetails(flightReference):
    # The search result already contains the provider detail used by the MVP comparison UI.
    return flightReference


def retrieveLowerCostFlights(departureId, arrivalId, outboundDate, returnDate=None, currency='MYR'):
    data = retrieveFlightOptions(departureId, arrivalId, outboundDate, returnDate, currency)
    flights = list(data.get('items', []))
    return sorted(flights, key=lambda x: float(x.get('price', 999999) or 999999))[:5]


# Backward-compatible aliases
maps_search = retrieveDestinationResults
maps_place = retrieveDestinationDetails
flights_search = retrieveFlightOptions
