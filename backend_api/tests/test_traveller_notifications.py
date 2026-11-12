from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from services.traveller_notifications import derive_events, coordinates, inbox_presentation
from services.packing_checklist_service import checklist_id

UID='test_traveller_uid'
AUTH={'Authorization':'Bearer test'}
NOW=datetime(2026,11,8,15,tzinfo=timezone.utc)


def trip(**updates):
    return {'id':'own-trip','travellerId':UID,'title':'Penang trip','destinationArea':'Penang',
            'startDate':'2026-11-11','endDate':'2026-11-13',
            'destinationCoordinates':{'latitude':5.4141,'longitude':100.3288},**updates}


def order(**updates):
    return {'id':'own-order','travellerId':UID,'paymentStatus':'paid','status':'paid',
        'fulfilledTripId':'own-trip','fulfillmentStatus':'trip_ready',
        'fulfillmentRecord':{'status':'trip_ready','confirmedBy':'operator','confirmedAt':'2026-11-08T10:00:00Z'},
        'clientSecret':'private-do-not-expose','checkoutUrl':'private-url',**updates}


def checklist(**updates):
    return {'travellerId':UID,'tripId':'own-trip',
        'items':[{'applicable':True,'suppressed':False,'isPacked':False},
                 {'applicable':True,'suppressed':False,'isPacked':True}],**updates}


def forecast(**updates):
    return {'daily':{'time':['2026-11-11'],'weather_code':[63],
                     'precipitation_probability_max':[70],**updates}}


def test_five_truthful_categories_from_actual_record_fields_and_no_mutation():
    data=([order()],[trip()],{'own-trip':checklist()},{'own-trip':forecast()})
    before=deepcopy(data)
    events=derive_events(UID,*data,now=NOW)
    assert {e['category'] for e in events}=={'payment','arrangements_ready','upcoming_trip','packing','weather'}
    assert len(events)==5 and len({e['id'] for e in events})==5
    assert 'private' not in str(events)
    assert 'operator attestation' in next(e['message'] for e in events if e['category']=='arrangements_ready')
    assert '1 / 2' in next(e['message'] for e in events if e['category']=='packing')
    assert data==before


@pytest.mark.parametrize('start,status,expected',[('2026-11-11','generated',True),('2026-11-09','generated',True),
    ('2026-11-10','generated',False),('2026-11-08','generated',False),('2026-11-07','generated',False),
    ('2026-02-30','generated',False),('bad','generated',False),('2026-11-11','cancelled',False)])
def test_trip_reminder_exact_malaysia_date_boundaries(start,status,expected):
    events=derive_events(UID,[],[trip(startDate=start,status=status)],now=NOW)
    assert bool(events)==expected


def test_midnight_invalid_end_and_weather_on_later_trip_day():
    after_midnight=datetime(2026,11,8,16,tzinfo=timezone.utc)
    assert not derive_events(UID,[],[trip()],now=after_midnight)
    assert not derive_events(UID,[],[trip(endDate='2026-11-10')],now=NOW)
    events=derive_events(UID,[],[trip()],forecasts={'own-trip':forecast(time=['2026-11-12'],weather_code=[95])},now=NOW)
    assert any(e['category']=='weather' and '2026-11-12' in e['message'] for e in events)


@pytest.mark.parametrize('changes',[{'travellerId':'other'}, {'items':[]},
    {'items':[{'applicable':True,'suppressed':False,'isPacked':True}]},
    {'items':[{'applicable':True,'suppressed':False}]}, {'tripId':'other'}])
def test_packing_requires_valid_owned_incomplete_applicable_items(changes):
    events=derive_events(UID,[],[trip()],{'own-trip':checklist(**changes)},now=NOW)
    assert not any(e['category']=='packing' for e in events)


def test_weather_is_actual_forecast_not_unavailable_data_or_repeated_rain():
    assert not any(e['category']=='weather' for e in derive_events(UID,[],[trip()],now=NOW))
    def event(code,prob):
        return [e for e in derive_events(UID,[],[trip()],forecasts={'own-trip':forecast(weather_code=[code],precipitation_probability_max=[prob])},now=NOW) if e['category']=='weather']
    assert not event(0,20) and not event(0,None) and event(0,80)
    assert event(63,70)[0]['id']==event(65,90)[0]['id']
    assert event(95,90)[0]['id']!=event(65,90)[0]['id']
    assert 'not an official' in event(95,90)[0]['message']


