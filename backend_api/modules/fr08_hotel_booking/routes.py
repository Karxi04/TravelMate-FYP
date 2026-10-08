import os
import hashlib
import json
import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from auth_utils import auth_required
from utils import utc_now_iso
from services.liteapi_service import (
    search_places, retrieveHotelOffers, validateHotelOffer, createBookingReference,
    retrieveHotelContent, normalizeHotelContent, normalizeHotelOffers,
    normalizePrebookResult, ProviderMutationBlocked,
)
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


def _sample_mode():
    # FALLBACK_MODE remains useful for other modules. Hotel sample data is only
    # enabled explicitly or inside the deterministic test harness.
    return os.getenv('HOTEL_SAMPLE_MODE', '').lower() in {'1', 'true', 'yes'} or (
        _testing_mode() and _fallback_mode()
    )


def _transaction_mode():
    configured = os.getenv('HOTEL_TRANSACTION_MODE', '').strip().lower()
    if configured in {'local_demo', 'provider_sandbox'}:
        return configured
    # Existing provider-boundary tests retain their guarded sandbox path. A
    # normal configured deployment always defaults to a local demo transaction.
    if _testing_mode() and _liteapi_configured():
        return 'provider_sandbox'
    return 'local_demo'


def _booking_attempt_id(payload):
    raw = payload.get('hotelBookingAttemptId') or f"legacy_{uuid.uuid4().hex}"
    return normalize_attempt_id(raw, 'hotelBookingAttemptId')


def _hotel_operation_id(attempt_id, stage):
    return operation_document_id(f'hotel_{stage}', g.uid, attempt_id)


def _simulated_reference(provider_key, prefix, length):
    token = provider_key.rsplit('_', 1)[-1][:length].upper()
    return f'{prefix}{token}'


def _testing_mode():
    return os.getenv('TRAVELMATE_TESTING', '').lower() in {'1', 'true', 'yes'}


def _provenance(source, now=None):
    now = now or utc_now_iso()
    if source == 'liteapi':
        return {
            'contentSource': 'liteapi_provider',
            'rateSource': 'liteapi_live_quote',
            'rateProvenance': 'live_provider_quote',
            'quoteRetrievedAt': now,
            'transactionMode': _transaction_mode(),
            'demoDisclosure': 'Demo reservation — no room will be reserved.' if _transaction_mode() == 'local_demo' else 'Provider sandbox transaction.',
        }
    return {
        'contentSource': 'sample_fixture',
        'rateSource': 'sample_fixture',
        'rateProvenance': 'explicit_sample_fixture',
        'quoteRetrievedAt': now,
        'transactionMode': 'local_demo',
        'demoDisclosure': 'Sample hotel content and price; not live availability. Demo reservation — no room will be reserved.',
    }


def _local_validation_id(provider_key):
    return _simulated_reference(provider_key, 'demo_validation_', 16)


def _local_demo_validation(quote, offer, provider_key):
    validation_id = _local_validation_id(provider_key)
    return {
        'validationId': validation_id,
        'offerId': offer,
        'status': 'validated',
        'validationMode': 'local_demo',
        'isSimulated': True,
        'sandbox': False,
        **(quote.get('offer') or {}),
    }


def _safe_provider_error(exc, fallback):
    return str(exc) if isinstance(exc, ProviderMutationBlocked) else fallback


def _quote_document_id(quote_id):
    return f'{g.uid}_{quote_id}'


