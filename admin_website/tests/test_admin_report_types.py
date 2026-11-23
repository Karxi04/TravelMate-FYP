"""Actual Administrator rendering/proxy routes with synthetic API responses only."""
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import MagicMock
from html import unescape
from urllib.parse import urlparse, parse_qs
import re

import pytest

from test_admin_commerce_presentation import auth_client, _patch_view_api


RECORDS = {
    'system_summary': {},
    'users': {'id': 'account-fixture', 'name': 'Synthetic Operator', 'role': 'operator', 'status': 'active',
              'verificationStatus': 'verified', 'createdAt': '2026-11-10T10:00:00Z'},
    'packages': {'id': 'package-fixture', 'title': 'Synthetic Heritage Tour', 'destination': 'Melaka',
                 'operatorId': 'operator-fixture', 'adultPrice': 50, 'currency': 'MYR', 'approvalStatus': 'approved'},
    'campaigns': {'id': 'campaign-fixture', 'campaignTitle': 'Synthetic Campaign', 'packageId': 'package-fixture',
                  'discountType': 'percentage', 'discountValue': 10, 'reviewStatus': 'approved'},
    'feedback': {'id': 'review-fixture', 'destinationName': 'Synthetic Destination', 'rating': 4,
                 'comment': 'A pleasant visit.', 'feedbackStatus': 'hidden', 'moderationStatus': 'reviewed',
                 'feedbackSource': 'FYP Evaluation — Regional', 'reviewProvenance': 'Synthetic FYP evaluation feedback'},
    'bookings': {'id': 'booking-fixture', 'hotelName': 'Synthetic Hotel', 'hotelCost': 75, 'hotelCurrency': 'MYR',
                 'travellerCount': 2, 'bookingStatus': 'selected', 'paymentStatus': 'unpaid'},
    'payments': {'id': 'payment-fixture', 'productType': 'package', 'productTitle': 'Synthetic Paid Tour',
                 'amount': None, 'currency': 'MYR', 'paymentStatus': 'paid', 'testMode': True},
}


def api_response(report, status=200):
    response = MagicMock(ok=status == 200, status_code=status)
    response.json.return_value = {'ok': status == 200, 'report': report, 'error': 'Invalid report criteria'}
    return response


@pytest.mark.parametrize('kind', RECORDS)
def test_every_report_type_renders_actual_record_schema(auth_client, kind):
    record = deepcopy(RECORDS[kind])
    data = {'criteria': {'reportType': kind}, 'records': [record] if record else [],
            'counts': {'filtered_records': 1}, 'summary': {}}
    with _patch_view_api('admin_fr13.reports', MagicMock(return_value=api_response(data))):
        response = auth_client.get('/admin/reports', query_string={'reportType': kind})
    assert response.status_code == 200
    if record:
        assert record['id'] in response.text
        table = response.text.split('<table class="records-table">')[1].split('</table>')[0]
        for field in {'users': ['role', 'verificationStatus'], 'packages': ['title', 'destination', 'operatorId'],
                      'campaigns': ['campaignTitle', 'packageId', 'discountType'],
                      'feedback': ['comment', 'feedbackSource', 'reviewProvenance', 'feedbackStatus'],
                      'bookings': ['hotelName', 'bookingStatus', 'paymentStatus'],
                      'payments': ['productTitle', 'paymentStatus']}[kind]:
            assert record[field] in table
        if kind == 'payments':
            assert '>Yes<' in table and '>0.00<' not in table


@pytest.mark.parametrize('date', [None, 12345, {'invalid': 'date'}, datetime(2026, 11, 10, tzinfo=timezone.utc)])
def test_historical_dates_do_not_crash_rendering(auth_client, date):
    data = {'records': [{'id': 'historical-fixture', 'createdAt': date, 'amount': None, 'groupTotal': None}],
            'counts': {}, 'summary': {}}
    with _patch_view_api('admin_fr13.reports', MagicMock(return_value=api_response(data))):
        assert auth_client.get('/admin/reports?reportType=payments').status_code == 200


@pytest.mark.parametrize('kind', RECORDS)
def test_empty_reports_and_only_two_export_actions_preserve_all_filters(auth_client, kind):
    params = {'reportType': kind, 'startDate': '2026-11-01', 'endDate': '2026-11-30', 'filter': 'Penang & heritage'}
    api = MagicMock(return_value=api_response({'records': []}))
    with _patch_view_api('admin_fr13.reports', api):
        response = auth_client.get('/admin/reports', query_string=params)
    assert response.status_code == 200
    if kind != 'system_summary':
        assert 'No matching records found' in response.text
    links = re.findall(r'href="([^"]*/reports/export\?[^"]*)"', response.text)
    assert len(links) == 2
    formats = set()
    for link in links:
        query = parse_qs(urlparse(unescape(link)).query)
        formats.add(query.pop('format')[0])
        assert query == {key: [value] for key, value in params.items()}
    assert formats == {'xlsx', 'pdf'}
    assert 'Print Report' not in response.text and 'Export CSV' not in response.text and 'Advanced CSV' not in response.text
    api.assert_called_once_with('GET', '/api/fr13/reports/summary', params=params)