def test_foreign_or_simulated_payments_and_unattested_readiness_do_not_notify():
    for updates in [{'travellerId':'other'},{'isSimulated':True},{'bookingMode':'simulation'}]:
        assert not derive_events(UID,[order(**updates)],[],now=NOW)
    events=derive_events(UID,[order(fulfillmentRecord={})],[trip()],now=NOW)
    assert not any(e['category']=='arrangements_ready' for e in events)
    assert not any(e['category']=='arrangements_ready' for e in derive_events(UID,[order(paymentStatus='refunded')],[trip()],now=NOW))
    assert not any(e['category']=='arrangements_ready' for e in derive_events(UID,[order()],[trip(travellerId='other')],now=NOW))
    assert coordinates(trip(destinationCoordinates={'latitude':float('nan'),'longitude':0})) is None


@pytest.mark.parametrize('payment,status,expected',[('paid','paid','paid'),('failed','payment_failed','failed'),
    ('cancelled','cancelled','cancelled'),('unpaid','expired','expired'),('pending','payment_pending',None),
    ('unpaid','paid',None)])
def test_notifications_follow_real_persisted_payment_lifecycle(payment,status,expected):
    events=derive_events(UID,[order(paymentStatus=payment,status=status)],[],now=NOW)
    if expected:
        assert len(events)==1 and events[0]['category']=='payment' and f'is {expected}.' in events[0]['message']
    else:
        assert not events


@pytest.mark.parametrize('state',['succeeded','successful','success','completed'])
def test_legacy_success_aliases_use_the_same_paid_event_identity(state):
    records=[order(paymentStatus=state,id='legacy',checkoutOrderId='own-order'),order()]
    events=derive_events(UID,records,[],now=NOW)
    assert len(events)==1 and events[0]['category']=='payment' and 'is paid.' in events[0]['message']


@pytest.fixture
def notification_store():
    db={('checkout_orders','own-order'):order(),('itineraries','own-trip'):trip(),
        ('packing_checklists',checklist_id(UID,'own-trip')):checklist()}
    def read(coll,doc=None,filters=None,**kwargs):
        if doc is not None:return deepcopy(db.get((coll,doc)))
        return [deepcopy({'id':did,**value}) for (collection,did),value in db.items() if collection==coll
                and all(value.get(field)==expected for field,op,expected in filters or [])]
    def claim(coll,doc,data):
        assert coll in {'notification_weather_cache','traveller_notifications'}
        created=(coll,doc) not in db
        if created:db[(coll,doc)]=deepcopy(data)
        return deepcopy(db[(coll,doc)]),created
    def write(coll,data,doc=None,**kwargs):
        assert coll=='notification_weather_cache'
        db[(coll,doc)]=deepcopy(data)
        return data
    def update(coll,doc,data,**kwargs):
        assert coll=='traveller_notifications'
        db[(coll,doc)].update(deepcopy(data))
        return deepcopy(db[(coll,doc)])
    module='modules.traveller_notifications.'
    with patch(module+'retrieveRecord',side_effect=read),patch(module+'claimRecord',side_effect=claim), \
         patch(module+'storeRecord',side_effect=write),patch(module+'updateRecord',side_effect=update), \
         patch(module+'retrieveSevenDayForecast',return_value=forecast()) as provider,patch(module+'datetime') as dt:
        dt.now.return_value=NOW
        yield db,provider


def test_authenticated_reconcile_read_unread_dedup_cache_and_owner_routes(client,mock_traveller_auth,notification_store):
    db,provider=notification_store
    before=deepcopy(db)
    first=client.get('/api/traveller/notifications',headers=AUTH)
    assert first.status_code==200 and first.json['unreadCount']==5
    assert 'private' not in first.get_data(as_text=True)
    upcoming=next(item for item in first.json['items'] if item['category']=='upcoming_trip')
    assert upcoming['message']=='Your Penang trip starts in 3 days, on 11 November 2026.'
    nid=first.json['items'][0]['id']
    assert client.patch('/api/traveller/notifications/'+nid,headers=AUTH,json={'read':True}).status_code==200
    second=client.get('/api/traveller/notifications',headers=AUTH)
    assert second.json['unreadCount']==4 and len(second.json['items'])==5
    provider.assert_called_once_with({'latitude':5.4141,'longitude':100.3288})
    assert client.patch('/api/traveller/notifications/'+nid,headers=AUTH,json={'read':False}).status_code==200
    assert client.get('/api/traveller/notifications',headers=AUTH).json['unreadCount']==5
    assert client.patch('/api/traveller/notifications/'+nid,headers=AUTH,json={'read':'true'}).status_code==400
    db[('traveller_notifications','foreign')]={'travellerId':'other','read':False}
    assert client.patch('/api/traveller/notifications/foreign',headers=AUTH,json={'read':True}).status_code==404
    assert not any(item['id']=='foreign' for item in client.get('/api/traveller/notifications',headers=AUTH).json['items'])
    for key,value in before.items():assert db[key]==value


