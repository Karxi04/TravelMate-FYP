from copy import deepcopy
from datetime import datetime, timezone, timedelta
from threading import RLock
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path
import subprocess
import sys

import pytest

from services import notification_delivery as delivery
from modules import traveller_notifications as routes
from sequence_contract import firebase_firestore as persistence
from services.traveller_notifications import derive_events
from test_preference_learning_transaction import TransactionDatabase

UID='test_traveller_uid'
AUTH={'Authorization':'Bearer fixture'}
NOW=datetime(2026,11,8,12,tzinfo=timezone.utc)


class Memory:
    def __init__(self): self.rows={};self.lock=RLock()
    def read(self,coll,key=None,filters=None,limit=None,**kwargs):
        with self.lock:
            if key is not None:
                row=deepcopy(self.rows.get((coll,key)))
                return {'id':key,**row} if row is not None else None
            rows=[{'id':key,**deepcopy(value)} for (name,key),value in self.rows.items() if name==coll
                  and all(value.get(field)==expected for field,op,expected in filters or [])]
            return rows[:limit] if limit else rows
    def claim(self,coll,key,data):
        with self.lock:
            created=(coll,key) not in self.rows
            if created:self.rows[(coll,key)]=deepcopy(data)
            return {'id':key,**deepcopy(self.rows[(coll,key)])},created
    def transact(self,coll,key,transform):
        with self.lock:
            updated=transform(deepcopy(self.rows.get((coll,key))))
            if updated is not None:self.rows[(coll,key)]=deepcopy(updated)
            return deepcopy(updated)


@pytest.fixture
def memory(monkeypatch):
    db=Memory()
    monkeypatch.setenv('TRAVELMATE_PUSH_ENABLED','true')
    monkeypatch.setenv('PUSH_ANDROID_APP_IDS','org.travelmate.hermetic.travelmate_hermetic')
    for module in (delivery,routes):
        monkeypatch.setattr(module,'retrieveRecord',db.read)
    monkeypatch.setattr(delivery,'claimRecord',db.claim)
    monkeypatch.setattr(delivery,'transactNotificationRecord',db.transact)
    monkeypatch.setattr(delivery,'now_utc',lambda:NOW)
    return db


def registration(token='token-1-'+'x'*30):
    return {'token':token,'bindingSecret':'s'*43,'appId':'org.travelmate.hermetic.travelmate_hermetic'}


def event(db,uid=UID):
    item=derive_events(uid,[{'id':'order','travellerId':uid,'paymentStatus':'paid','updatedAt':NOW.isoformat()}],[],now=NOW)[0]
    db.claim('traveller_notifications',item['id'],item)
    delivery.queue_notification(item,True)
    return item


def test_registration_multiple_devices_owner_secret_rotation_and_logout(memory):
    first=delivery.register_device(UID,registration())
    second=delivery.register_device(UID,registration('token-2-'+'y'*30))
    assert first!=second
    assert delivery.register_device(UID,registration())==first
    with pytest.raises(PermissionError):delivery.register_device('other',registration())
    with pytest.raises(PermissionError):delivery.register_device(UID,{**registration(),'bindingSecret':'a'*43})
    delivery.register_device(UID,registration(),True)
    assert not memory.read('notification_devices',first)['active']
    delivery.register_device('other',registration())
    with pytest.raises(PermissionError):delivery.register_device(UID,registration(),True)


def test_rollback_disables_new_registration_without_blocking_owned_revocation(client,mock_traveller_auth,memory,monkeypatch):
    delivery.register_device(UID,registration())
    monkeypatch.setenv('TRAVELMATE_PUSH_ENABLED','false')
    monkeypatch.setenv('PUSH_ANDROID_APP_IDS','')
    assert client.post('/api/traveller/notifications/devices',headers=AUTH,json=registration()).status_code==503
    assert client.post('/api/traveller/notifications/devices/unregister',headers=AUTH,json=registration()).status_code==200


@pytest.mark.parametrize('payload',[{}, {'token':'short'}, {**registration(),'travellerId':'other'},
    {**registration(),'appId':'wrong'}, {**registration(),'bindingSecret':'invalid'}])
def test_registration_validation_does_not_accept_client_ownership(memory,payload):
    with pytest.raises(ValueError):delivery.register_device(UID,payload)
    assert not memory.rows


def test_dispatch_multi_device_replay_no_private_payload_and_no_other_owner(memory):
    delivery.register_device(UID,registration())
    delivery.register_device(UID,{**registration('another-'+'z'*30),'bindingSecret':'b'*43})
    delivery.register_device('other',registration('foreign-'+'z'*30))
    item=event(memory);sent=[]
    assert delivery.dispatch(sender=lambda device,notice:sent.append((device,notice)))['sent']==2
    delivery.queue_notification(item,True)
    assert delivery.dispatch(sender=lambda *args:sent.append(args))['sent']==0
    assert len(sent)==2 and all(device['travellerId']==UID for device,notice in sent)
    assert len(memory.read('traveller_notifications'))==1


