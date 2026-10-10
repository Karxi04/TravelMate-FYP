from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib, hmac, json, time
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from services.serpapi_service import retrieveFlightOptions, normalizeFlightResult
from services.flight_quote_eligibility import flight_review
from sequence_contract.domain_functions import calculateBudget
from test_fr08_fr09_hotels_payments import MemoryPersistence
from test_p1_checkout import _patch_persistence
HEADERS = {'Authorization': 'Bearer test-token'}


def quote(adults=1, round_trip=False):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    day = (now + timedelta(days=20)).date().isoformat()
    back = (now + timedelta(days=22)).date().isoformat() if round_trip else None
    def leg(number, origin, dest, date):
        return {'airline': 'Fixture Air', 'flight_number': number, 'departure_airport': {'id': origin, 'time': date+' 10:00'}, 'arrival_airport': {'id': dest, 'time': date+' 11:00'}, 'duration': 60}
    raw = {'flights': [leg('FX1', 'KUL', 'PEN', day)], 'price': 120, 'type': 'Round trip' if round_trip else 'One way'}
    if back: raw['return_flights'] = [leg('FX2', 'PEN', 'KUL', back)]
    echo = {'departure_id': 'KUL', 'arrival_id': 'PEN', 'outbound_date': day, 'type': 1 if back else 2, 'currency': 'MYR', 'adults': adults}
    if back: echo['return_date'] = back
    response = {'search_parameters': echo, 'search_metadata': {'id': 'provider_fixture', 'status': 'Success', 'created_at': now.strftime('%Y-%m-%d %H:%M:%S UTC')}, 'best_flights': [raw]}
    with patch('services.serpapi_service._request', return_value=response):
        option = retrieveFlightOptions('KUL', 'PEN', day, back, adults=adults)['items'][0]
    option.update({'optionId': 'option_f3', 'quoteCompleteness': 'complete', 'roundTripComplete': bool(back)})
    return {'id': 'search_f3', 'travellerId': 'test_traveller_uid', 'source': 'serpapi', 'criteria': {'departure_id': 'KUL', 'arrival_id': 'PEN', 'outbound_date': day, 'return_date': back, 'currency': 'MYR', 'traveller_count': adults}, 'providerSearchId': 'provider_fixture', 'retrievedAt': now.isoformat(), 'expiresAt': (now+timedelta(hours=1)).isoformat(), 'quoteVersion': 1, 'items': [option]}


def payload(record, **changes):
    return {'quoteType': 'flight', 'searchId': record['id'], 'optionId': 'option_f3', 'orderAttemptId': 'order_attempt_f3', 'confirmedFlightQuote': True, 'flightQuoteFingerprint': flight_review(record, 'option_f3')['fingerprint'], **changes}


def test_single_adult_and_multisegment_price_are_counted_once():
    record = quote(); segments = record['items'][0]['outboundSegments']; second = deepcopy(segments[0])
    segments[0]['arrivalAirportCode'] = 'BKK'; second.update({'departureAirportCode': 'BKK', 'flightNumber': 'FX2', 'departureTime': '12:00', 'arrivalTime': '13:00'}); segments.append(second)
    review = flight_review(record, 'option_f3')
    assert review['snapshot']['price'] == 120 and review['snapshot']['travellerCount'] == 1
    budget = calculateBudget({'travellerCount': 1, 'flightCost': 120, 'flightCurrency': 'MYR', 'selectedFlight': record['items'][0], 'hotelCost': 50, 'hotelCurrency': 'MYR', 'activities': [{'estimatedCost': 10}], 'transportCost': 0, 'foodCost': 0})
    assert budget['flight'] == 120 and budget['total'] == 180


@pytest.mark.parametrize('adults,round_trip,reason', [(2,False,'Multi-adult'), (1,True,'Round-trip'), (2,True,'Round-trip')])
def test_unsupported_party_and_combined_scope_stay_blocked(adults, round_trip, reason):
    record = quote(adults, round_trip); option = record['items'][0]
    assert option['checkoutEligible'] is False
    with pytest.raises(ValueError, match=reason): flight_review(record, 'option_f3')
    assert calculateBudget({'flightCost': option['price'], 'flightCurrency': 'MYR', 'selectedFlight': option})['flight'] == 0


def test_complete_round_trip_needs_compatible_returns_and_supported_price():
    record = quote(round_trip=True); record['items'][0]['returnSegments'][0]['departureAirportCode'] = 'SIN'
    with pytest.raises(ValueError, match='route or date'): flight_review(record,'option_f3')
    record['items'][0]['quoteCompleteness'] = 'return_selection_pending'
    with pytest.raises(ValueError, match='complete compatible'): flight_review(record,'option_f3')


