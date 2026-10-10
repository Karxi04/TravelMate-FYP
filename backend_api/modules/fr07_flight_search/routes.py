import os
import math
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from flask import Blueprint, request, jsonify, g
from auth_utils import auth_required
from services.serpapi_service import retrieveFlightOptions, retrieveFlightReturns, retrieveFlightDetails, normalizeFlightResult
from services.local_catalog import FLIGHTS
from services.flight_quote_eligibility import provider_time, validate_segments
from services.flight_itinerary_adjustment import fingerprint
from sequence_contract.validators import validateFlightSearchCriteria
from sequence_contract.domain_functions import applyFlightFilter, compareSelectedFlights, calculateBudget
from sequence_contract.firebase_firestore import retrieveRecord, storeRecord, updateRecord

bp = Blueprint('fr07_flights', __name__, url_prefix='/api/fr7')

# Quotes are short-lived server-owned records; the local cache is only a read-through optimization.
_FLIGHT_QUOTES = {}
_FLIGHT_QUOTES_COLLECTION = 'flight_quotes'
_QUOTE_TTL_SECONDS = 3600
_TEST_DURABLE_QUOTES = {}


def reset_flight_quotes():
    _FLIGHT_QUOTES.clear()


def _testing_mode():
    return os.getenv('TRAVELMATE_TESTING', '').lower() in {'1', 'true', 'yes'}


def _sample_mode():
    return os.getenv('FLIGHT_SAMPLE_MODE', '').lower() in {'1', 'true', 'yes'} or (_testing_mode() and _fallback_mode())


def _now():
    return datetime.now(timezone.utc).isoformat()


def _expires_at(retrieved_at):
    return (datetime.fromisoformat(retrieved_at.replace('Z', '+00:00')) + timedelta(seconds=_QUOTE_TTL_SECONDS)).isoformat()


def _quote_doc_id(uid, search_id):
    return f'{uid}_{search_id}'


def _public_option(item):
    safe = dict(item or {})
    for key in ('departureToken', 'bookingToken', 'returnToken', '_departureToken', '_outboundOptionId'):
        safe.pop(key, None)
    safe.pop('returnOptions', None)
    return safe


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


def _load_quote(search_id):
    quote = _FLIGHT_QUOTES.get(search_id)
    if quote and quote.get('travellerId') == g.uid:
        expires_at = quote.get('expiresAt')
        if not expires_at:
            return quote
        try:
            if datetime.fromisoformat(expires_at.replace('Z', '+00:00')) > datetime.now(timezone.utc):
                return quote
        except ValueError:
            pass
        return None
    doc_id = _quote_doc_id(g.uid, search_id)
    try:
        quote = retrieveRecord(_FLIGHT_QUOTES_COLLECTION, doc_id)
    except Exception:
        quote = _TEST_DURABLE_QUOTES.get(doc_id) if _testing_mode() else None
    if not quote or quote.get('travellerId') != g.uid:
        return None
    expires_at = quote.get('expiresAt')
    if expires_at:
        try:
            if datetime.fromisoformat(expires_at.replace('Z', '+00:00')) <= datetime.now(timezone.utc):
                return None
        except ValueError:
            return None
    _FLIGHT_QUOTES[search_id] = quote
    return quote


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
    }


def _store_quote(criteria, items, source, metadata=None):
    search_id = f'flight_search_{uuid4().hex}'
    original = provider_time((metadata or {}).get('created_at'))
    retrieved_at = original or _now()
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
                safe['priceBasis'] = 'provider_round_trip_candidate_unverified'
        else:
            safe['quoteCompleteness'] = 'complete'
            safe['selectionStage'] = 'complete'
            safe['budgetEligible'] = safe.get('checkoutEligible', source == 'sample_fixture')
        safe['flightSearchId'] = search_id
        safe['flightOptionId'] = safe['optionId']
        safe['retrievedAt'] = retrieved_at
        safe_items.append(safe)
    quote = {
        'id': search_id, 'travellerId': g.uid, 'criteria': dict(criteria),
        'source': source, 'retrievedAt': retrieved_at, 'expiresAt': _expires_at(retrieved_at),
        'retrievalTimeStatus': 'provider_original' if original else 'unavailable',
        'providerSearchId': (metadata or {}).get('id'),
        'quoteVersion': 1, 'selectionStage': 'outbound_candidate' if any(not x.get('returnSegments') for x in safe_items) else 'complete',
        'items': safe_items, 'returnOptions': {},
    }
    _FLIGHT_QUOTES[search_id] = quote
    _persist_quote(quote)
    return search_id, safe_items


