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
from .analytics_service import generate_business_analytics
from services.report_service import export_operator_report
from services.package_service import (
    normalise_package,
    package_for_read,
    package_submission_error,
    package_validation_error,
)
from services.image_storage_service import (
    validate_image_file,
    save_image_file,
    is_safe_filename,
    delete_image_file,
)

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
    snapshot = order.get('packageSnapshot') or {}
    participants = order.get('participants') or snapshot.get('participants') or {}
    return {
        'orderReference': order.get('id'),
        'packageId': order.get('packageId') or snapshot.get('packageId'),
        'packageTitle': snapshot.get('title'),
        'departureDate': order.get('departureDate') or snapshot.get('selectedDepartureDate'),
        'groupSize': order.get('groupSize') or snapshot.get('groupSize') or participants.get('total'),
        'adults': participants.get('adults'), 'children': participants.get('children'),
        'paymentStatus': order.get('paymentStatus'), 'orderStatus': order.get('status'),
        'fulfillmentStatus': order.get('fulfillmentStatus'),
        'groupTotal': order.get('amount'), 'currency': order.get('currency'),
        'supplierReservationStatus': 'not_created',
        'testMode': order.get('provider') == 'stripe_checkout_test',
        'createdAt': order.get('createdAt'),
    }


@bp.get('/bookings')
@auth_required(['operator', 'admin'])
def package_bookings():
    filters = [('operatorId', '==', g.uid)] if g.role == 'operator' else None
    orders = retrieveRecord('checkout_orders', filters=filters) or []
    items = [
        _booking_projection(order) for order in orders
        if isinstance(order, dict) and order.get('quoteType') == 'package'
    ]
    return jsonify({'ok': True, 'items': items})


@bp.post('/packages')
@auth_required(['operator'])
def create_package_route():
    payload=request.get_json(silent=True) or {}
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
    merged={**current, **payload}; error=package_validation_error(merged)
    if error:return jsonify({'ok':False,'error':error}),400
    updates=normalise_package(payload,current)
    if current.get('approvalStatus')=='approved':
        updates.update({'approvalStatus':'draft','reviewReason':'','reviewComment':'','reviewedAt':'','reviewedBy':'','reviewedByName':'','submittedAt':''})
    updates['updatedAt']=utc_now_iso(); return jsonify({'ok':True,'package':package_for_read(updateRecord('tourism_packages',pid,updates))})
@bp.delete('/packages/<pid>')
@auth_required(['operator'])
def delete_package(pid):
    current=_own('tourism_packages',pid)
    if not current:return jsonify({'ok':False,'error':'Package not found'}),404
    if current.get('approvalStatus') in {'pending','submitted','approved'}:return jsonify({'ok':False,'error':'Submitted or approved packages must be archived instead'}),409
    deleteRecord('tourism_packages',pid); return jsonify({'ok':True})
@bp.post('/packages/<pid>/submit')
@auth_required(['operator'])
def submit_package(pid):
    current=_own('tourism_packages',pid)
    if not current:return jsonify({'ok':False,'error':'Package not found'}),404
    if current.get('approvalStatus') not in {'draft','rejected'}:return jsonify({'ok':False,'error':'Only draft or rejected packages can be submitted'}),409
    error=package_submission_error(current)
    if error:return jsonify({'ok':False,'error':error}),400
    return jsonify({'ok':True,'package':updateRecord('tourism_packages',pid,submitForApproval(current)),'status':'pending'})

@bp.post('/packages/<pid>/archive')
@auth_required(['operator'])
def archive_package(pid):
    current=_own('tourism_packages',pid)
    if not current:return jsonify({'ok':False,'error':'Package not found'}),404
    if current.get('approvalStatus') in {'pending','submitted'}:return jsonify({'ok':False,'error':'A package under review cannot be archived'}),409
    return jsonify({'ok':True,'package':updateRecord('tourism_packages',pid,{'approvalStatus':'archived','updatedAt':utc_now_iso()})})
@bp.get('/campaigns')
@auth_required(['operator'])
def campaigns():return jsonify({'ok':True,'items':retrieveRecord('promotional_campaigns',filters=[('operatorId','==',g.uid)])})
@bp.post('/campaigns')
@auth_required(['operator'])
def create_campaign_route():
    payload=request.get_json(silent=True) or {}
    if not validateCampaignDatesAndContent(payload):return jsonify({'ok':False,'error':'Invalid campaign dates or content'}),400
    pid=str(payload.get('packageId','')).strip()
    if pid:
        pkg=_own('tourism_packages',pid)
        if not pkg:return jsonify({'ok':False,'error':'Related package not found'}),404
        if pkg.get('approvalStatus')!='approved':return jsonify({'ok':False,'error':'Promotional campaign requires an approved package'}),409
    profile=retrieveRecord('users',g.uid) or {}
    payload['operatorName']=profile.get('companyName') or profile.get('businessName') or profile.get('name') or 'TravelMate Tourism Operator'
    result=storeRecord('promotional_campaigns',createCampaign(payload,g.uid)); return jsonify({'ok':True,'id':result['id'],'campaign':result}),201
@bp.put('/campaigns/<cid>')
@auth_required(['operator'])
def update_campaign(cid):
    current=_own('promotional_campaigns',cid)
    if not current:return jsonify({'ok':False,'error':'Campaign not found'}),404
    if current.get('reviewStatus')=='pending':return jsonify({'ok':False,'error':'Campaign under administrator review cannot be edited'}),409
    payload=request.get_json(silent=True) or {}
    if not validateCampaignDatesAndContent({**current,**payload}):return jsonify({'ok':False,'error':'Invalid campaign dates or content'}),400
    payload['updatedAt']=utc_now_iso()
    if current.get('reviewStatus') == 'approved':
        payload.update({'reviewStatus': 'draft', 'campaignStatus': 'draft', 'reviewComment': ''})
    return jsonify({'ok':True,'campaign':updateRecord('promotional_campaigns',cid,payload)})
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

    return jsonify({
        'ok': True,
        'campaign': updateRecord(
            'promotional_campaigns',
            cid,
            {
                'reviewStatus': 'pending',
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
    deleted = delete_image_file(filename)
    return jsonify({'ok': True, 'deleted': deleted})

