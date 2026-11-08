"""Read-only property discovery and safe package accommodation provenance."""
import ipaddress
import math
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests
from services.liteapi_service import retrieveHotelContent, retrieveHotelProperties, normalizeHotelContent


class HotelDataError(Exception):
    def __init__(self, message, status=400, code='invalid_hotel_selection'):
        super().__init__(message)
        self.status, self.code = status, code


def _text(value, maximum=200):
    if not isinstance(value, str):
        return None
    value = re.sub(r'<[^>]*>', '', value)
    value = ''.join(char for char in value if ord(char) >= 32).strip()
    return value[:maximum] or None


def valid_hotel_id(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value) is not None


def _number(value, maximum):
    if isinstance(value, bool) or value is None or value == '':
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and 0 <= number <= maximum else None
    except (ValueError, TypeError, OverflowError):
        return None


def _stars(value):
    stars = _number(value, 5)
    return stars if stars is not None and stars >= 1 and stars * 2 == int(stars * 2) else None


def _image(value):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 for c in value):
        return None
    try:
        url = urlsplit(value)
        if (url.scheme != 'https' or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.port not in {None, 443}
                or url.hostname.lower() in {'localhost', 'localhost.localdomain'}
                or url.hostname.lower().endswith(('.local', '.localhost'))):
            return None
        try:
            if not ipaddress.ip_address(url.hostname).is_global:
                return None
        except ValueError:
            pass
        return value
    except ValueError:
        return None


def _amenities(value):
    if not isinstance(value, list):
        return []
    result = []
    for raw in value[:50]:
        text = _text(raw.get('name') if isinstance(raw, dict) else raw, 100)
        if text and text not in result:
            result.append(text)
    return result[:20]


def safe_hotel_snapshot(value):
    """Recursive allowlist for stored/public/new-checkout display snapshots."""
    if (not isinstance(value, dict) or value.get('provider') != 'liteapi'
            or not valid_hotel_id(value.get('hotelId')) or not _text(value.get('name'))):
        return None
    stars = _stars(value.get('stars'))
    images = value.get('imageUrls') if isinstance(value.get('imageUrls'), list) else []
    image_urls = list(dict.fromkeys(url for raw in images[:8] if (url := _image(raw))))
    main_photo = _image(value.get('mainPhoto')) or (image_urls[0] if image_urls else None)
    stamp = None
    try:
        parsed = datetime.fromisoformat(str(value.get('retrievedAt')).replace('Z', '+00:00'))
        if parsed.tzinfo is not None:
            stamp = parsed.isoformat()
    except (TypeError, ValueError):
        pass
    return {'provider': 'liteapi', 'hotelId': value['hotelId'], 'name': _text(value['name']),
            'address': _text(value.get('address'), 500), 'city': _text(value.get('city')),
            'country': _text(value.get('country')), 'stars': stars,
            'starClassificationSource': 'liteapi' if stars is not None else None,
            'guestRating': _number(value.get('guestRating'), 10), 'imageUrls': image_urls,
            'mainPhoto': main_photo, 'amenities': _amenities(value.get('amenities')),
            'source': 'liteapi_property_content', 'retrievedAt': stamp, 'reservationStatus': 'not_created'}


def safe_room_snapshot(value, hotel_id):
    if not valid_hotel_id(hotel_id) or not isinstance(value, dict) or value.get('hotelId') != hotel_id:
        return None
    room_id = str(value.get('id') or '')
    name = _text(value.get('roomName'))
    if isinstance(value.get('id'), bool) or not valid_hotel_id(room_id) or not name:
        return None
    beds = []
    raw_beds = value.get('bedTypes') if isinstance(value.get('bedTypes'), list) else []
    for bed in raw_beds[:12]:
        if isinstance(bed, dict) and _text(bed.get('bedType')):
            beds.append({'bedType': _text(bed['bedType']), 'quantity': _number(bed.get('quantity'), 100),
                         'bedSize': _text(bed.get('bedSize'))})
    photos = value.get('photos') if isinstance(value.get('photos'), list) else []
    return {'id': room_id, 'hotelId': hotel_id, 'roomName': name,
            'description': _text(value.get('description'), 1500), 'bedTypes': beds,
            'bedRelation': value.get('bedRelation') if value.get('bedRelation') in {'AND', 'OR', 'NONE', 'COMPLEX'} else None,
            **{key: _number(value.get(key), 100) for key in ('maxAdults', 'maxChildren', 'maxOccupancy')},
            'roomAmenities': _amenities(value.get('roomAmenities')),
            'photos': [url for photo in photos[:8] if (url := _image(photo.get('url') if isinstance(photo, dict) else photo))],
            'source': 'liteapi_room_content', 'reservationStatus': 'not_created', 'availabilityChecked': False}


