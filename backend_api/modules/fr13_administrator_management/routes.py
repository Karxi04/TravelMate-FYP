import csv, io
from flask import send_file
from flask import Blueprint, request, jsonify, g, Response, abort, current_app
from math import isfinite
from werkzeug.exceptions import HTTPException
from firebase_admin import auth
from auth_utils import auth_required
from utils import utc_now_iso
from sequence_contract.validators import (
    validateAccountAction,
    validateReportCriteria,
    validateAdminDestinationRecord,
    validateAdminActivityRecord,
    validateCampaignDatesAndContent,
)
from sequence_contract.firebase_firestore import retrieveRecord, storeRecord, updateRecord, deleteRecord
from sequence_contract.domain_functions import (
    approve,
    reject
)

from services.commerce_money import record_money as _record_money, record_amount as _amount
from services.report_service import (
    export_system_report_pdf
)
from services.package_service import package_for_read, package_submission_error
from services.review_service import ReviewConflict, current_screen, review_revision, published_review, review_history
from services.public_content_projection import active_campaign, eligible_package
from services.campaign_schedule import campaign_package_ids
from modules.fr12_tourism_operator_management.analytics_service import is_paid_order
from firebase_service import get_db

bp=Blueprint('fr13_admin',__name__,url_prefix='/api/fr13')
RECORD_LIMIT = 500


def _fail(message, status):
    response = jsonify({'ok': False, 'error': message})
    response.status_code = status
    abort(response)


def _payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        _fail('Request data must be an object', 400)
    return data


def _load(collection):
    records = retrieveRecord(collection, limit=RECORD_LIMIT + 1) or []
    g.admin_data_limited = getattr(g, 'admin_data_limited', False) or len(records) > RECORD_LIMIT
    return records[:RECORD_LIMIT]


def _save(collection, identity, updates, current):
    saved = updateRecord(collection, identity, updates, expected=current)
    if not saved:
        _fail('The record changed or could not be saved. Refresh and try again.', 503)
    return saved


def _reconcile_moderation(collection,identity,current):
    from services.public_content_projection import source_changed
    # A prior source write may have succeeded before projection publication failed.
    source_changed(collection,identity)
    if retrieveRecord(collection,identity) != current:
        raise ReviewConflict('This record changed. Refresh and try again.')


@bp.errorhandler(Exception)
def admin_failure(error):
    if isinstance(error, HTTPException):
        return error
    if isinstance(error, ReviewConflict):
        return jsonify({'ok': False, 'error': str(error)}), 409
    current_app.logger.warning('Administrator operation failed (%s)', type(error).__name__)
    return jsonify({'ok': False, 'error': 'Administrator service is temporarily unavailable. Please try again.'}), 503


@bp.after_request
def list_scope(response):
    body = response.get_json(silent=True) if response.is_json else None
    if isinstance(body, dict) and body.get('ok') and isinstance(body.get('items'), list):
        body.update(dataLimited=getattr(g, 'admin_data_limited', False), recordLimit=RECORD_LIMIT)
        response.set_data(current_app.json.dumps(body))
    return response


def _criteria():
    data = {
        'reportType': request.args.get('reportType') or 'system_summary',
        'startDate': request.args.get('startDate') or '',
        'endDate': request.args.get('endDate') or '',
        'filter': request.args.get('filter') or '',
    }
    return data


FORBIDDEN_COMMERCE_KEYS = {
    'providerIdempotencyKey',
    'clientSecret',
    'stripeClientSecret',
    'rawSessionId',
    'checkoutSessionId',
    'checkoutUrl',
    'firebaseToken',
    'authToken',
    'password',
    'sessionToken',
}


def _sanitize_commerce_record(record):
    if isinstance(record, list):
        return [_sanitize_commerce_record(value) for value in record]
    if isinstance(record, dict):
        return {k: _sanitize_commerce_record(v) for k, v in record.items() if k not in FORBIDDEN_COMMERCE_KEYS
                and k not in {'passwordHash', 'private_key', 'apiKey', 'api_key', 'refreshToken', 'idToken'}}
    return record


def _in_date_range(item, start, end, fields=('createdAt', 'updatedAt', 'submittedAt', 'reviewedAt', 'timestamp', 'date')):
    if not start and not end:
        return True
    values = [str(item.get(field) or '')[:10] for field in fields if item.get(field)]
    if not values:
        return False
    return (not start or values[0] >= start) and (not end or values[0] <= end)


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
        number = float(value or 0)
        return number if isfinite(number) and number >= 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def _int_or_default(value, default):
    try:
        return int(float(value or default))
    except (TypeError, ValueError):
        return default