@pytest.mark.parametrize('change,reason', [('amount','does not match'),('currency','MYR'),('time','stale'),('proof','evidence'),('segment','incomplete')])
def test_bad_owned_quotes_are_rejected(change,reason):
    record = quote(); option = record['items'][0]
    if change=='amount': option['price']=121
    elif change=='currency': option['currency']='USD'
    elif change=='time': record['retrievedAt']=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
    elif change=='proof': option['priceEvidence']=None
    elif change=='segment': option['outboundSegments'][0]['arrivalTime']=None
    with pytest.raises(ValueError,match=reason): flight_review(record,'option_f3')


def test_request_counts_and_local_labels_are_not_semantic_evidence():
    option=normalizeFlightResult({'price':800,'price_basis':'provider_round_trip_verified','currency':'MYR'},traveller_count=2)
    assert option['priceSemanticsStatus']=='unverified' and not option.get('priceEvidence')


@pytest.mark.parametrize('tamper',[{'amount':1},{'currency':'USD'},{'travellerCount':2},{'outboundSegments':[]},{'confirmedFlightQuote':False},{'flightQuoteFingerprint':'old'}])
def test_tampered_payload_and_unconfirmed_changes_cannot_checkout(client,mock_traveller_auth,tamper):
    record=quote(); memory=MemoryPersistence(); memory.seed('flight_quotes','test_traveller_uid_search_f3',record)
    with _patch_persistence(memory)[1],patch('modules.fr09_payment.routes.createCheckoutSession') as create:
        response=client.post('/api/fr9/checkout/session',headers=HEADERS,json=payload(record,**tamper))
    assert response.status_code==409; create.assert_not_called()


def test_foreign_quote_and_trip_cannot_checkout(client,mock_traveller_auth):
    record=quote();record['travellerId']='other';memory=MemoryPersistence();memory.seed('flight_quotes','test_traveller_uid_search_f3',record)
    with _patch_persistence(memory)[1]:
        response=client.post('/api/fr9/checkout/flight-review',headers=HEADERS,json={'searchId':'search_f3','optionId':'option_f3'})
    assert response.status_code==409
    record['travellerId']='test_traveller_uid';memory.seed('flight_quotes','test_traveller_uid_search_f3',record);memory.seed('itineraries','foreign',{'travellerId':'other'})
    with _patch_persistence(memory)[1]:
        response=client.post('/api/fr9/checkout/session',headers=HEADERS,json=payload(record,itineraryId='foreign'))
    assert response.status_code==409


def test_shared_snapshot_is_immutable_and_material_changes_reconfirm(client,mock_traveller_auth):
    record=quote();memory=MemoryPersistence();memory.seed('flight_quotes','test_traveller_uid_search_f3',record);original=payload(record)
    session=SimpleNamespace(id='cs_f3_fixture',url='https://checkout.stripe.test/f3')
    with _patch_persistence(memory)[0],_patch_persistence(memory)[1],_patch_persistence(memory)[2],patch('modules.fr09_payment.routes.createCheckoutSession',return_value=session) as create:
        response=client.post('/api/fr9/checkout/session',headers=HEADERS,json=original);assert response.status_code==200
        order=response.get_json()['order'];snapshot=deepcopy(order['quoteSnapshot']);assert order['amount']==120 and order['demoOrder'] and not order['flightBooked']
        assert 'demo order' in create.call_args.kwargs['product_name']
        record['items'][0]['price']=150;record['items'][0]['priceEvidence']['amount']=150;memory.seed('flight_quotes','test_traveller_uid_search_f3',record)
        changed=client.post('/api/fr9/checkout/session',headers=HEADERS,json=original);assert changed.status_code==409
        review=client.post('/api/fr9/checkout/flight-review',headers=HEADERS,json={'searchId':'search_f3','optionId':'option_f3'})
        assert review.get_json()['fingerprint']!=original['flightQuoteFingerprint']
        bound=client.post('/api/fr9/checkout/session',headers=HEADERS,json=payload(record));assert bound.status_code==409
        assert create.call_count==1 and memory.retrieve('checkout_orders',order['id'])['quoteSnapshot']==snapshot
        memory.update('checkout_orders',order['id'],{'status':'paid','paymentStatus':'paid'})
        assert client.post('/api/fr9/checkout/session',headers=HEADERS,json=payload(record)).status_code==409