@pytest.mark.parametrize('amount', [None, 'unknown', 'NaN', 'Infinity', {}, [], True, -10, 0, '12.34'])
def test_amounts_are_not_assumed_zero_and_private_fields_are_not_rendered(auth_client, amount):
    record = {**RECORDS['payments'], 'amount': amount, 'password': 'PRIVATE_CREDENTIAL',
              'productTitle': '<script>literal-product</script>'}
    with _patch_view_api('admin_fr13.reports', MagicMock(return_value=api_response({'records': [record]}))):
        response = auth_client.get('/admin/reports?reportType=payments')
    assert response.status_code == 200
    table = response.text.split('<table class="records-table">')[1].split('</table>')[0]
    assert 'PRIVATE_CREDENTIAL' not in response.text and '<script>literal-product</script>' not in table
    assert '&lt;script&gt;literal-product&lt;/script&gt;' in table
    assert ('>0.00<' in table) is (amount == 0)
    if amount == '12.34':
        assert '>12.34<' in table


@pytest.mark.parametrize('status', [400, 403, 503])
def test_backend_failure_is_not_an_empty_successful_report(auth_client, status):
    with _patch_view_api('admin_fr13.reports', MagicMock(return_value=api_response({}, status))):
        response = auth_client.get('/admin/reports?reportType=feedback')
    assert response.status_code == status
    assert 'No matching records found' not in response.text


@pytest.mark.parametrize('records', [None, [], [{'id': 'sparse'}, {'id': 'nulls', 'amount': None, 'createdAt': None}]])
def test_nullable_and_mixed_legacy_records_are_supported(auth_client, records):
    with _patch_view_api('admin_fr13.reports', MagicMock(return_value=api_response({'records': records}))):
        assert auth_client.get('/admin/reports?reportType=users').status_code == 200


@pytest.mark.parametrize('records', ['invalid', {}, [None]])
def test_malformed_record_contract_is_not_hidden_as_empty_success(auth_client, records):
    with _patch_view_api('admin_fr13.reports', MagicMock(return_value=api_response({'records': records}))):
        assert auth_client.get('/admin/reports?reportType=users').status_code == 502


def test_invalid_json_and_unavailable_feedback_are_explained(auth_client):
    malformed = api_response({})
    malformed.json.side_effect = ValueError('PRIVATE response')
    with _patch_view_api('admin_fr13.reports', MagicMock(return_value=malformed)):
        response = auth_client.get('/admin/reports?reportType=feedback')
    assert response.status_code == 502 and 'PRIVATE' not in response.text
    source = {'feedbackSources': {'partial': True, 'recordLimitPerSource': 10000,
              'sources': {'fyp_regional': {'status': 'unavailable', 'loaded': 0}}}, 'records': []}
    with _patch_view_api('admin_fr13.reports', MagicMock(return_value=api_response(source))):
        response = auth_client.get('/admin/reports?reportType=feedback')
    assert response.status_code == 200
    assert 'Feedback source scope — Partial' in response.text and 'fyp_regional: unavailable' in response.text


def test_unsupported_report_or_format_rejected_before_proxy(auth_client):
    api = MagicMock()
    for path in ['/admin/reports?reportType=other', '/admin/reports?reportType=unsupported',
                 '/admin/reports/export?format=unsupported']:
        with _patch_view_api('admin_fr13.reports', api), _patch_view_api('admin_fr13.export_report', api):
            assert auth_client.get(path).status_code == 400
    api.assert_not_called()


@pytest.mark.parametrize('kind', RECORDS)
@pytest.mark.parametrize('format', ['xlsx', 'pdf'])
def test_download_proxies_preserve_type_dates_keyword_and_bytes(auth_client, kind, format):
    params = {'reportType': kind, 'startDate': '2026-11-01', 'endDate': '2026-11-30', 'filter': 'Penang'}
    result = api_response({})
    result.content = b'isolated-download-bytes'
    api = MagicMock(return_value=result)
    with _patch_view_api('admin_fr13.export_report', api):
        response = auth_client.get('/admin/reports/export', query_string={**params, 'format': format})
    assert response.status_code == 200 and response.data == result.content
    assert 'attachment' in response.headers['Content-Disposition']
    api.assert_called_once_with('GET', '/api/fr13/reports/export' + ('.xlsx' if format == 'xlsx' else ''), params=params)


@pytest.mark.parametrize('path', ['/admin/reports', '/admin/reports/export?format=xlsx', '/admin/reports/export?format=pdf'])
def test_reports_require_an_admin_session(auth_client, path):
    with auth_client.session_transaction() as session:
        session['portal_role'] = 'operator'
    api = MagicMock()
    with _patch_view_api('admin_fr13.reports', api), _patch_view_api('admin_fr13.export_report', api):
        assert auth_client.get(path).status_code == 302
    api.assert_not_called()
