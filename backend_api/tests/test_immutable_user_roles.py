"""Role integrity through actual routes/auth middleware using synthetic in-memory accounts."""
from copy import deepcopy
from itertools import permutations
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from modules.fr13_administrator_management import routes
from sequence_contract.validators import validateAccountAction


@pytest.fixture
def accounts(monkeypatch):
    import auth_utils
    state = {'manager': {'id': 'manager', 'uid': 'manager', 'role': 'admin', 'status': 'active'},
             'target': {'id': 'target', 'uid': 'target', 'role': 'traveller', 'status': 'active',
                        'verificationHistory': [{'decision': 'registered'}]}}
    def verify(token, **kwargs):
        return {'uid': token, 'email': 'synthetic@example.invalid', 'role': 'admin'}
    def snapshot(uid):
        return SimpleNamespace(exists=uid in state, to_dict=lambda: deepcopy(state.get(uid)))
    def collection(name):
        assert name == 'users'
        return SimpleNamespace(document=lambda uid: SimpleNamespace(get=lambda: snapshot(uid)))
    monkeypatch.setattr(auth_utils.auth, 'verify_id_token', verify)
    monkeypatch.setattr(auth_utils, 'get_db', lambda: SimpleNamespace(collection=collection))
    def retrieve(collection, uid=None, limit=None, **kwargs):
        assert collection == 'users'
        return deepcopy(state.get(uid)) if uid else deepcopy(list(state.values())[:limit])
    def update(collection, uid, updates, expected=None):
        assert collection == 'users' and 'role' not in updates
        assert expected == state[uid]
        state[uid].update(deepcopy(updates))
        return deepcopy(state[uid])
    write = Mock(side_effect=update)
    identity_write = Mock()
    monkeypatch.setattr(routes, 'retrieveRecord', retrieve)
    monkeypatch.setattr(routes, 'updateRecord', write)
    monkeypatch.setattr(routes.auth, 'update_user', identity_write)
    return state, write, identity_write


def headers(uid='manager'):
    return {'Authorization': 'Bearer ' + uid}


@pytest.mark.parametrize('original,requested', list(permutations(['traveller', 'operator', 'admin'], 2)))
def test_all_six_cross_role_transitions_rejected_without_any_write(client, accounts, original, requested):
    state, write, identity_write = accounts
    state['target']['role'] = original
    before = deepcopy(state)
    result = client.put('/api/fr13/users/target', headers=headers(), json={'role': requested, 'status': 'deactivated'})
    assert result.status_code == 409 and 'cannot be changed' in result.json['error']
    assert state == before
    write.assert_not_called()
    identity_write.assert_not_called()


@pytest.mark.parametrize('role', ['traveller', 'operator', 'admin', 'tourism_operator', 'administrator'])
def test_same_role_echo_is_a_read_only_noop(client, accounts, role):
    state, write, identity_write = accounts
    state['target']['role'] = role
    before = deepcopy(state)
    result = client.put('/api/fr13/users/target', headers=headers(), json={'role': role})
    assert result.status_code == 200 and result.json['user']['role'] == role
    assert state == before
    write.assert_not_called()
    identity_write.assert_not_called()


@pytest.mark.parametrize('role', ['traveller', 'operator', 'admin', 'tourism_operator', 'administrator'])
def test_deactivate_reactivate_and_fresh_auth_keep_registered_role(client, accounts, role):
    state, write, identity_write = accounts
    state['target']['role'] = role
    history = deepcopy(state['target']['verificationHistory'])
    for status in ['deactivated', 'active']:
        result = client.put('/api/fr13/users/target', headers=headers(), json={'status': status, 'role': role})
        assert result.status_code == 200 and result.json['user']['role'] == role
        assert 'role' not in write.call_args.args[2]
        identity_write.assert_called_with('target', disabled=status == 'deactivated')
        signed_in = client.get('/api/fr1/me', headers=headers('target'))
        assert signed_in.status_code == (403 if status == 'deactivated' else 200)
        if status == 'active':
            assert signed_in.json['profile']['role'] == role
    assert state['target']['verificationHistory'] == history


@pytest.mark.parametrize('role', ['operator', 'tourism_operator'])
@pytest.mark.parametrize('verification', ['pending', 'approved', 'rejected', 'verified'])
def test_verification_uses_stored_operator_role_and_preserves_history(client, accounts, role, verification):
    state, write, identity_write = accounts
    state['target'].update(role=role, verificationStatus='pending')
    history = deepcopy(state['target']['verificationHistory'])
    result = client.put('/api/fr13/users/target', headers=headers(), json={'verificationStatus': verification})
    assert result.status_code == 200
    assert state['target']['role'] == role and state['target']['verificationStatus'] == verification
    assert state['target']['verificationHistory'] == history and 'role' not in write.call_args.args[2]
    identity_write.assert_not_called()


