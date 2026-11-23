"""Shared read-only Administrator record columns for HTML, XLSX, PDF and compact CSV."""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime


# Logical display fields, label, character width, cell type. No arbitrary source keys are appended.
SCHEMAS = {
    'users': [('reference', 'User ID', 34, 'text'), ('name', 'Full Name', 28, 'text'),
              ('email', 'Email', 32, 'text'), ('role', 'Role', 18, 'text'),
              ('status', 'Account Status', 18, 'text'), ('verificationStatus', 'Verification Status', 20, 'text'),
              ('createdAt', 'Created Date', 24, 'date')],
    'packages': [('reference', 'Package ID', 34, 'text'), ('name', 'Package Name', 42, 'text'),
                 ('destination', 'Destination', 28, 'text'), ('operator', 'Operator', 28, 'text'),
                 ('price', 'Adult / Base Price', 18, 'money'), ('currency', 'Currency', 12, 'text'),
                 ('approvalStatus', 'Approval Status', 18, 'text'), ('createdAt', 'Created Date', 24, 'date')],
    'campaigns': [('reference', 'Campaign ID', 34, 'text'), ('name', 'Campaign Name', 38, 'text'),
                  ('relatedPackage', 'Related Package', 34, 'text'),
                  ('promoCode', 'Promo Code', 20, 'text'), ('discountType', 'Discount Type', 18, 'text'),
                  ('discountValue', 'Discount Value', 18, 'number'), ('startDate', 'Start Date', 22, 'date'),
                  ('endDate', 'End Date', 22, 'date'), ('reviewStatus', 'Review Status', 18, 'text')],
    'feedback': [('reference', 'Feedback ID', 34, 'text'), ('destination', 'Destination', 28, 'text'),
                 ('destinationId', 'Destination ID', 34, 'text'),
                 ('rating', 'Rating', 10, 'number'), ('comment', 'Review Comment', 60, 'text'),
                 ('feedbackSource', 'Feedback Source', 28, 'text'), ('reviewProvenance', 'Review Provenance', 32, 'text'),
                 ('feedbackStatus', 'Feedback Status', 18, 'text'), ('moderationStatus', 'Moderation Status', 20, 'text'),
                 ('moderationCategory', 'Moderation Category', 20, 'text'),
                 ('submitted', 'Submitted Date', 24, 'date'), ('reviewedAt', 'Reviewed Date', 24, 'date')],
    'bookings': [('reference', 'Booking Reference', 42, 'text'), ('type', 'Booking Type', 16, 'text'),
                 ('name', 'Product Name', 42, 'text'), ('departureDate', 'Departure Date', 22, 'date'),
                 ('travellers', 'Traveller Count', 16, 'number'), ('amount', 'Amount', 18, 'money'),
                 ('currency', 'Currency', 12, 'text'), ('payment', 'Payment Status', 18, 'text'),
                 ('booking_state', 'Booking / Record Status', 22, 'text'),
                 ('createdAt', 'Created Date', 24, 'date')],
    'payments': [('reference', 'Order Reference', 42, 'text'), ('type', 'Product Type', 16, 'text'),
                 ('name', 'Product Name', 42, 'text'), ('amount', 'Amount', 18, 'money'),
                 ('currency', 'Currency', 12, 'text'), ('payment', 'Payment Status', 18, 'text'),
                 ('testMode', 'Test Mode', 12, 'text'), ('createdAt', 'Created Date', 24, 'date')],
    'other': [('reference', 'Record ID', 38, 'text'), ('name', 'Name', 45, 'text'),
              ('status', 'Record Status', 22, 'text'), ('createdAt', 'Created Date', 24, 'date')],
}


def _first(record, *paths):
    for path in paths:
        value = record
        for key in path.split('.'):
            value = value.get(key) if isinstance(value, dict) else None
        if value is not None and value != '' and value != '-':
            return value
    return None


