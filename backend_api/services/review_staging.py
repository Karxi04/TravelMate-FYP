"""Opt-in local moderation overlay. Never writes production feedback or fixture sources."""
import json
import os
import sqlite3
from pathlib import Path

from services.review_service import ReviewConflict, review_revision


def staging_path():
    raw = os.getenv('FYP_REVIEW_STAGING_PATH', '').strip()
    if not raw:
        return None
    path = Path(raw)
    boundary = Path('D:/workspace').resolve()
    resolved = path.resolve()
    if not path.is_absolute() or not resolved.is_relative_to(boundary) or resolved.suffix != '.sqlite3':
        raise ValueError('Review staging must be a dedicated .sqlite3 file under D:/workspace.')
    return resolved


def _read_state():
    path = staging_path()
    if path is None or not path.exists():
        return {}
    with sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True) as db:
        return {identity: json.loads(value) for identity, value in db.execute('SELECT id, data FROM moderation')}


def overlay_rows(rows):
    states = _read_state()
    return [{**row, **states.get(row['id'], {}).get('updates', {})} for row in rows]


def history(record):
    state = _read_state().get(record['id'], {})
    return list(reversed(state.get('history', []))) or [record.get('moderationDecision', {})]


def moderate(expected, updates, source):
    path = staging_path()
    if path is None:
        raise ReviewConflict('This fixture is read-only. Configure an approved local staging overlay first.')
    # Exact immutable source plus CAS prevents stale cross-admin decisions.
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=5) as db:
        db.execute('CREATE TABLE IF NOT EXISTS moderation (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT data FROM moderation WHERE id=?', (source['id'],)).fetchone()
        state = json.loads(row[0]) if row else {}
        current = {**source, **state.get('updates', {})}
        if review_revision(current) != review_revision(expected):
            raise ReviewConflict('This review changed. Refresh and try again.')
        events = state.get('history') or [source.get('moderationDecision', {})]
        events.append({**updates['moderationDecision'], 'screening': source.get('screening', {})})
        state = {'updates': {**state.get('updates', {}), **updates}, 'history': events}
        db.execute('INSERT OR REPLACE INTO moderation VALUES (?,?)', (source['id'], json.dumps(state)))
        return {**current, **updates}