def _quote_item(payload):
    search_id = str(payload.get('searchId') or payload.get('quoteId') or '').strip()
    option_id = str(payload.get('optionId') or '').strip()
    if not search_id or not option_id:
        return None, None
    quote = _load_quote(search_id)
    if not quote:
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
    if any(request.args.get(k, '0') not in {'0', ''} for k in ('children', 'infants_in_seat', 'infants_on_lap')):
        return jsonify({'ok': False, 'error': 'Flight search currently supports adults only; children and infants are unsupported.'}), 400
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

    items = applyFlightFilter(items, dict(request.args))
    for item in items:
        item.setdefault('source', source)
        item.setdefault('sourceLabel', 'Provider search result' if source == 'serpapi' else 'Explicit sample fixture (not a current schedule)')
        item.setdefault('retrievedAt', _now())
        item.setdefault('cacheStatus', 'live' if source == 'serpapi' else 'fixture')
        item.setdefault('transactionMode', 'planning_reference')
    try:
        search_id, items = _store_quote(criteria, items, source, result.get('search_metadata') if source == 'serpapi' else None)
    except Exception:
        return jsonify({'ok': False, 'error': 'Flight quote storage is unavailable. Try again later.'}), 503
    public_items = [_public_option(x) for x in items]
    complete_round_trip = bool(return_date) and bool(public_items) and all(x.get('roundTripComplete') for x in public_items)
    return jsonify({
        'ok': True,
        'items': public_items,
        'best_flights': public_items,
        'other_flights': [],
        'source': source,
        'sourceLabel': 'Provider search result' if source == 'serpapi' else 'Explicit sample fixture (not a current schedule)',
        'retrievedAt': _FLIGHT_QUOTES[search_id]['retrievedAt'],
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
    quote, outbound = _quote_item(payload)
    if not quote or not outbound or not quote.get('criteria', {}).get('return_date'):
        return jsonify({'ok': False, 'error': 'Choose an outbound flight from a valid round-trip search'}), 409
    token = outbound.get('departureToken') or outbound.get('_departureToken')
    if not token:
        return jsonify({'ok': False, 'error': 'This outbound option has no compatible return search'}), 409
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
        segments = list(normalized.get('outboundSegments') or normalized.get('returnSegments') or [])
        signature = repr([(x.get('flightNumber'), x.get('departureDate'), x.get('departureTime'), x.get('arrivalDate'), x.get('arrivalTime')) for x in segments])
        if not segments or signature in seen:
            continue
        seen.add(signature)
        option = dict(normalized)
        option_id = f"return_{outbound.get('optionId')}_{index}"
        option.update({
            'id': option_id, 'optionId': option_id, 'outboundSegments': [], 'returnSegments': segments,
            'tripType': 'return_leg', 'roundTripComplete': False, 'quoteCompleteness': 'return_selection_pending',
            'selectionStage': 'return_candidate', 'priceStatus': 'reference_only', 'price': None,
            'priceBasis': None, 'budgetEligible': False, 'checkoutEligible': False,
            'returnReferencePrice': normalized.get('price'), '_outboundOptionId': outbound.get('optionId'),
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
    quote, option = _quote_item(payload)
    if quote and option:
        return jsonify({'ok': True, 'flight': _public_option(option), 'searchId': quote['id'], 'criteria': quote['criteria']})
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
    input_option = trusted
    return_option = None
    if quote and trusted and quote.get('criteria', {}).get('return_date') and not trusted.get('roundTripComplete'):
        return_option_id = str(payload.get('returnOptionId') or '').strip()
        return_option = (quote.get('returnOptions') or {}).get(trusted.get('optionId'), [])
        return_option = next((x for x in return_option if x.get('optionId') == return_option_id), None)
        if not return_option:
            return jsonify({'ok': False, 'error': 'Choose a compatible return flight before continuing'}), 409
        trusted = dict(trusted)
        trusted['outboundSegments'] = list(trusted.get('outboundSegments') or [])
        trusted['returnSegments'] = list(return_option.get('returnSegments') or [])
        if not trusted['returnSegments']:
            return jsonify({'ok': False, 'error': 'The selected return flight is incomplete'}), 409
        trusted.update({
            'tripType': 'round_trip', 'roundTripComplete': True, 'quoteCompleteness': 'complete',
            'selectionStage': 'complete_round_trip', 'priceBasis': 'provider_round_trip_price_unresolved',
            'priceScope': 'provider_ticket_price_unverified', 'priceSemanticsStatus': 'unverified',
            'budgetEligible': False, 'checkoutEligible': False, 'priceStatus': 'reference_only',
            'checkoutBlockReason': 'Round-trip price scope is unresolved; excluded from budget and Checkout.',
            'priceEvidence': None, 'returnOptionId': return_option_id,
            'returnReferencePrice': return_option.get('returnReferencePrice'),
            'returnDate': quote['criteria'].get('return_date'),
        })
    if trusted is None:
        if not (_testing_mode() and isinstance(flight, dict) and flight):
            return jsonify({'ok': False, 'error': 'Select a flight from a completed search'}), 409
        trusted = _safe_client_fixture(flight)
        trusted.update({'currency': 'MYR', 'currencyStatus': 'known', 'priceStatus': 'available', 'priceBasis': 'legacy_test_fixture', 'source': 'test_fixture', 'quoteCompleteness': 'complete', 'budgetEligible': True})
    elif isinstance(flight, dict) and flight:
        if str(flight.get('optionId') or flight.get('id') or '').strip() not in {'', str((input_option or trusted).get('optionId') or (input_option or trusted).get('id') or '')}:
            return jsonify({'ok': False, 'error': 'Selected flight does not match the owned quote'}), 409
        if 'price' in flight and flight.get('price') is not None and flight.get('price') != (input_option or trusted).get('price'):
            return jsonify({'ok': False, 'error': 'Selected flight price does not match the owned quote'}), 409
        for field in ('currency', 'outboundSegments', 'returnSegments'):
            if field in flight and flight.get(field) not in (None, []) and flight.get(field) != (input_option or trusted).get(field):
                return jsonify({'ok': False, 'error': 'Selected flight details do not match the owned quote'}), 409
    try:
        price = float(trusted.get('price')) if trusted.get('price') is not None else 0.0
        if not math.isfinite(price) or price < 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Selected flight price is unavailable'}), 409
    if trusted.get('quoteCompleteness') != 'complete':
        return jsonify({'ok': False, 'error': 'Complete flight quote is required before selection'}), 409
    if quote:
        try:
            validate_segments(quote['criteria'], trusted.get('outboundSegments'), trusted.get('returnSegments') or [], detailed=False)
        except ValueError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 409
        if return_option:
            trusted['optionId'] = 'roundtrip_' + fingerprint({'outbound': input_option['optionId'], 'return': return_option_id})[:24]
            trusted['id'] = trusted['optionId']
            quote['items'] = [x for x in quote['items'] if x.get('optionId') != trusted['optionId']] + [dict(trusted)]
            _persist_quote(quote)
        trusted['flightSearchId'] = quote['id']
        trusted['flightOptionId'] = trusted['optionId']
    conflicts = _flight_conflicts(current, trusted)
    if conflicts and not payload.get('acknowledgeConflicts'):
        return jsonify({'ok': False, 'error': 'Flight conflicts require acknowledgement', 'conflicts': conflicts, 'status': 'conflicts_require_acknowledgement'}), 409
    patch = {
        'selectedFlight': trusted,
        'flightCost': price if trusted.get('budgetEligible', True) and trusted.get('currency') == 'MYR' else 0,
        'flightCurrency': trusted.get('currency'),
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
