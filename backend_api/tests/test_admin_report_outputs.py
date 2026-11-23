"""All real report APIs/exporters with in-memory sources and read-only temporary moderation."""
import io
import re
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import patch
from zipfile import ZipFile

import pytest

from admin_report_records import display_value, display_table
from services import report_service
from services.admin_report_csv import REPORT_TITLES
from test_admin_feedback_report_scope import scope, AUTH
from test_admin_spreadsheet_layout import inspect_xlsx
from test_report_pdf_presentation import export_pages


@pytest.fixture
def report_sources(scope, monkeypatch):
    from modules.fr13_administrator_management import routes
    def retrieve(collection, document_id=None, limit=None, **kwargs):
        rows = deepcopy(scope['collections'].get(collection, []))
        if document_id:
            return next((row for row in rows if row.get('id') == document_id), None)
        return rows[:limit]
    monkeypatch.setattr(routes, 'retrieveRecord', retrieve)
    common = {'createdAt': '2026-11-10T10:00:00Z', 'filterTag': 'Penang audit fixture', 'password': 'PRIVATE_SENTINEL'}
    scope['collections'].update({
        'users': [{**common, 'id': 'fixture-user', 'role': 'operator', 'name': 'Penang Fixture Operator', 'verificationStatus': 'verified'}],
        'tourism_packages': [{**common, 'id': 'fixture-package', 'title': 'Penang Fixture Package', 'approvalStatus': 'approved',
                              'adultPrice': 50, 'currency': 'MYR', 'operatorId': 'fixture-operator'}],
        'promotional_campaigns': [{**common, 'id': 'fixture-campaign', 'campaignTitle': 'Penang Fixture Offer',
                                  'packageId': 'fixture-package', 'discountType': 'percentage', 'discountValue': 10,
                                  'reviewStatus': 'approved', 'startDate': '2026-11-01', 'endDate': '2026-11-30'}],
        'hotel_bookings': [{**common, 'id': 'fixture-hotel', 'hotelName': 'Penang Fixture Hotel', 'hotelCost': 75,
                            'hotelCurrency': 'MYR', 'bookingStatus': 'selected', 'paymentStatus': 'unpaid', 'travellerCount': 2}],
        'checkout_orders': [{**common, 'id': 'fixture-paid-order', 'quoteType': 'package', 'packageId': 'fixture-package',
                             'packageSnapshot': {'title': 'Penang Fixture Package'}, 'groupSize': 2,
                             'selectedDepartureDate': '2026-11-24', 'paymentStatus': 'paid', 'amount': 100,
                             'currency': 'MYR', 'provider': 'stripe_checkout_test', 'testMode': True}],
    })
    return scope


@pytest.mark.parametrize('kind', REPORT_TITLES)
@pytest.mark.parametrize('empty', [False, True])
def test_each_type_summary_xlsx_pdf_and_filters(client, mock_admin_auth, report_sources, tmp_path, kind, empty):
    criteria = {'reportType': kind, 'startDate': '2026-11-10', 'endDate': '2026-11-10',
                'filter': 'definitely-no-match' if empty else 'Penang'}
    body = client.get('/api/fr13/reports/summary', query_string=criteria, headers=AUTH)
    assert body.status_code == 200
    report = body.json['report']
    assert bool(report['records']) is not empty
    assert 'PRIVATE_SENTINEL' not in body.text
    if kind == 'feedback' and not empty:
        assert report['counts']['feedback'] == 121 and report['summary']['feedback']['hiddenOrRemoved'] == 1
    if kind == 'bookings' and not empty:
        assert {row['id'] for row in report['records']} == {'fixture-hotel', 'fixture-paid-order'}
    pages = []
    original = report_service.NumberedCanvas

    def capture(*args, **kwargs):
        canvas = original(*args, **kwargs)
        pages.append(canvas)
        return canvas

    with patch.object(report_service, 'NumberedCanvas', side_effect=capture):
        pdf = client.get('/api/fr13/reports/export.pdf', query_string=criteria, headers=AUTH)
    assert pdf.status_code == 200 and pdf.mimetype == 'application/pdf'
    assert pdf.data.startswith(b'%PDF-') and b'%%EOF' in pdf.data[-40:]
    state = pages[0]._saved_page_states
    assert len(state) >= 3
    text = '\n'.join('\n'.join(page['_code']) for page in state)
    if kind == 'system_summary':
        assert 'Administrator System Activity Report' in text
    else:
        assert REPORT_TITLES[kind].replace('TravelMate ', '') in '\n'.join(state[0]['_code'])
        assert f'{kind.title()} records' in text
        for row in report['records'][:200]:
            assert row['id'] in text
        if empty:
            assert 'No matching records found' in text
        if kind in {'payments', 'bookings'}:
            # PDF wraps text into separate drawing operators; compare joined visible text.
            visible_text = ' '.join(re.findall(r'\(([^()]*)\) Tj', text))
            assert 'independently confirm a supplier reservation' in visible_text
    assert 'PRIVATE_SENTINEL' not in text
    xlsx = client.get('/api/fr13/reports/export.xlsx', query_string=criteria, headers=AUTH)
    assert xlsx.status_code == 200 and 'spreadsheetml' in xlsx.mimetype
    with ZipFile(io.BytesIO(xlsx.data)) as archive:
        assert archive.testzip() is None and b'PRIVATE_SENTINEL' not in archive.read('xl/sharedStrings.xml')
    sheets, _, _ = inspect_xlsx(xlsx.data)
    values = {str(value) for _, cells, _ in sheets for value in cells.values()}
    for row in report['records']:
        assert row['id'] in values
    # Small isolated output fixtures for external reader verification; never owner records.
    (tmp_path / f'{kind}.pdf').write_bytes(pdf.data)
    (tmp_path / f'{kind}.xlsx').write_bytes(xlsx.data)


