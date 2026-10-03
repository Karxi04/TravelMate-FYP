import pytest
from unittest.mock import patch, MagicMock
from modules.fr12_tourism_operator_management.analytics_service import generate_business_analytics

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
