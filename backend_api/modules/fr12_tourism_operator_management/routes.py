import io
from copy import deepcopy
from flask import Blueprint, request, jsonify, g

from auth_utils import auth_required
from utils import utc_now_iso
from request_rate_limit import rate_limit_response
from services.operator_hotel_service import HotelDataError, resolve_package_hotel
from services.review_service import ReviewConflict
from services.operator_package_lifecycle import deletion_blocker, lifecycle_patch

from sequence_contract.validators import validateCampaignDatesAndContent

from sequence_contract.firebase_firestore import (
    retrieveRecord,
    storeRecord,
    updateRecord,
    deleteRecord,
    commitPackageFulfillment,
)

from sequence_contract.domain_functions import (
    createPackage,
    submitForApproval,
    createCampaign,
    calculatePackageViews,
    calculateBookingCount,
    calculateCampaignEngagement
)

from firebase_service import get_db

from flask import send_file
from .analytics_service import generate_business_analytics, _safe_analytics_booking, unique_package_orders, RECORD_LIMIT, is_paid_order
from services.package_checkout_contract import derive_required_services, build_initial_fulfillment_record, fulfillment_readiness
from services.public_content_projection import eligible_package
from services.report_service import export_operator_report
from services.package_service import (
    normalise_package,
    package_for_read,
    package_submission_error,
    package_update_changes_reviewed_content,
    package_validation_error,
)
from services.image_storage_service import (
    validate_image_file,
    save_image_file,
    is_safe_filename,
    delete_image_file,
    save_image_metadata,
    get_image_metadata,
    verify_image_deletion_permission,
)

CAMPAIGN_EDITABLE_FIELDS = {
    'campaignTitle',
    'description',
    'packageId',
    'startDate',
    'endDate',
    'discountType',
    'discountValue',
    'promoCode',
    'bannerImageUrl',
    'termsConditions',
}

PROTECTED_CAMPAIGN_FIELDS = {
    'operatorId',
    'operatorName',
    'reviewStatus',
    'campaignStatus',
    'reviewerId',
    'reviewedBy',
    'reviewedByName',
    'reviewedAt',
    'approvedAt',
    'rejectedAt',
    'reviewComment',
    'reviewReason',
    'submittedAt',
    'createdAt',
    'updatedAt',
    'id',
}

bp=Blueprint('fr12_operator',__name__,url_prefix='/api/fr12')

def _own(collection,id):
    data=retrieveRecord(collection,id)
    return data if data and data.get('operatorId')==g.uid and not (collection == 'tourism_packages' and data.get('deletedAt')) else None
@bp.get('/packages')
@auth_required(['operator'])
def packages():
    items = retrieveRecord('tourism_packages', filters=[('operatorId', '==', g.uid)])
    if not items and g.role == 'admin':
        items = retrieveRecord('tourism_packages')
    return jsonify({'ok': True, 'items': [package_for_read(item) for item in items if not item.get('deletedAt')]})


def _booking_projection(order):
    return {**_safe_analytics_booking(order, include_fulfillment=True), 'paidAt': order.get('paidAt')}


@bp.get('/bookings')
@auth_required(['operator', 'admin'])
def package_bookings():
    filters = [('operatorId', '==', g.uid)] if g.role == 'operator' else None
    orders = retrieveRecord('checkout_orders', filters=filters, limit=RECORD_LIMIT + 1) or []
    items = [
        _booking_projection(order) for order in unique_package_orders(orders[:RECORD_LIMIT])
        if g.role == 'admin' or order.get('operatorId') == g.uid
    ]
    return jsonify({'ok': True, 'items': items, 'dataLimited': len(orders) > RECORD_LIMIT, 'recordLimit': RECORD_LIMIT})


@bp.get('/bookings/<order_reference>')
@auth_required(['operator', 'admin'])
def package_booking_detail(order_reference):
    order = retrieveRecord('checkout_orders', order_reference)
    if not order or order.get('quoteType') != 'package' or (g.role != 'admin' and order.get('operatorId') != g.uid):
        return jsonify({'ok': False, 'error': 'Booking not found'}), 404
    return jsonify({'ok': True, 'booking': _booking_projection(order)})


