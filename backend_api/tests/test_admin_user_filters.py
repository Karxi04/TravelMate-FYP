"""Authorized user-list filters; synthetic data only and writes forbidden."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from modules.fr13_administrator_management import routes


ROWS = [
    {'id':'t-active', 'role':'traveller', 'status':'active', 'name':'Coastal Traveller'},
    {'id':'t-inactive', 'role':'traveller', 'status':'deactivated', 'name':'Hill Traveller'},
    {'id':'t-legacy', 'role':'TrAvElEr', 'name':'Historical Traveller'},
    {'id':'t-user', 'role':'USER', 'status':'active'},
    {'id':'o-active', 'role':'operator', 'status':'active', 'companyName':'Coastal Tours'},
    {'id':'o-inactive', 'role':'operator', 'status':'deactivated'},
    {'id':'o-alias', 'role':'ToUrIsM_OpErAtOr', 'status':' Active '},
    {'id':'a-active', 'role':'admin', 'status':'active', 'email':'coastal@example.invalid'},
    {'id':'a-inactive', 'role':'admin', 'status':'deactivated'},
    {'id':'a-alias', 'role':'AdMiNiStRaToR', 'status':'DEACTIVATED', 'clientSecret':'private-sentinel'},
]
ROLE_IDS = {'traveller':{'t-active','t-inactive','t-legacy','t-user'},
            'operator':{'o-active','o-inactive','o-alias'},
            'admin':{'a-active','a-inactive','a-alias'}}
STATUS_IDS = {'active':{'t-active','t-legacy','t-user','o-active','o-alias','a-active'},
              'deactivated':{'t-inactive','o-inactive','a-inactive','a-alias'}}
AUTH = {'Authorization':'Bearer synthetic-admin'}


@pytest.fixture
def user_records(monkeypatch):
    rows = deepcopy(ROWS)
    def read(collection, **kwargs):
        assert collection == 'users' and kwargs == {'limit':501}
        return rows
    retrieve = Mock(side_effect=read)
    monkeypatch.setattr(routes, 'retrieveRecord', retrieve)
    writes = [Mock(side_effect=AssertionError('User filtering cannot write records.')) for _ in range(3)]
    for name, spy in zip(('storeRecord','updateRecord','deleteRecord'), writes):
        monkeypatch.setattr(routes, name, spy)
    yield rows, retrieve
    assert rows == ROWS
    for spy in writes:
        spy.assert_not_called()


@pytest.mark.parametrize('role,expected_role', [(None,None),('',None),('all',None),(' ALL ',None),
    ('traveller','traveller'),('operator','operator'),('admin','admin'),
    ('ToUrIsM_OpErAtOr','operator'),('Administrator','admin'),('TrAvElEr','traveller'),('user','traveller')])
@pytest.mark.parametrize('status,expected_status', [(None,None),('',None),('all',None),('Active','active'),(' Deactivated ','deactivated')])
def test_all_role_status_combinations(client, mock_admin_auth, user_records, role, expected_role, status, expected_status):
    params = {k:v for k,v in {'role':role,'status':status}.items() if v is not None}
    result = client.get('/api/fr13/users', query_string=params, headers=AUTH)
    expected = set(row['id'] for row in ROWS)
    if expected_role:
        expected &= ROLE_IDS[expected_role]
    if expected_status:
        expected &= STATUS_IDS[expected_status]
    assert result.status_code == 200
    assert {row['id'] for row in result.json['items']} == expected
    assert result.json['recordLimit'] == 500
    assert 'private-sentinel' not in result.text


@pytest.mark.parametrize('role', ['all','traveller','operator','admin'])
@pytest.mark.parametrize('status', ['all','active','deactivated'])
def test_keyword_combines_with_role_status(client, mock_admin_auth, user_records, role, status):
    result = client.get('/api/fr13/users', query_string={'role':role,'status':status,'q':' COASTAL '}, headers=AUTH)
    expected = {'t-active','o-active','a-active'}
    if role != 'all':
        expected &= ROLE_IDS[role]
    if status != 'all':
        expected &= STATUS_IDS[status]
    assert result.status_code == 200 and {row['id'] for row in result.json['items']} == expected


def test_real_empty_result_and_sanitized_records(client, mock_admin_auth, user_records):
    result = client.get('/api/fr13/users?q=does-not-exist&role=all&status=all', headers=AUTH)
    assert result.status_code == 200 and result.json['items'] == []
    result = client.get('/api/fr13/users?role=administrator', headers=AUTH)
    assert all('clientSecret' not in row for row in result.json['items'])


@pytest.mark.parametrize('params', [{'role':'superuser'},{'status':'pending'},{'role':'null'},{'status':'disabled'}])
def test_invalid_filters_rejected_before_loading_users(client, mock_admin_auth, user_records, params):
    result = client.get('/api/fr13/users', query_string=params, headers=AUTH)
    assert result.status_code == 400 and 'Invalid' in result.json['error']
    user_records[1].assert_not_called()


@pytest.mark.parametrize('actor', ['traveller','operator'])
def test_user_filters_are_still_administrator_only(client, request, user_records, actor):
    request.getfixturevalue('mock_' + actor + '_auth')
    result = client.get('/api/fr13/users?role=all&status=all', headers=AUTH)
    assert result.status_code == 403
    user_records[1].assert_not_called()


def test_user_filters_require_authentication(client, user_records):
    assert client.get('/api/fr13/users?role=all&status=all').status_code == 401
    user_records[1].assert_not_called()
