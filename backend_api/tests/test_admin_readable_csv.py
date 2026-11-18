"""CSV presentation contracts; all report/auth/persistence boundaries use isolated fixtures."""
import csv
import io
import json
from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch

import pytest

from modules.fr13_administrator_management import routes
from services.admin_report_csv import COLUMNS, REPORT_TITLES, readable_csv

AUTH = {'Authorization': 'Bearer synthetic-admin'}


def report(kind='payments', records=None):
    return {
        'generatedAt': '2026-11-18T02:03:04+00:00',
        'criteria': {'reportType': kind, 'startDate': '2026-11-01', 'endDate': '', 'filter': 'Penang'},
        'dataLimited': True, 'recordLimit': 500, 'recordsLimited': True, 'recordDisplayLimit': 200,
        'counts': {'users': 4, 'filtered_records': 201, 'payment_records': 3},
        'summary': {'payments': {'total': 3, 'paid': 2, 'failed': 1, 'testMode': 2,
                                 'totalPaidRevenue': 120.75, 'testPaidTotal': 100.25}},
        'records': records or [],
    }


def parse(text):
    return list(csv.reader(io.StringIO(text.lstrip('\ufeff'), newline='')))


def details(rows):
    index = next(i for i, row in enumerate(rows) if row[0] == 'DETAILED RECORDS') + 1
    if rows[index][0] == 'No records matched the selected criteria':
        index += 1
    return rows[index], rows[index + 1:]


@pytest.mark.parametrize('kind', REPORT_TITLES)
def test_each_report_title_columns_exact_values_and_constant_row_width(kind):
    item = {key: f'value-{key}' for key, _ in COLUMNS[kind]}
    item.update(extraLegacyField='preserve this', id='000012345678901234567890')
    source = report(kind, [item, {'id': 'second', 'amount': 0, 'testMode': False}])
    before = deepcopy(source)
    output = readable_csv(source)
    rows = parse(output)
    assert output.startswith('\ufeff') and '\r\n' in output
    assert rows[0][0] == REPORT_TITLES[kind]
    header, records = details(rows)
    assert header[:len(COLUMNS[kind])] == [label for _, label in COLUMNS[kind]]
    assert len(records) == 2 and all(len(row) == len(header) for row in rows)
    assert len(header) == len(set(header))
    first = dict(zip(header, records[0]))
    for key, label in COLUMNS[kind]:
        assert first[label] == str(item[key])
    assert first['Extra Legacy Field [extraLegacyField]'] == 'preserve this'
    assert source == before
    assert 'END OF REPORT' not in output


def test_unicode_quotes_multiline_null_precision_dates_and_nested_values():
    comment = '中文 café, "quoted"\r\nsecond line\nthird line'
    item = {'id': '001', 'productTitle': comment, 'amount': Decimal('123.456700'),
            'createdAt': '2026-11-18T10:03:04.123456+08:00', 'testMode': False,
            'currency': None, 'nested': {'name': '槟城', 'rows': [1, None]}}
    header, records = details(parse(readable_csv(report(records=[item]))))
    assert len(records) == 1
    row = dict(zip(header, records[0]))
    assert row['Product Name'] == comment
    assert row['Amount'] == '123.456700'
    assert row['Currency'] == '' and row['Test Mode'] == 'False'
    assert row['Created Date'] == item['createdAt']
    assert json.loads(row['Nested [nested]']) == item['nested']


@pytest.mark.parametrize('payload', ['=HYPERLINK("unsafe")', ' +cmd', '-2+3', '@SUM(1)',
                                      '\tformula', '\rformula', '\n=1+1', '  \t=1+1'])
def test_formula_protection_in_records_metadata_and_extension_headers(payload):
    source = report(records=[{'id': 'record', 'productTitle': payload, payload: payload}])
    source['criteria']['filter'] = payload
    rows = parse(readable_csv(source))
    header, records = details(rows)
    assert records[0][header.index('Product Name')] == "'" + payload
    assert next(row[1] for row in rows if row[0] == 'Applied Filter') == "'" + payload
    assert not any(cell.lstrip().startswith(('=', '+', '-', '@')) for row in rows for cell in row)


def test_summary_values_and_scope_disclosures_are_source_values_not_recalculated():
    rows = parse(readable_csv(report()))
    pairs = {row[0]: row[1] for row in rows}
    assert pairs['Payment Records / Paid Records'] == '2'
    assert pairs['Payment Records / Recorded Paid Total (MYR, All Recorded Modes)'] == '120.75'
    assert pairs['Payment Records / Included Test Mode Paid Total (MYR)'] == '100.25'
    assert pairs['Source Record Limit (Per Category)'] == '500'
    assert pairs['Detailed Record Limit'] == '200'
    assert pairs['Detailed Export Limited'] == 'True'
    assert pairs['Records Exported'] == '0'
    assert 'not the complete system dataset' in pairs['Source Scope']
    assert pairs['End Date'] == ''
    assert details(rows)[1] == []


def test_readable_route_redaction_download_and_unchanged_summary(client, mock_admin_auth):
    source = report(records=[{'id': 'order-1', 'productTitle': '=unsafe', 'amount': 120.75,
                              'passwordHash': 'PRIVATE', 'metadata': {'clientSecret': 'PRIVATE'}}])
    before = deepcopy(source)
    with patch.object(routes, '_summary', return_value=source):
        response = client.get('/api/fr13/reports/export.csv?reportType=payments&layout=readable', headers=AUTH)
    assert response.status_code == 200 and response.mimetype == 'text/csv'
    assert response.data.startswith(b'\xef\xbb\xbf')
    assert 'TravelMate_Admin_payments_Report.csv' in response.headers['Content-Disposition']
    text = response.get_data(as_text=True)
    assert 'PRIVATE' not in text and "'=unsafe" in text
    assert source == before


