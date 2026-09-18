import os
import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from auth_utils import auth_required
from utils import utc_now_iso
from services.liteapi_service import search_places, retrieveHotelOffers, validateHotelOffer, createBookingReference, normalizeHotelOffers
from services.local_catalog import LOCAL_HOTEL_ITEMS, CAR_RENTALS
from sequence_contract.validators import validateHotelSearchCriteria, validateBookingDetails, validateCarRentalSearchCriteria
from sequence_contract.domain_functions import applyHotelFilter, compareSelectedHotels, calculateBudget
from sequence_contract.firebase_firestore import retrieveRecord, storeRecord, updateRecord

bp = Blueprint('fr08_hotels', __name__, url_prefix='/api/fr8')


def _fallback_mode():
    return os.getenv('FALLBACK_MODE', 'false').lower() in {'1', 'true', 'yes'}


def _own_itinerary(iid):
    if not iid:
        return None
    data = retrieveRecord('itineraries', iid)
    return data if data and data.get('travellerId') == g.uid else None


def _rental_days(pickup_date, dropoff_date):
    try:
        start = datetime.strptime(str(pickup_date), "%Y-%m-%d").date()
        end = datetime.strptime(str(dropoff_date), "%Y-%m-%d").date()
        return max(1, (end - start).days + 1)
    except Exception:
        return 1


@bp.get('/places/search')
@auth_required(['traveller'])
def places():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'ok': False, 'error': 'q is required'}), 400
    try:
        return jsonify({'ok': True, 'result': search_places(q), 'source': 'liteapi'})
    except Exception as exc:
        if not _fallback_mode():
            return jsonify({'ok': False, 'error': str(exc)}), 502
        return jsonify({'ok': True, 'result': {'data': [{'placeId': 'local_penang', 'displayName': q, 'formattedAddress': 'Malaysia'}]}, 'source': 'local'})


@bp.post('/hotels/search')
@auth_required(['traveller'])
def hotels_search():
    payload = request.get_json(silent=True) or {}
    if not validateHotelSearchCriteria(payload):
        return jsonify({'ok': False, 'error': 'Destination, checkin and checkout are required'}), 400
    try:
        room_quantity = max(1, int(payload.get('roomQuantity', 1) or 1))
    except Exception:
        room_quantity = 1

    req = {
        'occupancies': payload.get('occupancies') or [{'adults': int(payload.get('adults', 2) or 2)} for _ in range(room_quantity)],
        'currency': payload.get('currency', 'MYR'),
        'guestNationality': payload.get('guestNationality', 'MY'),
        'checkin': payload['checkin'],
        'checkout': payload['checkout'],
        'roomMapping': True,
        'maxRatesPerHotel': int(payload.get('maxRatesPerHotel', 3) or 3),
        'includeHotelData': True,
    }
    if payload.get('placeId'):
        req['placeId'] = payload['placeId']
    elif payload.get('hotelIds'):
        req['hotelIds'] = payload['hotelIds']
    else:
        # LiteAPI supports AI-assisted destination search in rate requests.
        req['aiSearch'] = payload.get('aiSearch') or payload.get('destination')

    try:
        result = retrieveHotelOffers(req)
        items = normalizeHotelOffers(result)
        if not items:
            raise RuntimeError('LiteAPI returned no bookable offers for these dates')
        source = 'liteapi'
    except Exception as exc:
        if not _fallback_mode():
            return jsonify({'ok': False, 'error': str(exc)}), 502
        items = [dict(x) for x in LOCAL_HOTEL_ITEMS]
        result = {'items': items, 'sandbox': True}
        source = 'local'

    filters = {
        'refundable': payload.get('refundable'),
        'sort': payload.get('sort'),
    }
    items = applyHotelFilter(items, filters)
    for item in items:
        try:
            unit_price = float(item.get('price', 0) or 0)
            item['nightlyRoomRate'] = unit_price
            item['roomQuantity'] = room_quantity
            item['price'] = round(unit_price * room_quantity, 2)
        except Exception:
            item['roomQuantity'] = room_quantity
    return jsonify({'ok': True, 'items': items, 'result': {'items': items}, 'source': source})


@bp.post('/hotels/compare')
@auth_required(['traveller'])
def compare_hotels():
    return jsonify({'ok': True, 'items': compareSelectedHotels((request.get_json(silent=True) or {}).get('items', []))})


@bp.post('/hotels/prebook')
@auth_required(['traveller'])
def hotel_prebook():
    offer = str((request.get_json(silent=True) or {}).get('offerId', '')).strip()
    if not offer:
        return jsonify({'ok': False, 'error': 'offerId is required'}), 400
    if offer.startswith('local_offer_') and _fallback_mode():
        return jsonify({'ok': True, 'result': {'prebookId': 'local_prebook_' + offer.split('_')[-1], 'offerId': offer, 'status': 'prebooked', 'sandbox': True}, 'source': 'local'})
    try:
        return jsonify({'ok': True, 'result': validateHotelOffer(offer), 'source': 'liteapi'})
    except Exception as exc:
        if not _fallback_mode():
            return jsonify({'ok': False, 'error': str(exc)}), 502
        return jsonify({'ok': True, 'result': {'prebookId': f'local_prebook_{uuid.uuid4().hex[:8]}', 'offerId': offer, 'status': 'prebooked', 'sandbox': True}, 'source': 'local'})


