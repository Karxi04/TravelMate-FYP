"""Explicit bounded provider discovery. Quotes only: no itinerary or supplier mutation."""
from datetime import datetime, timezone

from services.transaction_reliability import operation_document_id
from sequence_contract.firebase_firestore import claimRecord, updateRecord


class DiscoveryError(ValueError):
    pass


def run_search(owner, trip, kind, state, search, request_id=None):
    """Durable ten-minute deduplication and two searches/category/account/hour."""
    now = datetime.now(timezone.utc)
    bucket = int(now.timestamp()) // 600
    identity = operation_document_id('budget_search', owner, f"{trip['id']}:{state}:{kind}:{bucket}")
    if request_id:
        # Bind a submitted intent to its original cache bucket, even across a clock boundary.
        intent, _ = claimRecord('budget_alternative_search_intents',
            operation_document_id('budget_search_intent', owner, f'{kind}:{request_id}'), {
                'travellerId': owner, 'tripId': trip['id'], 'stateVersion': state,
                'cacheId': identity, 'createdAt': now.isoformat(),
            })
        if intent.get('travellerId') != owner or intent.get('tripId') != trip['id'] or intent.get('stateVersion') != state:
            raise DiscoveryError('This search intent belongs to another trip revision.')
        identity = intent['cacheId']
    record, created = claimRecord('budget_alternative_searches', identity, {
        'travellerId': owner, 'tripId': trip['id'], 'stateVersion': state, 'category': kind,
        'status': 'pending', 'createdAt': now.isoformat(),
    })
    if not created:
        if record.get('travellerId') != owner or record.get('stateVersion') != state:
            raise DiscoveryError('This search does not match the current trip.')
        return {**record.get('result', {}), 'status': record.get('status'), 'reused': True}
    for slot in range(2):
        key = operation_document_id('budget_search_quota', owner, f"{kind}:{now.strftime('%Y%m%d%H')}:{slot}")
        _, reserved = claimRecord('budget_alternative_search_quota', key, {
            'travellerId': owner, 'searchId': identity, 'createdAt': now.isoformat(),
        })
        if reserved:
            break
    else:
        result = {'status': 'quota_limited', 'requestsAttempted': 0}
        updateRecord('budget_alternative_searches', identity, {'status': result['status'], 'result': result})
        return result
    # The service invokes at most two flight requests or one hotel rates request.
    # A failure consumes its reservation; it is never automatically replayed.
    attempted = 0
    def invoke(call, *args, **kwargs):
        nonlocal attempted
        cap = 2 if kind == 'flight' else 1
        if attempted >= cap:
            raise DiscoveryError('The provider request limit was reached.')
        attempted += 1
        return call(*args, **kwargs)
    try:
        references = search(invoke)
        result = {'status': 'completed', 'requestsAttempted': attempted, 'references': references}
    except Exception:
        result = {'status': 'unavailable', 'requestsAttempted': attempted}
    updateRecord('budget_alternative_searches', identity, {'status': result['status'], 'result': result})
    return result


def flight_search(trip, invoke):
    from modules.fr05_smart_itinerary_budget_planner.routes import _flight_cabin
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
    }, 'MYR', traveller_count(trip.get('travellerCount')), _flight_cabin(trip), None)
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
    for offer in normalizeHotelOffers(response)[:20]:
        if offer.get('roomQuantity') not in (None, rooms) or not _offer_matches_occupancies(offer, occupancies):
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
    return [{'hotelOfferQuoteId': row['quoteId'], 'offerId': row['offerId']}
            for row in _persist_quotes(items, criteria, 'liteapi')]