def _validate_content(payload, activity=False):
    for key, value in payload.items():
        if key in {'title','destinationName','activityName','address','category','type','description','openingHours','status'}:
            if not isinstance(value,str) or len(value) > (10000 if key == 'description' else 2000):
                _fail('Content fields must contain valid text.',400)
    if 'estimatedCost' in payload and _amount({'amount':payload['estimatedCost']}) is None:
        _fail('Estimated cost must be a finite nonnegative amount.',400)
    if activity and 'recommendedDurationMinutes' in payload:
        value=payload['recommendedDurationMinutes']
        try:
            valid=not isinstance(value,bool) and float(value).is_integer() and 1 <= float(value) <= 1440
        except (TypeError,ValueError,OverflowError):
            valid=False
        if not valid:_fail('Duration must be a whole number from 1 to 1440 minutes.',400)
    if 'status' in payload and payload['status'] not in {'active','inactive'}:
        _fail('Content status must be active or inactive.',400)


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
        return collections.get('users', [])
    if report_type == 'packages':
        return collections.get('packages', [])
    if report_type == 'campaigns':
        return collections.get('campaigns', [])
    if report_type == 'feedback':
        return collections.get('feedback', [])
    if report_type == 'bookings':
        return collections.get('hotel_bookings', []) + collections.get('package_bookings', [])
    if report_type == 'payments':
        return collections.get('payment_records', [])
    return (
        collections.get('users', [])
        + collections.get('packages', [])
        + collections.get('campaigns', [])
        + collections.get('feedback', [])
        + collections.get('hotel_bookings', [])
        + collections.get('payment_records', [])
    )
@bp.get('/users')
@auth_required(['admin'])
def users():
    items = [_sanitize_commerce_record(item) for item in _load('users')]
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
    payload=_payload()
    if any(k in payload and not isinstance(payload[k],str) for k in ('role','status','verificationStatus')):
        _fail('Invalid account action',400)
    if not validateAccountAction(payload):return jsonify({'ok':False,'error':'No valid account update supplied'}),400
    updates={k:v for k,v in payload.items() if k in {'role','status','verificationStatus'}}
    if uid == g.uid and (updates.get('role') not in (None, 'admin') or updates.get('status') == 'deactivated'):
        return jsonify({'ok':False,'error':'Administrators cannot disable or demote their own account'}), 409
    current=retrieveRecord('users',uid)
    if not current:return jsonify({'ok':False,'error':'User not found'}),404
    if updates.get('verificationStatus') in {'approved','verified','rejected'} and updates.get('role',current.get('role')) not in {'operator','tourism_operator'}:
        _fail('Business verification is only applicable to Operator accounts.',400)
    updates['updatedAt']=utc_now_iso()
    if 'status' in updates: auth.update_user(uid,disabled=updates['status']=='deactivated')
    return jsonify({'ok':True,'user':_sanitize_commerce_record(_save('users',uid,updates,current))})
@bp.get('/packages/pending')
@auth_required(['admin'])
def pending_packages():
    items=_review_queue()
    return jsonify({'ok':True,'items':[package_for_read(item) for item in items if item.get('approvalStatus') in {'pending','submitted'}]})

@bp.get('/packages')
@auth_required(['admin'])
def review_packages():
    items=_review_queue()
    status=str(request.args.get('status','all')).strip().lower()
    query=str(request.args.get('q','')).strip().lower()
    if status!='all':
        expected={'pending','submitted'} if status=='pending' else {status}
        items=[item for item in items if str(item.get('approvalStatus','draft')).lower() in expected]
    if query:items=[item for item in items if query in ' '.join(str(item.get(field) or '') for field in ('title','packageTitle','destination','destinationName','operatorName')).lower()]
    items.sort(key=lambda item:(item.get('approvalStatus') not in {'pending','submitted'},str(item.get('submittedAt') or item.get('updatedAt') or '')))
    return jsonify({'ok':True,'items':[package_for_read(item) for item in items]})


def _review_queue():
    # approvalStatus is the current lifecycle; reviewedAt/By retain past decisions.
    return [item for item in _load('tourism_packages') if not item.get('deletedAt')
            and str(item.get('approvalStatus') or '').lower()
            in {'pending', 'submitted', 'approved', 'rejected', 'suspended'}]

@bp.get('/packages/<pid>')
@auth_required(['admin'])
def package_details(pid):
    item=retrieveRecord('tourism_packages',pid)
    if not item:return jsonify({'ok':False,'error':'Package not found'}),404
    return jsonify({'ok':True,'package':package_for_read(item)})
