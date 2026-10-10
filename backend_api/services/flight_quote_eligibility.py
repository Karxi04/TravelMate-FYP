"""Evidence-backed eligibility for the shared flight demo checkout."""
import math
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from services.flight_itinerary_adjustment import fingerprint

PRICE_RULE = 'serpapi_single_adult_one_way_ticket_v1'
PRICE_DOC = 'https://serpapi.com/google-flights-api'
FARE_SCOPE_DOC = 'https://support.google.com/travel/answer/2475306?hl=en'
FEE_DISCLOSURE = 'Displayed air transport price includes VAT/GST and airport taxes. Baggage and other airline or agency fees are not verified and may be additional.'
QUOTE_TTL_SECONDS = 3600


def provider_time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace(' UTC', '+00:00').replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def classify_price(response, params, raw, option):
    """Only a singleton party avoids the undocumented multi-adult price scope."""
    echo = response.get('search_parameters') or {}
    metadata = response.get('search_metadata') or {}
    original = provider_time(metadata.get('created_at'))
    reason = 'The provider price basis has not been established for this quote.'
    eligible = False
    if params.get('return_date') or params.get('departure_token') or params.get('type') != 2:
        reason = 'Round-trip prices are planning references: whether the selected return price includes the outbound is unresolved.'
    elif params.get('adults', 1) != 1:
        reason = 'Multi-adult prices are planning references: per-adult versus whole-party pricing is unresolved.'
    else:
        matched = all(str(echo.get(k)) == str(params.get(k)) for k in ('departure_id', 'arrival_id', 'outbound_date', 'type', 'currency'))
        single = str(echo.get('adults', 1)) == '1' and all(str(echo.get(k, 0)) == '0' for k in ('children', 'infants_in_seat', 'infants_on_lap'))
        try:
            amount = float(raw.get('price'))
            positive = not isinstance(raw.get('price'), bool) and math.isfinite(amount) and amount > 0
        except (TypeError, ValueError):
            positive = False
        eligible = bool(matched and single and positive and raw.get('type') == 'One way'
                        and not echo.get('return_date') and metadata.get('status') == 'Success'
                        and metadata.get('id') and original
                        and str(raw.get('currency') or echo.get('currency') or '').upper() == str(params.get('currency')).upper())
    if eligible and not (datetime.now(timezone.utc) - timedelta(seconds=QUOTE_TTL_SECONDS) < datetime.fromisoformat(original) <= datetime.now(timezone.utc)):
        eligible = False
        reason = 'The original provider quote is stale. Search again before Checkout.'
    option.update({
        'checkoutEligible': eligible, 'budgetEligible': eligible,
        'checkoutBlockReason': None if eligible else reason,
        'priceSemanticsStatus': 'verified_single_adult_one_way' if eligible else 'unverified',
        'passengerPriceBasis': 'single_adult_equals_whole_party' if eligible else 'unverified',
        'priceBasis': 'single_adult_whole_one_way_itinerary' if eligible else 'provider_price_reference_unverified',
        'originalRetrievedAt': original, 'retrievalTimeStatus': 'provider_original' if original else 'unavailable',
    })
    option['priceEvidence'] = {
        'rule': PRICE_RULE, 'documentation': PRICE_DOC, 'fareScopeDocumentation': FARE_SCOPE_DOC,
        'providerSearchId': metadata.get('id'), 'originalRetrievedAt': original,
        'providerType': raw.get('type'), 'request': {k: params.get(k) for k in ('departure_id', 'arrival_id', 'outbound_date', 'type', 'currency', 'adults')},
        'amount': option.get('price'), 'currency': option.get('currency'),
        'passengers': {'adults': 1, 'children': 0, 'infants_in_seat': 0, 'infants_on_lap': 0},
    } if eligible else None
    return option


def validate_segments(criteria, outbound, returns, detailed=True):
    def leg(segments, origin, destination, departure_date):
        if not isinstance(segments, list) or not segments or any(not isinstance(s, dict) for s in segments):
            raise ValueError('Flight segments are incomplete.')
        if segments[0].get('departureAirportCode') != origin or segments[-1].get('arrivalAirportCode') != destination or segments[0].get('departureDate') != departure_date:
            raise ValueError('Flight route or date does not match the owned search.')
        for index, segment in enumerate(segments):
            if index and segments[index - 1].get('arrivalAirportCode') != segment.get('departureAirportCode'):
                raise ValueError('Flight connections are incompatible.')
            if detailed:
                for prefix in ('departure', 'arrival'):
                    if not re.fullmatch(r'[A-Z]{3}', str(segment.get(prefix + 'AirportCode') or '')):
                        raise ValueError('Flight airport information is incomplete.')
                    try:
                        datetime.strptime(str(segment.get(prefix + 'Date')) + ' ' + str(segment.get(prefix + 'Time')), '%Y-%m-%d %H:%M')
                    except ValueError:
                        raise ValueError('Flight dates and times are incomplete.')
                if not segment.get('flightNumber') or not segment.get('airline'):
                    raise ValueError('Flight number or airline is incomplete.')
        return segments
    leg(outbound, criteria.get('departure_id'), criteria.get('arrival_id'), criteria.get('outbound_date'))
    if criteria.get('return_date'):
        leg(returns, criteria.get('arrival_id'), criteria.get('departure_id'), criteria.get('return_date'))
    elif returns:
        raise ValueError('A one-way quote cannot contain return segments.')


