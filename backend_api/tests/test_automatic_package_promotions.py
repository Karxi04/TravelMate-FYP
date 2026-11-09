"""Authoritative campaign pricing, isolated routes and mocked Stripe; no external money/data."""
from copy import deepcopy
from unittest.mock import patch
import pytest
from services.package_pricing import calculate_package_pricing, pricing_fingerprint
from services.package_checkout_contract import prepare_package_snapshot
from services.public_content_projection import public_package
from test_package_checkout_contract import package
from test_cross_system_commerce import campaign
from test_fr15_package_checkout_stripe import package_payment, session_response

NOW='2026-11-09T10:00:00Z'

@pytest.mark.parametrize(('kind','value','basis','expected'), [('percentage','12.5','per_person',218.75),('fixed','31.27','per_person',218.73),('percentage','12.5','per_group',87.5),('fixed','31.27','per_group',68.73)])
def test_one_money_contract(kind,value,basis,expected):
    p=package(childPrice=50,priceBasis=basis)
    c=campaign(discountType=kind,discountValue=value,packageIds=['p1','p2'])
    q=calculate_package_pricing(p,{'adults':2,'children':1},[c],now=NOW)
    s=prepare_package_snapshot(p,{'id':'op1'},participants={'adults':2,'children':1},campaigns=[c],now=NOW)
    assert q==s['pricingBreakdown'] and s['price']==expected and s['amountMinor']==round(expected*100)
    assert s['quoteToken']==pricing_fingerprint(s)

@pytest.mark.parametrize('changes',[{'reviewStatus':'pending'},{'reviewStatus':'rejected'},{'campaignStatus':'suspended'},{'startDate':'2026-11-10'},{'endDate':'2026-11-08'},{'operatorId':'other'},{'packageIds':['other']},{'discountValue':0},{'discountType':'marketing'},{'usageLimit':5}])
def test_ineligible_never_discounts(changes):
    assert calculate_package_pricing(package(),campaigns=[campaign(**changes)],now=NOW)['finalPayable']==100


def test_best_single_offer_tie_and_coupon():
    a=campaign(id='a',discountValue=20)
    b=campaign(id='b',discountType='fixed',discountValue=20)
    coupon=campaign(id='c',discountValue=30,promoCode='SAVE')
    for offers in ([b,a,coupon],[coupon,a,b]):
        q=calculate_package_pricing(package(),campaigns=offers,now=NOW)
        assert q['finalPayable']==80 and q['promotion']['id']=='a'
        q=calculate_package_pricing(package(),campaigns=offers,promo_code='save',now=NOW)
        assert q['finalPayable']==70 and q['promotionDiscount']==30
    with pytest.raises(ValueError,match='Promo code'):calculate_package_pricing(package(),campaigns=[coupon],promo_code='invalid',now=NOW)


def test_legacy_manual_fields_cannot_compete_and_source_untouched():
    p=package(promotionalPrice=1,originalPrice=999,promotionStart='2020-01-01',promotionEnd='2099-01-01')
    original=deepcopy(p)
    q=calculate_package_pricing(p,campaigns=[campaign()],now=NOW)
    assert q['finalPayable']==85 and p==original
    projection=public_package(p,campaigns=[campaign()])
    assert not {'promotionalPrice','originalPrice','promotionStart','promotionEnd'} & projection.keys()
    assert projection['packagePricing']['offers'][0]['finalPayable']==85


@pytest.mark.parametrize('participants',[{'adults':1,'children':0},{'adults':1,'children':3}])
def test_minimum_and_capacity(participants):
    with pytest.raises(ValueError):calculate_package_pricing(package(minimumTravellers=2,maximumTravellers=3,childPrice=50),participants)


