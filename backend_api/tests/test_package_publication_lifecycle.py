from copy import deepcopy
from unittest.mock import patch

import pytest

from services.package_checkout_contract import prepare_package_snapshot
from services.package_service import normalise_package, package_validation_error
from services.public_content_projection import (
    PUBLIC_CAMPAIGN_COLLECTION,
    PUBLIC_PACKAGE_COLLECTION,
    eligible_package,
    public_package,
    sync_package,
)


AUTH = {'Authorization': 'Bearer valid_test_token'}
SUSPENSION_REASON = 'Safety information requires administrator review.'


def _package(status='approved', availability='available', **overrides):
    return {
        'id': 'pkg-lifecycle',
        'operatorId': 'test_operator_uid',
        'operatorName': 'Penang Tours',
        'approvalStatus': status,
        'availabilityStatus': availability,
        'schemaVersion': 2,
        'title': 'Penang Heritage Escape',
        'packageTitle': 'Penang Heritage Escape',
        'destination': 'George Town, Penang',
        'destinationName': 'George Town, Penang',
        'fullDescription': 'A guided Penang heritage experience.',
        'description': 'A guided Penang heritage experience.',
        'durationDays': 1,
        'durationNights': 0,
        'adultPrice': 100,
        'price': 100,
        'currency': 'MYR',
        'priceBasis': 'per_person',
        'itineraryDays': [{
            'title': 'Heritage day',
            'description': 'Explore George Town with a local guide.',
        }],
        **overrides,
    }


@pytest.mark.parametrize(
    ('status', 'availability', 'expected'),
    [
        ('draft', 'available', False),
        ('pending', 'available', False),
        ('approved', 'available', True),
        ('approved', 'unavailable', False),
        ('suspended', 'available', False),
    ],
)
def test_publication_matrix_requires_approved_and_available(status, availability, expected):
    assert eligible_package(_package(status, availability)) is expected


def test_new_package_default_is_intentionally_available_and_invalid_values_are_rejected(
    client, mock_operator_auth,
):
    payload = _package('draft')
    payload.pop('id')
    payload.pop('operatorId')
    payload.pop('approvalStatus')
    payload.pop('availabilityStatus')
    assert normalise_package(payload)['availabilityStatus'] == 'available'
    assert package_validation_error({**payload, 'availabilityStatus': 'hidden'}) == (
        'Availability status must be available or unavailable.'
    )

    with patch(
        'modules.fr12_tourism_operator_management.routes.retrieveRecord',
        return_value={'companyName': 'Penang Tours'},
    ), patch(
        'modules.fr12_tourism_operator_management.routes.storeRecord',
        side_effect=lambda _collection, data: {'id': 'new-package', **data},
    ):
        response = client.post('/api/fr12/packages', headers=AUTH, json=payload)
    assert response.status_code == 201
    assert response.get_json()['package']['availabilityStatus'] == 'available'


def test_admin_suspension_requires_admin_and_meaningful_reason(
    client, mock_traveller_auth,
):
    forbidden = client.post(
        '/api/fr13/packages/pkg-lifecycle/suspend', headers=AUTH,
        json={'reason': SUSPENSION_REASON},
    )
    assert forbidden.status_code == 403


def test_admin_suspension_records_audit_without_changing_content_or_availability(
    client, mock_admin_auth,
):
    current = _package()
    orders = [{'id': 'order-1', 'paymentStatus': 'paid', 'amount': 100}]
    trips = [{'id': 'trip-1', 'packageSnapshot': {'title': current['title'], 'price': 100}}]
    historical_state = deepcopy((orders, trips))
    with patch(
        'modules.fr13_administrator_management.routes.retrieveRecord',
        return_value=current,
    ), patch(
        'modules.fr13_administrator_management.routes.updateRecord',
    ) as update:
        update.side_effect = lambda _collection, _key, changes: {**current, **changes}
        response = client.post(
            '/api/fr13/packages/pkg-lifecycle/suspend', headers=AUTH,
            json={'reason': SUSPENSION_REASON},
        )

    assert response.status_code == 200
    body = response.get_json()
    assert body['status'] == 'suspended'
    assert body['idempotent'] is False
    assert body['package']['approvalStatus'] == 'suspended'
    assert body['package']['availabilityStatus'] == 'available'
    assert body['package']['title'] == current['title']
    changes = update.call_args.args[2]
    assert changes['suspensionReason'] == SUSPENSION_REASON
    assert changes['suspendedBy'] == 'test_admin_uid'
    assert changes['suspendedByName'] == 'Test Admin'
    assert changes['suspendedAt']
    assert (orders, trips) == historical_state


