import os
import math
from datetime import datetime, timezone
from uuid import uuid4
from flask import Blueprint, request, jsonify, g
from auth_utils import auth_required
from services.serpapi_service import retrieveFlightOptions, retrieveFlightDetails, normalizeFlightResult
from services.local_catalog import FLIGHTS
from sequence_contract.validators import validateFlightSearchCriteria
from sequence_contract.domain_functions import applyFlightFilter, compareSelectedFlights, calculateBudget
from sequence_contract.firebase_firestore import retrieveRecord, updateRecord

bp = Blueprint('fr07_flights', __name__, url_prefix='/api/fr7')

# ponytail: process-local quotes keep the planning reference small and deterministic;
# move to a short-lived database collection if searches must survive process restarts.
_FLIGHT_QUOTES = {}


def reset_flight_quotes():
    _FLIGHT_QUOTES.clear()


def _testing_mode():
    return os.getenv('TRAVELMATE_TESTING', '').lower() in {'1', 'true', 'yes'}


def _sample_mode():
    return os.getenv('FLIGHT_SAMPLE_MODE', '').lower() in {'1', 'true', 'yes'} or (_testing_mode() and _fallback_mode())


def _now():
    return datetime.now(timezone.utc).isoformat()


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
    })
    return item


def _criteria(data, currency, travellers, travel_class, stops):
    return {
        'departure_id': data['departure_id'], 'arrival_id': data['arrival_id'],
        'outbound_date': data['outbound_date'], 'return_date': data.get('return_date'),
        'currency': str(currency or '').upper() or None, 'traveller_count': travellers,
        'travel_class': travel_class, 'stops': stops,
    }


def _store_quote(criteria, items, source):
    search_id = f'flight_search_{uuid4().hex}'
    safe_items = []
    for index, item in enumerate(items):
        safe = dict(item)
        safe['optionId'] = safe.get('optionId') or safe.get('id') or f'flight_option_{index}'
        safe['id'] = safe['optionId']
        safe_items.append(safe)
    _FLIGHT_QUOTES[search_id] = {
        'id': search_id, 'travellerId': g.uid, 'criteria': dict(criteria),
        'source': source, 'retrievedAt': _now(), 'items': safe_items,
    }
    return search_id, safe_items


def _quote_item(payload):
    search_id = str(payload.get('searchId') or payload.get('quoteId') or '').strip()
    option_id = str(payload.get('optionId') or '').strip()
    quote = _FLIGHT_QUOTES.get(search_id)
    if not quote or quote.get('travellerId') != g.uid:
        return None, None
    option = next((x for x in quote.get('items', []) if x.get('optionId') == option_id or x.get('id') == option_id), None)
    return quote, option


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
    activities = itinerary.get('activities') or []
    for activity in activities:
        if not isinstance(activity, dict):
            continue
        day = int(activity.get('dayNo') or 1)
        time_value = str(activity.get('scheduledStartTime') or activity.get('timeSlot') or '').strip().lower()
        if arrival and day == 1 and any(token in time_value for token in ('morning', '08:', '09:', '10:', '11:')):
            warnings.append({'type': 'arrival_activity', 'activityId': activity.get('activityId'), 'message': 'This activity may begin before the outbound flight arrives.', 'precision': 'local_time_only', 'timezoneStatus': 'unavailable'})
        if departure and day == int(itinerary.get('tripDays') or 999) and any(token in time_value for token in ('evening', '18:', '19:', '20:', '21:', '22:')):
            warnings.append({'type': 'departure_activity', 'activityId': activity.get('activityId'), 'message': 'This activity may extend too close to the return flight.', 'precision': 'local_time_only', 'timezoneStatus': 'unavailable'})
    return warnings


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
        return jsonify({'ok': False, 'error': 'Use different 3-letter airports and valid flight dates'}), 400

    return_date = data['return_date']
    currency = request.args.get('currency', 'MYR').strip().upper()
    try:
        travellers = max(1, int(request.args.get('traveller_count', 1) or 1))
    except Exception:
        travellers = 1
    try:
        travel_class = int(request.args.get('travel_class', 1) or 1)
        stops = request.args.get('provider_stops') or None
        criteria = _criteria(data, currency, travellers, travel_class, stops)
        result = retrieveFlightOptions(
            data['departure_id'], data['arrival_id'], data['outbound_date'], return_date,
            currency=currency,
            travelClass=travel_class, stops=stops,
        )
        items = [
            x if isinstance(x, dict) and ('outboundSegments' in x or 'priceBasis' in x)
            else normalizeFlightResult(x, index, currency)
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

    items = applyFlightFilter(items, dict(request.args))
    for item in items:
        item.setdefault('source', source)
        item.setdefault('sourceLabel', 'Provider search result' if source == 'serpapi' else 'Explicit sample fixture (not a current schedule)')
        item.setdefault('retrievedAt', _now())
        item.setdefault('cacheStatus', 'live' if source == 'serpapi' else 'fixture')
        item.setdefault('transactionMode', 'planning_reference')
    search_id, items = _store_quote(criteria, items, source)
    return jsonify({
        'ok': True,
        'items': items,
        'best_flights': items,
        'other_flights': [],
        'source': source,
        'sourceLabel': 'Provider search result' if source == 'serpapi' else 'Explicit sample fixture (not a current schedule)',
        'retrievedAt': _now(),
        'searchId': search_id,
        'criteria': criteria,
        'tripType': 'round_trip' if return_date else 'one_way',
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
    quote, option = _quote_item(payload)
    if quote and option:
        return jsonify({'ok': True, 'flight': option, 'searchId': quote['id'], 'criteria': quote['criteria']})
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
    quote, trusted = _quote_item(payload)
    if trusted is None:
        if not (_testing_mode() and isinstance(flight, dict) and flight):
            return jsonify({'ok': False, 'error': 'Select a flight from a completed search'}), 409
        trusted = _safe_client_fixture(flight)
        trusted.update({'currency': 'MYR', 'currencyStatus': 'known', 'priceStatus': 'available', 'priceBasis': 'legacy_test_fixture', 'source': 'test_fixture'})
    try:
        price = float(trusted.get('price'))
        if not math.isfinite(price) or price < 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Selected flight price is unavailable'}), 409
    if str(trusted.get('currency') or '').upper() != 'MYR' or not trusted.get('priceBasis'):
        return jsonify({'ok': False, 'error': 'Selected flight has no valid MYR planning price'}), 409
    conflicts = _flight_conflicts(current, trusted)
    if conflicts and not payload.get('acknowledgeConflicts'):
        return jsonify({'ok': False, 'error': 'Flight conflicts require acknowledgement', 'conflicts': conflicts, 'status': 'conflicts_require_acknowledgement'}), 409
    patch = {
        'selectedFlight': trusted,
        'flightCost': price,
        'flightCurrency': 'MYR',
        'flightPriceBasis': trusted.get('priceBasis'),
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
    return jsonify({'ok': True, 'itinerary': updated, 'selectedFlight': trusted, 'budget': patch['budgetEstimate']})


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
