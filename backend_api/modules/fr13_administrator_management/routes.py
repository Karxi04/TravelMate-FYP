import csv, io
from flask import send_file
from flask import Blueprint, request, jsonify, g, Response
from firebase_admin import auth
from auth_utils import auth_required
from utils import utc_now_iso
from sequence_contract.validators import (
    validateAccountAction,
    validateReportCriteria,
    validateAdminDestinationRecord,
    validateAdminActivityRecord,
)
from sequence_contract.firebase_firestore import retrieveRecord, storeRecord, updateRecord, deleteRecord
from sequence_contract.domain_functions import (
    approve,
    reject
)

from services.report_service import (
    export_system_report_pdf
)
from services.package_service import package_for_read
from firebase_service import get_db

bp=Blueprint('fr13_admin',__name__,url_prefix='/api/fr13')


def _criteria():
    data = {
        'reportType': request.args.get('reportType') or 'system_summary',
        'startDate': request.args.get('startDate') or '',
        'endDate': request.args.get('endDate') or '',
        'filter': request.args.get('filter') or '',
    }
    return data


def _in_date_range(item, start, end, fields=('createdAt', 'updatedAt', 'submittedAt', 'reviewedAt')):
    if not start and not end:
        return True
    values = [str(item.get(field) or '')[:10] for field in fields if item.get(field)]
    if not values:
        return False
    return any((not start or value >= start) and (not end or value <= end) for value in values)


def _filter_records(items, criteria):
    items = list(items or [])
    start = criteria.get('startDate') or ''
    end = criteria.get('endDate') or ''
    keyword = str(criteria.get('filter') or '').strip().lower()
    filtered = [x for x in items if _in_date_range(x, start, end)]
    if keyword:
        filtered = [
            x for x in filtered
            if keyword in ' '.join(str(v) for v in x.values()).lower()
        ]
    return filtered


