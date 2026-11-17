"""Public geographic facts and bounded lookup; no Traveller records or provider keys."""
from collections import defaultdict
from difflib import SequenceMatcher, get_close_matches
from functools import lru_cache
import json
import math
from pathlib import Path
import re
from threading import Lock
from time import monotonic
import unicodedata

from services.malaysia_boundary import coordinate_state

GENERIC_AREA_WORDS = {'bukit', 'kuala', 'sungai', 'tanjung', 'kampung', 'kampong', 'taman', 'bandar', 'pulau', 'kota'}


def text(value):
    value = unicodedata.normalize('NFKD', str(value or ''))
    return re.sub(r'[^a-z0-9]+', ' ', ''.join(c for c in value if not unicodedata.combining(c)).lower()).strip()


@lru_cache(maxsize=1)
def dataset():
    return json.loads((Path(__file__).parent / 'data/malaysia_locations.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def indexes():
    aliases, identities = defaultdict(list), {}
    for row in dataset()['places']:
        identities[row['id']] = row
        for alias in {text(row['name']), *(text(a) for a in row['aliases'])}:
            if alias:
                aliases[alias].append(row)
    return aliases, identities


def state_name(value):
    value = text(value)
    aliases = {'pulau pinang': 'Penang', 'malacca': 'Melaka', 'trengganu': 'Terengganu'}
    for prefix in ('wilayah persekutuan ', 'w p ', 'federal territory of '):
        value = value.removeprefix(prefix)
    return aliases.get(value) or next((s for s in dataset()['counts']['byState'] if text(s) == value), None)


@lru_cache(maxsize=8192)
def _parts(value):
    parts = [text(p) for p in str(value or '').split(',') if text(p)]
    if parts and parts[-1] in {'malaysia', 'my'}:
        parts.pop()
    state = state_name(parts[-1]) if len(parts) > 1 else None
    if state:
        parts.pop()
    if len(parts) == 1 and not state and parts[0] not in indexes()[0]:
        for candidate in sorted(dataset()['counts']['byState'], key=len, reverse=True):
            suffix = text(candidate)
            if parts[0].endswith(' ' + suffix):
                parts[0], state = parts[0][:-len(suffix)].strip(), candidate
                break
    return parts, state


def exact(value, *, state=None):
    parts, qualifier = _parts(str(value or ''))
    if not parts:
        return []
    query = parts[0]
    if not (state or qualifier) and query in GENERIC_AREA_WORDS:
        return []  # A common area prefix alone is not a sufficiently identified destination.
    district_only = query.endswith(' district') or query.startswith('daerah ')
    query = query.removesuffix(' district').removeprefix('daerah ').strip()
    rows = indexes()[0].get(query, [])
    if not rows:
        with _remote_lock:
            rows = [row for expiry, row in _remote.values() if expiry > monotonic()
                    and query in {text(row['name']), *(text(a) for a in row['aliases'])}]
    rows = [r for r in rows if (not (state or qualifier) or r['state'] == (state or qualifier))
            and (len(parts) < 2 or text(r.get('district')) == parts[1])
            and (not district_only or r['kind'] == 'district')]
    if not (state or qualifier) and len({r['state'] for r in rows}) > 1:
        return list(rows)
    # A named town is distinct from the same-named district; district labels are explicit.
    primary = [r for r in rows if text(r['name']) == query and r['kind'] == 'locality']
    primary = primary or [r for r in rows if r['kind'] == 'locality']
    return primary if primary and not district_only else list(rows)


def by_id(identity):
    identity = str(identity or '').removeprefix('geonames:')
    row = indexes()[1].get(identity)
    if row:
        return row
    with _remote_lock:
        saved = _remote.get(identity)
        return saved[1] if saved and saved[0] > monotonic() else None


def label(row):
    name = row['name'] + (' District' if row['kind'] == 'district' else '')
    duplicates = [r for r in indexes()[0].get(text(row['name']), [])
                  if r['state'] == row['state'] and r['kind'] == row['kind'] and text(r['name']) == text(row['name'])]
    district = f", {row['district']}" if len(duplicates) > 1 and row.get('district') else ''
    return f"{name}{district}, {row['state']}, Malaysia"


def unambiguous_labels(rows):
    counts = defaultdict(int)
    for row in rows:
        counts[text(row['canonicalName'])] += 1
    return [row for row in rows if counts[text(row['canonicalName'])] == 1]


def search(query, *, limit=30, fuzzy=True):
    parts, state = _parts(str(query or ''))
    value = parts[0] if parts else ''
    if len(value) < 2:
        return []
    direct = exact(query)
    if direct:
        return sorted(direct, key=lambda r: (-r['population'], r['name'], r['id']))[:limit]
    tokens = value.split()
    found = []
    for row in dataset()['places']:
        if state and row['state'] != state:
            continue
        names = [text(row['name']), *(text(a) for a in row['aliases'])]
        if any(name.startswith(value) for name in names):
            rank = 0
        elif all(any(word.startswith(t) for word in text(row['name']).split()) for t in tokens):
            rank = 1
        else:
            continue
        found.append((rank, -row['population'], row['name'], row['id'], row))
    if found:
        return [entry[-1] for entry in sorted(found, key=lambda v: v[:-1])[:limit]]
    if fuzzy and len(value) >= 5:
        keys = get_close_matches(value, indexes()[0], n=3, cutoff=.88)
        rows = []
        for key in keys:
            for row in exact(key, state=state):
                if row['id'] not in {r['id'] for r in rows}:
                    rows.append({**row, 'spellingSuggestion': True})
        return rows[:limit]
    return []


def mentions(value):
    words = text(value).split()
    found = []
    end_of_match = 0
    for start in range(len(words)):
        if start < end_of_match:
            continue
        for length in range(min(6, len(words) - start), 0, -1):
            name = ' '.join(words[start:start + length])
            rows = exact(name)
            if len(rows) == 1 and len(name) >= 4:
                if words[start] in {'to', 'in', 'at', 'near', 'from', 'around', 'on', 'with', 'for'} and text(rows[0]['name']) != name:
                    continue
                found.append((start, start + length, rows[0]))
                end_of_match = start + length
                break
    return found


def confident_spelling(value):
    choices = search(value)
    if not choices or not all(r.get('spellingSuggestion') for r in choices):
        return None
    parts, _ = _parts(str(value or ''))
    query = parts[0] if parts else ''
    ranked = sorted(((max(SequenceMatcher(None, query, text(a)).ratio()
                          for a in [row['name'], *row['aliases']]), row) for row in choices),
                    key=lambda item: item[0], reverse=True)
    if ranked[0][0] >= .9 and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= .06):
        return ranked[0][1]
    return None


_remote, _remote_lock = {}, Lock()


def verified_provider_row(item):
    if not isinstance(item, dict):
        return None
    state = state_name(item.get('admin1'))
    try:
        if not re.fullmatch(r'[0-9]{1,10}', str(item.get('id'))) or not 0 < int(item['id']) < 2**31:
            return None
        identity = str(int(item['id']))
        lat, lon = float(item['latitude']), float(item['longitude'])
        population = int(item.get('population') or 0)
    except (KeyError, ValueError, TypeError, OverflowError):
        return None
    feature = str(item.get('feature_code') or '')
    if (item.get('country_code') != 'MY' or not state or not isinstance(item.get('name'), str)
            or not 1 <= len(item['name'].strip()) <= 150
            or population < 0 or (item.get('admin2') is not None and
                                  (not isinstance(item['admin2'], str) or len(item['admin2']) > 150))
            or not (feature.startswith('PPL') or feature in {'ADM2', 'ADM3', 'ISL', 'ISLS'})
            or feature in {'PPLH', 'PPLQ', 'PPLW', 'PPLCH'}
            or not math.isfinite(lat) or not math.isfinite(lon)
            or isinstance(item.get('latitude'), bool) or isinstance(item.get('longitude'), bool)
            or coordinate_state(lat, lon) != state):
        return None
    row = {'id': identity, 'name': str(item['name']), 'state': state, 'district': item.get('admin2'),
           'kind': 'district' if feature == 'ADM2' else 'subdistrict' if feature == 'ADM3'
                   else 'island' if feature in {'ISL', 'ISLS'} else 'locality',
           'latitude': lat, 'longitude': lon, 'aliases': [str(item['name'])],
           'feature': feature, 'population': population, 'fast': False,
           'source': 'open_meteo_geonames'}
    with _remote_lock:
        if len(_remote) >= 128:
            _remote.pop(next(iter(_remote)))
        _remote[identity] = (monotonic() + 3600, row)
    return row


def online_search(query):
    from services.open_meteo_service import geocode
    return [row for item in geocode(query, timeout=8, country_code='MY', count=10)
            if (row := verified_provider_row(item)) is not None]


def online_id(identity):
    from services.open_meteo_service import geocode_id
    return verified_provider_row(geocode_id(identity, timeout=8))
