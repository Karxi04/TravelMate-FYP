import os
import requests

DATA_BASE = "https://api.liteapi.travel/v3.0"
BOOK_BASE = "https://book.liteapi.travel/v3.0"


def _headers():
    key = os.getenv('LITEAPI_KEY', '').strip()
    if not key:
        raise RuntimeError('LITEAPI_KEY is not configured')
    return {'X-API-Key': key, 'Content-Type': 'application/json'}


def _json_or_error(response):
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and data.get('error'):
        err = data.get('error')
        if isinstance(err, dict):
            raise RuntimeError(str(err.get('description') or err.get('message') or err))
        raise RuntimeError(str(err))
    return data


def search_places(query):
    r = requests.get(
        f'{DATA_BASE}/data/places',
        params={'textQuery': query},
        headers=_headers(),
        timeout=30,
    )
    return _json_or_error(r)


def retrieveHotelOffers(payload):
    r = requests.post(
        f'{DATA_BASE}/hotels/rates',
        headers=_headers(),
        json=payload,
        timeout=55,
    )
    return _json_or_error(r)


def validateHotelOffer(offerId):
    r = requests.post(
        f'{BOOK_BASE}/rates/prebook',
        headers=_headers(),
        json={'offerId': offerId, 'usePaymentSdk': False},
        timeout=60,
    )
    return _json_or_error(r)


def createBookingReference(payload):
    r = requests.post(
        f'{BOOK_BASE}/rates/book',
        headers=_headers(),
        json=payload,
        timeout=65,
    )
    return _json_or_error(r)


def _money(value):
    if isinstance(value, dict):
        for key in ('amount', 'total', 'value', 'net'):
            if value.get(key) is not None:
                return _money(value.get(key))
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _currency(*objects):
    for obj in objects:
        if isinstance(obj, dict):
            for key in ('currency', 'currencyCode', 'currency_code'):
                if obj.get(key):
                    return str(obj[key])
            for key in ('retailRate', 'retail_rate', 'price'):
                nested = obj.get(key)
                if isinstance(nested, dict) and nested.get('currency'):
                    return str(nested['currency'])
    return 'MYR'


def _first_rate(room):
    rates = room.get('rates') if isinstance(room, dict) else None
    if isinstance(rates, list) and rates:
        return rates[0] if isinstance(rates[0], dict) else {}
    return room if isinstance(room, dict) else {}


def _extract_price(room, rate):
    candidates = [
        rate.get('retailRate'), rate.get('retail_rate'), rate.get('price'), rate.get('total'),
        room.get('retailRate'), room.get('price'), room.get('total'),
    ]
    for candidate in candidates:
        amount = _money(candidate)
        if amount > 0:
            return amount
    return 0.0


def _refundable(room, rate):
    for obj in (rate, room):
        if not isinstance(obj, dict):
            continue
        for key in ('refundable', 'isRefundable', 'is_refundable'):
            if key in obj:
                return bool(obj.get(key))
        policy = obj.get('cancellationPolicies') or obj.get('cancellation_policies')
        if isinstance(policy, list) and policy:
            return True
    return False


def normalizeHotelOffers(result):
    """Normalize both current LiteAPI response variants into one Flutter-friendly list."""
    result = result or {}
    hotels = result.get('hotels') or result.get('data', {}).get('hotels') if isinstance(result.get('data'), dict) else result.get('hotels')
    if not isinstance(hotels, list):
        hotels = []

    content_by_id = {}
    for hotel in hotels:
        if isinstance(hotel, dict):
            hid = str(hotel.get('id') or hotel.get('hotelId') or hotel.get('hotel_id') or '')
            if hid:
                content_by_id[hid] = hotel

    rate_groups = []
    raw_data = result.get('data')
    if isinstance(raw_data, list):
        rate_groups = raw_data
    elif isinstance(raw_data, dict):
        for key in ('data', 'rates', 'hotels'):
            if isinstance(raw_data.get(key), list):
                rate_groups = raw_data[key]
                break
    if not rate_groups and isinstance(result.get('rates'), list):
        rate_groups = result['rates']

    items = []
    seen = set()
    for group in rate_groups:
        if not isinstance(group, dict):
            continue
        hotel_id = str(group.get('hotelId') or group.get('hotel_id') or group.get('id') or '')
        content = content_by_id.get(hotel_id, {})
        room_types = group.get('roomTypes') or group.get('room_types') or group.get('rooms') or []
        if not isinstance(room_types, list):
            room_types = []
        if not room_types:
            room_types = [group]

        for room in room_types:
            if not isinstance(room, dict):
                continue
            rate = _first_rate(room)
            offer_id = str(room.get('offerId') or room.get('offer_id') or rate.get('offerId') or rate.get('offer_id') or group.get('offerId') or '')
            if not offer_id:
                continue
            key = (hotel_id, offer_id)
            if key in seen:
                continue
            seen.add(key)
            price = _extract_price(room, rate)
            name = content.get('name') or group.get('hotelName') or group.get('name') or f'Hotel {hotel_id}'
            address = content.get('address') or content.get('addressLine') or group.get('address') or ''
            photo = content.get('main_photo') or content.get('mainPhoto') or content.get('mainPhotoUrl') or ''
            stars = content.get('stars') or content.get('starRating') or content.get('star_rating') or 0
            rating = content.get('rating') or content.get('reviewScore') or group.get('rating') or 0
            room_name = room.get('roomName') or room.get('name') or room.get('roomType') or rate.get('roomName') or 'Available room'
            board = rate.get('boardName') or rate.get('boardType') or room.get('boardName') or ''
            items.append({
                'hotelId': hotel_id,
                'name': name,
                'address': address,
                'rating': rating,
                'stars': stars,
                'price': round(price, 2),
                'currency': _currency(rate, room, group),
                'roomName': room_name,
                'boardName': board,
                'refundable': _refundable(room, rate),
                'offerId': offer_id,
                'mainPhoto': photo,
                'raw': {'hotel': content, 'rateGroup': group, 'room': room},
            })

    # Some accounts/API response versions place an offer directly on the hotel record.
    if not items:
        for index, hotel in enumerate(hotels):
            if not isinstance(hotel, dict):
                continue
            offer_id = str(hotel.get('offerId') or hotel.get('offer_id') or '')
            if not offer_id:
                continue
            items.append({
                'hotelId': str(hotel.get('id') or hotel.get('hotelId') or index),
                'name': hotel.get('name') or 'Hotel',
                'address': hotel.get('address') or '',
                'rating': hotel.get('rating') or 0,
                'stars': hotel.get('stars') or 0,
                'price': _money(hotel.get('price') or hotel.get('retailRate')),
                'currency': _currency(hotel),
                'roomName': hotel.get('roomName') or 'Available room',
                'boardName': hotel.get('boardName') or '',
                'refundable': bool(hotel.get('refundable', False)),
                'offerId': offer_id,
                'mainPhoto': hotel.get('mainPhoto') or hotel.get('main_photo') or '',
                'raw': hotel,
            })
    return items


search_rates = retrieveHotelOffers
prebook = validateHotelOffer
book = createBookingReference
