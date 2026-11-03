from unittest.mock import patch, MagicMock
from copy import deepcopy
import pytest
from test_fr12_operator import commerce_read_only_guard


def _s1_hotel_order(**changes):
    return {
        'id': 's1-hotel-order', 'quoteType': 'hotel', 'bookingId': 's1-hotel-booking',
        'amount': 180, 'currency': 'MYR', 'paymentStatus': 'paid', 'status': 'paid',
        'provider': 'stripe_checkout_test', 'paidAt': '2026-11-01T12:00:00Z',
        'createdAt': '2026-11-01T11:00:00Z', 'fulfillmentStatus': 'demo_only',
        'supplierBookingStatus': 'not_created', 'stripePaymentIntentId': 'pi_synthetic_hotel',
        'checkoutUrl': 'private-checkout', 'clientSecret': 'private-client',
        'quoteSnapshot': {'hotelId': 's1-hotel', 'name': 'Synthetic Hotel', 'clientSecret': 'private-nested'},
        **changes,
    }


def test_s1_admin_hotel_filter_is_read_only_and_preserves_separate_statuses(client, mock_admin_auth):
    orders = [_s1_hotel_order(), {
        'id': 's1-package', 'quoteType': 'package', 'paymentStatus': 'paid',
        'packageSnapshot': {'title': 'Synthetic package', 'accommodation': {'hotelId': 's1-hotel'}},
    }]
    legacy = [{'id': 'mirror', 'orderReference': 's1-hotel-order', 'productType': 'hotel', 'amount': 180}]
    before = deepcopy((orders, legacy))
    with commerce_read_only_guard(), patch('modules.fr13_administrator_management.routes.retrieveRecord',
            side_effect=lambda coll, **kw: orders if coll == 'checkout_orders' else legacy) as read:
        response = client.get('/api/fr13/payments?product=hotel&status=paid', headers={'Authorization': 'Bearer test'})
    assert response.status_code == 200
    assert len(response.json['items']) == 1
    item = response.json['items'][0]
    assert item['id'] == 's1-hotel-order' and item['bookingId'] == 's1-hotel-booking'
    assert item['productType'] == 'hotel' and item['amount'] == 180 and item['currency'] == 'MYR'
    assert item['isPaid'] is True and item['testMode'] is True
    assert item['paidAt'] == orders[0]['paidAt']
    assert item['supplierBookingStatus'] == 'not_created' and item['fulfillmentStatus'] == 'demo_only'
    assert item['quoteSnapshot'] == {'hotelId': 's1-hotel', 'name': 'Synthetic Hotel'}
    assert 'private-' not in response.get_data(as_text=True)
    assert (orders, legacy) == before
    assert [(c.args[0], c.kwargs) for c in read.call_args_list] == [
        ('checkout_orders', {'limit': 501}), ('payment_records', {'limit': 501})]


def test_s1_admin_legacy_classification_and_unknown_values_are_not_invented(client, mock_admin_auth):
    records = [{'id': 'unclassified', 'hotelName': 'Ambiguous legacy property'},
               {'id': 'explicit-hotel', 'productType': 'hotel', 'amount': None, 'currency': ''}]
    before = deepcopy(records)
    with commerce_read_only_guard(), patch('modules.fr13_administrator_management.routes.retrieveRecord',
            side_effect=lambda coll, **kw: [] if coll == 'checkout_orders' else records):
        all_records = client.get('/api/fr13/payments', headers={'Authorization': 'Bearer test'}).json['items']
        hotel = client.get('/api/fr13/payments?product=hotel', headers={'Authorization': 'Bearer test'}).json['items']
    assert {x['id']: x['productType'] for x in all_records} == {
        'unclassified': 'legacy_payment', 'explicit-hotel': 'hotel'}
    assert len(hotel) == 1 and hotel[0]['id'] == 'explicit-hotel'
    assert hotel[0]['amount'] is None and hotel[0]['currency'] == 'UNKNOWN'
    assert 'paidAt' not in hotel[0] and records == before


@pytest.mark.parametrize('role', ['anonymous', 'traveller', 'operator'])
def test_s1_admin_payments_reject_non_admin_roles(client, request, role):
    if role != 'anonymous':
        request.getfixturevalue('mock_' + role + '_auth')
    with commerce_read_only_guard(), patch('modules.fr13_administrator_management.routes.retrieveRecord') as read:
        response = client.get('/api/fr13/payments?product=hotel',
                              headers={} if role == 'anonymous' else {'Authorization': 'Bearer test'})
    assert response.status_code == (401 if role == 'anonymous' else 403)
    read.assert_not_called()


