"""Actual Administrator route/template filtering with a mocked read-only Backend."""
import re
from unittest.mock import MagicMock

import pytest

from test_admin_commerce_presentation import auth_client, _patch_view_api


def backend_response(ok=True, status=200):
    result = MagicMock(ok=ok, status_code=status)
    result.json.return_value = {'ok':ok,'items':[], 'error':'private-sentinel'}
    return result


def selected(html, name, value):
    select = re.search(r'<select\b[^>]*aria-label="Filter by ' + name + r'"[^>]*>(.*?)</select>', html, re.S).group(1)
    assert re.search(r'<option value="' + value + r'"\s+selected', select)


@pytest.mark.parametrize('role', ['all','traveller','operator','admin'])
@pytest.mark.parametrize('status', ['all','active','deactivated'])
def test_role_status_and_keyword_filters_stay_selected(auth_client, role, status):
    api = MagicMock(return_value=backend_response())
    with _patch_view_api('admin_fr13.users', api):
        result = auth_client.get('/admin/users', query_string={'role':role,'status':status,'q':' Coastal '})
    assert result.status_code == 200
    selected(result.text, 'role', role)
    selected(result.text, 'status', status)
    assert 'name="q" value="Coastal"' in result.text
    params = {'q':'Coastal', **({'role':role} if role != 'all' else {}), **({'status':status} if status != 'all' else {})}
    api.assert_called_once_with('GET','/api/fr13/users',params=params)
    assert 'No people match this view.' in result.text


@pytest.mark.parametrize('alias,canonical', [('ToUrIsM_OpErAtOr','operator'),('Administrator','admin'),('TrAvElEr','traveller'),('USER','traveller')])
def test_aliases_and_case_are_canonicalized_for_selection(auth_client, alias, canonical):
    api = MagicMock(return_value=backend_response())
    with _patch_view_api('admin_fr13.users', api):
        result = auth_client.get('/admin/users',query_string={'role':alias,'status':' ACTIVE '})
    selected(result.text,'role',canonical)
    selected(result.text,'status','active')
    api.assert_called_once_with('GET','/api/fr13/users',params={'role':canonical,'status':'active'})


def test_reset_clears_keyword_role_and_status(auth_client):
    api = MagicMock(return_value=backend_response())
    with _patch_view_api('admin_fr13.users', api):
        filtered = auth_client.get('/admin/users?q=Coastal&role=operator&status=deactivated')
        href = re.search(r'href="([^"]+)">Reset Filters</a>',filtered.text).group(1)
        assert href == '/admin/users'
        api.reset_mock()
        reset = auth_client.get(href)
    api.assert_called_once_with('GET','/api/fr13/users',params={})
    selected(reset.text,'role','all')
    selected(reset.text,'status','all')
    assert 'name="q" value=""' in reset.text


@pytest.mark.parametrize('suffix', ['', '?role=all&status=all', '?role=&status=', '?role=ALL&status=ALL'])
def test_all_filters_are_omitted_from_backend_request(auth_client, suffix):
    api = MagicMock(return_value=backend_response())
    with _patch_view_api('admin_fr13.users',api):
        result = auth_client.get('/admin/users'+suffix)
    assert result.status_code == 200
    api.assert_called_once_with('GET','/api/fr13/users',params={})


@pytest.mark.parametrize('code',[400,500,503])
def test_backend_error_is_not_an_empty_result(auth_client, code):
    api = MagicMock(return_value=backend_response(False,code))
    with _patch_view_api('admin_fr13.users',api):
        result = auth_client.get('/admin/users?q=Coastal&role=operator&status=active')
    assert result.status_code == code
    assert 'temporarily unavailable' in result.text and 'role="alert"' in result.text
    assert 'No people match this view.' not in result.text and 'private-sentinel' not in result.text
    selected(result.text,'role','operator')
    selected(result.text,'status','active')
    assert 'name="q" value="Coastal"' in result.text
