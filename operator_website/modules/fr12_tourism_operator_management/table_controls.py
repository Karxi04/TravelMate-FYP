"""Deterministic sorting of the portal's complete loaded record set."""
from datetime import date, datetime, timezone
from math import isfinite
from portal_commerce import payment_label


CATALOG_COLUMNS = {'title': 'Package', 'destination': 'Destination', 'duration': 'Duration',
                   'price': 'Price', 'status': 'Status', 'updated': 'Updated'}
BOOKING_COLUMNS = {'reference': 'Order Reference', 'package': 'Package Excursion', 'departure': 'Departure',
                   'party': 'Party Breakdown', 'amount': 'Amount', 'payment': 'Payment Status',
                   'fulfillment': 'In-App Fulfillment', 'supplier': 'Supplier Status', 'created': 'Created'}


def number(value):
    try:
        parsed = float(value)
        return parsed if not isinstance(value, bool) and isfinite(parsed) and parsed >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def departure_date(value):
    try:
        text = str(value).strip()
        parsed = date.fromisoformat(text).isoformat()
        return parsed if text == parsed else None
    except (ValueError, TypeError):
        return None


def instant(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc).timestamp() if parsed.tzinfo is None else parsed.timestamp()
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def sort_records(items, column, direction, catalog=False):
    fields = ({'title': ('title', 'packageTitle'), 'destination': ('destination', 'destinationName'),
               'duration': ('durationDays',), 'price': ('adultPrice', 'price'), 'status': ('approvalStatus',),
               'updated': ('updatedAt', 'createdAt')} if catalog else
              {'reference': ('orderReference', 'id'), 'package': ('packageTitle',), 'departure': ('departureDate',),
               'party': ('groupSize',), 'amount': ('amount', 'groupTotal'), 'payment': ('paymentStatus',),
               'fulfillment': ('fulfillmentStatus',), 'supplier': ('supplierReservationStatus',), 'created': ('createdAt',)})
    def value(item):
        if column == 'payment':
            return payment_label(item.get('paymentStatus'), item.get('orderStatus')).casefold() if item.get('paymentStatus') or item.get('orderStatus') else None
        raw = next((item.get(key) for key in fields[column] if item.get(key) not in (None, '')), None)
        if column in {'duration', 'price', 'party', 'amount'}:
            return number(raw)
        if column == 'departure':
            return departure_date(raw)
        if column in {'updated', 'created'}:
            return instant(raw)
        text = str(raw).strip() if raw is not None else ''
        return text.casefold() if text else None
    ordered = sorted(items, key=lambda item: (str(item.get('id') or item.get('orderReference') or '').casefold(), str(item.get('id') or item.get('orderReference') or '')))
    known = [item for item in ordered if value(item) is not None]
    missing = [item for item in ordered if value(item) is None]
    return sorted(known, key=value, reverse=direction == 'desc') + missing
