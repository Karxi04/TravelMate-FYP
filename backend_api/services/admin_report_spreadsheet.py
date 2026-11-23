"""Compact administrator views; existing FR13 payload owns all business values."""
import csv
import io
import math
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from services.admin_report_csv import REPORT_TITLES, COUNT_LABELS, SECTION_LABELS, METRIC_LABELS, _cell, _label, feedback_scope_text


from admin_report_records import SCHEMAS, _first, _value, record_table


def summary_table(report):
    rows = [('Loaded Scope', COUNT_LABELS.get(key, _label(key)), value)
            for key, value in (report.get('counts') or {}).items()]
    rows.extend((SECTION_LABELS.get(section, _label(section)), METRIC_LABELS.get(key, _label(key)), value)
                for section, metrics in (report.get('summary') or {}).items() for key, value in metrics.items())
    columns = [('category', 'Category', 30, 'text'), ('metric', 'Metric', 64, 'text'),
               ('value', 'Value', 28, 'number')]
    return columns, rows


def metadata(report):
    criteria = report.get('criteria') or {}
    scope = ('Partial source dataset. ' if report.get('dataLimited') else 'Loaded source scope. ')
    scope += (f"Other categories: up to {report.get('recordLimit', 500)} records per source; 200 non-feedback detail rows."
              if report.get('feedbackSources') else
              f"Up to {report.get('recordLimit', 500)} records per source; {report.get('recordDisplayLimit', 200)} detailed rows per export.")
    if report.get('recordsLimited'):
        scope += ' Detailed export is incomplete.'
    if report.get('feedbackSources'):
        scope += ' ' + feedback_scope_text(report)
    return [
        ('Generated At', _date_text(report.get('generatedAt'))),
        ('Report Type', (criteria.get('reportType') or 'system_summary').replace('_', ' ').title()),
        ('Reporting Period', f"{criteria.get('startDate') or 'No start-date restriction'} to {criteria.get('endDate') or 'No end-date restriction'}"),
        ('Applied Filter', criteria.get('filter') or 'None'),
        ('Records', f"{(report.get('counts') or {}).get('filtered_records', 'Not provided')} matching; {len(report.get('records') or [])} detailed records exported"),
        ('Source / Limits', scope),
        ('Important', 'Test-mode payment records are not live income. Payment does not confirm a supplier reservation. Aware timestamps are shown in UTC; other dates stay as recorded.'),
        ('Full Data', 'Advanced CSV retains all sanitized fields. Summary counts cover loaded sources and may exceed detailed rows. Active campaigns and approved campaigns overlap; feedback categories may overlap.'),
    ]


def compact_csv(report):
    kind = (report.get('criteria') or {}).get('reportType', 'system_summary')
    columns, rows = summary_table(report) if kind == 'system_summary' else record_table(kind, report.get('records') or [])
    width = len(columns) + 1
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\r\n')
    def row(values):
        writer.writerow([_cell(value) for value in values] + [''] * (width - len(values)))
    row([REPORT_TITLES[kind]])
    for values in metadata(report):
        row(values)
    row([])
    row(['No.'] + [column[1] for column in columns])
    for index, values in enumerate(rows, 1):
        row([index, *[_date_text(value) if col[3] == 'date' else value for col, value in zip(columns, values)]])
    return '\ufeff' + output.getvalue()


def _record_category(record):
    if record.get('reportCategory') == 'feedback':
        return 'feedback'
    # Presentation grouping only. Ambiguous rows stay in Other Records, never guessed or dropped.
    matches = []
    if record.get('role'):
        matches.append('users')
    if record.get('approvalStatus') is not None and _first(record, 'title', 'packageTitle'):
        matches.append('packages')
    if record.get('campaignTitle'):
        matches.append('campaigns')
    if record.get('feedbackStatus') or (record.get('rating') is not None and record.get('comment')):
        matches.append('feedback')
    if record.get('productType'):
        matches.append('payments')
    elif record.get('hotelName') or record.get('selectedHotel') or record.get('stayCriteria'):
        matches.append('bookings')
    return matches[0] if len(matches) == 1 else 'other'


