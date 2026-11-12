"""Private registration and retryable FCM delivery. Disabled until explicitly configured."""
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import os
import re
from uuid import uuid4

from sequence_contract.firebase_firestore import retrieveRecord, claimRecord, transactNotificationRecord
from services.traveller_notifications import (
    TRIP_REMINDER_CATEGORIES, MYT, active_trip, canonical_payment_order,
    derive_events, matches_trip_reminder, push_presentation, trip_start,
)

log = logging.getLogger(__name__)


def enabled():
    return os.getenv('TRAVELMATE_PUSH_ENABLED', '').lower() == 'true'


def dispatch_enabled():
    return enabled() and os.getenv('PUSH_DISPATCH_ENABLED', 'true').lower() == 'true'


def rollout_traveller():
    return os.getenv('PUSH_TRAVELLER_UID', '').strip()


def _in_rollout(uid):
    return rollout_traveller() in ('', uid)


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def now_utc():
    return datetime.now(timezone.utc)


def register_device(uid, payload, disable=False):
    if not disable and not _in_rollout(uid):
        raise PermissionError('Device registration is unavailable.')
    allowed = {'token', 'bindingSecret', 'appId', 'localTripReminders'}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise ValueError('Use token, bindingSecret, appId and optional localTripReminders only.')
    if 'localTripReminders' in payload and not isinstance(payload['localTripReminders'], bool):
        raise ValueError('localTripReminders must be a boolean.')
    token, secret, app = (payload.get(key) for key in ('token','bindingSecret','appId'))
    if not isinstance(app,str) or not isinstance(token,str) or not 20 <= len(token) <= 4096 or not isinstance(secret,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}',secret):
        raise ValueError('Invalid device registration.')
    if not disable and app not in {value.strip() for value in os.getenv('PUSH_ANDROID_APP_IDS','').split(',') if value.strip()}:
        raise ValueError('Android application is not enabled for push.')
    key = digest(token)
    def update(current):
        if current and (current.get('appId') != app or current.get('bindingHash') != digest(secret) or
                        (current.get('travellerId') != uid and (current.get('active') or disable))):
            raise PermissionError('Device registration is unavailable.')
        if disable and not current:
            return None
        return {'travellerId':uid,'token':token,'bindingHash':digest(secret),'appId':app,
                'active':not disable,'updatedAt':now_utc().isoformat(),
                'localTripReminders':payload.get('localTripReminders',False)}
    transactNotificationRecord('notification_devices',key,update)
    return key


def queue_notification(event, created):
    if not dispatch_enabled() or not created or not _in_rollout(event.get('travellerId')):
        return
    if event.get('category') in {'payment','arrangements_ready','package_booking','arrangements_update','booking_attention'}:
        try:
            occurred = datetime.fromisoformat(str(event.get('occurredAt') or '').replace('Z','+00:00'))
            if occurred.tzinfo is None or not now_utc()-timedelta(hours=24) <= occurred <= now_utc()+timedelta(minutes=5):return
        except ValueError:return
    claimRecord('notification_outbox',event['id'],{'travellerId':event['travellerId'],
        'notificationId':event['id'],'status':'pending','createdAt':now_utc().isoformat(),
        'expiresAt':(datetime.fromisoformat(event['createdAt'])+timedelta(hours=24)).isoformat()})


def still_due(notification, now):
    category = notification.get('category')
    if category == 'payment' and notification.get('paymentType') == 'package' and notification.get('paymentState') == 'paid':
        order = retrieveRecord('checkout_orders',notification.get('paymentOrderId')) if notification.get('paymentOrderId') else None
        return bool(order and order.get('travellerId') == notification.get('travellerId') and order.get('paymentStatus') == 'paid'
                    and not order.get('isSimulated') and order.get('bookingMode') != 'simulation')
    if category in {'arrangements_ready','package_booking','arrangements_update','booking_attention'}:
        uid=notification.get('travellerId')
        source=notification.get('sourceOrderId')
        order=retrieveRecord('checkout_orders',source) if source else None
        if not order or order.get('travellerId')!=uid:return False
        tid=order.get('fulfilledTripId')
        trip=retrieveRecord('itineraries',tid) if tid else None
        if trip and (trip.get('travellerId')!=uid or (not active_trip(trip) and category!='booking_attention')):return False
        return any(item['id']==notification['id'] for item in derive_events(uid,[order],[trip] if trip else [],now=now))
    if category not in TRIP_REMINDER_CATEGORIES: return True
    uid=notification['travellerId'];tid=(notification.get('target') or {}).get('tripId')
    trip=retrieveRecord('itineraries',tid) if tid else None
    if not matches_trip_reminder(notification, trip):return False
    delta=(trip_start(trip)-now.astimezone(MYT).date()).days
    if category=='weather':return 0<=delta<=6 and str(notification.get('forecastDate') or '')>=now.astimezone(MYT).date().isoformat()
    if delta not in {1,3}:return False
    if category=='packing':
        from services.packing_checklist_service import checklist_id
        checklist=retrieveRecord('packing_checklists',checklist_id(uid,tid)) or {}
        return any(e['category']=='packing' for e in derive_events(uid,[],[trip],{tid:checklist},now=now))
    return True


