"""Tap-equivalent GET/form contracts for sorting, departure management and lifecycle controls."""
from copy import deepcopy
from html import unescape
import re
from unittest.mock import MagicMock, patch

import pytest

from test_operator_bookings import auth_client, app  # noqa: F401


def booking(reference, **changes):
    return {'id':reference,'orderReference':reference,'packageId':'p1','packageTitle':'Heritage package',
            'departureDate':'2027-01-10','groupSize':3,'adults':2,'children':1,'amount':300,'groupTotal':300,
            'currency':'MYR','paymentStatus':'paid','orderStatus':'paid','isPaid':True,'testMode':True,
            'fulfillmentStatus':'awaiting_operator_fulfillment','supplierReservationStatus':'not_created',
            'createdAt':'2026-11-08T10:00:00Z',**changes}


@pytest.fixture
def portal_data():
    data = {'bookings':[], 'packages':[], 'calls':[], 'detail':None, 'limited':False}
    def api(method,path,**kwargs):
        data['calls'].append((method,path,deepcopy(kwargs)))
        body = {'ok':True}
        if method == 'GET' and path == '/api/fr12/bookings':body.update(items=deepcopy(data['bookings']),dataLimited=data['limited'])
        elif method == 'GET' and path == '/api/fr12/packages':body['items'] = deepcopy(data['packages'])
        elif method == 'GET' and path.startswith('/api/fr12/bookings/'):
            body['booking'] = deepcopy(data['detail'] or next((item for item in data['bookings'] if item['orderReference'] == path.split('/')[-1]),None))
        elif method == 'PUT':body['package'] = {'approvalStatus':'archived'}
        response = MagicMock(ok=True,status_code=200)
        response.json.return_value = body
        return response
    with patch.dict(app.view_functions['operator_fr12.bookings'].__globals__,{'call_api':api}):
        yield data


def ids(html,catalog=False):
    return re.findall(r'data-'+('package-id' if catalog else 'order-reference')+r'="([^"]+)"',html)


SORTED = [
    booking('C',packageTitle='Beta',departureDate='2027-01-02',groupSize=10,amount=100,paymentStatus='paid',fulfillmentStatus='partially_fulfilled',supplierReservationStatus='operator_attested',createdAt='2026-11-08T10:00:00Z'),
    booking('A',packageTitle='Alpha',departureDate='2027-01-01',groupSize=2,amount=9.5,paymentStatus='failed',orderStatus='failed',isPaid=False,fulfillmentStatus='fulfillment_declined',supplierReservationStatus='declined',createdAt='2026-11-07T10:00:00Z'),
    booking('B',packageTitle='Gamma',departureDate='2027-01-03',groupSize=20,amount=1000,paymentStatus='pending',orderStatus='checkout_open',isPaid=False,fulfillmentStatus='trip_ready',supplierReservationStatus='not_created',createdAt='2026-11-09T10:00:00Z'),
]
EXPECTED = {'reference':['A','B','C'],'package':['A','C','B'],'departure':['A','C','B'],
            'party':['A','C','B'],'amount':['A','C','B'],'payment':['A','C','B'],
            'fulfillment':['A','C','B'],'supplier':['A','B','C'],'created':['A','C','B']}


@pytest.mark.parametrize('column',list(EXPECTED))
@pytest.mark.parametrize('direction',['asc','desc'])
def test_every_booking_header_sorts_raw_values_and_reverses(auth_client,portal_data,column,direction):
    portal_data['bookings'] = deepcopy(SORTED)
    page = auth_client.get('/bookings',query_string={'sort':column,'direction':direction})
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    expected = EXPECTED[column] if direction == 'asc' else list(reversed(EXPECTED[column]))
    assert ids(html) == expected and len(set(ids(html))) == 3
    assert f'aria-sort="{"ascending" if direction == "asc" else "descending"}"' in html
    assert 'MYR' in html


