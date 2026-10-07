import os
import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from auth_utils import auth_required
from utils import utc_now_iso
from services.liteapi_service import search_places, retrieveHotelOffers, validateHotelOffer, createBookingReference, normalizeHotelOffers
from services.transaction_reliability import (
    is_ambiguous_provider_error,
    normalize_attempt_id,
    operation_document_id,
    provider_idempotency_key,
)
from services.local_catalog import LOCAL_HOTEL_ITEMS, CAR_RENTALS
from services.malaysian_locality import filter_candidates, normalize_destination_scope
from sequence_contract.validators import validateHotelSearchCriteria, validateBookingDetails, validateCarRentalSearchCriteria
from sequence_contract.domain_functions import applyHotelFilter, compareSelectedHotels, calculateBudget
from sequence_contract.firebase_firestore import claimRecord, retrieveRecord, updateRecord

bp = Blueprint('fr08_hotels', __name__, url_prefix='/api/fr8')


def _fallback_mode():
    return os.getenv('FALLBACK_MODE', 'false').lower() in {'1', 'true', 'yes'}


def _liteapi_configured():
    return bool(os.getenv('LITEAPI_KEY', '').strip())


def _booking_attempt_id(payload):
    raw = payload.get('hotelBookingAttemptId') or f"legacy_{uuid.uuid4().hex}"
    return normalize_attempt_id(raw, 'hotelBookingAttemptId')


def _hotel_operation_id(attempt_id, stage):
    return operation_document_id(f'hotel_{stage}', g.uid, attempt_id)


def _simulated_reference(provider_key, prefix, length):
    token = provider_key.rsplit('_', 1)[-1][:length].upper()
    return f'{prefix}{token}'


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
        destination = payload.get('destination') or payload.get('aiSearch') or (
            'Penang' if payload.get('placeId') == 'local_penang' else ''
        )
        items, _rejected = filter_candidates(
            LOCAL_HOTEL_ITEMS, normalize_destination_scope(destination)
        )
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
    payload = request.get_json(silent=True) or {}
    offer = str(payload.get('offerId', '')).strip()
    if not offer:
        return jsonify({'ok': False, 'error': 'offerId is required'}), 400
    try:
        attempt_id = _booking_attempt_id(payload)
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    document_id = _hotel_operation_id(attempt_id, 'prebook')
    provider_key = provider_idempotency_key(
        'hotel', g.uid, attempt_id, 'prebook'
    )
    now = utc_now_iso()
    claimed, created = claimRecord('hotel_prebook_attempts', document_id, {
        'travellerId': g.uid,
        'hotelBookingAttemptId': attempt_id,
        'offerId': offer,
        'stage': 'prebook',
        'status': 'pending',
        'providerRequestKey': provider_key,
        'createdAt': now,
        'updatedAt': now,
    })
    if claimed.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'Prebook attempt not found'}), 404
    if str(claimed.get('offerId') or '') != offer:
        return jsonify({'ok': False, 'error': 'hotelBookingAttemptId is already bound to another offer'}), 409
    if not created:
        if claimed.get('status') == 'succeeded':
            return jsonify({
                'ok': True,
                'result': claimed.get('providerResult') or {
                    'prebookId': claimed.get('prebookId'),
                    'offerId': offer,
                    'status': 'prebooked',
                    'sandbox': claimed.get('isSimulated', False),
                },
                'hotelBookingAttemptId': attempt_id,
                'source': claimed.get('source', 'local'),
                'reused': True,
            })
        return jsonify({
            'ok': True,
            'hotelBookingAttemptId': attempt_id,
            'status': 'pending',
            'reconciliationRequired': True,
            'message': 'Prebook outcome is still being verified; it was not submitted again.',
        }), 202

    use_demo = _fallback_mode() and (
        offer.startswith('local_offer_') or not _liteapi_configured()
    )
    try:
        if use_demo:
            result = {
                'prebookId': _simulated_reference(provider_key, 'local_prebook_', 16),
                'offerId': offer,
                'status': 'prebooked',
                'sandbox': True,
            }
            source = 'local'
        else:
            result = validateHotelOffer(offer)
            source = 'liteapi'
    except Exception as exc:
        if is_ambiguous_provider_error(exc):
            patch = {
                'status': 'pending',
                'stage': 'prebook_outcome_unknown',
                'reconciliationRequired': True,
                'updatedAt': utc_now_iso(),
            }
            updateRecord('hotel_prebook_attempts', document_id, patch)
            return jsonify({
                'ok': True,
                'hotelBookingAttemptId': attempt_id,
                'status': 'pending',
                'reconciliationRequired': True,
                'message': 'Prebook outcome is unknown and was not automatically resubmitted.',
            }), 202
        if not _fallback_mode():
            updateRecord('hotel_prebook_attempts', document_id, {
                'status': 'failed',
                'failureReason': str(exc),
                'updatedAt': utc_now_iso(),
            })
            return jsonify({'ok': False, 'error': str(exc)}), 502
        result = {
            'prebookId': _simulated_reference(provider_key, 'local_prebook_', 16),
            'offerId': offer,
            'status': 'prebooked',
            'sandbox': True,
        }
        source = 'local'
    patch = {
        'status': 'succeeded',
        'stage': 'prebooked',
        'prebookId': result.get('prebookId') or result.get('id'),
        'providerResult': result,
        'source': source,
        'isSimulated': source == 'local',
        'updatedAt': utc_now_iso(),
    }
    updateRecord('hotel_prebook_attempts', document_id, patch)
    return jsonify({
        'ok': True,
        'result': result,
        'hotelBookingAttemptId': attempt_id,
        'source': source,
    })


