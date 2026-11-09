import pytest
from copy import deepcopy
from contextlib import ExitStack
from contextlib import contextmanager
from unittest.mock import patch, MagicMock, call
from modules.fr12_tourism_operator_management.analytics_service import generate_business_analytics
from services.package_service import package_for_read


@contextmanager
def commerce_read_only_guard():
    """Payment visibility must never mutate records or invoke a provider."""
    with ExitStack() as stack:
        forbidden = []
        for path in (
            'modules.fr12_tourism_operator_management.routes.storeRecord',
            'modules.fr12_tourism_operator_management.routes.updateRecord',
            'modules.fr12_tourism_operator_management.routes.deleteRecord',
            'modules.fr12_tourism_operator_management.routes.commitPackageFulfillment',
            'modules.fr13_administrator_management.routes.storeRecord',
            'modules.fr13_administrator_management.routes.updateRecord',
            'modules.fr13_administrator_management.routes.deleteRecord',
            'sequence_contract.firebase_firestore.claimRecord',
            'modules.fr09_payment.routes.createCheckoutSession',
            'modules.fr09_payment.routes.retrieveCheckoutSession',
            'modules.fr09_payment.routes._reconcile_checkout_order',
            'modules.fr08_hotel_booking.routes.createBookingReference',
            'requests.sessions.Session.request',
        ):
            forbidden.append(stack.enter_context(patch(path, side_effect=AssertionError('Read-only contract violation'))))
        yield
        for operation in forbidden:
            operation.assert_not_called()


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


def test_operator_booking_projection_is_owner_scoped_and_sanitized(client, mock_operator_auth):
    orders = [
        {
            'id': 'order-own', 'quoteType': 'package',
            'operatorId': 'test_operator_uid', 'travellerId': 'traveller-secret',
            'packageId': 'package-1',
            'packageSnapshot': {
                'title': 'Penang Heritage', 'selectedDepartureDate': '2027-02-10',
                'participants': {'adults': 2, 'children': 1, 'total': 3},
            },
            'amount': 1075.50, 'currency': 'MYR', 'status': 'paid',
            'paymentStatus': 'paid', 'fulfillmentStatus': 'fulfilled',
            'provider': 'stripe_checkout_test',
            'stripePaymentIntentId': 'pi_secret', 'createdAt': '2026-10-16T00:00:00Z',
        },
        {
            'id': 'order-other', 'quoteType': 'package',
            'operatorId': 'other-operator', 'packageSnapshot': {'title': 'Other'},
        },
        {
            'id': 'order-own-legacy', 'quoteType': 'package',
            'operatorId': 'test_operator_uid',
            'packageSnapshot': {'title': 'Legacy Package'},
            'amount': 100, 'currency': 'MYR', 'status': 'paid',
        },
    ]

    def retrieve(_collection, document_id=None, filters=None, limit=None):
        values = orders
        for field, operator, expected in filters or []:
            assert operator == '=='
            values = [item for item in values if item.get(field) == expected]
        return values

    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', side_effect=retrieve):
        response = client.get(
            '/api/fr12/bookings', headers={'Authorization': 'Bearer valid_test_token'}
        )
    assert response.status_code == 200
    items = response.get_json()['items']
    assert len(items) == 2 and items[0]['orderReference'] == 'order-own'
    assert items[0]['groupSize'] == 3 and items[0]['supplierReservationStatus'] == 'not_created'
    assert items[0]['testMode'] is True
    assert 'travellerId' not in items[0] and 'stripePaymentIntentId' not in items[0]
    legacy = items[1]
    assert legacy['orderReference'] == 'order-own-legacy'
    assert legacy['groupSize'] is None and legacy['adults'] is None and legacy['children'] is None
    assert legacy['supplierReservationStatus'] == 'not_created'


def test_operator_booking_projection_rejects_traveller(client, mock_traveller_auth):
    response = client.get(
        '/api/fr12/bookings', headers={'Authorization': 'Bearer valid_test_token'}
    )
    assert response.status_code == 403