@bp.post('/packages/<pid>/review')
@auth_required(['admin'])
def review_package(pid):
    payload=_payload(); decision=payload.get('decision')
    current=retrieveRecord('tourism_packages',pid)
    if not current:return jsonify({'ok':False,'error':'Package not found'}),404
    if current.get('deletedAt') or str(current.get('approvalStatus') or '').lower() in {'draft','archived'}:
        return jsonify({'ok':False,'error':'Draft and archived packages must be submitted by the operator before review.'}),409
    if not isinstance(decision,str) or decision not in {'approved','rejected'}:return jsonify({'ok':False,'error':'decision must be approved or rejected'}),400
    if not isinstance(payload.get('comment',''), str) or len(payload.get('comment','')) > 2000:_fail('Use a review note of at most 2000 characters.',400)
    comment=payload.get('comment','').strip()
    if current.get('approvalStatus') == decision and current.get('reviewComment','') == comment:
        _reconcile_moderation('tourism_packages',pid,current)
        return jsonify({'ok':True,'package':package_for_read(current),'idempotent':True})
    if current.get('approvalStatus') not in {'pending','submitted'}:return jsonify({'ok':False,'error':'Only submitted packages can be reviewed'}),409
    if decision=='rejected' and not comment:return jsonify({'ok':False,'error':'A rejection reason is required'}),400
    if decision=='approved':
        error=package_submission_error(current)
        if error:return jsonify({'ok':False,'error':error}),400
    review=approve(current,comment) if decision=='approved' else reject(current,comment)
    updates={'approvalStatus':review['decision'],'reviewReason':review['reviewComment'],'reviewComment':review['reviewComment'],'reviewedBy':g.uid,'reviewedByName':(g.profile or {}).get('name','Administrator'),'reviewedAt':review['reviewedAt'],'updatedAt':utc_now_iso()}
    if decision == 'approved' and current.get('suspendedAt'):
        updates.update({'suspensionResolvedAt':updates['updatedAt'],'suspensionResolvedBy':g.uid,'suspensionResolvedByName':updates['reviewedByName']})
    return jsonify({'ok':True,'package':_save('tourism_packages',pid,updates,current)})


@bp.post('/packages/<pid>/suspend')
@auth_required(['admin'])
def suspend_package(pid):
    current=retrieveRecord('tourism_packages',pid)
    if not current:return jsonify({'ok':False,'error':'Package not found'}),404
    payload=_payload()
    reason=str(payload.get('reason') or '').strip()
    if len(reason) < 10:return jsonify({'ok':False,'error':'A meaningful suspension reason of at least 10 characters is required'}),400
    if len(reason) > 500:return jsonify({'ok':False,'error':'Suspension reason cannot exceed 500 characters'}),400
    status=str(current.get('approvalStatus') or 'draft').lower()
    if status == 'suspended':
        if reason != str(current.get('suspensionReason') or '').strip():
            return jsonify({'ok':False,'error':'Package is already suspended with a different reason'}),409
        _reconcile_moderation('tourism_packages',pid,current)
        return jsonify({'ok':True,'package':package_for_read(current),'status':'suspended','idempotent':True})
    if status != 'approved':
        return jsonify({'ok':False,'error':'Only approved packages can be suspended'}),409
    now=utc_now_iso()
    updates={
        'approvalStatus':'suspended',
        'suspensionReason':reason,
        'suspendedBy':g.uid,
        'suspendedByName':(g.profile or {}).get('name','Administrator'),
        'suspendedAt':now,
        'updatedAt':now,
    }
    saved=_save('tourism_packages',pid,updates,current)
    return jsonify({'ok':True,'package':package_for_read(saved),'status':'suspended','idempotent':False})
@bp.get('/campaigns/pending')
@auth_required(['admin'])
def pending_campaigns():
    return campaign_records(pending_only=True)

def _campaign_view(item):
    item = dict(item)
    packages=[retrieveRecord('tourism_packages', pid) for pid in campaign_package_ids(item)]
    packages=[p for p in packages if isinstance(p,dict)]
    item['linkedPackages']=[{'id':p.get('id'),'title':p.get('title') or p.get('packageTitle'),'approvalStatus':p.get('approvalStatus')} for p in packages]
    item['packageTitle']=', '.join(p.get('title') or p.get('packageTitle') or '-' for p in packages) or '-'
    item['destinationName']=', '.join(dict.fromkeys(p.get('destinationName') or p.get('destination') or '' for p in packages))
    item['operatorName']=(packages[0].get('operatorName') if packages else None) or 'Tourism Operator'
    return item

def campaign_records(pending_only=False):
    items=_load('promotional_campaigns')
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
    from services.campaign_schedule import campaign_schedule_error
    payload=_payload(); decision=payload.get('decision')
    current=retrieveRecord('promotional_campaigns',cid)
    if not current:return jsonify({'ok':False,'error':'Campaign not found'}),404
    if not isinstance(decision,str) or decision not in {'approved','rejected'}:return jsonify({'ok':False,'error':'decision must be approved or rejected'}),400
    if not isinstance(payload.get('comment',''),str) or len(payload.get('comment','')) > 2000:_fail('Use a review note of at most 2000 characters.',400)
    comment=payload.get('comment','').strip()
    if decision=='rejected' and not comment:return jsonify({'ok':False,'error':'A rejection reason is required'}),400
    if current.get('reviewStatus') == decision and current.get('reviewComment','') == comment:
        _reconcile_moderation('promotional_campaigns',cid,current)
        return jsonify({'ok':True,'campaign':current,'idempotent':True})
    if current.get('reviewStatus') not in {'pending','submitted','under_review'}:
        return jsonify({'ok':False,'error':'Only submitted campaigns can be reviewed'}),409
    if decision=='approved':
        schedule_error = campaign_schedule_error(current, publishing=True)
        if schedule_error:_fail(schedule_error,400)
        if not validateCampaignDatesAndContent(current):_fail('Invalid campaign dates or content',400)
        if not campaign_package_ids(current):_fail('Related package not found',404)
        for package_id in campaign_package_ids(current):
            package=retrieveRecord('tourism_packages',package_id)
            if not package:_fail('Related package not found',404)
            if not eligible_package(package) or not current.get('operatorId') or package.get('operatorId') != current['operatorId']:
                _fail('Campaign requires an eligible package owned by its operator',409)
    review=approve(current,comment) if decision=='approved' else reject(current,comment); updates={'reviewStatus':review['decision'],'reviewComment':review['reviewComment'],'reviewReason':review['reviewComment'],'reviewedBy':g.uid,'reviewedAt':review['reviewedAt'],'updatedAt':utc_now_iso()}
    if decision=='approved':updates['campaignStatus']='approved'
    return jsonify({'ok':True,'campaign':_save('promotional_campaigns',cid,updates,current)})
