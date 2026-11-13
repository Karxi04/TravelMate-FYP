from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Lock

import pytest

from modules.fr05_smart_itinerary_budget_planner import expense_routes as expenses

HEADERS = {'Authorization': 'Bearer synthetic'}
URL = '/api/fr5/itineraries/expense-trip/expenses'
ENTRY = {'name': 'Lunch', 'category': 'Food', 'type': 'planned', 'amount': '15.25',
         'description': 'Market meal', 'date': '2026-11-14'}
TRIP = {'id': 'expense-trip', 'travellerId': 'test_traveller_uid', 'title': 'Penang',
        'startDate': '2026-11-14', 'endDate': '2026-11-15', 'budgetLimit': 300,
        'budgetEstimate': {'total': 190}, 'activities': []}


@pytest.fixture
def expense_store(monkeypatch):
    saved = deepcopy(TRIP)
    lock = Lock()

    def transact(iid, uid, payload):
        with lock:
            if iid != saved['id'] or uid != saved['travellerId']:
                raise expenses.ExpenseError('Trip not found.', 404)
            if saved.get('packageTrip'):
                raise expenses.ExpenseError('Ordinary trips only.', 409)
            if payload is not None:
                saved.update(expenses.update_expenses(saved, payload, 'new-expense'))
            return {'ok': True, 'expenses': deepcopy(saved.get('manualExpenses', [])),
                    'revision': saved.get('manualExpenseRevision', 0),
                    'overview': expenses.expense_overview(saved, [{'amountMinor': 8000}])}

    monkeypatch.setattr(expenses, '_transact_expenses', transact)
    return saved


def test_expenses_add_edit_delete_reload_and_limit(client, mock_traveller_auth, expense_store):
    def change(action, revision, **fields):
        response = client.patch(URL, headers=HEADERS, json={'action': action, 'expectedRevision': revision, **fields})
        assert response.status_code == 200, response.json
        return response.json

    assert client.get(URL, headers=HEADERS).json['expenses'] == []
    added = change('add', 0, expense=ENTRY)
    assert added['expenses'][0]['amountMinor'] == 1525
    assert added['overview']['plannedMinor'] == 1525
    expense_id = added['expenses'][0]['id']
    edited = change('edit', 1, expenseId=expense_id, expense={**ENTRY, 'type': 'actual', 'amount': '12.30'})
    overview = edited['overview']
    assert (overview['plannedMinor'], overview['actualMinor'], overview['verifiedMinor']) == (0, 1230, 8000)
    assert overview['balanceAfterRecordedActualMinor'] == 28770
    assert overview['unknownCategories']
    assert client.get(URL, headers=HEADERS).json == edited
    assert expense_store['budgetEstimate'] == TRIP['budgetEstimate']
    changed = change('limit', 2, budgetLimit='250.10', expectedBudgetLimit=300)
    assert changed['overview']['balanceAfterRecordedActualMinor'] == 23780
    removed = change('delete', 3, expenseId=expense_id)
    assert removed['expenses'] == [] and removed['overview']['actualMinor'] == 0
    assert expense_store['activities'] == TRIP['activities']


@pytest.mark.parametrize('invalid', [{'amount': True}, {'amount': '-10'}, {'amount': '0'},
    {'amount': '0.001'}, {'amount': 'NaN'}, {'amount': '1e99'}, {'category': 'Hotel'},
    {'date': '2026-11-16'}, {'date': '20261114'}, {'type': 'verified'}, {'currency': 'USD'},
    {'paidTotal': 0}, {'travellerId': 'foreign'}])
def test_invalid_expense_does_not_write(client, mock_traveller_auth, expense_store, invalid):
    response = client.patch(URL, headers=HEADERS, json={
        'action': 'add', 'expectedRevision': 0, 'expense': {**ENTRY, **invalid},
    })
    assert response.status_code == 400
    assert expense_store == TRIP


def test_stale_expenses_cannot_overwrite_other_edits(app, mock_traveller_auth, expense_store):
    def add(name):
        with app.test_client() as client:
            return client.patch(URL, headers=HEADERS, json={
                'action': 'add', 'expectedRevision': 0, 'expense': {**ENTRY, 'name': name},
            }).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(add, ['Lunch A', 'Lunch B'])) == [200, 409]
    assert len(expense_store['manualExpenses']) == 1
    with app.test_client() as client:
        response = client.patch(URL, headers=HEADERS, json={
            'action': 'limit', 'expectedRevision': 1, 'expectedBudgetLimit': 200, 'budgetLimit': '400',
        })
    assert response.status_code == 409 and expense_store['budgetLimit'] == 300


def test_access_rejects_nonowner_and_package_trip(client, mock_traveller_auth, expense_store):
    assert client.get(URL).status_code == 401
    expense_store['travellerId'] = 'foreign'
    assert client.get(URL, headers=HEADERS).status_code == 404
    expense_store.update(travellerId='test_traveller_uid', packageTrip=True)
    assert client.get(URL, headers=HEADERS).status_code == 409
