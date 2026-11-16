"""Batch B uses existing mocked chat storage; every non-chat write/provider is forbidden."""
from copy import deepcopy

import pytest

from test_chatbot_saved_preview import conversation, select
from modules.fr11_chatbot_travel_assistant.personal_budget import explain_budget


@pytest.fixture
def personal(conversation, monkeypatch):
    records, writes, providers, talk = conversation
    for trip in records['itineraries'].values():
        trip.update(travelMode='public_transport', accommodationChoice='none', carRentalChoice='not_required')
        for a in trip['activities']:
            a.update(pricingUnit='per_person', unitPrice=10, costProvenance='catalog_estimate')
    monkeypatch.setattr('modules.fr11_chatbot_travel_assistant.routes.interpretChatbotIntent', lambda *_: pytest.fail('Personal tools must not call Gemini'))
    return conversation


def test_budget_selection_followups_reopen_and_no_nonchat_write(personal, client):
    records, writes, providers, talk = personal
    before = deepcopy(records['itineraries'])
    first = talk('Explain my trip budget')
    sid = first['session']['id']
    assert 'Which saved trip' in first['reply']
    response = talk('5', sid)
    budget = response['item']['budgetReasoning']
    assert budget['tripId'] == 'trip5' and budget['travellerCount'] == 2
    assert budget['modelledSubtotal'] == 585  # food360 + transport105 + per-person activities120
    assert 'per-person quote' in response['reply']
    assert 'estimated_daily_allowance' in response['reply']
    assert len(talk('What about Day 2?', sid)['item']['budgetReasoning']['daily']) == 3
    reopened = client.get('/api/fr11/sessions/' + sid, headers={'Authorization': 'Bearer fixture'})
    assert reopened.status_code == 200
    assert talk('and per person?', sid)['item']['budgetReasoning']['tripId'] == 'trip5'
    assert records['itineraries'] == before and set(writes) <= {'chat_messages', 'chat_sessions'} and not providers


def test_group_what_if_is_read_only_and_does_not_replace_adjustment_draft(personal):
    records, writes, providers, talk = personal
    sid = select(personal)
    original = deepcopy(records['itineraries']['trip5'])
    result = talk('What if my trip budget were RM300 per person for 3 travellers?', sid)
    scenario = result['item']['budgetReasoning']
    assert scenario['scenario'] and scenario['budgetLimit'] == 900 and scenario['travellerCount'] == 3
    assert 'nothing was saved' in result['reply']
    assert 'activePlan' not in records['chat_sessions'][sid]['planningState']
    talk('Set the budget to RM700', sid)
    draft = deepcopy(records['chat_sessions'][sid]['planningState']['activePlan'])
    talk('How much is my food budget?', sid)
    assert records['chat_sessions'][sid]['planningState']['activePlan'] == draft
    assert records['itineraries']['trip5'] == original and 'itineraries' not in writes and not providers


def test_unknown_prices_are_not_free_and_day_allocation_reconciles(personal):
    records, _, _, talk = personal
    trip = records['itineraries']['trip5']
    trip.update(foodCost=10.01, transportCost=5, accommodationChoice='undecided')
    trip['activities'][0].pop('pricingUnit')
    result = explain_budget(trip)
    assert result['incomplete']
    assert next(r for r in result['categories'] if r['category'] == 'hotel')['amount'] is None
    assert result['daily'][0]['unknownActivities'] == 1
    assert round(sum(r['modelledSubtotal'] for r in result['daily']) + result['sharedTravelAndStay'] + result['unassignedActivitySubtotal'], 2) == result['modelledSubtotal']
    sid = select(personal)
    assert 'not a guaranteed cheapest-day ranking' in talk('Which day is most expensive in my budget?', sid)['reply']


def test_ledger_and_paid_amounts_are_separate_not_double_counted(personal):
    records, writes, _, talk = personal
    records['itineraries']['trip5']['manualExpenses'] = [
        {'id':'expense', 'name':'Lunch', 'category':'Food', 'currency':'MYR', 'type':'actual', 'amountMinor':2500}]
    records['checkout_orders'] = {'order':{'id':'order','travellerId':'test_traveller_uid', 'itineraryId':'trip5',
        'fulfilledTripId':'trip5', 'quoteType':'package','status':'paid','paymentStatus':'paid','amountMinor':10000,'amount':100,'currency':'MYR'}}
    records['itineraries']['trip5']['purchasedPackages'] = [{'checkoutOrderId':'order'}]
    sid = select(personal)
    result = talk('Explain my budget breakdown', sid)['item']['budgetReasoning']
    assert result['modelledSubtotal'] == 585
    assert result['recordedExpenses']['actualMinor'] == 2500
    assert result['recordedExpenses']['verifiedMinor'] == 10000
    assert set(writes) <= {'chat_messages','chat_sessions'}