@bp.post('/hotels/book')
@auth_required(['traveller'])
def hotel_book():
    payload = request.get_json(silent=True) or {}
    if not validateBookingDetails(payload):
        return jsonify({'ok': False, 'error': 'prebookId is required'}), 400

    prebook_id = str(payload.get('prebookId') or '')
    source = 'liteapi'
    if prebook_id.startswith('local_prebook_') and _fallback_mode():
        result = {
            'bookingId': 'TM-BK-' + uuid.uuid4().hex[:8].upper(),
            'hotelConfirmationCode': 'TM-' + uuid.uuid4().hex[:6].upper(),
            'status': 'confirmed',
            'sandbox': True,
        }
        source = 'local'
    else:
        # Only provider-supported booking fields are forwarded. Extra local TravelMate
        # fields such as itineraryId/selectedHotel stay on our side.
        provider_payload = {k: v for k, v in payload.items() if k not in {'itineraryId', 'selectedHotel', 'hotelCost'}}
        try:
            result = createBookingReference(provider_payload)
        except Exception as exc:
            if not _fallback_mode():
                return jsonify({'ok': False, 'error': str(exc)}), 502
            result = {
                'bookingId': 'TM-BK-' + uuid.uuid4().hex[:8].upper(),
                'hotelConfirmationCode': 'TM-' + uuid.uuid4().hex[:6].upper(),
                'status': 'confirmed',
                'sandbox': True,
            }
            source = 'local'

    selected_hotel = payload.get('selectedHotel') if isinstance(payload.get('selectedHotel'), dict) else {}
    hotel_cost = float(payload.get('hotelCost') or selected_hotel.get('price') or 0)
    record = {
        'travellerId': g.uid,
        'bookingStatus': result.get('status', 'confirmed'),
        'bookingReference': result.get('bookingId') or result.get('id') or result.get('hotelConfirmationCode', ''),
        'providerResult': result,
        'selectedHotel': selected_hotel,
        'roomQuantity': selected_hotel.get('roomQuantity') or payload.get('roomQuantity') or 1,
        'hotelCost': hotel_cost,
        'source': source,
        'createdAt': utc_now_iso(),
    }
    saved = storeRecord('hotel_bookings', record)

    itinerary_id = str(payload.get('itineraryId') or '').strip()
    current = _own_itinerary(itinerary_id)
    itinerary = None
    if current:
        patch = {'selectedHotel': selected_hotel, 'hotelCost': hotel_cost, 'hotelBookingId': saved['id']}
        patch['budgetEstimate'] = calculateBudget({**current, **patch})
        itinerary = updateRecord('itineraries', itinerary_id, patch)

    return jsonify({'ok': True, 'id': saved['id'], 'booking': saved, 'itinerary': itinerary, 'source': source})


@bp.get('/bookings')
@auth_required(['traveller'])
def bookings():
    return jsonify({'ok': True, 'items': retrieveRecord('hotel_bookings', filters=[('travellerId', '==', g.uid)])})


@bp.post('/car-rentals/search')
@auth_required(['traveller'])
def car_rentals_search():
    payload = request.get_json(silent=True) or {}
    if not validateCarRentalSearchCriteria(payload):
        return jsonify({'ok': False, 'error': 'Pickup location, valid dates and driver count are required'}), 400
    days = _rental_days(payload.get('pickupDate'), payload.get('dropoffDate'))
    vehicle_type = str(payload.get('vehicleType') or '').strip().lower()
    items = []
    for row in CAR_RENTALS:
        if vehicle_type and vehicle_type != 'all' and vehicle_type not in str(row.get('vehicleType', '')).lower():
            continue
        item = {
            **row,
            'pickupLocation': payload.get('pickupLocation') or row.get('pickupLocation'),
            'dropoffLocation': payload.get('dropoffLocation') or payload.get('pickupLocation') or row.get('pickupLocation'),
            'pickupDate': payload.get('pickupDate'),
            'dropoffDate': payload.get('dropoffDate'),
            'rentalDays': days,
            'totalPrice': round(float(row.get('dailyRate', 0) or 0) * days, 2),
            'sandbox': True,
        }
        items.append(item)
    items.sort(key=lambda x: float(x.get('totalPrice', 0) or 0))
    return jsonify({'ok': True, 'items': items, 'source': 'local'})


@bp.post('/car-rentals/select')
@auth_required(['traveller'])
def select_car_rental():
    payload = request.get_json(silent=True) or {}
    itinerary_id = str(payload.get('itineraryId') or '').strip()
    rental = payload.get('rental') if isinstance(payload.get('rental'), dict) else {}
    current = _own_itinerary(itinerary_id)
    if not current:
        return jsonify({'ok': False, 'error': 'Select a valid itinerary first'}), 404
    if not rental:
        return jsonify({'ok': False, 'error': 'rental is required'}), 400
    cost = float(rental.get('totalPrice') or rental.get('price') or rental.get('dailyRate') or 0)
    patch = {
        'selectedCarRental': rental,
        'carRentalCost': cost,
        'updatedAt': utc_now_iso(),
    }
    patch['budgetEstimate'] = calculateBudget({**current, **patch})
    updated = updateRecord('itineraries', itinerary_id, patch)
    return jsonify({'ok': True, 'itinerary': updated, 'selectedCarRental': rental, 'budget': patch['budgetEstimate']})
