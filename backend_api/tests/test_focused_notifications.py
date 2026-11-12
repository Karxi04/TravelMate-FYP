from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch
import pytest
from test_android_push_delivery import memory, registration, event, NOW, UID, AUTH
from services import notification_delivery as delivery
from services.traveller_notifications import derive_events, push_presentation, canonical_payment_order


def package_order():
    return {'id':'paid-package','travellerId':UID,'quoteType':'package','paymentStatus':'paid','paidAt':NOW.isoformat()}


def test_confirmed_package_success_wording_and_no_private_financial_data(memory):
    order=package_order();before=deepcopy(order)
    notice=derive_events(UID,[order],[],now=NOW)[0]
    assert push_presentation(notice)=={'title':'TravelMate — Payment Successful','body':'Your tourism package payment has been confirmed.'}
    assert order==before and UID not in str(push_presentation(notice))


@pytest.mark.parametrize('state',['pending','failed','cancelled','expired','refunded'])
def test_unconfirmed_and_unsuccessful_payment_never_say_success(state):
    events=derive_events(UID,[{**package_order(),'paymentStatus':state}],[],now=NOW)
    assert all('Successful' not in push_presentation(n)['title'] for n in events)


def test_payment_projection_keeps_package_identity_from_owned_checkout():
    order=package_order();row={'id':'projection','travellerId':UID,'checkoutOrderId':order['id'],'paymentStatus':'paid'}
    linked=canonical_payment_order(row,UID,lambda key:order)
    assert linked['quoteType']=='package' and linked['checkoutOrderId']==order['id']
    assert canonical_payment_order(row,UID,lambda key:{**order,'travellerId':'foreign'})==row


def test_paid_package_replay_dispatches_once_and_refund_blocks_stale_success(memory):
    order=package_order();memory.claim('checkout_orders',order['id'],order)
    delivery.register_device(UID,registration())
    with patch.object(delivery,'dispatch'):
        delivery.capture_committed_order(order);delivery.capture_committed_order(order)
    sent=[];assert delivery.dispatch(sender=lambda *args:sent.append(args))['sent']==1
    assert delivery.dispatch(sender=lambda *args:sent.append(args))['sent']==0 and len(sent)==1
    notice=derive_events(UID,[order],[],now=NOW)[0]
    assert delivery.still_due(notice,NOW)
    memory.rows[('checkout_orders',order['id'])]['paymentStatus']='refunded'
    assert not delivery.still_due(notice,NOW)
    memory.rows[('checkout_orders',order['id'])]['paymentStatus']='paid'
    memory.rows[('checkout_orders',order['id'])]['travellerId']='foreign'
    assert not delivery.still_due(notice,NOW)


def test_committed_payment_dispatches_without_worker_even_with_pending_backlog(memory):
    order = package_order()
    memory.claim('checkout_orders', order['id'], order)
    delivery.register_device(UID, registration())
    for nid in ('old-one', 'old-two'):
        memory.claim('notification_outbox', nid, {
            'travellerId': UID, 'notificationId': nid, 'status': 'pending',
            'expiresAt': (NOW + timedelta(hours=1)).isoformat(),
        })
    with patch.object(delivery, '_send') as sender:
        delivery.capture_committed_order(order)
        delivery.capture_committed_order(order)
    sender.assert_called_once()
    notice = sender.call_args.args[1]
    assert notice['paymentOrderId'] == order['id']
    assert memory.read('notification_outbox', notice['id'])['status'] == 'processed'
    assert memory.read('notification_outbox', 'old-one')['status'] == 'pending'


def test_local_reminders_suppress_only_matching_device_upcoming_push(memory):
    trip={'id':'trip','travellerId':UID,'startDate':(NOW.date()+timedelta(days=1)).isoformat()}
    memory.claim('itineraries','trip',trip)
    notice=next(n for n in derive_events(UID,[],[trip],now=NOW) if n['category']=='upcoming_trip')
    memory.claim('traveller_notifications',notice['id'],notice);delivery.queue_notification(notice,True)
    delivery.register_device(UID,{**registration(),'localTripReminders':True})
    delivery.register_device(UID,{**registration('second-'+'x'*30),'bindingSecret':'t'*43})
    sends=[];delivery.dispatch(sender=lambda device,n:sends.append(device))
    assert len(sends)==1 and not sends[0]['localTripReminders']
    event(memory);sends.clear();delivery.dispatch(sender=lambda device,n:sends.append(device))
    assert len(sends)==2


@pytest.mark.parametrize('value',['true',1,None,{}])
def test_local_capability_is_a_boolean_not_an_ownership_escape(memory,value):
    with pytest.raises(ValueError):delivery.register_device(UID,{**registration(),'localTripReminders':value})


def test_real_registration_route_explains_disabled_backend(client,mock_traveller_auth,memory,monkeypatch):
    monkeypatch.setenv('TRAVELMATE_PUSH_ENABLED','false')
    result=client.post('/api/traveller/notifications/devices',headers=AUTH,json=registration())
    assert result.status_code==503 and result.json['code']=='push_disabled'


def test_normal_travelmate_application_can_register_with_authorized_allowlist(client,mock_traveller_auth,memory,monkeypatch):
    monkeypatch.setenv('PUSH_ANDROID_APP_IDS','com.example.travelmate_traveller')
    result=client.post('/api/traveller/notifications/devices',headers=AUTH,
                       json={**registration(),'appId':'com.example.travelmate_traveller','localTripReminders':True})
    assert result.status_code==200 and result.json['ok'] is True
    assert memory.read('notification_devices')[0]['localTripReminders'] is True