def _attach_booking_to_itinerary(document_id, booking, payload):
    itinerary_id = str(payload.get('itineraryId') or booking.get('itineraryId') or '').strip()
    if not itinerary_id:
        return booking, None
    try:
        current = _own_itinerary(itinerary_id)
    except Exception as exc:
        patch = {
            'itineraryId': itinerary_id,
            'itineraryAttachmentStatus': 'failed',
            'itineraryAttachmentError': str(exc),
            'updatedAt': utc_now_iso(),
        }
        updated = updateRecord('hotel_bookings', document_id, patch) or {**booking, **patch}
        return updated, None
    if not current:
        patch = {
            'itineraryId': itinerary_id,
            'itineraryAttachmentStatus': 'failed',
            'itineraryAttachmentError': 'Itinerary was not found or is not owned by the traveller',
            'updatedAt': utc_now_iso(),
        }
        updated = updateRecord('hotel_bookings', document_id, patch) or {**booking, **patch}
        return updated, None
    selected_hotel = booking.get('selectedHotel') or {}
    hotel_cost = float(booking.get('hotelCost') or 0)
    trip_patch = {
        'selectedHotel': selected_hotel,
        'hotelCost': hotel_cost,
        'hotelBookingId': document_id,
    }
    trip_patch['budgetEstimate'] = calculateBudget({**current, **trip_patch})
    try:
        itinerary = updateRecord('itineraries', itinerary_id, trip_patch)
        patch = {
            'itineraryId': itinerary_id,
            'itineraryAttachmentStatus': 'succeeded',
            'updatedAt': utc_now_iso(),
        }
        updated = updateRecord('hotel_bookings', document_id, patch) or {**booking, **patch}
        return updated, itinerary
    except Exception as exc:
        patch = {
            'itineraryId': itinerary_id,
            'itineraryAttachmentStatus': 'failed',
            'itineraryAttachmentError': str(exc),
            'updatedAt': utc_now_iso(),
        }
        updated = updateRecord('hotel_bookings', document_id, patch) or {**booking, **patch}
        return updated, None


def _booking_response(booking, itinerary=None, reused=False, status_code=200):
    status = str(booking.get('bookingStatus') or 'pending')
    public_booking = {
        key: value for key, value in booking.items()
        if key != 'providerRequestKey'
    }
    return jsonify({
        'ok': status not in {'failed'},
        'id': booking.get('id'),
        'booking': public_booking,
        'itinerary': itinerary,
        'source': booking.get('source', 'local'),
        'hotelBookingAttemptId': booking.get('hotelBookingAttemptId', ''),
        'status': status,
        'reused': reused,
        'reconciliationRequired': status == 'pending',
    }), status_code


