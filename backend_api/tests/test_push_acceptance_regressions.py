"""Push acceptance source regressions: isolated records and fake senders only."""
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch
import pytest
from test_android_push_delivery import memory, registration, event, NOW, UID
from services import notification_delivery as delivery
from services.traveller_notifications import derive_events


def paid_package():
    order={'id':'package-order','operatorId':'op','travellerId':UID,'quoteType':'package','paymentStatus':'paid',
        'paidAt':NOW.isoformat(),'updatedAt':NOW.isoformat(),'fulfilledTripId':'owned-package-trip',
        'fulfillmentStatus':'awaiting_operator_fulfillment','fulfillmentRecord':{'status':'awaiting_operator_fulfillment','services':{}}}
    trip={'id':'owned-package-trip','travellerId':UID,'operatorId':'op','checkoutOrderId':order['id'],
        'createdAt':NOW.isoformat(),'tripType':'package'}
    return order,trip


def test_paid_package_trip_creation_is_a_real_separate_event():
    order,trip=paid_package();before=deepcopy((order,trip))
    events=derive_events(UID,[order],[trip],now=NOW)
    assert {e['category'] for e in events}=={'payment','package_booking'}
    assert next(e for e in events if e['category']=='package_booking')['target']['tripId']==trip['id']
    assert (order,trip)==before


def test_actual_arrangement_and_decline_events_do_not_claim_supplier_confirmation():
    order,trip=paid_package()
    order['fulfillmentStatus']='partially_fulfilled'
    order['fulfillmentRecord']={'status':'partially_fulfilled','services':{'transport':{'required':True,'status':'confirmed',
        'reference':'PRIVATE-SUPPLIER-REF','confirmedAt':NOW.isoformat(),'confirmedBy':'op','provenance':'operator_attested'}}}
    events=derive_events(UID,[order],[trip],now=NOW)
    assert any(e['category']=='arrangements_update' for e in events)
    assert 'PRIVATE-SUPPLIER-REF' not in str(events)
    order['fulfillmentStatus']='fulfillment_declined'
    order['fulfillmentRecord'].update(status='fulfillment_declined',declinedAt=NOW.isoformat(),declinedBy='op',declineReason='PRIVATE-REASON')
    events=derive_events(UID,[order],[trip],now=NOW)
    assert any(e['category']=='booking_attention' for e in events)
    assert 'PRIVATE-REASON' not in str(events)


def test_changed_application_allowlist_blocks_previously_registered_device(memory,monkeypatch):
    delivery.register_device(UID,registration());event(memory)
    monkeypatch.setenv('PUSH_ANDROID_APP_IDS','different-approved-app')
    calls=[];delivery.dispatch(sender=lambda *args:calls.append(args))
    assert not calls


def test_decline_alert_survives_the_real_inactive_trip_mirror(memory):
    order,trip=paid_package()
    order['fulfillmentStatus']='fulfillment_declined'
    order['fulfillmentRecord']={'status':'fulfillment_declined','declinedAt':NOW.isoformat(),'declinedBy':'op','services':{}}
    trip['fulfillmentStatus']='fulfillment_declined'
    memory.claim('checkout_orders',order['id'],order);memory.claim('itineraries',trip['id'],trip)
    events=derive_events(UID,[order],[trip],now=NOW)
    assert 'package_booking' not in {e['category'] for e in events}
    notice=next(e for e in events if e['category']=='booking_attention')
    assert notice['target']['screen']=='package_trip' and delivery.still_due(notice,NOW)
    memory.claim('traveller_notifications',notice['id'],notice);delivery.queue_notification(notice,True)
    delivery.register_device(UID,registration());calls=[]
    delivery.dispatch(sender=lambda *args:calls.append(args))
    assert len(calls)==1


@pytest.mark.parametrize('category',['package_booking','arrangements_ready','arrangements_update'])
def test_business_notifications_revalidate_current_entitlements(memory,category):
    order,trip=paid_package()
    order['fulfillmentStatus']='partially_fulfilled' if category=='arrangements_update' else 'trip_ready'
    order['fulfillmentRecord']={'status':order['fulfillmentStatus'],'confirmedAt':NOW.isoformat(),'confirmedBy':'op','services':{
        'transport':{'required':True,'status':'confirmed','reference':'actual','confirmedAt':NOW.isoformat(),'confirmedBy':'op','provenance':'operator_attested'}}}
    memory.claim('checkout_orders',order['id'],order);memory.claim('itineraries',trip['id'],trip)
    notice=next(e for e in derive_events(UID,[order],[trip],now=NOW) if e['category']==category)
    assert delivery.still_due(notice,NOW)
    memory.rows[('checkout_orders',order['id'])]['paymentStatus']='refunded'
    assert not delivery.still_due(notice,NOW)


