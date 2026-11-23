"""Compact CSV and styled XLSX contracts using isolated report payloads only."""
import csv
import io
from copy import deepcopy
from decimal import Decimal
from datetime import datetime
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from modules.fr13_administrator_management import routes
from services.admin_report_spreadsheet import compact_csv, export_xlsx, record_table, summary_table
from services.admin_report_csv import REPORT_TITLES

AUTH = {'Authorization': 'Bearer synthetic-admin'}
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def source(kind='payments', records=None):
    return {'criteria': {'reportType': kind, 'startDate': '2026-11-01', 'endDate': '', 'filter': 'Penang'},
            'generatedAt': '2026-11-18T10:26:01+08:00', 'dataLimited': True, 'recordLimit': 500,
            'recordsLimited': True, 'recordDisplayLimit': 200, 'counts': {'filtered_records': 301},
            'summary': {'users': {'total': 10}, 'payments': {'total': 33, 'paid': 12,
                         'totalPaidRevenue': 345.6789, 'testPaidTotal': 123.4567}},
            'records': records or []}


def payment(**changes):
    return {'id': '000012345678901234567890', 'productType': 'package', 'productTitle': 'Heritage Tour',
            'amount': 123.4567, 'currency': 'MYR', 'paymentStatus': 'paid', 'testMode': True,
            'createdAt': '2026-11-18T10:26:01+08:00', **changes}


def workbook(report):
    output = io.BytesIO()
    export_xlsx(report, output)
    return output.getvalue()


def inspect_xlsx(content):
    with ZipFile(io.BytesIO(content)) as archive:
        strings = ET.fromstring(archive.read('xl/sharedStrings.xml'))
        strings = [''.join(node.itertext()) for node in strings]
        book = ET.fromstring(archive.read('xl/workbook.xml'))
        result = []
        for index, info in enumerate(book.find('m:sheets', NS), 1):
            sheet = ET.fromstring(archive.read(f'xl/worksheets/sheet{index}.xml'))
            cells = {}
            for node in sheet.findall('.//m:sheetData/m:row/m:c', NS):
                value = node.find('m:v', NS)
                value = value.text if value is not None else None
                cells[node.attrib['r']] = strings[int(value)] if node.get('t') == 's' else value
            result.append((info.attrib['name'], cells, sheet))
        return result, archive.read('xl/styles.xml'), archive.namelist()


def parse_compact(data):
    rows = list(csv.reader(io.StringIO(data.lstrip('\ufeff'), newline='')))
    index = next(i for i, row in enumerate(rows) if row[0] == 'No.')
    return rows, rows[index], rows[index + 1:]


@pytest.mark.parametrize('kind', REPORT_TITLES)
def test_compact_report_types_never_expand_with_raw_fields(kind):
    report = source(kind, [payment(**{f'raw{i}': 'technical data' for i in range(193)})])
    before = deepcopy(report)
    rows, headings, records = parse_compact(compact_csv(report))
    assert rows[0][0] == REPORT_TITLES[kind]
    # Feedback deliberately exposes identity, provenance and effective moderation in 13 columns.
    assert len(headings) <= (13 if kind == 'feedback' else 10) and len({len(row) for row in rows}) == 1
    if kind == 'feedback':
        assert headings == ['No.', 'Feedback ID', 'Destination', 'Destination ID', 'Rating', 'Review Comment',
                            'Feedback Source', 'Review Provenance', 'Feedback Status', 'Moderation Status',
                            'Moderation Category', 'Submitted Date', 'Reviewed Date']
    assert 'technical data' not in compact_csv(report)
    if kind == 'system_summary':
        assert headings == ['No.', 'Category', 'Metric', 'Value']
        assert [row[1:] for row in records] == [[str(v) for v in row] for row in summary_table(report)[1]]
    else:
        assert len(records) == 1 and records[0][0] == '1'
    assert report == before