def _float_or_zero(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _int_or_default(value, default):
    try:
        return int(float(value or default))
    except (TypeError, ValueError):
        return default


def _normalise_destination_payload(payload):
    return {
        'title': str(payload.get('title') or payload.get('destinationName') or '').strip(),
        'address': str(payload.get('address') or '').strip(),
        'category': str(payload.get('category') or '').strip(),
        'type': str(payload.get('type') or '').strip(),
        'description': str(payload.get('description') or '').strip(),
        'openingHours': str(payload.get('openingHours') or '').strip(),
        'estimatedCost': _float_or_zero(payload.get('estimatedCost')),
        'status': str(payload.get('status') or 'active').strip() or 'active',
        'updatedAt': utc_now_iso(),
    }


def _normalise_activity_payload(payload):
    return {
        'activityName': str(payload.get('activityName') or payload.get('title') or '').strip(),
        'destinationName': str(payload.get('destinationName') or '').strip(),
        'category': str(payload.get('category') or '').strip(),
        'description': str(payload.get('description') or '').strip(),
        'estimatedCost': _float_or_zero(payload.get('estimatedCost')),
        'recommendedDurationMinutes': _int_or_default(payload.get('recommendedDurationMinutes'), 90),
        'status': str(payload.get('status') or 'active').strip() or 'active',
        'updatedAt': utc_now_iso(),
    }


def _records_for_type(report_type, collections):
    if report_type == 'users':
        return collections['users']
    if report_type == 'packages':
        return collections['packages']
    if report_type == 'campaigns':
        return collections['campaigns']
    if report_type == 'feedback':
        return collections['feedback']
    if report_type == 'bookings':
        return collections['hotel_bookings']
    if report_type == 'payments':
        return collections['payment_records']
    return sum(collections.values(), [])
@bp.get('/users')
@auth_required(['admin'])
def users():
    items = retrieveRecord('users') or []
    role = str(request.args.get('role') or '').strip().lower()
    status = str(request.args.get('status') or '').strip().lower()
    query = str(request.args.get('q') or '').strip().lower()
    if role:
        items = [item for item in items if str(item.get('role') or '').lower() == role]
    if status:
        items = [item for item in items if str(item.get('status') or 'active').lower() == status]
    if query:
        items = [item for item in items if query in ' '.join(str(item.get(k) or '') for k in ('name', 'email', 'companyName', 'role')).lower()]
    return jsonify({'ok':True,'items':items})
@bp.put('/users/<uid>')
@auth_required(['admin'])
def update_user(uid):
    payload=request.get_json(silent=True) or {}
    if not validateAccountAction(payload):return jsonify({'ok':False,'error':'No valid account update supplied'}),400
    updates={k:v for k,v in payload.items() if k in {'role','status','verificationStatus'}}
    if uid == g.uid and (updates.get('role') not in (None, 'admin') or updates.get('status') == 'deactivated'):
        return jsonify({'ok':False,'error':'Administrators cannot disable or demote their own account'}), 409
    updates['updatedAt']=utc_now_iso()
    if 'status' in updates: auth.update_user(uid,disabled=updates['status']=='deactivated')
    return jsonify({'ok':True,'user':updateRecord('users',uid,updates)})
@bp.get('/packages/pending')
@auth_required(['admin'])
def pending_packages():
    items=retrieveRecord('tourism_packages')
    return jsonify({'ok':True,'items':[package_for_read(item) for item in items if item.get('approvalStatus') in {'pending','submitted'}]})

@bp.get('/packages')
@auth_required(['admin'])
def review_packages():
    items=retrieveRecord('tourism_packages')
    status=str(request.args.get('status','all')).strip().lower()
    query=str(request.args.get('q','')).strip().lower()
    if status!='all':
        expected={'pending','submitted'} if status=='pending' else {status}
        items=[item for item in items if str(item.get('approvalStatus','draft')).lower() in expected]
    if query:items=[item for item in items if query in ' '.join(str(item.get(field) or '') for field in ('title','packageTitle','destination','destinationName','operatorName')).lower()]
    items.sort(key=lambda item:(item.get('approvalStatus') not in {'pending','submitted'},str(item.get('submittedAt') or item.get('updatedAt') or '')))
    return jsonify({'ok':True,'items':[package_for_read(item) for item in items]})

@bp.get('/packages/<pid>')
@auth_required(['admin'])
def package_details(pid):
    item=retrieveRecord('tourism_packages',pid)
    if not item:return jsonify({'ok':False,'error':'Package not found'}),404
    return jsonify({'ok':True,'package':package_for_read(item)})
@bp.post('/packages/<pid>/review')
@auth_required(['admin'])
def review_package(pid):
    current=retrieveRecord('tourism_packages',pid)
    if not current:return jsonify({'ok':False,'error':'Package not found'}),404
    if current.get('approvalStatus') not in {'pending','submitted'}:return jsonify({'ok':False,'error':'Only submitted packages can be reviewed'}),409
    payload=request.get_json(silent=True) or {}; decision=payload.get('decision')
    if decision not in {'approved','rejected'}:return jsonify({'ok':False,'error':'decision must be approved or rejected'}),400
    comment=str(payload.get('comment','')).strip()
    if decision=='rejected' and not comment:return jsonify({'ok':False,'error':'A rejection reason is required'}),400
    review=approve(current,comment) if decision=='approved' else reject(current,comment)
    updates={'approvalStatus':review['decision'],'reviewReason':review['reviewComment'],'reviewComment':review['reviewComment'],'reviewedBy':g.uid,'reviewedByName':(g.profile or {}).get('name','Administrator'),'reviewedAt':review['reviewedAt'],'updatedAt':utc_now_iso()}; return jsonify({'ok':True,'package':updateRecord('tourism_packages',pid,updates)})
@bp.get('/campaigns/pending')
@auth_required(['admin'])
def pending_campaigns():
    return campaign_records(pending_only=True)

def _campaign_view(item):
    item = dict(item)
    package=retrieveRecord('tourism_packages',str(item.get('packageId') or '')) or {}
    item['packageTitle']=package.get('packageTitle') or package.get('title') or '-'
    item['destinationName']=package.get('destinationName') or package.get('destination') or ''
    item['operatorName']=package.get('operatorName') or package.get('operatorDisplayName') or 'Tourism Operator'
    return item

def campaign_records(pending_only=False):
    items=retrieveRecord('promotional_campaigns') or []
    if pending_only:
        items=[item for item in items if str(item.get('reviewStatus') or '').lower() in {'pending','submitted','under_review'}]
    status=str(request.args.get('status') or '').strip().lower()
    query=str(request.args.get('q') or '').strip().lower()
    if status and status != 'all': items=[item for item in items if str(item.get('reviewStatus') or '').lower() == status]
    items=[_campaign_view(item) for item in items]
    if query: items=[item for item in items if query in ' '.join(str(item.get(k) or '') for k in ('campaignTitle','packageTitle','destinationName','operatorName','promoCode')).lower()]
    items.sort(key=lambda item: (str(item.get('reviewStatus') or '').lower() not in {'pending','submitted','under_review'}, str(item.get('submittedAt') or item.get('updatedAt') or '')))
    return jsonify({'ok':True,'items':items})

@bp.get('/campaigns')
@auth_required(['admin'])
def campaigns():
    return campaign_records()

@bp.get('/campaigns/<cid>')
@auth_required(['admin'])
def campaign_details(cid):
    item=retrieveRecord('promotional_campaigns',cid)
    if not item:return jsonify({'ok':False,'error':'Campaign not found'}),404
    return jsonify({'ok':True,'campaign':_campaign_view(item)})
@bp.post('/campaigns/<cid>/review')
@auth_required(['admin'])
def review_campaign(cid):
    current=retrieveRecord('promotional_campaigns',cid)
    if not current:return jsonify({'ok':False,'error':'Campaign not found'}),404
    payload=request.get_json(silent=True) or {}; decision=payload.get('decision')
    if decision not in {'approved','rejected'}:return jsonify({'ok':False,'error':'decision must be approved or rejected'}),400
    comment=str(payload.get('comment','')).strip()
    if decision=='rejected' and not comment:return jsonify({'ok':False,'error':'A rejection reason is required'}),400
    review=approve(current,comment) if decision=='approved' else reject(current,comment); updates={'reviewStatus':review['decision'],'reviewComment':review['reviewComment'],'reviewReason':review['reviewComment'],'reviewedBy':g.uid,'reviewedAt':review['reviewedAt'],'updatedAt':utc_now_iso()}
    if decision=='approved':updates['campaignStatus']='approved'
    return jsonify({'ok':True,'campaign':updateRecord('promotional_campaigns',cid,updates)})
@bp.get('/feedback')
@auth_required(['admin'])
def all_feedback():return jsonify({'ok':True,'items':retrieveRecord('feedback')})

@bp.post('/feedback/<fid>/review')
@auth_required(['admin'])
def review_feedback(fid):
    current=retrieveRecord('feedback',fid)
    if not current:return jsonify({'ok':False,'error':'Feedback not found'}),404
    payload=request.get_json(silent=True) or {}; decision=str(payload.get('decision','keep')).lower()
    if decision not in {'keep','remove'}:return jsonify({'ok':False,'error':'decision must be keep or remove'}),400
    if decision=='remove':
        updates={
            'moderationStatus':'removed',
            'feedbackStatus':'removed',
            'reviewComment':payload.get('comment',''),
            'removedBy':g.uid,
            'removedAt':utc_now_iso(),
            'updatedAt':utc_now_iso(),
        }
        return jsonify({'ok':True,'feedback':updateRecord('feedback',fid,updates),'removedId':fid,'decision':'remove'})
    updates={'moderationStatus':'reviewed','feedbackStatus':'visible','reviewComment':payload.get('comment',''),'reviewedBy':g.uid,'reviewedAt':utc_now_iso(),'updatedAt':utc_now_iso()}
    return jsonify({'ok':True,'feedback':updateRecord('feedback',fid,updates),'decision':'keep'})

@bp.delete('/feedback/<fid>')
@auth_required(['admin'])
def remove_feedback(fid):
    if not retrieveRecord('feedback',fid):return jsonify({'ok':False,'error':'Feedback not found'}),404
    updates={
        'moderationStatus':'removed',
        'feedbackStatus':'removed',
        'removedBy':g.uid,
        'removedAt':utc_now_iso(),
        'updatedAt':utc_now_iso(),
    }
    return jsonify({'ok':True,'feedback':updateRecord('feedback',fid,updates),'removedId':fid})


@bp.get('/destinations')
@auth_required(['admin'])
def destinations():
    return jsonify({'ok': True, 'items': retrieveRecord('admin_destinations') or []})


@bp.post('/destinations')
@auth_required(['admin'])
def create_destination():
    payload = request.get_json(silent=True) or {}
    data = _normalise_destination_payload(payload)
    if not validateAdminDestinationRecord(data):
        return jsonify({'ok': False, 'error': 'Destination name is required'}), 400
    data['createdAt'] = utc_now_iso()
    return jsonify({'ok': True, 'destination': storeRecord('admin_destinations', data)}), 201


@bp.put('/destinations/<did>')
@auth_required(['admin'])
def update_destination(did):
    payload = request.get_json(silent=True) or {}
    data = _normalise_destination_payload(payload)
    if not validateAdminDestinationRecord(data):
        return jsonify({'ok': False, 'error': 'Destination name is required'}), 400
    item = updateRecord('admin_destinations', did, data)
    if not item:
        return jsonify({'ok': False, 'error': 'Destination record not found'}), 404
    return jsonify({'ok': True, 'destination': item})


@bp.delete('/destinations/<did>')
@auth_required(['admin'])
def delete_destination(did):
    if not deleteRecord('admin_destinations', did):
        return jsonify({'ok': False, 'error': 'Destination record not found'}), 404
    return jsonify({'ok': True})


@bp.get('/activities')
@auth_required(['admin'])
def activities():
    return jsonify({'ok': True, 'items': retrieveRecord('admin_activities') or []})


@bp.post('/activities')
@auth_required(['admin'])
def create_activity():
    payload = request.get_json(silent=True) or {}
    data = _normalise_activity_payload(payload)
    if not validateAdminActivityRecord(data):
        return jsonify({'ok': False, 'error': 'Activity name is required'}), 400
    data['createdAt'] = utc_now_iso()
    return jsonify({'ok': True, 'activity': storeRecord('admin_activities', data)}), 201


@bp.put('/activities/<aid>')
@auth_required(['admin'])
def update_activity(aid):
    payload = request.get_json(silent=True) or {}
    data = _normalise_activity_payload(payload)
    if not validateAdminActivityRecord(data):
        return jsonify({'ok': False, 'error': 'Activity name is required'}), 400
    item = updateRecord('admin_activities', aid, data)
    if not item:
        return jsonify({'ok': False, 'error': 'Activity record not found'}), 404
    return jsonify({'ok': True, 'activity': item})


@bp.delete('/activities/<aid>')
@auth_required(['admin'])
def delete_activity(aid):
    if not deleteRecord('admin_activities', aid):
        return jsonify({'ok': False, 'error': 'Activity record not found'}), 404
    return jsonify({'ok': True})


@bp.get('/bookings')
@auth_required(['admin'])
def booking_records():
    return jsonify({'ok': True, 'items': retrieveRecord('hotel_bookings') or []})


@bp.get('/payments')
@auth_required(['admin'])
def payment_records():
    return jsonify({'ok': True, 'items': retrieveRecord('payment_records') or []})


def _summary(criteria=None):
    criteria = criteria or {'reportType': 'system_summary'}
    if not validateReportCriteria(criteria):
        raise ValueError('Use a valid report type and date range')
    users = retrieveRecord('users') or []
    packages = retrieveRecord('tourism_packages') or []
    campaigns = retrieveRecord('promotional_campaigns') or []
    feedback = retrieveRecord('feedback') or []
    hotel_bookings = retrieveRecord('hotel_bookings') or []
    payment_records = retrieveRecord('payment_records') or []
    collections = {
        'users': users,
        'packages': packages,
        'campaigns': campaigns,
        'feedback': feedback,
        'hotel_bookings': hotel_bookings,
        'payment_records': payment_records,
    }
    report_type = str(criteria.get('reportType') or 'system_summary')
    scoped_records = _filter_records(_records_for_type(report_type, collections), criteria)

    travellers = sum(1 for u in users if str(u.get('role', '')).lower() == 'traveller')
    operators = sum(1 for u in users if str(u.get('role', '')).lower() in {'operator', 'tourism_operator'})
    administrators = sum(1 for u in users if str(u.get('role', '')).lower() in {'admin', 'administrator'})
    active_users = sum(1 for u in users if str(u.get('status', 'active')).lower() != 'deactivated')
    deactivated_users = sum(1 for u in users if str(u.get('status', '')).lower() == 'deactivated')

    approved_pkgs = sum(1 for p in packages if str(p.get('approvalStatus', '')).lower() == 'approved')
    pending_pkgs = sum(1 for p in packages if str(p.get('approvalStatus', '')).lower() in {'pending', 'pending_approval', 'under_review'})
    rejected_pkgs = sum(1 for p in packages if str(p.get('approvalStatus', '')).lower() == 'rejected')
    draft_pkgs = sum(1 for p in packages if str(p.get('approvalStatus', '')).lower() in {'', 'draft'})

    approved_camps = sum(1 for c in campaigns if str(c.get('reviewStatus', '')).lower() == 'approved')
    pending_camps = sum(1 for c in campaigns if str(c.get('reviewStatus', '')).lower() in {'pending', 'pending_approval', 'under_review'})
    rejected_camps = sum(1 for c in campaigns if str(c.get('reviewStatus', '')).lower() == 'rejected')
    active_camps = sum(1 for c in campaigns if str(c.get('campaignStatus', '')).lower() == 'active' or str(c.get('reviewStatus', '')).lower() == 'approved')

    visible_fb = sum(1 for f in feedback if str(f.get('feedbackStatus', 'visible')).lower() == 'visible')
    pending_fb = sum(1 for f in feedback if str(f.get('moderationStatus', '')).lower() in {'pending', 'pending_review'})
    removed_fb = sum(1 for f in feedback if str(f.get('feedbackStatus', '')).lower() == 'removed' or str(f.get('moderationStatus', '')).lower() == 'removed')

    generated_at = utc_now_iso()

    return {
        'generatedAt': generated_at,
        'criteria': criteria,
        'counts': {
            'users': len(users),
            'tourism_packages': len(packages),
            'promotional_campaigns': len(campaigns),
            'hotel_bookings': len(hotel_bookings),
            'payment_records': len(payment_records),
            'feedback': len(feedback),
            'filtered_records': len(scoped_records),
        },
        'summary': {
            'users': {
                'total': len(users),
                'travellers': travellers,
                'operators': operators,
                'administrators': administrators,
                'active': active_users,
                'deactivated': deactivated_users,
            },
            'packages': {
                'total': len(packages),
                'approved': approved_pkgs,
                'pending': pending_pkgs,
                'rejected': rejected_pkgs,
                'draft': draft_pkgs,
            },
            'campaigns': {
                'total': len(campaigns),
                'approved': approved_camps,
                'pending': pending_camps,
                'active': active_camps,
                'rejected': rejected_camps,
            },
            'feedback': {
                'total': len(feedback),
                'visible': visible_fb,
                'pending': pending_fb,
                'removed': removed_fb,
            },
        },
        'records': scoped_records[:200],
    }

@bp.get("/reports/summary")
@auth_required(['admin'])
def report_summary():
    try:
        report_data = _summary(_criteria())
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    return jsonify({
        'ok': True,
        'report': report_data,
        **report_data['summary'],
        'counts': report_data['counts'],
        'generatedAt': report_data['generatedAt'],
    }), 200

#export
@bp.get('/reports/export.pdf')
@auth_required(['admin'])
def export_report_pdf():
    try:
        report = _summary(_criteria())
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    profile = retrieveRecord('users', g.uid) or g.profile or {}
    buffer = io.BytesIO()
    export_system_report_pdf(report, buffer, admin_profile=profile)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="TravelMate_System_Report.pdf",
    )