def test_different_orders_and_replays_keep_true_separate_events(memory):
    order,trip=paid_package();delivery.register_device(UID,registration())
    other=deepcopy(order);other.update(id='another-order',fulfilledTripId='another-trip')
    second=deepcopy(trip);second.update(id='another-trip',checkoutOrderId=other['id'])
    for o,t in [(order,trip),(other,second)]:
        memory.claim('checkout_orders',o['id'],o);memory.claim('itineraries',t['id'],t)
    before=deepcopy(memory.rows)
    with patch.object(delivery,'dispatch'):
        for o in (order,other,order,other):delivery.capture_committed_order(o)
    notices=memory.read('traveller_notifications')
    assert len(notices)==4 and len(memory.read('notification_outbox'))==4
    assert {n['category'] for n in notices}=={'payment','package_booking'}
    for key,row in before.items():assert memory.rows[key]==row
    calls=[];assert delivery.dispatch(sender=lambda *args:calls.append(args))['sent']==4
    assert delivery.dispatch(sender=lambda *args:calls.append(args))['sent']==0 and len(calls)==4


@pytest.mark.parametrize('kind',['no_payment','wrong_trip_owner','wrong_order_link','no_operator_attestation','suggested_supplier'])
def test_no_invented_package_or_supplier_events(kind):
    order,trip=paid_package()
    if kind=='no_payment':order['paymentStatus']='unpaid'
    if kind=='wrong_trip_owner':trip['travellerId']='another'
    if kind=='wrong_order_link':trip['checkoutOrderId']='another'
    if kind in {'no_operator_attestation','suggested_supplier'}:
        order['fulfillmentStatus']='partially_fulfilled'
        order['fulfillmentRecord']={'status':'partially_fulfilled','services':{'transport':{'required':True,'status':'confirmed' if kind=='no_operator_attestation' else 'unconfirmed'}}}
    events=derive_events(UID,[order],[trip],now=NOW)
    if kind in {'no_payment','wrong_trip_owner','wrong_order_link'}:assert not any(e['category']=='package_booking' for e in events)
    assert not any(e['category']=='arrangements_update' for e in events)


def test_old_package_creation_does_not_become_a_fresh_system_alert(memory):
    order,trip=paid_package();trip['createdAt']=(NOW-timedelta(days=60)).isoformat()
    notice=next(e for e in derive_events(UID,[order],[trip],now=NOW) if e['category']=='package_booking')
    delivery.queue_notification(notice,True)
    assert memory.read('notification_outbox')==[]


def test_retry_diagnostics_never_store_arbitrary_provider_text(memory,caplog):
    delivery.register_device(UID,registration());notice=event(memory)
    class PrivateError(Exception):code='PRIVATE_ACCOUNT_OR_TOKEN'
    def fail(*args):raise PrivateError('PRIVATE_PAYMENT_DETAIL')
    with caplog.at_level('INFO',logger='services.notification_delivery'):
        delivery.dispatch(sender=fail)
    assert 'PRIVATE' not in caplog.text and notice['id'] in caplog.text and 'outcome=retry' in caplog.text
    assert memory.read('notification_deliveries')[0]['errorCode']=='send_failed'


def test_send_rechecks_current_app_before_provider_submission(memory,monkeypatch):
    key=delivery.register_device(UID,registration());event(memory)
    claim=delivery._claim_delivery
    def changed(*args):
        result=claim(*args);memory.rows[('notification_devices',key)]['appId']='revoked-app';return result
    monkeypatch.setattr(delivery,'_claim_delivery',changed)
    calls=[];delivery.dispatch(sender=lambda *args:calls.append(args))
    assert not calls and memory.read('notification_deliveries')[0]['status']=='cancelled'


def test_public_presentation_is_category_only(client,mock_traveller_auth,memory):
    notice=event(memory)
    memory.rows[('traveller_notifications',notice['id'])]['message']='PRIVATE_OWNED_PAYMENT_DATA'
    response=client.get('/api/traveller/notifications/'+notice['id'],headers={'Authorization':'Bearer fixture'})
    assert response.status_code==200
    assert response.json['presentation']['title']=='TravelMate — Payment Successful'
    assert 'PRIVATE' not in str(response.json['presentation'])