def test_payments_eight_columns_and_source_amounts_no_fake_myr_scope():
    report = source(records=[payment()])
    _, headings, records = parse_compact(compact_csv(report))
    assert headings == ['No.', 'Order Reference', 'Product Type', 'Product Name', 'Amount (MYR)',
                         'Payment Status', 'Test Mode', 'Created Date']
    assert records[0] == ['1', payment()['id'], 'package', 'Heritage Tour', '123.4567', 'paid', 'Yes',
                           '2026-11-18T02:26:01Z']
    for currency in ('USD', None):
        _, headings, records = parse_compact(compact_csv(source(records=[payment(), payment(currency=currency)])))
        assert 'Currency' in headings and 'Amount (MYR)' not in headings


def test_snapshot_hotel_name_and_distinct_statuses():
    columns, rows = record_table('payments', [payment(productTitle='-', quoteSnapshot={'name': 'Hotel 槟城'},
                                                    paymentStatus='cancelled', status='pending')])
    values = dict(zip([col[1] for col in columns], rows[0]))
    assert values['Product Name'] == 'Hotel 槟城'
    assert values['Payment Status'] == 'cancelled'


def test_hotel_booking_uses_existing_cost_currency_and_keeps_booking_status_separate():
    columns, rows = record_table('bookings', [{'id': 'booking', 'selectedHotel': {'name': 'Hotel'},
        'hotelCost': 249.84, 'hotelCurrency': 'MYR', 'bookingStatus': 'confirmed'}])
    values = dict(zip([col[1] for col in columns], rows[0]))
    assert values['Amount'] == 249.84 and values['Currency'] == 'MYR'
    assert values['Booking / Record Status'] == 'confirmed'
    assert 'Payment Status' not in values and 'Booking Type' not in values


def test_numbered_rows_unicode_quotes_multiline_formula_safety_and_missing_cells():
    value = '=unsafe, "中文"\nsecond line'
    report = source(records=[payment(productTitle=value, amount=Decimal('123.456700')), payment(testMode=False, amount=None)])
    report['criteria']['filter'] = '@unsafe'
    rows, headers, records = parse_compact(compact_csv(report))
    assert records[0][3] == "'" + value and records[0][4] == '123.456700'
    assert records[1][0] == '2' and records[1][4] == '' and records[1][6] == 'No'
    assert not any(cell.lstrip().startswith(('=', '+', '-', '@')) for row in rows for cell in row)
    assert '301 matching; 2 detailed records exported' in str(rows)
    assert 'Detailed export is incomplete' in str(rows)


@pytest.mark.parametrize('kind', REPORT_TITLES)
def test_xlsx_four_blocks_styling_freeze_filter_empty_and_no_formulas(kind):
    content = workbook(source(kind, [payment(productTitle='=NOT_A_FORMULA', id='0001')]))
    sheets, styles, files = inspect_xlsx(content)
    name, cells, xml = sheets[0]
    assert cells['A1'].startswith('TRAVELMATE  |  ')
    assert cells['A12'] == 'NO.' and cells['A13'] == '1'
    assert xml.find('m:sheetViews/m:sheetView/m:pane', NS).get('topLeftCell') == 'B13'
    assert xml.find('m:autoFilter', NS).get('ref').startswith('A12:')
    assert xml.find('m:mergeCells', NS) is not None
    assert all(color in styles for color in (b'FFF5A7A9', b'FFF9D1D0', b'FFA0F2AA', b'FFA9F0EE'))
    assert xml.find('.//m:f', NS) is None and xml.find('m:hyperlinks', NS) is None
    assert not any('externalLink' in file for file in files)
    assert name == ('System Overview' if kind == 'system_summary' else kind.title())
    empty_sheets, _, _ = inspect_xlsx(workbook(source(kind)))
    assert 'A13' not in empty_sheets[0][1] if kind != 'system_summary' else True


def test_xlsx_full_identifiers_amount_precision_dates_and_text_security():
    value = '中文, "quotes"\n' + 'very long product name ' * 30
    sheets, _, _ = inspect_xlsx(workbook(source(records=[payment(productTitle=value),
                payment(id='0002', amount=Decimal('123456789012345.6789'), productTitle='https://example.com')])))
    _, cells, xml = sheets[0]
    assert cells['B13'] == payment()['id'] and cells['D13'] == value
    assert float(cells['E13']) == 123.4567
    assert cells['E14'] == '123456789012345.6789'
    assert cells['H13'] != payment()['createdAt']  # real Excel datetime serial, converted to UTC
    row = xml.find("m:sheetData/m:row[@r='13']", NS)
    assert float(row.get('ht')) > 32
    assert xml.find('m:hyperlinks', NS) is None