@pytest.mark.parametrize('field,value', [('travellerCount',None),('travellerCount',0),('travellerCount',True),('travellerCount',1.001)])
def test_unknown_or_invalid_group_does_not_default_to_one(personal, field, value):
    records, _, _, talk = personal
    records['itineraries']['trip5'][field] = value
    sid = select(personal)
    result = talk('Explain my trip budget', sid)
    assert result['item']['budgetReasoning']['available'] is False
    assert 'assumed one traveller' in result['reply']


def test_changed_party_does_not_invent_commercial_requote(personal):
    records, _, _, talk = personal
    trip = records['itineraries']['trip5']
    trip.update(travelMode='flight', flightCost=500, flightCurrency='MYR', flightPriceBasis='party',
                selectedFlight={'airline':'Recorded airline','price':500,'currency':'MYR','priceBasis':'party','travellerCount':2})
    sid = select(personal)
    result = talk('What if my trip had 3 travellers?', sid)['item']['budgetReasoning']
    assert result['incomplete']
    assert next(r for r in result['categories'] if r['category']=='flight')['classification']=='unavailable'
    assert trip['flightCost']==500


def test_foreign_selection_and_foreign_rows_never_leak(personal):
    records, _, _, talk = personal
    records['itineraries']['foreign']={'id':'foreign','travellerId':'other','title':'SECRET FOREIGN TRIP'}
    first=talk('Explain my budget');sid=first['session']['id']
    assert 'SECRET' not in str(first)
    records['chat_sessions'][sid]['planningState']['personalContext']['choices']=['foreign']
    assert 'SECRET' not in str(talk('1',sid))
    records['checkout_orders']={'foreign':{'id':'foreign','travellerId':'other','paymentStatus':'paid','privateSentinel':'SECRET'}}
    assert 'SECRET' not in str(talk('Have I paid for my hotel?',sid))


def test_selection_facts_and_safe_navigation_without_quote_calls(personal):
    records, _, _, talk=personal
    records['itineraries']['trip5']['selectedHotel']={'name':'Recorded hotel','price':123,'currency':'USD',
        'checkin':'2027-02-10','checkout':'2027-02-12','privateSentinel':'SECRET','checkoutUrl':'SECRET'}
    sid=select(personal)
    result=talk('Which hotel is selected for my trip?',sid)
    assert 'Recorded hotel' in result['reply'] and 'USD' in result['reply']
    assert 'not proof of payment' in result['reply'] and 'SECRET' not in str(result)
    assert result['item']['assistantActions'][0]=={'kind':'trip','tripId':'trip5'}


def test_cross_product_order_selection_and_legacy_dedup(personal):
    records, writes, providers, talk=personal
    records['checkout_orders']={f'order{i}':{'id':f'order{i}','travellerId':'test_traveller_uid','quoteType':kind,
        'status':status,'paymentStatus':status,'amount':100,'currency':'MYR','provider':'stripe_checkout',
        'quoteSnapshot':{'name':'Named '+kind},'privateSentinel':'SECRET','checkoutUrl':'SECRET'}
        for i,(kind,status) in enumerate([('hotel','paid'),('flight','pending'),('package','cancelled')])}
    records['payment_records']={'projection':{'id':'projection','travellerId':'test_traveller_uid','checkoutOrderId':'order0','paymentStatus':'succeeded'}}
    first=talk('Show my payment orders');sid=first['session']['id']
    assert len(first['item']['personalOrders'])==3 and 'SECRET' not in str(first)
    result=talk('2',sid)
    assert len(result['item']['personalOrders'])==1
    assert result['item']['personalOrders'][0]['bookingType']=='flight'
    assert 'pending' in result['reply'] and 'not live provider verification' in result['reply']
    assert set(writes)<={'chat_messages','chat_sessions'} and not providers


def test_preferences_recommendations_saved_items_and_no_regeneration(personal):
    records,writes,providers,talk=personal
    uid='test_traveller_uid'
    records['travel_preferences']={uid:{'travellerId':uid,'interests':['Photography','Food'],'travelPersonality':'Explorer','privateSentinel':'SECRET'}}
    records['recommendation_snapshots']={'gen':{'id':'gen','travellerId':uid,'generatedAt':'2027-01-01',
        'recommendationResults':[{'destinationId':'d','title':'Recorded museum','recommendationReason':'Matches recorded Photography','privateSentinel':'SECRET'}]}}
    records['favourites']={'fav':{'id':'fav','travellerId':uid,'destinationId':'d','title':'Saved museum','privateSentinel':'SECRET'}}
    pref=talk('What are my preferences?');sid=pref['session']['id']
    assert 'Photography' in pref['reply'] and 'SECRET' not in str(pref)
    rec=talk('Why these recommendations for my travel style?',sid)
    assert 'Recorded museum' in rec['reply'] and '60%' in rec['reply'] and rec['item']['recommendationStale']
    assert 'SECRET' not in str(rec)
    assert 'Saved museum' in talk('Show my saved places',sid)['reply']
    assert set(writes)<={'chat_messages','chat_sessions'} and not providers