def test_admin_booking_projection_can_read_all_package_orders(client, mock_admin_auth):
    orders = [
        {'id': 'one', 'quoteType': 'package', 'operatorId': 'operator-1'},
        {'id': 'two', 'quoteType': 'package', 'operatorId': 'operator-2'},
        {'id': 'hotel', 'quoteType': 'hotel'},
    ]
    with patch(
        'modules.fr12_tourism_operator_management.routes.retrieveRecord',
        side_effect=lambda collection,*args,**kwargs: orders if collection=='checkout_orders' else None,
    ) as retrieve:
        response = client.get(
            '/api/fr12/bookings', headers={'Authorization': 'Bearer valid_test_token'}
        )
    assert response.status_code == 200
    assert [item['orderReference'] for item in response.get_json()['items']] == ['one', 'two']
    assert retrieve.call_args_list == [call('checkout_orders',filters=None,limit=501),
        call('package_requirement_clarifications','one'),call('package_requirement_clarifications','two')]

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

    # Mock checkout_orders: 1 belongs to op_alpha, 1 belongs to op_beta, 1 has no operatorId
    b1 = MagicMock()
    b1.id = 'b_alpha'
    b1.to_dict.return_value = {'operatorId': 'op_alpha', 'quoteType': 'package', 'totalAmount': 200.0, 'amount': 200.0, 'paymentStatus': 'paid'}

    b2 = MagicMock()
    b2.id = 'b_beta'
    b2.to_dict.return_value = {'operatorId': 'op_beta', 'quoteType': 'package', 'totalAmount': 300.0, 'amount': 300.0, 'paymentStatus': 'paid'}

    b3 = MagicMock()
    b3.id = 'b_generic'
    b3.to_dict.return_value = {'hotelName': 'General Hotel', 'quoteType': 'hotel', 'totalAmount': 150.0} # No operatorId

    def mock_collection(name):
        coll_mock = MagicMock()
        if name in ('checkout_orders', 'hotel_bookings'):
            coll_mock.where.return_value.stream.return_value = [b1]
            coll_mock.stream.return_value = [b1, b2, b3]
        elif name in ('tourism_packages', 'promotional_campaigns'):
            coll_mock.where.return_value.stream.return_value = [pkg_doc] if name == 'tourism_packages' else []
            coll_mock.stream.return_value = [pkg_doc] if name == 'tourism_packages' else []
        coll_mock.limit.return_value = coll_mock
        coll_mock.where.return_value.limit.return_value = coll_mock.where.return_value
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
                'startDate': '2030-10-01',
                'endDate': '2030-10-15',
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
        update.side_effect = lambda collection, document_id, data, **kwargs: {**approved, **data}
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
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', side_effect=lambda collection, *_a, **_k: draft if collection == 'tourism_packages' else []), \
         patch('modules.fr12_tourism_operator_management.routes.deleteRecord') as delete, \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord', return_value={**draft, 'deletedAt':'synthetic-time'}) as retire:
        removed = client.delete('/api/fr12/packages/pkg_v2',
                                headers={'Authorization': 'Bearer valid_test_token'})
    assert removed.status_code == 200
    delete.assert_not_called()
    assert retire.call_args.args[2]['deletedBy'] == 'test_operator_uid'
    assert retire.call_args.kwargs['expected'] == draft


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


@pytest.mark.parametrize('changes', [{'adultPrice': float('nan')}, {'adultPrice': float('inf')},
    {'maximumTravellers': 'many'}, {'minimumTravellers': 'invalid'}, {'title': {'invalid': True}}])
def test_f4a_package_numeric_validation(client, mock_operator_auth, changes):
    payload = {'title': 'Synthetic tour', 'destination': 'Penang', 'durationDays': 1,
               'adultPrice': 100, 'currency': 'MYR', **changes}
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value={}), \
         patch('modules.fr12_tourism_operator_management.routes.storeRecord', side_effect=lambda _c, data: {'id': 'synthetic', **data}) as store:
        response = client.post('/api/fr12/packages', headers={'Authorization': 'Bearer test'}, json=payload)
    assert response.status_code == 400
    store.assert_not_called()


