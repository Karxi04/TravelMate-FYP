import pytest
from contextlib import contextmanager
from unittest.mock import patch, MagicMock
from modules.fr12_tourism_operator_management.analytics_service import generate_business_analytics
from services.package_service import package_for_read


@contextmanager
def operator_auth_status(status):
    profile = {
        'uid': 'test_operator_uid',
        'email': 'operator@test.com',
        'role': 'operator',
        'status': 'active',
        'verificationStatus': status,
    }
    snap = MagicMock(exists=True)
    snap.to_dict.return_value = profile
    db = MagicMock()
    db.collection.return_value.document.return_value.get.return_value = snap
    with patch('auth_utils.auth.verify_id_token', return_value={'uid': 'test_operator_uid'}), \
         patch('auth_utils.get_db', return_value=db):
        yield


@pytest.mark.parametrize('verification_status', ['pending', 'rejected'])
def test_unverified_operator_is_denied(client, verification_status):
    with operator_auth_status(verification_status):
        response = client.get(
            '/api/fr12/packages',
            headers={'Authorization': 'Bearer valid_test_token'},
        )
    assert response.status_code == 403
    assert 'not verified' in response.get_json()['error']


def test_admin_operator_override_remains_allowed(client, mock_admin_auth):
    with patch(
        'modules.fr12_tourism_operator_management.routes.retrieveRecord',
        return_value=[],
    ):
        response = client.get(
            '/api/fr12/packages',
            headers={'Authorization': 'Bearer valid_test_token'},
        )
    assert response.status_code == 200

def test_operator_packages_crud(client, mock_operator_auth):
    sample_pkg = {
        'packageTitle': 'Penang Heritage Walking Tour',
        'destinationName': 'George Town',
        'price': 150.0,
        'durationDays': 1,
        'maxTravellers': 10,
    }
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord') as mock_retrieve, \
         patch('modules.fr12_tourism_operator_management.routes.storeRecord') as mock_store:
        mock_retrieve.return_value = {'companyName': 'Penang Tours Sdn Bhd'}
        mock_store.side_effect = lambda coll, data: {'id': 'pkg_001', **data}

        res = client.post(
            '/api/fr12/packages',
            headers={'Authorization': 'Bearer valid_test_token'},
            json=sample_pkg
        )
        assert res.status_code == 201
        data = res.get_json()
        assert data['ok'] is True
        assert data['package']['packageTitle'] == 'Penang Heritage Walking Tour'
        assert data['package']['operatorId'] == 'test_operator_uid'
        assert data['package']['approvalStatus'] == 'draft'

def test_operator_analytics_data_isolation():
    """Verify that bookings without operatorId or belonging to other operators do not leak."""
    mock_db = MagicMock()
    
    # Mock packages
    pkg_doc = MagicMock()
    pkg_doc.id = 'pkg_1'
    pkg_doc.to_dict.return_value = {
        'operatorId': 'op_alpha',
        'packageTitle': 'Op Alpha Package',
        'price': 100.0,
        'approvalStatus': 'approved'
    }
    mock_db.collection.return_value.where.return_value.stream.return_value = [pkg_doc]

    # Mock hotel_bookings: 1 belongs to op_alpha, 1 belongs to op_beta, 1 has no operatorId
    b1 = MagicMock()
    b1.id = 'b_alpha'
    b1.to_dict.return_value = {'operatorId': 'op_alpha', 'totalAmount': 200.0}

    b2 = MagicMock()
    b2.id = 'b_beta'
    b2.to_dict.return_value = {'operatorId': 'op_beta', 'totalAmount': 300.0}

    b3 = MagicMock()
    b3.id = 'b_generic'
    b3.to_dict.return_value = {'hotelName': 'General Hotel', 'totalAmount': 150.0} # No operatorId

    def mock_collection(name):
        coll_mock = MagicMock()
        if name == 'hotel_bookings':
            coll_mock.stream.return_value = [b1, b2, b3]
        elif name in ('tourism_packages', 'promotional_campaigns'):
            coll_mock.where.return_value.stream.return_value = [pkg_doc] if name == 'tourism_packages' else []
            coll_mock.stream.return_value = [pkg_doc] if name == 'tourism_packages' else []
        return coll_mock

    mock_db.collection.side_effect = mock_collection

    # Run for op_alpha
    report = generate_business_analytics(mock_db, operator_id='op_alpha')

    # Must ONLY have 1 booking (b_alpha)
    assert report['summary']['bookingRecords'] == 1
    assert len(report['bookings']) == 1
    assert report['bookings'][0]['id'] == 'b_alpha'
    assert report['summary']['totalPackages'] == 1
    assert report['summary']['approvedPackages'] == 1