def test_sort_header_links_toggle_preserve_filters_and_details_open_correct_order(auth_client,portal_data):
    portal_data['bookings'] = [booking('ref-a',amount=9.5),booking('ref-b',amount=100)]
    page = auth_client.get('/bookings?package=p1&departure=2027-01-10&status=paid&q=heritage&sort=amount&direction=asc')
    html = page.get_data(as_text=True)
    link = unescape(re.search(r'<a href="([^"]+)" aria-label="Sort by Amount"',html).group(1))
    assert 'direction=desc' in link and 'package=p1' in link and 'departure=2027-01-10' in link and 'status=paid' in link and 'q=heritage' in link
    reversed_page = auth_client.get(link)
    assert ids(reversed_page.get_data(as_text=True)) == ['ref-b','ref-a']
    details = re.findall(r'href="(/bookings/ref-[ab])"',reversed_page.get_data(as_text=True))
    assert details == ['/bookings/ref-b','/bookings/ref-a']
    assert auth_client.get(details[0]).status_code == 200
    assert portal_data['calls'][-1][1] == '/api/fr12/bookings/ref-b'


@pytest.mark.parametrize('direction',['asc','desc'])
def test_missing_numeric_and_dates_are_last_and_ties_use_identity(auth_client,portal_data,direction):
    portal_data['bookings'] = [booking('z',amount=10),booking('a',amount=10),booking('missing',amount=None,groupTotal=None,departureDate=None)]
    for column in ('amount','departure'):
        page = auth_client.get('/bookings',query_string={'sort':column,'direction':direction})
        assert ids(page.get_data(as_text=True)) == ['a','z','missing']


def departures(data):
    data['packages'] = [{'id':'p1','title':'Archived Heritage','approvalStatus':'archived'}, {'id':'p2','title':'Island tour'}]
    data['bookings'] = [booking('paid'),booking('pending',paymentStatus='unpaid',orderStatus='checkout_open',isPaid=False,groupSize=10,adults=8,children=2),
                        booking('later',departureDate='2027-02-10',fulfillmentStatus='trip_ready'),
                        booking('other',packageId='p2',packageTitle='Island tour',groupSize=8,adults=8,children=0)]


def test_package_departure_summary_counts_only_matching_paid_parties(auth_client,portal_data):
    departures(portal_data)
    original = deepcopy(portal_data['bookings'])
    page = auth_client.get('/bookings?package=p1&departure=2027-01-10&sort=reference&direction=asc')
    html = page.get_data(as_text=True)
    assert ids(html) == ['paid','pending']
    for key,value in {'bookings':2,'paid':1,'pending':1,'travellers':3,'adults':2,'children':1,'arrangements_pending':1,'ready':0}.items():
        assert f'data-summary="{key}">{value}</strong>' in html
    assert 'Archived Heritage' in html and 'paid orders only' in html
    assert portal_data['bookings'] == original


@pytest.mark.parametrize(('query','expected'),[
    ('package=p1&departure=2027-01-10&q=paid&status=paid',['paid']),
    ('package=p1&departure=2027-01-10&status=pending',['pending']),
    ('package=p1&from=2027-02-01&to=2027-02-28',['later']),
    ('package=p2',['other']),('package=not-owned',[]),('package=p1&departure=2020-01-01',[]),
])
def test_filters_compose_without_cross_package_or_date_leak(auth_client,portal_data,query,expected):
    departures(portal_data)
    page = auth_client.get('/bookings?'+query)
    html = page.get_data(as_text=True)
    assert ids(html) == expected
    assert 'Clear Filters' in html
    if not expected:assert 'No package bookings found' in html


def test_changing_package_resets_only_incompatible_departure_and_clear_restores_all(auth_client,portal_data):
    departures(portal_data)
    page = auth_client.get('/bookings?package=p2&previous_package=p1&departure=2027-02-10')
    assert ids(page.get_data(as_text=True)) == ['other']
    assert 'No bookings on 2027-02-10' not in page.get_data(as_text=True)
    assert len(ids(auth_client.get('/bookings').get_data(as_text=True))) == 4


