import os
import math
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5
from flask import Blueprint, request, jsonify, g
from auth_utils import auth_required
from services.serpapi_service import retrieveFlightOptions, retrieveFlightReturns, retrieveFlightDetails, normalizeFlightResult
from services.local_catalog import FLIGHTS
from sequence_contract.validators import validateFlightSearchCriteria
from sequence_contract.domain_functions import applyFlightFilter, compareSelectedFlights, calculateBudget
from sequence_contract.firebase_firestore import retrieveRecord, storeRecord, updateRecord

bp = Blueprint('fr07_flights', __name__, url_prefix='/api/fr7')

# Quotes are short-lived server-owned records; the local cache is only a read-through optimization.
_FLIGHT_QUOTES = {}
_FLIGHT_QUOTES_COLLECTION = 'flight_quotes'
_DEFAULT_QUOTE_TTL_SECONDS = 900
_MIN_QUOTE_TTL_SECONDS = 60
_MAX_QUOTE_TTL_SECONDS = 3600
_TEST_DURABLE_QUOTES = {}

_PRIVATE_FLIGHT_KEYS = {
    'bookingToken', 'departureToken', 'returnToken', '_departureToken',
    '_outboundOptionId', 'booking_token', 'departure_token', 'return_token',
    'continuationToken', 'providerTokens', 'raw', 'providerResponse',
    'booking_request',
}


def reset_flight_quotes():
    _FLIGHT_QUOTES.clear()
    _TEST_DURABLE_QUOTES.clear()


def _testing_mode():
    return os.getenv('TRAVELMATE_TESTING', '').lower() in {'1', 'true', 'yes'}


def _sample_mode():
    return os.getenv('FLIGHT_SAMPLE_MODE', '').lower() in {'1', 'true', 'yes'} or (_testing_mode() and _fallback_mode())


def _now():
    return datetime.now(timezone.utc).isoformat()


def _quote_ttl_seconds():
    try:
        value = int(os.getenv('FLIGHT_QUOTE_TTL_SECONDS', _DEFAULT_QUOTE_TTL_SECONDS))
    except (TypeError, ValueError):
        value = _DEFAULT_QUOTE_TTL_SECONDS
    return min(_MAX_QUOTE_TTL_SECONDS, max(_MIN_QUOTE_TTL_SECONDS, value))


def _expires_at(retrieved_at):
    return (datetime.fromisoformat(retrieved_at.replace('Z', '+00:00')) + timedelta(seconds=_quote_ttl_seconds())).isoformat()


def _quote_doc_id(uid, search_id):
    return f'{uid}_{search_id}'