@bp.get('/feedback')
@auth_required(['admin'])
def all_feedback():
    items = []
    for item in _load('feedback'):
        screening = current_screen(item)
        decision = item.get('moderationDecision') or {}
        if item.get('feedbackStatus') == 'removed':
            category = 'hidden'
        elif published_review(item):
            category = 'automatic' if decision.get('actor') == 'system' else 'manual'
        else:
            category = 'flagged' if screening['risk'] == 'flagged' else 'needs_review'
        items.append({**item, 'screening': screening, 'moderationCategory': category,
                      'reviewRevision': review_revision(item)})
    items.sort(key=lambda item: str(item.get('submittedAt') or ''), reverse=True)
    return jsonify({'ok': True, 'items': items})


@bp.get('/feedback/<fid>/history')
@auth_required(['admin'])
def feedback_history(fid):
    return jsonify({'ok': True, 'items': review_history(fid)})


def _commit_review(fid, current, updates, **extra):
    try:
        updates['screening'] = current_screen(current)
        return jsonify({'ok': True, 'feedback': updateRecord('feedback', fid, updates, expected=current), **extra})
    except ReviewConflict as error:
        return jsonify({'ok': False, 'error': str(error)}), 409
    except Exception:
        return jsonify({'ok': False, 'error': 'Review moderation is temporarily unavailable.'}), 503


def _admin_review_decision(outcome, note=''):
    return {'actor': 'administrator', 'actorId': g.uid, 'outcome': outcome,
            'at': utc_now_iso(), 'note': note}

@bp.post('/feedback/<fid>/review')
@auth_required(['admin'])
def review_feedback(fid):
    current=retrieveRecord('feedback',fid)
    if not current:return jsonify({'ok':False,'error':'Feedback not found'}),404
    payload=request.get_json(silent=True) or {}
    if not isinstance(payload, dict):return jsonify({'ok':False,'error':'Invalid moderation request'}),400
    decision=str(payload.get('decision','')).lower()
    if 'expectedUpdatedAt' in payload and payload['expectedUpdatedAt'] != (current.get('updatedAt') or ''):
        return jsonify({'ok':False,'error':'This review changed. Refresh and try again.'}),409
    if 'expectedRevision' in payload and payload['expectedRevision'] != review_revision(current):
        return jsonify({'ok':False,'error':'This review changed. Refresh and try again.'}),409
    if not isinstance(payload.get('comment',''), str) or len(payload.get('comment','')) > 2000:
        return jsonify({'ok':False,'error':'Use a moderation note of at most 2000 characters.'}),400
    if decision not in {'keep', 'remove', 'reject', 'hide'}:
        return jsonify({'ok': False, 'error': 'Choose Approve, Reject or Hide.'}), 400
    note = payload.get('comment', '')
    if decision != 'keep':
        outcome = ('hide' if published_review(current) else 'reject') if decision == 'remove' else decision
        updates={
            'moderationStatus':'removed',
            'feedbackStatus':'removed',
            'reviewComment':note,
            'removedBy':g.uid,
            'removedAt':utc_now_iso(),
            'updatedAt':utc_now_iso(),
            'moderationDecision':_admin_review_decision(outcome, note),
        }
        return _commit_review(fid, current, updates, removedId=fid, decision=decision)
    updates={'moderationStatus':'reviewed','feedbackStatus':'visible','reviewComment':note,'reviewedBy':g.uid,'reviewedAt':utc_now_iso(),'updatedAt':utc_now_iso(),
             'moderationDecision':_admin_review_decision('approve', note)}
    return _commit_review(fid, current, updates, decision='keep')

@bp.delete('/feedback/<fid>')
@auth_required(['admin'])
def remove_feedback(fid):
    current = retrieveRecord('feedback',fid)
    if not current:return jsonify({'ok':False,'error':'Feedback not found'}),404
    updates={
        'moderationStatus':'removed',
        'feedbackStatus':'removed',
        'removedBy':g.uid,
        'removedAt':utc_now_iso(),
        'updatedAt':utc_now_iso(),
        'moderationDecision':_admin_review_decision('hide'),
    }
    return _commit_review(fid, current, updates, removedId=fid)


@bp.get('/destinations')
@auth_required(['admin'])
def destinations():
    return jsonify({'ok': True, 'items': _load('admin_destinations')})