def _fulfillment_order(order_reference):
    try:
        order = retrieveRecord('checkout_orders', order_reference)
    except Exception:
        return None, (jsonify({'ok': False, 'error': 'Booking storage is temporarily unavailable'}), 503)
    if not order or order.get('quoteType') != 'package':
        return None, (jsonify({'ok': False, 'error': 'Booking not found'}), 404)
    if g.role != 'admin' and order.get('operatorId') != g.uid:
        return None, (jsonify({'ok': False, 'error': 'Booking not owned by this operator'}), 403)
    snapshot = order.get('packageSnapshot')
    if (not isinstance(snapshot, dict) or
            (snapshot.get('operatorId') and snapshot['operatorId'] != order.get('operatorId')) or
            (snapshot.get('packageId') and snapshot['packageId'] != order.get('packageId'))):
        return None, (jsonify({'ok': False, 'error': 'Purchased package ownership is inconsistent'}), 409)
    if not is_paid_order(order):
        return None, (jsonify({'ok': False, 'error': 'Cannot update fulfillment for an unpaid booking'}), 400)
    return order, None


def _fulfillment_payload(fields):
    payload = request.get_json(silent=True)
    if payload is None and not request.data:
        payload = {}
    if not isinstance(payload, dict) or set(payload) - fields:
        return None
    if any(not isinstance(value, str) for value in payload.values()):
        return None
    return {key: value.strip() for key, value in payload.items()}


def _save_fulfillment(order_reference, order, patch):
    from services.review_service import ReviewConflict
    try:
        updated = commitPackageFulfillment(order_reference, order, patch)
        if not updated:
            raise RuntimeError('No persisted result')
        return jsonify({'ok': True, 'booking': _booking_projection(updated)}), 200
    except ReviewConflict:
        return jsonify({'ok': False, 'error': 'Booking changed or linked Trip is unavailable. Refresh and try again.'}), 409
    except Exception:
        return jsonify({'ok': False, 'error': 'Booking storage is temporarily unavailable. Refresh before retrying.'}), 503


def _fulfillment_record(order):
    record = order.get('fulfillmentRecord')
    if not isinstance(record, dict) or not isinstance(record.get('services'), dict):
        record = build_initial_fulfillment_record(order['packageSnapshot'], now=order.get('createdAt'))
    return deepcopy(record)


@bp.post('/bookings/<order_reference>/fulfillment')
@auth_required(['operator', 'admin'])
def update_booking_fulfillment(order_reference):
    order, error = _fulfillment_order(order_reference)
    if error:
        return error
    if order.get('fulfillmentStatus') in {'trip_ready', 'fulfilled', 'fulfillment_declined'}:
        return jsonify({'ok': False, 'error': 'Completed or declined arrangements cannot be changed here'}), 409
    payload = _fulfillment_payload({'serviceType', 'reference', 'supplierName', 'providerName', 'guideOrActivity', 'notes'})
    if payload is None:
        return jsonify({'ok': False, 'error': 'Invalid attestation fields or value types'}), 400
    service_type = payload.get('serviceType')
    if service_type not in {'accommodation', 'transport', 'guideActivities'}:
        return jsonify({'ok': False, 'error': 'Invalid serviceType'}), 400
    reference = payload.get('reference', '')
    name = payload.get('supplierName') or payload.get('providerName') or payload.get('guideOrActivity') or ''
    if service_type == 'transport' and not name:
        return jsonify(ok=False,error='Enter the actual transport provider or internal fleet.'),400
    notes = payload.get('notes', '')
    if not reference or len(reference) > 200 or len(name) > 200 or len(notes) > 2000 or any(ord(c) < 32 for c in reference):
        return jsonify({'ok': False, 'error': 'A valid reservation reference is required (maximum 200 characters).'}), 400
    requirements = derive_required_services(order['packageSnapshot'])
    if not requirements[service_type]['required'] or requirements[service_type].get('uncertain'):
        return jsonify({'ok': False, 'error': 'This service is not a verified included package arrangement'}), 409
    record = _fulfillment_record(order)
    services = record.setdefault('services', {})
    name_field = {'accommodation': 'supplierName', 'transport': 'providerName', 'guideActivities': 'guideOrActivity'}[service_type]
    previous = services.get(service_type) or {}
    if (previous.get('status') == 'confirmed' and previous.get('reference') == reference and
            previous.get('notes', '') == notes and previous.get(name_field, '') == (name or previous.get(name_field, ''))):
        return _save_fulfillment(order_reference, order, {})
    now = utc_now_iso()
    services[service_type] = {**previous, 'required': True, 'status': 'confirmed',
        'reference': reference, name_field: name or previous.get(name_field, ''), 'notes': notes,
        'confirmedAt': now, 'confirmedBy': g.uid, 'provenance': 'operator_attested'}
    record.update({'status': 'partially_fulfilled', 'updatedAt': now, 'requiredServices': requirements})
    return _save_fulfillment(order_reference, order, {
        'fulfillmentRecord': record, 'fulfillmentStatus': 'partially_fulfilled',
        'supplierReservationStatus': 'not_created', 'updatedAt': now})


