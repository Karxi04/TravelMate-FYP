from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Lock
from unittest.mock import MagicMock, patch

import pytest
from services import packing_checklist_service as service
from modules.fr05_smart_itinerary_budget_planner import packing_routes

NOW = datetime(2026, 11, 3, 9, tzinfo=timezone.utc)
PATH = '/api/fr5/itineraries/packing-trip/packing-checklist'
TOKEN = {'Authorization': 'Bearer synthetic'}


def trip(**changes):
    return {'id': 'packing-trip', 'travellerId': 'test_traveller_uid', 'destinationArea': 'Penang',
            'startDate': '2026-11-03', 'endDate': '2026-11-05',
            'activities': [{'activityName': 'Heritage city walk', 'category': 'Culture'}], **changes}


def forecast(**changes):
    return {'source': 'open-meteo', 'fetchedAt': NOW.isoformat(), 'latitude': 5.4, 'longitude': 100.3,
            'daily': {'time': ['2026-11-03', '2026-11-04', '2026-11-05'],
                      'weather_code': [63, 0, 3], 'temperature_2m_max': [31, 32, 25],
                      'temperature_2m_min': [25, 24, 19]}, **changes}


def weather_trip(value):
    return trip(generationContext={'forecastData': value, 'destinationCoordinates': {'latitude': 5.4, 'longitude': 100.3}})


def generated(value=None, preferences=None):
    return service.mutate(None, value or trip(), preferences, 'test_traveller_uid', 'packing-trip', {}, NOW)[0]


@pytest.mark.parametrize('end,quantity', [('2026-11-03', 1), ('2026-11-05', 3), ('2026-12-02', 14),
                                       ('2026-11-05T00:00:00.000', 3), ('2026-11-05T23:00:00+08:00', 3)])
def test_duration_quantities_are_inclusive_and_bounded(end, quantity):
    record = generated(trip(endDate=end))
    assert next(i for i in record['items'] if i['itemId'] == 'clothing_changes')['quantity'] == quantity


@pytest.mark.parametrize('label,expected', [('Beach', {'swimwear', 'towel', 'sunscreen', 'beach_footwear'}),
    ('Hiking trail', {'walking_shoes', 'water_bottle', 'outdoor_clothing'}),
    ('City heritage', {'walking_shoes', 'day_bag', 'power_bank'})])
def test_activity_rules(label, expected):
    record = generated(trip(activities=[{'category': label}]))
    assert expected <= {i['itemId'] for i in record['items']}


def test_mixed_daily_activities_and_preferences_are_deduplicated_without_copying_preferences():
    value = trip(activities=[{'category': 'Beach hiking city'}], dailySchedule=[{'activities': [{'category': 'Hiking city'}]}])
    preferences = {'interests': ['Beach', 'Hiking'], 'privateSentinel': 'never-expose'}
    record = generated(value, preferences)
    ids = [i['itemId'] for i in record['items']]
    assert len(ids) == len(set(ids)) and ids.count('walking_shoes') == 1
    assert 'never-expose' not in str(record)
    assert generated(trip(activities=[]), {'interests': ['Hiking']})['items'][-2]['source'] == 'preference'


@pytest.mark.parametrize('value', [{}, {'startDate': 'bad', 'endDate': None}, {'startDate': '2026-11-05', 'endDate': '2026-11-03'},
                                  {'activities': None, 'dailySchedule': None, 'tripDays': False}])
def test_missing_optional_or_invalid_historical_fields_do_not_block(value):
    assert generated(trip(**value))['items']


def test_valid_weather_uses_dates_location_freshness_and_no_provider():
    record = generated(weather_trip(forecast()))
    assert record['weatherContext']['status'] == 'available'
    items = {i['itemId']: i for i in record['items']}
    assert items['rain_protection']['source'] == 'weather'
    assert {'light_jacket', 'sun_hat'} <= items.keys()