@bp.post('/destinations')
@auth_required(['admin'])
def create_destination():
    payload = _payload()
    _validate_content(payload)
    data = _normalise_destination_payload(payload)
    if not validateAdminDestinationRecord(data):
        return jsonify({'ok': False, 'error': 'Destination name is required'}), 400
    data['createdAt'] = utc_now_iso()
    return jsonify({'ok': True, 'destination': storeRecord('admin_destinations', data)}), 201


@bp.put('/destinations/<did>')
@auth_required(['admin'])
def update_destination(did):
    payload = _payload()
    current=retrieveRecord('admin_destinations',did)
    if not current:_fail('Destination record not found',404)
    _validate_content(payload)
    merged={**current,**payload}
    if 'destinationName' in payload and 'title' not in payload:merged['title']=payload['destinationName']
    if not validateAdminDestinationRecord(merged):
        return jsonify({'ok': False, 'error': 'Destination name is required'}), 400
    data={k:v for k,v in _normalise_destination_payload(merged).items() if k in payload or k=='updatedAt' or (k=='title' and 'destinationName' in payload)}
    item = _save('admin_destinations', did, data, current)
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
    return jsonify({'ok': True, 'items': _load('admin_activities')})


@bp.post('/activities')
@auth_required(['admin'])
def create_activity():
    payload = _payload()
    _validate_content(payload,activity=True)
    data = _normalise_activity_payload(payload)
    if not validateAdminActivityRecord(data):
        return jsonify({'ok': False, 'error': 'Activity name is required'}), 400
    data['createdAt'] = utc_now_iso()
    return jsonify({'ok': True, 'activity': storeRecord('admin_activities', data)}), 201


@bp.put('/activities/<aid>')
@auth_required(['admin'])
def update_activity(aid):
    payload = _payload()
    current=retrieveRecord('admin_activities',aid)
    if not current:_fail('Activity record not found',404)
    _validate_content(payload,activity=True)
    merged={**current,**payload}
    if 'title' in payload and 'activityName' not in payload:merged['activityName']=payload['title']
    if not validateAdminActivityRecord(merged):
        return jsonify({'ok': False, 'error': 'Activity name is required'}), 400
    data={k:v for k,v in _normalise_activity_payload(merged).items() if k in payload or k=='updatedAt' or (k=='activityName' and 'title' in payload)}
    item = _save('admin_activities', aid, data, current)
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
    booking_type = str(request.args.get('type') or 'hotel').strip().lower()
    query = str(request.args.get('q') or '').strip().lower()
    status = str(request.args.get('status') or '').strip().lower()

    items = []
    if booking_type in {'hotel', 'all'}:
        hotel_bookings = _load('hotel_bookings')
        linked_orders = {str(o.get('id')): o for o in _load('checkout_orders') if isinstance(o, dict)}
        for h in hotel_bookings:
            if not isinstance(h, dict):
                continue
            sanitized_h = _sanitize_commerce_record(h)
            sanitized_h.setdefault('bookingType', 'hotel')
            provider_result=h.get('providerResult') if isinstance(h.get('providerResult'),dict) else {}
            provenance='simulation' if h.get('isSimulated') or h.get('bookingMode') == 'simulation' or h.get('source') == 'local' else (
                'provider_sandbox' if h.get('sandbox') or provider_result.get('sandbox') or h.get('transactionMode') == 'provider_sandbox' else 'unverified')
            if (provenance == 'unverified' and h.get('source') == 'liteapi' and h.get('providerMutationCalled') is True
                    and h.get('bookingStatus') == 'confirmed' and h.get('bookingReference')
                    and h['bookingReference'] in [provider_result.get(k) for k in ('bookingId', 'id', 'hotelConfirmationCode')]):
                provenance = 'provider_recorded'
            amount, currency = _record_money(h, linked_orders)
            sanitized_h.update(reservationProvenance=provenance, amount=amount, currency=currency)
            if provenance == 'simulation':
                sanitized_h['confirmationLabel'] = 'Hotel Details Saved'
            elif provenance == 'provider_sandbox':
                sanitized_h['confirmationLabel'] = 'Provider Sandbox Record'
            elif provenance == 'provider_recorded':
                sanitized_h['confirmationLabel'] = 'Provider Confirmation Recorded'
            elif provenance == 'unverified':
                sanitized_h['confirmationLabel'] = 'Reservation Not Confirmed'
            items.append(sanitized_h)

    if booking_type in {'package', 'all'}:
        checkout_orders = _unified_payment_records(_load('checkout_orders'), [])
        for o in checkout_orders:
            if not isinstance(o, dict):
                continue
            quote_type = str(o.get('quoteType') or '').lower()
            if quote_type == 'package' or o.get('packageId') or o.get('attemptType') == 'package_checkout':
                pkg_snapshot = o.get('packageSnapshot') if isinstance(o.get('packageSnapshot'), dict) else {}
                title = pkg_snapshot.get('title') or pkg_snapshot.get('packageTitle') or o.get('packageTitle') or '-'
                operator_id = o.get('operatorId') or pkg_snapshot.get('operatorId') or '-'
                package_id = o.get('packageId') or pkg_snapshot.get('packageId') or '-'

                sanitized_order = _sanitize_commerce_record(o)
                supplier_status = str(o.get('supplierReservationStatus') or 'not_created').lower()
                supplier_disclosure = {
                    'operator_attested': 'Supplier arrangements recorded by the operator; not independently API verified by TravelMate.',
                    'declined': 'Operator unable to fulfill; no refund is implied by this status.',
                    'not_required': 'No supplier reservations required for the included services.',
                }.get(supplier_status)
                if supplier_disclosure is None:
                    supplier_status = 'not_created'
                    supplier_disclosure = 'Package Trip creation is platform-managed; no direct third-party supplier reservation has been booked.'
                pkg_proj = {
                    **sanitized_order,
                    'bookingType': 'package',
                    'bookingReference': o.get('id'),
                    'packageId': package_id,
                    'packageTitle': title,
                    'operatorId': operator_id,
                    'travellerId': o.get('travellerId'),
                    'paymentStatus': o.get('paymentStatus') or o.get('status') or 'unpaid',
                    'orderStatus': o.get('status') or 'checkout_pending',
                    'fulfillmentStatus': o.get('fulfillmentStatus') or 'fulfillment_pending',
                    'supplierReservationStatus': supplier_status,
                    'supplierReservationDisclosure': supplier_disclosure,
                    'testMode': bool(o.get('testMode')),
                    'amount': _amount(o),
                    'currency': str(o.get('currency') or 'UNKNOWN').upper(),
                    'createdAt': o.get('createdAt') or '',
                }
                from services.booking_requirements import load_context
                from modules.fr12_tourism_operator_management.analytics_service import _safe_analytics_booking
                context, trip = load_context(o,retrieveRecord)
                assessment = _safe_analytics_booking(o,include_fulfillment=True,requirement_context=context,trip_state=trip)
                pkg_proj['statusOverview'] = assessment['statusOverview']
                pkg_proj['readiness'] = assessment['readiness']
                pkg_proj['clarificationStatus'] = (context.get('record') or {}).get('status')
                items.append(pkg_proj)

    if status:
        items = [
            item for item in items
            if str(item.get('bookingStatus') or item.get('paymentStatus') or item.get('orderStatus') or '').lower() == status
        ]
    if query:
        items = [
            item for item in items
            if query in ' '.join(str(item.get(key) or '') for key in ('id', 'bookingReference', 'travellerId', 'packageTitle', 'hotelName', 'operatorId')).lower()
        ]

    items.sort(key=lambda item: str(item.get('createdAt') or ''), reverse=True)
    return jsonify({'ok': True, 'items': items})