@bp.post('/bookings/<order_reference>/confirm-fulfillment')
@auth_required(['operator', 'admin'])
def confirm_booking_fulfillment(order_reference):
    order, error = _fulfillment_order(order_reference)
    if error:
        return error
    if _fulfillment_payload(set()) is None:
        return jsonify({'ok': False, 'error': 'Confirmation does not accept booking field overrides'}), 400
    if order.get('fulfillmentStatus') in {'fulfillment_declined', 'fulfilled'}:
        return jsonify({'ok': False, 'error': 'Declined or legacy fulfilled arrangements require review'}), 409
    if order.get('fulfillmentStatus') == 'trip_ready':
        return _save_fulfillment(order_reference, order, {})
    record = _fulfillment_record(order)
    requirements = derive_required_services(order['packageSnapshot'])
    if any(meta.get('uncertain') for meta in requirements.values()):
        return jsonify({'ok': False, 'error': 'Purchased brochure does not reliably establish included services. Review is required.'}), 409
    readiness = fulfillment_readiness(order, requirements, record, True)
    if not readiness['canMarkReady']:
        return jsonify(ok=False,error='Cannot confirm fulfillment: arrangements have not been attested. ' + ' '.join(readiness['blockers'])),400
    now = utc_now_iso()
    record.update({'status': 'trip_ready', 'confirmedAt': now, 'confirmedBy': g.uid,
                   'updatedAt': now, 'requiredServices': requirements})
    # No supplier reservation is claimed when no supplier service was included.
    supplier_status = 'operator_attested' if any(meta['required'] for meta in requirements.values()) else 'not_required'
    return _save_fulfillment(order_reference, order, {
        'fulfillmentStatus': 'trip_ready', 'supplierReservationStatus': supplier_status,
        'fulfillmentRecord': record, 'updatedAt': now})


@bp.post('/bookings/<order_reference>/decline')
@auth_required(['operator', 'admin'])
def decline_booking_fulfillment(order_reference):
    order, error = _fulfillment_order(order_reference)
    if error:
        return error
    if order.get('fulfillmentStatus') in {'trip_ready', 'fulfilled'}:
        return jsonify({'ok': False, 'error': 'Cannot decline completed arrangements here'}), 409
    payload = _fulfillment_payload({'reason'})
    reason = payload.get('reason', '') if payload is not None else ''
    if not 5 <= len(reason) <= 2000:
        return jsonify({'ok': False, 'error': 'A detailed reason (at least 5 characters, maximum 2000) is required.'}), 400
    if order.get('fulfillmentStatus') == 'fulfillment_declined':
        if (order.get('fulfillmentRecord') or {}).get('declineReason') != reason:
            return jsonify({'ok': False, 'error': 'Booking is already declined'}), 409
        return _save_fulfillment(order_reference, order, {})
    now = utc_now_iso()
    record = _fulfillment_record(order)
    record.update({'status': 'fulfillment_declined', 'declineReason': reason, 'declinedAt': now,
                   'declinedBy': g.uid, 'updatedAt': now})
    return _save_fulfillment(order_reference, order, {
        'fulfillmentStatus': 'fulfillment_declined', 'supplierReservationStatus': 'declined',
        'fulfillmentRecord': record, 'updatedAt': now})


