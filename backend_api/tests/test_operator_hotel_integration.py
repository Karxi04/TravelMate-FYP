from contextlib import ExitStack, contextmanager
from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest
import requests

from services import operator_hotel_service as hotels
from services.package_checkout_contract import prepare_package_snapshot
from services.package_service import normalise_package
from services.public_content_projection import public_package
from services.review_service import ReviewConflict
from test_fr12_operator import operator_auth_status

AUTH = {'Authorization': 'Bearer synthetic'}
SEARCH = '/api/fr12/hotels/search?countryCode=MY&cityName=George%20Town'
DETAIL = '/api/fr12/hotels/lp_synthetic'


def raw_hotel(**changes):
    return {'id': 'lp_synthetic', 'name': 'Synthetic Heritage Hotel', 'address': 'Synthetic Street',
            'city_name': 'George Town', 'country_code': 'MY', 'stars': 4, 'rating': 8.7,
            'main_photo': 'https://images.example.test/hotel.jpg',
            'hotelImages': [{'url': 'https://images.example.test/room.jpg'}],
            'hotelFacilities': ['Wi-Fi', {'name': 'Pool'}],
            'privateKey': 'private-provider-secret', **changes}


def package(**changes):
    return {'id': 's4-package', 'operatorId': 'test_operator_uid', 'approvalStatus': 'draft',
            'packageTitle': 'Synthetic Penang Tour', 'destination': 'Penang', 'durationDays': 2,
            'adultPrice': 100, 'currency': 'MYR', 'priceBasis': 'per_person', 'taxIncluded': True,
            'fullDescription': 'Synthetic description.', 'availabilityStatus': 'available', **changes}


@contextmanager
def no_booking_mutations():
    with ExitStack() as stack:
        spies = [stack.enter_context(patch(path, side_effect=AssertionError('Forbidden mutation'))) for path in (
            'services.liteapi_service.validateHotelOffer', 'services.liteapi_service.createBookingReference',
            'modules.fr08_hotel_booking.routes.validateHotelOffer', 'modules.fr08_hotel_booking.routes.createBookingReference',
            'modules.fr09_payment.routes.createCheckoutSession', 'modules.fr09_payment.routes.updateRecord',
            'modules.fr08_hotel_booking.routes.claimRecord', 'requests.sessions.Session.request',
        )]
        yield
        for spy in spies:
            spy.assert_not_called()


@pytest.fixture
def provider():
    with patch.object(hotels, 'retrieveHotelProperties', return_value={'data': [raw_hotel()]}) as search, \
         patch.object(hotels, 'retrieveHotelContent', return_value={'data': raw_hotel()}) as detail:
        yield search, detail


def test_verified_operator_search_detail_are_bounded_read_only_and_redacted(client, mock_operator_auth, provider):
    with no_booking_mutations(), patch('modules.fr12_tourism_operator_management.routes.storeRecord') as write:
        search = client.get(SEARCH+'&hotelName=Heritage&starRating=4,4.5&limit=2&offset=4', headers=AUTH)
        detail = client.get(DETAIL, headers=AUTH)
    assert search.status_code == detail.status_code == 200
    item = search.json['items'][0]
    assert item['hotelId'] == 'lp_synthetic' and item['name'] == raw_hotel()['name']
    assert item['stars'] == 4 and item['guestRating'] == 8.7 and item['starClassificationSource'] == 'liteapi'
    assert item['city'] == 'George Town' and item['country'] == 'MY'
    assert item['amenities'] == ['Wi-Fi', 'Pool'] and item['imageUrls'] == ['https://images.example.test/room.jpg']
    assert item['reservationStatus'] == 'not_created' and search.json['availabilityChecked'] is False
    assert 'private-provider-secret' not in search.get_data(as_text=True)
    provider[0].assert_called_once_with({'countryCode': 'MY', 'cityName': 'George Town', 'hotelName': 'Heritage',
                                       'starRating': '4.0,4.5', 'limit': 2, 'offset': 4})
    provider[1].assert_called_once_with('lp_synthetic')
    write.assert_not_called()