def _settlements(record):
    keys={('intent',str(record[k])) for k in ('stripePaymentIntentId',) if record.get(k)}
    keys.update(('session',str(record[k])) for k in ('checkoutSessionId',) if record.get(k))
    if str(record.get('transactionReference') or '').startswith('pi_'):
        keys.add(('intent',record['transactionReference']))
    return keys


def _unified_payment_records(checkout_orders, payment_records):
    unique_orders = []
    seen_order_ids = set()
    seen_settlements=set()
    ordered=sorted((o for o in (checkout_orders or []) if isinstance(o,dict)),
                   key=lambda o:(str(o.get('updatedAt') or o.get('createdAt') or ''),not is_paid_order(o)),reverse=True)
    for o in ordered:
        if not isinstance(o, dict):
            continue
        oid = str(o.get('id') or '')
        keys=_settlements(o)
        if (oid and oid in seen_order_ids) or keys & seen_settlements:
            continue
        seen_settlements.update(keys)
        if oid:
            seen_order_ids.add(oid)
        unique_orders.append(o)

    known_order_ids = {str(o.get('id')) for o in (checkout_orders or []) if isinstance(o,dict) and o.get('id')}
    known_legacy_payment_ids = {str(o.get('legacyPaymentId')) for o in unique_orders if o.get('legacyPaymentId')}

    unique_payments = []
    seen_payment_ids = set()
    for p in sorted((p for p in (payment_records or []) if isinstance(p,dict)),
                    key=lambda p:(str(p.get('updatedAt') or p.get('createdAt') or ''),not is_paid_order(p)),reverse=True):
        if not isinstance(p, dict):
            continue
        pid = str(p.get('id') or '')
        if pid and pid in seen_payment_ids:
            continue
        if pid:
            seen_payment_ids.add(pid)

        ref_order = str(p.get('checkoutOrderId') or p.get('orderReference') or p.get('orderId') or '')
        if ref_order and ref_order in known_order_ids:
            continue
        if pid in known_legacy_payment_ids:
            continue
        keys=_settlements(p)
        if keys & seen_settlements:
            continue
        seen_settlements.update(keys)

        unique_payments.append(p)

    projected = []
    for o in unique_orders:
        sanitized = _sanitize_commerce_record(o)
        pkg_snapshot = o.get('packageSnapshot')
        pkg_title = (
            pkg_snapshot.get('title')
            if isinstance(pkg_snapshot, dict)
            else ''
        ) or o.get('bookingId') or o.get('orderTitle') or '-'
        sanitized['productType'] = o.get('quoteType') or 'package'
        sanitized['productTitle'] = pkg_title
        amount, currency = _record_money(o)
        sanitized.update(amount=amount,currency=currency,isPaid=is_paid_order(o))
        if o.get('provider') == 'stripe_checkout_test' or o.get('testMode') is True:
            sanitized['testMode'] = True
        elif o.get('testMode') is False:
            sanitized['testMode'] = False
        projected.append(sanitized)

    for p in unique_payments:
        sanitized = _sanitize_commerce_record(p)
        sanitized.setdefault('productType', 'legacy_payment')
        sanitized.setdefault('productTitle', p.get('bookingId') or p.get('itemTitle') or '-')
        amount, currency = _record_money(p)
        sanitized.update(amount=amount,currency=currency,isPaid=is_paid_order(p))
        if 'testMode' not in sanitized:
            if 'test' in str(p.get('provider') or '').lower() or str(p.get('transactionReference') or '').startswith('pi_sim_'):
                sanitized['testMode'] = True
            else:
                sanitized['testMode'] = False
        projected.append(sanitized)

    return projected


