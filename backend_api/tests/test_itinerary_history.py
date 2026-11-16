"""No live Firestore: exercise actual storage boundary with serializable SDK doubles."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace

import pytest

from services.itinerary_history import (HistoryConflict, editable_snapshot, history_patch,
    restore_patch, version_state, ensure_restorable)
from sequence_contract import firebase_firestore as storage
from test_preference_learning_transaction import TransactionDatabase


def trip():
    return {'id': 'trip', 'travellerId': 'owner', 'title': 'Penang trip', 'budgetLimit': 500,
            'destinationArea': 'Penang', 'startDate': '2027-02-10', 'endDate': '2027-02-12',
            'travellerCount': 1, 'activities': [
                {'activityId': f'a{day}', 'activityName': f'Park {day}', 'destinationId': f'p{day}',
                 'dayNo': day, 'timeSlot': '09:00 - 10:00', 'recommendedDurationMinutes': 60,
                 'gps_coordinates': {'latitude': 5.41, 'longitude': 100.33}}
                for day in (1, 2, 3)]}


class HistoryDatabase(TransactionDatabase):
    def __init__(self):
        super().__init__()
        self.fail_write = False

    def collection(self, name):
        collection = super().collection(name)
        db = self

        class Query:
            def __init__(self, filters): self.filters = filters
            def where(self, key, op, value): return Query([*self.filters, (key, value)])
            def limit(self, count): return self
            def stream(self, transaction=None):
                assert transaction is not None
                return [SimpleNamespace() for (c, _), row in db.records.items()
                        if c == name and all(row.get(k) == v for k, v in self.filters)]

        collection.where = lambda key, op, value: Query([(key, value)])
        return collection

    def transaction(self):
        tx = super().transaction()
        stage = tx.set
        def set_record(ref, data, merge=False):
            if self.fail_write: raise RuntimeError('simulated commit failure')
            stage(ref, {**self.records.get(ref.key, {}), **data} if merge else data)
        tx.set = set_record
        def update(ref, data):
            if self.fail_write: raise RuntimeError('simulated commit failure')
            tx.set(ref, {**self.records[ref.key], **data})
        tx.update = update
        return tx


@pytest.fixture
def database(monkeypatch):
    db = HistoryDatabase()
    db.records[('itineraries', 'trip')] = {k: v for k, v in trip().items() if k != 'id'}
    monkeypatch.setattr(storage, 'get_db', lambda: db)
    monkeypatch.setattr('google.cloud.firestore.transactional', db.transactional)
    return db


def test_real_adapter_atomic_history_failure_retention_and_noop(database):
    current = storage.updateRecord('itineraries', 'trip', {'budgetLimit': 600})
    assert current['itineraryRevision'] == 2
    assert current['itineraryHistory'][0]['state']['budgetLimit'] == 500
    assert storage.updateRecord('itineraries', 'trip', {'budgetLimit': 600})['itineraryRevision'] == 2
    before = deepcopy(database.records)
    database.fail_write = True
    with pytest.raises(RuntimeError): storage.updateRecord('itineraries', 'trip', {'budgetLimit': 700})
    assert database.records == before
    database.fail_write = False
    for amount in range(700, 1400, 100):
        current = storage.updateRecord('itineraries', 'trip', {'budgetLimit': amount})
    assert len(current['itineraryHistory']) == 5
    with pytest.raises(HistoryConflict): version_state(current, 1)
    assert storage.updateRecord('itineraries', 'trip', {'status': 'planned'})['itineraryRevision'] == current['itineraryRevision']


def test_concurrent_updates_capture_actual_previous_state_and_stale_restore_writes_nothing(database):
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [executor.submit(storage.updateRecord, 'itineraries', 'trip', p)
                   for p in ({'budgetLimit': 600}, {'title': 'Renamed trip'})]
        for result in results: result.result()
    saved = {'id': 'trip', **database.records[('itineraries', 'trip')]}
    assert saved['itineraryRevision'] == 3 and len(saved['itineraryHistory']) == 2
    assert saved['budgetLimit'] == 600 and saved['title'] == 'Renamed trip'
    stale = trip()
    before = deepcopy(database.records)
    with pytest.raises(HistoryConflict):
        storage.updateRecord('itineraries', 'trip', {'budgetLimit': 500, '_restoreVersion': 1}, expected=stale)
    assert before == database.records


@pytest.mark.parametrize('collection', ['hotel_bookings', 'checkout_orders'])
def test_transaction_rechecks_linked_commerce_and_owner_scope(database, collection):
    current = storage.updateRecord('itineraries', 'trip', {'budgetLimit': 600})
    database.records[(collection, 'linked')] = {'travellerId': 'owner', 'itineraryId': 'trip'}
    before = deepcopy(database.records)
    with pytest.raises(HistoryConflict):
        storage.updateRecord('itineraries', 'trip', {'budgetLimit': 500, '_restoreVersion': 1}, expected=current)
    assert database.records == before
    database.records[(collection, 'linked')]['travellerId'] = 'another-owner'
    result = storage.updateRecord('itineraries', 'trip', {'budgetLimit': 500, '_restoreVersion': 1}, expected=current)
    assert result['budgetLimit'] == 500 and result['itineraryHistory'][-1]['state']['budgetLimit'] == 600


def test_snapshots_do_not_copy_commerce_provider_data_or_duplicate_schedules():
    value = trip()
    value.update(selectedHotel={'private': 'HOTEL_SECRET'}, paymentSnapshot={'secret': 'STRIPE_SECRET'},
                 generationContext={'raw': 'PROVIDER_SECRET'}, dailySchedule=[{'activities': value['activities']}])
    snapshot = editable_snapshot(value)
    assert not any(secret in str(snapshot) for secret in ('HOTEL_SECRET', 'STRIPE_SECRET', 'PROVIDER_SECRET'))
    assert 'dailySchedule' not in snapshot
    value['activities'][0]['description'] = 'x' * 50000
    with pytest.raises(HistoryConflict): history_patch(value, {'title': 'Other'})


@pytest.mark.parametrize('field', ['selectedFlight', 'selectedHotel', 'hotelBookingId', 'checkoutOrderId',
                                  'paymentId', 'packageTrip', 'purchasedPackages', 'flightBookingId', 'paidTotal'])
def test_travel_and_commercial_selections_block_restoration(field):
    value = trip()
    value[field] = 'linked'
    with pytest.raises(HistoryConflict): ensure_restorable(value)


def test_restore_budget_full_and_day_preserve_scope_and_reversibility():
    original = trip()
    saved = {**original, **history_patch(original, {'budgetLimit': 900})}
    patch = restore_patch(saved, 1, scope='budget')
    assert patch['budgetLimit'] == 500 and 'activities' not in patch
    changed = deepcopy(saved['activities'])
    changed[1].update(activityName='New day 2', destinationId='new2')
    newer = {**saved, **history_patch(saved, {'activities': changed})}
    day_patch = restore_patch(newer, 1, scope='day', day=2)
    assert [a for a in day_patch['activities'] if a['dayNo'] != 2] == [a for a in changed if a['dayNo'] != 2]
    assert next(a for a in day_patch['activities'] if a['dayNo'] == 2)['activityName'] == 'Park 2'
    assert 'budgetLimit' not in day_patch
    assert [a['dayNo'] for a in day_patch['activities']] == [1, 2, 3]
    assert next(d for d in day_patch['dailySchedule'] if d['dayNo'] == 2)['dayLabel'].startswith('Day 2')
    full = restore_patch(newer, 1)
    assert full['budgetLimit'] == 500 and len(full['activities']) == 3
    restored = {**newer, **history_patch(newer, full)}
    assert version_state(restored, 3)['budgetLimit'] == 900


def test_copied_server_metadata_cannot_rewind_the_version_chain(database):
    first = storage.updateRecord('itineraries', 'trip', {'budgetLimit': 600})
    second = storage.updateRecord('itineraries', 'trip', {'title': 'Next'})
    result = storage.updateRecord('itineraries', 'trip', {'budgetLimit': 700,
        'itineraryHistory': first['itineraryHistory'], 'itineraryRevision': first['itineraryRevision']})
    assert result['itineraryRevision'] == 4 and len(result['itineraryHistory']) == 3
    assert result['itineraryHistory'][-1]['state']['title'] == second['title']
    assert '_restoreVersion' not in result


def test_title_only_restore_does_not_rearrange_or_strip_activity_metadata():
    original = trip()
    original['activities'][0]['scheduledStartTime'] = '11:15'
    original['activities'][0]['scheduleNotes'] = ['Personal arrangement']
    saved = {**original, **history_patch(original, {'title': 'Another title'})}
    patch = restore_patch(saved, 1)
    assert patch['title'] == original['title'] and 'activities' not in patch and 'dailySchedule' not in patch


def test_structured_restore_budget_scope_is_allowlisted():
    from modules.fr11_chatbot_travel_assistant.contextual_intent import validate_interpretation
    state = {'adjustment': {'tripId': 'owned'}}
    assert validate_interpretation({'intent': 'restore_version', 'version': 1, 'restoreScope': 'budget', 'confidence': 1}, state, [])
    assert validate_interpretation({'intent': 'restore_version', 'version': 1, 'restoreScope': 'payment', 'confidence': 1}, state, []) is None
    assert validate_interpretation({'intent': 'restore_version', 'version': 1, 'restoreScope': 'day', 'confidence': 1}, state, []) is None


def test_legacy_count_is_used_only_when_actually_recorded():
    original = trip()
    original.pop('travellerCount')
    original['numberOfTravellers'] = 4
    saved = {**original, **history_patch(original, {'travellerCount': 2})}
    assert restore_patch(saved, 1)['travellerCount'] == 4
    original.pop('numberOfTravellers')
    saved = {**original, **history_patch(original, {'travellerCount': 2})}
    with pytest.raises(HistoryConflict, match='historical traveller count'):
        restore_patch(saved, 1)


def test_two_concurrent_restorations_only_commit_once(database):
    expected = storage.updateRecord('itineraries', 'trip', {'budgetLimit': 600})
    def restore():
        try:
            return storage.updateRecord('itineraries', 'trip', {'budgetLimit': 500, '_restoreVersion': 1}, expected=expected)
        except HistoryConflict as error:
            return error
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: restore(), range(2)))
    assert sum(isinstance(r, dict) for r in results) == 1
    assert sum(isinstance(r, HistoryConflict) for r in results) == 1
    final = database.records[('itineraries', 'trip')]
    assert final['itineraryRevision'] == 3 and len(final['itineraryHistory']) == 2


@pytest.mark.parametrize('field,status', [('status', 'confirmed'), ('paymentStatus', 'paid'), ('bookingStatus', 'booked')])
def test_legacy_commercial_status_without_ids_still_blocks_restoration(field, status):
    with pytest.raises(HistoryConflict): ensure_restorable({**trip(), field: status})