@pytest.mark.parametrize('role', ['traveller', 'admin'])
@pytest.mark.parametrize('verification', ['pending', 'approved', 'rejected'])
def test_non_operators_cannot_receive_operator_verification(client, accounts, role, verification):
    state, write, identity_write = accounts
    state['target']['role'] = role
    before = deepcopy(state)
    result = client.put('/api/fr13/users/target', headers=headers(), json={'verificationStatus': verification})
    assert result.status_code == 400 and state == before
    write.assert_not_called()
    identity_write.assert_not_called()


@pytest.mark.parametrize('payload', [{'status': 'deactivated'}, {'role': 'traveller'}, {'role': 'operator'}])
def test_administrator_cannot_deactivate_or_change_self(client, accounts, payload):
    state, write, identity_write = accounts
    before = deepcopy(state)
    assert client.put('/api/fr13/users/manager', headers=headers(), json=payload).status_code == 409
    assert state == before
    write.assert_not_called()
    identity_write.assert_not_called()


@pytest.mark.parametrize('actor', ['traveller', 'operator', None])
def test_non_admin_updates_rejected_even_with_forged_token_role(client, accounts, actor):
    state, write, identity_write = accounts
    state['target']['role'] = actor or 'traveller'
    result = client.put('/api/fr13/users/manager', headers=headers('target') if actor else {}, json={'status': 'deactivated'})
    assert result.status_code == (403 if actor else 401)
    write.assert_not_called()
    identity_write.assert_not_called()


@pytest.mark.parametrize('payload', [{}, None, [], {'role': 'admin'}, {'status': []}, {'verificationStatus': {}},
                                    {'status': 'active', 'customClaims': {'admin': True}}])
def test_account_validator_fails_closed_without_stored_role_or_for_invalid_fields(payload):
    assert not validateAccountAction(payload)


def test_search_role_filter_and_status_filter_remain_available(client, accounts):
    state, _, _ = accounts
    state['target'].update(role='operator', name='Synthetic Tours', status='deactivated')
    result = client.get('/api/fr13/users?q=Synthetic&role=operator&status=deactivated', headers=headers())
    assert result.status_code == 200 and [row['id'] for row in result.json['items']] == ['target']
    assert client.get('/api/fr13/users?role=traveller', headers=headers()).json['items'] == []


@pytest.mark.parametrize('role,requested', list(permutations(['traveller', 'operator', 'admin'], 2)))
def test_profile_registration_replay_cannot_convert_existing_role(client, accounts, monkeypatch, role, requested):
    from modules.fr01_user_management import routes as profile
    state, _, _ = accounts
    state['target']['role'] = role
    monkeypatch.setattr(profile, 'retrieveRecord', lambda *_: deepcopy(state['target']))
    write = Mock()
    monkeypatch.setattr(profile, 'updateRecord', write)
    before = deepcopy(state)
    response = client.post('/api/fr1/profile', headers=headers('target'), json={
        'name': 'Synthetic', 'role': requested, 'companyName': 'Synthetic Tours', 'registrationNo': 'FIXTURE'})
    assert response.status_code == 409 and state == before
    write.assert_not_called()


def test_concurrent_initial_registration_cannot_overwrite_first_role(client, accounts, monkeypatch):
    from modules.fr01_user_management import routes as profile
    state, _, _ = accounts
    monkeypatch.setattr(profile, 'retrieveRecord', lambda *_: None)
    claim = Mock(return_value=({'id': 'target', 'role': 'traveller'}, False))
    monkeypatch.setattr(profile, 'claimRecord', claim)
    before = deepcopy(state)
    result = client.post('/api/fr1/profile', headers=headers('target'), json={
        'name': 'Synthetic', 'role': 'operator', 'companyName': 'Synthetic Tours', 'registrationNo': 'FIXTURE'})
    assert result.status_code == 409 and state == before
    claim.assert_called_once()
    assert claim.call_args.args[0:2] == ('users', 'target')


@pytest.mark.parametrize('role', ['traveller', 'operator', 'admin'])
def test_profile_edit_updates_personal_fields_without_role_write(client, accounts, monkeypatch, role):
    from modules.fr01_user_management import routes as profile
    state, _, _ = accounts
    state['target']['role'] = role
    monkeypatch.setattr(profile, 'retrieveRecord', lambda *_: deepcopy(state['target']))
    def update(collection, uid, data, expected):
        assert 'role' not in data and expected == state[uid]
        state[uid].update(data)
        return deepcopy(state[uid])
    monkeypatch.setattr(profile, 'updateRecord', update)
    result = client.post('/api/fr1/profile', headers=headers('target'), json={'name': 'Edited Synthetic'})
    assert result.status_code == 200 and state['target']['role'] == role


@pytest.mark.parametrize('role,requested', list(permutations(['traveller', 'operator', 'admin'], 2)))
def test_personal_profile_put_rejects_role_conversion(client, accounts, monkeypatch, role, requested):
    from modules.fr01_user_management import routes as profile
    state, _, _ = accounts
    state['target']['role'] = role
    write = Mock()
    monkeypatch.setattr(profile, 'updateRecord', write)
    assert client.put('/api/fr1/me', headers=headers('target'), json={'role': requested}).status_code == 409
    write.assert_not_called()
