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
        if "hasn't returned any results" in str(data['error']).lower():
            return {'local_results': []}
        raise RuntimeError(str(data['error']))
    return data


def retrieveDestinationResults(searchInput, location="Malaysia", coordinates=None, start=0):
    query = (searchInput or "").strip()
    loc = (location or "").strip()
    if loc and loc.lower() not in query.lower():
        query = f"{query} in {loc}"
    params = {
        'engine': 'google_maps',
        'q': query,
        'hl': 'en',
        'gl': 'my',
    }
    if start:
        params['start'] = start
    coordinates = coordinates if isinstance(coordinates, dict) else {}
    latitude = coordinates.get('latitude')
    longitude = coordinates.get('longitude')
    if latitude is not None and longitude is not None:
        params['ll'] = f'@{latitude},{longitude},11z'
    return _request(params)


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


def _airport(value):
    value = value if isinstance(value, dict) else {}
    raw_time = _time(value).strip()
    inferred_date = None
    clock_time = raw_time or None
    if re.match(r'^\d{4}-\d{2}-\d{2}[ T]', raw_time):
        inferred_date, clock_time = raw_time[:10], raw_time[11:].strip() or None
    return {
        'code': str(value.get('id') or '').strip() or None,
        'name': str(value.get('name') or '').strip() or None,
        'date': str(value.get('date') or '').strip() or inferred_date,
        'time': clock_time,
        'localDateTime': raw_time or None,
    }


def _segment(leg):
    leg = dict(leg or {})
    dep = _airport(leg.get('departure_airport'))
    arr = _airport(leg.get('arrival_airport'))
    airline = str(leg.get('airline') or '').strip() or None
    operating = str(leg.get('operating_airline') or '').strip() or None
    return {
        'departureAirportCode': dep['code'],
        'departureAirportName': dep['name'],
        'departureDate': dep['date'],
        'departureTime': dep['time'],
        'departureLocalDateTime': dep['localDateTime'],
        'arrivalAirportCode': arr['code'],
        'arrivalAirportName': arr['name'],
        'arrivalDate': arr['date'],
        'arrivalTime': arr['time'],
        'arrivalLocalDateTime': arr['localDateTime'],
        'durationMinutes': leg.get('duration'),
        'airline': airline,
        'operatingAirline': operating,
        'flightNumber': str(leg.get('flight_number') or '').strip() or None,
        'travelClass': leg.get('travel_class'),
        'aircraft': leg.get('airplane') or leg.get('aircraft'),
        'departureTerminal': leg.get('departure_airport', {}).get('terminal') if isinstance(leg.get('departure_airport'), dict) else None,
        'arrivalTerminal': leg.get('arrival_airport', {}).get('terminal') if isinstance(leg.get('arrival_airport'), dict) else None,
        'extensions': leg.get('extensions') if isinstance(leg.get('extensions'), list) else [],
    }


def _stops_from_legs(legs):
    if not legs:
        return 0
    return max(0, len(legs) - 1)


