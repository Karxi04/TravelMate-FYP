"""Explicit chat date ranges; calendar dates take priority over a duration hint."""
import re
from datetime import date, datetime, timezone, timedelta

_MONTHS = {name: index for index, names in enumerate([
    ('jan', 'january'), ('feb', 'february'), ('mar', 'march'), ('apr', 'april'),
    ('may',), ('jun', 'june'), ('jul', 'july'), ('aug', 'august'),
    ('sep', 'sept', 'september'), ('oct', 'october'), ('nov', 'november'), ('dec', 'december'),
], start=1) for name in names}
_MONTH = '|'.join(sorted(_MONTHS, key=len, reverse=True))
_POINT = re.compile(r'\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{4})?|\d{1,2}(?:st|nd|rd|th)?\s+(?:' + _MONTH + r')\b(?:\s*,?\s*\d{4})?)', re.I)
_SEPARATOR = re.compile(r'^\s*(?:until|till|to|through|[-\u2013\u2014])\s*$', re.I)
_SHORT_RANGE = re.compile(r'\b(\d{1,2})\s*(?:to|until|[-\u2013\u2014])\s*(\d{1,2})\s+(' + _MONTH + r')\b(?:\s+(\d{4}))?', re.I)


def malaysian_today():
    return datetime.now(timezone(timedelta(hours=8))).date()


def _parts(value):
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        year, month, day = map(int, value.split('-'))
        return day, month, year
    if '/' in value:
        parts = list(map(int, value.split('/')))
        day, month = parts[:2]
        if day <= 12 and month <= 12 and day != month:
            raise ValueError('Please write month names or ISO dates so the date order is unambiguous.')
        return day, month, parts[2] if len(parts) == 3 else None
    match = re.fullmatch(r'(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)(?:\s*,?\s*(\d{4}))?', value, re.I)
    if not match:
        raise ValueError('Please give both travel dates, for example 12 Dec 2026 to 16 Dec 2026.')
    return int(match[1]), _MONTHS[match[2].lower()], int(match[3]) if match[3] else None


def parse_date_range(message, today=None):
    """Return ISO start/end, None for no range, or a specific clarification error."""
    message = _SHORT_RANGE.sub(lambda m: f'{m[1]} {m[3]} {m[4] or ""} to {m[2]} {m[3]} {m[4] or ""}', message)
    points = list(_POINT.finditer(message))
    if len(points) < 2:
        if points and re.search(r'\b(?:until|till|through|to)\b', message[points[0].end():], re.I):
            raise ValueError('Please provide the end date as well as the start date.')
        return None
    if len(points) != 2 or not _SEPARATOR.fullmatch(message[points[0].end():points[1].start()]):
        raise ValueError('Which two dates should I use? Write one start date and one end date joined by to or until.')
    first = _parts(points[0].group()); last = _parts(points[1].group())
    today = today or malaysian_today()
    year = first[2] or last[2] or today.year
    if first[2] is None and last[2] is None and (first[1], first[0]) < (today.month, today.day):
        year += 1
    start_year = year
    if first[2] is None and last[2] is not None and first[1] > last[1]:
        start_year -= 1
    end_year = last[2] or (start_year + (1 if last[1] < first[1] else 0))
    try:
        start = date(start_year, first[1], first[0]); end = date(end_year, last[1], last[0])
    except ValueError:
        raise ValueError('Those calendar dates are invalid. Please provide a valid start and end date.') from None
    if end < start:
        raise ValueError('The end date is before the start date. Which date range did you intend?')
    if start < today:
        raise ValueError('Those dates are in the past. Please choose a future travel date range.')
    if (end - start).days + 1 > 14:
        raise ValueError('The chat planner supports up to 14 calendar days. Please choose a shorter date range.')
    return start.isoformat(), end.isoformat()