def test_acceptance_rollout_scopes_existing_outbox_and_registration(memory, monkeypatch):
    delivery.register_device(UID, registration())
    other_registration = registration('other-' + 'x' * 30)
    delivery.register_device('other', other_registration)
    own = event(memory)
    foreign = event(memory, 'other')
    monkeypatch.setenv('PUSH_TRAVELLER_UID', UID)
    with pytest.raises(PermissionError):
        delivery.register_device('other', other_registration)
    assert delivery.dispatch(uid='other')['sent'] == 0
    sent = []
    assert delivery.dispatch(sender=lambda device, notice: sent.append(notice['id']))['sent'] == 1
    assert sent == [own['id']]
    assert memory.read('notification_outbox', foreign['id'])['status'] == 'pending'
    delivery.register_device('other', other_registration, disable=True)


def test_concurrent_dispatch_lease_prevents_duplicate_send(memory):
    delivery.register_device(UID,registration());event(memory);calls=[]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures=[executor.submit(delivery.dispatch,sender=lambda *args:calls.append(args)) for _ in range(2)]
        for future in futures:future.result()
    assert len(calls)==1


def test_transient_retry_and_invalid_token_cleanup(memory,monkeypatch):
    key=delivery.register_device(UID,registration());event(memory)
    def unavailable(*args):raise RuntimeError('secret-provider-error')
    assert delivery.dispatch(sender=unavailable)['sent']==0
    states=memory.read('notification_deliveries');assert states[0]['status']=='retry'
    assert 'secret-provider-error' not in str(states)
    assert delivery.dispatch(sender=lambda *args:None)['sent']==0
    monkeypatch.setattr(delivery,'now_utc',lambda:NOW+timedelta(minutes=2))
    UnregisteredError=type('UnregisteredError',(Exception,),{})
    def invalid(*args):raise UnregisteredError()
    delivery.dispatch(sender=invalid)
    assert not memory.read('notification_devices',key)['active']
    assert memory.read('notification_deliveries')[0]['status']=='invalid'


def test_logout_before_dispatch_and_expired_outbox_never_send(memory,monkeypatch):
    delivery.register_device(UID,registration());event(memory)
    delivery.register_device(UID,registration(),True)
    calls=[];delivery.dispatch(sender=lambda *args:calls.append(args));assert not calls
    item=event(memory,'other')
    delivery.register_device('other',registration('other-'+'q'*30))
    monkeypatch.setattr(delivery,'now_utc',lambda:NOW+timedelta(days=2))
    delivery.dispatch(sender=lambda *args:calls.append(args));assert not calls


def test_scheduled_reminders_revalidate_dates_cancellation_and_packing(memory):
    from services.packing_checklist_service import checklist_id
    trip={'id':'t','travellerId':UID,'startDate':'2026-11-11','endDate':'2026-11-13'}
    checklist={'tripId':'t','travellerId':UID,'items':[{'applicable':True,'suppressed':False,'isPacked':False}]}
    events=derive_events(UID,[],[trip],{'t':checklist},now=NOW)
    memory.claim('itineraries','t',trip);memory.claim('packing_checklists',checklist_id(UID,'t'),checklist)
    assert all(delivery.still_due(item,NOW) for item in events)
    memory.rows[('packing_checklists',checklist_id(UID,'t'))]['items'][0]['isPacked']=True
    assert not delivery.still_due(next(e for e in events if e['category']=='packing'),NOW)
    memory.rows[('itineraries','t')]['startDate']='2026-11-12'
    assert all(not delivery.still_due(item,NOW) for item in events)


def test_post_commit_capture_uses_persisted_ready_evidence_and_replay(memory):
    record={'id':'o','travellerId':UID,'paymentStatus':'paid','updatedAt':NOW.isoformat(),'fulfilledTripId':'t','fulfillmentStatus':'trip_ready',
            'fulfillmentRecord':{'status':'trip_ready','confirmedAt':NOW.isoformat(),'confirmedBy':'operator'}}
    memory.claim('itineraries','t',{'travellerId':UID})
    with patch.object(delivery,'dispatch'):
        delivery.capture_committed_order(record);delivery.capture_committed_order(record)
    assert {r['category'] for r in memory.read('traveller_notifications')}=={'payment','arrangements_ready'}
    assert len(memory.read('notification_outbox'))==2
    with patch.object(delivery,'capture_committed_order') as hook:
        persistence._notify_committed('checkout_orders','o',record)
        persistence._notify_committed('payment_records','p',record)
        persistence._notify_committed('itineraries','t',record)
        assert hook.call_count==2


def test_real_firestore_delivery_transaction_serializes_competing_claims():
    db=TransactionDatabase()
    with patch.object(persistence,'get_db',return_value=db),patch('google.cloud.firestore.transactional',side_effect=db.transactional):
        def claim():return persistence.transactNotificationRecord('notification_deliveries','id',
            lambda current:None if current else {'lease':'one'})
        with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(lambda _:claim(),range(2)))
    assert sum(result is not None for result in results)==1 and db.writes==1