def test_cheap_advice_is_not_an_applied_saving_or_live_search(personal):
    _,writes,providers,talk=personal
    sid=select(personal)
    result=talk('How can I make my trip cheaper?',sid)
    assert 'no saving is guaranteed' in result['reply'] and 'Lower-Cost Alternatives' in result['reply']
    assert 'tripPlan' not in result['item'] and set(writes)<={'chat_messages','chat_sessions'} and not providers


def test_package_price_context_remains_separate(personal):
    records,_,_,talk=personal
    sid=select(personal)
    state=records['chat_sessions'][sid]['planningState']
    state.update(assistantMode='packages',packageSearch={'destination':'Penang','budgetMax':500,'budgetBasis':'per_person'})
    from modules.fr11_chatbot_travel_assistant.personal_questions import respond
    assert respond('500 per person one',state,lambda *a,**k:pytest.fail('Must remain in package tool'),'test_traveller_uid') is None


def test_scenario_short_corrections_preserve_group_basis_without_saving(personal):
    records,writes,_,talk=personal
    sid=select(personal)
    talk('What if my budget were RM300 per person for 3 travellers?',sid)
    changed=talk('Actually RM200 total',sid)['item']['budgetReasoning']
    assert changed['budgetLimit']==200 and changed['travellerCount']==3
    changed=talk('What if 4 people?',sid)['item']['budgetReasoning']
    assert changed['budgetLimit']==200 and changed['travellerCount']==4
    assert records['itineraries']['trip5']['budgetLimit']==500
    assert set(writes)<={'chat_messages','chat_sessions'}


def test_saved_package_budget_uses_purchase_snapshot_not_duplicate_inclusions(personal):
    records,_,_,talk=personal
    records['itineraries']={'p':{'id':'p','travellerId':'test_traveller_uid','title':'Purchased tour',
        'packageTrip':True,'checkoutOrderId':'order','foodCost':9999,'hotelCost':9999}}
    records['checkout_orders']={'order':{'id':'order','travellerId':'test_traveller_uid','quoteType':'package',
        'amountMinor':91600,'currency':'MYR','status':'paid','paymentStatus':'paid'}}
    result=talk('Explain my trip budget')
    assert '916.0' in result['reply'] and '9999' not in result['reply']
    assert 'not added again' in result['reply']


def test_data_failure_is_retryable_not_empty_or_provider_fallback(personal, monkeypatch, client):
    _,_,providers,_=personal
    from modules.fr11_chatbot_travel_assistant import routes
    read=routes.retrieveRecord
    def failing(collection,*args,**kwargs):
        if collection=='itineraries':raise RuntimeError('PRIVATE DATABASE ERROR')
        return read(collection,*args,**kwargs)
    monkeypatch.setattr(routes,'retrieveRecord',failing)
    response=client.post('/api/fr11/chat',headers={'Authorization':'Bearer fixture'},json={'message':'Explain my trip budget'})
    assert response.status_code==503 and 'PRIVATE' not in str(response.json) and not providers


def test_later_deleted_trip_and_foreign_session_are_rechecked(personal, client):
    records,_,_,talk=personal
    first=talk('Explain my budget');sid=first['session']['id']
    talk('5',sid)
    del records['itineraries']['trip5']
    assert 'no longer available' in talk('What about Day 2?',sid)['reply']
    records['chat_sessions'][sid]['travellerId']='other'
    response=client.post('/api/fr11/chat',headers={'Authorization':'Bearer fixture'},json={'message':'Explain my budget','sessionId':sid})
    assert response.status_code==404


def test_missing_profiles_snapshots_and_favourites_are_truthful(personal):
    _,writes,providers,talk=personal
    assert 'No saved preferences' in talk('What are my preferences?')['reply']
    assert 'No saved recommendations' in talk('Show my recommendations')['reply']
    assert 'No saved places' in talk('Show my saved places')['reply']
    assert set(writes)<={'chat_messages','chat_sessions'} and not providers