def configure_routes(memory,monkeypatch):
    for module in ('fr15_package_checkout','shared_public_content','fr12_tourism_operator_management','fr13_administrator_management'):
        monkeypatch.setattr(f'modules.{module}.routes.retrieveRecord',memory.retrieve)
    monkeypatch.setattr('modules.fr15_package_checkout.routes.claimRecord',memory.claim)
    for module in ('fr12_tourism_operator_management','fr13_administrator_management'):
        monkeypatch.setattr(f'modules.{module}.routes.updateRecord',memory.update)
    p=package(childPrice=50)
    memory.seed('users','op1',{'role':'operator','status':'active','verificationStatus':'approved'})
    memory.seed('users','admin1',{'role':'admin','status':'active'})
    memory.seed('tourism_packages','p1',p)
    memory.seed('tourism_packages','p2',package(id='p2'))
    memory.seed('promotional_campaigns','c1',campaign(startDate='2020-01-01',endDate='2099-01-01',packageIds=['p1','p2']))
    return p


def test_public_quote_attempt_stripe_parity_and_paid_history(client,package_payment,monkeypatch):
    memory,headers=package_payment;p=configure_routes(memory,monkeypatch)
    payload={'packageId':'p1','participants':{'adults':2,'children':1}}
    public=client.get('/api/public/tourism-packages',headers=headers).get_json()['items']
    assert {x['id'] for x in public}>={'p1','p2'}
    assert next(x for x in public if x['id']=='p1')['packagePricing']['offers'][0]['finalPayable']==85
    offers=client.get('/api/public/promotional-campaigns',headers=headers).get_json()['items']
    assert {x['packageId'] for x in offers}=={'p1','p2'}
    quote=client.post('/api/fr15/package-checkout-attempts/quote',headers=headers,json=payload).get_json()['quote']
    assert quote['price']==212.5
    result=client.post('/api/fr15/package-checkout-attempts',headers=headers,json={**payload,'quoteToken':quote['quoteToken'],'idempotencyKey':'one'})
    assert result.status_code==200,result.get_json()
    attempt=result.get_json()['attempt'];aid=attempt['id']
    with patch('modules.fr09_payment.routes.createCheckoutSession',return_value=session_response()) as stripe:
        result=client.post(f'/api/fr9/package-checkout-attempts/{aid}/checkout/session',headers=headers,json={'amount':1})
    assert result.status_code==200,result.get_json()
    order=result.get_json()['order'];assert stripe.call_args.args[0]==212.5
    assert order['amountMinor']==21250 and order['packageSnapshot']['pricingBreakdown']['promotion']['id']=='c1'
    stored=deepcopy(memory.retrieve('checkout_orders',order['id']))
    memory.update('promotional_campaigns','c1',{'discountValue':99})
    assert memory.retrieve('checkout_orders',order['id'])==stored


@pytest.mark.parametrize('change',[{'endDate':'2000-01-01'},{'discountValue':20},{'termsConditions':'New terms'},{'reviewStatus':'rejected'}])
def test_changed_offer_blocks_before_stripe_and_preserves_attempt(client,package_payment,monkeypatch,change):
    memory,headers=package_payment;configure_routes(memory,monkeypatch)
    payload={'packageId':'p1','idempotencyKey':'change'}
    attempt=client.post('/api/fr15/package-checkout-attempts',headers=headers,json=payload).get_json()['attempt']
    old=deepcopy(attempt)
    memory.update('promotional_campaigns','c1',change)
    with patch('modules.fr09_payment.routes.createCheckoutSession') as stripe:
        result=client.post(f"/api/fr9/package-checkout-attempts/{attempt['id']}/checkout/session",headers=headers,json={})
    assert result.status_code==409 and 'changed' in result.get_json()['error']
    stripe.assert_not_called()
    assert memory.retrieve('package_checkout_attempts',attempt['id'])==old
    refreshed=client.post('/api/fr15/package-checkout-attempts/quote',headers=headers,json=payload)
    assert refreshed.status_code==200


def test_old_unpaid_quote_needs_refresh_without_mutation(client,package_payment,monkeypatch):
    memory,headers=package_payment;configure_routes(memory,monkeypatch)
    memory.seed('package_checkout_attempts','old',{'travellerId':'traveller-1','packageSnapshot':{'packageId':'p1','operatorId':'op1','price':100,'currency':'MYR'}})
    original=memory.retrieve('package_checkout_attempts','old')
    with patch('modules.fr09_payment.routes.createCheckoutSession') as stripe:
        r=client.post('/api/fr9/package-checkout-attempts/old/checkout/session',headers=headers,json={})
    assert r.status_code==409 and 'older unpaid quote' in r.get_json()['error']
    stripe.assert_not_called();assert memory.retrieve('package_checkout_attempts','old')==original


