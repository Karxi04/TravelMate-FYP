"""Immutable registered-role controls and permitted management payloads, with mocked Backend only."""
import re
from unittest.mock import MagicMock

import pytest

from test_admin_commerce_presentation import auth_client, _patch_view_api


def response(payload=None):
    result = MagicMock(ok=True, status_code=200)
    result.json.return_value = payload or {'ok': True}
    return result


@pytest.mark.parametrize('role,label', [('traveller', 'Traveller'), ('operator', 'Tourism Operator'),
                                      ('admin', 'Administrator'), ('tourism_operator', 'Tourism Operator'),
                                      ('administrator', 'Administrator')])
def test_registered_role_is_a_badge_not_a_form_field(auth_client, role, label):
    result = response({'items': [{'id': 'target', 'name': 'Synthetic Account', 'role': role,
                                  'status': 'active', 'verificationStatus': 'pending'}]})
    with _patch_view_api('admin_fr13.users', MagicMock(return_value=result)):
        page = auth_client.get('/admin/users')
    assert page.status_code == 200
    form = re.search(r'<form\b[^>]*action="/admin/users/target/update"[^>]*>(.*?)</form>', page.text, re.S).group(1)
    assert re.search(r'aria-label="Registered role">\s*' + re.escape(label) + r'\s*</span>', form)
    assert not re.search(r'<(?:select|input)\b[^>]*name="role"', form)
    assert 'name="status"' in form and '>Save</button>' in form
    assert ('name="verificationStatus"' in form) == (role in {'operator', 'tourism_operator'})
    assert 'aria-label="Filter by role"' in page.text  # Read-only account roles do not remove search filters.
    assert 'manage permission roles' not in page.text and 'roles cannot be changed' in page.text


@pytest.mark.parametrize('fields', [{'status': 'active'}, {'status': 'deactivated'},
                                   {'verificationStatus': 'pending'}, {'verificationStatus': 'approved'},
                                   {'verificationStatus': 'rejected'}, {'status': 'active', 'verificationStatus': 'approved'}])
def test_management_form_forwards_only_allowed_fields(auth_client, fields):
    api = MagicMock(return_value=response())
    with _patch_view_api('admin_fr13.update_user', api):
        result = auth_client.post('/admin/users/target/update', data={**fields, 'uid': 'not-target', 'customClaims': 'ignored'})
    assert result.status_code == 302
    api.assert_called_once_with('PUT', '/api/fr13/users/target', json=fields)


@pytest.mark.parametrize('role', ['traveller', 'operator', 'admin'])
def test_tampered_role_form_is_rejected_before_backend_request(auth_client, role):
    api = MagicMock()
    with _patch_view_api('admin_fr13.update_user', api):
        result = auth_client.post('/admin/users/target/update', data={'role': role, 'status': 'deactivated'})
    assert result.status_code == 409 and 'roles cannot be changed' in result.text
    api.assert_not_called()


def test_user_search_and_role_status_filters_still_forward(auth_client):
    api = MagicMock(return_value=response({'items': []}))
    with _patch_view_api('admin_fr13.users', api):
        assert auth_client.get('/admin/users?q=Synthetic&role=operator&status=active').status_code == 200
    api.assert_called_once_with('GET', '/api/fr13/users', params={'q': 'Synthetic', 'role': 'operator', 'status': 'active'})


def test_non_admin_account_update_is_denied_before_proxy(auth_client):
    with auth_client.session_transaction() as session:
        session['portal_role'] = 'traveller'
    api = MagicMock()
    with _patch_view_api('admin_fr13.update_user', api):
        result = auth_client.post('/admin/users/target/update', data={'status': 'active'})
    assert result.status_code == 302
    api.assert_not_called()