@pytest.mark.parametrize('reason', ['', 'short', 'x' * 501])
def test_admin_suspension_rejects_invalid_reason(client, mock_admin_auth, reason):
    with patch(
        'modules.fr13_administrator_management.routes.retrieveRecord',
        return_value=_package(),
    ), patch('modules.fr13_administrator_management.routes.updateRecord') as update:
        response = client.post(
            '/api/fr13/packages/pkg-lifecycle/suspend', headers=AUTH,
            json={'reason': reason},
        )
    assert response.status_code == 400
    update.assert_not_called()


def test_admin_suspension_rejects_invalid_transition(client, mock_admin_auth):
    with patch(
        'modules.fr13_administrator_management.routes.retrieveRecord',
        return_value=_package('pending'),
    ), patch('modules.fr13_administrator_management.routes.updateRecord') as update:
        response = client.post(
            '/api/fr13/packages/pkg-lifecycle/suspend', headers=AUTH,
            json={'reason': SUSPENSION_REASON},
        )
    assert response.status_code == 409
    update.assert_not_called()


def test_duplicate_suspension_is_idempotent_but_conflicting_reason_is_rejected(
    client, mock_admin_auth,
):
    suspended = _package(
        'suspended', suspensionReason=SUSPENSION_REASON,
        suspendedAt='2026-10-19T10:00:00+00:00', suspendedBy='original-admin',
    )
    with patch(
        'modules.fr13_administrator_management.routes.retrieveRecord',
        return_value=suspended,
    ), patch('modules.fr13_administrator_management.routes.updateRecord') as update:
        repeated = client.post(
            '/api/fr13/packages/pkg-lifecycle/suspend', headers=AUTH,
            json={'reason': SUSPENSION_REASON},
        )
        conflicting = client.post(
            '/api/fr13/packages/pkg-lifecycle/suspend', headers=AUTH,
            json={'reason': 'A different valid administrator reason.'},
        )
    assert repeated.status_code == 200
    assert repeated.get_json()['idempotent'] is True
    assert repeated.get_json()['package']['suspendedBy'] == 'original-admin'
    assert conflicting.status_code == 409
    update.assert_not_called()


def test_suspended_package_projection_is_removed(monkeypatch):
    deleted = []
    monkeypatch.delenv('TRAVELMATE_TESTING', raising=False)
    monkeypatch.setattr(
        'services.public_content_projection.deleteRecord',
        lambda collection, key: deleted.append((collection, key)),
    )
    monkeypatch.setattr(
        'services.public_content_projection.retrieveRecord',
        lambda collection, *args, **kwargs: (
            [{'id': 'campaign-1', 'packageId': 'pkg-lifecycle'}]
            if collection == 'promotional_campaigns' else []
        ),
    )

    sync_package('pkg-lifecycle', _package('suspended'))
    assert (PUBLIC_PACKAGE_COLLECTION, 'pkg-lifecycle') in deleted
    assert (PUBLIC_CAMPAIGN_COLLECTION, 'campaign-1') in deleted


def test_suspended_package_can_be_resubmitted_but_not_republished_by_operator(
    client, mock_operator_auth,
):
    suspended = _package(
        'suspended', suspensionReason=SUSPENSION_REASON,
        suspendedAt='2026-10-19T10:00:00+00:00',
    )
    with patch(
        'modules.fr12_tourism_operator_management.routes.retrieveRecord',
        return_value=suspended,
    ), patch(
        'modules.fr12_tourism_operator_management.routes.updateRecord',
        side_effect=lambda _collection, _key, changes: {**suspended, **changes},
    ):
        response = client.post(
            '/api/fr12/packages/pkg-lifecycle/submit', headers=AUTH,
        )
    assert response.status_code == 200
    package = response.get_json()['package']
    assert package['approvalStatus'] == 'pending'
    assert package['suspensionReason'] == SUSPENSION_REASON
    assert eligible_package(package) is False


def test_operator_cannot_delete_or_archive_an_admin_suspended_package(
    client, mock_operator_auth,
):
    suspended = _package('suspended', suspensionReason=SUSPENSION_REASON)
    with patch(
        'modules.fr12_tourism_operator_management.routes.retrieveRecord',
        return_value=suspended,
    ), patch('modules.fr12_tourism_operator_management.routes.deleteRecord') as delete, patch(
        'modules.fr12_tourism_operator_management.routes.updateRecord',
    ) as update:
        removed = client.delete('/api/fr12/packages/pkg-lifecycle', headers=AUTH)
        archived = client.post('/api/fr12/packages/pkg-lifecycle/archive', headers=AUTH)
    assert removed.status_code == 409
    assert archived.status_code == 409
    delete.assert_not_called()
    update.assert_not_called()