@pytest.mark.parametrize('query',['from=invalid','from=2027-02-01&to=2027-01-01'])
def test_invalid_date_range_is_explicit_and_does_not_broaden_results(auth_client,portal_data,query):
    departures(portal_data)
    page = auth_client.get('/bookings?'+query)
    assert 'role="alert"' in page.get_data(as_text=True) and ids(page.get_data(as_text=True)) == []


def test_missing_departure_and_incomplete_party_are_not_invented(auth_client,portal_data):
    portal_data['bookings'] = [booking('legacy',departureDate=None,adults=None,children=None,groupSize=None)]
    page = auth_client.get('/bookings?departure=missing')
    html = page.get_data(as_text=True)
    assert ids(html) == ['legacy']
    assert 'incomplete party details' in html and 'data-summary="travellers">0</strong>' in html


def test_historical_departure_filter_ignores_new_catalog_departure_dates(auth_client,portal_data):
    portal_data['packages'] = [{'id':'p1','title':'Edited package','departureDates':['2030-01-01'],'approvalStatus':'archived'}]
    portal_data['bookings'] = [booking('historical',departureDate='2020-02-01')]
    html = auth_client.get('/bookings?package=p1&departure=2020-02-01').get_data(as_text=True)
    assert ids(html) == ['historical'] and '<option value="2020-02-01" selected>' in html
    assert '<option value="2030-01-01"' not in html


CATALOG = [{'id':'c','title':'Beta','destination':'Kedah','durationDays':3,'adultPrice':100,'approvalStatus':'draft','updatedAt':'2026-11-08T10:00:00Z'},
           {'id':'a','title':'Alpha','destination':'Johor','durationDays':1,'adultPrice':9.5,'approvalStatus':'archived','updatedAt':'2026-11-07T10:00:00Z'},
           {'id':'b','title':'Gamma','destination':'Penang','durationDays':10,'adultPrice':1000,'approvalStatus':'rejected','updatedAt':'2026-11-09T10:00:00Z'}]
CATALOG_EXPECTED = {'title':['a','c','b'],'destination':['a','c','b'],'duration':['a','c','b'],'price':['a','c','b'],'status':['a','c','b'],'updated':['a','c','b']}


@pytest.mark.parametrize('column',list(CATALOG_EXPECTED))
@pytest.mark.parametrize('direction',['asc','desc'])
def test_catalog_headers_sort_correctly(auth_client,portal_data,column,direction):
    portal_data['packages'] = deepcopy(CATALOG)
    page = auth_client.get('/packages',query_string={'sort':column,'direction':direction})
    assert page.status_code == 200
    expected = CATALOG_EXPECTED[column] if direction == 'asc' else list(reversed(CATALOG_EXPECTED[column]))
    assert ids(page.get_data(as_text=True),True) == expected


def test_archived_actions_search_sort_and_restore_form_mapping(auth_client,portal_data):
    portal_data['packages'] = deepcopy(CATALOG)
    page = auth_client.get('/packages?status=archived&q=Johor&sort=price&direction=asc')
    html = page.get_data(as_text=True)
    assert ids(html,True) == ['a']
    assert '/packages/a/edit-page?view=1' in html and '/packages/a/edit-page' in html
    assert '/packages/a/restore' in html and '/packages/a/delete' in html and "confirm('Delete" in html
    result = auth_client.post('/packages/a/restore',data={'expectedUpdatedAt':CATALOG[1]['updatedAt']})
    assert result.status_code == 302 and 'status=draft' in result.location
    assert portal_data['calls'][-1] == ('POST','/api/fr12/packages/a/restore',{'json':{'expectedUpdatedAt':CATALOG[1]['updatedAt']}})