def test_quote_changed_before_attempt_requires_review(client,package_payment,monkeypatch):
    memory,headers=package_payment;configure_routes(memory,monkeypatch)
    q=client.post('/api/fr15/package-checkout-attempts/quote',headers=headers,json={'packageId':'p1'}).get_json()['quote']
    memory.update('promotional_campaigns','c1',{'discountValue':30})
    with patch('modules.fr15_package_checkout.routes.claimRecord') as claim:
        r=client.post('/api/fr15/package-checkout-attempts',headers=headers,json={'packageId':'p1','idempotencyKey':'quoted','quoteToken':q['quoteToken']})
    assert r.status_code==409 and r.get_json()['code']=='package_price_changed';claim.assert_not_called()


def test_multi_package_admin_ownership_approval_and_edit(client,package_payment,monkeypatch):
    memory,_=package_payment;configure_routes(memory,monkeypatch)
    admin={'Authorization':'Bearer admin1'};operator={'Authorization':'Bearer op1'}
    memory.update('promotional_campaigns','c1',{'reviewStatus':'pending'})
    memory.update('tourism_packages','p2',{'operatorId':'other'})
    r=client.post('/api/fr13/campaigns/c1/review',headers=admin,json={'decision':'approved'})
    assert r.status_code==409
    memory.update('tourism_packages','p2',{'operatorId':'op1'})
    assert client.post('/api/fr13/campaigns/c1/review',headers=admin,json={'decision':'approved'}).status_code==200
    assert client.put('/api/fr12/campaigns/c1',headers=operator,json={'description':'Changed'}).status_code==200
    edited=memory.retrieve('promotional_campaigns','c1')
    assert edited['reviewStatus']=='draft' and edited['campaignStatus']=='draft'


@pytest.mark.parametrize('field',['originalPrice','promotionalPrice','promotionStart','promotionEnd'])
def test_package_editor_cannot_set_competing_promotion(client,package_payment,monkeypatch,field):
    memory,_=package_payment;configure_routes(memory,monkeypatch)
    h={'Authorization':'Bearer op1'}
    for path,method in [('/api/fr12/packages','post'),('/api/fr12/packages/p1','put')]:
        r=getattr(client,method)(path,headers=h,json={field:1})
        assert r.status_code==400 and 'Promotions & Campaigns' in r.get_json()['error']


def test_stripe_sdk_minor_units_match_shared_quote(monkeypatch):
    from services import stripe_service
    q=calculate_package_pricing(package(adultPrice='10.005',childPrice='4.994'),{'adults':2,'children':1},[campaign(discountValue='12.5')],now=NOW)
    monkeypatch.setattr(stripe_service,'_setup',lambda:True)
    with patch.object(stripe_service.stripe.checkout.Session,'create',return_value={}) as create:
        stripe_service.createCheckoutSession(q['finalPayable'],'MYR','synthetic','order','https://example.test/success','https://example.test/cancel')
    assert q['originalSubtotal']==25.01 and q['finalPayable']==21.88
    assert create.call_args.kwargs['line_items'][0]['price_data']['unit_amount']==q['amountMinor']==2188


