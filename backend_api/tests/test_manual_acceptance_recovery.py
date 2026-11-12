"""Reported brochure/profile/date examples, isolated HTTP and projection regressions."""
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from services.package_checkout_contract import validate_package_departure, derive_required_services
from services.package_service import package_submission_error
from services.traveller_notifications import canonical_payment_order, derive_events
from services.recommendation_taxonomy import candidate_concepts
from modules.fr04_hybrid_recommendation import routes
from test_recommendation_relevance import repository, AUTH, UID
from test_operator_hotel_integration import package
from test_fr15_package_checkout_api import package_api, seed_package, post
from test_fr15_package_checkout_stripe import package_payment, seed_attempt, start_checkout, session_response
from test_traveller_notifications import notification_store

NOW = datetime(2026,11,8,16,tzinfo=timezone.utc)  # Nov 9 in Malaysia
BUTTERWORTH = ['Standard admission ticket to Penang Bird Park.',
    'Wildlife experience including access to visitor exhibits and aviaries.',
    'Butterworth Art Walk guided sightseeing experience.']


@pytest.mark.parametrize('text,concept', [('Photogenic murals','photography'),('Scenic viewpoints','photography'),
    ('Street photography','photography'),('美食街','food'),('小贩中心','food'),('茶室','food'),
    ('街頭攝影','photography'),('观景台','photography'),('Kopitiam','food'),('Medan selera','food')])
def test_literal_grounded_provider_labels(text,concept):
    assert concept in candidate_concepts({'title':text})


@pytest.mark.parametrize('text', ['Popular tourist attraction','A market','Visitor centre','A shopping mall'])
def test_tourist_status_is_not_photography_evidence(text):
    assert 'photography' not in candidate_concepts({'title':text})


@pytest.mark.parametrize('text', ['没有壁画','附近有壁画','沒有小販中心','附近有小贩中心'])
def test_bounded_mandarin_negation_and_nearby_are_not_offered_attributes(text):
    concepts=candidate_concepts({'title':'Visitor centre','description':text})
    assert not {'photography','food'} & concepts


def test_personal_legacy_zero_is_stale_and_reuse_refreshes_metadata_and_pool(client,mock_traveller_auth,repository):
    repository.update('travel_preferences',UID,{'interests':['Photography','Food'], 'travelPersonality':'Planner','travelPace':'Moderate'})
    legacy = {'recommendationGenerationId':'legacy','travellerId':UID,'requestedDestination':'Penang',
        'canonicalDestinationScope':routes.normalize_destination_scope('Penang'),
        'recommendationResults':[{'destinationId':'street-art','title':'Venue','address':'Penang, Malaysia','finalScore':61}]}
    repository.store('recommendation_snapshots',legacy,'legacy')
    before=deepcopy(repository.read('recommendation_snapshots','legacy'))
    repository.store('destination_cache',{'destinationId':'street-art','title':'Penang Street Art','address':'Penang, Malaysia'},'street-art')
    repository.store('destination_cache',{'destinationId':'food','title':'Kopitiam','address':'Penang, Malaysia'},'food')
    options={'generationId':'legacy','scoreBasis':'personal_v2','minimumMatchScore':45}
    stale=client.get('/api/fr4/recommendations',headers=AUTH,query_string=options).json
    assert stale['stale'] is True and not stale['recommendations']
    with patch.object(routes,'_provider_destinations') as provider:
        response=client.post('/api/fr4/recommendations/generate',headers=AUTH,json={
            'destinationArea':'Penang','previousGenerationId':'legacy','scoreBasis':'personal_v2','minimumMatchScore':45})
    assert response.status_code==200,response.json
    body=response.json
    ids={row['destinationId'] for row in body['recommendations']}
    assert {'street-art','food'} <= ids
    assert body['pagination']['personalEvidenceCount'] >= 2
    assert all(row['personalSuitabilityScore'] >= 45 for row in body['recommendations'])
    assert repository.read('recommendation_snapshots','legacy') == before
    provider.assert_not_called()
    shared=client.get('/api/fr4/recommendations',headers=AUTH,query_string={**options,'generationId':body['recommendationGenerationId']}).json
    assert not shared['stale'] and shared['recommendations']==body['recommendations']


@pytest.mark.parametrize('now,selected,allowed', [
    (datetime(2026,11,8,15,59,tzinfo=timezone.utc),'2026-11-08',True),
    (NOW,'2026-11-08',False),(NOW,'2026-11-09',True),(NOW,'2026-11-07',False),
    (NOW,'2026-02-30',False),(NOW,'20261109',False),(NOW,'2026-11-10',True)])
