import io
import json
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from services.image_storage_service import (
    get_image_metadata,
    get_upload_dir,
    is_safe_filename,
    save_image_metadata,
)

AUTH_OP_A = {'Authorization': 'Bearer valid_op_a_token'}
AUTH_OP_B = {'Authorization': 'Bearer valid_op_b_token'}
AUTH_ADMIN = {'Authorization': 'Bearer valid_admin_token'}
AUTH_TRAVELLER = {'Authorization': 'Bearer valid_traveller_token'}
AUTH_UNVERIFIED = {'Authorization': 'Bearer valid_unverified_token'}

UID_OP_A = 'test_operator_uid'
UID_OP_B = 'operator_b_uid'
UID_ADMIN = 'admin_uid'
UID_TRAVELLER = 'traveller_uid'
UID_UNVERIFIED = 'unverified_operator_uid'

SAMPLE_PNG_BYTES = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4'
    b'\x00\x00\x00\x00IEND\xaeB`\x82'
)

BASE_CAMPAIGN = {
    'id': 'campaign-1',
    'operatorId': UID_OP_A,
    'operatorName': 'Operator A Company',
    'campaignTitle': 'Summer Getaway Promo',
    'description': 'Enjoy special discounts on local tours.',
    'packageId': 'pkg-approved-1',
    'startDate': '2026-11-01',
    'endDate': '2026-11-30',
    'discountType': 'percentage',
    'discountValue': 15,
    'promoCode': 'SUMMER15',
    'bannerImageUrl': 'http://127.0.0.1:5000/api/public/package-images/banner1.png',
    'termsConditions': 'Standard terms apply.',
    'reviewStatus': 'draft',
    'campaignStatus': 'draft',
    'createdAt': '2026-10-01T00:00:00Z',
    'updatedAt': '2026-10-01T00:00:00Z',
}

APPROVED_CAMPAIGN = {
    **BASE_CAMPAIGN,
    'id': 'campaign-approved-1',
    'reviewStatus': 'approved',
    'campaignStatus': 'active',
    'reviewerId': UID_ADMIN,
    'reviewedBy': UID_ADMIN,
    'reviewedByName': 'System Administrator',
    'reviewedAt': '2026-10-05T00:00:00Z',
    'approvedAt': '2026-10-05T00:00:00Z',
    'reviewComment': 'Approved for publication.',
}


def read_campaign_and_package(campaign):
    records = {
        ('promotional_campaigns', campaign['id']): campaign,
        ('tourism_packages', campaign['packageId']): {
            'id': campaign['packageId'], 'operatorId': UID_OP_A,
            'approvalStatus': 'approved', 'availabilityStatus': 'available',
        },
    }
    return lambda collection, document_id: records.get((collection, document_id))


@pytest.fixture
def temp_upload_dir(monkeypatch):
    temp_dir = tempfile.mkdtemp()
    monkeypatch.setenv("PACKAGE_IMAGE_UPLOAD_DIR", temp_dir)
    monkeypatch.setenv("PUBLIC_IMAGE_BASE_URL", "http://127.0.0.1:5000")
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mock_multi_auth():
    """Mock auth_required for various user roles and uids."""
    with patch("auth_utils.auth.verify_id_token") as mock_verify, \
         patch("auth_utils.get_db") as mock_get_db:

        def fake_verify(token, **kwargs):
            if token == 'valid_op_a_token':
                return {'uid': UID_OP_A, 'email': 'op_a@test.com', 'name': 'Operator A'}
            if token == 'valid_op_b_token':
                return {'uid': UID_OP_B, 'email': 'op_b@test.com', 'name': 'Operator B'}
            if token == 'valid_admin_token':
                return {'uid': UID_ADMIN, 'email': 'admin@test.com', 'name': 'Admin'}
            if token == 'valid_traveller_token':
                return {'uid': UID_TRAVELLER, 'email': 'traveller@test.com', 'name': 'Traveller'}
            if token == 'valid_unverified_token':
                return {'uid': UID_UNVERIFIED, 'email': 'unverified@test.com', 'name': 'Unverified'}
            raise ValueError('Invalid token')

        mock_verify.side_effect = fake_verify

        profiles = {
            UID_OP_A: {'uid': UID_OP_A, 'role': 'operator', 'status': 'active', 'verificationStatus': 'verified', 'companyName': 'Operator A Company'},
            UID_OP_B: {'uid': UID_OP_B, 'role': 'operator', 'status': 'active', 'verificationStatus': 'verified', 'companyName': 'Operator B Company'},
            UID_ADMIN: {'uid': UID_ADMIN, 'role': 'admin', 'status': 'active'},
            UID_TRAVELLER: {'uid': UID_TRAVELLER, 'role': 'traveller', 'status': 'active'},
            UID_UNVERIFIED: {'uid': UID_UNVERIFIED, 'role': 'operator', 'status': 'active', 'verificationStatus': 'pending'},
        }

        mock_db = MagicMock()
        def fake_collection(name):
            coll = MagicMock()
            def fake_doc(doc_id):
                doc = MagicMock()
                snap = MagicMock()
                if name == 'users' and doc_id in profiles:
                    snap.exists = True
                    snap.to_dict.return_value = profiles[doc_id]
                else:
                    snap.exists = False
                    snap.to_dict.return_value = None
                doc.get.return_value = snap
                return doc
            coll.document.side_effect = fake_doc
            return coll

        mock_db.collection.side_effect = fake_collection
        mock_get_db.return_value = mock_db
        yield