def test_firestore_datetime_objects_and_naive_historical_dates():
    sheets, _, _ = inspect_xlsx(workbook(source(records=[
        payment(createdAt=datetime.fromisoformat('2026-11-18T10:26:01+08:00')),
        payment(createdAt='2026-11-18 10:26:01'), payment(createdAt=None)])))
    cells = sheets[0][1]
    assert float(cells['H13']) > 45000
    assert cells['H14'] == '2026-11-18 10:26:01'
    assert cells['H15'] is None


def test_system_overview_and_category_sheets_cover_every_loaded_record_once():
    records = [{'id': 'u', 'role': 'traveller', 'name': 'User'},
               {'id': 'p', 'approvalStatus': 'approved', 'title': 'Package'},
               {'id': 'c', 'campaignTitle': 'Campaign'}, {'id': 'f', 'feedbackStatus': 'visible'},
               payment(), {'id': 'b', 'hotelName': 'Hotel'}, {'id': 'unknown', 'custom': 'legacy'},
               {'id': 'ambiguous', 'role': 'traveller', 'campaignTitle': 'Mixed'}]
    # Historical CSV imports can include empty fields from every record category.
    records = [dict({'role': None, 'approvalStatus': None, 'title': None, 'campaignTitle': None,
                     'feedbackStatus': None, 'rating': None, 'comment': None}, **record) for record in records]
    report = source('system_summary', records)
    before = deepcopy(report)
    sheets, _, _ = inspect_xlsx(workbook(report))
    assert sheets[0][0] == 'System Overview'
    assert sheets[0][1]['B13'] == 'Loaded Scope' and sheets[0][1]['D13'] == '301'
    assert len(sheets) == 8
    identifiers = [value for _, cells, _ in sheets[1:] for key, value in cells.items()
                   if key.startswith('B') and key[1:].isdigit() and int(key[1:]) >= 13]
    assert sorted(identifiers) == sorted(record['id'] for record in records)
    assert report == before


def test_excel_overlong_cell_fails_explicitly_instead_of_silent_truncation():
    with pytest.raises(ValueError, match='Excel text limit'):
        workbook(source(records=[payment(productTitle='x' * 32768)]))


@pytest.mark.parametrize('extension', ['csv?layout=compact', 'xlsx'])
@pytest.mark.parametrize('role', ['none', 'traveller', 'operator'])
def test_export_admin_access(client, request, extension, role):
    if role != 'none':
        request.getfixturevalue('mock_' + role + '_auth')
    result = client.get('/api/fr13/reports/export.' + extension, headers={} if role == 'none' else AUTH)
    assert result.status_code == (401 if role == 'none' else 403)


def test_xlsx_route_alias_redaction_and_filter_forwarding(client, mock_admin_auth):
    report = source(records=[payment(metadata={'clientSecret': 'PRIVATE'}, passwordHash='PRIVATE')])
    for path in ['/api/fr13/reports/export.xlsx?', '/api/fr13/reports/export?format=xlsx&']:
        with patch.object(routes, '_summary', return_value=report) as load:
            response = client.get(path + 'reportType=payments&filter=Penang&startDate=2026-11-01', headers=AUTH)
        assert response.status_code == 200
        assert response.mimetype.endswith('spreadsheetml.sheet')
        assert 'TravelMate_Admin_payments_Report.xlsx' in response.headers['Content-Disposition']
        load.assert_called_once_with({'reportType': 'payments', 'filter': 'Penang', 'startDate': '2026-11-01', 'endDate': ''})
        sheets, _, _ = inspect_xlsx(response.data)
        assert 'PRIVATE' not in str(sheets)


def test_bad_criteria_remain_rejected(client, mock_admin_auth):
    with patch.object(routes, '_summary', side_effect=ValueError('Use a valid report type')):
        response = client.get('/api/fr13/reports/export.xlsx?reportType=invalid', headers=AUTH)
    assert response.status_code == 400