@bp.get('/payments')
@auth_required(['admin'])
def payment_records():
    query = str(request.args.get('q') or '').strip().lower()
    status = str(request.args.get('status') or '').strip().lower()
    product = str(request.args.get('product') or '').strip().lower()
    start_date = str(request.args.get('startDate') or '').strip()
    end_date = str(request.args.get('endDate') or '').strip()

    if not validateReportCriteria({'startDate':start_date,'endDate':end_date}):_fail('Use a valid date range',400)
    checkout_orders = _load('checkout_orders')
    legacy_payments = _load('payment_records')
    items = _unified_payment_records(checkout_orders, legacy_payments)

    if status:
        items = [item for item in items if str(item.get('paymentStatus') or item.get('status') or '').lower() == status]
    if product:
        items = [item for item in items if str(item.get('productType') or '').lower() == product]
    if start_date or end_date:
        items = [item for item in items if _in_date_range(item, start_date, end_date)]
    if query:
        items = [
            item for item in items
            if query in ' '.join(str(item.get(key) or '') for key in ('id', 'travellerId', 'productType', 'productTitle', 'operatorId', 'transactionReference')).lower()
        ]
    items.sort(key=lambda item: str(item.get('createdAt') or ''), reverse=True)
    return jsonify({'ok': True, 'items': items})