@pytest.mark.parametrize('change', [{'fetchedAt': (NOW-timedelta(days=2)).isoformat()}, {'fetchedAt': None},
    {'fetchedAt': '2026-11-03T09:00:00'}, {'fetchedAt': (NOW+timedelta(days=1)).isoformat()},
    {'source': 'unknown'}, {'source': {}}, {'latitude': 1.0}, {'unavailable': True},
    {'daily': {'time': ['2030-01-01'], 'weather_code': [63]}}, {'daily': {}}])
def test_unreliable_weather_falls_back_honestly(change):
    record = generated(weather_trip(forecast(**change)))
    assert record['weatherContext']['status'] == 'unavailable'
    assert not any(i['source'] == 'weather' for i in record['items'])
    assert 'not a forecast' in next(i['reason'] for i in record['items'] if i['itemId'] == 'rain_protection')


def test_partial_weather_and_missing_measurements_do_not_invent_temperatures():
    record = generated(weather_trip(forecast(daily={'time': ['2026-11-03'], 'weather_code': [63]})))
    assert record['weatherContext']['status'] == 'partial'
    assert not any(i['itemId'] == 'light_jacket' for i in record['items'])


@pytest.mark.parametrize('changes,expected', [({'destinationCountry': 'Singapore'}, False),
    ({'originCountry': 'Malaysia', 'destinationCountry': 'Singapore'}, True),
    ({'originLocation': {'country': 'MY'}, 'destinationCountry': 'Malaysia'}, False),
    ({'originCountry': 'unknown', 'destinationCountry': 'Singapore'}, False)])
def test_international_requires_explicit_reliable_origin_and_destination(changes, expected):
    assert ('passport' in {i['itemId'] for i in generated(trip(**changes))['items']}) is expected


def test_refresh_preserves_customizations_checked_suppressed_inactive_and_reappearing_items():
    original = trip(activities=[{'category': 'Beach'}])
    current = generated(original)
    def edit(action, **fields):
        nonlocal current
        current, _ = service.mutate(current, original, None, 'test_traveller_uid', 'packing-trip',
                                   {'action': action, 'expectedRevision': current['revision'], **fields}, NOW)
    edit('update', itemId='swimwear', name='My swimwear', quantity=2, isPacked=True)
    edit('remove', itemId='towel')
    edit('add', itemId='custom_book', name='Novel', category='miscellaneous', isPacked=True)
    changed = trip(endDate='2026-11-06', activities=[{'category': 'Hiking'}])
    current, summary = service.mutate(current, changed, None, 'test_traveller_uid', 'packing-trip',
        {'action': 'refresh', 'expectedRevision': current['revision']}, NOW+timedelta(minutes=1))
    items = {i['itemId']: i for i in current['items']}
    assert summary['added'] > 0 and items['custom_book']['isPacked']
    assert not items['swimwear']['applicable'] and items['towel']['suppressed']
    current, _ = service.mutate(current, original, None, 'test_traveller_uid', 'packing-trip',
        {'action': 'refresh', 'expectedRevision': current['revision']}, NOW+timedelta(minutes=2))
    items = {i['itemId']: i for i in current['items']}
    assert items['swimwear']['isPacked'] and items['swimwear']['name'] == 'My swimwear' and items['swimwear']['quantity'] == 2
    assert items['swimwear']['applicable'] and items['towel']['suppressed']


def test_repeated_generation_and_unchanged_refresh_do_not_reset_or_write_new_revision():
    current = generated()
    again, _ = service.mutate(current, trip(), None, 'test_traveller_uid', 'packing-trip', {}, NOW+timedelta(hours=1))
    assert again == current
    refreshed, _ = service.mutate(current, trip(), None, 'test_traveller_uid', 'packing-trip',
        {'action': 'refresh', 'expectedRevision': 1}, NOW+timedelta(minutes=1))
    assert refreshed == current