# =========================================================================
# P0-A: CAMPAIGN AUTHORIZATION TESTS
# =========================================================================

def test_authorized_campaign_content_update_succeeds(client, mock_multi_auth):
    """An authorized operator can update legitimate editable content fields."""
    updated_record = {
        **BASE_CAMPAIGN,
        'description': 'Updated promo description.',
        'discountValue': 20,
        'promoCode': 'SUMMER20',
    }
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', side_effect=read_campaign_and_package(BASE_CAMPAIGN)), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord', return_value=updated_record) as update:
        res = client.put(
            f'/api/fr12/campaigns/{BASE_CAMPAIGN["id"]}',
            headers=AUTH_OP_A,
            json={
                'description': 'Updated promo description.',
                'discountValue': 20,
                'promoCode': 'SUMMER20',
            }
        )

    assert res.status_code == 200
    assert res.get_json()['ok'] is True
    update.assert_called_once()
    updates = update.call_args.args[2]
    assert updates['description'] == 'Updated promo description.'
    assert updates['discountValue'] == 20
    assert updates['promoCode'] == 'SUMMER20'
    assert 'updatedAt' in updates
    # Ensure no protected fields leaked in
    for field in ['operatorId', 'reviewStatus', 'campaignStatus', 'reviewerId', 'approvedAt']:
        assert field not in updates


@pytest.mark.parametrize('protected_payload', [
    {'operatorId': UID_OP_B},
    {'operatorName': 'Injected Operator'},
    {'reviewStatus': 'approved'},
    {'campaignStatus': 'active'},
    {'reviewerId': UID_ADMIN},
    {'reviewedBy': UID_ADMIN},
    {'reviewedByName': 'Admin User'},
    {'reviewedAt': '2026-10-21T00:00:00Z'},
    {'approvedAt': '2026-10-21T00:00:00Z'},
    {'rejectedAt': '2026-10-21T00:00:00Z'},
    {'reviewComment': 'Self approved'},
    {'reviewReason': 'Bypassed'},
    {'submittedAt': '2026-10-21T00:00:00Z'},
    {'createdAt': '2020-01-01T00:00:00Z'},
    {'updatedAt': '2020-01-01T00:00:00Z'},
    {'id': 'different-id'},
])
def test_protected_campaign_fields_are_rejected(client, mock_multi_auth, protected_payload):
    """Any attempt by an operator to supply protected fields during update is rejected with 400."""
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value=BASE_CAMPAIGN), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord') as update:
        res = client.put(
            f'/api/fr12/campaigns/{BASE_CAMPAIGN["id"]}',
            headers=AUTH_OP_A,
            json={
                'description': 'Legitimate update text',
                **protected_payload,
            }
        )

    assert res.status_code == 400
    assert res.get_json()['ok'] is False
    assert 'protected' in res.get_json()['error'].lower()
    # Zero unauthorized writes!
    update.assert_not_called()


