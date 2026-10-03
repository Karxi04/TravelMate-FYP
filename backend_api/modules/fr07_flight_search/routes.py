import os
from flask import Blueprint, request, jsonify, g
from auth_utils import auth_required
from services.serpapi_service import retrieveFlightOptions, retrieveFlightDetails
from services.local_catalog import FLIGHTS
from sequence_contract.validators import validateFlightSearchCriteria
from sequence_contract.domain_functions import applyFlightFilter, compareSelectedFlights, calculateBudget
from sequence_contract.firebase_firestore import retrieveRecord, updateRecord

bp = Blueprint('fr07_flights', __name__, url_prefix='/api/fr7')


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
    currency = request.args.get('currency', 'MYR')
    try:
        travellers = max(1, int(request.args.get('traveller_count', 1) or 1))
    except Exception:
        travellers = 1
    try:
        result = retrieveFlightOptions(
            data['departure_id'], data['arrival_id'], data['outbound_date'], return_date,
            currency=currency,
            travelClass=int(request.args.get('travel_class', 1) or 1),
            stops=request.args.get('provider_stops') or None,
        )
        items = result.get('items', [])
        source = 'serpapi'
    except Exception as exc:
        if not _fallback_mode():
            return jsonify({'ok': False, 'error': str(exc)}), 502
        items = []
        for raw in FLIGHTS:
            item = dict(raw)
            # Keep the requested airport pair visible in local fallback results while preserving
            # the varied price/duration/stop options.
            item['departureAirport'] = data['departure_id']
            item['arrivalAirport'] = data['arrival_id']
            items.append(item)
        source = 'local'

    items = applyFlightFilter(items, dict(request.args))
    for item in items:
        try:
            unit_price = float(item.get('price', 0) or 0)
            item['unitPrice'] = unit_price
            item['travellerCount'] = travellers
            item['price'] = round(unit_price * travellers, 2)
        except Exception:
            item['travellerCount'] = travellers
    return jsonify({
        'ok': True,
        'items': items,
        'best_flights': items,
        'other_flights': [],
        'source': source,
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
    return jsonify({'ok': True, 'flight': retrieveFlightDetails((request.get_json(silent=True) or {}).get('flight', {}))})


@bp.post('/flights/select')
@auth_required(['traveller'])
def select_flight():
    payload = request.get_json(silent=True) or {}
    itinerary_id = str(payload.get('itineraryId') or '').strip()
    flight = payload.get('flight') or {}
    current = _own_itinerary(itinerary_id)
    if not current:
        return jsonify({'ok': False, 'error': 'Select a valid itinerary first'}), 404
    if not isinstance(flight, dict) or not flight:
        return jsonify({'ok': False, 'error': 'flight is required'}), 400

    price = float(flight.get('price', 0) or 0)
    patch = {
        'selectedFlight': flight,
        'flightCost': price,
    }
    patch['budgetEstimate'] = calculateBudget({**current, **patch})
    updated = updateRecord('itineraries', itinerary_id, patch)
    return jsonify({'ok': True, 'itinerary': updated, 'selectedFlight': flight, 'budget': patch['budgetEstimate']})