def test_empty_progress_and_suppression_restore():
    current = generated()
    for item in list(current['items']):
        current, _ = service.mutate(current, trip(), None, 'test_traveller_uid', 'packing-trip',
            {'action': 'remove', 'itemId': item['itemId'], 'expectedRevision': current['revision']}, NOW)
    dto = service.response_dto(current, trip(), None, NOW)
    assert dto['state'] == 'empty' and dto['progress']['completionPercentage'] == 0 and dto['progress']['totalItems'] == 0
    current, _ = service.mutate(current, trip(), None, 'test_traveller_uid', 'packing-trip',
        {'action': 'restore', 'itemId': 'phone_charger', 'expectedRevision': current['revision']}, NOW)
    assert service.response_dto(current, trip(), None, NOW)['progress']['totalItems'] == 1


def test_expired_weather_is_downgraded_in_read_response_without_mutating_stored_items():
    value = weather_trip(forecast())
    current = generated(value)
    before = deepcopy(current)
    dto = service.response_dto(current, value, None, NOW+timedelta(days=2))
    assert dto['needsRefresh'] and dto['weatherContext']['status'] == 'unavailable'
    assert not any(i['source'] == 'weather' for i in dto['checklist']['items']) and current == before


@pytest.fixture
def packing_store(monkeypatch):
    """Atomic fake for HTTP tests; real Firestore transaction covered separately."""
    lock = Lock()
    state = {'trip': trip(), 'preferences': None, 'current': None, 'writes': 0}
    def transact(trip_id, uid, transform):
        with lock:
            if trip_id != 'packing-trip' or not state['trip'] or state['trip'].get('travellerId') != uid:
                raise service.PackingError('Trip not found.', 404)
            current = state['current']
            if current and (current.get('travellerId') != uid or current.get('tripId') != trip_id):
                raise service.PackingError('Checklist not found.', 404)
            updated, response = transform(deepcopy(current), deepcopy(state['trip']), state['preferences'])
            if updated is not None and updated != current:
                state.update(current=deepcopy(updated), writes=state['writes']+1)
            return response
    monkeypatch.setattr(packing_routes, 'transactPackingChecklist', transact)
    return state


def test_http_generate_edit_read_refresh_and_legacy_trip_unchanged(client, mock_traveller_auth, packing_store):
    packing_store['trip'].update(selectedCarRental={'id': 'legacy', 'price': 75}, carRentalCost=75,
                                  packageSnapshot={'amount': 100}, budgetEstimate={'total': 500})
    before = deepcopy(packing_store['trip'])
    assert client.get(PATH, headers=TOKEN).json['state'] == 'not_generated'
    assert packing_store['writes'] == 0
    response = client.post(PATH, headers=TOKEN, json={})
    assert response.status_code == 200 and response.json['changes']['created'] is True
    assert client.post(PATH, headers=TOKEN, json={}).json['checklist']['revision'] == 1
    assert packing_store['writes'] == 1
    response = client.patch(PATH, headers=TOKEN, json={'action': 'update', 'itemId': 'phone_charger', 'isPacked': True, 'expectedRevision': 1})
    assert response.status_code == 200 and response.json['progress']['packedItems'] == 1
    assert client.get(PATH, headers=TOKEN).json['progress']['packedItems'] == 1
    assert client.post(PATH, headers=TOKEN, json={'action': 'refresh', 'expectedRevision': 2}).status_code == 200
    assert packing_store['trip'] == before


@pytest.mark.parametrize('method', ['get', 'post', 'patch'])
def test_http_no_auth_rejected_before_storage(client, method):
    with patch.object(packing_routes, 'transactPackingChecklist') as store:
        response = getattr(client, method)(PATH, json={})
    assert response.status_code == 401
    store.assert_not_called()


@pytest.mark.parametrize('role', ['operator', 'admin'])
def test_http_other_roles_forbidden(client, request, role):
    request.getfixturevalue('mock_'+role+'_auth')
    with patch.object(packing_routes, 'transactPackingChecklist') as store:
        response = client.get(PATH, headers=TOKEN)
    assert response.status_code == 403
    store.assert_not_called()