@pytest.mark.parametrize('role', ['anonymous', 'traveller', 'admin', 'unverified', 'suspended'])
def test_discovery_requires_verified_active_operator(client, request, provider, role):
    with ExitStack() as stack:
        if role in {'traveller', 'admin'}:
            request.getfixturevalue('mock_'+role+'_auth')
        elif role == 'unverified':
            stack.enter_context(operator_auth_status('pending'))
        elif role == 'suspended':
            snap = MagicMock(exists=True)
            snap.to_dict.return_value = {'role': 'operator', 'verificationStatus': 'approved', 'status': 'suspended'}
            db = MagicMock()
            db.collection.return_value.document.return_value.get.return_value = snap
            stack.enter_context(patch('auth_utils.get_db', return_value=db))
            stack.enter_context(patch('auth_utils.auth.verify_id_token', return_value={'uid': 'suspended-operator'}))
        with no_booking_mutations():
            for path in [SEARCH, DETAIL]:
                response = client.get(path, headers={} if role == 'anonymous' else AUTH)
                assert response.status_code == (401 if role == 'anonymous' else 403)
    provider[0].assert_not_called()
    provider[1].assert_not_called()


@pytest.mark.parametrize('query', ['hotelName=Hotel', 'countryCode=MY', 'cityName=Penang',
    'countryCode=Malaysia&cityName=Penang', 'countryCode=MY&cityName=Penang&limit=21',
    'countryCode=MY&cityName=Penang&offset=-1', 'countryCode=MY&cityName=Penang&starRating=4.2',
    'countryCode=MY&cityName=Penang&stars=4', 'countryCode=MY&cityName=Penang&cityName=Other',
    'placeId=place&countryCode=MY', 'placeId=place&checkin=2030-01-01'])
def test_unsupported_invalid_or_duplicate_search_filters_fail_before_provider(client, mock_operator_auth, provider, query):
    response = client.get('/api/fr12/hotels/search?'+query, headers=AUTH)
    assert response.status_code == 400
    provider[0].assert_not_called()


def test_empty_and_place_search_do_not_fabricate_results(client, mock_operator_auth, provider):
    provider[0].return_value = {'data': []}
    response = client.get('/api/fr12/hotels/search?placeId=synthetic-place', headers=AUTH)
    assert response.status_code == 200 and response.json['items'] == [] and response.json['hasMore'] is False
    provider[0].assert_called_once_with({'placeId': 'synthetic-place', 'limit': 10, 'offset': 0})


@pytest.mark.parametrize('stars', [None, '', 0, True, 6, 4.2, 'unknown'])
def test_unknown_stars_never_fall_back_to_guest_score(client, mock_operator_auth, provider, stars):
    provider[1].return_value = {'data': raw_hotel(stars=stars, rating=9.2)}
    response = client.get(DETAIL, headers=AUTH)
    assert response.status_code == 200
    assert response.json['hotel']['stars'] is None and response.json['hotel']['starClassificationSource'] is None
    assert response.json['hotel']['guestRating'] == 9.2


@pytest.mark.parametrize('status,expected', [(401,503),(403,503),(429,429),(404,404),(500,502)])
def test_provider_errors_are_safe_and_never_return_supplier_secrets(client, mock_operator_auth, provider, status, expected):
    failed = requests.Response()
    failed.status_code = status
    provider[1].side_effect = requests.HTTPError('private-api-key-in-url', response=failed)
    response = client.get(DETAIL, headers=AUTH)
    assert response.status_code == expected and response.json['ok'] is False
    assert 'private-api-key-in-url' not in response.get_data(as_text=True)
    if status == 429:
        assert response.headers['Retry-After'] == '60'


@pytest.mark.parametrize('failure', [requests.Timeout('private-token'), RuntimeError('private-token'), ValueError('private-token')])
def test_timeout_configuration_or_decode_failure_is_unavailable(client, mock_operator_auth, provider, failure):
    provider[0].side_effect = failure
    response = client.get(SEARCH, headers=AUTH)
    assert response.status_code in {502, 503} and 'private-token' not in response.get_data(as_text=True)


