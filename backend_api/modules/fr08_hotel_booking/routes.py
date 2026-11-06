import os
import hashlib
import json
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify, g
from auth_utils import auth_required
from utils import utc_now_iso
from services.liteapi_service import (
    attachRoomContent,
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
from sequence_contract.validators import validateBookingDetails, validateCarRentalSearchCriteria
from sequence_contract.domain_functions import applyHotelFilter, compareSelectedHotels, calculateBudget
from sequence_contract.firebase_firestore import claimRecord, retrieveRecord, updateRecord

bp = Blueprint('fr08_hotels', __name__, url_prefix='/api/fr8')

_DEFAULT_QUOTE_TTL_SECONDS = 900
_MIN_QUOTE_TTL_SECONDS = 60
_MAX_QUOTE_TTL_SECONDS = 3600


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


def _quote_ttl_seconds(name='HOTEL_QUOTE_TTL_SECONDS'):
    try:
        value = int(os.getenv(name, _DEFAULT_QUOTE_TTL_SECONDS))
    except (TypeError, ValueError):
        value = _DEFAULT_QUOTE_TTL_SECONDS
    return min(_MAX_QUOTE_TTL_SECONDS, max(_MIN_QUOTE_TTL_SECONDS, value))


def _expiry(now=None, name='HOTEL_QUOTE_TTL_SECONDS'):
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (current + timedelta(seconds=_quote_ttl_seconds(name))).isoformat()


def _parse_iso(value):
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _is_expired(record, now=None):
    expires = _parse_iso((record or {}).get('expiresAt'))
    if expires is None:
        return True
    return expires <= (now or datetime.now(timezone.utc))


def _positive_int(value, label):
    if isinstance(value, bool):
        raise ValueError(f'{label} must be a whole number.')
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{label} must be a whole number.')
    if number < 1 or str(value).strip() not in {str(number), f'{number}.0'}:
        raise ValueError(f'{label} must be at least 1.')
    return number


def _child_ages(value, label):
    if value in (None, '', []):
        return []
    if not isinstance(value, list):
        try:
            count = int(value)
        except (TypeError, ValueError):
            count = -1
        if count == 0:
            return []
        raise ValueError(f'{label} requires one age for every child.')
    ages = []
    for raw in value:
        if isinstance(raw, bool):
            raise ValueError(f'{label} must contain whole-number ages.')
        try:
            age = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f'{label} must contain whole-number ages.')
        if age < 0 or str(raw).strip() not in {str(age), f'{age}.0'}:
            raise ValueError(f'{label} must contain non-negative whole-number ages.')
        ages.append(age)
    return ages


def _normalise_occupancies(payload, room_quantity):
    raw = payload.get('occupancies')
    if not raw:
        if room_quantity != 1:
            raise ValueError(
                'Room-by-room occupancy is required for multi-room searches.'
            )
        adults = _positive_int(payload.get('adults', 2), 'Adults')
        children = payload.get('childAges')
        if children is None:
            children = payload.get('children')
        ages = _child_ages(
            children,
            'Children',
        )
        return [{'adults': adults, **({'children': ages} if ages else {})}]
    if not isinstance(raw, list) or len(raw) != room_quantity:
        raise ValueError('Provide exactly one occupancy entry for each room.')

    occupancies = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f'Room {index} occupancy must be an object.')
        adults = _positive_int(item.get('adults'), f'Room {index} adults')
        children = item.get('children')
        if children is None:
            children = item.get('childAges')
        ages = _child_ages(
            children,
            f'Room {index} children',
        )
        occupancies.append({
            'adults': adults,
            **({'children': ages} if ages else {}),
        })

    expected_adults = payload.get('adults')
    if expected_adults not in (None, ''):
        if _positive_int(expected_adults, 'Total adults') != sum(
                room['adults'] for room in occupancies):
            raise ValueError('Total adults do not match the room-by-room occupancy.')
    expected_children = payload.get('children')
    if expected_children not in (None, '', []):
        if isinstance(expected_children, list):
            expected_count = len(_child_ages(expected_children, 'Total children'))
        else:
            try:
                expected_count = int(expected_children)
            except (TypeError, ValueError):
                raise ValueError('Total children must be a whole number.')
            if expected_count < 0:
                raise ValueError('Total children cannot be negative.')
        actual_count = sum(len(room.get('children', [])) for room in occupancies)
        if expected_count != actual_count:
            raise ValueError('Total children do not match the room-by-room occupancy.')
    return occupancies