@bp.get("/reports/export")
@auth_required(['admin'])
def export_report():
    if str(request.args.get('format') or '').lower() == 'csv':
        return export_report_csv()
    try:
        report = _summary(_criteria())
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    profile = retrieveRecord('users', g.uid) or g.profile or {}
    buffer = io.BytesIO()
    export_system_report_pdf(report, buffer, admin_profile=profile)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="TravelMate_System_Report.pdf",
    )


@bp.get('/reports/export.csv')
@auth_required(['admin'])
def export_report_csv():
    try:
        report = _summary(_criteria())
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['TravelMate Administrator System Report'])
    writer.writerow(['Generated At', report.get('generatedAt', '')])
    criteria = report.get('criteria', {})
    writer.writerow(['Report Type', criteria.get('reportType', 'system_summary')])
    writer.writerow(['Start Date', criteria.get('startDate', '')])
    writer.writerow(['End Date', criteria.get('endDate', '')])
    writer.writerow(['Filter', criteria.get('filter', '')])
    writer.writerow([])
    writer.writerow(['Metric', 'Value'])
    for key, value in report.get('counts', {}).items():
        writer.writerow([key, value])
    writer.writerow([])
    writer.writerow(['Filtered Records'])
    records = report.get('records') or []
    fieldnames = sorted({key for item in records for key in item.keys()})
    if fieldnames:
        writer.writerow(fieldnames)
        for item in records:
            writer.writerow([item.get(field, '') for field in fieldnames])
    else:
        writer.writerow(['No records matched the selected criteria'])
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=TravelMate_System_Report.csv'},
    )