def test_http_invalid_token_is_rejected_before_storage(client):
    with patch('auth_utils.auth.verify_id_token', side_effect=ValueError('expired synthetic token')), \
         patch.object(packing_routes, 'transactPackingChecklist') as store:
        response = client.get(PATH, headers=TOKEN)
    assert response.status_code == 401 and response.json['ok'] is False
    store.assert_not_called()


@pytest.mark.parametrize('payload', [{'action': []}, {'action': 'generate', 'travellerId': 'foreign'},
    {'action': 'generate', 'revision': 99}, [], None])
def test_http_invalid_generation_and_protected_metadata_rejected(client, mock_traveller_auth, packing_store, payload):
    response = client.post(PATH, headers=TOKEN, json=payload, content_type='application/json')
    assert response.status_code == 400 and packing_store['writes'] == 0


@pytest.mark.parametrize('fields', [{'quantity': 0}, {'quantity': True}, {'quantity': 31}, {'isPacked': 'true'},
    {'name': ''}, {'name': 'x'*101}, {'name': '<script>'}, {'name': 'x\ny'}, {'category': []},
    {'category': 'invented'}, {'travellerId': 'other'}, {'suppressed': True}, {}])
def test_http_item_validation_does_not_write(client, mock_traveller_auth, packing_store, fields):
    client.post(PATH, headers=TOKEN, json={})
    response = client.patch(PATH, headers=TOKEN, json={'action': 'update', 'itemId': 'phone_charger', 'expectedRevision': 1, **fields})
    assert response.status_code == 400 and packing_store['writes'] == 1


def test_http_ownership_missing_corrupt_checklist_and_invalid_id(client, mock_traveller_auth, packing_store):
    for owner in ['foreign', None]:
        packing_store['trip'] = trip(travellerId=owner) if owner else None
        assert client.get(PATH, headers=TOKEN).status_code == 404
        assert client.post(PATH, headers=TOKEN, json={}).status_code == 404
    packing_store['trip'] = trip()
    packing_store['current'] = {**generated(), 'travellerId': 'foreign'}
    assert client.get(PATH, headers=TOKEN).status_code == 404
    assert client.get(PATH.replace('packing-trip', 'missing-trip'), headers=TOKEN).status_code == 404
    assert client.get(PATH.replace('packing-trip', 'x'*513), headers=TOKEN).status_code == 400


def test_http_optimistic_conflict_and_concurrent_updates_are_not_lost(app, mock_traveller_auth, packing_store):
    with app.test_client() as client:
        client.post(PATH, headers=TOKEN, json={})
    def update(name):
        with app.test_client() as client:
            return client.patch(PATH, headers=TOKEN, json={'action': 'update', 'itemId': 'phone_charger',
                                                         'name': name, 'expectedRevision': 1})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(update, ['Cable A', 'Cable B']))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert next(r for r in responses if r.status_code == 409).json['currentRevision'] == 2
    assert packing_store['writes'] == 2


def test_http_storage_failure_is_generic_and_recovers(client, mock_traveller_auth, packing_store):
    with patch.object(packing_routes, 'transactPackingChecklist', side_effect=RuntimeError('private-storage-detail')):
        response = client.post(PATH, headers=TOKEN, json={})
    assert response.status_code == 503 and 'private-storage-detail' not in response.get_data(as_text=True)
    assert packing_store['writes'] == 0
    assert client.post(PATH, headers=TOKEN, json={}).status_code == 200