def _hotel_package_payload(payload, current=None):
    if payload.get('hotelSelection') is not None:
        if g.role != 'operator':
            return None, (jsonify(ok=False,error='Verified Tourism Operator access is required.'),403)
        limited = rate_limit_response('provider_search', g.uid)
        if limited is not None:
            return None, limited
    try:
        return resolve_package_hotel(payload, current), None
    except HotelDataError as error:
        response = jsonify(ok=False,error=str(error),code=error.code)
        if error.status == 429:response.headers['Retry-After']='60'
        return None, (response,error.status)


@bp.post('/packages')
@auth_required(['operator'])
def create_package_route():
    payload=request.get_json(silent=True) or {}
    if not isinstance(payload, dict):return jsonify({'ok':False,'error':'Package data must be an object'}),400
    error=package_validation_error(payload)
    if error:return jsonify({'ok':False,'error':error}),400
    payload, error = _hotel_package_payload(payload)
    if error is not None:return error
    profile=retrieveRecord('users',g.uid) or {}
    package=normalise_package(payload)
    package.update({
        'operatorName':profile.get('companyName') or profile.get('businessName') or profile.get('name') or 'TravelMate Tourism Operator',
        'operatorEmail':profile.get('businessEmail') or profile.get('email') or '',
        'operatorPhone':profile.get('businessContact') or profile.get('phoneNo') or profile.get('phone') or '',
    })
    if 'accommodationHotel' in package:
        try:
            result = storeRecord('tourism_packages', createPackage(package,g.uid))
            if not result:raise RuntimeError('Package write failed')
        except Exception:
            return jsonify(ok=False,error='Package could not be saved. Reload and try again.'),503
    else:
        result=storeRecord('tourism_packages',createPackage(package,g.uid))
    return jsonify({'ok':True,'id':result['id'],'package':package_for_read(result)}),201
@bp.put('/packages/<pid>')
@auth_required(['operator'])
def update_package(pid):
    current=_own('tourism_packages',pid)
    if not current:return jsonify({'ok':False,'error':'Package not found'}),404
    if current.get('approvalStatus') in {'pending','submitted'}:return jsonify({'ok':False,'error':'Package cannot be edited in its current state'}),409
    payload=request.get_json(silent=True) or {}
    if not isinstance(payload, dict):return jsonify({'ok':False,'error':'Package data must be an object'}),400
    merged={**current, **payload}; error=package_validation_error(merged)
    if error:return jsonify({'ok':False,'error':error}),400
    hotel_edit = 'hotelSelection' in payload or bool(current.get('accommodationHotel'))
    payload, error = _hotel_package_payload(payload, current)
    if error is not None:return error
    updates=normalise_package(payload,current)
    if current.get('approvalStatus') == 'archived':
        updates.update(lifecycle_patch(current, g.uid, 'edited_archived', 'archived'))
        updates['archiveRequiresReview'] = bool(current.get('archiveRequiresReview') or package_update_changes_reviewed_content(current, payload))
    if current.get('approvalStatus')=='approved' and package_update_changes_reviewed_content(current,payload):
        updates.update({'approvalStatus':'draft','reviewReason':'','reviewComment':'','reviewedAt':'','reviewedBy':'','reviewedByName':'','submittedAt':''})
    updates['updatedAt']=utc_now_iso()
    try:
        saved = updateRecord('tourism_packages', pid, updates, **({'expected': current} if hotel_edit or current.get('approvalStatus') == 'archived' else {}))
        if not saved:
            return jsonify(ok=False,error='Package could not be saved. Reload and try again.'),503
        return jsonify({'ok':True,'package':package_for_read(saved)})
    except ReviewConflict:
        return jsonify(ok=False,error='Package changed. Reload and try again.'),409
    except Exception:
        return jsonify(ok=False,error='Package could not be saved. Reload and try again.'),503