def _validate_stay_dates(checkin, checkout):
    try:
        start = datetime.strptime(str(checkin), '%Y-%m-%d').date()
        end = datetime.strptime(str(checkout), '%Y-%m-%d').date()
    except (TypeError, ValueError):
        raise ValueError('Check-in and check-out must use YYYY-MM-DD.')
    if end <= start:
        raise ValueError('Check-out must be after check-in.')


def _offer_matches_occupancies(offer, expected):
    actual = offer.get('occupancyBreakdown')
    if not actual:
        offer['occupancyValidationStatus'] = 'provider_not_reported'
        return True
    if len(actual) != len(expected):
        return False
    ordered = sorted(actual, key=lambda item: int(item.get('occupancyNumber') or 0))
    for requested, provided in zip(expected, ordered):
        adults = provided.get('adultCount')
        child_ages = provided.get('childrenAges')
        if adults is not None and int(adults) != requested['adults']:
            return False
        if child_ages is not None and list(child_ages) != requested.get('children', []):
            return False
        if child_ages is None and provided.get('childCount') is not None:
            if int(provided['childCount']) != len(requested.get('children', [])):
                return False
        maximum = provided.get('maxOccupancy')
        if maximum is not None and requested['adults'] + len(
                requested.get('children', [])) > int(maximum):
            return False
    offer['occupancyValidationStatus'] = 'verified'
    return True


def _provider_sandbox(result):
    if not isinstance(result, dict):
        return False
    candidates = [result]
    data = result.get('data')
    if isinstance(data, dict):
        candidates.append(data)
    return any(item.get('sandbox') is True for item in candidates)


def _provenance(source, now=None, provider_sandbox=False):
    now = now or utc_now_iso()
    if source == 'liteapi':
        if provider_sandbox:
            return {
                'contentSource': 'liteapi_provider',
                'rateSource': 'liteapi_sandbox_quote',
                'rateProvenance': 'sandbox_provider_quote',
                'quoteRetrievedAt': now,
                'transactionMode': 'provider_sandbox',
                'demoDisclosure': 'Provider sandbox quote — not live inventory.',
            }
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
    occupancies = deepcopy(req.get('occupancies') or [])
    return {
        'destination': payload.get('destination') or payload.get('aiSearch') or '',
        'placeId': payload.get('placeId'),
        'hotelIds': payload.get('hotelIds'),
        'checkin': payload.get('checkin'),
        'checkout': payload.get('checkout'),
        'adults': sum(room['adults'] for room in occupancies),
        'children': sum(len(room.get('children', [])) for room in occupancies),
        'guestCount': sum(
            room['adults'] + len(room.get('children', []))
            for room in occupancies
        ),
        'roomQuantity': room_quantity,
        'occupancies': occupancies,
        'currency': req.get('currency'),
        'guestNationality': req.get('guestNationality'),
    }


def _persist_quotes(items, criteria, source):
    output = []
    created_at = datetime.now(timezone.utc)
    created_text = created_at.isoformat()
    expires_at = _expiry(created_at)
    for item in items:
        item = dict(item)
        item['checkin'] = criteria.get('checkin')
        item['checkout'] = criteria.get('checkout')
        item['quoteVersion'] = _quote_version(item)
        quote_id = hashlib.sha256(json.dumps({
            'uid': g.uid, 'criteria': criteria, 'offer': item,
            'createdAt': created_text,
        }, sort_keys=True, default=str).encode()).hexdigest()[:32]
        item['quoteId'] = quote_id
        item['quoteExpiresAt'] = expires_at
        record = {
            'quoteId': quote_id,
            'travellerId': g.uid,
            'offer': item,
            'criteria': deepcopy(criteria),
            'source': source,
            'createdAt': created_text,
            'updatedAt': created_text,
            'expiresAt': expires_at,
        }
        claimRecord('hotel_offer_quotes', _quote_document_id(quote_id), record)
        output.append(item)
    return output