def normalizeFlightResult(item, index=0, currency='MYR', traveller_count=None, price_basis=None):
    item = dict(item or {})
    legs = item.get('flights') or []
    outbound_legs = item.get('outbound_flights') or item.get('outboundFlights')
    return_legs = item.get('return_flights') or item.get('returnFlights')
    if outbound_legs is None and isinstance(item.get('itineraries'), list):
        itineraries = item.get('itineraries')
        outbound_legs = (itineraries[0] or {}).get('segments', []) if itineraries else []
        return_legs = (itineraries[1] or {}).get('segments', []) if len(itineraries) > 1 else []
    outbound_legs = list(outbound_legs or legs)
    return_legs = list(return_legs or [])
    all_legs = outbound_legs + return_legs
    first = dict(outbound_legs[0]) if outbound_legs else {}
    last = dict((return_legs or outbound_legs)[-1]) if (return_legs or outbound_legs) else first
    dep = first.get('departure_airport') or {}
    arr = last.get('arrival_airport') or {}
    stops = _stops_from_legs(outbound_legs)
    airline = first.get('airline') or item.get('airline') or 'Flight'
    flight_number = first.get('flight_number') or item.get('flight_number') or ''
    duration = item.get('total_duration') or sum(
        int(x.get('duration') or 0) for x in all_legs if str(x.get('duration') or '').isdigit()
    ) or None
    booking_token = item.get('booking_token') or ''
    raw_id = f"{airline}-{flight_number}-{_time(dep)}-{index}"
    safe_id = re.sub(r'[^a-zA-Z0-9_-]+', '_', raw_id).strip('_')
    price = item.get('price')
    try:
        price = float(price) if price is not None and str(price).strip() else None
    except (TypeError, ValueError):
        price = None
    actual_currency = str(item.get('currency') or currency or '').strip().upper() or None
    requested_adults = traveller_count if traveller_count is not None else item.get('traveller_count')
    try:
        requested_adults = max(1, int(requested_adults)) if requested_adults is not None else None
    except (TypeError, ValueError):
        requested_adults = None
    result = {
        'id': safe_id or f'flight_{index}',
        'airline': airline,
        'flightNumber': flight_number,
        'departureAirport': _airport_id(dep) or None,
        'arrivalAirport': _airport_id(arr) or None,
        'departureAirportName': dep.get('name') if isinstance(dep, dict) else None,
        'arrivalAirportName': arr.get('name') if isinstance(arr, dict) else None,
        'departureTime': _airport(dep)['time'],
        'arrivalTime': _airport(arr)['time'],
        'outboundDate': _airport(dep)['date'],
        'returnDate': (_airport(return_legs[0].get('departure_airport'))['date'] if return_legs else None),
        'durationMinutes': duration,
        'stops': stops,
        'stopText': 'Nonstop' if stops == 0 else f'{stops} stop' + ('s' if stops != 1 else ''),
        'price': price,
        'currency': actual_currency,
        'currencyStatus': 'known' if actual_currency else 'unknown',
        'priceStatus': 'available' if price is not None else 'unknown',
        'priceBasis': (
            item.get('price_basis') or price_basis or (
                'provider_round_trip_ticket_price_requested_adults' if return_legs
                else 'itinerary_total'
            )
            if price is not None else None
        ),
        'travellerCount': requested_adults,
        'passengerComposition': {'adults': requested_adults} if requested_adults is not None else None,
        'passengerPriceBasis': item.get('passenger_price_basis') or 'provider_response_requested_adults' if requested_adults is not None else None,
        'priceScope': 'provider_ticket_price' if price is not None else None,
        'priceSemanticsStatus': 'provider_response_requested_adults' if price is not None and requested_adults is not None else None,
        'outboundSegments': [_segment(x) for x in outbound_legs],
        'returnSegments': [_segment(x) for x in return_legs],
        'tripType': 'round_trip' if return_legs else 'one_way',
        'roundTripComplete': bool(return_legs) if item.get('return_flights') is not None or item.get('returnFlights') is not None or item.get('itineraries') is not None else None,
        'timezoneStatus': 'local_time_only',
        'bookingToken': booking_token,
        'departureToken': item.get('departure_token') or '',
        'returnToken': item.get('return_token') or '',
        'carbonEmissions': item.get('carbon_emissions'),
    }
    result['stopText'] = 'Nonstop' if stops == 0 else f'{stops} stop' + ('s' if stops != 1 else '')
    return result


def normalizeFlightResults(data, currency='MYR', traveller_count=None, price_basis=None):
    raw = list((data or {}).get('best_flights', []) or []) + list((data or {}).get('other_flights', []) or [])
    items = []
    seen = set()
    for index, row in enumerate(raw):
        item = normalizeFlightResult(row, index, currency, traveller_count, price_basis)
        signature = (
            tuple(tuple(segment.get(key) for key in ('flightNumber', 'departureAirportCode',
                'arrivalAirportCode', 'departureDate', 'departureTime', 'arrivalDate', 'arrivalTime', 'travelClass'))
                for leg in ('outboundSegments', 'returnSegments') for segment in item[leg]),
            item['price'], item['currency'], item['departureToken'], item['bookingToken'],
        )
        if signature in seen:
            continue
        seen.add(signature)
        items.append(item)
    return items


def retrieveFlightOptions(departureId, arrivalId, outboundDate, returnDate=None, currency='MYR', travelClass=1, stops=None, adults=1, departureToken=None, *, deepSearch=False, showHidden=False):
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
    if adults is not None:
        params['adults'] = max(1, int(adults))
    if returnDate:
        params['return_date'] = returnDate
    if departureToken:
        params['departure_token'] = departureToken
    if stops not in (None, ''):
        params['stops'] = stops
    if deepSearch:
        params['deep_search'] = 'true'
    if showHidden:
        params['show_hidden'] = 'true'
    data = _request(params)
    return {
        'items': normalizeFlightResults(data, currency, adults),
        'search_metadata': data.get('search_metadata', {}),
        'search_parameters': data.get('search_parameters', {}),
        'raw': data,
    }


def retrieveFlightReturns(departureToken, departureId, arrivalId, outboundDate, returnDate, currency='MYR', adults=1, travelClass=1, stops=None):
    return retrieveFlightOptions(
        departureId, arrivalId, outboundDate, returnDate, currency=currency,
        travelClass=travelClass, stops=stops, adults=adults,
        departureToken=departureToken,
    )


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