def _normalize(raw, expected_id=None):
    if not isinstance(raw, dict):
        raise HotelDataError('Hotel provider returned invalid metadata.', 502, 'hotel_provider_response')
    hotel_id = raw.get('id') or raw.get('hotelId')
    if not valid_hotel_id(hotel_id) or (expected_id and hotel_id != expected_id):
        raise HotelDataError('Hotel provider returned inconsistent hotel identity.', 502, 'hotel_provider_response')
    # Reuse the Traveller content adapter, adding only property-list/detail aliases.
    adapter_input = dict(raw)
    for key in ('images', 'photos'):
        if not isinstance(adapter_input.get(key), (list, str)):
            adapter_input[key] = []
    if not isinstance(adapter_input.get('coordinates'), dict):
        adapter_input['coordinates'] = {}
    value = normalizeHotelContent({'data': adapter_input})
    photos = raw.get('hotelImages') if isinstance(raw.get('hotelImages'), list) else None
    if photos is not None:
        value['imageUrls'] = [p.get('url') if isinstance(p, dict) else p for p in photos[:8]]
    value.update(provider='liteapi', hotelId=hotel_id,
                 city=raw.get('city') or raw.get('city_name'), country=raw.get('country') or raw.get('country_code'),
                 guestRating=value.get('rating'), retrievedAt=datetime.now(timezone.utc).isoformat())
    value['amenities'] = raw.get('amenities') or raw.get('hotelFacilities') or []
    result = safe_hotel_snapshot(value)
    if result is None:
        raise HotelDataError('Hotel provider returned invalid metadata.', 502, 'hotel_provider_response')
    return result


def _provider_call(operation, *args, detail=False):
    try:
        result = operation(*args)
        if not isinstance(result, dict) or result.get('error'):
            raise HotelDataError('Hotel provider returned invalid metadata.', 502, 'hotel_provider_response')
        return result
    except requests.HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 429:
            raise HotelDataError('Hotel information is busy. Please try again shortly.', 429, 'hotel_provider_rate_limit') from None
        if status == 404 and detail:
            raise HotelDataError('Hotel not found.', 404, 'hotel_not_found') from None
        if status in {401, 403}:
            raise HotelDataError('Hotel provider access is unavailable.', 503, 'hotel_provider_configuration') from None
        raise HotelDataError('Hotel provider is temporarily unavailable.', 502, 'hotel_provider_unavailable') from None
    except requests.RequestException:
        raise HotelDataError('Hotel provider is temporarily unavailable.', 502, 'hotel_provider_unavailable') from None
    except (ValueError, TypeError, RuntimeError):
        code = 'hotel_provider_configuration' if not os.getenv('LITEAPI_KEY', '').strip() else 'hotel_provider_unavailable'
        raise HotelDataError('Hotel information is currently unavailable.', 503, code) from None


def search_hotels(arguments):
    allowed = {'countryCode', 'cityName', 'hotelName', 'placeId', 'starRating', 'limit', 'offset'}
    if not set(arguments) <= allowed or any(len(arguments.getlist(key)) != 1 for key in arguments):
        raise HotelDataError('Unsupported or repeated hotel search filter.')
    filters = {}
    for key, maximum in [('countryCode', 2), ('cityName', 100), ('hotelName', 100), ('placeId', 200)]:
        value = arguments.get(key)
        if value is not None:
            if (not isinstance(value, str) or not value.strip() or len(value) > maximum
                    or any(ord(c) < 32 or c in '<>' for c in value)):
                raise HotelDataError('Invalid hotel search filter.')
            filters[key] = value.strip()
    if 'countryCode' in filters:
        if not re.fullmatch(r'[A-Za-z]{2}', filters['countryCode']):
            raise HotelDataError('Use a two-letter countryCode.')
        filters['countryCode'] = filters['countryCode'].upper()
    if not (('cityName' in filters and 'countryCode' in filters) or 'placeId' in filters):
        raise HotelDataError('Provide cityName with countryCode, or a provider placeId.')
    if 'placeId' in filters and ('cityName' in filters or 'countryCode' in filters):
        raise HotelDataError('Use either city/country or placeId for location.')
    try:
        limit, offset = int(arguments.get('limit', '10')), int(arguments.get('offset', '0'))
        if not 1 <= limit <= 20 or not 0 <= offset <= 1000:
            raise ValueError
    except (ValueError, TypeError):
        raise HotelDataError('Use limit 1–20 and offset 0–1000.')
    filters.update(limit=limit, offset=offset)
    if 'starRating' in arguments:
        if len(arguments['starRating']) > 40:
            raise HotelDataError('starRating must contain half-step values from 1 to 5.')
        values = arguments['starRating'].split(',')
        parsed = [_stars(value) for value in values]
        if not values or len(values) > 9 or any(value is None for value in parsed):
            raise HotelDataError('starRating must contain half-step values from 1 to 5.')
        filters['starRating'] = ','.join(f'{value:.1f}' for value in parsed)
    result = _provider_call(retrieveHotelProperties, filters)
    rows = result.get('data')
    if not isinstance(rows, list):
        raise HotelDataError('Hotel provider returned invalid search results.', 502, 'hotel_provider_response')
    items, seen = [], set()
    for raw in rows[:limit]:
        item = _normalize(raw)
        if 'starRating' in filters and item['stars'] not in parsed:
            continue
        if item['hotelId'] not in seen:
            items.append(item)
            seen.add(item['hotelId'])
    return {'ok': True, 'items': items, 'limit': limit, 'offset': offset,
            'hasMore': None if len(rows) >= limit else False,
            'source': 'liteapi_property_content', 'availabilityChecked': False}