def test_http_limits_custom_items_and_oversized_requests(client, mock_traveller_auth, packing_store):
    client.post(PATH, headers=TOKEN, json={})
    assert client.patch(PATH, headers=TOKEN, data=' '*16385, content_type='application/json').status_code == 413
    assert client.post(PATH, headers=TOKEN, data=' '*16385, content_type='application/json',
                       environ_overrides={'CONTENT_LENGTH': '', 'wsgi.input_terminated': True}).status_code == 413
    current = packing_store['current']
    current['items'] = [{**current['items'][0], 'itemId': 'custom_'+str(i), 'isCustom': True} for i in range(100)]
    response = client.patch(PATH, headers=TOKEN, json={'action': 'add', 'itemId': 'custom_extra',
        'name': 'Extra', 'category': 'miscellaneous', 'expectedRevision': current['revision']})
    assert response.status_code == 400 and packing_store['writes'] == 1


def test_http_custom_add_remove_noop_updates_and_stale_revision(client, mock_traveller_auth, packing_store):
    client.post(PATH, headers=TOKEN, json={})
    response = client.patch(PATH, headers=TOKEN, json={'action': 'add', 'itemId': 'custom_book',
        'name': 'Book', 'category': 'miscellaneous', 'expectedRevision': 1})
    assert response.status_code == 200 and response.json['checklist']['revision'] == 2
    assert client.patch(PATH, headers=TOKEN, json={'action': 'update', 'itemId': 'custom_book',
        'isPacked': False, 'expectedRevision': 2}).json['checklist']['revision'] == 2
    assert client.patch(PATH, headers=TOKEN, json={'action': 'remove', 'itemId': 'custom_book',
        'expectedRevision': 2}).status_code == 200
    assert not any(i['itemId'] == 'custom_book' for i in packing_store['current']['items'])
    assert client.post(PATH, headers=TOKEN, json={'action': 'refresh', 'expectedRevision': 1}).status_code == 409


@pytest.mark.parametrize('failure', ['Aborted', 'DeadlineExceeded'])
def test_repository_contention_has_one_bounded_fresh_transaction_retry(failure):
    from google.api_core import exceptions
    from sequence_contract import firebase_firestore as repository
    commit = MagicMock(side_effect=[getattr(exceptions, failure)('synthetic lock timeout'), {'ok': True}])
    with patch.object(repository, 'get_db', return_value=MagicMock()), \
         patch('google.cloud.firestore.transactional', return_value=commit), patch('time.sleep') as sleep:
        assert repository.transactPackingChecklist('trip', 'uid', MagicMock()) == {'ok': True}
    assert commit.call_count == 2 and sleep.call_count == 1


def test_repository_contention_exhaustion_does_not_return_success():
    from google.api_core.exceptions import DeadlineExceeded
    from sequence_contract import firebase_firestore as repository
    commit = MagicMock(side_effect=DeadlineExceeded('synthetic timeout'))
    with patch.object(repository, 'get_db', return_value=MagicMock()), \
         patch('google.cloud.firestore.transactional', return_value=commit), patch('time.sleep'):
        with pytest.raises(DeadlineExceeded):
            repository.transactPackingChecklist('trip', 'uid', MagicMock())
    assert commit.call_count == 2


def test_repository_retries_only_sdk_wrapped_contention_not_arbitrary_value_error():
    from google.api_core.exceptions import Aborted
    from sequence_contract import firebase_firestore as repository
    wrapped = ValueError('SDK retries exhausted')
    wrapped.__cause__ = Aborted('synthetic contention')
    with patch.object(repository, 'get_db', return_value=MagicMock()), \
         patch('google.cloud.firestore.transactional', return_value=MagicMock(side_effect=[wrapped, {'ok': True}])) as decorate, \
         patch('time.sleep'):
        assert repository.transactPackingChecklist('trip', 'uid', MagicMock()) == {'ok': True}
        assert decorate.return_value.call_count == 2
    with patch.object(repository, 'get_db', return_value=MagicMock()), \
         patch('google.cloud.firestore.transactional', return_value=MagicMock(side_effect=ValueError('invalid data'))) as decorate, \
         patch('time.sleep') as sleep:
        with pytest.raises(ValueError):
            repository.transactPackingChecklist('trip', 'uid', MagicMock())
        assert decorate.return_value.call_count == 1
        sleep.assert_not_called()