def test_default_and_explicit_legacy_remain_byte_compatible(client, mock_admin_auth):
    source = report(records=[{'id': '001', 'amount': 3.14159, 'title': '=unsafe'}])
    expected = io.StringIO()
    writer = csv.writer(expected)
    rows = [['TravelMate Administrator System Report'], ['Generated At', source['generatedAt']],
            ['Report Type', 'payments'], ['Start Date', '2026-11-01'], ['End Date', ''], ['Filter', 'Penang'],
            ['Source records limited', True], ['Export rows limited', True], [], ['Metric', 'Value'],
            *[[k, v] for k, v in source['counts'].items()], [], ['Filtered Records'],
            ['amount', 'id', 'title'], [3.14159, '001', "'=unsafe"]]
    writer.writerows(rows)
    with patch.object(routes, '_summary', return_value=source):
        default = client.get('/api/fr13/reports/export.csv', headers=AUTH)
        legacy = client.get('/api/fr13/reports/export.csv?layout=legacy', headers=AUTH)
    assert default.data == legacy.data == expected.getvalue().encode('utf-8')
    assert 'TravelMate_System_Report.csv' in default.headers['Content-Disposition']


@pytest.mark.parametrize('role', ['none', 'traveller', 'operator'])
def test_readable_access_is_admin_only(client, request, role):
    if role != 'none':
        request.getfixturevalue('mock_' + role + '_auth')
    response = client.get('/api/fr13/reports/export.csv?layout=readable', headers={} if role == 'none' else AUTH)
    assert response.status_code == (401 if role == 'none' else 403)


def test_invalid_layout_is_rejected_without_loading_records(client, mock_admin_auth):
    with patch.object(routes, '_summary') as load:
        response = client.get('/api/fr13/reports/export.csv?layout=unknown', headers=AUTH)
    assert response.status_code == 400
    load.assert_not_called()


def test_real_source_and_detail_caps_remain_disclosed(client, mock_admin_auth):
    items = [{'id': str(i), 'name': 'Account', 'role': 'traveller'} for i in range(502)]
    with patch.object(routes, 'retrieveRecord', side_effect=lambda collection, **kw: items if collection == 'users' else []):
        response = client.get('/api/fr13/reports/export.csv?reportType=users&layout=readable', headers=AUTH)
    rows = parse(response.get_data(as_text=True))
    header, records = details(rows)
    pairs = {row[0]: row[1] for row in rows}
    assert len(records) == 200
    assert pairs['Loaded Scope / Matching Detailed Records'] == '500'
    assert pairs['User Accounts / Total Records'] == '500'
    assert pairs['Records Exported'] == '200'
    assert pairs['Detailed Export Limited'] == 'True'
    assert 'Partial source data' in pairs['Source Scope']


@pytest.mark.parametrize('kind', REPORT_TITLES)
def test_empty_reports_have_stable_headers_and_no_fabricated_records(kind):
    source = report(kind)
    source.update(counts={}, summary={}, dataLimited=False, recordsLimited=False)
    rows = parse(readable_csv(source))
    header, records = details(rows)
    assert records == [] and header == [label for _, label in COLUMNS[kind]]
    assert ['No records matched the selected criteria'] + [''] * (len(header) - 1) in rows


@pytest.mark.parametrize('kind', REPORT_TITLES)
def test_real_summary_route_filters_and_all_sanitized_fields_survive(client, mock_admin_auth, kind):
    record = {'id': '0001', 'createdAt': '2026-11-01', 'name': 'Penang',
              'packageSnapshot': {'title': 'Penang Package'}, 'comment': 'Penang review',
              'amount': 7.1234, 'currency': 'MYR', 'paymentStatus': 'paid', 'testMode': True,
              'custom': {'text': 'original'}, 'password': 'PRIVATE'}
    def retrieve(collection, *args, **kwargs):
        return [deepcopy(record), {**record, 'id': 'old', 'createdAt': '2000-01-01'}]
    query = f'?reportType={kind}&layout=readable&startDate=2026-11-01&endDate=2026-11-01&filter=Penang'
    with patch.object(routes, 'retrieveRecord', side_effect=retrieve):
        response = client.get('/api/fr13/reports/export.csv' + query, headers=AUTH)
        original = client.get('/api/fr13/reports/summary' + query, headers=AUTH).get_json()['report']
    assert response.status_code == 200
    header, rows = details(parse(response.get_data(as_text=True)))
    assert len(rows) == len(original['records']) and rows
    assert all('old' not in row for row in rows)
    assert 'PRIVATE' not in response.get_data(as_text=True)
    labels = dict(COLUMNS[kind])
    for item, row in zip(original['records'], rows):
        values = dict(zip(header, row))
        for key, value in item.items():
            label = labels.get(key) or next(name for name in header if name.endswith(f'[{key}]'))
            if isinstance(value, (dict, list)):
                assert json.loads(values[label]) == value
            else:
                expected = '' if value is None else str(value)
                if expected.lstrip().startswith(('=', '+', '-', '@')):
                    expected = "'" + expected
                assert values[label] == expected
