"""Opt-in local moderation overlay. Never writes production feedback or fixture sources."""
import json
import os
import sqlite3
from hashlib import sha256
from pathlib import Path

from services.review_service import ReviewConflict, review_revision

FIELDS = {'moderationStatus','feedbackStatus','updatedAt','reviewComment','reviewedBy','reviewedAt',
          'removedBy','removedAt','moderationDecision'}


class ReviewStagingUnavailable(RuntimeError):
    pass


def _unavailable():
    return ReviewStagingUnavailable('Local review moderation storage is unavailable. No review changes were applied.')


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
    try:
        path = staging_path()
    except ValueError as exc:
        raise _unavailable() from exc
    if path is None:
        return {}
    try:
        with sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True) as db:
            states = {identity: json.loads(value) for identity, value in db.execute('SELECT id, data FROM moderation')}
        for state in states.values():
            if (not isinstance(state,dict) or not isinstance(state.get('updates'),dict)
                    or not set(state['updates']) <= FIELDS or not isinstance(state.get('history'),list)):
                raise ValueError('Invalid moderation overlay.')
        return states
    except (sqlite3.Error,OSError,ValueError) as exc:
        raise _unavailable() from exc


def initialize():
    """Owner-controlled setup only; never called by GET or moderation routes."""
    path = staging_path()
    if path is None:
        raise ValueError('Choose a dedicated local review staging path first.')
    path.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(path) as db:
        tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if tables-{'moderation'}:
            raise ValueError('Use a dedicated moderation database, not another application database.')
        db.execute('CREATE TABLE IF NOT EXISTS moderation (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
    if os.name != 'nt':
        path.chmod(0o600)
    _read_state()


def ready():
    try:
        path=staging_path()
        if path is None or not os.access(path,os.W_OK):
            return False
        _read_state()
        return True
    except (ValueError,ReviewStagingUnavailable):
        return False


def evidence_revision():
    return sha256(json.dumps(_read_state(),sort_keys=True,separators=(',',':')).encode()).hexdigest()


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
    if (source.get('synthetic') is not True or expected.get('synthetic') is not True
            or source.get('id') != expected.get('id') or not set(updates) <= FIELDS):
        raise ValueError('Only moderation fields of an existing synthetic review may be staged.')
    # Exact immutable source plus CAS prevents stale cross-admin decisions.
    try:
        with sqlite3.connect(f'{path.as_uri()}?mode=rw',uri=True,timeout=5) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM moderation WHERE id=?', (source['id'],)).fetchone()
            state = json.loads(row[0]) if row else {}
            if not isinstance(state,dict) or not set(state.get('updates',{})) <= FIELDS:
                raise _unavailable()
            current = {**source, **state.get('updates', {})}
            if review_revision(current) != review_revision(expected):
                raise ReviewConflict('This review changed. Refresh and try again.')
            events = state.get('history') or [source.get('moderationDecision', {})]
            events.append({**updates['moderationDecision'], 'screening': source.get('screening', {})})
            state = {'updates': {**state.get('updates', {}), **updates}, 'history': events}
            db.execute('INSERT OR REPLACE INTO moderation VALUES (?,?)', (source['id'], json.dumps(state)))
            return {**current, **updates}
    except (sqlite3.Error,OSError) as exc:
        raise _unavailable() from exc