def _value(record, field, kind):
    paths = {
        'reference': ('bookingReference', 'id', 'uid', 'orderReference', 'transactionReference') if kind == 'bookings'
                     else ('id', 'uid', 'orderReference', 'transactionReference'),
        'name': {'users': ('name', 'fullName'), 'packages': ('title', 'packageTitle'),
                 'campaigns': ('campaignTitle',)}.get(kind, (
                     'productTitle', 'packageTitle', 'packageSnapshot.title', 'packageSnapshot.packageTitle',
                     'hotelName', 'quoteSnapshot.name', 'quoteSnapshot.hotel.name', 'selectedHotel.name',
                     'acceptedPrebookSnapshot.name', 'orderTitle', 'name', 'title')),
        'type': ('productType', 'bookingType', 'quoteType'),
        'payment': ('paymentStatus', 'status'), 'price': ('adultPrice', 'price'),
        'operator': ('operatorName', 'operatorId'),
        'destination': ('destination', 'destinationName', 'destinationId'),
        'travellers': ('travellerCount', 'groupSize', 'participants.totalTravellers', 'participants.total'),
        'departureDate': ('departureDate', 'selectedDepartureDate', 'checkInDate', 'stayCriteria.checkIn'),
        'relatedPackage': ('packageTitle', 'packageId', 'packageIds'),
        'submitted': ('submittedAt', 'createdAt', 'timestamp', 'date'),
        'booking_state': ('bookingStatus', 'status'),
    }
    if kind == 'bookings':
        paths.update(amount=('amount', 'hotelCost'), currency=('currency', 'hotelCurrency'))
    value = _first(record, *paths.get(field, (field,)))
    if field == 'testMode' and isinstance(value, bool):
        return 'Yes' if value else 'No'
    return value


def record_table(kind, records):
    columns = list(SCHEMAS[kind])
    # Only a known homogeneous MYR scope permits the compact currency-specific heading.
    if kind == 'payments' and records and all(item.get('currency') == 'MYR' for item in records):
        columns = [(key, 'Amount (MYR)' if key == 'amount' else label, width, cell_type)
                   for key, label, width, cell_type in columns if key != 'currency']
    # Optional booking details are absent from some supported legacy records.
    optional = {'departureDate', 'travellers', 'type', 'payment', 'booking_state'} if kind == 'bookings' else set()
    columns = [col for col in columns if col[0] not in optional
               or any(_value(record, col[0], kind) is not None for record in records)]
    return columns, [tuple(_value(record, key, kind) for key, *_ in columns) for record in records]


def display_value(value, kind='text'):
    """Format a view cell, without changing the underlying record or money value."""
    if value is None or value == '':
        return '—'
    if kind == 'date':
        if isinstance(value, str):
            try:
                value = date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value.replace('Z', '+00:00'))
            except ValueError:
                try:
                    value = parsedate_to_datetime(value)  # Flask JSON's historical HTTP-date representation.
                except (ValueError, TypeError, OverflowError):
                    return 'Not Available'
        if isinstance(value, datetime):
            if value.tzinfo:
                return value.astimezone(timezone.utc).strftime('%d %b %Y %H:%M UTC')
            return value.strftime('%d %b %Y %H:%M')
        return value.strftime('%d %b %Y') if isinstance(value, date) else 'Not Available'
    if kind in {'money', 'number'}:
        if isinstance(value, (dict, list, bool)):
            return 'Not Available'
        try:
            number = Decimal(str(value))
            if not number.is_finite() or number < 0:
                return 'Not Available'
            if abs(number.adjusted()) > 20:
                return str(number)  # Keep extreme legacy values bounded without inventing zero.
            return f'{number:,.2f}' if kind == 'money' else format(number, 'f')
        except (InvalidOperation, ValueError):
            return 'Not Available'
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return ', '.join(value) or '—'
    if isinstance(value, (dict, list)):
        return 'Not Available'
    return str(value)


def display_table(kind, records):
    columns, rows = record_table(kind, records)
    return [label for _, label, *_ in columns], [
        [display_value(value, column[3]) for value, column in zip(row, columns)] for row in rows]
