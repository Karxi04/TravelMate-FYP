"""Explicit bounded provider discovery. Quotes only: no itinerary or supplier mutation."""
from datetime import datetime, timezone, timedelta
import os
import logging

from services.transaction_reliability import operation_document_id
from sequence_contract.firebase_firestore import claimRecord, updateRecord


class DiscoveryError(ValueError):
    pass


class _SearchLimitReached(Exception):
    pass


def searches_per_hour():
    try:
        return max(1, min(6, int(os.getenv('BUDGET_ALTERNATIVE_SEARCHES_PER_HOUR', '6'))))
    except ValueError:
        return 6


def run_search(owner, trip, kind, state, search, request_id=None, comparison=None):
    """Durable deduplication; count submitted provider searches, not page visits or validation failures."""
    now = datetime.now(timezone.utc)
    bucket = int(now.timestamp()) // 600
    variant = f":{comparison['mode']}:{comparison['comparisonCabin']}" if comparison else ''
    identity = operation_document_id('budget_search', owner, f"v2:{trip['id']}:{state}:{kind}{variant}:{bucket}")
    if request_id:
        # Bind a submitted intent to its original cache bucket, even across a clock boundary.
        intent, _ = claimRecord('budget_alternative_search_intents',
            operation_document_id('budget_search_intent', owner, f'{kind}:{request_id}'), {
                'travellerId': owner, 'tripId': trip['id'], 'stateVersion': state,
                'comparison': comparison,
                'cacheId': identity, 'createdAt': now.isoformat(),
            })
        if (intent.get('travellerId') != owner or intent.get('tripId') != trip['id'] or intent.get('stateVersion') != state
                or intent.get('comparison') != comparison):
            raise DiscoveryError('This search intent belongs to another trip revision.')
        identity = intent['cacheId']
    record, created = claimRecord('budget_alternative_searches', identity, {
        'travellerId': owner, 'tripId': trip['id'], 'stateVersion': state, 'category': kind,
        'status': 'pending', 'createdAt': now.isoformat(),
    })
    if not created:
        if record.get('travellerId') != owner or record.get('stateVersion') != state:
            raise DiscoveryError('This search does not match the current trip.')
        result = {**record.get('result', {}), 'status': record.get('status'), 'reused': True}
        if result['status'] == 'quota_limited' and result.get('retryAt'):
            retry_at = datetime.fromisoformat(result['retryAt'].replace('Z', '+00:00'))
            if now >= retry_at:
                return {**result, 'status': 'retry_available'}
        return result
    reserved = False
    limit = searches_per_hour()
    retry_at = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).isoformat()
    attempted = 0
    def invoke(call, *args, **kwargs):
        nonlocal attempted, reserved
        cap = 2 if kind == 'flight' else 1
        if attempted >= cap:
            raise DiscoveryError('The provider request limit was reached.')
        if not reserved:
            # Reserve only at the first actual provider boundary. Legacy slot IDs
            # remain valid, so rollout does not reset earlier account usage.
            for slot in range(limit):
                key = operation_document_id('budget_search_quota', owner, f"{kind}:{now.strftime('%Y%m%d%H')}:{slot}")
                _, reserved = claimRecord('budget_alternative_search_quota', key, {
                    'travellerId': owner, 'searchId': identity, 'createdAt': now.isoformat(),
                })
                if reserved:
                    break
            if not reserved:
                raise _SearchLimitReached
        attempted += 1
        return call(*args, **kwargs)
    try:
        found = search(invoke)
        result = {'status': 'completed', 'requestsAttempted': attempted,
                  **(found if isinstance(found, dict) else {'references': found})}
    except _SearchLimitReached:
        result = {'status': 'quota_limited', 'requestsAttempted': 0, 'retryAt': retry_at, 'searchesPerHour': limit}
    except Exception as error:
        # Submitted requests can consume provider credits even on timeout; keep
        # their reservation. Pre-provider validation failures reserve nothing.
        from requests.exceptions import Timeout
        status = getattr(getattr(error, 'response', None), 'status_code', None)
        failure = ('provider_timeout' if isinstance(error, (Timeout, TimeoutError)) else
                   'provider_rate_limited' if status == 429 else
                   'provider_unavailable' if status in (502, 503, 504) else 'provider_error')
        result = {'status': 'unavailable' if attempted else 'needs_review', 'requestsAttempted': attempted,
                  'failureCode': failure if attempted else 'search_not_started'}
        logging.getLogger(__name__).warning('budget_discovery_unavailable category=%s attempts=%s', kind, attempted)
    result.update(providerReached=attempted > 0,comparison=comparison)
    updateRecord('budget_alternative_searches', identity, {'status': result['status'], 'result': result})
    return result


def flight_comparison(trip, mode='same_cabin', target=None):
    """Only server-established cabin evidence defines a permitted downgrade."""
    from modules.fr05_smart_itinerary_budget_planner.routes import _flight_cabin
    original=_flight_cabin(trip)
    if original not in {1,2,3,4} or not isinstance(mode,str) or mode not in {'same_cabin','include_lower'}:
        raise DiscoveryError('Choose a supported cabin comparison for a verified selected flight.')
    allowed=list(range(1,original+1)) if mode=='include_lower' else [original]
    target=(1 if mode=='include_lower' else original) if target is None else target
    if type(target) is not int or target not in allowed:
        raise DiscoveryError('The comparison cabin must retain the original cabin or be an explicitly selected lower cabin.')
    return {'mode':mode,'originalCabin':original,'comparisonCabin':target,'allowedCabins':allowed,
            'cabinDowngrade':target < original}