@pytest.mark.parametrize('changes', [
    {'discountType': 'percentage', 'discountValue': 101}, {'discountType': 'fixed', 'discountValue': -1},
    {'discountType': 'percentage', 'discountValue': float('nan')},
    {'discountType': 'percentage', 'discountValue': 'invalid'}, {'discountType': 'unsupported', 'discountValue': 10},
    {'discountType': ['percentage'], 'discountValue': 10}])
def test_f4a_campaign_discount_validation(client, mock_operator_auth, changes):
    payload = {'campaignTitle': 'Synthetic offer', 'startDate': '2030-01-01', 'endDate': '2030-01-02', **changes}
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value={}), \
         patch('modules.fr12_tourism_operator_management.routes.storeRecord', side_effect=lambda _c, data: {'id': 'synthetic', **data}) as store:
        response = client.post('/api/fr12/campaigns', headers={'Authorization': 'Bearer test'}, json=payload)
    assert response.status_code == 400
    store.assert_not_called()


@pytest.mark.parametrize('status', ['pending', 'approved'])
def test_f4a_campaign_submission_lifecycle(client, mock_operator_auth, status):
    campaign = {'operatorId': 'test_operator_uid', 'reviewStatus': status, 'packageId': 'p',
                'campaignTitle': 'Synthetic offer', 'startDate': '2030-01-01', 'endDate': '2030-01-02'}
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value=campaign), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord', side_effect=lambda _c, _i, data: data) as update:
        response = client.post('/api/fr12/campaigns/c/submit', headers={'Authorization': 'Bearer test'})
    assert response.status_code == 409
    update.assert_not_called()


@pytest.mark.parametrize('package', [None, {'operatorId': 'other', 'approvalStatus': 'approved'},
    {'operatorId': 'test_operator_uid', 'approvalStatus': 'archived'},
    {'operatorId': 'test_operator_uid', 'approvalStatus': 'approved', 'availabilityStatus': 'unavailable'}])
def test_f4a_campaign_submit_rechecks_package(client, mock_operator_auth, package):
    campaign = {'operatorId': 'test_operator_uid', 'reviewStatus': 'rejected', 'packageId': 'p',
                'campaignTitle': 'Synthetic offer', 'startDate': '2030-01-01', 'endDate': '2030-01-02'}
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord',
               side_effect=lambda coll, *_a, **_k: campaign if coll == 'promotional_campaigns' else package), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord', side_effect=lambda _c, _i, data: data) as update:
        response = client.post('/api/fr12/campaigns/c/submit', headers={'Authorization': 'Bearer test'})
    assert response.status_code in {404, 409}
    update.assert_not_called()


def test_f4a_package_with_order_history_requires_archive(client, mock_operator_auth):
    package = {'operatorId': 'test_operator_uid', 'approvalStatus': 'draft'}
    order = {'id': 'historical-order', 'packageId': 'p', 'status': 'paid'}
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord',
               side_effect=lambda coll, *_a, **_k: package if coll == 'tourism_packages' else [order]), \
         patch('modules.fr12_tourism_operator_management.routes.deleteRecord') as delete:
        response = client.delete('/api/fr12/packages/p', headers={'Authorization': 'Bearer test'})
    assert response.status_code == 409
    assert 'archive' in response.get_json()['error'].lower()
    delete.assert_not_called()


def test_f4a_booking_detail_owner_and_redaction(client, mock_operator_auth):
    order = {'id': 'owned', 'operatorId': 'test_operator_uid', 'quoteType': 'package',
             'amount': 100, 'currency': 'MYR', 'paymentStatus': 'paid', 'status': 'paid',
             'travellerId': 'private-user', 'checkoutUrl': 'private-checkout-url'}
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value=order):
        response = client.get('/api/fr12/bookings/owned', headers={'Authorization': 'Bearer test'})
    assert response.status_code == 200
    assert response.get_json()['booking']['orderReference'] == 'owned'
    assert 'private-' not in response.get_data(as_text=True)
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value={**order, 'operatorId': 'other'}):
        assert client.get('/api/fr12/bookings/owned', headers={'Authorization': 'Bearer test'}).status_code == 404