def test_authenticated_registration_detail_and_role_boundaries(client,mock_traveller_auth,memory):
    response=client.post('/api/traveller/notifications/devices',headers=AUTH,json=registration())
    assert response.status_code==200 and 'token' not in response.json
    item=event(memory)
    assert client.get('/api/traveller/notifications/'+item['id'],headers=AUTH).status_code==200
    memory.rows[('traveller_notifications',item['id'])]['travellerId']='other'
    assert client.get('/api/traveller/notifications/'+item['id'],headers=AUTH).status_code==404
    assert client.post('/api/traveller/notifications/devices/unregister',headers=AUTH,json=registration()).status_code==200


@pytest.mark.parametrize('role',['anonymous','operator','admin'])
def test_push_registration_never_accepts_other_roles(client,request,memory,role):
    if role!='anonymous':request.getfixturevalue('mock_'+role+'_auth')
    assert client.post('/api/traveller/notifications/devices',headers={} if role=='anonymous' else AUTH,json=registration()).status_code==(401 if role=='anonymous' else 403)


def test_fcm_wire_payload_contains_only_opaque_notification_id_and_generic_lock_screen_text(memory,monkeypatch):
    monkeypatch.setenv('PUSH_FIREBASE_PROJECT_ID','isolated-push-test')
    monkeypatch.delenv('FIRESTORE_EMULATOR_HOST',raising=False)
    notice=event(memory)
    with patch('firebase_admin.get_app',return_value=SimpleNamespace(project_id='isolated-push-test')),patch('firebase_admin.messaging.send') as send:
        delivery._send({'token':registration()['token']},notice)
    message=send.call_args.args[0]
    assert message.data=={'notificationId':notice['id']}
    assert UID not in message.notification.body and 'order' not in message.notification.body
    assert message.android.notification.tag==notice['id']
    assert message.android.notification.channel_id=='travelmate_updates'


def test_read_inbox_event_cancels_unsent_push(memory):
    delivery.register_device(UID,registration());item=event(memory)
    memory.rows[('traveller_notifications',item['id'])]['read']=True
    calls=[];delivery.dispatch(sender=lambda *args:calls.append(args))
    assert not calls


def test_historical_payment_catchup_keeps_inbox_without_inventing_a_new_push_event(memory):
    old=derive_events(UID,[{'id':'historical','travellerId':UID,'paymentStatus':'paid',
        'paidAt':(NOW-timedelta(days=60)).isoformat()}],[],now=NOW)[0]
    memory.claim('traveller_notifications',old['id'],old)
    delivery.queue_notification(old,True)
    assert memory.read('traveller_notifications',old['id']) and not memory.read('notification_outbox')


def test_same_installation_token_rotation_keeps_one_delivery_identity(memory):
    delivery.register_device(UID,registration())
    delivery.register_device(UID,registration('rotated-'+'q'*30))
    event(memory);calls=[]
    delivery.dispatch(sender=lambda *args:calls.append(args))
    assert len(calls)==1


def test_crashed_attempts_are_bounded_even_when_no_sender_result_was_recorded(memory):
    key=delivery.register_device(UID,registration());item=event(memory)
    ledger=delivery.digest([item['id'],memory.read('notification_devices',key)['bindingHash']])
    memory.claim('notification_deliveries',ledger,{'status':'sending','attempts':8,'leaseUntil':'','lease':'old'})
    calls=[];delivery.dispatch(sender=lambda *args:calls.append(args))
    assert not calls and memory.read('notification_deliveries',ledger)['status']=='exhausted'


def test_worker_imports_under_isolated_cloud_container_module_path():
    worker=Path(__file__).resolve().parents[1]/'scripts/notification_worker.py'
    code=f"import runpy; runpy.run_path({str(worker)!r},run_name='isolated_import'); import modules.traveller_notifications"
    result=subprocess.run([sys.executable,'-I','-B','-c',code],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_worker_lease_bounded_device_page_and_partial_outbox_repair(memory,monkeypatch):
    from scripts import notification_worker as worker
    item=event(memory)
    del memory.rows[('notification_outbox',item['id'])]
    document=SimpleNamespace(id='device',to_dict=lambda:{'active':True,'travellerId':UID,'updatedAt':NOW.isoformat()})
    class Query:
        def order_by(self,field):assert field=='__name__';return self
        def limit(self,count):assert count==1;return self
        def stream(self):return iter([document])
    monkeypatch.setattr(worker,'get_db',lambda:SimpleNamespace(collection=lambda _:Query()))
    monkeypatch.setattr(worker,'transactNotificationRecord',memory.transact)
    monkeypatch.setattr(worker,'now_utc',lambda:NOW)
    monkeypatch.setattr(routes,'reconcile',lambda uid:{'items':[item]})
    monkeypatch.setattr(worker,'dispatch',lambda **kwargs:{'sent':0})
    result=worker.run_worker(1)
    assert result['owners']==1 and result['moreDevices']
    assert memory.read('notification_outbox',item['id'])
    state=memory.read('notification_worker_state','reconcile')
    assert state['cursor']=='device' and state['leaseUntil']==''
    memory.rows[('notification_worker_state','reconcile')]['leaseUntil']=(NOW+timedelta(hours=1)).isoformat()
    assert worker.run_worker(1)=={'leased':True}