def flight_search(trip, invoke, comparison=None):
    from modules.fr07_flight_search.routes import (
        _criteria, _provider_route_matches, _store_quote, _FLIGHT_QUOTES,
        _return_segments, _completed_option, _persist_quote,
    )
    from sequence_contract.validators import flightSearchValidationError
    from services.serpapi_service import retrieveFlightOptions, retrieveFlightReturns
    from services.activity_pricing import traveller_count
    selected = trip.get('selectedFlight') or {}
    outbound = selected.get('outboundSegments') or []
    returns = selected.get('returnSegments') or []
    if not outbound:
        raise DiscoveryError('A comparable selected flight is needed.')
    criteria = _criteria({
        'departure_id': outbound[0].get('departureAirportCode'),
        'arrival_id': outbound[-1].get('arrivalAirportCode'),
        'outbound_date': outbound[0].get('departureDate'),
        'return_date': returns[0].get('departureDate') if returns else None,
    }, 'MYR', traveller_count(trip.get('travellerCount')),
       (comparison or flight_comparison(trip))['comparisonCabin'], None)
    if flightSearchValidationError(criteria) or criteria.get('travel_class') not in {1, 2, 3, 4}:
        raise DiscoveryError('The route, dates or cabin need review.')
    args = (criteria['departure_id'], criteria['arrival_id'], criteria['outbound_date'], criteria.get('return_date'))
    result = invoke(retrieveFlightOptions, *args, currency='MYR',
                    travelClass=criteria['travel_class'], adults=criteria['traveller_count'])
    items = [{**row, 'source': 'serpapi', 'planningOnly': True} for row in result.get('items', [])
             if isinstance(row, dict) and _provider_route_matches(row, criteria)][:5]
    if not items:
        return []
    identity, stored = _store_quote(criteria, items, 'serpapi')
    quote = _FLIGHT_QUOTES[identity]
    if criteria.get('return_date'):
        # Complete only one outbound branch, bounded to one extra provider request.
        for option in stored:
            if _return_segments(option, criteria):
                _completed_option(quote, option, option)
        if not quote['completedOptions']:
            outbound = next((row for row in stored if row.get('departureToken')), None)
            if outbound:
                returned = invoke(retrieveFlightReturns, outbound['departureToken'], *args,
                                  adults=criteria['traveller_count'], travelClass=criteria['travel_class'])
                for index, row in enumerate(returned.get('items', [])[:8]):
                    segments = _return_segments(row, criteria)
                    if segments:
                        _completed_option(quote, outbound, {**row, 'optionId': f'return_{index}', 'returnSegments': segments})
        _persist_quote(quote)
        options = quote['completedOptions'].values()
    else:
        options = stored
    return [{'searchId': identity, 'optionId': row['optionId']} for row in options
            if row.get('quoteCompleteness') == 'complete']


def hotel_search(criteria, invoke):
    from modules.fr08_hotel_booking.routes import (
        _validate_stay_dates, _normalise_occupancies, _offer_matches_occupancies,
        _persist_quotes, _provenance, _provider_sandbox,
    )
    from services.liteapi_service import retrieveHotelOffers, normalizeHotelOffers
    _validate_stay_dates(criteria['checkin'], criteria['checkout'])
    rooms = criteria['roomQuantity']
    occupancies = _normalise_occupancies(criteria, rooms)
    req = {'aiSearch': criteria['destination'], 'checkin': criteria['checkin'], 'checkout': criteria['checkout'],
           'occupancies': occupancies, 'currency': 'MYR', 'guestNationality': criteria.get('guestNationality') or 'MY',
           'limit': 10, 'offset': 0, 'maxRatesPerHotel': 2, 'includeHotelData': True, 'roomMapping': True}
    response = invoke(retrieveHotelOffers, req)
    items = []
    rejected = {}
    rates=normalizeHotelOffers(response)[:20]
    for offer in rates:
        if offer.get('roomQuantity') not in (None, rooms) or not _offer_matches_occupancies(offer, occupancies):
            rejected['occupancy_or_rooms']=rejected.get('occupancy_or_rooms',0)+1
            continue
        offer = {**offer, **_provenance('liteapi', provider_sandbox=_provider_sandbox(response)), 'roomQuantity': rooms}
        if offer.get('priceBasis') == 'per_room_night' and offer.get('priceStatus') == 'available':
            from datetime import date
            nights = (date.fromisoformat(criteria['checkout']) - date.fromisoformat(criteria['checkin'])).days
            offer['nightlyRoomRate'] = offer['price']
            offer['price'] = round(float(offer['price']) * rooms * nights, 2)
            offer['priceBasis'] = 'stay_total'
        if (offer.get('priceBasis') == 'stay_total' and offer.get('taxesAndFeesStatus') == 'included'
                and offer.get('currency') == 'MYR' and offer.get('priceStatus') == 'available'):
            items.append(offer)
        else:
            reason=('currency' if offer.get('currency')!='MYR' else 'incomplete_price_or_charges')
            rejected[reason]=rejected.get(reason,0)+1
    return {'references':[{'hotelOfferQuoteId': row['quoteId'], 'offerId': row['offerId']}
            for row in _persist_quotes(items, criteria, 'liteapi')],
            'candidateCount':len(rates),'validQuoteCount':len(items),'rejectedCount':sum(rejected.values()),
            'rejectionCounts':rejected}