def test_f4a_profile_cannot_forge_privileges(client, mock_operator_auth):
    profile = {'uid': 'test_operator_uid', 'role': 'operator', 'verificationStatus': 'approved'}
    with patch('modules.fr01_user_management.routes.updateRecord', side_effect=lambda c, uid, fields: {**profile, **fields}) as update:
        response = client.put('/api/fr1/me', headers={'Authorization': 'Bearer test'}, json={
            'name': 'Synthetic Owner', 'companyName': 'Synthetic Business', 'role': 'admin',
            'operatorId': 'other', 'verificationStatus': 'rejected'})
    assert response.status_code == 200
    assert response.get_json()['profile']['role'] == 'operator'
    assert response.get_json()['profile']['verificationStatus'] == 'approved'
    assert not {'role', 'operatorId', 'verificationStatus'} & set(update.call_args.args[2])


def _s1_package_order(**changes):
    return {'id':'s1-order-owned','quoteType':'package','operatorId':'test_operator_uid',
        'packageId':'s1-package','packageSnapshot':{'title':'Synthetic package','operatorId':'test_operator_uid',
            'accommodation':{'accommodationName':'Included property'}},
        'amount':250,'currency':'MYR','status':'paid','paymentStatus':'paid','testMode':True,
        'paidAt':'2026-11-01T12:00:00+00:00','createdAt':'2026-11-01T11:00:00+00:00',
        'updatedAt':'2026-11-02T12:00:00+00:00','fulfillmentStatus':'awaiting_operator_fulfillment',
        'supplierReservationStatus':'not_created','travellerId':'private-traveller',
        'checkoutUrl':'private-checkout','clientSecret':'private-client',
        'stripePaymentIntentId':'private-intent-'+str(changes.get('id','s1-order-owned')),
        **changes}


@pytest.mark.parametrize('paid_at',[None,'2026-11-01T12:00:00+00:00'])
def test_s1_operator_payment_timestamp_is_available_without_invented_fallback(client,mock_operator_auth,paid_at):
    order=_s1_package_order(paidAt=paid_at);before=deepcopy(order)
    with commerce_read_only_guard(),patch('modules.fr12_tourism_operator_management.routes.retrieveRecord',return_value=order):
        response=client.get('/api/fr12/bookings/s1-order-owned',headers={'Authorization':'Bearer valid_test_token'})
    assert response.status_code==200
    booking=response.json['booking']
    assert booking['paidAt']==paid_at
    assert booking['createdAt']==order['createdAt'] and booking['updatedAt']==order['updatedAt']
    assert booking['orderReference']==order['id'] and booking['packageId']=='s1-package'
    assert booking['packageTitle']=='Synthetic package' and booking['amount']==250 and booking['currency']=='MYR'
    assert booking['isPaid'] is True and booking['testMode'] is True
    assert booking['fulfillmentStatus']=='awaiting_operator_fulfillment' and booking['supplierReservationStatus']=='not_created'
    assert 'private-' not in response.get_data(as_text=True)
    assert order==before


def test_s1_operator_list_owner_filter_dedup_and_missing_values(client,mock_operator_auth):
    orders=[_s1_package_order(),_s1_package_order(),
            _s1_package_order(id='foreign',operatorId='other-operator'),
            _s1_package_order(id='hotel',quoteType='hotel'),
            _s1_package_order(id='unknown',amount=None,currency='',paidAt=None,paymentStatus='pending',status='checkout_pending')]
    before=deepcopy(orders)
    with commerce_read_only_guard(),patch('modules.fr12_tourism_operator_management.routes.retrieveRecord',
            side_effect=lambda collection,*args,**kwargs: orders if collection=='checkout_orders' else None) as read:
        response=client.get('/api/fr12/bookings',headers={'Authorization':'Bearer valid_test_token'})
    assert response.status_code==200 and response.json['ok'] is True
    assert read.call_args_list == [call('checkout_orders',filters=[('operatorId','==','test_operator_uid')],limit=501),
        call('package_requirement_clarifications','unknown'),call('package_requirement_clarifications','s1-order-owned')]
    items={item['id']:item for item in response.json['items']}
    assert set(items)=={'s1-order-owned','unknown'}
    assert items['unknown']['amount'] is None and items['unknown']['currency']=='UNKNOWN'
    assert items['unknown']['paidAt'] is None and items['unknown']['isPaid'] is False
    assert response.json['dataLimited'] is False and response.json['recordLimit']==500
    assert 'private-' not in response.get_data(as_text=True) and orders==before