def capture_committed_order(order):
    if not dispatch_enabled():
        return
    try:
        uid = order.get('travellerId')
        if not uid or not _in_rollout(uid):
            return
        order = canonical_payment_order(order,uid,lambda oid:retrieveRecord('checkout_orders',oid))
        tid = order.get('fulfilledTripId')
        trip = retrieveRecord('itineraries',tid) if tid else None
        events = derive_events(uid,[order],[trip] if trip else [])
        for event in events:
            saved, created = claimRecord('traveller_notifications',event['id'],event)
            # Replays repair a missed enqueue, but never revive old expired sends.
            if created or saved.get('createdAt') == event.get('createdAt'):
                queue_notification(saved,True)
            elif not retrieveRecord('notification_outbox',event['id']):
                queue_notification(saved,True)
        if events:
            # Older pending jobs must not crowd a newly committed payment out of the send budget.
            dispatch(uid=uid,max_sends=2,notification_ids=[event['id'] for event in events])
    except Exception:
        log.warning('Committed notification projection deferred to scheduled reconciliation.')


def _send(device, notification):
    from firebase_admin import messaging, get_app, initialize_app
    project = os.getenv('PUSH_FIREBASE_PROJECT_ID','')
    if not project or project.startswith('demo-') or os.getenv('FIRESTORE_EMULATOR_HOST') or get_app().project_id != project:
        raise RuntimeError('FCM project configuration is unavailable.')
    try:
        app = get_app('travelmate-push')
    except ValueError:
        app = initialize_app(get_app().credential,{'projectId':project,'httpTimeout':5},name='travelmate-push')
    if app.project_id != project: raise RuntimeError('FCM project mismatch.')
    # FlutterFire 16.5 exposes registration tokens, not FCM-registered FIDs.
    # Admin 7.7 supports token compatibility; never relabel a token as a FID.
    presentation = push_presentation(notification)
    return messaging.send(messaging.Message(token=device['token'],
        notification=messaging.Notification(**presentation),
        data={'notificationId':notification['id']},
        android=messaging.AndroidConfig(priority='high',ttl=timedelta(hours=1),
            notification=messaging.AndroidNotification(channel_id='travelmate_updates',icon='ic_notification',
                tag=notification['id'],visibility='private'))),app=app)


def _claim_delivery(key, now):
    lease = uuid4().hex
    def update(current):
        current = current or {'attempts':0}
        if current.get('status') in {'sent','invalid','cancelled','exhausted'}:
            return None
        if current['attempts'] >= 8:
            return {**current,'status':'exhausted','leaseUntil':''}
        if str(current.get('retryAt') or '') > now.isoformat() or str(current.get('leaseUntil') or '') > now.isoformat():
            return None
        return {**current,'status':'sending','lease':lease,'attempts':current['attempts']+1,
                'leaseUntil':(now+timedelta(minutes=5)).isoformat()}
    return transactNotificationRecord('notification_deliveries',key,update)


def _finish(key, lease, patch):
    return transactNotificationRecord('notification_deliveries',key,
        lambda current:{**current,**patch,'leaseUntil':''} if current and current.get('lease')==lease else None)


def _eligible_device(device, owner, now):
    allowed={app.strip() for app in os.getenv('PUSH_ANDROID_APP_IDS','').split(',') if app.strip()}
    return bool(device and device.get('active') and device.get('travellerId')==owner and device.get('appId') in allowed
                and str(device.get('updatedAt') or '') >= (now-timedelta(days=30)).isoformat())