def test_s1_admin_payments_empty_cap_and_invalid_dates(client, mock_admin_auth):
    with commerce_read_only_guard(), patch('modules.fr13_administrator_management.routes.retrieveRecord', return_value=[]):
        response = client.get('/api/fr13/payments?product=hotel', headers={'Authorization': 'Bearer test'})
    assert response.json == {'ok': True, 'items': [], 'dataLimited': False, 'recordLimit': 500}
    orders = [_s1_hotel_order(id=f's1-{i}', stripePaymentIntentId=f'pi_synthetic_{i}') for i in range(501)]
    with commerce_read_only_guard(), patch('modules.fr13_administrator_management.routes.retrieveRecord',
            side_effect=lambda coll, **kw: orders if coll == 'checkout_orders' else []):
        response = client.get('/api/fr13/payments?product=hotel', headers={'Authorization': 'Bearer test'})
    assert len(response.json['items']) == 500 and response.json['dataLimited'] is True
    with commerce_read_only_guard(), patch('modules.fr13_administrator_management.routes.retrieveRecord') as read:
        response = client.get('/api/fr13/payments?startDate=bad-date', headers={'Authorization': 'Bearer test'})
    assert response.status_code == 400
    read.assert_not_called()


def test_s1_admin_payments_storage_failure_is_unavailable_not_empty_or_leaked(client, mock_admin_auth):
    with commerce_read_only_guard(), patch('modules.fr13_administrator_management.routes.retrieveRecord',
            side_effect=RuntimeError('private-storage-detail')):
        response = client.get('/api/fr13/payments?product=hotel', headers={'Authorization': 'Bearer test'})
    assert response.status_code == 503 and response.json['ok'] is False
    assert 'private-storage-detail' not in response.get_data(as_text=True)


def test_s1_catalog_retirement_keeps_discovery_source_and_records_intact():
    from modules.fr03_destination_search_information import routes as discovery
    records = [{'id': 's1-active', 'title': 'Synthetic active destination'},
               {'id': 's1-archived', 'status': 'archived'}]
    before = deepcopy(records)
    with patch.object(discovery, 'retrieveRecord', return_value=records) as read:
        result = discovery._all_destinations()
    read.assert_called_once_with('admin_destinations')
    assert any(x.get('id') == 's1-active' for x in result)
    assert not any(x.get('id') == 's1-archived' for x in result)
    assert len(result) >= len(discovery.DESTINATIONS) + 1 and records == before

def test_admin_rbac_forbidden_for_traveller(client, mock_traveller_auth):
    res = client.get(
        '/api/fr13/users',
        headers={'Authorization': 'Bearer valid_test_token'}
    )
    assert res.status_code == 403
    assert 'Insufficient role permission' in res.get_json()['error']