def _resolve_quote(payload, offer):
    quote_id = str(payload.get('quoteId') or '').strip()
    if quote_id:
        record = retrieveRecord('hotel_offer_quotes', _quote_document_id(quote_id))
        if not record or record.get('travellerId') != g.uid:
            return None, 'The hotel quote was not found or is not owned by this traveller.', 400
        if _is_expired(record):
            return None, 'This hotel quote has expired. Search again to refresh availability and pricing.', 409
        trusted = dict(record.get('offer') or {})
        if trusted.get('offerId') != offer:
            return None, 'This quote is bound to a different hotel offer.', 409
        return record, None, None
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
            now = datetime.now(timezone.utc)
            return {
                'quoteId': 'test-local-quote', 'travellerId': g.uid,
                'offer': item, 'criteria': {}, 'createdAt': now.isoformat(),
                'expiresAt': _expiry(now),
            }, None, None
    return None, 'quoteId is required; search again before validating this hotel offer.', 400


def _accepted_prebook_snapshot(record, validated, source, now=None):
    current = now
    if current is None:
        current = _parse_iso(record.get('acceptedAt') or record.get('updatedAt') or record.get('createdAt'))
    if current is None:
        current = datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    criteria = deepcopy(record.get('criteria') or {})
    return {
        'id': record['id'],
        'status': 'accepted',
        'travellerId': record['travellerId'],
        'provider': 'liteapi' if source == 'liteapi' else 'local_demo',
        'transactionMode': 'provider_sandbox' if source == 'liteapi' else 'local_demo',
        'supplierBookingStatus': 'not_created',
        'hotelBookingAttemptId': record['hotelBookingAttemptId'],
        'quoteId': record.get('quoteId'),
        'hotelId': validated.get('hotelId'),
        'name': validated.get('name'),
        'hotelName': validated.get('name'),
        'offerId': validated.get('offerId'),
        'roomName': validated.get('roomName'),
        'boardName': validated.get('boardName'),
        'prebookId': validated.get('prebookId'),
        'validationId': validated.get('validationId'),
        'checkin': criteria.get('checkin'),
        'checkout': criteria.get('checkout'),
        'roomQuantity': criteria.get('roomQuantity'),
        'occupancies': deepcopy(criteria.get('occupancies') or []),
        'guestCount': criteria.get('guestCount'),
        'amount': validated.get('price'),
        'currency': str(validated.get('currency') or '').upper(),
        'priceBasis': validated.get('priceBasis'),
        'taxesAndFeesStatus': validated.get('taxesAndFeesStatus'),
        'taxesAndFees': deepcopy(validated.get('taxesAndFees') or []),
        'cancellation': deepcopy(validated.get('cancellation') or {}),
        'acceptedQuoteVersion': _quote_version(validated),
        'originalQuoteExpiresAt': record.get('quoteExpiresAt'),
        'acceptedAt': current.isoformat(),
        'expiresAt': _expiry(current, 'HOTEL_PREBOOK_TTL_SECONDS'),
    }


def _public_accepted_snapshot(snapshot):
    if not snapshot:
        return None
    expired = _is_expired(snapshot)
    return {
        'id': snapshot.get('id'),
        'status': 'expired' if (expired and snapshot.get('status') == 'accepted') else snapshot.get('status'),
        'expiresAt': snapshot.get('expiresAt'),
        'amount': snapshot.get('amount'),
        'currency': snapshot.get('currency'),
        'transactionMode': snapshot.get('transactionMode'),
        'supplierBookingStatus': snapshot.get('supplierBookingStatus'),
        'checkoutEligible': bool(
            not expired and
            snapshot.get('checkin') and snapshot.get('checkout') and
            snapshot.get('occupancies') and snapshot.get('amount') is not None and
            snapshot.get('currency') == 'MYR'
        ),
    }