def hotel_detail(hotel_id):
    if not valid_hotel_id(hotel_id):
        raise HotelDataError('Invalid hotel ID.')
    result = _provider_call(retrieveHotelContent, hotel_id, detail=True)
    raw = result.get('data')
    if raw is None or raw == [] or raw == {}:
        raise HotelDataError('Hotel not found.', 404, 'hotel_not_found')
    if isinstance(raw, list):
        if len(raw) != 1:
            raise HotelDataError('Hotel provider returned ambiguous hotel metadata.', 502, 'hotel_provider_response')
        raw = raw[0]
    hotel = _normalize(raw, hotel_id)
    rooms = raw.get('rooms') if isinstance(raw.get('rooms'), list) else []
    hotel['rooms'] = []
    for raw_room in rooms[:100]:
        if isinstance(raw_room, dict):
            # The enclosing detail response owns identity when the room omits hotelId.
            room = safe_room_snapshot({'hotelId': hotel_id, **raw_room}, hotel_id)
            if room and not any(saved['id'] == room['id'] for saved in hotel['rooms']):
                hotel['rooms'].append(room)
    return hotel


def resolve_package_hotel(payload, existing=None):
    """Only provider+ID are client inputs; all authoritative facts are re-fetched."""
    if 'accommodationHotel' in payload or 'accommodationRoom' in payload:
        raise HotelDataError('accommodationHotel is server-controlled. Submit hotelSelection instead.')
    updated = dict(payload)
    room_present = 'roomSelection' in updated
    room_selection = updated.pop('roomSelection', None)
    old_hotel = safe_hotel_snapshot((existing or {}).get('accommodationHotel'))
    hotel = old_hotel
    if 'hotelSelection' not in payload:
        if hotel:
            if 'accommodationName' in payload and payload['accommodationName'] != hotel['name']:
                raise HotelDataError('Clear hotelSelection before entering a different accommodation name.')
            if hotel['stars'] is not None and 'accommodationCategory' in payload and payload['accommodationCategory'] != f"{hotel['stars']:g}-Star":
                raise HotelDataError('Clear hotelSelection before overriding the provider star category.')
    else:
        selection = updated.pop('hotelSelection')
        if selection is None:
            hotel = None
            updated.update(accommodationHotel=None, accommodationRoom=None)
            if (existing or {}).get('accommodationRoom') and 'roomType' not in payload:
                updated['roomType'] = ''
        else:
            if (not isinstance(selection, dict) or set(selection) != {'provider', 'hotelId'}
                    or selection.get('provider') != 'liteapi' or not valid_hotel_id(selection.get('hotelId'))):
                raise HotelDataError('Select a LiteAPI hotel using only provider and hotelId.')
            hotel = hotel_detail(selection['hotelId'])
            updated.update(accommodationHotel=safe_hotel_snapshot(hotel), accommodationName=hotel['name'],
                           accommodationCategory=f"{hotel['stars']:g}-Star" if hotel['stars'] is not None else '')
            if not old_hotel or old_hotel['hotelId'] != hotel['hotelId']:
                updated['accommodationRoom'] = None
                if (existing or {}).get('accommodationRoom') and 'roomType' not in payload:
                    updated['roomType'] = ''
    if room_present and room_selection is None:
        updated['accommodationRoom'] = None
    elif room_present:
        if (not hotel or not isinstance(room_selection, dict) or set(room_selection) != {'hotelId', 'roomId'}
                or room_selection.get('hotelId') != hotel['hotelId']
                or not valid_hotel_id(room_selection.get('roomId'))):
            raise HotelDataError('Select a room belonging to the selected hotel.')
        if 'rooms' not in hotel:
            hotel = hotel_detail(hotel['hotelId'])
        room = next((room for room in hotel.get('rooms', []) if room['id'] == room_selection['roomId']), None)
        if room is None:
            raise HotelDataError('Room details are no longer available. Use manual Room Configuration instead.')
        updated['accommodationRoom'] = room
        if not str(updated.get('roomType') or '').strip():
            updated['roomType'] = room['roomName']
    return updated