def _sanitize_flight_snapshot(value):
    if isinstance(value, list):
        return [_sanitize_flight_snapshot(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: _sanitize_flight_snapshot(item)
        for key, item in value.items()
        if key not in _PRIVATE_FLIGHT_KEYS and key != 'returnOptions'
    }


def _public_option(item):
    return _sanitize_flight_snapshot(dict(item or {}))


def _persist_quote(quote):
    record = dict(quote)
    record.pop('items', None)
    record['items'] = quote.get('items', [])
    try:
        storeRecord(_FLIGHT_QUOTES_COLLECTION, record, _quote_doc_id(quote['travellerId'], quote['id']))
    except Exception:
        if not _testing_mode():
            raise
        _TEST_DURABLE_QUOTES[_quote_doc_id(quote['travellerId'], quote['id'])] = record


def _quote_expiry_status(quote):
    raw = quote.get('expiresAt') if isinstance(quote, dict) else None
    if not raw:
        return 'invalid_flight_quote'
    try:
        expires_at = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return 'invalid_flight_quote'
    return 'flight_quote_expired' if expires_at <= datetime.now(timezone.utc) else None


def _load_quote_state(search_id):
    if not search_id:
        return None, 'invalid_flight_quote'
    quote = _FLIGHT_QUOTES.get(search_id)
    if quote and quote.get('travellerId') == g.uid:
        error = _quote_expiry_status(quote)
        return (None, error) if error else (quote, None)
    doc_id = _quote_doc_id(g.uid, search_id)
    try:
        quote = retrieveRecord(_FLIGHT_QUOTES_COLLECTION, doc_id)
    except Exception:
        quote = _TEST_DURABLE_QUOTES.get(doc_id) if _testing_mode() else None
    if not quote or quote.get('travellerId') != g.uid:
        return None, 'invalid_flight_quote'
    error = _quote_expiry_status(quote)
    if error:
        return None, error
    _FLIGHT_QUOTES[search_id] = quote
    return quote, None


def _load_quote(search_id):
    return _load_quote_state(search_id)[0]


def _flight_error(code, message, status=409):
    return jsonify({'ok': False, 'code': code, 'error': message}), status


def _normalise_sample(item, criteria, index):
    item = dict(item or {})
    item.update({
        'outboundDate': criteria['outbound_date'],
        'returnDate': criteria.get('return_date'),
        'currency': str(item.get('currency') or '').upper() or None,
        'currencyStatus': 'known' if item.get('currency') else 'unknown',
        'priceStatus': 'available' if item.get('price') is not None else 'unknown',
        'priceBasis': 'sample_itinerary_total' if item.get('price') is not None else None,
        'travellerCount': criteria['traveller_count'],
        'source': 'sample_fixture',
        'isSample': True,
        'sourceLabel': 'Explicit sample fixture (not a current schedule)',
        'retrievedAt': _now(),
        'cacheStatus': 'fixture',
        'transactionMode': 'planning_reference',
        'timezoneStatus': 'local_time_only',
        'outboundSegments': [{
            'departureAirportCode': item.get('departureAirport'),
            'arrivalAirportCode': item.get('arrivalAirport'),
            'departureDate': criteria['outbound_date'],
            'arrivalDate': criteria['outbound_date'],
            'departureTime': item.get('departureTime'),
            'arrivalTime': item.get('arrivalTime'),
            'airline': item.get('airline'),
            'flightNumber': item.get('flightNumber'),
            'durationMinutes': item.get('durationMinutes'),
            'operatingAirline': item.get('airline'),
            'travelClass': item.get('cabinClass'),
        }],
        'returnSegments': [],
        'roundTripComplete': False if criteria.get('return_date') else None,
        'quoteCompleteness': 'return_selection_pending' if criteria.get('return_date') else 'complete',
        'selectionStage': 'outbound_candidate' if criteria.get('return_date') else 'complete',
        'budgetEligible': not bool(criteria.get('return_date')),
        'priceScope': 'sample_fixture' if item.get('price') is not None else None,
        'priceSemanticsStatus': 'sample_fixture' if item.get('price') is not None else None,
    })
    return item


def _criteria(data, currency, travellers, travel_class, stops):
    return {
        'departure_id': data['departure_id'], 'arrival_id': data['arrival_id'],
        'outbound_date': data['outbound_date'], 'return_date': data.get('return_date'),
        'currency': str(currency or '').upper() or None, 'traveller_count': travellers,
        'travel_class': travel_class, 'stops': stops,
        'passengerComposition': {'adults': travellers},
        'airportValidationStatus': 'provider_result_required',
    }


def _store_quote(criteria, items, source):
    search_id = f'flight_search_{uuid4().hex}'
    retrieved_at = _now()
    safe_items = []
    for index, item in enumerate(items):
        safe = dict(item)
        safe['optionId'] = safe.get('optionId') or safe.get('id') or f'flight_option_{index}'
        safe['id'] = safe['optionId']
        if criteria.get('return_date') and not safe.get('returnSegments'):
            safe['quoteCompleteness'] = 'return_selection_pending'
            safe['selectionStage'] = 'outbound_candidate'
            safe['budgetEligible'] = False
            safe['roundTripComplete'] = False
            if safe.get('price') is not None:
                safe['priceBasis'] = 'provider_round_trip_candidate_price_requested_adults'
        else:
            safe['quoteCompleteness'] = 'complete'
            safe['selectionStage'] = 'complete'
            safe['budgetEligible'] = True
        safe_items.append(safe)
    quote = {
        'id': search_id, 'travellerId': g.uid, 'criteria': dict(criteria),
        'source': source, 'retrievedAt': retrieved_at, 'expiresAt': _expires_at(retrieved_at),
        'quoteVersion': 1, 'selectionStage': 'outbound_candidate' if any(not x.get('returnSegments') for x in safe_items) else 'complete',
        'freshnessStatus': 'fixture' if source == 'sample_fixture' else 'provider_cache_possible',
        'planningOnly': True,
        'items': safe_items, 'returnOptions': {}, 'completedOptions': {},
    }
    _FLIGHT_QUOTES[search_id] = quote
    _persist_quote(quote)
    return search_id, safe_items


def _quote_item(payload):
    search_id = str(payload.get('searchId') or payload.get('quoteId') or '').strip()
    option_id = str(payload.get('optionId') or '').strip()
    quote, error = _load_quote_state(search_id)
    if not quote:
        return None, None, error
    candidates = list(quote.get('items') or []) + list((quote.get('completedOptions') or {}).values())
    option = next((x for x in candidates if x.get('optionId') == option_id or x.get('id') == option_id), None)
    return quote, option, None


def _completed_option(quote, outbound, return_option):
    existing = next((item for item in (quote.get('completedOptions') or {}).values()
                     if item.get('outboundOptionId') == outbound.get('optionId')
                     and item.get('returnOptionId') == return_option.get('optionId')), None)
    if existing:
        return existing
    amount = return_option.get('price')
    try:
        amount = float(amount)
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return None
    criteria = quote.get('criteria') or {}
    currency = str(return_option.get('currency') or '').upper()
    travellers = int(criteria.get('traveller_count') or 0)
    composition = return_option.get('passengerComposition') or {}
    outbound_composition = outbound.get('passengerComposition') or {}
    if (currency != str(criteria.get('currency') or '').upper() or not travellers
            or return_option.get('travellerCount') != travellers
            or composition.get('adults') != travellers
            or outbound.get('travellerCount') != travellers
            or outbound_composition.get('adults') != travellers
            or return_option.get('currencyStatus') != 'known'
            or return_option.get('priceScope') != 'provider_ticket_price'
            or return_option.get('priceSemanticsStatus') != 'provider_response_requested_adults'):
        return None
    completed_id = 'flight_completed_' + uuid5(
        NAMESPACE_URL,
        f"{quote['id']}:{outbound.get('optionId')}:{return_option.get('optionId')}",
    ).hex
    completed = {
        **dict(outbound),
        'id': completed_id,
        'optionId': completed_id,
        'completedOptionId': completed_id,
        'searchId': quote['id'],
        'outboundOptionId': outbound.get('optionId'),
        'returnOptionId': return_option.get('optionId'),
        'outboundSegments': list(outbound.get('outboundSegments') or []),
        'returnSegments': list(return_option.get('returnSegments') or []),
        'price': amount,
        'currency': currency,
        'currencyStatus': 'known',
        'priceStatus': 'available',
        'priceBasis': 'provider_round_trip_ticket_price_requested_adults',
        'priceScope': 'provider_ticket_price',
        'priceSemanticsStatus': 'provider_response_requested_adults',
        'travellerCount': travellers,
        'passengerComposition': {'adults': travellers},
        'requestedTravelClass': criteria.get('travel_class'),
        'tripType': 'round_trip',
        'returnDate': criteria.get('return_date'),
        'roundTripComplete': True,
        'quoteCompleteness': 'complete',
        'selectionStage': 'complete_round_trip',
        'budgetEligible': True,
        'retrievedAt': quote.get('retrievedAt'),
        'expiresAt': quote.get('expiresAt'),
        'freshnessStatus': quote.get('freshnessStatus'),
        'planningOnly': True,
        'transactionMode': 'planning_reference',
    }
    quote.setdefault('completedOptions', {})[completed_id] = completed
    return completed


def _return_segments(option, criteria):
    """Accept only the reverse leg requested for the selected outbound quote."""
    expected_departure = str(criteria.get('arrival_id') or '').upper()
    expected_arrival = str(criteria.get('departure_id') or '').upper()
    expected_date = str(criteria.get('return_date') or '')[:10]
    for segments in (option.get('returnSegments'), option.get('outboundSegments')):
        segments = list(segments or [])
        if not segments:
            continue
        first, last = segments[0], segments[-1]
        departure = str(first.get('departureAirportCode') or first.get('departureAirport') or '').upper()
        arrival = str(last.get('arrivalAirportCode') or last.get('arrivalAirport') or '').upper()
        date = str(first.get('departureDate') or '')[:10]
        if departure == expected_departure and arrival == expected_arrival and date == expected_date:
            return segments
    return []


def _safe_client_fixture(flight):
    allowed = {'id', 'airline', 'flightNumber', 'departureAirport', 'arrivalAirport', 'departureTime', 'arrivalTime', 'price', 'currency', 'durationMinutes', 'stops', 'stopText', 'outboundDate', 'returnDate'}
    return {k: flight[k] for k in allowed if k in flight}


def _flight_conflicts(itinerary, flight):
    """Return conservative local-time planning warnings; never invent a timezone."""
    segments = list(flight.get('outboundSegments') or []) + list(flight.get('returnSegments') or [])
    if not segments:
        return []
    warnings = []
    arrival = next((x for x in reversed(flight.get('outboundSegments') or []) if isinstance(x, dict)), None)
    departure = next((x for x in (flight.get('returnSegments') or []) if isinstance(x, dict)), None)
    try:
        trip_start = datetime.fromisoformat(str(itinerary.get('startDate'))[:10]).date()
    except (TypeError, ValueError):
        trip_start = None

    def trip_day(segment, field):
        if not trip_start or not segment:
            return None
        try:
            return (datetime.fromisoformat(str(segment.get(field))[:10]).date() - trip_start).days + 1
        except (TypeError, ValueError):
            return None

    arrival_day = trip_day(arrival, 'arrivalDate') or trip_day(arrival, 'departureDate')
    departure_day = trip_day(departure, 'departureDate')
    activities = itinerary.get('activities') or []
    for activity in activities:
        if not isinstance(activity, dict):
            continue
        day = int(activity.get('dayNo') or 1)
        time_value = str(activity.get('scheduledStartTime') or activity.get('timeSlot') or '').strip().lower()
        if arrival_day and day == arrival_day and any(token in time_value for token in ('morning', '08:', '09:', '10:', '11:')):
            warnings.append({'type': 'arrival_activity', 'activityId': activity.get('activityId'), 'message': 'This activity may begin before the outbound flight arrives.', 'precision': 'local_time_only', 'timezoneStatus': 'unavailable'})
        if departure_day and day == departure_day and any(token in time_value for token in ('evening', '18:', '19:', '20:', '21:', '22:')):
            warnings.append({'type': 'departure_activity', 'activityId': activity.get('activityId'), 'message': 'This activity may extend too close to the return flight.', 'precision': 'local_time_only', 'timezoneStatus': 'unavailable'})
    return warnings


def _flight_trip_date_error(itinerary, flight):
    try:
        trip_start = datetime.fromisoformat(str(itinerary['startDate'])[:10]).date()
        trip_end = datetime.fromisoformat(str(itinerary['endDate'])[:10]).date()
        if trip_end < trip_start:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return {
            'code': 'invalid_trip_dates',
            'error': 'The target Trip must have a valid startDate and endDate before attaching a flight.',
            'status': 'hard_conflict',
            'tripDates': {
                'startDate': itinerary.get('startDate'),
                'endDate': itinerary.get('endDate'),
            },
        }

    dated_segments = []
    for segment_type, segments in (
            ('outbound', flight.get('outboundSegments') or []),
            ('return', flight.get('returnSegments') or [])):
        for index, segment in enumerate(segments):
            if not isinstance(segment, dict):
                return {
                    'code': 'invalid_flight_dates',
                    'error': 'The selected flight has incomplete segment date information.',
                    'status': 'hard_conflict',
                }
            for field in ('departureDate', 'arrivalDate'):
                value = str(segment.get(field) or '')[:10]
                try:
                    parsed = datetime.fromisoformat(value).date()
                except (TypeError, ValueError):
                    return {
                        'code': 'invalid_flight_dates',
                        'error': 'The selected flight has incomplete segment date information.',
                        'status': 'hard_conflict',
                    }
                dated_segments.append((segment_type, index, field, value, parsed))
    if not dated_segments:
        return {
            'code': 'invalid_flight_dates',
            'error': 'The selected flight has no verifiable segment dates.',
            'status': 'hard_conflict',
        }

    conflicts = [
        {
            'type': 'flight_dates',
            'segmentType': segment_type,
            'segmentIndex': index,
            'field': field,
            'flightDate': value,
            'tripStartDate': trip_start.isoformat(),
            'tripEndDate': trip_end.isoformat(),
            'message': 'Selected flight dates must fall within the Trip dates.',
        }
        for segment_type, index, field, value, parsed in dated_segments
        if not (trip_start <= parsed <= trip_end)
    ]
    if not conflicts:
        return None
    return {
        'code': 'flight_trip_date_mismatch',
        'error': 'Selected flight dates must fall within the Trip dates.',
        'status': 'hard_conflict',
        'tripDates': {
            'startDate': trip_start.isoformat(),
            'endDate': trip_end.isoformat(),
        },
        'flightDates': sorted({value for _, _, _, value, _ in dated_segments}),
        'conflicts': conflicts,
    }


def _fallback_mode():
    return os.getenv('FALLBACK_MODE', 'false').lower() in {'1', 'true', 'yes'}


def _own_itinerary(iid):
    if not iid:
        return None
    data = retrieveRecord('itineraries', iid)
    return data if data and data.get('travellerId') == g.uid else None


CITY_TO_IATA = {
    'KUALA LUMPUR': 'KUL',
    'KL': 'KUL',
    'KLIA': 'KUL',
    'PENANG': 'PEN',
    'GEORGETOWN': 'PEN',
    'GEORGE TOWN': 'PEN',
    'SINGAPORE': 'SIN',
    'CHANGI': 'SIN',
    'BANGKOK': 'BKK',
    'SUVARNABHUMI': 'BKK',
    'TOKYO': 'NRT',
    'NARITA': 'NRT',
    'HANEDA': 'HND',
    'SEOUL': 'ICN',
    'INCHEON': 'ICN',
    'HONG KONG': 'HKG',
    'HK': 'HKG',
    'LANGKAWI': 'LGK',
    'KOTA KINABALU': 'BKI',
    'KUCHING': 'KCH',
    'JOHOR BAHRU': 'JHB',
    'JB': 'JHB',
    'IPOH': 'IPH',
    'MELAKA': 'MKZ',
    'MALACCA': 'MKZ',
    'LONDON': 'LHR',
    'HEATHROW': 'LHR',
    'SYDNEY': 'SYD',
    'MELBOURNE': 'MEL',
    'BALI': 'DPS',
    'DENPASAR': 'DPS',
    'JAKARTA': 'CGK',
    'TAIPEI': 'TPE',
    'OSAKA': 'KIX',
    'DUBAI': 'DXB',
}


def _resolve_iata(val):
    c = str(val or '').strip().upper()
    if len(c) == 3 and c.isalpha():
        return c
    for k, v in CITY_TO_IATA.items():
        if k == c or k in c or c in k:
            return v
    return c


def _provider_route_matches(item, criteria):
    segments = list(item.get('outboundSegments') or [])
    if not segments:
        return False
    first, last = segments[0], segments[-1]
    return (
        str(first.get('departureAirportCode') or '').upper() == criteria['departure_id']
        and str(last.get('arrivalAirportCode') or '').upper() == criteria['arrival_id']
        and str(first.get('departureDate') or '')[:10] == criteria['outbound_date']
    )


@bp.get('/flights/search')
@auth_required(['traveller'])
def search_flights():
    data = {
        'departure_id': _resolve_iata(request.args.get('departure_id', '')),
        'arrival_id': _resolve_iata(request.args.get('arrival_id', '')),
        'outbound_date': request.args.get('outbound_date', '').strip(),
        'return_date': request.args.get('return_date', '').strip() or None,
    }
    if not validateFlightSearchCriteria(data):
        return _flight_error('invalid_flight_search', 'Use different 3-letter airports and current or future flight dates', 400)

    return_date = data['return_date']
    currency = request.args.get('currency', 'MYR').strip().upper()
    try:
        travellers = int(request.args.get('traveller_count', 1))
        if travellers <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return _flight_error('invalid_passenger_count', 'traveller_count must be a positive whole number', 400)
    try:
        travel_class = int(request.args.get('travel_class', 1) or 1)
        if travel_class not in {1, 2, 3, 4}:
            raise ValueError
    except (TypeError, ValueError):
        return _flight_error('invalid_cabin_class', 'travel_class must be 1, 2, 3, or 4', 400)
    try:
        stops = request.args.get('provider_stops') or None
        criteria = _criteria(data, currency, travellers, travel_class, stops)
        result = retrieveFlightOptions(
            data['departure_id'], data['arrival_id'], data['outbound_date'], return_date,
            currency=currency,
            travelClass=travel_class, stops=stops, adults=travellers,
        )
        items = [
            x if isinstance(x, dict) and ('outboundSegments' in x or 'priceBasis' in x)
            else normalizeFlightResult(x, index, currency, travellers)
            for index, x in enumerate(result.get('items', []))
        ]
        source = 'serpapi'
    except Exception:
        if not _sample_mode():
            return jsonify({'ok': False, 'error': 'Flight provider is unavailable. Try again later.'}), 502
        items = []
        for raw in FLIGHTS:
            item = dict(raw)
            # Keep the requested airport pair visible in local fallback results while preserving
            # the varied price/duration/stop options.
            item['departureAirport'] = data['departure_id']
            item['arrivalAirport'] = data['arrival_id']
            items.append(_normalise_sample(item, criteria, len(items)))
        source = 'sample_fixture'

    if source == 'serpapi':
        items = [item for item in items if _provider_route_matches(item, criteria)]
        criteria['airportValidationStatus'] = 'provider_result' if items else 'unverified_no_provider_result'
    else:
        criteria['airportValidationStatus'] = 'sample_fixture'
    items = applyFlightFilter(items, dict(request.args))
    for item in items:
        item.setdefault('source', source)
        item.setdefault('sourceLabel', 'Provider search result' if source == 'serpapi' else 'Explicit sample fixture (not a current schedule)')
        item.setdefault('retrievedAt', _now())
        item.setdefault('cacheStatus', 'provider_cache_possible' if source == 'serpapi' else 'fixture')
        item.setdefault('freshnessStatus', 'provider_cache_possible' if source == 'serpapi' else 'fixture')
        item.setdefault('planningOnly', True)
        item.setdefault('transactionMode', 'planning_reference')
    try:
        search_id, items = _store_quote(criteria, items, source)
    except Exception:
        return jsonify({'ok': False, 'error': 'Flight quote storage is unavailable. Try again later.'}), 503
    public_items = [_public_option(x) for x in items]
    stored_quote = _FLIGHT_QUOTES[search_id]
    complete_round_trip = bool(return_date) and bool(public_items) and all(x.get('roundTripComplete') for x in public_items)
    return jsonify({
        'ok': True,
        'items': public_items,
        'best_flights': public_items,
        'other_flights': [],
        'source': source,
        'sourceLabel': 'Provider search result' if source == 'serpapi' else 'Explicit sample fixture (not a current schedule)',
        'retrievedAt': stored_quote['retrievedAt'],
        'expiresAt': stored_quote['expiresAt'],
        'freshnessStatus': stored_quote['freshnessStatus'],
        'planningOnly': True,
        'searchId': search_id,
        'criteria': criteria,
        'tripType': 'round_trip' if return_date else 'one_way',
        'quoteCompleteness': 'complete' if complete_round_trip or not return_date else 'return_selection_pending',
        'selectionStage': 'complete' if complete_round_trip or not return_date else 'outbound_candidate',
    })


@bp.post('/flights/returns')
@auth_required(['traveller'])
def search_flight_returns():
    payload = request.get_json(silent=True) or {}
    quote, outbound, quote_error = _quote_item(payload)
    if quote_error:
        message = 'This flight quote has expired. Search again.' if quote_error == 'flight_quote_expired' else 'The flight quote is invalid or unavailable.'
        return _flight_error(quote_error, message)
    if not outbound or not quote.get('criteria', {}).get('return_date'):
        return _flight_error('invalid_outbound_selection', 'Choose an outbound flight from a valid round-trip search')
    token = outbound.get('departureToken') or outbound.get('_departureToken')
    if not token:
        return _flight_error('invalid_outbound_selection', 'This outbound option has no compatible return search')
    criteria = quote['criteria']
    try:
        result = retrieveFlightReturns(
            token, criteria['departure_id'], criteria['arrival_id'], criteria['outbound_date'],
            criteria['return_date'], currency=criteria['currency'], adults=criteria['traveller_count'],
            travelClass=criteria['travel_class'], stops=criteria.get('stops'),
        )
    except Exception:
        return jsonify({'ok': False, 'error': 'Return-flight provider is unavailable. Try again later.'}), 502
    options = []
    seen = set()
    for index, raw in enumerate(result.get('items', [])):
        normalized = raw if isinstance(raw, dict) and 'outboundSegments' in raw else normalizeFlightResult(raw, index, criteria['currency'], criteria['traveller_count'])
        segments = _return_segments(normalized, criteria)
        signature = repr([(x.get('flightNumber'), x.get('departureDate'), x.get('departureTime'), x.get('arrivalDate'), x.get('arrivalTime')) for x in segments])
        if not segments or signature in seen:
            continue
        seen.add(signature)
        option = dict(normalized)
        option_id = f"return_{outbound.get('optionId')}_{index}"
        try:
            completed_price = float(option.get('price'))
            if not math.isfinite(completed_price) or completed_price <= 0:
                raise ValueError
        except (TypeError, ValueError):
            completed_price = None
        option.update({
            'id': option_id, 'optionId': option_id, 'outboundSegments': [], 'returnSegments': segments,
            'tripType': 'return_leg', 'roundTripComplete': False, 'quoteCompleteness': 'return_selection_pending',
            'selectionStage': 'return_candidate',
            'priceStatus': 'available' if completed_price is not None else 'unknown',
            'price': completed_price, 'combinedPrice': completed_price,
            'priceBasis': 'provider_round_trip_ticket_price_requested_adults' if completed_price is not None else None,
            'budgetEligible': False, '_outboundOptionId': outbound.get('optionId'),
            'freshnessStatus': quote.get('freshnessStatus'), 'planningOnly': True,
            'expiresAt': quote.get('expiresAt'),
        })
        options.append(option)
    quote.setdefault('returnOptions', {})[outbound['optionId']] = options
    quote['selectionStage'] = 'return_selection_pending'
    quote['quoteVersion'] = int(quote.get('quoteVersion') or 1) + 1
    try:
        _persist_quote(quote)
    except Exception:
        return jsonify({'ok': False, 'error': 'Flight quote storage is unavailable. Try again later.'}), 503
    return jsonify({
        'ok': True, 'items': [_public_option(x) for x in options], 'searchId': quote['id'],
        'optionId': outbound['optionId'],
        'retrievedAt': quote.get('retrievedAt'), 'expiresAt': quote.get('expiresAt'),
        'freshnessStatus': quote.get('freshnessStatus'), 'planningOnly': True,
        'quoteCompleteness': 'return_selection_pending' if options else 'return_unavailable',
        'selectionStage': 'return_selection_pending' if options else 'return_unavailable',
    })


@bp.post('/flights/compare')
@auth_required(['traveller'])
def compare_flights():
    items = (request.get_json(silent=True) or {}).get('items', [])
    return jsonify({'ok': True, 'items': compareSelectedFlights(items)})


@bp.post('/flights/details')
@auth_required(['traveller'])
def flight_details():
    payload = request.get_json(silent=True) or {}
    quote, option, quote_error = _quote_item(payload)
    if quote and option:
        return jsonify({'ok': True, 'flight': _public_option(option), 'searchId': quote['id'],
                        'criteria': quote['criteria'], 'retrievedAt': quote.get('retrievedAt'),
                        'expiresAt': quote.get('expiresAt'), 'freshnessStatus': quote.get('freshnessStatus'),
                        'planningOnly': True})
    if quote_error and not _testing_mode():
        message = 'This flight quote has expired. Search again.' if quote_error == 'flight_quote_expired' else 'The flight quote is invalid or unavailable.'
        return _flight_error(quote_error, message)
    if not _testing_mode():
        return jsonify({'ok': False, 'error': 'Flight search reference is required'}), 400
    return jsonify({'ok': True, 'flight': _safe_client_fixture(retrieveFlightDetails(payload.get('flight', {})))})


@bp.post('/flights/select')
@auth_required(['traveller'])
def select_flight():
    payload = request.get_json(silent=True) or {}
    itinerary_id = str(payload.get('itineraryId') or '').strip()
    flight = payload.get('flight') or {}
    current = _own_itinerary(itinerary_id)
    if not current:
        return jsonify({'ok': False, 'error': 'Select a valid itinerary first'}), 404
    quote, trusted, quote_error = _quote_item(payload)
    client_match_target = trusted
    return_option = None
    completed_selection_created = False
    if quote and trusted and quote.get('criteria', {}).get('return_date') and not trusted.get('completedOptionId'):
        if trusted.get('roundTripComplete') and trusted.get('returnSegments'):
            trusted = _completed_option(quote, trusted, trusted)
            completed_selection_created = True
        else:
            return_option_id = str(payload.get('returnOptionId') or '').strip()
            return_option = (quote.get('returnOptions') or {}).get(trusted.get('optionId'), [])
            return_option = next((x for x in return_option if x.get('optionId') == return_option_id), None)
            if not return_option:
                return _flight_error('invalid_return_selection', 'Choose a compatible return flight before continuing')
            if not list(return_option.get('returnSegments') or []):
                return _flight_error('invalid_return_selection', 'The selected return flight is incomplete')
            trusted = _completed_option(quote, trusted, return_option)
            completed_selection_created = True
        if not trusted:
            return _flight_error('flight_price_unavailable', 'The provider did not supply a trustworthy completed round-trip fare')
    if trusted is None:
        if not (_testing_mode() and isinstance(flight, dict) and flight):
            message = 'This flight quote has expired. Search again.' if quote_error == 'flight_quote_expired' else 'Select a flight from a valid completed search'
            return _flight_error(quote_error or 'invalid_flight_quote', message)
        trusted = _safe_client_fixture(flight)
        trusted.update({'currency': 'MYR', 'currencyStatus': 'known', 'priceStatus': 'available', 'priceBasis': 'legacy_test_fixture', 'source': 'test_fixture', 'quoteCompleteness': 'complete', 'budgetEligible': True})
    elif isinstance(flight, dict) and flight:
        match_target = client_match_target or trusted
        if str(flight.get('optionId') or flight.get('id') or '').strip() not in {'', str(match_target.get('optionId') or match_target.get('id') or '')}:
            return _flight_error('invalid_outbound_selection', 'Selected flight does not match the owned quote')
        if 'price' in flight and flight.get('price') is not None and flight.get('price') != match_target.get('price'):
            return _flight_error('invalid_outbound_selection', 'Selected flight price does not match the owned quote')
        for field in ('currency', 'outboundSegments', 'returnSegments'):
            if field in flight and flight.get(field) not in (None, []) and flight.get(field) != match_target.get(field):
                return _flight_error('invalid_outbound_selection', 'Selected flight details do not match the owned quote')
    try:
        price = float(trusted.get('price'))
        if not math.isfinite(price) or price <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return _flight_error('flight_price_unavailable', 'Selected flight price is unavailable')
    if str(trusted.get('currency') or '').upper() != 'MYR' or not trusted.get('priceBasis'):
        return _flight_error('flight_price_unavailable', 'Selected flight has no valid MYR planning price')
    if trusted.get('quoteCompleteness') != 'complete' or trusted.get('budgetEligible') is False:
        return _flight_error('invalid_flight_quote', 'Complete flight quote is required before selection')
    if quote:
        trusted = {
            **trusted,
            'flightSearchId': quote.get('id'),
            'flightOptionId': trusted.get('optionId') or trusted.get('id'),
        }
    trusted = _sanitize_flight_snapshot(trusted)
    if quote:
        date_error = _flight_trip_date_error(current, trusted)
        if date_error:
            return jsonify({'ok': False, **date_error}), 409
    if completed_selection_created:
        try:
            _persist_quote(quote)
        except Exception:
            return _flight_error('invalid_flight_quote', 'The completed flight selection could not be stored safely', 503)
    conflicts = _flight_conflicts(current, trusted)
    if conflicts and not payload.get('acknowledgeConflicts'):
        return jsonify({'ok': False, 'error': 'Flight conflicts require acknowledgement', 'conflicts': conflicts, 'status': 'conflicts_require_acknowledgement'}), 409
    patch = {
        'selectedFlight': trusted,
        'flightCost': price,
        'flightCurrency': 'MYR',
        'flightPriceBasis': trusted.get('priceBasis'),
        'flightQuoteCompleteness': trusted.get('quoteCompleteness'),
        'flightPriceScope': trusted.get('priceScope'),
        'flightPriceSemanticsStatus': trusted.get('priceSemanticsStatus'),
        'flightQuoteVersion': quote.get('quoteVersion') if quote else None,
        'flightQuoteRetrievedAt': quote.get('retrievedAt') if quote else None,
        'flightSelectionStatus': 'selected',
        'flightSearchId': quote.get('id') if quote else None,
        'flightOptionId': trusted.get('optionId') or trusted.get('id'),
        'flightSelectionSource': trusted.get('source') or (quote or {}).get('source'),
        'flightSelectedAt': _now(),
        'flightConflicts': conflicts,
        'flightConflictStatus': 'acknowledged' if conflicts else 'none',
    }
    patch['budgetEstimate'] = calculateBudget({**current, **patch})
    updated = updateRecord('itineraries', itinerary_id, patch)
    return jsonify({'ok': True, 'itinerary': updated, 'selectedFlight': _public_option(trusted), 'budget': patch['budgetEstimate']})


@bp.post('/itineraries/<iid>/flight-selection/remove')
@auth_required(['traveller'])
def remove_flight_selection(iid):
    current = _own_itinerary(iid)
    if not current:
        return jsonify({'ok': False, 'error': 'Itinerary not found'}), 404
    patch = {
        'selectedFlight': None, 'flightCost': 0, 'flightCurrency': None,
        'flightPriceBasis': None, 'flightSelectionStatus': 'removed',
        'flightSelectionRemovedAt': _now(), 'updatedAt': _now(),
    }
    patch['budgetEstimate'] = calculateBudget({**current, **patch})
    return jsonify({'ok': True, 'itinerary': updateRecord('itineraries', iid, patch), 'budget': patch['budgetEstimate']})
