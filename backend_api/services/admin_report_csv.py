"""Readable CSV presentation of the existing, sanitized FR13 report payload."""
import csv
import io
import json
import re


REPORT_TITLES = {
    'system_summary': 'TravelMate Administrator System Summary',
    'users': 'TravelMate User Accounts Report',
    'packages': 'TravelMate Tourism Packages Report',
    'campaigns': 'TravelMate Promotional Campaigns Report',
    'feedback': 'TravelMate Traveller Feedback Report',
    'bookings': 'TravelMate Booking Records Report',
    'payments': 'TravelMate Payment Records Report',
}

# Each entry refers to an existing payload field, not a derived database value.
COMMON = [('id', 'Record ID'), ('createdAt', 'Created Date'), ('updatedAt', 'Updated Date')]
COLUMNS = {
    'users': [('id', 'User ID'), ('uid', 'Firebase User ID'), ('name', 'Full Name'),
              ('fullName', 'Full Name (Alternate Field)'), ('email', 'Email'), ('role', 'Role'),
              ('status', 'Account Status'), ('verificationStatus', 'Verification Status'),
              ('createdAt', 'Created Date'), ('updatedAt', 'Updated Date')],
    'packages': [('id', 'Package ID'), ('title', 'Package Name'), ('packageTitle', 'Package Name (Alternate Field)'),
                 ('destination', 'Destination'), ('operatorId', 'Operator ID'), ('pricingModel', 'Pricing Model'),
                 ('adultPrice', 'Adult / Base Price'), ('childPrice', 'Child Price'), ('currency', 'Currency'),
                 ('status', 'Lifecycle Status'), ('approvalStatus', 'Approval Status'),
                 ('createdAt', 'Created Date'), ('updatedAt', 'Updated Date')],
    'campaigns': [('id', 'Campaign ID'), ('campaignTitle', 'Campaign Name'), ('operatorId', 'Operator ID'),
                  ('packageId', 'Package ID'), ('promoCode', 'Promo Code'), ('discountType', 'Discount Type'),
                  ('discountValue', 'Discount Value'), ('startDate', 'Start Date'), ('endDate', 'End Date'),
                  ('reviewStatus', 'Review Status'), ('campaignStatus', 'Campaign Status'),
                  ('createdAt', 'Created Date'), ('updatedAt', 'Updated Date')],
    'feedback': [('id', 'Feedback ID'), ('destinationId', 'Destination ID'), ('travellerId', 'Traveller ID'),
                 ('rating', 'Rating'), ('comment', 'Review Comment'), ('feedbackStatus', 'Feedback Status'),
                 ('moderationStatus', 'Moderation Status'), ('submittedAt', 'Submitted Date'),
                 ('createdAt', 'Created Date'), ('updatedAt', 'Updated Date')],
    'bookings': [('id', 'Record ID'), ('bookingReference', 'Booking Reference'), ('bookingType', 'Booking Type'),
                 ('productType', 'Product Type'), ('productTitle', 'Product Name'), ('packageTitle', 'Package Name'),
                 ('hotelName', 'Hotel Name'), ('travellerId', 'Traveller ID'), ('operatorId', 'Operator ID'),
                 ('departureDate', 'Departure Date'), ('travellerCount', 'Traveller Count'),
                 ('amount', 'Amount'), ('currency', 'Currency'), ('paymentStatus', 'Payment Status'),
                 ('status', 'Record Status'), ('testMode', 'Test Mode'),
                 ('createdAt', 'Created Date'), ('updatedAt', 'Updated Date')],
    'payments': [('id', 'Payment / Order Reference'), ('productType', 'Product Type'), ('productTitle', 'Product Name'),
                 ('travellerId', 'Traveller ID'), ('operatorId', 'Operator ID'), ('amount', 'Amount'),
                 ('currency', 'Currency'), ('paymentStatus', 'Payment Status'), ('status', 'Order / Record Status'),
                 ('isPaid', 'Verified Paid State'), ('testMode', 'Test Mode'), ('provider', 'Payment Provider'),
                 ('transactionReference', 'Transaction Reference'), ('createdAt', 'Created Date'),
                 ('updatedAt', 'Updated Date')],
}
COLUMNS['system_summary'] = COMMON + [('name', 'Full Name'), ('email', 'Email'), ('role', 'Role'),
    ('title', 'Package Name'), ('campaignTitle', 'Campaign Name'), ('comment', 'Review Comment'),
    ('rating', 'Rating'), ('hotelName', 'Hotel Name'), ('productType', 'Product Type'),
    ('productTitle', 'Product Name'), ('amount', 'Amount'), ('currency', 'Currency'),
    ('status', 'Record Status'), ('paymentStatus', 'Payment Status'), ('testMode', 'Test Mode')]