def test_inbox_words_legacy_trip_and_does_not_use_unverified_payment_amount():
    item = {'category':'upcoming_trip','message':'Butterworth Heritage & Wildlife Discovery – Full Day Tour starts in 1 day(s), on 2026-11-14.'}
    inbox_presentation(item)
    assert item['message']=='Your Butterworth Heritage & Wildlife Discovery trip starts in 1 day, on 14 November 2026.'
    payment = {'category':'payment','paymentState':'paid','message':'Your recorded payment status is paid.',
               'sourceLabel':'Order very-long-reference','target':{'orderId':'very-long-reference'}}
    inbox_presentation(payment, {'status':'payment_mismatch','paymentStatus':'paid','amountMinor':91600,'currency':'MYR'})
    assert payment['message']=='Your recorded payment status is paid.'
    assert payment['target']['orderId']=='very-long-reference' and 'sourceLabel' not in payment


@pytest.mark.parametrize('changed', [
    None, {'status': 'cancelled'}, {'deletedAt': 'recorded'}, {'endDate': 'invalid'},
    {'startDate': '2026-11-12'}, {'travellerId': 'someone-else'},
])
def test_stale_trip_reminders_leave_inbox_and_badge_without_deleting_history(
    client, mock_traveller_auth, notification_store, changed,
):
    db, _ = notification_store
    path = '/api/traveller/notifications'
    first = client.get(path, headers=AUTH).json
    reminder_ids = {row['id'] for row in first['items'] if row['category'] in {
        'upcoming_trip', 'packing', 'weather',
    }}
    assert len(reminder_ids) == 3
    if changed is None:
        del db[('itineraries', 'own-trip')]
    else:
        db[('itineraries', 'own-trip')].update(changed)
    after = client.get(path, headers=AUTH).json
    assert not reminder_ids.intersection(row['id'] for row in after['items'])
    assert after['unreadCount'] == 2
    for nid in reminder_ids:
        assert ('traveller_notifications', nid) in db
        assert client.get(f'{path}/{nid}', headers=AUTH).status_code == 404


def test_reopening_inbox_uses_the_current_malaysia_calendar_day(
    client, mock_traveller_auth, notification_store,
):
    db, _ = notification_store
    path = '/api/traveller/notifications'
    first = client.get(path, headers=AUTH).json
    notice = next(row for row in first['items'] if row['category'] == 'upcoming_trip')
    assert 'starts in 3 days' in notice['message']
    with patch('modules.traveller_notifications.datetime') as clock:
        clock.now.return_value = datetime(2026, 11, 8, 16, tzinfo=timezone.utc)
        refreshed = client.get(path, headers=AUTH).json
    same = next(row for row in refreshed['items'] if row['id'] == notice['id'])
    assert same['message'] == 'Your Penang trip starts in 2 days, on 11 November 2026.'
    assert same['read'] == notice['read']
    assert 'starts in 3 day(s)' in db[('traveller_notifications', notice['id'])]['message']


@pytest.mark.parametrize('role',['anonymous','operator','admin'])
def test_notification_routes_are_traveller_only(client,request,role):
    if role!='anonymous':request.getfixturevalue('mock_'+role+'_auth')
    headers={} if role=='anonymous' else AUTH
    assert client.get('/api/traveller/notifications',headers=headers).status_code==(401 if role=='anonymous' else 403)
    assert client.patch('/api/traveller/notifications/x',headers=headers,json={'read':True}).status_code==(401 if role=='anonymous' else 403)


def test_reconcile_reads_actual_legacy_payment_collection_without_replay_duplicates(client,mock_traveller_auth,notification_store):
    db,_=notification_store
    db[('payment_records','legacy-linked')]={'travellerId':UID,'paymentStatus':'succeeded','checkoutOrderId':'own-order'}
    db[('payment_records','legacy-separate')]={'travellerId':UID,'paymentStatus':'succeeded','clientSecret':'private'}
    first=client.get('/api/traveller/notifications',headers=AUTH)
    assert first.status_code==200 and len(first.json['items'])==6
    assert len([item for item in first.json['items'] if item['category']=='payment'])==2
    assert 'private' not in first.get_data(as_text=True)
    assert len(client.get('/api/traveller/notifications',headers=AUTH).json['items'])==6


def test_unavailable_forecast_does_not_fake_weather_and_store_error_is_retryable(client,mock_traveller_auth,notification_store):
    _,provider=notification_store
    provider.side_effect=RuntimeError('Unavailable')
    result=client.get('/api/traveller/notifications',headers=AUTH)
    assert result.status_code==200 and not any(e['category']=='weather' for e in result.json['items'])
    with patch('modules.traveller_notifications.claimRecord',side_effect=RuntimeError('Unavailable')):
        assert client.get('/api/traveller/notifications',headers=AUTH).status_code==503