@bp.delete('/packages/<pid>')
@auth_required(['operator'])
def delete_package(pid):
    current=retrieveRecord('tourism_packages',pid)
    if not current or current.get('operatorId') != g.uid:return jsonify({'ok':False,'error':'Package not found'}),404
    if current.get('deletedAt'):return jsonify(ok=True, idempotent=True)
    if current.get('approvalStatus') not in {'draft','rejected','archived'}:
        return jsonify({'ok':False,'error':'Submitted, approved or suspended packages cannot be deleted'}),409
    try:
        blocker = deletion_blocker(retrieveRecord, pid)
        if blocker:return jsonify(ok=False, error=blocker),409
        patch = lifecycle_patch(current, g.uid, 'deleted', 'archived')
        patch.update(deletedAt=patch['updatedAt'], deletedBy=g.uid)
        # A retained tombstone also protects a late in-flight checkout and approval audit metadata.
        saved = updateRecord('tourism_packages', pid, patch, expected=current)
        if not saved:raise RuntimeError('Package not saved')
    except ReviewConflict:
        return jsonify(ok=False,error='Package changed. Reload before deleting.'),409
    except Exception:
        return jsonify(ok=False,error='Package dependencies could not be verified or deletion could not be saved. Try again later.'),503
    return jsonify(ok=True, deletionMode='soft_delete')
@bp.post('/packages/<pid>/submit')
@auth_required(['operator'])
def submit_package(pid):
    current=_own('tourism_packages',pid)
    if not current:return jsonify({'ok':False,'error':'Package not found'}),404
    if current.get('approvalStatus') not in {'draft','rejected','suspended'}:return jsonify({'ok':False,'error':'Only draft, rejected or suspended packages can be submitted'}),409
    error=package_submission_error(current)
    if error:return jsonify({'ok':False,'error':error}),400
    return jsonify({'ok':True,'package':updateRecord('tourism_packages',pid,submitForApproval(current)),'status':'pending'})

@bp.post('/packages/<pid>/archive')
@auth_required(['operator'])
def archive_package(pid):
    current=_own('tourism_packages',pid)
    if not current:return jsonify({'ok':False,'error':'Package not found'}),404
    if current.get('approvalStatus') in {'pending','submitted','suspended'}:return jsonify({'ok':False,'error':'A package under review or suspension cannot be archived'}),409
    if current.get('approvalStatus') == 'archived':return jsonify(ok=True,package=package_for_read(current),idempotent=True)
    patch = lifecycle_patch(current, g.uid, 'archived', 'archived')
    patch.update(archivedAt=patch['updatedAt'], archivedBy=g.uid)
    return _save_package_transition(pid, current, patch)


def _save_package_transition(pid, current, patch):
    try:
        saved = updateRecord('tourism_packages', pid, patch, expected=current)
        if not saved:raise RuntimeError('Package not saved')
        return jsonify(ok=True, package=package_for_read(saved))
    except ReviewConflict:
        return jsonify(ok=False,error='Package changed. Reload and try again.'),409
    except Exception:
        return jsonify(ok=False,error='Package changes could not be saved. Try again later.'),503


@bp.post('/packages/<pid>/restore')
@auth_required(['operator'])
def restore_package(pid):
    current = _own('tourism_packages', pid)
    if not current:return jsonify(ok=False,error='Package not found'),404
    if current.get('approvalStatus') != 'archived':
        if current.get('approvalStatus') == 'draft' and current.get('restoredAt'):
            return jsonify(ok=True,package=package_for_read(current),idempotent=True)
        return jsonify(ok=False,error='Only archived packages can be restored.'),409
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):return jsonify(ok=False,error='Restore data must be an object.'),400
    if 'expectedUpdatedAt' in payload and payload['expectedUpdatedAt'] != current.get('updatedAt'):
        return jsonify(ok=False,error='Package changed. Reload before restoring.'),409
    patch = lifecycle_patch(current, g.uid, 'restored', 'draft')
    patch.update(restoredAt=patch['updatedAt'], restoredBy=g.uid)
    return _save_package_transition(pid, current, patch)