@bp.post('/hotels/book')
@auth_required(['traveller'])
def hotel_book():
    payload = request.get_json(silent=True) or {}
    if not validateBookingDetails(payload):
        return jsonify({'ok': False, 'error': 'prebookId is required'}), 400

    try:
        attempt_id = _booking_attempt_id(payload)
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    prebook_id = str(payload.get('prebookId') or '')
    selected_hotel = payload.get('selectedHotel') if isinstance(payload.get('selectedHotel'), dict) else {}
    hotel_cost = float(payload.get('hotelCost') or selected_hotel.get('price') or 0)
    document_id = _hotel_operation_id(attempt_id, 'book')
    provider_key = provider_idempotency_key('hotel', g.uid, attempt_id, 'book')
    now = utc_now_iso()
    record = {
        'travellerId': g.uid,
        'hotelBookingAttemptId': attempt_id,
        'prebookId': prebook_id,
        'bookingStatus': 'pending',
        'stage': 'booking_pending',
        'providerRequestKey': provider_key,
        'selectedHotel': selected_hotel,
        'roomQuantity': selected_hotel.get('roomQuantity') or payload.get('roomQuantity') or 1,
        'hotelCost': hotel_cost,
        'itineraryId': str(payload.get('itineraryId') or '').strip(),
        'itineraryAttachmentStatus': 'pending' if payload.get('itineraryId') else 'not_requested',
        'createdAt': now,
        'updatedAt': now,
    }
    claimed, created = claimRecord('hotel_bookings', document_id, record)
    if claimed.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'Booking attempt not found'}), 404
    if str(claimed.get('prebookId') or '') != prebook_id:
        return jsonify({'ok': False, 'error': 'hotelBookingAttemptId is already bound to another prebook'}), 409
    if not created:
        if claimed.get('bookingStatus') in {'confirmed', 'paid'}:
            updated, itinerary = _attach_booking_to_itinerary(document_id, claimed, payload)
            return _booking_response(updated, itinerary, reused=True)
        if claimed.get('bookingStatus') == 'failed':
            return _booking_response(claimed, reused=True, status_code=409)
        # LiteAPI has no reconciliation/status lookup in this integration. A
        # pending duplicate is deliberately not submitted to the provider again.
        return _booking_response(claimed, reused=True, status_code=202)

    source = 'liteapi'
    use_demo = _fallback_mode() and (
        prebook_id.startswith('local_prebook_') or not _liteapi_configured()
    )
    try:
        if use_demo:
            result = {
                'bookingId': _simulated_reference(provider_key, 'TM-DEMO-', 10),
                'hotelConfirmationCode': _simulated_reference(provider_key, 'DEMO-', 8),
                'status': 'confirmed',
                'sandbox': True,
            }
            source = 'local'
        else:
            # Stage identity is persisted locally. LiteAPI's current integration
            # has no guaranteed idempotency contract, so it is not resubmitted
            # after an ambiguous outcome.
            provider_payload = {
                k: v for k, v in payload.items()
                if k not in {
                    'itineraryId', 'selectedHotel', 'hotelCost',
                    'hotelBookingAttemptId', 'roomQuantity',
                }
            }
            result = createBookingReference(provider_payload)
    except Exception as exc:
        if is_ambiguous_provider_error(exc):
            patch = {
                'bookingStatus': 'pending',
                'stage': 'booking_outcome_unknown',
                'reconciliationRequired': True,
                'verificationRequired': True,
                'updatedAt': utc_now_iso(),
            }
            pending = updateRecord('hotel_bookings', document_id, patch) or {
                'id': document_id,
                **record,
                **patch,
            }
            return _booking_response(pending, status_code=202)
        if not _fallback_mode():
            patch = {
                'bookingStatus': 'failed',
                'stage': 'booking_failed',
                'failureReason': str(exc),
                'updatedAt': utc_now_iso(),
            }
            updateRecord('hotel_bookings', document_id, patch)
            return jsonify({'ok': False, 'error': str(exc), 'hotelBookingAttemptId': attempt_id}), 502
        result = {
            'bookingId': _simulated_reference(provider_key, 'TM-DEMO-', 10),
            'hotelConfirmationCode': _simulated_reference(provider_key, 'DEMO-', 8),
            'status': 'confirmed',
            'sandbox': True,
        }
        source = 'local'

    patch = {
        'bookingStatus': result.get('status', 'confirmed'),
        'bookingReference': result.get('bookingId') or result.get('id') or result.get('hotelConfirmationCode', ''),
        'providerResult': result,
        'source': source,
        'bookingMode': 'simulation' if source == 'local' else 'provider',
        'isSimulated': source == 'local',
        'confirmationLabel': 'Simulated confirmation' if source == 'local' else 'Provider confirmation',
        'stage': 'booking_confirmed',
        'updatedAt': utc_now_iso(),
    }
    saved = updateRecord('hotel_bookings', document_id, patch) or {
        'id': document_id,
        **record,
        **patch,
    }
    saved, itinerary = _attach_booking_to_itinerary(document_id, saved, payload)
    return _booking_response(saved, itinerary)


@bp.get('/bookings/attempts/<attempt_id>')
@auth_required(['traveller'])
def reconcile_booking(attempt_id):
    try:
        attempt_id = normalize_attempt_id(attempt_id, 'hotelBookingAttemptId')
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    record = retrieveRecord('hotel_bookings', _hotel_operation_id(attempt_id, 'book'))
    if not record or record.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'Booking attempt not found'}), 404
    status_code = 202 if record.get('bookingStatus') == 'pending' else 200
    return _booking_response(record, reused=True, status_code=status_code)


@bp.get('/bookings')
@auth_required(['traveller'])
def bookings():
    records = retrieveRecord('hotel_bookings', filters=[('travellerId', '==', g.uid)])
    items = [
        {key: value for key, value in record.items() if key != 'providerRequestKey'}
        for record in records
    ]
    return jsonify({'ok': True, 'items': items})


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