def test_malaysia_departure_boundary(now,selected,allowed):
    if allowed: assert validate_package_departure({},selected,now)==selected
    else:
        with pytest.raises(ValueError):validate_package_departure({},selected,now)


def test_fixed_flexible_and_stale_selection_never_switch_departure():
    assert validate_package_departure({},None,NOW) is None
    assert validate_package_departure({'departureDates':['2026-11-10']},None,NOW)=='2026-11-10'
    for selected in ['2026-11-07', None]:
        with pytest.raises(ValueError):
            validate_package_departure({'departureDates':['2026-11-10']},selected,NOW,allow_default=False)


def test_direct_attempt_api_rejects_past_departure_without_financial_writes(client,package_api):
    memory,_identity,headers=package_api
    seed_package(memory,departureDates=['2026-11-07'])
    before=deepcopy(memory.collections)
    with patch('services.package_checkout_contract.malaysia_today',return_value=NOW.date()),patch('services.stripe_service.createPaymentSession') as provider:
        response=post(client,headers(),packageId='package-1',idempotencyKey='past',departureDate='2026-11-07')
    assert response.status_code==409,response.json
    assert not memory.collections.get('package_checkout_attempts')
    assert memory.collections['tourism_packages']==before['tourism_packages']
    provider.assert_not_called()


@pytest.mark.parametrize('change', ['past','removed','archived'])
def test_stale_attempt_rejected_before_stripe_session(client,package_payment,change):
    memory,headers=package_payment
    snapshot=seed_attempt(memory)
    snapshot.update(selectedDepartureDate='2026-11-07',departureDates=['2026-11-07'])
    memory.collections['package_checkout_attempts']['attempt-1']['packageSnapshot']=deepcopy(snapshot)
    if change=='removed':
        snapshot['selectedDepartureDate']='2027-01-01'
        snapshot['departureDates']=['2027-01-01']
        memory.collections['package_checkout_attempts']['attempt-1']['packageSnapshot']=deepcopy(snapshot)
        memory.collections['tourism_packages']['package-1']['departureDates']=['2027-02-01']
    if change=='archived':memory.collections['tourism_packages']['package-1']['approvalStatus']='archived'
    before=deepcopy(memory.collections)
    with patch('services.package_checkout_contract.malaysia_today',return_value=NOW.date()),patch('modules.fr09_payment.routes.createCheckoutSession') as provider:
        response=start_checkout(client,headers)
    assert response.status_code==409,response.json
    assert memory.collections==before
    provider.assert_not_called()


def test_paid_reconciliation_preserves_past_purchased_date_even_after_catalogue_archival(client,package_payment):
    from types import SimpleNamespace
    memory,headers=package_payment
    snapshot=seed_attempt(memory)
    snapshot.update(selectedDepartureDate='2026-11-07',departureDates=['2026-11-07'])
    memory.collections['package_checkout_attempts']['attempt-1']['packageSnapshot']=deepcopy(snapshot)
    with patch('services.package_checkout_contract.malaysia_today',return_value=datetime(2026,11,7).date()),patch('modules.fr09_payment.routes.createCheckoutSession',return_value=session_response()):
        first=start_checkout(client,headers)
    assert first.status_code==200,first.json
    oid=first.json['order']['id']
    memory.collections['tourism_packages']['package-1']['approvalStatus']='archived'
    provider=SimpleNamespace(id='cs_package_1',status='complete',payment_status='paid',amount_total=45025,currency='myr',payment_intent='pi_test')
    with patch('services.package_checkout_contract.malaysia_today',return_value=NOW.date()),patch('modules.fr09_payment.routes.retrieveCheckoutSession',return_value=provider),patch('modules.fr09_payment.routes.createCheckoutSession') as create:
        result=client.get('/api/fr9/orders/'+oid+'/reconcile',headers=headers)
    assert result.status_code==200,result.json
    assert result.json['order']['paymentStatus']=='paid'
    assert memory.collections['checkout_orders'][oid]['packageSnapshot']==snapshot
    assert memory.collections['checkout_orders'][oid]['amountMinor']==45025
    create.assert_not_called()


def test_butterworth_exact_brochure_needs_either_guide_or_admission_choice_not_transport_or_hotel():
    draft=package(inclusions=BUTTERWORTH, accommodationIncluded=False,transportIncluded=False,guideActivitiesIncluded=False)
    original=deepcopy(draft)
    error=package_submission_error(draft)
    assert 'guideActivitiesIncluded' in error and 'Standard admission ticket to Penang Bird Park' in error
    assert 'Butterworth Art Walk guided sightseeing experience' in error
    assert draft==original
    corrected={**draft,'guideActivitiesIncluded':True}
    assert package_submission_error(corrected) is None
    requirements=derive_required_services(corrected)
    assert requirements['guideActivities']['required'] and not requirements['guideActivities']['uncertain']
    assert not requirements['accommodation']['required'] and not requirements['transport']['required']


