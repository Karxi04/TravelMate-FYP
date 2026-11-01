import io
from flask import Blueprint, request, jsonify, g

from auth_utils import auth_required
from utils import utc_now_iso

from sequence_contract.validators import validateCampaignDatesAndContent

from sequence_contract.firebase_firestore import (
    retrieveRecord,
    storeRecord,
    updateRecord,
    deleteRecord
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
from services.package_checkout_contract import derive_required_services, build_initial_fulfillment_record
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
    data=retrieveRecord(collection,id); return data if data and data.get('operatorId')==g.uid else None
@bp.get('/packages')
@auth_required(['operator'])
def packages():
    items = retrieveRecord('tourism_packages', filters=[('operatorId', '==', g.uid)])
    if not items and g.role == 'admin':
        items = retrieveRecord('tourism_packages')
    return jsonify({'ok': True, 'items': [package_for_read(item) for item in items]})


def _booking_projection(order):
    return _safe_analytics_booking(order, include_fulfillment=True)


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


@bp.post('/bookings/<order_reference>/fulfillment')
@auth_required(['operator', 'admin'])
def update_booking_fulfillment(order_reference):
    order = retrieveRecord('checkout_orders', order_reference)
    if not order or order.get('quoteType') != 'package':
        return jsonify({'ok': False, 'error': 'Booking not found'}), 404
    if g.role != 'admin' and order.get('operatorId') != g.uid:
        return jsonify({'ok': False, 'error': 'Booking not owned by this operator'}), 403
    if not is_paid_order(order):
        return jsonify({'ok': False, 'error': 'Cannot update fulfillment for an unpaid booking'}), 400
    if order.get('fulfillmentStatus') == 'fulfillment_declined':
        return jsonify({'ok': False, 'error': 'Fulfillment for this booking has been declined'}), 409

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({'ok': False, 'error': 'Payload must be a JSON object'}), 400

    service_type = str(payload.get('serviceType') or '').strip()
    valid_services = {'accommodation', 'transport', 'guideActivities'}
    if service_type not in valid_services:
        return jsonify({'ok': False, 'error': f'Invalid serviceType. Must be one of: {", ".join(sorted(valid_services))}'}), 400

    reference = str(payload.get('reference') or '').strip()
    if not reference:
        return jsonify({'ok': False, 'error': 'Booking or reservation reference is required'}), 400

    supplier_name = str(payload.get('supplierName') or payload.get('providerName') or payload.get('guideOrActivity') or '').strip()
    notes = str(payload.get('notes') or '').strip()

    snapshot = order.get('packageSnapshot') or {}
    ful_record = order.get('fulfillmentRecord')
    if not isinstance(ful_record, dict) or not ful_record.get('services'):
        ful_record = build_initial_fulfillment_record(snapshot, now=order.get('createdAt'))

    now = utc_now_iso()
    svc = ful_record.setdefault('services', {}).setdefault(service_type, {})
    svc['status'] = 'confirmed'
    svc['reference'] = reference
    svc['notes'] = notes
    svc['confirmedAt'] = now
    svc['confirmedBy'] = g.uid
    svc['provenance'] = 'operator_attested'

    if service_type == 'accommodation':
        svc['supplierName'] = supplier_name or svc.get('supplierName') or ''
    elif service_type == 'transport':
        svc['providerName'] = supplier_name or svc.get('providerName') or ''
    elif service_type == 'guideActivities':
        svc['guideOrActivity'] = supplier_name or svc.get('guideOrActivity') or ''

    ful_record['updatedAt'] = now
    current_ful_status = order.get('fulfillmentStatus')
    new_ful_status = current_ful_status
    if current_ful_status in {'awaiting_operator_fulfillment', 'fulfillment_pending', None}:
        new_ful_status = 'partially_fulfilled'
    ful_record['status'] = new_ful_status

    order_patch = {
        'fulfillmentRecord': ful_record,
        'fulfillmentStatus': new_ful_status,
        'updatedAt': now,
    }
    updated_order = updateRecord('checkout_orders', order_reference, order_patch) or {**order, **order_patch}

    trip_id = order.get('fulfilledTripId')
    if trip_id:
        updateRecord('itineraries', trip_id, {
            'fulfillmentRecord': ful_record,
            'fulfillmentStatus': new_ful_status,
            'updatedAt': now,
        })

    return jsonify({'ok': True, 'booking': _booking_projection(updated_order)}), 200


@bp.post('/bookings/<order_reference>/confirm-fulfillment')
@auth_required(['operator', 'admin'])
def confirm_booking_fulfillment(order_reference):
    order = retrieveRecord('checkout_orders', order_reference)
    if not order or order.get('quoteType') != 'package':
        return jsonify({'ok': False, 'error': 'Booking not found'}), 404
    if g.role != 'admin' and order.get('operatorId') != g.uid:
        return jsonify({'ok': False, 'error': 'Booking not owned by this operator'}), 403
    if not is_paid_order(order):
        return jsonify({'ok': False, 'error': 'Cannot confirm fulfillment for an unpaid booking'}), 400
    if order.get('fulfillmentStatus') == 'fulfillment_declined':
        return jsonify({'ok': False, 'error': 'Fulfillment for this booking has been declined'}), 409

    snapshot = order.get('packageSnapshot') or {}
    ful_record = order.get('fulfillmentRecord')
    if not isinstance(ful_record, dict) or not ful_record.get('services'):
        ful_record = build_initial_fulfillment_record(snapshot, now=order.get('createdAt'))

    req_services = ful_record.get('requiredServices') or derive_required_services(snapshot)
    services = ful_record.get('services') or {}

    labels = {
        'accommodation': 'Accommodation',
        'transport': 'Ground Transportation',
        'guideActivities': 'Guide & Activities',
    }
    for svc_key, meta in req_services.items():
        if isinstance(meta, dict) and meta.get('required'):
            svc_data = services.get(svc_key) or {}
            if svc_data.get('status') != 'confirmed' or not str(svc_data.get('reference') or '').strip():
                label = labels.get(svc_key, svc_key)
                return jsonify({
                    'ok': False,
                    'error': f'Cannot confirm fulfillment: {label} arrangements have not been attested.'
                }), 400

    now = utc_now_iso()
    ful_record['status'] = 'trip_ready'
    ful_record['confirmedAt'] = now
    ful_record['confirmedBy'] = g.uid
    ful_record['updatedAt'] = now

    order_patch = {
        'fulfillmentStatus': 'trip_ready',
        'supplierReservationStatus': 'operator_attested',
        'fulfillmentRecord': ful_record,
        'updatedAt': now,
    }
    updated_order = updateRecord('checkout_orders', order_reference, order_patch) or {**order, **order_patch}

    trip_id = order.get('fulfilledTripId')
    if trip_id:
        updateRecord('itineraries', trip_id, {
            'supplierReservationStatus': 'operator_attested',
            'fulfillmentStatus': 'trip_ready',
            'fulfillmentRecord': ful_record,
            'updatedAt': now,
        })

    return jsonify({'ok': True, 'booking': _booking_projection(updated_order)}), 200


@bp.post('/bookings/<order_reference>/decline')
@auth_required(['operator', 'admin'])
def decline_booking_fulfillment(order_reference):
    order = retrieveRecord('checkout_orders', order_reference)
    if not order or order.get('quoteType') != 'package':
        return jsonify({'ok': False, 'error': 'Booking not found'}), 404
    if g.role != 'admin' and order.get('operatorId') != g.uid:
        return jsonify({'ok': False, 'error': 'Booking not owned by this operator'}), 403
    if order.get('fulfillmentStatus') == 'trip_ready':
        return jsonify({'ok': False, 'error': 'Cannot decline a booking that is already confirmed and trip-ready.'}), 409

    payload = request.get_json(silent=True) or {}
    reason = str((payload.get('reason') if isinstance(payload, dict) else '') or '').strip()
    if len(reason) < 5:
        return jsonify({'ok': False, 'error': 'A detailed reason (at least 5 characters) is required to decline fulfillment.'}), 400

    snapshot = order.get('packageSnapshot') or {}
    ful_record = order.get('fulfillmentRecord')
    if not isinstance(ful_record, dict) or not ful_record.get('services'):
        ful_record = build_initial_fulfillment_record(snapshot, now=order.get('createdAt'))

    now = utc_now_iso()
    ful_record['status'] = 'fulfillment_declined'
    ful_record['declineReason'] = reason
    ful_record['declinedAt'] = now
    ful_record['declinedBy'] = g.uid
    ful_record['updatedAt'] = now

    order_patch = {
        'fulfillmentStatus': 'fulfillment_declined',
        'supplierReservationStatus': 'declined',
        'fulfillmentRecord': ful_record,
        'updatedAt': now,
    }
    updated_order = updateRecord('checkout_orders', order_reference, order_patch) or {**order, **order_patch}

    trip_id = order.get('fulfilledTripId')
    if trip_id:
        updateRecord('itineraries', trip_id, {
            'supplierReservationStatus': 'declined',
            'fulfillmentStatus': 'fulfillment_declined',
            'fulfillmentRecord': ful_record,
            'updatedAt': now,
        })

    return jsonify({'ok': True, 'booking': _booking_projection(updated_order)}), 200


@bp.post('/packages')
@auth_required(['operator'])
def create_package_route():
    payload=request.get_json(silent=True) or {}
    if not isinstance(payload, dict):return jsonify({'ok':False,'error':'Package data must be an object'}),400
    error=package_validation_error(payload)
    if error:return jsonify({'ok':False,'error':error}),400
    profile=retrieveRecord('users',g.uid) or {}
    package=normalise_package(payload)
    package.update({
        'operatorName':profile.get('companyName') or profile.get('businessName') or profile.get('name') or 'TravelMate Tourism Operator',
        'operatorEmail':profile.get('businessEmail') or profile.get('email') or '',
        'operatorPhone':profile.get('businessContact') or profile.get('phoneNo') or profile.get('phone') or '',
    })
    result=storeRecord('tourism_packages',createPackage(package,g.uid)); return jsonify({'ok':True,'id':result['id'],'package':package_for_read(result)}),201
@bp.put('/packages/<pid>')
@auth_required(['operator'])
def update_package(pid):
    current=_own('tourism_packages',pid)
    if not current:return jsonify({'ok':False,'error':'Package not found'}),404
    if current.get('approvalStatus') in {'pending','submitted','archived'}:return jsonify({'ok':False,'error':'Package cannot be edited in its current state'}),409
    payload=request.get_json(silent=True) or {}
    if not isinstance(payload, dict):return jsonify({'ok':False,'error':'Package data must be an object'}),400
    merged={**current, **payload}; error=package_validation_error(merged)
    if error:return jsonify({'ok':False,'error':error}),400
    updates=normalise_package(payload,current)
    if current.get('approvalStatus')=='approved' and package_update_changes_reviewed_content(current,payload):
        updates.update({'approvalStatus':'draft','reviewReason':'','reviewComment':'','reviewedAt':'','reviewedBy':'','reviewedByName':'','submittedAt':''})
    updates['updatedAt']=utc_now_iso(); return jsonify({'ok':True,'package':package_for_read(updateRecord('tourism_packages',pid,updates))})
@bp.delete('/packages/<pid>')
@auth_required(['operator'])
def delete_package(pid):
    current=_own('tourism_packages',pid)
    if not current:return jsonify({'ok':False,'error':'Package not found'}),404
    if current.get('approvalStatus') in {'pending','submitted','approved','suspended'}:return jsonify({'ok':False,'error':'Submitted, approved or suspended packages cannot be deleted'}),409
    if retrieveRecord('checkout_orders', filters=[('packageId', '==', pid)], limit=1):
        return jsonify({'ok': False, 'error': 'Packages with order history must be archived, not deleted.'}), 409
    deleteRecord('tourism_packages',pid); return jsonify({'ok':True})
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
    return jsonify({'ok':True,'package':updateRecord('tourism_packages',pid,{'approvalStatus':'archived','updatedAt':utc_now_iso()})})
@bp.get('/campaigns')
@auth_required(['operator'])
def campaigns():return jsonify({'ok':True,'items':retrieveRecord('promotional_campaigns',filters=[('operatorId','==',g.uid)])})
@bp.post('/campaigns')
@auth_required(['operator'])
def create_campaign_route():
    payload=request.get_json(silent=True) or {}
    if not isinstance(payload, dict):return jsonify({'ok':False,'error':'Campaign data must be an object'}),400
    disallowed = [k for k in payload if k in PROTECTED_CAMPAIGN_FIELDS]
    if disallowed:
        return jsonify({'ok':False,'error':f'Field "{disallowed[0]}" is protected and cannot be supplied by operator'}),400
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