def _dispatch_log(nid, outcome):
    safe_id=nid if isinstance(nid,str) and re.fullmatch(r'[a-f0-9]{64}',nid) else 'invalid'
    log.info('notification_dispatch event=%s outcome=%s',safe_id,outcome)


def dispatch(uid=None, limit=100, sender=None, max_sends=100, *, notification_ids=None):
    if not dispatch_enabled():
        return {'sent':0,'disabled':True}
    scoped_uid = rollout_traveller()
    if scoped_uid:
        if uid is not None and uid != scoped_uid:
            return {'sent': 0}
        uid = scoped_uid
    sender = sender or _send
    now = now_utc()
    filters = [('status','==','pending')]
    if uid: filters.append(('travellerId','==',uid))
    sent = 0; attempts = 0
    jobs = (retrieveRecord('notification_outbox',filters=filters,limit=limit) or []
            if notification_ids is None
            else (retrieveRecord('notification_outbox', nid) for nid in notification_ids))
    for job in jobs:
        if not job or job.get('status') != 'pending' or (uid and job.get('travellerId') != uid):
            continue
        owner = job['travellerId']; nid = job['notificationId']
        if str(job.get('expiresAt') or '') <= now.isoformat():
            transactNotificationRecord('notification_outbox',job['id'],lambda current:{**current,'status':'expired'} if current else None)
            continue
        notification = retrieveRecord('traveller_notifications',nid)
        if not notification or notification.get('travellerId') != owner:
            continue
        if notification.get('read') or not still_due(notification,now):
            transactNotificationRecord('notification_outbox',job['id'],lambda row:{**row,'status':'cancelled'} if row else None)
            continue
        devices = retrieveRecord('notification_devices',filters=[('travellerId','==',owner),('active','==',True)],limit=20) or []
        complete = True
        for device in devices:
            if notification.get('category') == 'upcoming_trip' and device.get('localTripReminders') is True:
                continue
            if not _eligible_device(device,owner,now):
                continue
            if attempts >= max_sends:
                complete=False;break
            key = digest([nid,device['bindingHash']])
            attempt = _claim_delivery(key,now)
            if not attempt or attempt.get('status') != 'sending':
                state = retrieveRecord('notification_deliveries',key) or {}
                complete &= state.get('status') in {'sent','invalid','cancelled','exhausted'}
                continue
            lease=attempt['lease']
            current = retrieveRecord('notification_devices',device['id'])
            if not _eligible_device(current,owner,now) or current.get('bindingHash')!=device.get('bindingHash'):
                _finish(key,lease,{'status':'cancelled'});continue
            if notification.get('category') == 'upcoming_trip' and current.get('localTripReminders') is True:
                _finish(key,lease,{'status':'cancelled'});continue
            try:
                attempts+=1
                sender(current,notification)
                _finish(key,lease,{'status':'sent','sentAt':now_utc().isoformat()});sent+=1
                _dispatch_log(nid,'provider_accepted')
            except Exception as error:
                safe_codes={'UnregisteredError':'unregistered','SenderIdMismatchError':'sender_mismatch',
                    'UnavailableError':'unavailable','ResourceExhaustedError':'quota_exceeded','InternalError':'internal'}
                code = safe_codes.get(type(error).__name__,'send_failed')
                invalid = type(error).__name__ in {'UnregisteredError','SenderIdMismatchError'}
                if invalid:
                    transactNotificationRecord('notification_devices',device['id'],lambda row:
                        {**row,'active':False} if row and row.get('travellerId')==owner else None)
                terminal = invalid or attempt['attempts'] >= 8
                _finish(key,lease,{'status':'invalid' if invalid else 'exhausted' if terminal else 'retry',
                    'errorCode':code,
                    'retryAt':(now+timedelta(seconds=min(3600,30*2**min(attempt['attempts'],7)))).isoformat()})
                _dispatch_log(nid,'invalid_token' if invalid else 'exhausted' if terminal else 'retry')
                complete &= terminal
        if complete:
            transactNotificationRecord('notification_outbox',job['id'],lambda current:{**current,'status':'processed'} if current else None)
        if attempts >= max_sends:break
    return {'sent':sent}