@pytest.mark.parametrize('kind', REPORT_TITLES)
@pytest.mark.parametrize('format', ['pdf', 'xlsx'])
def test_legacy_export_dispatch_retains_selected_type(client, mock_admin_auth, report_sources, kind, format):
    output = client.get('/api/fr13/reports/export', query_string={'reportType': kind, 'format': format}, headers=AUTH)
    assert output.status_code == 200
    assert output.data.startswith(b'%PDF' if format == 'pdf' else b'PK')


@pytest.mark.parametrize('value', [None, 'bad', 'NaN', 'Infinity', {}, [], True, -1])
def test_unknown_money_never_becomes_zero(value):
    assert display_value(value, 'money') in {'—', 'Not Available'}


@pytest.mark.parametrize('value,expected', [
    ('2026-11-10', '10 Nov 2026'), ('2026-11-10T10:00:00+08:00', '10 Nov 2026 02:00 UTC'),
    ('Tue, 10 Nov 2026 02:00:00 GMT', '10 Nov 2026 02:00 UTC'),
    (datetime(2026, 11, 10, tzinfo=timezone.utc), '10 Nov 2026 00:00 UTC'),
    ({}, 'Not Available'), (5, 'Not Available'), (None, '—')])
def test_date_representation_is_safe(value, expected):
    assert display_value(value, 'date') == expected


def test_shared_display_is_read_only_and_keeps_zero_precise_raw_values():
    records = [{'id': 'historical', 'amount': '0', 'currency': 'MYR', 'testMode': False},
               {'id': 'old', 'amount': '12.3456', 'currency': 'MYR', 'testMode': True}]
    before = deepcopy(records)
    headers, rows = display_table('payments', records)
    assert '0.00' in rows[0] and '12.35' in rows[1]
    assert 'No' in rows[0] and 'Yes' in rows[1]
    assert records == before


def test_pdf_long_text_multiple_pages_escaping_and_explicit_detail_bound():
    data = {'criteria': {'reportType': 'feedback'}, 'counts': {'filtered_records': 201},
            'records': [{'id': f'feedback-long-{n:03}', 'comment': 'Long review <img src="file:///forbidden"> ' * 120,
                          'rating': 4, 'feedbackStatus': 'hidden', 'reviewProvenance': 'Synthetic FYP evaluation feedback'}
                         for n in range(201)]}
    # Exercise in-row pagination with long comments, then a lighter large-count boundary.
    long = {**data, 'records': data['records'][:2]}
    pages, _ = export_pages(long, False)
    assert len(pages) > 3 and 'file:///forbidden' in '\n'.join(pages)
    for row in data['records']:
        row['comment'] = 'Short synthetic review.'
    pages, _ = export_pages(data, False)
    text = '\n'.join(pages)
    assert 'Showing 200 of 201' in text and 'PDF detail limit: 200' in text
    assert 'feedback-long-199' in text and 'feedback-long-200' not in text


@pytest.mark.parametrize('kind', ['unsupported', 'other'])
def test_invalid_report_type_is_rejected(client, mock_admin_auth, kind):
    for path in ['/api/fr13/reports/summary', '/api/fr13/reports/export.pdf', '/api/fr13/reports/export.xlsx']:
        assert client.get(path, query_string={'reportType': kind}, headers=AUTH).status_code == 400


@pytest.mark.parametrize('criteria', [{'startDate': '2026-13-01'}, {'endDate': 'invalid'},
                                    {'startDate': '2026-11-20', 'endDate': '2026-11-10'}])
def test_invalid_dates_rejected_for_summary_and_both_exports(client, mock_admin_auth, criteria):
    for path in ['/api/fr13/reports/summary', '/api/fr13/reports/export.pdf', '/api/fr13/reports/export.xlsx']:
        assert client.get(path, query_string={'reportType': 'feedback', **criteria}, headers=AUTH).status_code == 400


def test_unavailable_evaluation_sources_are_disclosed_in_both_exports(client, mock_admin_auth, report_sources, monkeypatch):
    from modules.fr13_administrator_management import routes
    from services import review_staging
    monkeypatch.setattr(routes, 'private_dataset', lambda: None)
    monkeypatch.setattr(review_staging, 'staging_path', lambda: report_sources['path'].with_name('missing.sqlite3'))
    criteria = {'reportType': 'feedback'}
    result = client.get('/api/fr13/reports/summary', query_string=criteria, headers=AUTH).json['report']
    assert result['counts']['feedback'] == 2 and result['feedbackSources']['partial']
    pages, _ = export_pages(result, False)
    assert 'unavailable' in '\n'.join(pages)
    for path in ['/api/fr13/reports/export.pdf', '/api/fr13/reports/export.xlsx']:
        assert client.get(path, query_string=criteria, headers=AUTH).status_code == 200
    xlsx = client.get('/api/fr13/reports/export.xlsx', query_string=criteria, headers=AUTH)
    sheets, _, _ = inspect_xlsx(xlsx.data)
    assert 'unavailable' in ' '.join(str(value) for _, cells, _ in sheets for value in cells.values())
    assert not report_sources['path'].with_name('missing.sqlite3').exists()