@pytest.mark.parametrize('protected_field', [
    'reviewStatus', 'campaignStatus', 'reviewerId', 'approvedAt', 'operatorId'
])
def test_campaign_creation_rejects_protected_fields(client, mock_multi_auth, protected_field):
    """Campaign creation rejects protected fields supplied by client."""
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value={'id': 'pkg-1', 'approvalStatus': 'approved', 'operatorId': UID_OP_A}), \
         patch('modules.fr12_tourism_operator_management.routes.storeRecord') as store:
        res = client.post(
            '/api/fr12/campaigns',
            headers=AUTH_OP_A,
            json={
                'campaignTitle': 'New Campaign',
                'description': 'Promo',
                'startDate': '2026-11-01',
                'endDate': '2026-11-30',
                'packageId': 'pkg-1',
                protected_field: 'malicious_value',
            }
        )

    assert res.status_code == 400
    assert 'protected' in res.get_json()['error'].lower()
    store.assert_not_called()


def test_cross_operator_campaign_update_denied(client, mock_multi_auth):
    """Operator A cannot update Operator B's campaign."""
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value=BASE_CAMPAIGN), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord') as update:
        # Request made by Operator B on Operator A's campaign
        res = client.put(
            f'/api/fr12/campaigns/{BASE_CAMPAIGN["id"]}',
            headers=AUTH_OP_B,
            json={'description': 'Hacked by B'}
        )

    assert res.status_code == 404
    assert res.get_json()['ok'] is False
    update.assert_not_called()


def test_unverified_operator_denied_campaign_update(client, mock_multi_auth):
    """Unverified operators cannot update campaigns."""
    res = client.put(
        f'/api/fr12/campaigns/{BASE_CAMPAIGN["id"]}',
        headers=AUTH_UNVERIFIED,
        json={'description': 'Test'}
    )
    assert res.status_code == 403
    assert 'not verified' in res.get_json()['error'].lower()


def test_traveller_denied_campaign_update(client, mock_multi_auth):
    """Travellers cannot update campaigns."""
    res = client.put(
        f'/api/fr12/campaigns/{BASE_CAMPAIGN["id"]}',
        headers=AUTH_TRAVELLER,
        json={'description': 'Test'}
    )
    assert res.status_code == 403
    assert 'permission' in res.get_json()['error'].lower()


def test_unauthenticated_user_denied_campaign_update(client, mock_multi_auth):
    """Unauthenticated requests are denied."""
    res = client.put(
        f'/api/fr12/campaigns/{BASE_CAMPAIGN["id"]}',
        json={'description': 'Test'}
    )
    assert res.status_code == 401


def test_approved_campaign_editing_resets_to_draft_and_clears_moderation(client, mock_multi_auth):
    """Editing an approved campaign returns reviewStatus and campaignStatus to draft and clears audit fields."""
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', side_effect=read_campaign_and_package(APPROVED_CAMPAIGN)), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord') as update:
        update.side_effect = lambda coll, doc_id, data: {**APPROVED_CAMPAIGN, **data}
        res = client.put(
            f'/api/fr12/campaigns/{APPROVED_CAMPAIGN["id"]}',
            headers=AUTH_OP_A,
            json={'description': 'Changed promotional offer text.'}
        )

    assert res.status_code == 200
    update.assert_called_once()
    updates = update.call_args.args[2]
    assert updates['reviewStatus'] == 'draft'
    assert updates['campaignStatus'] == 'draft'
    assert updates['reviewComment'] == ''
    assert updates['reviewReason'] == ''
    assert updates['reviewedBy'] == ''
    assert updates['reviewedByName'] == ''
    assert updates['reviewedAt'] == ''
    assert updates['approvedAt'] == ''
    assert updates['submittedAt'] == ''


def test_campaign_under_review_cannot_be_edited(client, mock_multi_auth):
    """Campaign with reviewStatus == 'pending' cannot be edited."""
    pending = {**BASE_CAMPAIGN, 'reviewStatus': 'pending'}
    with patch('modules.fr12_tourism_operator_management.routes.retrieveRecord', return_value=pending), \
         patch('modules.fr12_tourism_operator_management.routes.updateRecord') as update:
        res = client.put(
            f'/api/fr12/campaigns/{pending["id"]}',
            headers=AUTH_OP_A,
            json={'description': 'Edit while pending'}
        )

    assert res.status_code == 409
    assert 'administrator review' in res.get_json()['error'].lower()
    update.assert_not_called()