@pytest.mark.parametrize('data,status', [({'data': None},404), ({'data': []},404), ({'data': [raw_hotel(),raw_hotel()]},502),
    ({'data': raw_hotel(id='different')},502), ({'data': {'name': 'No identity'}},502),
    ({'data': raw_hotel(name=None)},502), ({'data': 'malformed'},502)])
def test_missing_or_inconsistent_detail_identity_fails_closed(client, mock_operator_auth, provider, data, status):
    provider[1].return_value = data
    assert client.get(DETAIL, headers=AUTH).status_code == status


def test_optional_malformed_metadata_and_unsafe_images_are_not_exposed(client, mock_operator_auth, provider):
    provider[1].return_value = {'data': raw_hotel(images={}, photos={}, coordinates=[],
        hotelImages=[{'url': 'https://images.example.test/a.jpg?apiKey=private-token'},
                     {'url': 'http://127.0.0.1/private'}, {'url': 'https://127.0.0.1/private'}],
        main_photo='https://user:pass@images.example.test/x.jpg', hotelFacilities=[{'private': 'private-token'}])}
    response = client.get(DETAIL, headers=AUTH)
    assert response.status_code == 200
    assert response.json['hotel']['mainPhoto'] is None and response.json['hotel']['imageUrls'] == []
    assert response.json['hotel']['amenities'] == [] and 'private-token' not in response.get_data(as_text=True)


def test_shared_rate_limit_prevents_extra_discovery_requests(client, mock_operator_auth, provider):
    for _ in range(30):
        assert client.get(DETAIL, headers=AUTH).status_code == 200
    response = client.get(DETAIL, headers=AUTH)
    assert response.status_code == 429 and int(response.headers['Retry-After']) >= 1
    assert provider[1].call_count == 30


def test_adapter_uses_only_fixed_metadata_host_and_bounded_timeout():
    from services import liteapi_service
    response = MagicMock()
    response.json.return_value = {'data': []}
    with patch.object(liteapi_service, '_headers', return_value={'X-API-Key': 'synthetic-only'}), \
         patch.object(liteapi_service.requests, 'get', return_value=response) as get:
        assert liteapi_service.retrieveHotelProperties({'countryCode': 'MY', 'cityName': 'Penang'}) == {'data': []}
    assert get.call_args.args == ('https://api.liteapi.travel/v3.0/data/hotels',)
    assert get.call_args.kwargs['timeout'] == 20


def test_package_create_revalidates_provider_and_auto_populates_name_and_category(client, mock_operator_auth, provider):
    payload = package(hotelSelection={'provider': 'liteapi', 'hotelId': 'lp_synthetic'},
                      accommodationName='Forged name', accommodationCategory='5-Star')
    before = deepcopy(payload)
    with no_booking_mutations(), patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value={}), \
         patch('modules.fr12_tourism_operator_management.routes.storeRecord', side_effect=lambda coll,data: {'id':'new',**data}) as store:
        response = client.post('/api/fr12/packages', headers=AUTH, json=payload)
    assert response.status_code == 201
    saved = store.call_args.args[1]
    assert saved['operatorId'] == 'test_operator_uid' and saved['approvalStatus'] == 'draft'
    assert saved['accommodationName'] == 'Synthetic Heritage Hotel' and saved['accommodationCategory'] == '4-Star'
    assert saved['accommodationHotel']['stars'] == 4 and saved['accommodationHotel']['guestRating'] == 8.7
    assert saved['accommodationHotel']['reservationStatus'] == 'not_created' and 'hotelSelection' not in saved
    assert 'private-provider-secret' not in str(saved) and payload == before
    provider[1].assert_called_once_with('lp_synthetic')


@pytest.mark.parametrize('selection', [{'provider': 'other', 'hotelId': 'lp_synthetic'},
    {'provider': 'liteapi', 'hotelId': 'lp_synthetic', 'stars': 5}, {'provider':'liteapi','hotelId':'https://evil.test'}, 'lp_synthetic'])
def test_invalid_selection_does_not_write_or_call_provider(client, mock_operator_auth, provider, selection):
    with patch('modules.fr12_tourism_operator_management.routes.storeRecord') as store:
        response = client.post('/api/fr12/packages', headers=AUTH, json=package(hotelSelection=selection))
    assert response.status_code == 400
    store.assert_not_called()
    provider[1].assert_not_called()