@pytest.mark.parametrize('text,required', [('Free self-guided art walk.',False),('Optional admission tickets.',False),
    ('Free attraction admission.',False),('Standard admission ticket to Penang Bird Park.',True),
    ('Butterworth Art Walk guided sightseeing experience.',True)])
def test_entitlements_are_independent_of_optional_free_visits(text,required):
    result=derive_required_services({'inclusions':[text]})['guideActivities']
    assert result['required']==required and not result['uncertain']


def test_financial_aliases_share_event_but_distinct_purchases_and_transitions_remain():
    order={'id':'checkout-1','travellerId':UID,'paymentStatus':'paid','paidAt':'2026-11-09T01:00:00Z','packageSnapshot':{'title':'Butterworth Full Day'}}
    ledger={'id':'ledger-1','orderReference':'ledger-display','checkoutOrderId':'checkout-1','travellerId':UID,'paymentStatus':'paid'}
    before=deepcopy((order,ledger))
    linked=canonical_payment_order(ledger,UID,lambda key:order)
    events=derive_events(UID,[order,linked],[],now=NOW)
    assert len(events)==1 and events[0]['target']['orderId']=='checkout-1'
    distinct={**order,'id':'checkout-2'}
    assert len(derive_events(UID,[order,linked,distinct],[],now=NOW))==2
    assert len(derive_events(UID,[order,{**order,'paymentStatus':'refunded'}],[],now=NOW))==2
    assert canonical_payment_order(ledger,UID,lambda key:{**order,'travellerId':'other'})==ledger
    assert (order,ledger)==before


def test_existing_inbox_context_is_response_only_read_and_timestamp_preserved(client,mock_traveller_auth,notification_store):
    db,_provider=notification_store
    db[('checkout_orders','one')]={'id':'one','travellerId':UID,'paymentStatus':'paid','status':'paid',
                                   'packageSnapshot':{'title':'Penang package'},'currency':'MYR','amountMinor':91600}
    nid=derive_events(UID,[db[('checkout_orders','one')]],[],now=NOW)[0]['id']
    saved={'id':nid,'travellerId':UID,'category':'payment','title':'Payment status updated','message':'Your recorded payment status is paid.',
        'target':{'screen':'payments','orderId':'one'},'createdAt':'2026-11-01T00:00:00Z','read':True,'readAt':'2026-11-02T00:00:00Z'}
    db[('traveller_notifications',nid)]=deepcopy(saved)
    response=client.get('/api/traveller/notifications',headers=AUTH)
    assert response.status_code==200
    item=next(item for item in response.json['items'] if item['id']==nid)
    assert item['title']=='Payment Successful'
    assert item['message']=='Your payment of MYR 916.00 for Penang package was confirmed.'
    assert 'sourceLabel' not in item and item['target']['orderId']=='one'
    assert item['createdAt']==saved['createdAt'] and item['read'] and item['readAt']==saved['readAt']
    assert db[('traveller_notifications',nid)]==saved


def test_commit_hook_alias_replay_keeps_one_inbox_and_outbox_without_sending(monkeypatch):
    from services import notification_delivery as delivery
    now=datetime.now(timezone.utc)
    order={'id':'checkout-1','travellerId':UID,'paymentStatus':'paid','paidAt':now.isoformat()}
    ledger={'id':'ledger-1','orderReference':'other-display','checkoutOrderId':'checkout-1','travellerId':UID,'paymentStatus':'paid'}
    store={('checkout_orders','checkout-1'):deepcopy(order)}
    def read(collection,key):return deepcopy(store.get((collection,key)))
    def claim(collection,key,value):
        created=(collection,key) not in store
        if created:store[collection,key]=deepcopy(value)
        return deepcopy(store[collection,key]),created
    monkeypatch.setattr(delivery,'enabled',lambda:True)
    monkeypatch.setattr(delivery,'retrieveRecord',read)
    monkeypatch.setattr(delivery,'claimRecord',claim)
    with patch.object(delivery,'dispatch') as dispatch,patch.object(delivery,'_send') as send:
        delivery.capture_committed_order(order)
        first=deepcopy(store)
        delivery.capture_committed_order(ledger)
        delivery.capture_committed_order(order)
    assert store==first
    assert sum(collection=='traveller_notifications' for collection,_ in store)==1
    assert sum(collection=='notification_outbox' for collection,_ in store)==1
    assert dispatch.call_count==3
    send.assert_not_called()
