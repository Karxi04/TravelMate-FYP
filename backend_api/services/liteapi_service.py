import math
import os
import requests

DATA_BASE = "https://api.liteapi.travel/v3.0"
BOOK_BASE = "https://book.liteapi.travel/v3.0"


class ProviderMutationBlocked(RuntimeError):
    """External hotel mutations are unavailable without confirmed sandbox mode."""


def provider_mutations_allowed():
    # The test harness is allowed to exercise mocked provider boundaries. No
    # production configuration currently proves that a LiteAPI key is sandbox
    # scoped, so real external mutations fail closed.
    return os.getenv('TRAVELMATE_TESTING', '').strip().lower() in {'1', 'true', 'yes'}


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
    if not provider_mutations_allowed():
        raise ProviderMutationBlocked('External hotel validation is unavailable until a confirmed sandbox environment is configured.')
    r = requests.post(
        f'{BOOK_BASE}/rates/prebook',
        headers=_headers(),
        json={'offerId': offerId, 'usePaymentSdk': False},
        timeout=60,
    )
    return _json_or_error(r)


def createBookingReference(payload):
    if not provider_mutations_allowed():
        raise ProviderMutationBlocked('External hotel booking is unavailable until a confirmed sandbox environment is configured.')
    r = requests.post(
        f'{BOOK_BASE}/rates/book',
        headers=_headers(),
        json=payload,
        timeout=65,
    )
    return _json_or_error(r)


def normalizePrebookResult(result, fallback_offer=None):
    """Return a safe, provider-shaped prebook summary without raw payloads."""
    result = result or {}
    data = result.get('data') if isinstance(result, dict) else None
    data = data if isinstance(data, dict) else result
    prebook_id = data.get('prebookId') or result.get('prebookId') or data.get('id')
    offer_id = data.get('offerId') or result.get('offerId') or fallback_offer
    groups = data.get('roomTypes') or data.get('room_types') or []
    group = groups[0] if isinstance(groups, list) and len(groups) == 1 and isinstance(groups[0], dict) else {}
    rates = group.get('rates') if isinstance(group, dict) else []
    rate = rates[0] if isinstance(rates, list) and len(rates) == 1 and isinstance(rates[0], dict) else {}
    amount, basis = _extract_price(group, rate, data)
    if amount is None:
        amount = _money(data.get('price') or data.get('total'))
        if amount is not None:
            basis = 'stay_total'
    if data.get('priceBasis'):
        basis = str(data['priceBasis'])
    currency = _currency(rate, group, data)
    cancellation = _cancellation(group, rate)
    if isinstance(data.get('cancellation'), dict):
        cancellation = data['cancellation']
    fees_status = data.get('taxesAndFeesStatus') or _fees(rate, group)
    return {
        'prebookId': str(prebook_id) if prebook_id else None,
        'offerId': str(offer_id) if offer_id else None,
        'status': str(data.get('status') or result.get('status') or 'prebooked'),
        'price': amount,
        'priceStatus': 'available' if amount is not None else 'unknown',
        'priceBasis': basis,
        'currency': currency,
        'currencyStatus': 'known' if currency else 'unknown',
        'cancellation': cancellation,
        'taxesAndFeesStatus': fees_status,
        'sandbox': bool(data.get('sandbox') or result.get('sandbox')),
    }


def _money(value):
    """Return a finite amount, or None when the provider value is unusable."""
    if isinstance(value, (list, tuple)):
        parsed = [_money(item) for item in value]
        if not parsed or any(item is None for item in parsed):
            return None
        return round(sum(parsed), 2)
    if isinstance(value, dict):
        for key in ('amount', 'total', 'value', 'net'):
            if value.get(key) is not None:
                return _money(value.get(key))
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if math.isfinite(amount) and amount >= 0 else None


def _currency(*objects):
    for obj in objects:
        if isinstance(obj, dict):
            for key in ('currency', 'currencyCode', 'currency_code'):
                if obj.get(key):
                    return str(obj[key])
            for key in ('retailRate', 'retail_rate', 'price', 'offerRetailRate'):
                nested = obj.get(key)
                if isinstance(nested, dict):
                    found = _currency(nested)
                    if found:
                        return found
                elif isinstance(nested, list):
                    found = _currency(*nested)
                    if found:
                        return found
    return None


def _first_rate(room):
    rates = room.get('rates') if isinstance(room, dict) else None
    if isinstance(rates, list) and rates:
        return rates[0] if isinstance(rates[0], dict) else {}
    return room if isinstance(room, dict) else {}