def test_admin_reapproval_preserves_operator_availability_and_resolves_audit(
    client, mock_admin_auth,
):
    pending = _package(
        'pending', 'unavailable', suspensionReason=SUSPENSION_REASON,
        suspendedAt='2026-10-19T10:00:00+00:00', suspendedBy='test_admin_uid',
    )
    with patch(
        'modules.fr13_administrator_management.routes.retrieveRecord',
        return_value=pending,
    ), patch(
        'modules.fr13_administrator_management.routes.updateRecord',
        side_effect=lambda _collection, _key, changes: {**pending, **changes},
    ):
        response = client.post(
            '/api/fr13/packages/pkg-lifecycle/review', headers=AUTH,
            json={'decision': 'approved', 'comment': 'Corrections verified.'},
        )
    assert response.status_code == 200
    package = response.get_json()['package']
    assert package['approvalStatus'] == 'approved'
    assert package['availabilityStatus'] == 'unavailable'
    assert package['suspensionResolvedBy'] == 'test_admin_uid'
    assert package['suspensionResolvedAt']
    assert eligible_package(package) is False


@pytest.mark.parametrize(
    ('availability', 'expected_public'),
    [('unavailable', False), ('available', True)],
)
def test_approved_availability_update_preserves_approval_and_controls_publication(
    client, mock_operator_auth, availability, expected_public,
):
    approved = _package('approved', 'available' if availability == 'unavailable' else 'unavailable')
    with patch(
        'modules.fr12_tourism_operator_management.routes.retrieveRecord',
        return_value=approved,
    ), patch(
        'modules.fr12_tourism_operator_management.routes.updateRecord',
    ) as update:
        update.side_effect = lambda _collection, _key, changes: {**approved, **changes}
        response = client.put(
            '/api/fr12/packages/pkg-lifecycle', headers=AUTH,
            json={'availabilityStatus': availability},
        )
    assert response.status_code == 200
    saved = response.get_json()['package']
    assert saved['approvalStatus'] == 'approved'
    assert saved['availabilityStatus'] == availability
    assert eligible_package(saved) is expected_public
    assert 'approvalStatus' not in update.call_args.args[2]


def test_full_operator_form_can_change_only_availability_without_forcing_review(
    client, mock_operator_auth,
):
    approved = _package()
    payload = {
        key: value for key, value in approved.items()
        if key not in {'id', 'operatorId', 'operatorName', 'approvalStatus'}
    }
    payload['availabilityStatus'] = 'unavailable'
    with patch(
        'modules.fr12_tourism_operator_management.routes.retrieveRecord',
        return_value=approved,
    ), patch(
        'modules.fr12_tourism_operator_management.routes.updateRecord',
        side_effect=lambda _collection, _key, changes: {**approved, **changes},
    ):
        response = client.put(
            '/api/fr12/packages/pkg-lifecycle', headers=AUTH, json=payload,
        )
    assert response.status_code == 200
    saved = response.get_json()['package']
    assert saved['approvalStatus'] == 'approved'
    assert saved['availabilityStatus'] == 'unavailable'


def test_reviewed_content_change_still_returns_approved_package_to_draft(
    client, mock_operator_auth,
):
    approved = _package()
    with patch(
        'modules.fr12_tourism_operator_management.routes.retrieveRecord',
        return_value=approved,
    ), patch(
        'modules.fr12_tourism_operator_management.routes.updateRecord',
        side_effect=lambda _collection, _key, changes: {**approved, **changes},
    ):
        response = client.put(
            '/api/fr12/packages/pkg-lifecycle', headers=AUTH,
            json={'adultPrice': 120},
        )
    assert response.status_code == 200
    assert response.get_json()['package']['approvalStatus'] == 'draft'


def test_suspended_package_cannot_start_new_checkout_and_penang_identity_is_preserved():
    suspended = _package('suspended')
    before = deepcopy(suspended)
    with pytest.raises(ValueError, match='not approved and available'):
        prepare_package_snapshot(suspended, {'id': 'test_operator_uid'})
    assert suspended == before

    projection = public_package(_package())
    assert projection['destination'] == 'George Town, Penang'
    assert projection['destinationName'] == 'George Town, Penang'