def _summary(criteria=None):
    criteria = criteria or {'reportType': 'system_summary'}
    if not validateReportCriteria(criteria):
        raise ValueError('Use a valid report type and date range')
    if criteria.get('reportType','system_summary') not in {'system_summary','users','packages','campaigns','feedback','bookings','payments'}:
        raise ValueError('Use a valid report type')
    users = _filter_records(_load('users'),criteria)
    loaded_packages = _load('tourism_packages')
    packages = _filter_records(loaded_packages,criteria)
    campaigns = _filter_records(_load('promotional_campaigns'),criteria)
    feedback = _filter_records(_load('feedback'),criteria)
    hotel_bookings = _filter_records(_load('hotel_bookings'),criteria)
    checkout_orders = _load('checkout_orders')
    legacy_payments = _load('payment_records')
    # Resolve canonical mirrors before filtering, so an out-of-range mirror cannot reappear.
    unified_payments = _filter_records(_unified_payment_records(checkout_orders, legacy_payments),criteria)
    checkout_orders = _filter_records(checkout_orders,criteria)
    package_bookings = [item for item in unified_payments if item.get('productType') == 'package']

    collections = {
        'users': users,
        'packages': packages,
        'campaigns': campaigns,
        'feedback': feedback,
        'hotel_bookings': hotel_bookings,
        'package_bookings': package_bookings,
        'payment_records': unified_payments,
        'checkout_orders': checkout_orders,
    }
    report_type = str(criteria.get('reportType') or 'system_summary')
    scoped_records = _filter_records(_records_for_type(report_type, collections), criteria)

    travellers = sum(1 for u in users if str(u.get('role', '')).lower() == 'traveller')
    operators = sum(1 for u in users if str(u.get('role', '')).lower() in {'operator', 'tourism_operator'})
    administrators = sum(1 for u in users if str(u.get('role', '')).lower() in {'admin', 'administrator'})
    active_users = sum(1 for u in users if str(u.get('status', 'active')).lower() != 'deactivated')
    deactivated_users = sum(1 for u in users if str(u.get('status', '')).lower() == 'deactivated')

    approved_pkgs = sum(1 for p in packages if str(p.get('approvalStatus', '')).lower() == 'approved')
    pending_pkgs = sum(1 for p in packages if str(p.get('approvalStatus', '')).lower() in {'pending', 'submitted', 'pending_approval', 'under_review'})
    rejected_pkgs = sum(1 for p in packages if str(p.get('approvalStatus', '')).lower() == 'rejected')
    draft_pkgs = sum(1 for p in packages if str(p.get('approvalStatus', '')).lower() in {'', 'draft'})

    approved_camps = sum(1 for c in campaigns if str(c.get('reviewStatus', '')).lower() == 'approved')
    pending_camps = sum(1 for c in campaigns if str(c.get('reviewStatus', '')).lower() in {'pending', 'submitted', 'pending_approval', 'under_review'})
    rejected_camps = sum(1 for c in campaigns if str(c.get('reviewStatus', '')).lower() == 'rejected')
    eligible_ids={p.get('id') for p in loaded_packages if eligible_package(p)}
    active_camps = sum(1 for c in campaigns if active_campaign(c) and bool(set(campaign_package_ids(c)) & eligible_ids))

    visible_fb = sum(1 for f in feedback if published_review(f))
    pending_fb = sum(1 for f in feedback if str(f.get('moderationStatus', '')).lower() in {'pending', 'pending_review'})
    removed_fb = sum(1 for f in feedback if str(f.get('feedbackStatus', '')).lower() == 'removed' or str(f.get('moderationStatus', '')).lower() == 'removed')

    # Payment metrics across unified payments
    paid_payments = sum(
        1 for p in unified_payments
        if is_paid_order(p)
    )
    pending_payments = sum(
        1 for p in unified_payments
        if str(p.get('paymentStatus') or p.get('status') or '').lower() in {'pending', 'payment_pending', 'unpaid', 'checkout_pending'}
    )
    failed_payments = sum(
        1 for p in unified_payments
        if str(p.get('paymentStatus') or p.get('status') or '').lower() in {'failed', 'payment_failed', 'checkout_failed'}
    )
    expired_payments = sum(
        1 for p in unified_payments
        if str(p.get('paymentStatus') or p.get('status') or '').lower() in {'expired', 'checkout_expired'}
    )
    test_mode_payments = sum(
        1 for p in unified_payments
        if p.get('testMode') is True or 'test' in str(p.get('provider') or '').lower() or str(p.get('transactionReference') or '').startswith('pi_sim_')
    )
    paid_myr=[p for p in unified_payments if is_paid_order(p) and p.get('currency') == 'MYR']
    total_paid_revenue = round(sum(_amount(p) for p in paid_myr if _amount(p) is not None),2)
    test_paid_total=round(sum(_amount(p) for p in paid_myr if p.get('testMode') and _amount(p) is not None),2)

    generated_at = utc_now_iso()

    return {
        'dataLimited':getattr(g,'admin_data_limited',False),
        'recordLimit':RECORD_LIMIT,
        'recordsLimited':len(scoped_records)>200,
        'recordDisplayLimit':200,
        'generatedAt': generated_at,
        'criteria': criteria,
        'counts': {
            'users': len(users),
            'tourism_packages': len(packages),
            'promotional_campaigns': len(campaigns),
            'hotel_bookings': len(hotel_bookings),
            'package_bookings':len(package_bookings),
            'payment_records': len(unified_payments),
            'checkout_orders': len(checkout_orders),
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
                'pendingOperators':sum(1 for u in users if u.get('role') in {'operator','tourism_operator'} and u.get('verificationStatus','pending') == 'pending'),
                'approvedOperators':sum(1 for u in users if u.get('role') in {'operator','tourism_operator'} and u.get('verificationStatus') in {'approved','verified'}),
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
            'payments': {
                'total': len(unified_payments),
                'paid': paid_payments,
                'pending': pending_payments,
                'failed': failed_payments,
                'expired': expired_payments,
                'testMode': test_mode_payments,
                'totalPaidRevenue': total_paid_revenue,
                'testPaidTotal':test_paid_total,
                'unpricedPaidOrders':sum(1 for p in paid_myr if _amount(p) is None),
                'excludedCurrencyPaidOrders':sum(1 for p in unified_payments if is_paid_order(p) and p.get('currency') != 'MYR'),
            },
        },
        'records': _sanitize_commerce_record(scoped_records[:200]),
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
    def row(values):
        writer.writerow(["'"+str(v) if str(v).lstrip().startswith(('=','+','-','@','\t','\r')) else v for v in values])
    row(['TravelMate Administrator System Report'])
    row(['Generated At', report.get('generatedAt', '')])
    criteria = report.get('criteria', {})
    row(['Report Type', criteria.get('reportType', 'system_summary')])
    row(['Start Date', criteria.get('startDate', '')])
    row(['End Date', criteria.get('endDate', '')])
    row(['Filter', criteria.get('filter', '')])
    row(['Source records limited',report.get('dataLimited',False)])
    row(['Export rows limited',report.get('recordsLimited',False)])
    row([])
    row(['Metric', 'Value'])
    for key, value in report.get('counts', {}).items():
        row([key, value])
    row([])
    row(['Filtered Records'])
    records = report.get('records') or []
    fieldnames = sorted({key for item in records for key in item.keys()})
    if fieldnames:
        row(fieldnames)
        for item in records:
            row([item.get(field, '') for field in fieldnames])
    else:
        row(['No records matched the selected criteria'])
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=TravelMate_System_Report.csv'},
    )