def test_removing_trip_flight_preserves_paid_history_hotel_and_manual_activities(client,mock_traveller_auth):
    memory=MemoryPersistence();record=quote();trip={'travellerId':'test_traveller_uid','selectedFlight':record['items'][0],'flightCost':120,'flightCurrency':'MYR','flightPriceBasis':'single_adult_whole_one_way_itinerary','selectedHotel':{'name':'Keep hotel'},'hotelCost':90,'hotelCurrency':'MYR','activities':[{'activityId':'manual','estimatedCost':20}],'travellerCount':1}
    memory.seed('itineraries','trip_f3',trip);memory.seed('checkout_orders','paid_f3',{'travellerId':'test_traveller_uid','status':'paid','quoteSnapshot':flight_review(record,'option_f3')['snapshot']});before=deepcopy(memory.retrieve('checkout_orders','paid_f3'))
    with patch('modules.fr07_flight_search.routes.retrieveRecord',side_effect=memory.retrieve),patch('modules.fr07_flight_search.routes.updateRecord',side_effect=memory.update),_patch_persistence(memory)[1]:
        removed=client.post('/api/fr7/itineraries/trip_f3/flight-selection/remove',headers=HEADERS);assert removed.status_code==200
        result=removed.get_json()['itinerary'];assert result['selectedHotel']==trip['selectedHotel'] and result['activities']==trip['activities'] and result['budgetEstimate']['flight']==0
        assert len(client.get('/api/fr9/orders',headers=HEADERS).get_json()['items'])==1
    assert memory.retrieve('checkout_orders','paid_f3')==before


def test_signed_webhook_receipt_preserves_paid_flight_snapshot(client):
    memory=MemoryPersistence();snapshot=flight_review(quote(),'option_f3')['snapshot'];memory.seed('checkout_orders','order_f3',{'quoteType':'flight','status':'paid','paymentStatus':'paid','amount':120,'currency':'MYR','checkoutSessionId':'cs_f3','quoteSnapshot':snapshot})
    event={'id':'evt_f3','type':'checkout.session.completed','data':{'object':{'id':'cs_f3','metadata':{'orderId':'order_f3'},'amount_total':12000,'currency':'myr','payment_status':'paid','status':'complete'}}};body=json.dumps(event).encode();timestamp=str(int(time.time()));secret='whsec_f3_fixture';signature=hmac.new(secret.encode(),timestamp.encode()+b'.'+body,hashlib.sha256).hexdigest()
    with patch.dict('os.environ',{'STRIPE_WEBHOOK_SECRET':secret}),_patch_persistence(memory)[1],_patch_persistence(memory)[2]:
        response=client.post('/api/fr9/webhooks/stripe',data=body,headers={'Stripe-Signature':f't={timestamp},v1={signature}'})
    assert response.status_code==200;saved=memory.retrieve('checkout_orders','order_f3');assert saved['paymentVerification']['eventId']=='evt_f3' and saved['quoteSnapshot']==snapshot and saved['status']=='paid'


def test_original_provider_time_is_preserved_in_quote_storage(client, mock_traveller_auth):
    from modules.fr07_flight_search import routes
    record = quote(); original = (datetime.now(timezone.utc) - timedelta(minutes=20)).replace(microsecond=0)
    result = {'items': record['items'], 'search_metadata': {'id': 'provider_fixture', 'created_at': original.strftime('%Y-%m-%d %H:%M:%S UTC')}}
    with patch('modules.fr07_flight_search.routes.retrieveFlightOptions', return_value=result):
        response = client.get('/api/fr7/flights/search', headers=HEADERS, query_string={'departure_id': 'KUL', 'arrival_id': 'PEN', 'outbound_date': record['criteria']['outbound_date']})
    assert response.status_code == 200
    data = response.get_json(); stored = routes._FLIGHT_QUOTES[data['searchId']]
    assert stored['retrievedAt'] == original.isoformat() == data['retrievedAt']
    assert datetime.fromisoformat(stored['expiresAt']) == original + timedelta(hours=1)


def test_child_configuration_is_rejected_without_provider_request(client, mock_traveller_auth):
    with patch('modules.fr07_flight_search.routes.retrieveFlightOptions') as provider:
        response = client.get('/api/fr7/flights/search?departure_id=KUL&arrival_id=PEN&outbound_date=2027-01-01&children=1', headers=HEADERS)
    assert response.status_code == 400
    provider.assert_not_called()


def test_party_provenance_cannot_be_tampered():
    record = quote(); record['items'][0]['passengerComposition']['children'] = 1
    with pytest.raises(ValueError, match='no children or infants'):
        flight_review(record, 'option_f3')


def test_missing_stripe_amount_or_currency_cannot_verify_flight_payment():
    from modules.fr09_payment.routes import _apply_checkout_session
    record = {'quoteType': 'flight', 'status': 'checkout_open', 'amount': 120, 'currency': 'MYR'}
    for session in [{'status': 'complete', 'payment_status': 'paid', 'currency': 'myr'}, {'status': 'complete', 'payment_status': 'paid', 'amount_total': 12000}]:
        assert _apply_checkout_session(record, session)['status'] == 'payment_mismatch'