def test_archived_view_reuses_complete_editor_and_rejects_post(auth_client,portal_data):
    portal_data['packages'] = [{**CATALOG[1],'fullDescription':'Complete preserved description','priceBasis':'per_person','currency':'MYR'}]
    page = auth_client.get('/packages/a/edit-page?view=1')
    html = page.get_data(as_text=True)
    assert page.status_code == 200 and 'View Tourism Package' in html
    assert '<fieldset disabled aria-label="Read-only package details">' in html
    assert 'Complete preserved description' in html and 'Restore it as Draft' in html
    assert auth_client.post('/packages/a/edit-page?view=1',data={'title':'Forged'}).status_code == 405
    assert not any(method == 'PUT' for method,_,_ in portal_data['calls'])


def test_transport_form_separates_brochure_from_actual_saved_provider(auth_client,portal_data):
    brochure = 'Long brochure paragraph promising a private airport transfer and island transport'
    portal_data['detail'] = booking('transport',requiredServices={'transport':{'required':True,'brochureTypes':[brochure]}},
        fulfillmentRecord={'services':{'transport':{'status':'unconfirmed','providerName':brochure}}},packageBrochure={},
        readiness={'canMarkReady':False,'blockers':['Transportation booking reference is missing.','Actual transport provider / fleet is missing.'],
                   'components':[],'requiredCount':1,'completedCount':0,'requirementsReliable':True})
    page = auth_client.get('/bookings/transport')
    html = page.get_data(as_text=True)
    assert page.status_code == 200 and brochure in html
    assert 'Read-only Brochure Specification' in html and 'name="providerName" value=""' in html
    assert f'value="{brochure}"' not in html
    assert 'Transportation booking reference is missing.' in html
    assert 'Actual transport provider / fleet is missing.' in html
    assert 'FYP demonstration environment' not in html
    assert '<a href="/bookings" class="active">' in html
    assert 'fulfillment-grid' in html and 'minmax(min(100%,340px),1fr)' in html
    assert 'aria-label="Copy Reference"' in html and 'order-status-grid' in html
    portal_data['detail']['fulfillmentRecord']['services']['transport'].update(
        status='confirmed',provenance='operator_attested',providerName='Saved actual fleet',reference='SAVED-42',notes='Saved pickup notes')
    saved_html = auth_client.get('/bookings/transport').get_data(as_text=True)
    assert 'name="providerName" value="Saved actual fleet"' in saved_html
    assert 'value="SAVED-42"' in saved_html and 'value="Saved pickup notes"' in saved_html
    result = auth_client.post('/bookings/transport/fulfillment',data={'serviceType':'transport','providerName':'Actual fleet','reference':'DISPATCH-42','notes':'Gate A'})
    assert result.status_code == 302
    assert portal_data['calls'][-1] == ('POST','/api/fr12/bookings/transport/fulfillment',{'json':{'serviceType':'transport','reference':'DISPATCH-42','providerName':'Actual fleet','notes':'Gate A'}})


def test_payment_disclosure_footer_remains_on_payment_page(auth_client,portal_data):
    assert 'FYP demonstration environment' in auth_client.get('/payments').get_data(as_text=True)


def test_delete_callback_targets_the_selected_package(auth_client,portal_data):
    page = auth_client.post('/packages/selected-package/delete')
    assert page.status_code == 302
    assert portal_data['calls'][-1][:2] == ('DELETE','/api/fr12/packages/selected-package')


@pytest.mark.parametrize('action',['restore','delete'])
def test_lifecycle_forms_require_csrf_before_api_call(auth_client,portal_data,action):
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        response = auth_client.post('/packages/p1/'+action)
    finally:
        app.config['WTF_CSRF_ENABLED'] = False
    assert response.status_code == 400 and portal_data['calls'] == []


def test_data_limit_is_honest_and_sorting_does_not_add_database_queries(auth_client,portal_data):
    portal_data['bookings'] = deepcopy(SORTED)
    portal_data['limited'] = True
    page = auth_client.get('/bookings?sort=amount&direction=desc')
    assert 'Sorting, filters and totals cover the loaded records only' in page.get_data(as_text=True)
    assert [(method,path) for method,path,_ in portal_data['calls']] == [('GET','/api/fr12/bookings'),('GET','/api/fr12/packages')]