def _timestamp(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    if not isinstance(value, str):
        return value
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return date.astimezone(timezone.utc).replace(tzinfo=None) if date.tzinfo else value
    except ValueError:
        return value


def _date_text(value):
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.isoformat()
    parsed = _timestamp(value)
    return parsed.isoformat() + 'Z' if isinstance(parsed, datetime) else value


def export_xlsx(report, target):
    import xlsxwriter
    workbook = xlsxwriter.Workbook(target, {'in_memory': True, 'strings_to_formulas': False,
                                           'strings_to_urls': False, 'strings_to_numbers': False})
    workbook.set_properties({'title': REPORT_TITLES[report['criteria']['reportType']], 'company': 'TravelMate'})
    base = {'font_name': 'Calibri', 'font_size': 11, 'font_color': '#203745', 'valign': 'top',
            'text_wrap': True, 'border': 1, 'border_color': '#E1E5E7'}
    title = workbook.add_format({**base, 'bold': True, 'font_size': 18, 'bg_color': '#F5A7A9', 'valign': 'vcenter'})
    meta_label = workbook.add_format({**base, 'bold': True, 'bg_color': '#F9D1D0', 'valign': 'vcenter'})
    meta_value = workbook.add_format({**base, 'bg_color': '#F9D1D0', 'valign': 'vcenter'})
    heading = workbook.add_format({**base, 'bold': True, 'bg_color': '#A0F2AA', 'valign': 'vcenter'})
    sequence = workbook.add_format({**base, 'bold': True, 'bg_color': '#A9F0EE', 'align': 'center', 'valign': 'vcenter'})
    formats = {}
    for parity in (0, 1):
        for kind in ('text', 'number', 'money', 'integer', 'date'):
            fmt = {**base, 'bg_color': '#FFFFFF' if parity == 0 else '#F4F8F8'}
            if kind in {'number', 'money', 'integer'}:
                fmt.update(num_format='#,##0' if kind == 'integer' else '#,##0.00########', align='right')
            if kind == 'date':
                fmt['num_format'] = 'dd mmm yyyy hh:mm:ss.000'
            formats[parity, kind] = workbook.add_format(fmt)

    def write(sheet, row, col, value, fmt, kind='text'):
        if value is None:
            sheet.write_blank(row, col, None, fmt)
            return
        if kind == 'date':
            value = _timestamp(value)
        if isinstance(value, datetime):
            sheet.write_datetime(row, col, value, fmt)
        elif kind in {'number', 'money'} and not isinstance(value, bool):
            try:
                number = Decimal(str(value))
                if number.is_finite() and len(number.normalize().as_tuple().digits) <= 15:
                    sheet.write_number(row, col, float(number), fmt)
                    return
            except InvalidOperation:
                pass
            write(sheet, row, col, str(value), fmt)
        else:
            text = str(value)
            if len(text) > 32767:
                raise ValueError('A report cell exceeds the Excel text limit. Use Advanced CSV for complete data.')
            sheet.write_string(row, col, text, fmt)

    def sheet(name, columns, rows, subtitle=None):
        ws = workbook.add_worksheet(name)
        last_col = len(columns)
        ws.hide_gridlines(2)
        ws.set_zoom(80)
        ws.set_column(0, 0, 7)
        for index, (_, _, width, _) in enumerate(columns, 1):
            ws.set_column(index, index, width)
        ws.merge_range(0, 0, 0, last_col, '', title)
        write(ws, 0, 0, 'TRAVELMATE  |  ' + (subtitle or REPORT_TITLES[report['criteria']['reportType']].replace('TravelMate ', '')).upper(), title)
        ws.set_row(0, 42)
        split = 1 if last_col == 3 else 2
        for r, (label, value) in enumerate(metadata(report), 2):
            if label == 'Records':
                value += f'; {len(rows)} rows on this sheet'
            ws.merge_range(r, 0, r, split, '', meta_label)
            ws.merge_range(r, split + 1, r, last_col, '', meta_value)
            write(ws, r, 0, label, meta_label)
            if isinstance(_timestamp(value), datetime):
                value = _timestamp(value).strftime('%d %b %Y %H:%M:%S UTC')
            write(ws, r, split + 1, value, meta_value)
            available = sum(col[2] for col in columns[split:])
            ws.set_row(r, max(26, 17 * math.ceil(len(str(value)) / max(available, 20)) + 10))
        header_row = 11
        for c, text in enumerate(['No.'] + [column[1] for column in columns]):
            write(ws, header_row, c, text.upper(), heading)
        ws.set_row(header_row, 34)
        for r, values in enumerate(rows, header_row + 1):
            ws.write_number(r, 0, r - header_row, sequence)
            lines = 1
            for c, (value, (_, _, width, kind)) in enumerate(zip(values, columns), 1):
                format_kind = kind
                if kind == 'number' and value is not None:
                    try:
                        number = Decimal(str(value))
                        if number.is_finite() and number == number.to_integral():
                            format_kind = 'integer'
                    except InvalidOperation:
                        pass
                write(ws, r, c, value, formats[(r - header_row - 1) % 2, format_kind], kind)
                lines = max(lines, sum(max(1, math.ceil(len(line) / max(width - 3, 1)))
                                       for line in str(value or '').split('\n')))
            ws.set_row(r, min(409, max(32, 17 * lines + 10)))
        ws.freeze_panes(header_row + 1, 1)
        ws.autofilter(header_row, 0, header_row + len(rows), last_col)
        ws.set_landscape()
        ws.set_paper(9)
        ws.fit_to_pages(1, 0)
        ws.repeat_rows(header_row)
        ws.set_footer('&LTravelMate&RPage &P of &N')
        ws.print_area(0, 0, header_row + len(rows), last_col)

    kind = report['criteria']['reportType']
    records = report.get('records') or []
    if kind == 'system_summary':
        sheet('System Overview', *summary_table(report))
        groups = {}
        for record in records:
            groups.setdefault(_record_category(record), []).append(record)
        for category, items in groups.items():
            name = {'users': 'User Accounts', 'packages': 'Tourism Packages', 'campaigns': 'Campaigns',
                    'feedback': 'Feedback', 'payments': 'Payment Records', 'bookings': 'Booking Records',
                    'other': 'Other Records'}[category]
            sheet(name, *record_table(category, items), subtitle=name)
    else:
        sheet(kind.replace('_', ' ').title(), *record_table(kind, records))
        sheet('Report Summary', *summary_table(report), subtitle='Report Summary')
    workbook.close()
