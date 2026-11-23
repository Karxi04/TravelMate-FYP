"""Administrator report/source parity with synthetic records and read-only temporary SQLite."""
import csv
import io
import json
import sqlite3
from copy import deepcopy
from hashlib import sha256
from unittest.mock import Mock

import pytest

from modules.fr13_administrator_management import routes
from services import review_staging
from test_admin_spreadsheet_layout import inspect_xlsx
from test_report_pdf_presentation import export_pages

AUTH = {'Authorization': 'Bearer synthetic-admin'}


def review(identity, **fields):
    return {'id': identity, 'destinationId': 'local_penang_hill', 'destinationName': 'Penang Hill',
            'rating': 4, 'comment': 'A lovely visit with beautiful views.', 'feedbackStatus': 'visible',
            'moderationStatus': 'reviewed', 'submittedAt': '2026-11-10T10:00:00Z',
            'moderationDecision': {'actor': 'system', 'outcome': 'approve'}, **fields}


@pytest.fixture
def scope(app, monkeypatch, tmp_path):
    genuine = [review('shared'), review('genuine-two')]
    penang = [review('shared' if n == 0 else f'penang-{n:03}', synthetic=True) for n in range(104)]
    regional = [review(f'regional-{n:03}', synthetic=True) for n in range(15)]
    collections = {'feedback': genuine}
    monkeypatch.setattr(routes, 'retrieveRecord', lambda collection, *args, limit=None, **kw:
                        deepcopy(collections.get(collection, [])[:limit]))
    monkeypatch.setattr(routes, 'private_dataset', lambda: ('private-fixture', {}))
    monkeypatch.setattr(routes, 'dataset_reviews', lambda *_: deepcopy(penang))
    app.config['LOCAL_FYP_SAMPLE_REVIEWS'] = True
    path = tmp_path / 'moderation.sqlite3'
    monkeypatch.setattr(review_staging, 'staging_path', lambda: path)
    review_staging.initialize()  # Test setup only. Report paths must never call this.
    updates = {'feedbackStatus': 'hidden', 'reviewedAt': '2026-11-23T01:00:00Z',
               'updatedAt': '2026-11-23T01:00:00Z', 'moderationDecision': {'actor': 'admin', 'outcome': 'hide'}}
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO moderation VALUES (?,?)', ('regional-000', json.dumps({'updates': updates, 'history': [updates]})))
    before = sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(routes, 'all_regional_reviews', lambda: review_staging.overlay_rows(deepcopy(regional)))
    writers = [Mock(side_effect=AssertionError('Reports cannot write')) for _ in range(4)]
    for name, writer in zip(('storeRecord', 'updateRecord', 'deleteRecord'), writers):
        monkeypatch.setattr(routes, name, writer)
    monkeypatch.setattr(review_staging, 'initialize', writers[-1])
    connect, connections = sqlite3.connect, []

    def readonly(*args, **kwargs):
        assert kwargs.get('uri') is True and str(args[0]).endswith('?mode=ro')
        connections.append(str(args[0]))
        db = connect(*args, **kwargs)
        # Also enforce the boundary in SQLite, beyond mode=ro.
        db.set_authorizer(lambda action, *_: sqlite3.SQLITE_DENY if action in {
            sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
            sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE} else sqlite3.SQLITE_OK)
        return db

    monkeypatch.setattr(sqlite3, 'connect', readonly)
    state = dict(genuine=genuine, penang=penang, regional=regional, collections=collections,
                 path=path, connections=connections)
    yield state
    for writer in writers:
        writer.assert_not_called()
    if path.exists():
        assert sha256(path.read_bytes()).hexdigest() == before


def report(client, **criteria):
    response = client.get('/api/fr13/reports/summary', query_string={'reportType': 'feedback', **criteria}, headers=AUTH)
    assert response.status_code == 200, response.json
    return response.json['report']