def test_forged_snapshot_and_foreign_package_are_rejected_before_provider(client, mock_operator_auth, provider):
    with patch('modules.fr12_tourism_operator_management.routes.storeRecord') as store:
        assert client.post('/api/fr12/packages', headers=AUTH, json=package(accommodationHotel={'stars':5})).status_code == 400
    store.assert_not_called()
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value=package(operatorId='other')), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord') as update:
        response = client.put('/api/fr12/packages/foreign', headers=AUTH,
                              json={'hotelSelection': {'provider':'liteapi','hotelId':'lp_synthetic'}})
    assert response.status_code == 404
    update.assert_not_called()
    provider[1].assert_not_called()


def test_approved_hotel_edit_returns_to_draft_and_uses_expected_record(client, mock_operator_auth, provider):
    original = package(approvalStatus='approved', reviewedBy='admin', updatedAt='v1')
    before = deepcopy(original)
    with no_booking_mutations(), patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value=original), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord',
               side_effect=lambda coll,id,patch,**kw: {**original,**patch}) as update:
        response = client.put('/api/fr12/packages/s4-package', headers=AUTH,
                              json={'hotelSelection': {'provider':'liteapi','hotelId':'lp_synthetic'}})
    assert response.status_code == 200 and response.json['package']['approvalStatus'] == 'draft'
    assert response.json['package']['reviewedBy'] == ''
    assert update.call_args.kwargs == {'expected': original} and original == before


def test_stale_package_selection_and_failed_write_never_report_success(client, mock_operator_auth, provider):
    for error, status in [(ReviewConflict('changed'),409),(RuntimeError('private-storage-detail'),503)]:
        with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value=package()), \
             patch('modules.fr12_tourism_operator_management.routes.updateRecord', side_effect=error):
            response = client.put('/api/fr12/packages/s4-package', headers=AUTH,
                                  json={'hotelSelection': {'provider':'liteapi','hotelId':'lp_synthetic'}})
        assert response.status_code == status and 'private-storage-detail' not in response.get_data(as_text=True)


def test_existing_selection_requires_explicit_manual_detach_and_unknown_stars_remain_unknown(client, mock_operator_auth, provider):
    hotel = hotels.hotel_detail('lp_synthetic')
    current = package(accommodationHotel=hotel, accommodationName=hotel['name'], accommodationCategory='4-Star')
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value=current), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord', side_effect=lambda c,id,p,**kw:{**current,**p}):
        assert client.put('/api/fr12/packages/s4-package', headers=AUTH, json={'accommodationCategory':'5-Star'}).status_code == 400
        response = client.put('/api/fr12/packages/s4-package', headers=AUTH,
                              json={'hotelSelection':None,'accommodationName':'Manual Hotel','accommodationCategory':'Boutique'})
    assert response.status_code == 200 and response.json['package']['accommodationHotel'] is None
    assert response.json['package']['accommodationName'] == 'Manual Hotel'
    provider[1].return_value = {'data': raw_hotel(stars=None)}
    resolved = hotels.resolve_package_hotel({'hotelSelection':{'provider':'liteapi','hotelId':'lp_synthetic'}})
    assert resolved['accommodationCategory'] == '' and resolved['accommodationHotel']['stars'] is None


def test_snapshot_crosses_public_and_new_checkout_boundaries_without_mutating_old_orders(provider):
    hotel = hotels.hotel_detail('lp_synthetic')
    source = package(approvalStatus='approved', accommodationHotel={**deepcopy(hotel),'privateKey':'private-sentinel'},
                     accommodationName=hotel['name'],accommodationCategory='4-Star')
    before = deepcopy(source)
    historical_order = {'paymentStatus':'paid','packageSnapshot':{'accommodation':{'accommodationName':'Old Manual Hotel'}}}
    original_order = deepcopy(historical_order)
    public = public_package(source)
    snapshot = prepare_package_snapshot(source, {'id':'test_operator_uid'})
    assert public['accommodationHotel']['hotelId'] == hotel['hotelId']
    assert 'private-sentinel' not in str(public) and 'private-sentinel' not in str(snapshot)
    assert snapshot['accommodation']['accommodationHotel']['stars'] == 4
    source['accommodationHotel']['amenities'].append('Changed later')
    assert 'Changed later' not in snapshot['accommodation']['accommodationHotel']['amenities']
    assert historical_order == original_order and before['accommodationHotel']['amenities'] == hotel['amenities']
    legacy = package(approvalStatus='approved',accommodationName='Legacy Manual',accommodationCategory='Boutique')
    assert 'accommodationHotel' not in public_package(legacy)
    assert 'accommodationHotel' not in prepare_package_snapshot(legacy,{'id':'test_operator_uid'})['accommodation']