COUNT_LABELS = dict(zip(
    ('users', 'tourism_packages', 'promotional_campaigns', 'feedback', 'hotel_bookings',
     'package_bookings', 'payment_records', 'checkout_orders', 'filtered_records'),
    ('User Accounts', 'Tourism Packages', 'Promotional Campaigns', 'Feedback Records', 'Hotel Bookings',
     'Package Booking Records', 'Payment Records', 'Checkout Orders', 'Matching Detailed Records')))
SECTION_LABELS = {'users': 'User Accounts', 'packages': 'Tourism Packages',
                  'campaigns': 'Promotional Campaigns', 'feedback': 'Traveller Feedback',
                  'payments': 'Payment Records'}
METRIC_LABELS = {
    'total': 'Total Records', 'paid': 'Paid Records', 'pending': 'Pending Records',
    'failed': 'Failed Records', 'expired': 'Expired Records', 'testMode': 'Test Mode Records',
    'totalPaidRevenue': 'Recorded Paid Total (MYR, All Recorded Modes)',
    'testPaidTotal': 'Included Test Mode Paid Total (MYR)',
    'unpricedPaidOrders': 'Paid MYR Records Without a Usable Amount',
    'excludedCurrencyPaidOrders': 'Paid Records Excluded From MYR Total (Other / Unknown Currency)',
}


def _label(key):
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', key).replace('_', ' ').title()


def _cell(value):
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, default=str)
    else:
        value = str(value)
    # CSV has no cell types. Neutralize spreadsheet formulas, including control-prefixed text.
    if value.startswith(('\t', '\r', '\n')) or value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def readable_csv(report):
    """Return an Excel-friendly UTF-8 CSV; callers retain auth and sanitization."""
    criteria = report.get('criteria') or {}
    report_type = criteria.get('reportType') or 'system_summary'
    records = report.get('records') or []
    columns = list(COLUMNS[report_type])
    known = {key for key, _ in columns}
    # Preserve every additional sanitized field without letting it reorder the core schema.
    extra = sorted({key for item in records for key in item} - known)
    columns.extend((key, f'{_label(key)} [{key}]') for key in extra)
    width = max(2, len(columns))
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\r\n')

    def row(values=()):
        writer.writerow([_cell(value) for value in values] + [''] * (width - len(values)))

    row([REPORT_TITLES[report_type]])
    row(['REPORT INFORMATION'])
    for label, value in (
        ('Generated At', report.get('generatedAt')),
        ('Report Type', report_type.replace('_', ' ').title()),
        ('Start Date', criteria.get('startDate')), ('End Date', criteria.get('endDate')),
        ('Applied Filter', criteria.get('filter')),
        ('Reporting Period', 'Dates as specified above; blank bounds mean no date restriction.'),
        ('Source Scope', 'Partial source data loaded; this is not the complete system dataset.'
         if report.get('dataLimited') else 'Loaded source scope; a source loading cap applies.'),
        ('Source Record Limit (Per Category)', report.get('recordLimit')),
        ('Detailed Export Limited', report.get('recordsLimited', False)),
        ('Detailed Record Limit', report.get('recordDisplayLimit')),
        ('Records Exported', len(records)),
        ('Summary Scope', 'Summary counts cover the filtered loaded sources; detailed rows may be capped.'),
        ('Financial Disclosure', 'Recorded paid totals include test-mode records. Test totals are included, not additional income. No real settlement or supplier reservation is implied.'),
        ('Category Disclosure', 'Active campaigns are a subset of approved campaigns; feedback moderation categories may overlap.'),
        ('Data Conventions', 'Blank means missing or null. Dates retain source timezone/precision. Nested values use JSON. Import identifiers as Text to preserve leading zeros and long IDs in Excel.'),
    ):
        row([label, value])
    row()
    row(['REPORT SUMMARY'])
    row(['Metric', 'Value'])
    for key, value in (report.get('counts') or {}).items():
        row([f'Loaded Scope / {COUNT_LABELS.get(key, _label(key))}', value])
    for section, metrics in (report.get('summary') or {}).items():
        for key, value in metrics.items():
            row([f'{SECTION_LABELS.get(section, _label(section))} / {METRIC_LABELS.get(key, _label(key))}', value])
    row()
    row(['DETAILED RECORDS'])
    if not records:
        row(['No records matched the selected criteria'])
    row([label for _, label in columns])
    for item in records:
        row([item.get(key) for key, _ in columns])
    # BOM permits Excel to detect UTF-8; no terminator record is appended to the data table.
    return '\ufeff' + output.getvalue()
