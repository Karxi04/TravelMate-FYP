"""Malaysia calendar boundaries for campaign publication and checkout."""
from datetime import date, datetime, timedelta, timezone


def malaysia_today(now=None):
    if isinstance(now, str):
        now = datetime.fromisoformat(now.replace('Z', '+00:00'))
    if isinstance(now, datetime):
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone(timedelta(hours=8)))
        return now.astimezone(timezone(timedelta(hours=8))).date()
    return now if isinstance(now, date) else datetime.now(timezone(timedelta(hours=8))).date()


def campaign_schedule_error(data, *, new=False, previous=None, publishing=False, now=None):
    try:
        start = date.fromisoformat(data.get('startDate', ''))
        end = date.fromisoformat(data.get('endDate', ''))
    except (ValueError, TypeError):
        return 'Enter valid campaign start and end dates (YYYY-MM-DD).'
    if end < start:
        return 'Campaign end date must not precede its start date.'
    today = malaysia_today(now)
    changed = previous is not None and data.get('startDate') != previous.get('startDate')
    if (new or changed) and start < today:
        return 'Campaign start date must be today or later in Malaysia.'
    if publishing and end < today:
        return 'An expired campaign cannot be submitted or approved.'
    return None