def _quote_version(offer):
    material = {
        key: offer.get(key)
        for key in (
            'offerId', 'hotelId', 'price', 'currency', 'priceBasis',
            'taxesAndFeesStatus', 'cancellation', 'roomQuantity',
        )
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _search_criteria(payload, req, room_quantity):
    return {
        'destination': payload.get('destination') or payload.get('aiSearch') or '',
        'placeId': payload.get('placeId'),
        'hotelIds': payload.get('hotelIds'),
        'checkin': payload.get('checkin'),
        'checkout': payload.get('checkout'),
        'adults': int(payload.get('adults', 1) or 1),
        'roomQuantity': room_quantity,
        'occupancies': req.get('occupancies') or [],
        'currency': req.get('currency'),
        'guestNationality': req.get('guestNationality'),
    }


def _persist_quotes(items, criteria, source):
    output = []
    for item in items:
        item = dict(item)
        item['quoteVersion'] = _quote_version(item)
        quote_id = hashlib.sha256(json.dumps({
            'uid': g.uid, 'criteria': criteria, 'offer': item,
        }, sort_keys=True, default=str).encode()).hexdigest()[:32]
        item['quoteId'] = quote_id
        record = {
            'quoteId': quote_id,
            'travellerId': g.uid,
            'offer': item,
            'criteria': criteria,
            'source': source,
            'createdAt': utc_now_iso(),
            'updatedAt': utc_now_iso(),
        }
        claimRecord('hotel_offer_quotes', _quote_document_id(quote_id), record)
        output.append(item)
    return output


def _resolve_quote(payload, offer):
    quote_id = str(payload.get('quoteId') or '').strip()
    if quote_id:
        record = retrieveRecord('hotel_offer_quotes', _quote_document_id(quote_id))
        if not record or record.get('travellerId') != g.uid:
            return None, 'The hotel quote was not found or is not owned by this traveller.'
        trusted = dict(record.get('offer') or {})
        if trusted.get('offerId') != offer:
            return None, 'This quote is bound to a different hotel offer.'
        return record, None
    if _testing_mode() and offer.startswith('local_offer_'):
        item = next((dict(x) for x in LOCAL_HOTEL_ITEMS if x.get('offerId') == offer), None)
        if item is None:
            # Test-only synthetic local offers exercise the same trusted quote
            # path without allowing a client-supplied amount into production.
            item = {
                'offerId': offer,
                'hotelId': f'test_hotel_{offer[-12:]}',
                'name': 'Demo local hotel',
                'price': 120.0,
                'priceStatus': 'available',
                'priceBasis': 'stay_total',
                'currency': 'MYR',
                'currencyStatus': 'known',
                'taxesAndFeesStatus': 'included',
                'cancellation': {'tag': 'RFN', 'status': 'known'},
                'refundable': True,
            }
        if item:
            item.setdefault('priceStatus', 'available')
            item.setdefault('priceBasis', 'per_room_night')
            item.setdefault('currencyStatus', 'known')
            item.setdefault('taxesAndFeesStatus', 'unknown')
            item.setdefault('cancellation', {'tag': 'RFN' if item.get('refundable') else 'NRFN', 'status': 'known'})
            return {'quoteId': 'test-local-quote', 'travellerId': g.uid, 'offer': item, 'criteria': {}}, None
    return None, 'quoteId is required; search again before validating this hotel offer.'


def _material_quote_changes(original, validated):
    keys = ('price', 'currency', 'taxesAndFeesStatus')
    changes = {
        key: {'before': original.get(key), 'after': validated.get(key)}
        for key in keys if original.get(key) != validated.get(key)
    }
    old_policy = original.get('cancellation') or {}
    new_policy = validated.get('cancellation') or {}
    if old_policy != new_policy:
        changes['cancellation'] = {'before': old_policy, 'after': new_policy}
    return changes


def _authoritative_offer(record):
    offer = dict(record.get('validatedOffer') or record.get('offer') or {})
    amount = offer.get('price')
    currency = str(offer.get('currency') or '').upper()
    if offer.get('priceStatus') != 'available' or not isinstance(amount, (int, float)) or amount < 0:
        return None, 'The validated hotel price is unavailable; search again.'
    if currency != 'MYR':
        return None, 'Only MYR hotel offers can be attached to the current MYR trip and payment flow.'
    return offer, None


def _safe_booking_result(result):
    if not isinstance(result, dict):
        return {'status': 'unknown'}
    return {
        key: result.get(key)
        for key in ('bookingId', 'id', 'hotelConfirmationCode', 'status', 'currency', 'amount', 'total', 'sandbox')
        if result.get(key) is not None
    }


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
            return jsonify({'ok': False, 'error': 'Hotel provider is unavailable right now.'}), 502
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
        'currency': payload.get('currency') or 'MYR',
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
        provenance = _provenance(source)
        # LiteAPI rate responses may omit property content. Enrich only those
        # properties, by exact provider ID, and keep the read-only boundary.
        content_cache = {}
        if _liteapi_configured() and not _testing_mode():
            for hotel_id in list({str(item.get('hotelId') or '') for item in items})[:20]:
                if not hotel_id:
                    continue
                try:
                    content_cache[hotel_id] = normalizeHotelContent(
                        retrieveHotelContent(hotel_id), hotel_id
                    )
                except Exception:
                    content_cache[hotel_id] = {}
            for item in items:
                content = content_cache.get(str(item.get('hotelId') or ''), {})
                for key, value in content.items():
                    if value not in (None, '', []):
                        item.setdefault(key, value)
    except Exception as exc:
        if not _sample_mode():
            return jsonify({'ok': False, 'error': _safe_provider_error(
                exc, 'The hotel offer could not be validated right now.'
            )}), 502
        destination = payload.get('destination') or payload.get('aiSearch') or (
            'Penang' if payload.get('placeId') == 'local_penang' else ''
        )
        items, _rejected = filter_candidates(
            LOCAL_HOTEL_ITEMS, normalize_destination_scope(destination)
        )
        result = {'items': items, 'sandbox': True}
        source = 'local'
        provenance = _provenance(source)

    filters = {
        'refundable': payload.get('refundable'),
        'sort': payload.get('sort'),
    }
    items = applyHotelFilter(items, filters)
    for item in items:
        item.update(provenance)
        item['roomQuantity'] = room_quantity
        if item.get('priceBasis') == 'per_room_night' and item.get('priceStatus') == 'available':
            item['nightlyRoomRate'] = item.get('price')
            item['price'] = round(float(item['price']) * room_quantity, 2)
            item['priceBasis'] = 'stay_total'
        elif item.get('priceBasis') == 'room_total':
            item['nightlyRoomRate'] = None
            # The provider response did not expose an offer-level total. Do
            # not multiply an ambiguous room/rate amount by room count.
            item['priceStatus'] = 'unknown'
            item['price'] = None
    items = _persist_quotes(items, _search_criteria(payload, req, room_quantity), source)
    return jsonify({
        'ok': True,
        'items': items,
        'result': {'items': items},
        'source': source,
        'contentSource': provenance['contentSource'],
        'rateSource': provenance['rateSource'],
        'quoteRetrievedAt': provenance['quoteRetrievedAt'],
        'transactionMode': provenance['transactionMode'],
    })


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
    quote, quote_error = _resolve_quote(payload, offer)
    if quote_error:
        return jsonify({'ok': False, 'error': quote_error}), 400
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
        'quoteId': quote.get('quoteId'),
        'offer': quote.get('offer') or {},
        'criteria': quote.get('criteria') or {},
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
            reused_result = claimed.get('providerResult') or {
                'validationId': claimed.get('validationId'),
                'offerId': offer,
                'status': claimed.get('validationStatus') or 'validated',
                'sandbox': claimed.get('isSimulated', False),
            }
            if claimed.get('prebookId') and not reused_result.get('prebookId'):
                reused_result['prebookId'] = claimed.get('prebookId')
            return jsonify({
                'ok': True,
                'result': reused_result,
                'hotelBookingAttemptId': attempt_id,
                'source': claimed.get('source', 'local'),
                'reused': True,
            })
        if claimed.get('status') == 'reprice_required':
            accepted = str(payload.get('acceptedQuoteVersion') or '')
            if accepted and accepted == claimed.get('validatedQuoteVersion'):
                promoted = updateRecord('hotel_prebook_attempts', document_id, {
                    'status': 'succeeded', 'stage': 'prebooked',
                    'acceptedQuoteVersion': accepted, 'updatedAt': utc_now_iso(),
                }) or claimed
                return jsonify({
                    'ok': True,
                    'result': promoted.get('validatedOffer') or {},
                    'hotelBookingAttemptId': attempt_id,
                    'source': promoted.get('source', 'liteapi'),
                    'acceptedQuoteVersion': accepted,
                })
            return jsonify({
                'ok': False,
                'status': 'reprice_required',
                'error': 'Review and accept the latest validated hotel price and terms before continuing.',
                'changes': claimed.get('quoteChanges') or {},
                'validatedOffer': claimed.get('validatedOffer') or {},
                'quoteVersion': claimed.get('validatedQuoteVersion'),
            }), 409
        return jsonify({
            'ok': True,
            'hotelBookingAttemptId': attempt_id,
            'status': 'pending',
            'reconciliationRequired': True,
            'message': 'Prebook outcome is still being verified; it was not submitted again.',
        }), 202

    use_demo = _transaction_mode() == 'local_demo'
    try:
        if use_demo:
            result = _local_demo_validation(quote, offer, provider_key)
            source = 'local'
        else:
            result = validateHotelOffer(offer)
            source = 'liteapi'
    except ProviderMutationBlocked as exc:
        updateRecord('hotel_prebook_attempts', document_id, {
            'status': 'failed', 'stage': 'provider_mutation_blocked',
            'failureReason': str(exc), 'updatedAt': utc_now_iso(),
        })
        return jsonify({'ok': False, 'error': str(exc), 'status': 'provider_unavailable'}), 503
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
        if not _fallback_mode() or not offer.startswith('local_offer_'):
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
    if use_demo:
        validated = dict(result)
        version = _quote_version(validated)
        original = quote.get('offer') or {}
        changes = _material_quote_changes(original, validated)
        if validated.get('priceStatus') != 'available' or not validated.get('currency'):
            updateRecord('hotel_prebook_attempts', document_id, {
                'status': 'failed', 'stage': 'demo_unpriced',
                'validatedOffer': validated, 'updatedAt': utc_now_iso(),
            })
            return jsonify({'ok': False, 'error': 'The hotel price or currency is unavailable; search again.'}), 422
        patch = {
            'status': 'succeeded', 'stage': 'validated_local_demo',
            'validationId': validated['validationId'],
            'validationStatus': 'validated',
            'validatedOffer': validated,
            'validatedQuoteVersion': version,
            'quoteChanges': changes,
            'source': source,
            'isSimulated': True,
            'providerMutationCalled': False,
            'demoDisclosure': 'Demo reservation — no room will be reserved.',
            'updatedAt': utc_now_iso(),
        }
        updateRecord('hotel_prebook_attempts', document_id, patch)
        return jsonify({
            'ok': True, 'result': validated,
            'hotelBookingAttemptId': attempt_id, 'source': source,
        })

    validated = normalizePrebookResult(result, offer)
    # Keep non-sensitive offer presentation fields from the server quote while
    # allowing only normalized provider values to replace price/terms.
    if source != 'local':
        authority = {'price', 'priceStatus', 'priceBasis', 'currency',
                     'currencyStatus', 'cancellation', 'taxesAndFeesStatus'}
        presentation = {
            key: value for key, value in (quote.get('offer') or {}).items()
            if key not in authority
        }
        validated = {
            **presentation,
            **{key: value for key, value in validated.items() if value is not None},
        }
    if source == 'local':
        validated.update({
            key: value for key, value in (quote.get('offer') or {}).items()
            if key in {'price', 'priceStatus', 'priceBasis', 'currency', 'currencyStatus', 'cancellation', 'taxesAndFeesStatus'}
        })
    if not validated.get('prebookId'):
        updateRecord('hotel_prebook_attempts', document_id, {
            'status': 'failed', 'stage': 'prebook_unusable',
            'failureReason': 'Provider did not return a prebook ID', 'updatedAt': utc_now_iso(),
        })
        return jsonify({'ok': False, 'error': 'The hotel offer could not be validated; search again.'}), 422
    if validated.get('priceStatus') != 'available' or not validated.get('currency'):
        updateRecord('hotel_prebook_attempts', document_id, {
            'status': 'failed', 'stage': 'prebook_unpriced',
            'validatedOffer': validated, 'updatedAt': utc_now_iso(),
        })
        return jsonify({'ok': False, 'error': 'The validated hotel price or currency is unavailable; search again.'}), 422
    original = quote.get('offer') or {}
    changes = _material_quote_changes(original, validated)
    version = _quote_version(validated)
    if source != 'local' and changes and payload.get('acceptedQuoteVersion') != version:
        updateRecord('hotel_prebook_attempts', document_id, {
            'status': 'reprice_required',
            'stage': 'prebook_reprice_required',
            'prebookId': validated.get('prebookId'),
            'validatedOffer': validated,
            'validatedQuoteVersion': version,
            'quoteChanges': changes,
            'source': source,
            'updatedAt': utc_now_iso(),
        })
        return jsonify({
            'ok': False,
            'status': 'reprice_required',
            'error': 'The hotel price or terms changed. Review the latest offer before continuing.',
            'changes': changes,
            'validatedOffer': validated,
            'quoteVersion': version,
        }), 409
    patch = {
        'status': 'succeeded',
        'stage': 'prebooked',
        'prebookId': validated.get('prebookId'),
        'validatedOffer': validated,
        'validatedQuoteVersion': version,
        'providerResult': validated,
        'quoteChanges': changes,
        'source': source,
        'isSimulated': source == 'local',
        'updatedAt': utc_now_iso(),
    }
    updateRecord('hotel_prebook_attempts', document_id, patch)
    return jsonify({
        'ok': True,
        'result': validated,
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
        'hotelCurrency': str(booking.get('hotelCurrency') or selected_hotel.get('currency') or '').upper(),
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
        return jsonify({'ok': False, 'error': 'validationId is required'}), 400

    try:
        attempt_id = _booking_attempt_id(payload)
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    validation_id = str(payload.get('validationId') or '')
    prebook_id = str(payload.get('prebookId') or '')
    prebook_document_id = _hotel_operation_id(attempt_id, 'prebook')
    prebook_record = retrieveRecord('hotel_prebook_attempts', prebook_document_id)
    if not prebook_record or prebook_record.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'Validate this hotel offer before booking.'}), 409
    expected_id = validation_id or prebook_id
    stored_id = str(prebook_record.get('validationId') or prebook_record.get('prebookId') or '')
    if prebook_record.get('status') != 'succeeded' or stored_id != expected_id:
        return jsonify({'ok': False, 'error': 'This hotel validation is stale or incomplete; validate the offer again.'}), 409
    selected_hotel, authority_error = _authoritative_offer(prebook_record)
    if authority_error:
        return jsonify({'ok': False, 'error': authority_error}), 409
    hotel_cost = float(selected_hotel['price'])
    document_id = _hotel_operation_id(attempt_id, 'book')
    provider_key = provider_idempotency_key('hotel', g.uid, attempt_id, 'book')
    now = utc_now_iso()
    record = {
        'travellerId': g.uid,
        'hotelBookingAttemptId': attempt_id,
        'validationId': validation_id or None,
        'prebookId': prebook_id or None,
        'quoteId': prebook_record.get('quoteId'),
        'validatedQuoteVersion': prebook_record.get('validatedQuoteVersion'),
        'validatedOffer': selected_hotel,
        'bookingStatus': 'pending',
        'stage': 'booking_pending',
        'providerRequestKey': provider_key,
        'selectedHotel': selected_hotel,
        'roomQuantity': selected_hotel.get('roomQuantity') or prebook_record.get('criteria', {}).get('roomQuantity') or 1,
        'hotelCost': hotel_cost,
        'hotelCurrency': str(selected_hotel.get('currency')).upper(),
        'amountSource': 'validated_offer',
        'itineraryId': str(payload.get('itineraryId') or '').strip(),
        'itineraryAttachmentStatus': 'pending' if payload.get('itineraryId') else 'not_requested',
        'createdAt': now,
        'updatedAt': now,
    }
    claimed, created = claimRecord('hotel_bookings', document_id, record)
    if claimed.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'Booking attempt not found'}), 404
    claimed_id = str(claimed.get('validationId') or claimed.get('prebookId') or '')
    if claimed_id != expected_id:
        return jsonify({'ok': False, 'error': 'hotelBookingAttemptId is already bound to another validation'}), 409
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
    use_demo = _transaction_mode() == 'local_demo'
    try:
        if use_demo:
            result = {
                'bookingId': _simulated_reference(provider_key, 'demo_booking_', 10),
                'status': 'confirmed',
                'isSimulated': True,
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
                    'hotelBookingAttemptId', 'roomQuantity', 'quoteId',
                }
            }
            provider_payload['offerId'] = selected_hotel.get('offerId')
            provider_payload['prebookId'] = prebook_id
            provider_payload['clientReference'] = provider_key
            result = createBookingReference(provider_payload)
    except ProviderMutationBlocked as exc:
        patch = {
            'bookingStatus': 'failed',
            'stage': 'provider_mutation_blocked',
            'failureReason': str(exc),
            'updatedAt': utc_now_iso(),
        }
        updateRecord('hotel_bookings', document_id, patch)
        return jsonify({'ok': False, 'error': str(exc), 'status': 'provider_unavailable'}), 503
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
        if _transaction_mode() != 'local_demo' or not use_demo:
            patch = {
                'bookingStatus': 'failed',
                'stage': 'booking_failed',
                'failureReason': str(exc),
                'updatedAt': utc_now_iso(),
            }
            updateRecord('hotel_bookings', document_id, patch)
            return jsonify({
                'ok': False,
                'error': _safe_provider_error(exc, 'The hotel booking could not be completed right now.'),
                'hotelBookingAttemptId': attempt_id,
            }), 502
        result = {
            'bookingId': _simulated_reference(provider_key, 'TM-DEMO-', 10),
            'hotelConfirmationCode': _simulated_reference(provider_key, 'DEMO-', 8),
            'status': 'confirmed',
            'sandbox': True,
        }
        source = 'local'

    provider_data = result.get('data') if isinstance(result, dict) and isinstance(result.get('data'), dict) else {}
    provider_amount = (
        result.get('amount') or result.get('total') or
        provider_data.get('amount') or provider_data.get('total')
    )
    provider_currency = str(
        result.get('currency') or provider_data.get('currency') or
        selected_hotel.get('currency') or ''
    ).upper()
    try:
        provider_amount_number = float(provider_amount) if provider_amount is not None else None
    except (TypeError, ValueError):
        provider_amount_number = None
    if (provider_amount is not None and provider_amount_number != hotel_cost) or provider_currency != str(selected_hotel.get('currency')).upper():
        patch = {
            'bookingStatus': 'pending',
            'stage': 'booking_material_discrepancy',
            'reconciliationRequired': True,
            'verificationRequired': True,
            'providerResult': _safe_booking_result(result),
            'providerDiscrepancy': {
                'expectedAmount': hotel_cost,
                'providerAmount': provider_amount,
                'expectedCurrency': str(selected_hotel.get('currency')).upper(),
                'providerCurrency': provider_currency,
            },
            'updatedAt': utc_now_iso(),
        }
        pending = updateRecord('hotel_bookings', document_id, patch) or {'id': document_id, **record, **patch}
        return _booking_response(pending, status_code=202)

    patch = {
        'bookingStatus': result.get('status', 'confirmed'),
        'bookingReference': result.get('bookingId') or result.get('id') or result.get('hotelConfirmationCode', ''),
        'providerResult': _safe_booking_result(result) if source != 'local' else None,
        'source': source,
        'bookingMode': 'simulation' if source == 'local' else 'provider',
        'isSimulated': source == 'local',
        'providerMutationCalled': source != 'local',
        'demoDisclosure': 'Demo reservation — no room will be reserved.' if source == 'local' else None,
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