def test_campaign_relink_revokes_old_embedded_price_and_updates_new_parent(monkeypatch):
    from services import public_content_projection as projection
    from test_fr15_package_checkout_stripe import PaymentMemory
    memory=PaymentMemory()
    for pid in ('p1','p2'):memory.seed('tourism_packages',pid,package(id=pid))
    memory.seed('promotional_campaigns','c1',campaign(packageIds=['p1'],endDate='2099-01-01'))
    monkeypatch.setenv('TRAVELMATE_TESTING','false')
    monkeypatch.setattr(projection,'retrieveRecord',memory.retrieve)
    monkeypatch.setattr(projection,'storeRecord',lambda collection,data,key:memory.seed(collection,key,data))
    monkeypatch.setattr(projection,'deleteRecord',lambda collection,key:memory.collections.setdefault(collection,{}).pop(key,None))
    projection.sync_package('p1')
    assert memory.retrieve('public_tourism_packages','p1')['packagePricing']['offers']
    projection.revoke_projection('promotional_campaigns','c1')
    assert memory.retrieve('public_tourism_packages','p1')['packagePricing']['offers']==[]
    current=memory.update('promotional_campaigns','c1',{'packageIds':['p2'],'packageId':'p2'})
    projection.source_changed('promotional_campaigns','c1',current)
    assert memory.retrieve('public_tourism_packages','p1')['packagePricing']['offers']==[]
    assert memory.retrieve('public_tourism_packages','p2')['packagePricing']['offers']
    assert memory.retrieve('public_promotional_campaigns','c1')['packageIds']==['p2']


@pytest.mark.parametrize('source',[{'packageIds':['p1','other']},{'packageIds':[]},{'packageIds':'p1'}])
def test_campaign_creation_rejects_invalid_or_foreign_multi_associations(client,package_payment,monkeypatch,source):
    memory,_=package_payment;configure_routes(memory,monkeypatch)
    memory.seed('tourism_packages','other',package(id='other',operatorId='other'))
    payload=campaign(startDate='2027-01-01',endDate='2027-02-01',**source)
    for key in ('id','operatorId','reviewStatus','campaignStatus'):payload.pop(key,None)
    with patch('modules.fr12_tourism_operator_management.routes.storeRecord') as store:
        r=client.post('/api/fr12/campaigns',headers={'Authorization':'Bearer op1'},json=payload)
    assert r.status_code in {400,404};store.assert_not_called()


def test_create_submit_approve_multi_package_campaign_route_contract(client,package_payment,monkeypatch):
    memory,_=package_payment;configure_routes(memory,monkeypatch)
    def store(collection,data):
        memory.seed(collection,'new-campaign',data)
        return memory.retrieve(collection,'new-campaign')
    monkeypatch.setattr('modules.fr12_tourism_operator_management.routes.storeRecord',store)
    h={'Authorization':'Bearer op1'}
    r=client.post('/api/fr12/campaigns',headers=h,json={'campaignTitle':'Multi-package offer','packageIds':['p2','p1','p2'],
        'startDate':'2027-01-01','endDate':'2027-02-01','discountType':'percentage','discountValue':15})
    assert r.status_code==201,r.get_json()
    c=r.get_json()['campaign'];assert c['packageIds']==['p2','p1'] and c['packageId']=='p2'
    assert c['reviewStatus']=='draft'
    r=client.post('/api/fr12/campaigns/new-campaign/submit',headers=h)
    assert r.status_code==200,r.get_json()
    assert memory.retrieve('promotional_campaigns','new-campaign')['reviewStatus']=='pending'
    r=client.post('/api/fr13/campaigns/new-campaign/review',headers={'Authorization':'Bearer admin1'},json={'decision':'approved'})
    assert r.status_code==200,r.get_json()
    assert memory.retrieve('promotional_campaigns','new-campaign')['reviewStatus']=='approved'


def test_edit_keeps_exact_legacy_package_promotion_audit_fields(client,package_payment,monkeypatch):
    memory,_=package_payment;configure_routes(memory,monkeypatch)
    legacy={'originalPrice':'199.00','promotionalPrice':'80.00','promotionStart':'2020-01-01','promotionEnd':'2020-12-31'}
    memory.seed('tourism_packages','p1',{**package(title='Penang',destination='Penang',durationDays=1,fullDescription='A detailed public package.',approvalStatus='draft'),**legacy})
    response=client.put('/api/fr12/packages/p1',headers={'Authorization':'Bearer op1'},json={'shortDescription':'Updated normal brochure'})
    assert response.status_code==200,response.get_json()
    stored=memory.retrieve('tourism_packages','p1')
    assert {key:stored[key] for key in legacy}==legacy
    assert public_package(stored,campaigns=[])['packagePricing']['base']['finalPayable']==100