def _extract_price(room, rate, group=None):
    """Use an explicit offer total before a single-rate total.

    LiteAPI's offerRetailRate is the whole offer total. A rate retailRate is
    only a safe fallback when no offer-level total is supplied.
    """
    group = group or {}
    offer_total = group.get('offerRetailRate') or room.get('offerRetailRate')
    amount = _money(offer_total)
    if amount is not None:
        return amount, 'stay_total'
    for candidate in (
        rate.get('retailRate'), rate.get('retail_rate'), rate.get('price'),
        rate.get('total'), room.get('retailRate'), room.get('price'), room.get('total'),
    ):
        amount = _money(candidate)
        if amount is not None:
            return amount, 'room_total'
    return None, 'unknown'


def _refundable(room, rate):
    for obj in (rate, room):
        if not isinstance(obj, dict):
            continue
        for key in ('refundable', 'isRefundable', 'is_refundable'):
            if key in obj:
                return bool(obj.get(key))
        policy = obj.get('cancellationPolicies') or obj.get('cancellation_policies')
        if isinstance(policy, dict):
            tag = str(policy.get('refundableTag') or '').upper()
            if tag in {'RFN', 'RF'}:
                return True
            if tag in {'NRFN', 'NRF'}:
                return False
        if isinstance(policy, list) and policy:
            return None
    return None


def _cancellation(room, rate):
    for obj in (rate, room):
        policy = obj.get('cancellationPolicies') or obj.get('cancellation_policies')
        if not policy:
            continue
        if isinstance(policy, dict):
            tag = policy.get('refundableTag')
            infos = policy.get('cancelPolicyInfos') or policy.get('cancel_policy_infos') or []
            deadline = None
            penalties = []
            if isinstance(infos, list):
                for info in infos:
                    if not isinstance(info, dict):
                        continue
                    deadline = deadline or info.get('cancelTime') or info.get('cancel_time')
                    if info.get('amount') is not None:
                        penalties.append({
                            'amount': _money(info.get('amount')),
                            'currency': info.get('currency'),
                        })
            return {
                'tag': str(tag).upper() if tag else None,
                'deadline': deadline,
                'penalties': penalties,
                'status': 'known' if tag or deadline or penalties else 'unknown',
            }
        if isinstance(policy, list):
            return {'tag': None, 'deadline': None, 'penalties': [], 'status': 'known'}
    return {'tag': None, 'deadline': None, 'penalties': [], 'status': 'unknown'}


def _fees(rate, room):
    for obj in (rate, room):
        retail = obj.get('retailRate') if isinstance(obj, dict) else None
        values = None
        if isinstance(retail, dict):
            values = retail.get('taxesAndFees') or retail.get('taxes_and_fees')
        if values is None and isinstance(obj, dict):
            values = obj.get('taxesAndFees') or obj.get('taxes_and_fees')
        if not isinstance(values, list):
            continue
        included = {bool(item.get('included')) for item in values if isinstance(item, dict) and 'included' in item}
        if included == {True}:
            return 'included'
        if included == {False}:
            return 'excluded'
        if included:
            return 'mixed'
    return 'unknown'


def normalizeHotelOffers(result):
    """Normalize both current LiteAPI response variants into one Flutter-friendly list."""
    result = result or {}
    hotels = result.get('hotels')
    if not isinstance(hotels, list) and isinstance(result.get('data'), dict):
        hotels = result['data'].get('hotels')
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
            price, price_basis = _extract_price(room, rate, group)
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
                'price': price,
                'priceStatus': 'available' if price is not None else 'unknown',
                'priceBasis': price_basis,
                'currency': _currency(rate, room, group),
                'currencyStatus': 'known' if _currency(rate, room, group) else 'unknown',
                'roomName': room_name,
                'boardName': board,
                'refundable': _refundable(room, rate),
                'cancellation': _cancellation(room, rate),
                'taxesAndFeesStatus': _fees(rate, room),
                'offerId': offer_id,
                'mainPhoto': photo,
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
                'priceStatus': 'available' if _money(hotel.get('price') or hotel.get('retailRate')) is not None else 'unknown',
                'priceBasis': 'stay_total',
                'currency': _currency(hotel),
                'currencyStatus': 'known' if _currency(hotel) else 'unknown',
                'roomName': hotel.get('roomName') or 'Available room',
                'boardName': hotel.get('boardName') or '',
                'refundable': hotel.get('refundable'),
                'cancellation': {'tag': None, 'deadline': None, 'penalties': [], 'status': 'unknown'},
                'taxesAndFeesStatus': 'unknown',
                'offerId': offer_id,
                'mainPhoto': hotel.get('mainPhoto') or hotel.get('main_photo') or '',
            })
    return items


search_rates = retrieveHotelOffers
prebook = validateHotelOffer
book = createBookingReference