def flight_review(record, option_id):
    criteria = record.get('criteria') or {}
    option = next((x for x in record.get('items', []) if isinstance(x, dict) and x.get('optionId') == option_id), None)
    if not option or record.get('source') != 'serpapi':
        raise ValueError('A server-owned provider flight quote is required.')
    now = datetime.now(timezone.utc)
    original = provider_time(record.get('retrievedAt'))
    expires = provider_time(record.get('expiresAt'))
    if not original or not expires or not (now - timedelta(seconds=QUOTE_TTL_SECONDS) < datetime.fromisoformat(original) <= now) or datetime.fromisoformat(expires) <= now:
        raise ValueError('This flight quote is stale. Search again and reconfirm the new quote.')
    if option.get('quoteCompleteness') != 'complete' or (criteria.get('return_date') and not option.get('roundTripComplete')):
        raise ValueError('A complete compatible return selection is required.')
    validate_segments(criteria, option.get('outboundSegments'), option.get('returnSegments') or [])
    if criteria.get('return_date'):
        raise ValueError('Round-trip Checkout is blocked: combined outbound/return price scope is unresolved.')
    if criteria.get('traveller_count') != 1:
        raise ValueError('Multi-adult Checkout is blocked: per-adult versus whole-party price scope is unresolved.')
    try:
        future = datetime.strptime(str(criteria.get('outbound_date')), '%Y-%m-%d').date() > now.date()
    except ValueError:
        future = False
    if not future:
        raise ValueError('Flight demo Checkout requires a future departure date; same-day timezone resolution is unsupported.')
    if criteria.get('currency') != 'MYR' or option.get('currency') != 'MYR':
        raise ValueError('Only a validated MYR flight quote is supported.')
    evidence = option.get('priceEvidence') or {}
    expected_request = {'departure_id': criteria.get('departure_id'), 'arrival_id': criteria.get('arrival_id'), 'outbound_date': criteria.get('outbound_date'), 'type': 2, 'currency': 'MYR', 'adults': 1}
    if not option.get('checkoutEligible') or evidence.get('rule') != PRICE_RULE or evidence.get('documentation') != PRICE_DOC or evidence.get('fareScopeDocumentation') != FARE_SCOPE_DOC or evidence.get('request') != expected_request or evidence.get('providerType') != 'One way' or not evidence.get('providerSearchId') or evidence.get('providerSearchId') != record.get('providerSearchId'):
        raise ValueError('This flight quote has no supported provider price evidence.')
    passengers = evidence.get('passengers')
    composition = option.get('passengerComposition') or {}
    if passengers != {'adults': 1, 'children': 0, 'infants_in_seat': 0, 'infants_on_lap': 0} or option.get('travellerCount') != 1 or composition.get('adults') != 1 or any(composition.get(k, 0) != 0 or criteria.get(k, 0) != 0 for k in ('children', 'infants_in_seat', 'infants_on_lap')):
        raise ValueError('Only one adult with no children or infants is supported for flight Checkout.')
    amount = option.get('price')
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount <= 0 or evidence.get('amount') != amount or evidence.get('currency') != 'MYR' or evidence.get('originalRetrievedAt') != original or option.get('originalRetrievedAt') != original:
        raise ValueError('Flight price or original retrieval evidence does not match the quote.')
    snapshot = {
        'quoteId': record['id'], 'optionId': option_id, 'quoteVersion': record.get('quoteVersion'),
        'tripType': 'one_way', 'outboundDate': criteria['outbound_date'], 'returnDate': None,
        'outboundSegments': deepcopy(option['outboundSegments']), 'returnSegments': [],
        'travellerCount': 1, 'passengerComposition': {'adults': 1, 'children': 0, 'infants': 0},
        'price': amount, 'currency': 'MYR', 'priceBasis': 'single_adult_whole_one_way_itinerary',
        'retrievedAt': original, 'expiresAt': expires, 'timezoneStatus': 'local_time_only',
        'priceEvidence': deepcopy(evidence), 'feeDisclosure': FEE_DISCLOSURE, 'demoOrder': True, 'flightBooked': False,
    }
    return {'snapshot': snapshot, 'fingerprint': fingerprint(snapshot)}
