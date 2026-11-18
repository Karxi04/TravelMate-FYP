"""Report layouts use isolated existing analytics contracts; never live records."""
from copy import deepcopy
from io import BytesIO
from unittest.mock import patch

import pytest

from services import report_service as reports


def operator_data():
    return {
        'generatedAt':'2026-11-18T03:04:05+00:00', 'dataLimited':True,
        'summary':{'totalPackages':5,'approvedPackages':2,'pendingPackages':1,'draftPackages':1,
                   'rejectedPackages':0,'totalCampaigns':3,'activeCampaigns':1,
                   'totalPackageValue':1234.5,'bookingRecords':4,'paidBookings':3,
                   'totalPaidRevenue':456.78,'testPaidTotal':123.45,'testModeOrders':2,
                   'fulfilledBookings':1,'pendingFulfillmentBookings':2},
        'packages':[{'packageTitle':'Heritage & Nature <Tour>','destinationName':'Johor',
                     'adultPrice':250,'currency':'MYR','durationDays':3,'maxTravellers':12,
                     'approvalStatus':'approved'}],
        'campaigns':[{'campaignTitle':'Seasonal <Offer>','promoCode':'SAFE',
                      'discountType':'percentage','discountValue':10,'startDate':'2026-11-01',
                      'endDate':'2026-11-30','reviewStatus':'approved'}],
        'bookings':[{'packageTitle':'Heritage & Nature <Tour>'} for _ in range(3)]+[{'packageTitle':'Beach'}],
    }


def admin_data():
    return {
        'generatedAt':'2026-11-18T03:04:05+00:00','dataLimited':True,'recordsLimited':True,
        'criteria':{'reportType':'payments','startDate':'2026-11-01','endDate':'2026-11-18','filter':'paid'},
        'counts':{'users':10,'tourism_packages':5,'promotional_campaigns':3,'feedback':8,
                  'payment_records':4,'hotel_bookings':2},
        'summary':{
            'users':{'total':10,'travellers':7,'operators':2,'administrators':1,'active':9,'deactivated':1},
            'packages':{'total':5,'approved':2,'pending':1,'rejected':1,'draft':1},
            'campaigns':{'total':3,'approved':2,'pending':1,'active':1},
            'feedback':{'total':8,'visible':5,'pending':2,'removed':1},
            'payments':{'total':4,'paid':3,'totalPaidRevenue':456.78,'testPaidTotal':123.45,'testMode':2},
        },
    }


def export_pages(data, operator):
    target=BytesIO()
    canvases=[]
    original=reports.NumberedCanvas
    def capture(*args,**kwargs):
        obj=original(*args,**kwargs)
        canvases.append(obj)
        return obj
    with patch.object(reports,'NumberedCanvas',side_effect=capture):
        if operator:
            reports.export_operator_report(data,target,{'businessName':'Coastal & Heritage <Agency>'})
        else:
            reports.export_system_report_pdf(data,target,{'name':'Administrator','email':'test@example.invalid'})
    pages=['\n'.join(state['_code']) for state in canvases[0]._saved_page_states]
    assert target.getvalue().startswith(b'%PDF')
    return pages,target.getvalue()


@pytest.mark.parametrize('operator',[True,False])
def test_real_cover_summary_charts_and_details_have_distinct_pages(operator):
    data=operator_data() if operator else admin_data()
    before=deepcopy(data)
    pages,pdf=export_pages(data,operator)
    assert len(pages)>=4
    assert 'TravelMate' in pages[0]
    assert ('Tourism Operator Business' if operator else 'Administrator System') in pages[0]
    assert 'Executive summary' not in pages[0]
    assert 'Executive summary' in pages[1]
    assert '456.78' in pages[1] and '123.45' in pages[1]
    assert 'simulated' in pages[0]
    assert 'Visual analytics' in pages[2]
    assert any('Detailed report' in page for page in pages[3:])
    assert '18 November 2026, 03:04:05 UTC' in pages[0]
    assert all(f'Page {i+1} of {len(pages)}' in page for i,page in enumerate(pages))
    assert data==before


def test_operator_charts_use_summary_and_loaded_booking_titles_exactly():
    charts=reports._report_charts(operator_data(),True)
    assert charts[0][1]==[('Approved',2),('Pending review',1),('Rejected',0),('Draft',1),('Other / unclassified',1)]
    assert charts[1][1]==[('Heritage & Nature <Tour>',3),('Beach',1)]
    assert charts[2][1]==[('Fulfilled / trip ready',1),('Pending arrangements',2),('Other / unclassified',1)]


def test_admin_charts_use_roles_moderation_and_overlapping_campaign_states():
    charts=reports._report_charts(admin_data())
    assert charts[0][1]==[('Travellers',7),('Tourism operators',2),('Administrators',1)]
    assert charts[1][1]==[('Approved',2),('Pending review',1),('Rejected',1),('Draft',1)]
    assert charts[2][1]==[('Approved',2),('Pending review',1),('Rejected',0),('Active',1)]
    assert 'overlap' in charts[2][3]
    assert charts[3][1]==[('Visible',5),('Pending review',2),('Removed',1)]


@pytest.mark.parametrize('operator',[True,False])
def test_empty_reports_generate_without_inventing_a_chart_slice(operator):
    pages,_=export_pages({},operator)
    assert len(pages)>=4
    assert 'No category counts available' in '\n'.join(pages)
    chart=reports._chart_content([('Approved',0)],'donut',reports._get_styles())
    assert isinstance(chart,reports.Paragraph)


def test_long_package_labels_flow_and_all_detail_rows_survive():
    data=operator_data()
    data['packages']=[{**data['packages'][0],'packageTitle':f'Unique package {i:03d} '+('Long package name ' * 15)}
                      for i in range(45)]
    data['bookings']=[{'packageTitle':row['packageTitle']} for row in data['packages']]
    pages,_=export_pages(data,True)
    assert len(pages)>8
    text='\n'.join(pages)
    for i in range(45):
        assert f'Unique package {i:03d}' in text
    assert text.count('Package Title')>1
    assert all(page.count('Package Title') <= 1 for page in pages)


@pytest.mark.parametrize('operator',[True,False])
def test_untrusted_markup_is_literal_text_not_an_external_resource(operator):
    data=operator_data() if operator else admin_data()
    label='<img src="file:///forbidden">'
    if operator:
        data['packages'][0]['packageTitle']=label
        data['bookings'][0]['packageTitle']=label
    else:
        data['criteria']['filter']=label
    pages,_=export_pages(data,operator)
    assert 'file:///forbidden' in '\n'.join(pages)
    assert all('clientSecret' not in page for page in pages)


def test_vector_bars_share_a_scale_and_labels_show_the_exact_values():
    chart=reports._chart_content([('One',1),('Four',4),('Zero',0)],'bar',reports._get_styles())
    rows=chart._cellvalues
    assert [row[2].getPlainText() for row in rows]==['1','4','0']
    assert rows[0][1].contents[1].width==58
    assert rows[1][1].contents[1].width==232
    assert len(rows[2][1].contents)==1


@pytest.mark.parametrize('operator,expected', [
    (True,[5,2,3,'RM 1,234.50']),
    (False,[10,5,3,8]),
])
def test_executive_kpis_keep_exact_existing_values(operator,expected):
    data=operator_data() if operator else admin_data()
    with patch.object(reports,'_build_kpi_card',wraps=reports._build_kpi_card) as cards:
        export_pages(data,operator)
    assert [call.args[0] for call in cards.call_args_list]==expected
    if operator:
        assert cards.call_args_list[2].args[1]=='Total Campaigns'