@bp.get('/campaigns')
@auth_required(['operator'])
def campaigns():return jsonify({'ok':True,'items':retrieveRecord('promotional_campaigns',filters=[('operatorId','==',g.uid)])})
@bp.post('/campaigns')
@auth_required(['operator'])
def create_campaign_route():
    from services.campaign_schedule import campaign_schedule_error
    payload=request.get_json(silent=True) or {}
    if not isinstance(payload, dict):return jsonify({'ok':False,'error':'Campaign data must be an object'}),400
    disallowed = [k for k in payload if k in PROTECTED_CAMPAIGN_FIELDS]
    if disallowed:
        return jsonify({'ok':False,'error':f'Field "{disallowed[0]}" is protected and cannot be supplied by operator'}),400
    schedule_error = campaign_schedule_error(payload, new=True)
    if schedule_error:return jsonify({'ok': False, 'error': schedule_error}), 400
    if not validateCampaignDatesAndContent(payload):return jsonify({'ok':False,'error':'Invalid campaign dates or content'}),400
    pid=str(payload.get('packageId','')).strip()
    if pid:
        pkg=_own('tourism_packages',pid)
        if not pkg:return jsonify({'ok':False,'error':'Related package not found'}),404
        if not eligible_package(pkg):return jsonify({'ok':False,'error':'Promotional campaign requires an approved package'}),409
    profile=retrieveRecord('users',g.uid) or {}
    campaign_data = {k: payload[k] for k in payload if k in CAMPAIGN_EDITABLE_FIELDS}
    campaign_data['operatorName']=profile.get('companyName') or profile.get('businessName') or profile.get('name') or 'TravelMate Tourism Operator'
    result=storeRecord('promotional_campaigns',createCampaign(campaign_data,g.uid)); return jsonify({'ok':True,'id':result['id'],'campaign':result}),201
@bp.put('/campaigns/<cid>')
@auth_required(['operator'])
def update_campaign(cid):
    from services.campaign_schedule import campaign_schedule_error
    current=_own('promotional_campaigns',cid)
    if not current:return jsonify({'ok':False,'error':'Campaign not found'}),404
    if current.get('reviewStatus') in {'pending','submitted','under_review'}:return jsonify({'ok':False,'error':'Campaign under administrator review cannot be edited'}),409
    payload=request.get_json(silent=True) or {}
    if not isinstance(payload, dict):return jsonify({'ok':False,'error':'Campaign data must be an object'}),400
    if not payload:
        return jsonify({'ok':False,'error':'No update data provided'}),400
    disallowed = [k for k in payload if k in PROTECTED_CAMPAIGN_FIELDS]
    if disallowed:
        return jsonify({'ok':False,'error':f'Field "{disallowed[0]}" is protected and cannot be modified by operator'}),400
    updates = {k: payload[k] for k in payload if k in CAMPAIGN_EDITABLE_FIELDS}
    if not updates:
        return jsonify({'ok':False,'error':'No editable content fields provided'}),400
    merged = {**current, **updates}
    schedule_error = campaign_schedule_error(merged, previous=current)
    if schedule_error:return jsonify({'ok': False, 'error': schedule_error}), 400
    if not validateCampaignDatesAndContent(merged):return jsonify({'ok':False,'error':'Invalid campaign dates or content'}),400
    if 'packageId' in updates:
        pid=str(updates.get('packageId','')).strip()
        if pid:
            pkg=_own('tourism_packages',pid)
            if not pkg:return jsonify({'ok':False,'error':'Related package not found'}),404
            if not eligible_package(pkg):return jsonify({'ok':False,'error':'Promotional campaign requires an approved package'}),409
    updates['updatedAt']=utc_now_iso()
    if current.get('reviewStatus') == 'approved':
        updates.update({
            'reviewStatus': 'draft',
            'campaignStatus': 'draft',
            'reviewComment': '',
            'reviewReason': '',
            'reviewedBy': '',
            'reviewedByName': '',
            'reviewedAt': '',
            'approvedAt': '',
            'rejectedAt': '',
            'submittedAt': '',
        })
    return jsonify({'ok':True,'campaign':updateRecord('promotional_campaigns',cid,updates)})
@bp.delete('/campaigns/<cid>')
@auth_required(['operator'])
def delete_campaign(cid):
    current=_own('promotional_campaigns',cid)
    if not current:return jsonify({'ok':False,'error':'Campaign not found'}),404
    if current.get('campaignStatus')=='active' or current.get('reviewStatus')=='pending':return jsonify({'ok':False,'error':'Campaign cannot be deleted in its current state'}),409
    deleteRecord('promotional_campaigns',cid); return jsonify({'ok':True})