def test_short_payment_followup_uses_current_trip_only(personal):
    records,_,_,talk=personal
    records['checkout_orders']={'own':{'id':'own','travellerId':'test_traveller_uid','itineraryId':'different-trip',
        'quoteType':'hotel','status':'paid','paymentStatus':'paid','amount':100,'currency':'MYR'}}
    sid=select(personal)
    talk('Which hotel is selected for my trip?',sid)
    assert 'No matching owned' in talk('Is it paid?',sid)['reply']


def test_invalid_daily_scope_and_ambiguous_food_scenario_are_read_only(personal):
    _,writes,_,talk=personal
    sid=select(personal)
    assert 'outside' in talk('Explain my budget on Day 9',sid)['reply']
    assert 'daily food allowance' in talk('What if my food budget is RM20 per day?',sid)['reply']
    assert set(writes)<={'chat_messages','chat_sessions'}


def test_cheaper_previews_reuse_fr5_validation_without_applying(personal):
    from test_fr05_alternative_integrity import _planned_trip
    records,writes,providers,talk=personal
    trip=_planned_trip()
    trip.pop('checkoutOrderId',None)
    records['itineraries']={trip['id']:trip}
    before=deepcopy(trip)
    result=talk('How can I make my trip cheaper?')['item']['budgetReasoning']
    assert any(a['replacement']=='Penang Botanic Gardens' and a['estimatedSavings']==80 for a in result['pricedAlternatives'])
    assert records['itineraries'][trip['id']]==before
    assert set(writes)<={'chat_messages','chat_sessions'} and not providers


def test_explicit_named_trip_overrides_previous_personal_selection(personal):
    _,_,_,talk=personal
    result=talk('Explain my trip budget');sid=result['session']['id']
    talk('5',sid)
    result=talk('Explain my budget for 3-Day Penang Itinerary Plan 4',sid)
    assert result['item']['budgetReasoning']['tripId']=='trip4'


def test_new_editor_selection_replaces_stale_budget_context(personal):
    records,_,_,talk=personal
    first=talk('Explain my trip budget');sid=first['session']['id']
    talk('5',sid)
    talk('Adjust my itinerary',sid)
    talk('Adjust trip 4',sid)
    assert talk('Explain my trip budget',sid)['item']['budgetReasoning']['tripId']=='trip4'
    assert records['itineraries']['trip5']['budgetLimit']==500


def test_notifications_are_navigation_not_a_reconciling_get(personal,monkeypatch):
    records,writes,providers,talk=personal
    from modules.fr11_chatbot_travel_assistant import routes
    original=routes.retrieveRecord
    def guarded(collection,*args,**kwargs):
        assert not collection.startswith('notification') and collection!='traveller_notifications'
        return original(collection,*args,**kwargs)
    monkeypatch.setattr(routes,'retrieveRecord',guarded)
    result=talk('Show my notifications')
    assert 'have not called' in result['reply']
    assert set(writes)<={'chat_messages','chat_sessions'} and not providers


def test_flight_legs_are_saved_facts_without_private_provider_fields(personal):
    records,_,providers,talk=personal
    records['itineraries']['trip5']['selectedFlight']={'airline':'Recorded airline','outboundSegments':[
        {'departureAirport':'KUL','arrivalAirport':'PEN','departureDate':'2027-02-10','departureTime':'09:00',
         'flightNumber':'AB123','providerToken':'SECRET'}]}
    sid=select(personal)
    result=talk('Show my selected flight',sid)
    assert 'KUL' in result['reply'] and '09:00' in result['reply'] and 'AB123' in result['reply']
    assert 'SECRET' not in str(result) and not providers


def test_recommendation_followup_reuses_exact_owned_generation(personal):
    records,_,_,talk=personal
    uid='test_traveller_uid'
    records['recommendation_snapshots']={'g':{'id':'g','travellerId':uid,'generatedAt':'2027-01-01',
        'recommendationResults':[{'title':'One','destinationId':'one','recommendationReason':'Reason one'},
                                 {'title':'Two','destinationId':'two','recommendationReason':'Reason two'}]}}
    result=talk('Show my recommendations');sid=result['session']['id']
    records['recommendation_snapshots']['new']={'id':'new','travellerId':uid,'generatedAt':'2028-01-01','recommendationResults':[{'title':'NEW RESULT'}]}
    follow=talk('Why the second one?',sid)
    assert 'Reason two' in follow['reply'] and 'Reason one' not in follow['reply'] and 'NEW RESULT' not in str(follow)


def test_day_comparison_reports_highest_modelled_not_actual_or_complete_cost(personal):
    records,_,_,talk=personal
    records['itineraries']['trip5']['activities'][2]['unitPrice']=50
    sid=select(personal)
    result=talk('Which day is most expensive in my trip budget?',sid)
    assert result['item']['budgetReasoning']['highestModelledDays']==[2]
    assert 'not recorded daily actual spending' in result['reply']