def test_admin_campaign_review_approval_and_rejection_preserved(client, mock_multi_auth):
    """Admin review endpoint continues to function for approval and rejection."""
    pending = {**BASE_CAMPAIGN, 'reviewStatus': 'pending'}
    with patch('modules.fr13_administrator_management.routes.retrieveRecord',
               side_effect=lambda collection, *args, **kwargs: pending if collection == 'promotional_campaigns' else {'id':pending['packageId'],'operatorId':pending['operatorId'],'approvalStatus':'approved'}), \
         patch('modules.fr13_administrator_management.routes.updateRecord') as update:
        update.side_effect = lambda coll, doc_id, data, **kwargs: {**pending, **data}
        # Admin approves
        res_approve = client.post(
            f'/api/fr13/campaigns/{pending["id"]}/review',
            headers=AUTH_ADMIN,
            json={'decision': 'approved', 'comment': 'Looks great!'}
        )
        assert res_approve.status_code == 200
        saved = res_approve.get_json()['campaign']
        assert saved['reviewStatus'] == 'approved'
        assert saved['campaignStatus'] == 'approved'

        # Admin rejects
        res_reject = client.post(
            f'/api/fr13/campaigns/{pending["id"]}/review',
            headers=AUTH_ADMIN,
            json={'decision': 'rejected', 'comment': 'Fix discount dates.'}
        )
        assert res_reject.status_code == 200
        saved_reject = res_reject.get_json()['campaign']
        assert saved_reject['reviewStatus'] == 'rejected'


# =========================================================================
# P0-B: PACKAGE IMAGE AUTHORIZATION TESTS
# =========================================================================

def test_operator_upload_stores_authenticated_owner_metadata(client, mock_multi_auth, temp_upload_dir):
    """Upload endpoint records the authenticated operator's uid in server-side metadata."""
    data = {'file': (io.BytesIO(SAMPLE_PNG_BYTES), 'test_img.png', 'image/png')}
    res = client.post(
        '/api/fr12/package-images/upload',
        data=data,
        content_type='multipart/form-data',
        headers=AUTH_OP_A,
    )
    assert res.status_code == 201
    filename = res.get_json()['filename']
    assert is_safe_filename(filename)

    meta = get_image_metadata(filename)
    assert meta is not None
    assert meta['ownerId'] == UID_OP_A
    assert meta['filename'] == filename
    assert meta['uploadedAt']


def test_owner_can_delete_valid_unreferenced_image(client, mock_multi_auth, temp_upload_dir):
    """The uploading operator can successfully delete their unreferenced image."""
    data = {'file': (io.BytesIO(SAMPLE_PNG_BYTES), 'my_img.png', 'image/png')}
    upload_res = client.post(
        '/api/fr12/package-images/upload',
        data=data,
        content_type='multipart/form-data',
        headers=AUTH_OP_A,
    )
    filename = upload_res.get_json()['filename']

    # Delete as Operator A (the owner)
    del_res = client.delete(
        f'/api/fr12/package-images/{filename}',
        headers=AUTH_OP_A,
    )
    assert del_res.status_code == 200
    assert del_res.get_json()['ok'] is True
    assert del_res.get_json()['deleted'] is True

    # File and metadata removed from disk
    upload_dir = get_upload_dir()
    assert not (upload_dir / filename).exists()
    assert not (upload_dir / f"{filename}.meta.json").exists()


def test_operator_a_cannot_delete_operator_b_image(client, mock_multi_auth, temp_upload_dir):
    """Operator A is denied (403) when attempting to delete Operator B's image."""
    # Upload as Operator B
    data = {'file': (io.BytesIO(SAMPLE_PNG_BYTES), 'op_b_img.png', 'image/png')}
    upload_res = client.post(
        '/api/fr12/package-images/upload',
        data=data,
        content_type='multipart/form-data',
        headers=AUTH_OP_B,
    )
    filename = upload_res.get_json()['filename']

    # Attempt delete as Operator A
    del_res = client.delete(
        f'/api/fr12/package-images/{filename}',
        headers=AUTH_OP_A,
    )
    assert del_res.status_code == 403
    assert del_res.get_json()['ok'] is False
    assert 'permission' in del_res.get_json()['error'].lower()

    # Image remains intact on disk!
    upload_dir = get_upload_dir()
    assert (upload_dir / filename).exists()
    assert (upload_dir / f"{filename}.meta.json").exists()


def test_knowing_uuid_is_insufficient_for_deletion(client, mock_multi_auth, temp_upload_dir):
    """Even if an attacker knows the exact UUID of another operator's file, deletion is denied."""
    # Write a real file owned by Operator B directly
    filename = "0123456789abcdef0123456789abcdef.png"
    upload_dir = get_upload_dir()
    with open(upload_dir / filename, 'wb') as f:
        f.write(SAMPLE_PNG_BYTES)
    save_image_metadata(filename, owner_id=UID_OP_B)

    # Operator A calls delete with the exact UUID
    res = client.delete(f'/api/fr12/package-images/{filename}', headers=AUTH_OP_A)
    assert res.status_code == 403
    assert (upload_dir / filename).exists()