@bp.post('/campaigns/<cid>/submit')
@auth_required(['operator'])
def submit_campaign(cid):
    from services.campaign_schedule import campaign_schedule_error
    current = _own(
        'promotional_campaigns',
        cid
    )

    if not current:
        return jsonify({
            'ok': False,
            'error': 'Campaign not found'
        }), 404

    if current.get('reviewStatus', 'draft') not in {'draft', 'rejected'}:
        return jsonify({'ok': False, 'error': 'Only draft or rejected campaigns can be submitted.'}), 409
    schedule_error = campaign_schedule_error(current, publishing=True)
    if schedule_error:return jsonify({'ok': False, 'error': schedule_error}), 400
    if not validateCampaignDatesAndContent(current):
        return jsonify({'ok': False, 'error': 'Invalid campaign dates or content'}), 400
    package = _own('tourism_packages', str(current.get('packageId') or '').strip())
    if not package:
        return jsonify({'ok': False, 'error': 'Related package not found'}), 404
    if not eligible_package(package):
        return jsonify({'ok': False, 'error': 'Promotional campaign requires an approved package'}), 409

    return jsonify({
        'ok': True,
        'campaign': updateRecord(
            'promotional_campaigns',
            cid,
            {
                'reviewStatus': 'pending',
                'campaignStatus': 'draft',
                'submittedAt': utc_now_iso(),
                'updatedAt': utc_now_iso()
            }
        ),
        'status': 'pending'
    })


# ==========================================================
# BUSINESS ANALYTICS
# ==========================================================

@bp.get('/analytics')
@auth_required(['operator'])
def analytics():
    db = get_db()
    operator_id = g.uid
    report = generate_business_analytics(
        db=db,
        operator_id=operator_id
    )
    if g.role == 'admin' and report.get('summary', {}).get('totalPackages', 0) == 0:
        report = generate_business_analytics(
            db=db,
            operator_id=None
        )
    return jsonify({
        'ok': True,
        'analytics': report
    }), 200

#report export
@bp.get("/reports/export")
@auth_required(['operator'])
def export_report():
    db = get_db()
    operator_id = g.uid
    report = generate_business_analytics(
        db=db,
        operator_id=operator_id
    )
    if g.role == 'admin' and report.get('summary', {}).get('totalPackages', 0) == 0:
        report = generate_business_analytics(
            db=db,
            operator_id=None
        )
    profile = retrieveRecord('users', g.uid) or g.profile or {}
    buffer = io.BytesIO()
    export_operator_report(
        report,
        buffer,
        operator_profile=profile
    )
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="Tourism_Operator_Business_Report.pdf"
    )


# ==========================================================
# PACKAGE IMAGE UPLOADS
# ==========================================================

@bp.post('/package-images/upload')
@auth_required(['operator'])
def upload_package_image():
    if 'file' not in request.files and 'image' not in request.files:
        return jsonify({'ok': False, 'error': 'No image file provided'}), 400
    file = request.files.get('file') or request.files.get('image')
    ok, error_msg, ext = validate_image_file(file)
    if not ok:
        return jsonify({'ok': False, 'error': error_msg}), 400
    filename, url = save_image_file(file, ext, host_url=request.host_url)
    save_image_metadata(
        filename,
        owner_id=g.uid,
        original_name=getattr(file, 'filename', '')
    )
    return jsonify({
        'ok': True,
        'filename': filename,
        'url': url,
    }), 201


@bp.delete('/package-images/<filename>')
@auth_required(['operator'])
def delete_package_image(filename):
    if not is_safe_filename(filename):
        return jsonify({'ok': False, 'error': 'Invalid image filename'}), 400

    is_admin = (getattr(g, 'role', '') == 'admin')
    allowed, status_code, error_msg = verify_image_deletion_permission(
        filename,
        current_operator_id=g.uid,
        is_admin=is_admin
    )
    if not allowed:
        return jsonify({'ok': False, 'error': error_msg}), status_code

    deleted = delete_image_file(filename)
    return jsonify({'ok': True, 'deleted': deleted})