@pytest.mark.parametrize('record',[None,{'id':'other','operatorId':'other-operator','quoteType':'package'},
                                  {'id':'hotel','operatorId':'test_operator_uid','quoteType':'hotel'}])
def test_s1_operator_detail_foreign_missing_and_wrong_product_are_404(client,mock_operator_auth,record):
    with commerce_read_only_guard(),patch('modules.fr12_tourism_operator_management.routes.retrieveRecord',return_value=record):
        response=client.get('/api/fr12/bookings/unknown',headers={'Authorization':'Bearer valid_test_token'})
    assert response.status_code==404 and response.json=={'ok':False,'error':'Booking not found'}


def test_s1_operator_empty_and_capped_list_are_explicit(client,mock_operator_auth):
    with commerce_read_only_guard(),patch('modules.fr12_tourism_operator_management.routes.retrieveRecord',return_value=[]):
        response=client.get('/api/fr12/bookings',headers={'Authorization':'Bearer valid_test_token'})
    assert response.json=={'ok':True,'items':[],'dataLimited':False,'recordLimit':500}
    orders=[_s1_package_order(id=f's1-{i}') for i in range(501)]
    with commerce_read_only_guard(),patch('modules.fr12_tourism_operator_management.routes.retrieveRecord',return_value=orders):
        response=client.get('/api/fr12/bookings',headers={'Authorization':'Bearer valid_test_token'})
    assert len(response.json['items'])==500 and response.json['dataLimited'] is True


@pytest.mark.parametrize('path',['/api/fr12/bookings','/api/fr12/bookings/owned'])
def test_s1_operator_payments_require_token(client,path):
    with commerce_read_only_guard(),patch('modules.fr12_tourism_operator_management.routes.retrieveRecord') as read:
        response=client.get(path)
    assert response.status_code==401;read.assert_not_called()


@pytest.mark.parametrize('path',['/api/fr12/bookings','/api/fr12/bookings/owned'])
def test_s1_operator_payments_forbid_traveller(client,mock_traveller_auth,path):
    with commerce_read_only_guard(),patch('modules.fr12_tourism_operator_management.routes.retrieveRecord') as read:
        response=client.get(path,headers={'Authorization':'Bearer valid_test_token'})
    assert response.status_code==403;read.assert_not_called()


def test_f4a_campaign_rejected_resubmission_validates_and_persists(client, mock_operator_auth):
    campaign = {'operatorId': 'test_operator_uid', 'reviewStatus': 'rejected', 'campaignStatus': 'rejected',
                'campaignTitle': 'Synthetic offer', 'packageId': 'p', 'startDate': '2030-01-01', 'endDate': '2030-01-02',
                'discountType': 'percentage', 'discountValue': 10}
    package = {'operatorId': 'test_operator_uid', 'approvalStatus': 'approved'}
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord',
               side_effect=lambda coll, *_a, **_k: campaign if coll == 'promotional_campaigns' else package), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord', side_effect=lambda _c, _id, fields: {**campaign, **fields}) as update:
        response = client.post('/api/fr12/campaigns/c/submit', headers={'Authorization': 'Bearer test'})
    assert response.status_code == 200
    assert response.get_json()['campaign']['reviewStatus'] == 'pending'
    assert response.get_json()['campaign']['campaignStatus'] == 'draft'
    assert update.call_args.args[2]['submittedAt']