def test_admin_users_access(client, mock_admin_auth):
    with patch('modules.fr13_administrator_management.routes.retrieveRecord') as mock_retrieve:
        mock_retrieve.return_value = [
            {'uid': 'u1', 'role': 'traveller', 'email': 't@t.com'},
            {'uid': 'u2', 'role': 'operator', 'email': 'o@t.com'},
        ]
        res = client.get(
            '/api/fr13/users',
            headers={'Authorization': 'Bearer valid_test_token'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert len(data['items']) == 2


def test_admin_payment_history_is_forbidden_for_traveller(client, mock_traveller_auth):
    forbidden = client.get('/api/fr13/payments', headers={'Authorization': 'Bearer valid_test_token'})
    assert forbidden.status_code == 403


def test_admin_payment_history_filters_package_orders(client, mock_admin_auth):
    orders = [{
        'id': 'order-package-1', 'quoteType': 'package', 'travellerId': 'traveller-1',
        'paymentStatus': 'paid', 'createdAt': '2026-10-13T10:00:00Z',
        'packageSnapshot': {'title': 'Penang Heritage Escape'},
    }]
    with patch('modules.fr13_administrator_management.routes.retrieveRecord',
               side_effect=lambda collection, **kwargs: orders if collection == 'checkout_orders' else []):
        response = client.get('/api/fr13/payments?product=package&q=heritage',
                              headers={'Authorization': 'Bearer valid_test_token'})
    assert response.status_code == 200
    assert response.get_json()['items'] == [{
        **orders[0], 'productType': 'package', 'productTitle': 'Penang Heritage Escape',
        'amount':None,'currency':'UNKNOWN','isPaid':True,
    }]

def test_admin_review_package(client, mock_admin_auth):
    sample_pkg = {
        'id': 'pkg_pending_1',
        'packageTitle': 'Penang Sunset Cruise',
        'approvalStatus': 'pending'
    }
    sample_pkg.update(destination='Penang',price=100,durationDays=1,description='A complete legacy package.')
    with patch('modules.fr13_administrator_management.routes.retrieveRecord') as mock_retrieve, \
         patch('modules.fr13_administrator_management.routes.updateRecord') as mock_update:
        mock_retrieve.return_value = sample_pkg
        mock_update.side_effect = lambda coll, doc_id, data, **kwargs: {**sample_pkg, **data}

        # Approve package
        res = client.post(
            '/api/fr13/packages/pkg_pending_1/review',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'decision': 'approved', 'comment': 'Looks great!'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert data['package']['approvalStatus'] == 'approved'
        assert data['package']['reviewedBy'] == 'test_admin_uid'


def test_admin_rejection_requires_reason_and_completed_review_is_immutable(client, mock_admin_auth):
    pending = {'id': 'pkg_pending', 'packageTitle': 'Penang Tour', 'approvalStatus': 'pending'}
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', return_value=pending):
        missing = client.post('/api/fr13/packages/pkg_pending/review',
                              headers={'Authorization': 'Bearer valid_test_token'},
                              json={'decision': 'rejected', 'comment': ''})
    assert missing.status_code == 400
    assert missing.get_json()['error'] == 'A rejection reason is required'

    approved = {**pending, 'approvalStatus': 'approved'}
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', return_value=approved):
        duplicate = client.post('/api/fr13/packages/pkg_pending/review',
                                headers={'Authorization': 'Bearer valid_test_token'},
                                json={'decision': 'rejected', 'comment': 'Changed mind'})
    assert duplicate.status_code == 409

def test_admin_moderate_feedback(client, mock_admin_auth):
    sample_fb = {
        'id': 'fb_spam_1',
        'comment': 'Buy cheap sunglasses here!',
        'rating': 1,
        'feedbackStatus': 'visible'
    }
    with patch('modules.fr13_administrator_management.routes.retrieveRecord') as mock_retrieve, \
         patch('modules.fr13_administrator_management.routes.updateRecord') as mock_update:
        mock_retrieve.return_value = sample_fb
        mock_update.side_effect = lambda coll, doc_id, data, **kwargs: {**sample_fb, **data}

        # Remove spam feedback
        res = client.post(
            '/api/fr13/feedback/fb_spam_1/review',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'decision': 'remove', 'comment': 'Spam review'}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data['ok'] is True
        assert data['decision'] == 'remove'
        assert data['feedback']['feedbackStatus'] == 'removed'

def test_admin_destination_management(client, mock_admin_auth):
    with patch('modules.fr13_administrator_management.routes.storeRecord') as mock_store:
        mock_store.side_effect = lambda coll, data: {'id': 'dest_new_1', **data}

        res = client.post(
            '/api/fr13/destinations',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={
                'title': 'New Heritage Museum',
                'address': 'George Town, Penang',
                'category': 'Culture',
                'estimatedCost': 25.0,
                'rating': 4.7
            }
        )
        assert res.status_code == 201
        data = res.get_json()
        assert data['ok'] is True
        assert data['destination']['title'] == 'New Heritage Museum'

def test_admin_cannot_demote_or_disable_self(client, mock_admin_auth):
    res = client.put('/api/fr13/users/test_admin_uid',
                     headers={'Authorization': 'Bearer valid_test_token'},
                     json={'role': 'traveller'})
    assert res.status_code == 409
    assert 'cannot' in res.get_json()['error'].lower()

def test_campaign_queue_filters_and_rejection_requires_reason(client, mock_admin_auth):
    records = [
        {'id': 'camp-1', 'campaignTitle': 'Island offer', 'reviewStatus': 'pending', 'packageId': 'pkg-1'},
        {'id': 'camp-2', 'campaignTitle': 'Old offer', 'reviewStatus': 'approved', 'packageId': 'pkg-2'},
    ]
    def retrieve(collection, doc_id=None, filters=None, limit=None):
        if collection == 'promotional_campaigns':
            if doc_id: return next((x for x in records if x['id'] == doc_id), None)
            return records
        return {'packageTitle': 'Package'}
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', side_effect=retrieve):
        queued = client.get('/api/fr13/campaigns?status=pending', headers={'Authorization': 'Bearer valid_test_token'})
        assert queued.status_code == 200
        assert [x['id'] for x in queued.get_json()['items']] == ['camp-1']
        missing = client.post('/api/fr13/campaigns/camp-1/review', headers={'Authorization': 'Bearer valid_test_token'}, json={'decision': 'rejected'})
    assert missing.status_code == 400
    assert missing.get_json()['error'] == 'A rejection reason is required'
