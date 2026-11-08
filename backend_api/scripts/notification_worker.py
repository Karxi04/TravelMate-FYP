"""Cloud Run Job entry point. IAM schedules executions; no public sending endpoint."""
import json
import sys
from pathlib import Path
from datetime import timedelta
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from firebase_service import get_db, init_firebase
from sequence_contract.firebase_firestore import transactNotificationRecord
from services.notification_delivery import enabled, now_utc, dispatch, queue_notification


def run_worker(batch_size=100):
    if not enabled(): return {'disabled':True}
    now=now_utc();lease=uuid4().hex
    def acquire(row):
        if row and str(row.get('leaseUntil') or '')>now.isoformat():return None
        return {**(row or {}),'lease':lease,'leaseUntil':(now+timedelta(minutes=20)).isoformat()}
    state=transactNotificationRecord('notification_worker_state','reconcile',acquire)
    if not state:return {'leased':True}
    count=0;failed=0
    try:
        from modules.traveller_notifications import reconcile
        query=get_db().collection('notification_devices').order_by('__name__').limit(batch_size)
        if state.get('cursor'):query=query.start_after({'__name__':get_db().collection('notification_devices').document(state['cursor'])})
        rows=list(query.stream());seen=set()
        for doc in rows:
            device=doc.to_dict() or {};uid=device.get('travellerId')
            if not device.get('active') or not uid or uid in seen:continue
            if str(device.get('updatedAt') or '') < (now-timedelta(days=30)).isoformat():
                transactNotificationRecord('notification_devices',doc.id,lambda row:
                    {**row,'active':False} if row and str(row.get('updatedAt') or '') < (now-timedelta(days=30)).isoformat() else None)
                continue
            seen.add(uid)
            try:
                result=reconcile(uid)
                # Repair an inbox/outbox partial failure without changing history/read state.
                for item in result['items']:
                    if str(item.get('createdAt') or '')>=(now-timedelta(hours=24)).isoformat():queue_notification(item,True)
                count+=1
            except Exception:failed+=1
        sent=dispatch(limit=100)
        cursor=rows[-1].id if len(rows)==batch_size else ''
        transactNotificationRecord('notification_worker_state','reconcile',lambda row:
            {**row,'cursor':cursor,'leaseUntil':'','lastRunAt':now.isoformat(),'failures':failed} if row and row.get('lease')==lease else None)
        return {'owners':count,'failedOwners':failed,**sent,'moreDevices':bool(cursor)}
    except Exception:
        transactNotificationRecord('notification_worker_state','reconcile',lambda row:
            {**row,'leaseUntil':''} if row and row.get('lease')==lease else None)
        raise


if __name__=='__main__':
    init_firebase()
    print(json.dumps(run_worker()))
