"""Initial provisioning only, with mocked Auth/Firestore; no SDK initialization or live writes."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from google.api_core.exceptions import AlreadyExists

from scripts import create_admin


@pytest.fixture
def provisioning(monkeypatch):
    ref = Mock()
    ref.get.return_value = SimpleNamespace(exists=False)
    db = Mock()
    db.collection.return_value.document.return_value = ref
    monkeypatch.setattr(create_admin, 'get_db', lambda: db)
    lookup = Mock(return_value=SimpleNamespace(uid='synthetic-admin'))
    create = Mock(return_value=SimpleNamespace(uid='synthetic-admin'))
    monkeypatch.setattr(create_admin.auth, 'get_user_by_email', lookup)
    monkeypatch.setattr(create_admin.auth, 'create_user', create)
    return ref, lookup, create


def test_missing_profile_is_created_once_without_merge(provisioning):
    ref, _, create = provisioning
    create_admin.provision_admin('synthetic@example.invalid', 'synthetic-password')
    data = ref.create.call_args.args[0]
    assert data['role'] == 'admin' and data['uid'] == 'synthetic-admin' and data['status'] == 'active'
    ref.create.assert_called_once()
    ref.set.assert_not_called()
    ref.update.assert_not_called()
    create.assert_not_called()


def test_new_auth_identity_keeps_supported_initial_provisioning(provisioning):
    ref, lookup, create = provisioning
    lookup.side_effect = create_admin.auth.UserNotFoundError('Synthetic missing account')
    create_admin.provision_admin('synthetic@example.invalid', 'synthetic-password', 'Synthetic Administrator')
    create.assert_called_once_with(email='synthetic@example.invalid', password='synthetic-password', email_verified=True)
    assert ref.create.call_args.args[0]['name'] == 'Synthetic Administrator'


@pytest.mark.parametrize('role', ['traveller', 'operator', 'tourism_operator', None])
def test_existing_non_admin_is_never_converted(provisioning, role):
    ref, _, create = provisioning
    original = {'role': role, 'status': 'active', 'verificationHistory': ['preserved']}
    ref.get.return_value = SimpleNamespace(exists=True, to_dict=lambda: original)
    with pytest.raises(ValueError, match='cannot be converted'):
        create_admin.provision_admin('synthetic@example.invalid', 'synthetic-password')
    ref.create.assert_not_called()
    ref.set.assert_not_called()
    ref.update.assert_not_called()
    create.assert_not_called()
    assert original == {'role': role, 'status': 'active', 'verificationHistory': ['preserved']}


@pytest.mark.parametrize('role', ['admin', 'administrator'])
def test_existing_admin_is_idempotent_and_keeps_status_history_and_spelling(provisioning, role):
    ref, _, create = provisioning
    original = {'role': role, 'status': 'deactivated', 'createdAt': 'original', 'history': ['preserved']}
    ref.get.return_value = SimpleNamespace(exists=True, to_dict=lambda: original)
    create_admin.provision_admin('synthetic@example.invalid', 'synthetic-password')
    ref.create.assert_not_called()
    ref.set.assert_not_called()
    ref.update.assert_not_called()
    create.assert_not_called()
    assert original['role'] == role and original['status'] == 'deactivated' and original['history'] == ['preserved']


def test_concurrent_initial_profile_creation_fails_closed(provisioning):
    ref, _, _ = provisioning
    ref.create.side_effect = AlreadyExists('Synthetic concurrent registration')
    with pytest.raises(ValueError, match='concurrently'):
        create_admin.provision_admin('synthetic@example.invalid', 'synthetic-password')
    ref.set.assert_not_called()
    ref.update.assert_not_called()