def test_client_supplied_owner_metadata_is_ignored_on_upload(client, mock_multi_auth, temp_upload_dir):
    """Client cannot spoof ownerId via form-data fields during upload."""
    data = {
        'file': (io.BytesIO(SAMPLE_PNG_BYTES), 'spoof.png', 'image/png'),
        'ownerId': UID_OP_B,
        'operatorId': UID_OP_B,
    }
    upload_res = client.post(
        '/api/fr12/package-images/upload',
        data=data,
        content_type='multipart/form-data',
        headers=AUTH_OP_A,
    )
    assert upload_res.status_code == 201
    filename = upload_res.get_json()['filename']

    meta = get_image_metadata(filename)
    # Server recorded the authenticated caller UID_OP_A, ignoring UID_OP_B from client!
    assert meta['ownerId'] == UID_OP_A


def test_referenced_package_images_are_protected_from_deletion(client, mock_multi_auth, temp_upload_dir):
    """Images currently referenced by a package cannot be deleted (409 Conflict)."""
    data = {'file': (io.BytesIO(SAMPLE_PNG_BYTES), 'referenced.png', 'image/png')}
    upload_res = client.post(
        '/api/fr12/package-images/upload',
        data=data,
        content_type='multipart/form-data',
        headers=AUTH_OP_A,
    )
    filename = upload_res.get_json()['filename']

    # Package references this image
    package_with_image = {
        'id': 'pkg-draft-1',
        'operatorId': UID_OP_A,
        'approvalStatus': 'draft',
        'heroImage': f'http://127.0.0.1:5000/api/public/package-images/{filename}',
    }
    with patch('sequence_contract.firebase_firestore.retrieveRecord', return_value=[package_with_image]):
        del_res = client.delete(
            f'/api/fr12/package-images/{filename}',
            headers=AUTH_OP_A,
        )

    assert del_res.status_code == 409
    assert 'referenced' in del_res.get_json()['error'].lower()
    upload_dir = get_upload_dir()
    assert (upload_dir / filename).exists()


def test_published_package_images_protected_from_deletion(client, mock_multi_auth, temp_upload_dir):
    """Images referenced by an approved/published package are protected (409 Conflict)."""
    data = {'file': (io.BytesIO(SAMPLE_PNG_BYTES), 'published.png', 'image/png')}
    upload_res = client.post(
        '/api/fr12/package-images/upload',
        data=data,
        content_type='multipart/form-data',
        headers=AUTH_OP_A,
    )
    filename = upload_res.get_json()['filename']

    approved_package = {
        'id': 'pkg-approved-1',
        'operatorId': UID_OP_A,
        'approvalStatus': 'approved',
        'galleryImages': [f'http://127.0.0.1:5000/api/public/package-images/{filename}'],
    }
    with patch('sequence_contract.firebase_firestore.retrieveRecord', return_value=[approved_package]):
        del_res = client.delete(
            f'/api/fr12/package-images/{filename}',
            headers=AUTH_OP_A,
        )

    assert del_res.status_code == 409
    assert 'approved' in del_res.get_json()['error'].lower() or 'referenced' in del_res.get_json()['error'].lower()
    upload_dir = get_upload_dir()
    assert (upload_dir / filename).exists()


def test_cross_operator_referenced_image_protected_from_deletion(client, mock_multi_auth, temp_upload_dir):
    """Image referenced by Operator B's package cannot be deleted by Operator A (403 Forbidden)."""
    data = {'file': (io.BytesIO(SAMPLE_PNG_BYTES), 'op_b_pkg_img.png', 'image/png')}
    upload_res = client.post(
        '/api/fr12/package-images/upload',
        data=data,
        content_type='multipart/form-data',
        headers=AUTH_OP_A,
    )
    filename = upload_res.get_json()['filename']

    op_b_package = {
        'id': 'pkg-b-1',
        'operatorId': UID_OP_B,
        'approvalStatus': 'draft',
        'heroImage': f'http://127.0.0.1:5000/api/public/package-images/{filename}',
    }
    with patch('sequence_contract.firebase_firestore.retrieveRecord', return_value=[op_b_package]):
        del_res = client.delete(
            f'/api/fr12/package-images/{filename}',
            headers=AUTH_OP_A,
        )

    assert del_res.status_code == 403
    assert 'another operator' in del_res.get_json()['error'].lower()
    upload_dir = get_upload_dir()
    assert (upload_dir / filename).exists()