def test_nested_snapshot_allowlist_keeps_normalized_legacy_package_compatible():
    raw = package(accommodationHotel={'provider':'liteapi','hotelId':'lp_synthetic','name':'Hotel',
        'stars':None,'guestRating':9.9,'amenities':[{'name':'Pool','private':'never'}],
        'imageUrls':['https://images.example.test/a.jpg'],'private':'never'})
    normalized = normalise_package(raw)
    assert normalized['accommodationHotel']['stars'] is None
    assert normalized['accommodationHotel']['amenities'] == ['Pool']
    assert 'never' not in str(normalized)


def test_admin_review_retains_safe_provider_snapshot_without_provider_calls(client, mock_admin_auth, provider):
    snapshot = hotels.hotel_detail('lp_synthetic')
    provider[1].reset_mock()
    current = package(approvalStatus='pending', accommodationHotel=snapshot,
                      accommodationName=snapshot['name'],accommodationCategory='4-Star')
    before = deepcopy(current)
    with no_booking_mutations(), patch('modules.fr13_administrator_management.routes.retrieveRecord', return_value=current), \
         patch('modules.fr13_administrator_management.routes.updateRecord',
               side_effect=lambda c,id,changes,**kw:{**current,**changes}) as update:
        response = client.post('/api/fr13/packages/s4-package/review', headers=AUTH,
                               json={'decision':'approved','comment':'Synthetic review'})
    assert response.status_code == 200 and response.json['package']['approvalStatus'] == 'approved'
    assert response.json['package']['accommodationHotel'] == snapshot
    assert update.call_args.kwargs['expected'] == current and current == before
    provider[1].assert_not_called()


def test_public_traveller_endpoint_uses_safe_optional_snapshot(client, mock_traveller_auth, provider):
    snapshot = hotels.hotel_detail('lp_synthetic')
    source = package(approvalStatus='approved',accommodationHotel={**snapshot,'apiKey':'private-sentinel'})
    provider[1].reset_mock()
    with no_booking_mutations(), patch('modules.shared_public_content.routes.retrieveRecord',
            side_effect=lambda coll,*args,**kw:[source] if coll=='tourism_packages' else [] if coll=='promotional_campaigns' else {}):
        response = client.get('/api/public/tourism-packages',headers=AUTH)
    assert response.status_code == 200
    assert response.json['items'][0]['accommodationHotel']['hotelId'] == 'lp_synthetic'
    assert 'private-sentinel' not in response.get_data(as_text=True)
    provider[1].assert_not_called()