def csv_details(client, layout):
    response = client.get('/api/fr13/reports/export.csv', query_string={'reportType': 'feedback', 'layout': layout}, headers=AUTH)
    assert response.status_code == 200
    rows = list(csv.reader(io.StringIO(response.get_data(as_text=True).lstrip('\ufeff'))))
    key = 'id' if layout == 'legacy' else 'Feedback ID'
    index = next(n for n, row in enumerate(rows) if key in row)
    return rows[index], rows[index + 1:]


def xlsx_details(client, kind='feedback'):
    response = client.get('/api/fr13/reports/export.xlsx', query_string={'reportType': kind}, headers=AUTH)
    assert response.status_code == 200
    sheets, _, _ = inspect_xlsx(response.data)
    _, cells, xml = next(sheet for sheet in sheets if sheet[0] == 'Feedback')
    # Retain exporter layout; row 12 contains column headings, row 13 starts data.
    assert cells['B12'] == 'FEEDBACK ID' and cells['G12'] == 'FEEDBACK SOURCE'
    assert not xml.findall('.//m:f', {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'})
    return [(cells[f'B{n}'], cells[f'G{n}'], cells[f'I{n}']) for n in range(13, 13 + sum(
        key.startswith('B') and int(key[1:]) >= 13 for key in cells))]


def test_all_sources_overlay_once_and_cross_format_parity(client, mock_admin_auth, scope):
    result = report(client)
    assert result['counts']['feedback'] == result['counts']['filtered_records'] == 121
    assert result['summary']['feedback'] == {'total': 121, 'genuine': 2, 'evaluation': 119,
        'visible': 120, 'pending': 0, 'removed': 0, 'hiddenOrRemoved': 1, 'reviewed': 121}
    assert result['dataLimited'] is False and result['recordsLimited'] is False
    assert result['feedbackSources']['exported'] == 121
    assert {k: v['loaded'] for k, v in result['feedbackSources']['sources'].items()} == {
        'traveller': 2, 'fyp_penang': 104, 'fyp_regional': 15}
    expected = {(row['id'], row['feedbackSource'], row['feedbackStatus']) for row in result['records']}
    assert len(expected) == 121  # Same original ID from two sources is not collapsed.
    assert len([r for r in result['records'] if r['id'] == 'regional-000']) == 1
    assert next(r for r in result['records'] if r['id'] == 'regional-000')['moderationState'] == 'hidden'
    assert {r['reviewProvenance'] for r in result['records'] if r['reviewSource'] != 'traveller'} == {'Synthetic FYP evaluation feedback'}
    assert {r['reviewProvenance'] for r in result['records'] if r['reviewSource'] == 'traveller'} == {'Genuine Traveller feedback'}
    assert set(xlsx_details(client)) == expected
    for layout in ('legacy', 'readable', 'compact'):
        header, rows = csv_details(client, layout)
        keys = ('id', 'feedbackSource', 'feedbackStatus') if layout == 'legacy' else ('Feedback ID', 'Feedback Source', 'Feedback Status')
        assert {(row[header.index(a)], row[header.index(b)], row[header.index(c)]) for row in rows for a, b, c in [keys]} == expected
    readable = client.get('/api/fr13/reports/export.csv?reportType=feedback&layout=readable', headers=AUTH).text
    assert 'Source Record Limit (Other Categories)' in readable
    assert 'Source Record Limit (Per Category)' not in readable
    moderation = client.get('/api/fr13/feedback?source=all', headers=AUTH).json
    assert {(r['id'], r['reviewSource']) for r in moderation['items']} == {(r['id'], r['reviewSource']) for r in result['records']}
    assert report(client, reportType='system_summary')['summary']['feedback'] == result['summary']['feedback']
    assert scope['connections']


@pytest.mark.parametrize('kind', ['feedback', 'system_summary'])
def test_feedback_over_500_and_200_is_not_truncated_other_limits_retained(client, mock_admin_auth, scope, kind):
    scope['genuine'][:] = [review(f'genuine-{n:04}') for n in range(620)]
    scope['collections']['users'] = [{'id': f'user-{n:04}', 'role': 'traveller'} for n in range(240)]
    result = report(client, reportType=kind)
    assert result['counts']['feedback'] == 739
    assert len([r for r in result['records'] if r.get('reportCategory') == 'feedback']) == 739
    assert len(xlsx_details(client, kind)) == 739
    assert result['feedbackSources']['omittedLoaded'] == 0
    if kind == 'system_summary':
        assert result['counts']['filtered_records'] == 979 and len(result['records']) == 939
        assert result['recordsOmitted'] == 40 and result['recordsLimited'] is True
    else:
        assert result['counts']['filtered_records'] == 739 and result['recordsLimited'] is False


def test_bounded_lookahead_is_explicit_partial_not_silent_truncation(client, mock_admin_auth, scope, monkeypatch):
    monkeypatch.setattr(routes, 'FEEDBACK_LIMIT', 5)
    scope['genuine'][:] = [review(f'genuine-{n:03}') for n in range(8)]
    result = report(client)
    assert result['dataLimited'] and result['feedbackSources']['partial']
    assert result['feedbackSources']['sources']['traveller']['status'] == 'limited'
    assert result['feedbackSources']['totalMatchingExact'] is False
    assert len(result['records']) == 15
    header, rows = csv_details(client, 'compact')
    assert len(rows) == 15
    exported = client.get('/api/fr13/reports/export.csv?reportType=feedback&layout=compact', headers=AUTH).text
    assert 'lower bound; total/omitted unavailable' in exported


def test_source_flags_missing_overlay_and_private_source_fail_closed(client, mock_admin_auth, scope, monkeypatch):
    client.application.config['LOCAL_FYP_SAMPLE_REVIEWS'] = False
    result = report(client)
    assert result['counts']['feedback'] == 106
    assert result['feedbackSources']['sources']['fyp_regional']['status'] == 'disabled'
    client.application.config['LOCAL_FYP_SAMPLE_REVIEWS'] = True
    monkeypatch.setattr(review_staging, 'staging_path', lambda: scope['path'].with_name('absent.sqlite3'))
    monkeypatch.setattr(routes, 'private_dataset', lambda: None)
    result = report(client)
    assert result['counts']['feedback'] == 2 and result['dataLimited']
    assert result['feedbackSources']['sources']['fyp_regional']['status'] == 'unavailable'
    assert result['feedbackSources']['sources']['fyp_penang']['status'] == 'unavailable'
    assert not scope['path'].with_name('absent.sqlite3').exists()
    listing = client.get('/api/fr13/feedback?source=all', headers=AUTH).json
    assert listing['dataLimited'] and listing['regionalUnavailable'] and listing['privateUnavailable']


def test_date_keyword_legacy_submission_and_overlay_update_filters(client, mock_admin_auth, scope):
    scope['genuine'][:] = [review('legacy', submittedAt=None, createdAt='2026-11-10'),
                          review('too-old', submittedAt='2025-01-01', updatedAt='2026-11-10')]
    scope['penang'][0].update(submittedAt='2026-11-10', createdAt='2001-01-01', comment='Unique private wording')
    for kwargs, count in [({'startDate': '2026-11-10', 'endDate': '2026-11-10'}, 120),
                          ({'filter': 'Unique private wording'}, 1),
                          ({'startDate': '2026-11-23', 'endDate': '2026-11-23'}, 0)]:
        result = report(client, **kwargs)
        assert result['counts']['feedback'] == count
        listing = client.get('/api/fr13/feedback', query_string={'source': 'all', **kwargs}, headers=AUTH).json
        assert len(listing['items']) == count


def test_committed_36_plus_68_and_regional_definitions_use_same_export_scope(client, mock_admin_auth, scope, monkeypatch):
    from scripts.plan_penang_fyp_reviews import build_plan
    from scripts.plan_penang_fyp_expansion import build_plan as expansion_plan
    from services.fyp_reviews import all_regional_reviews
    original = [{**row, 'id': path.rsplit('/', 1)[-1]} for plan in (build_plan(), expansion_plan())
                for path, row in plan['documents'].items() if 'rating' in row]
    assert len(original) == 104
    scope['penang'][:] = deepcopy(original)
    monkeypatch.setattr(routes, 'all_regional_reviews', all_regional_reviews)
    regional = all_regional_reviews()
    before = deepcopy(regional)
    result = report(client)
    assert result['counts']['feedback'] == 2 + 104 + len(regional)
    assert len(xlsx_details(client, 'system_summary')) == result['counts']['feedback']
    exported = {(row['reviewSource'], row['id']): row for row in result['records']}
    for source, rows in [('fyp_penang', original), ('fyp_regional', regional)]:
        for row in rows:
            actual = exported[source, row['id']]
            for key in ('destinationId', 'rating', 'comment', 'feedbackStatus', 'moderationStatus', 'submittedAt'):
                assert actual.get(key) == row.get(key)
    assert all_regional_reviews() == before
    assert scope['penang'] == original
    print('COMMITTED_DEFINITION_COUNTS', json.dumps({key: value['loaded']
          for key, value in result['feedbackSources']['sources'].items()}, sort_keys=True))


def test_stored_screening_is_not_replaced_by_new_report_timestamp(client, mock_admin_auth, scope):
    stored = {'screenedAt': '2000-01-01', 'risk': 'uncertain', 'policyVersion': 'legacy'}
    scope['genuine'][0]['screening'] = stored
    first, second = report(client), report(client)
    assert next(row for row in first['records'] if row['id'] == 'shared' and row['reviewSource'] == 'traveller')['screening'] == stored
    assert first['records'] == second['records']


def test_empty_sources_and_legacy_synthetic_provenance_are_not_misrepresented(client, mock_admin_auth, scope):
    scope['genuine'][0]['synthetic'] = True
    result = report(client)
    legacy = next(row for row in result['records'] if row['reviewSource'] == 'traveller' and row['id'] == 'shared')
    assert legacy['reviewProvenance'] == 'Synthetic FYP evaluation feedback'
    assert legacy['feedbackSource'] == 'Firestore feedback (synthetic)'
    for key in ('genuine', 'penang', 'regional'):
        scope[key].clear()
    result = report(client)
    assert result['counts']['feedback'] == 0 and not result['dataLimited']
    assert result['feedbackSources']['totalMatching'] == 0
    assert xlsx_details(client) == []


def test_genuine_source_outage_is_disclosed_without_losing_available_evaluation(client, mock_admin_auth, scope, monkeypatch):
    monkeypatch.setattr(routes, 'retrieveRecord', Mock(side_effect=RuntimeError('isolated outage')))
    # Only exercise the shared feedback reader: unrelated category errors still use existing report failure handling.
    with client.application.test_request_context():
        records, availability = routes._feedback_scope(for_report=True)
    assert len(records) == 119 and availability['partial']
    assert availability['sources']['traveller']['status'] == 'unavailable'


def test_sparse_review_is_feedback_formula_text_is_safe_and_pdf_scope_matches(client, mock_admin_auth, scope):
    scope['genuine'][:] = [{'id': 'sparse', 'comment': '=HYPERLINK("bad")'}]
    result = report(client)
    assert len(xlsx_details(client, 'system_summary')) == 120
    header, rows = csv_details(client, 'compact')
    sparse = next(row for row in rows if row[header.index('Feedback ID')] == 'sparse')
    assert sparse[header.index('Review Comment')].startswith("'=")
    pages, _ = export_pages(result, False)
    text = '\n'.join(pages)
    assert 'fyp_regional: available, 15 loaded' in text
    assert 'Evaluation Feedback' in text and 'Genuine Feedback' in text
    assert 'Synthetic FYP evaluation' in text


@pytest.mark.parametrize('role', ['traveller', 'operator'])
@pytest.mark.parametrize('path', ['/api/fr13/feedback?source=all', '/api/fr13/reports/summary',
                                  '/api/fr13/reports/export.xlsx', '/api/fr13/reports/export.csv',
                                  '/api/fr13/reports/export.pdf'])
def test_all_source_reports_remain_admin_only(client, request, role, path):
    request.getfixturevalue('mock_' + role + '_auth')
    assert client.get(path, headers=AUTH).status_code == 403