def test_unknown_legacy_ownership_fails_closed(client, mock_multi_auth, temp_upload_dir):
    """Existing legacy image without metadata sidecar cannot be deleted by an operator (fails closed, 403)."""
    filename = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png"
    upload_dir = get_upload_dir()
    with open(upload_dir / filename, 'wb') as f:
        f.write(SAMPLE_PNG_BYTES)

    # No .meta.json exists!
    assert not (upload_dir / f"{filename}.meta.json").exists()

    res = client.delete(f'/api/fr12/package-images/{filename}', headers=AUTH_OP_A)
    assert res.status_code == 403
    assert 'ownership' in res.get_json()['error'].lower()
    # File safely preserved!
    assert (upload_dir / filename).exists()


@pytest.mark.parametrize('bad_filename', [
    '../../etc/passwd',
    '..%2F..%2Fetc%2Fpasswd',
    'evil.exe',
    'script.js',
    'short.png',
    'invalid_length.jpg',
])
def test_invalid_image_filename_and_path_traversal_rejected(client, mock_multi_auth, temp_upload_dir, bad_filename):
    """Path traversal and invalid filenames are rejected (400 Bad Request or 404 routing rejection)."""
    res = client.delete(f'/api/fr12/package-images/{bad_filename}', headers=AUTH_OP_A)
    assert res.status_code in (400, 404)


def test_unauthenticated_user_denied_image_deletion(client, mock_multi_auth, temp_upload_dir):
    """Unauthenticated call to delete image returns 401."""
    res = client.delete('/api/fr12/package-images/0123456789abcdef0123456789abcdef.png')
    assert res.status_code == 401


def test_unverified_operator_denied_image_deletion(client, mock_multi_auth, temp_upload_dir):
    """Unverified operator is denied image deletion with 403."""
    res = client.delete(
        '/api/fr12/package-images/0123456789abcdef0123456789abcdef.png',
        headers=AUTH_UNVERIFIED,
    )
    assert res.status_code == 403
    assert 'not verified' in res.get_json()['error'].lower()


def test_admin_can_delete_unreferenced_image(client, mock_multi_auth, temp_upload_dir):
    """Admin retains permission to delete unreferenced images."""
    data = {'file': (io.BytesIO(SAMPLE_PNG_BYTES), 'admin_clean.png', 'image/png')}
    upload_res = client.post(
        '/api/fr12/package-images/upload',
        data=data,
        content_type='multipart/form-data',
        headers=AUTH_OP_A,
    )
    filename = upload_res.get_json()['filename']

    del_res = client.delete(
        f'/api/fr12/package-images/{filename}',
        headers=AUTH_ADMIN,
    )
    assert del_res.status_code == 200
    assert del_res.get_json()['ok'] is True
    assert del_res.get_json()['deleted'] is True


def test_no_unrelated_files_are_removed(client, mock_multi_auth, temp_upload_dir):
    """Deleting one image does not remove any other image in the upload directory."""
    # Upload image 1
    d1 = {'file': (io.BytesIO(SAMPLE_PNG_BYTES), 'img1.png', 'image/png')}
    u1 = client.post('/api/fr12/package-images/upload', data=d1, content_type='multipart/form-data', headers=AUTH_OP_A)
    f1 = u1.get_json()['filename']

    # Upload image 2
    d2 = {'file': (io.BytesIO(SAMPLE_PNG_BYTES), 'img2.png', 'image/png')}
    u2 = client.post('/api/fr12/package-images/upload', data=d2, content_type='multipart/form-data', headers=AUTH_OP_A)
    f2 = u2.get_json()['filename']

    upload_dir = get_upload_dir()
    assert (upload_dir / f1).exists()
    assert (upload_dir / f2).exists()

    # Delete image 1
    del_res = client.delete(f'/api/fr12/package-images/{f1}', headers=AUTH_OP_A)
    assert del_res.status_code == 200

    # Image 1 is deleted, Image 2 remains intact
    assert not (upload_dir / f1).exists()
    assert (upload_dir / f2).exists()
    assert (upload_dir / f"{f2}.meta.json").exists()