def test_new_attempt_is_server_owned_and_retry_preserves_hotel_and_historical_order(client, mock_traveller_auth, provider):
    from test_fr15_package_checkout_api import AtomicMemory
    memory = AtomicMemory()
    hotel = hotels.hotel_detail('lp_synthetic')
    memory.seed('tourism_packages','s4-package',package(approvalStatus='approved',accommodationHotel=hotel))
    memory.seed('users','test_operator_uid',{'role':'operator','status':'active'})
    memory.seed('checkout_orders','historical-paid',{'paymentStatus':'paid','amount':90,
                'packageSnapshot':{'accommodation':{'accommodationName':'Historical manual hotel'}}})
    historical = memory.retrieve('checkout_orders','historical-paid')
    provider[1].reset_mock()
    with no_booking_mutations(), patch('modules.fr15_package_checkout.routes.retrieveRecord',side_effect=memory.retrieve), \
         patch('modules.fr15_package_checkout.routes.claimRecord',side_effect=memory.claim):
        response = client.post('/api/fr15/package-checkout-attempts',headers=AUTH,
                               json={'packageId':'s4-package','idempotencyKey':'s4-synthetic-attempt'})
        assert response.status_code == 200
        original_attempt = deepcopy(response.json['attempt'])
        assert original_attempt['packageSnapshot']['accommodation']['accommodationHotel'] == hotels.safe_hotel_snapshot(hotel)
        assert original_attempt['paymentStatus'] == 'payment_pending' and original_attempt['fulfillmentStatus'] == 'fulfillment_pending'
        memory.collections['tourism_packages']['s4-package']['accommodationHotel']['name']='Changed later'
        retry = client.post('/api/fr15/package-checkout-attempts',headers=AUTH,
                            json={'packageId':'s4-package','idempotencyKey':'s4-synthetic-attempt'})
    assert retry.status_code == 200 and retry.json['reused'] is True
    assert retry.json['attempt']['packageSnapshot'] == original_attempt['packageSnapshot']
    assert memory.retrieve('checkout_orders','historical-paid') == historical
    provider[1].assert_not_called()


@pytest.mark.parametrize('body', [None, {'data':None}, {'data':{}}, {'data':[{'name':'No ID'}]}, {'error':{'message':'private-token'}}])
def test_malformed_search_cannot_be_mistaken_for_empty_success(client, mock_operator_auth, provider, body):
    provider[0].return_value = body
    response = client.get(SEARCH,headers=AUTH)
    assert response.status_code == 502 and response.json['ok'] is False
    assert 'private-token' not in response.get_data(as_text=True)


def test_expired_client_snapshot_is_not_selection_evidence_and_save_refetches(client, mock_operator_auth, provider):
    with patch('modules.fr12_tourism_operator_management.routes.storeRecord') as store:
        response = client.post('/api/fr12/packages',headers=AUTH,json=package(
            hotelSelection={'provider':'liteapi','hotelId':'lp_synthetic','retrievedAt':'2001-01-01T00:00:00Z'}))
    assert response.status_code == 400
    store.assert_not_called()
    provider[1].assert_not_called()


def test_provider_failure_or_storage_failure_during_selection_never_saves_false_success(client, mock_operator_auth, provider):
    payload = package(hotelSelection={'provider':'liteapi','hotelId':'lp_synthetic'})
    provider[1].side_effect = requests.Timeout('private-provider-key')
    with patch('modules.fr12_tourism_operator_management.routes.storeRecord') as store:
        response = client.post('/api/fr12/packages',headers=AUTH,json=payload)
    assert response.status_code == 502
    store.assert_not_called()
    provider[1].side_effect = None
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord',return_value={}), \
         patch('modules.fr12_tourism_operator_management.routes.storeRecord',side_effect=RuntimeError('private-storage')):
        response = client.post('/api/fr12/packages',headers=AUTH,json=payload)
    assert response.status_code == 503 and 'private-storage' not in response.get_data(as_text=True)


@pytest.mark.parametrize('stars', [None, 3, 4.5])
def test_requested_stars_are_enforced_against_returned_metadata(client, mock_operator_auth, provider, stars):
    provider[0].return_value = {'data':[raw_hotel(stars=stars)]}
    response = client.get(SEARCH+'&starRating=4',headers=AUTH)
    assert response.status_code == 200 and response.json['items'] == []


def test_save_selection_shares_provider_quota_and_cannot_bypass_it(client, mock_operator_auth, provider):
    with patch('modules.fr12_tourism_operator_management.routes.rate_limit_response') as limit, \
         patch('modules.fr12_tourism_operator_management.routes.storeRecord') as store:
        from flask import jsonify
        with client.application.app_context():
            limit.return_value=(jsonify(ok=False,error='Too many requests.'),429)
        response=client.post('/api/fr12/packages',headers=AUTH,
            json=package(hotelSelection={'provider':'liteapi','hotelId':'lp_synthetic'}))
    assert response.status_code == 429
    limit.assert_called_once_with('provider_search','test_operator_uid')
    store.assert_not_called()
    provider[1].assert_not_called()