def _material_quote_changes(original, validated):
    keys = ('price', 'currency', 'taxesAndFeesStatus')
    changes = {
        key: {'before': original.get(key), 'after': validated.get(key)}
        for key in keys if original.get(key) != validated.get(key)
    }
    old_policy = original.get('cancellation') or {}
    new_policy = validated.get('cancellation') or {}
    if (original.get('taxesAndFees') or []) != (validated.get('taxesAndFees') or []):
        changes['taxesAndFees'] = {
            'before': original.get('taxesAndFees') or [],
            'after': validated.get('taxesAndFees') or [],
        }
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
        scope = normalize_destination_scope(q)
        state = scope.get('state') or ''
        state_slug = state.lower().replace(' ', '_') if state else 'malaysia'
        place_id = f'local_{state_slug}'
        return jsonify({
            'ok': True,
            'result': {
                'data': [{
                    'placeId': place_id,
                    'displayName': q,
                    'formattedAddress': scope.get('canonicalName') or 'Malaysia',
                }]
            },
            'source': 'local',
        })


@bp.post('/hotels/search')
@auth_required(['traveller'])
def hotels_search():
    payload = request.get_json(silent=True) or {}
    if not (
        (payload.get('destination') or payload.get('aiSearch') or
         payload.get('placeId') or payload.get('hotelIds')) and
        payload.get('checkin') and payload.get('checkout')
    ):
        return jsonify({'ok': False, 'error': 'Destination, checkin and checkout are required'}), 400
    try:
        room_quantity = _positive_int(payload.get('roomQuantity', 1), 'Rooms')
        _validate_stay_dates(payload.get('checkin'), payload.get('checkout'))
        occupancies = _normalise_occupancies(payload, room_quantity)
    except ValueError as exc:
        return jsonify({
            'ok': False,
            'error': str(exc),
            'status': 'invalid_occupancy',
        }), 400

    try:
        limit = int(payload.get('limit', 50))
        offset = int(payload.get('offset', 0))
        max_rates = int(payload.get('maxRatesPerHotel', 3) or 3)
        if not 1 <= limit <= 100 or not 0 <= offset <= 500 or not 1 <= max_rates <= 10:
            raise ValueError
        hotel_name = payload.get('hotelName', '')
        if not isinstance(hotel_name, str) or len(hotel_name) > 150:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'ok': False, 'error': 'Invalid hotel name or result page.'}), 400

    req = {
        'limit': limit, 'offset': offset,
        'occupancies': occupancies,
        'currency': payload.get('currency') or 'MYR',
        'guestNationality': payload.get('guestNationality', 'MY'),
        'checkin': payload['checkin'],
        'checkout': payload['checkout'],
        'roomMapping': True,
        'maxRatesPerHotel': max_rates,
        'includeHotelData': True,
    }
    if hotel_name.strip():
        req['hotelName'] = hotel_name.strip()
    local_place_id = str(payload.get('placeId') or '').strip()
    resolved_place_scope = ''
    if local_place_id.startswith('local_'):
        slug = local_place_id[6:]
        if slug and slug != 'malaysia':
            resolved_place_scope = slug.replace('_', ' ').title()
    destination = (
        payload.get('destination')
        or payload.get('aiSearch')
        or resolved_place_scope
        or ''
    )

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
        items = [
            item for item in items
            if _offer_matches_occupancies(item, occupancies)
        ]
        source = 'liteapi'
        provenance = _provenance(source, provider_sandbox=_provider_sandbox(result))
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
                    if key != 'rooms' and value not in (None, '', []):
                        item.setdefault(key, value)
                attachRoomContent(item, content)
    except Exception as exc:
        if not _sample_mode():
            return jsonify({'ok': False, 'error': _safe_provider_error(
                exc, 'The hotel offer could not be validated right now.'
            )}), 502
        norm_scope = normalize_destination_scope(destination)
        items, _rejected = filter_candidates(
            LOCAL_HOTEL_ITEMS, norm_scope
        )
        result = {'items': items, 'sandbox': True}
        source = 'local'
        provenance = _provenance(source)

    filters = {
        'refundable': payload.get('refundable'),
        'sort': payload.get('sort'),
    }
    if source == 'local' and hotel_name.strip():
        items = [item for item in items if hotel_name.casefold() in str(item.get('name', '')).casefold()]
    if source == 'local':
        items = items[offset:offset + limit]
    items = applyHotelFilter(items, filters)
    for item in items:
        item.update(provenance)
        item['roomQuantity'] = room_quantity
        if item.get('priceBasis') == 'per_room_night' and item.get('priceStatus') == 'available':
            item['nightlyRoomRate'] = item.get('price')
            nights = (datetime.strptime(payload['checkout'], '%Y-%m-%d') -
                      datetime.strptime(payload['checkin'], '%Y-%m-%d')).days
            item['price'] = round(float(item['price']) * room_quantity * nights, 2)
            item['priceBasis'] = 'stay_total'
        elif item.get('priceBasis') == 'room_total':
            item['nightlyRoomRate'] = None
            # The provider response did not expose an offer-level total. Do
            # not multiply an ambiguous room/rate amount by room count.
            item['priceStatus'] = 'unknown'
            item['price'] = None
    items = _persist_quotes(items, _search_criteria(payload, req, room_quantity), source)
    norm_scope = normalize_destination_scope(destination) if source == 'local' else None
    return jsonify({
        'ok': True,
        'items': items,
        'result': {'items': items},
        'source': source,
        'contentSource': provenance['contentSource'],
        'rateSource': provenance['rateSource'],
        'quoteRetrievedAt': provenance['quoteRetrievedAt'],
        'transactionMode': provenance['transactionMode'],
        'noResults': not items,
        'nextOffset': offset + limit if source == 'liteapi' and offset + limit <= 500 else None,
        'availabilityMessage': 'No matching rates were returned for this search. Try another name, location or stay date.' if not items else None,
        'destination': destination if destination else (payload.get('destination') or payload.get('aiSearch') or ''),
        'destinationScope': norm_scope,
        'sampleContentLimited': source == 'local' and not items,
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
    quote, quote_error, quote_status = _resolve_quote(payload, offer)
    if quote_error:
        return jsonify({
            'ok': False,
            'error': quote_error,
            'status': 'quote_expired' if quote_status == 409 and 'expired' in quote_error else 'quote_invalid',
        }), quote_status
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
        'quoteExpiresAt': quote.get('expiresAt'),
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
    if (claimed.get('quoteId') and quote.get('quoteId') and
            str(claimed.get('quoteId')) != str(quote.get('quoteId'))):
        return jsonify({'ok': False, 'error': 'hotelBookingAttemptId is already bound to another quote'}), 409
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
            snapshot = claimed.get('acceptedPrebookSnapshot')
            if not snapshot:
                historical_now = _parse_iso(
                    claimed.get('acceptedAt') or claimed.get('updatedAt') or claimed.get('createdAt')
                )
                snapshot = _accepted_prebook_snapshot(
                    claimed, claimed.get('validatedOffer') or reused_result,
                    claimed.get('source', 'local'),
                    now=historical_now,
                )
                updateRecord('hotel_prebook_attempts', document_id, {
                    'acceptedPrebookSnapshot': snapshot,
                    'updatedAt': utc_now_iso(),
                })
            return jsonify({
                'ok': True,
                'result': reused_result,
                'hotelBookingAttemptId': attempt_id,
                'source': claimed.get('source', 'local'),
                'acceptedPrebook': _public_accepted_snapshot(snapshot),
                'reused': True,
            })
        if claimed.get('status') == 'reprice_required':
            accepted = str(payload.get('acceptedQuoteVersion') or '')
            if accepted and accepted == claimed.get('validatedQuoteVersion'):
                snapshot = claimed.get('acceptedPrebookSnapshot') or _accepted_prebook_snapshot(
                    claimed, claimed.get('validatedOffer') or {},
                    claimed.get('source', 'liteapi'),
                    now=datetime.now(timezone.utc),
                )
                promoted = updateRecord('hotel_prebook_attempts', document_id, {
                    'status': 'succeeded', 'stage': 'prebooked',
                    'acceptedQuoteVersion': accepted, 'updatedAt': utc_now_iso(),
                    'acceptedAt': snapshot['acceptedAt'],
                    'acceptedPrebookSnapshot': snapshot,
                }) or claimed
                return jsonify({
                    'ok': True,
                    'result': promoted.get('validatedOffer') or {},
                    'hotelBookingAttemptId': attempt_id,
                    'source': promoted.get('source', 'liteapi'),
                    'acceptedQuoteVersion': accepted,
                    'acceptedPrebook': _public_accepted_snapshot(snapshot),
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
        snapshot = _accepted_prebook_snapshot(claimed, validated, source, now=datetime.now(timezone.utc))
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
            'acceptedAt': snapshot['acceptedAt'],
            'acceptedPrebookSnapshot': snapshot,
            'updatedAt': utc_now_iso(),
        }
        updateRecord('hotel_prebook_attempts', document_id, patch)
        return jsonify({
            'ok': True, 'result': validated,
            'hotelBookingAttemptId': attempt_id, 'source': source,
            'acceptedPrebook': _public_accepted_snapshot(snapshot),
        })

    validated = normalizePrebookResult(result, offer)
    # Keep non-sensitive offer presentation fields from the server quote while
    # allowing only normalized provider values to replace price/terms.
    if source != 'local':
        authority = {'price', 'priceStatus', 'priceBasis', 'currency',
                     'currencyStatus', 'cancellation', 'taxesAndFeesStatus',
                     'taxesAndFees'}
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
    snapshot = _accepted_prebook_snapshot(claimed, validated, source, now=datetime.now(timezone.utc))
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
        'acceptedAt': snapshot['acceptedAt'],
        'acceptedPrebookSnapshot': snapshot,
        'updatedAt': utc_now_iso(),
    }
    updateRecord('hotel_prebook_attempts', document_id, patch)
    return jsonify({
        'ok': True,
        'result': validated,
        'hotelBookingAttemptId': attempt_id,
        'source': source,
        'acceptedPrebook': _public_accepted_snapshot(snapshot),
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
    criteria = booking.get('stayCriteria')
    criteria = criteria if isinstance(criteria, dict) else {}
    try:
        checkin = datetime.strptime(str(criteria['checkin'])[:10], '%Y-%m-%d').date()
        checkout = datetime.strptime(str(criteria['checkout'])[:10], '%Y-%m-%d').date()
        trip_start = datetime.strptime(str(current['startDate'])[:10], '%Y-%m-%d').date()
        trip_end = datetime.strptime(str(current['endDate'])[:10], '%Y-%m-%d').date()
    except (KeyError, TypeError, ValueError):
        checkin = checkout = trip_start = trip_end = None
    if not all((checkin, checkout, trip_start, trip_end)):
        if not payload.get('acknowledgeCompatibilityUnverified'):
            patch = {
                'itineraryId': itinerary_id,
                'itineraryAttachmentStatus': 'compatibility_unverified',
                'itineraryAttachmentError': 'This historical booking has no verified stay dates. Confirm before attaching it to this trip.',
                'updatedAt': utc_now_iso(),
            }
            return updateRecord('hotel_bookings', document_id, patch) or {**booking, **patch}, None
        checkin = checkout = trip_start = trip_end = None
    if checkin and checkout and trip_start and trip_end and not (trip_start <= checkin < checkout <= trip_end):
        patch = {
            'itineraryId': itinerary_id,
            'itineraryAttachmentStatus': 'incompatible',
            'itineraryAttachmentError': 'Hotel dates must fall within the trip dates; checkout on the trip end date is allowed.',
            'updatedAt': utc_now_iso(),
        }
        return updateRecord('hotel_bookings', document_id, patch) or {**booking, **patch}, None
    stay_destination = normalize_destination_scope((criteria or {}).get('destination'))
    trip_destination = normalize_destination_scope(current.get('destinationArea'))
    if (stay_destination.get('resolved') and trip_destination.get('resolved') and
            stay_destination.get('state') != trip_destination.get('state')):
        patch = {
            'itineraryId': itinerary_id,
            'itineraryAttachmentStatus': 'incompatible',
            'itineraryAttachmentError': 'The hotel destination does not match this trip destination.',
            'updatedAt': utc_now_iso(),
        }
        return updateRecord('hotel_bookings', document_id, patch) or {**booking, **patch}, None
    if current.get('hotelBookingId') == document_id:
        patch = {
            'itineraryId': itinerary_id,
            'itineraryAttachmentStatus': 'succeeded',
            'updatedAt': utc_now_iso(),
        }
        return updateRecord('hotel_bookings', document_id, patch) or {**booking, **patch}, current
    selected_hotel = booking.get('selectedHotel') or {}
    hotel_cost = float(booking.get('hotelCost') or 0)
    trip_patch = {
        'selectedHotel': selected_hotel,
        'hotelCost': hotel_cost,
        'hotelCurrency': str(booking.get('hotelCurrency') or selected_hotel.get('currency') or '').upper(),
        'hotelBookingId': document_id,
        'accommodationChoice': 'paid_hotel',
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
    accepted_snapshot = prebook_record.get('acceptedPrebookSnapshot')
    if not isinstance(accepted_snapshot, dict) or accepted_snapshot.get('id') != prebook_document_id:
        return jsonify({
            'ok': False,
            'error': 'This hotel validation predates the secure Checkout contract. Search and validate the offer again.',
            'status': 'accepted_prebook_required',
        }), 409
    if _is_expired(accepted_snapshot):
        return jsonify({
            'ok': False,
            'error': 'This accepted hotel price has expired. Search and validate the offer again.',
            'status': 'accepted_prebook_expired',
        }), 409
    selected_hotel, authority_error = _authoritative_offer(prebook_record)
    if authority_error:
        return jsonify({'ok': False, 'error': authority_error}), 409
    try:
        hotel_cost = float(accepted_snapshot.get('amount'))
        selected_cost = float(selected_hotel['price'])
    except (TypeError, ValueError):
        return jsonify({
            'ok': False,
            'error': 'The accepted hotel price is invalid. Search and validate the offer again.',
            'status': 'accepted_prebook_mismatch',
        }), 409
    if (
        hotel_cost != selected_cost or
        str(accepted_snapshot.get('currency') or '').upper() !=
        str(selected_hotel.get('currency') or '').upper() or
        accepted_snapshot.get('offerId') != selected_hotel.get('offerId')
    ):
        return jsonify({
            'ok': False,
            'error': 'The accepted hotel price no longer matches the validated offer. Search again.',
            'status': 'accepted_prebook_mismatch',
        }), 409
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
        'acceptedPrebookSnapshotId': prebook_document_id,
        'acceptedPrebookSnapshot': deepcopy(accepted_snapshot),
        'bookingStatus': 'pending',
        'stage': 'booking_pending',
        'providerRequestKey': provider_key,
        'selectedHotel': selected_hotel,
        'roomQuantity': selected_hotel.get('roomQuantity') or prebook_record.get('criteria', {}).get('roomQuantity') or 1,
        'stayCriteria': dict(prebook_record.get('criteria') or {}),
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
    save_details_only = payload.get('saveDetailsOnly') is True
    use_demo = save_details_only or _transaction_mode() == 'local_demo'
    try:
        if use_demo:
            result = {
                'bookingId': None if save_details_only else _simulated_reference(provider_key, 'demo_booking_', 10),
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
        'confirmationLabel': 'Hotel Details Saved' if save_details_only else ('Simulated confirmation' if source == 'local' else 'Provider confirmation'),
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
        'carRentalChoice': 'selected',
        'updatedAt': utc_now_iso(),
    }
    patch['budgetEstimate'] = calculateBudget({**current, **patch})
    updated = updateRecord('itineraries', itinerary_id, patch)
    return jsonify({'ok': True, 'itinerary': updated, 'selectedCarRental': rental, 'budget': patch['budgetEstimate']})