def test_operator_package_submission(client, mock_operator_auth):
    sample_pkg = {
        'id': 'pkg_100',
        'operatorId': 'test_operator_uid',
        'packageTitle': 'Kek Lok Si Temple Tour',
        'destinationName': 'Air Itam',
        'price': 80.0,
        'durationDays': 1,
        'maxTravellers': 15,
        'validFrom': '2026-10-01',
        'validUntil': '2026-10-10',
        'description': 'Guided temple visit with scenic viewpoint photography.',
        'approvalStatus': 'draft'
    }
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord') as mock_retrieve, \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord') as mock_update:
        mock_retrieve.return_value = sample_pkg
        mock_update.side_effect = lambda coll, doc_id, data: {**sample_pkg, **data}

        res = client.post(
            '/api/fr12/packages/pkg_100/submit',
            headers={'Authorization': 'Bearer valid_test_token'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert data['status'] == 'pending'
        assert data['package']['approvalStatus'] == 'pending'

def test_operator_campaign_requires_approved_package(client, mock_operator_auth):
    draft_pkg = {
        'id': 'pkg_draft',
        'operatorId': 'test_operator_uid',
        'packageTitle': 'Draft Tour',
        'approvalStatus': 'draft'
    }
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord') as mock_retrieve:
        mock_retrieve.return_value = draft_pkg

        res = client.post(
            '/api/fr12/campaigns',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={
                'campaignTitle': 'Early Bird Promo',
                'description': 'Special discount for holiday season',
                'startDate': '2026-10-01',
                'endDate': '2026-10-15',
                'packageId': 'pkg_draft'
            }
        )
        assert res.status_code == 409
        assert 'requires an approved package' in res.get_json()['error']


def test_package_v2_validation_rejects_bad_itinerary_and_promotion(client, mock_operator_auth):
    base = {
        'schemaVersion': 2, 'title': 'Penang Escape', 'destination': 'Penang',
        'fullDescription': 'A complete local package.', 'durationDays': 2,
        'adultPrice': 100, 'currency': 'MYR',
    }
    bad_day = client.post('/api/fr12/packages', headers={'Authorization': 'Bearer valid_test_token'},
                          json={**base, 'itineraryDays': [{'title': '', 'description': 'Arrival'}]})
    assert bad_day.status_code == 400
    assert bad_day.get_json()['error'] == 'Each itinerary day needs a title and description.'
    bad_price = client.post('/api/fr12/packages', headers={'Authorization': 'Bearer valid_test_token'},
                            json={**base, 'originalPrice': 80, 'promotionalPrice': 90})
    assert bad_price.status_code == 400
    assert 'cannot exceed' in bad_price.get_json()['error']


def test_package_v2_ownership_approved_edit_and_archive(client, mock_operator_auth):
    approved = {
        'id': 'pkg_v2', 'operatorId': 'test_operator_uid', 'approvalStatus': 'approved',
        'schemaVersion': 2, 'title': 'Penang Escape', 'destination': 'Penang',
        'fullDescription': 'A complete local package.', 'durationDays': 2,
        'adultPrice': 100, 'currency': 'MYR',
        'itineraryDays': [{'title': 'Arrival', 'description': 'Meet the guide.'}],
    }
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value=approved), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord') as update:
        update.side_effect = lambda collection, document_id, data: {**approved, **data}
        edited = client.put('/api/fr12/packages/pkg_v2', headers={'Authorization': 'Bearer valid_test_token'},
                            json={'adultPrice': 120})
        assert edited.status_code == 200
        assert edited.get_json()['package']['approvalStatus'] == 'draft'
        archived = client.post('/api/fr12/packages/pkg_v2/archive',
                               headers={'Authorization': 'Bearer valid_test_token'})
        assert archived.status_code == 200
        assert archived.get_json()['package']['approvalStatus'] == 'archived'

    other = {**approved, 'operatorId': 'another_operator'}
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value=other):
        denied = client.put('/api/fr12/packages/pkg_v2',
                            headers={'Authorization': 'Bearer valid_test_token'}, json={'adultPrice': 120})
    assert denied.status_code == 404

    draft = {**approved, 'approvalStatus': 'draft'}
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value=draft), \
         patch('modules.fr12_tourism_operator_management.routes.deleteRecord') as delete:
        removed = client.delete('/api/fr12/packages/pkg_v2',
                                headers={'Authorization': 'Bearer valid_test_token'})
    assert removed.status_code == 200
    delete.assert_called_once_with('tourism_packages', 'pkg_v2')


def test_legacy_package_remains_readable_with_v2_aliases():
    item = package_for_read({
        'id': 'legacy', 'packageTitle': 'Legacy Tour', 'destinationName': 'Penang',
        'description': 'Existing package', 'price': 88, 'durationDays': 1,
    })
    assert item['title'] == 'Legacy Tour'
    assert item['destination'] == 'Penang'
    assert item['fullDescription'] == 'Existing package'
    assert item['adultPrice'] == 88


def test_approved_campaign_edit_returns_to_review(client, mock_operator_auth):
    campaign = {
        'id': 'campaign_v2', 'operatorId': 'test_operator_uid',
        'campaignTitle': 'Early bird', 'packageId': 'approved_package',
        'description': 'Save on a local experience.', 'reviewStatus': 'approved',
        'campaignStatus': 'active', 'startDate': '2026-12-01', 'endDate': '2026-12-31',
    }
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value=campaign), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord') as update:
        update.side_effect = lambda collection, document_id, data: {**campaign, **data}
        response = client.put('/api/fr12/campaigns/campaign_v2',
                              headers={'Authorization': 'Bearer valid_test_token'},
                              json={'description': 'Updated promotion.'})
    assert response.status_code == 200
    saved = response.get_json()['campaign']
    assert saved['reviewStatus'] == 'draft'
    assert saved['campaignStatus'] == 'draft'
