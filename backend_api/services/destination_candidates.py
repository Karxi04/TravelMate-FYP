"""Shared facts/discovery, independent of FR3 relevance, FR4 scores and FR11 conversation."""
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from math import cos, radians, sin, asin, sqrt, isfinite

from services.malaysian_locality import normalize_candidate_geography, normalize_destination_scope, filter_candidates
from services.recommendation_discovery import enrich_discovery_candidate, is_planning_candidate
from services.recommendation_taxonomy import normalize_phrase, provider_categories, experience_types
from services.serpapi_service import destination_pagination
from services.activity_pricing import PRICING_FIELDS

CACHE_DAYS = 7
PAGE_SIZE = 20
MAX_GENERATION_REQUESTS = 3
MAX_DISCOVERY_REQUESTS = 6  # Existing two queries × three pages; expansion cannot increase this chain budget.


def discovery_diagnostics(items, scope):
    accepted, rejected = filter_candidates(items, scope)
    return {'rawProviderCount': len(items), 'geographicallyValidCount': len(accepted),
            'geographicRejections': dict(Counter(row['geographicEligibility']['reason'] for row in rejected)),
            'tourismCandidateCount': sum(is_planning_candidate(row) for row in accepted)}


def destination_id(item):
    for field in ('destinationId', 'place_id', 'data_id', 'data_cid', 'id'):
        value = str(item.get(field) or '').strip()
        if value and '/' not in value and len(value) <= 512:
            return value
    name = normalize_phrase(item.get('title') or item.get('name'))
    if not name:
        return ''
    geo = normalize_candidate_geography(item)
    return 'place_' + hashlib.sha256(f'{name}|{geo.get("state")}|{geo.get("city")}'.encode()).hexdigest()[:24]


def identity_aliases(item):
    values = item.get('identityAliases')
    return {value for value in values[:8] if isinstance(value, str) and 0 < len(value) <= 512} if isinstance(values, list) else set()


def same_place(a, b):
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    fields = ('destinationId', 'place_id', 'data_id', 'data_cid', 'id', 'reviewDestinationId')
    left = {str(a[k]) for k in fields if a.get(k)} | identity_aliases(a)
    if left & ({str(b[k]) for k in fields if b.get(k)} | identity_aliases(b)):
        return True
    def canonical_name(row):
        name = normalize_phrase(row.get('title') or row.get('name')).replace('kek loksi', 'kek lok si')
        return 'kek lok si temple' if name == 'kek lok si' else name
    name = canonical_name(a)
    if not name or name != canonical_name(b):
        return False
    ga, gb = normalize_candidate_geography(a), normalize_candidate_geography(b)
    if not ga.get('state') or not gb.get('state'):
        return not ga.get('state') and not gb.get('state')
    if ga.get('state') != gb.get('state'):
        return False
    if ga.get('conflict') or gb.get('conflict'):
        return False
    if all(g.get('latitude') is not None and g.get('longitude') is not None for g in (ga, gb)):
        lat1, lat2 = radians(ga['latitude']), radians(gb['latitude'])
        distance = 12742 * asin(min(1, sqrt(sin((lat2-lat1)/2)**2 + cos(lat1)*cos(lat2)*sin(radians(gb['longitude']-ga['longitude'])/2)**2)))
        return distance <= .5
    return not (ga.get('city') and gb.get('city') and ga['city'] != gb['city'])


def timestamp(value):
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return datetime.min.replace(tzinfo=timezone.utc)


def normalise(items, scope, *, source=None, now=None):
    now = now or datetime.now(timezone.utc)
    accepted, _ = filter_candidates(items, scope)
    result = []
    for item in accepted:
        did = destination_id(item)
        if not did:
            continue
        row = {**_finite_metadata(item), 'destinationId': did}
        if isinstance(row.get('cachedAt'), datetime):
            row['cachedAt'] = timestamp(row['cachedAt']).isoformat()
        origin = source or row.get('candidateSource') or row.get('recommendationSource') or 'unknown'
        row['candidateSource'] = origin
        if origin == 'live_provider' and 'rating' in row:
            row['ratingSource'] = 'provider'
        elif origin == 'local_catalog' and 'rating' in row:
            row['ratingSource'] = 'unverified_local_catalog'
        if origin == 'cache':
            cached = timestamp(row.get('cachedAt'))
            row['cacheFreshness'] = ('unknown' if cached.year == 1 else
                                     'fresh' if now - timedelta(days=CACHE_DAYS) <= cached <= now + timedelta(minutes=5) else 'stale')
        row['metadataEvidence'] = {'providerCategoryIds': provider_categories(row),
                                  'categorySource': 'provider' if provider_categories(row) else 'recorded',
                                  'experienceTypes': experience_types(row), 'source': origin}
        result.append(enrich_discovery_candidate(row))
    return result


def _finite_metadata(value):
    if isinstance(value, float) and not isfinite(value):
        return None  # An invalid numeric provider value is unknown, never an invented score or coordinate.
    if isinstance(value, dict):
        return {key: _finite_metadata(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_metadata(item) for item in value]
    return value


def merge_candidates(*groups):
    """Newest provider/cache description wins; a verified local ticket is not overwritten by an unknown quote."""
    rows = [r for group in groups for r in group if isinstance(r, dict)]
    def priority(row):
        source = row.get('candidateSource')
        return (source == 'live_provider', timestamp(row.get('cachedAt')), source == 'cache', destination_id(row))
    output = []
    for row in sorted(rows, key=priority):
        index = next((i for i, old in enumerate(output) if same_place(old, row)), None)
        if index is None:
            output.append(dict(row))
            continue
        old = output[index]
        merged = {**old, **{k: v for k, v in row.items() if v not in (None, '', [], {})}}
        merged['destinationId'] = destination_id(old)
        merged['identityAliases'] = sorted({destination_id(old), destination_id(row),
                                            *identity_aliases(old), *identity_aliases(row)})[:8]
        if old.get('costProvenance') == 'verified_ticket' and row.get('costProvenance') != 'verified_ticket':
            merged.update({k: old[k] for k in PRICING_FIELDS if k in old})
        output[index] = merged
    return sorted(output, key=lambda row: (normalize_phrase(row.get('title') or row.get('name')), destination_id(row)))


def facts_signature(rows):
    fields = ('destinationId', 'title', 'name', 'category', 'type', 'types', 'type_id', 'type_ids',
              'description', 'address', 'gps_coordinates', 'rating', 'reviews', 'cachedAt')
    return json.dumps(sorted(({k: row[k] for k in fields if k in row} for row in rows),
                             key=lambda row: destination_id(row)), sort_keys=True, default=str)


def cached_candidates(read, scope, limit=150):
    filters = [] if scope['scopeKey'] == 'my' else [('canonicalDestinationScope', '==', scope['scopeKey'])]
    latest = list(read('destination_cache', filters=filters, orderBy=[('cachedAt', 'DESCENDING')], limit=limit) or [])
    if scope.get('state') and len(latest) < limit:
        latest += read('destination_cache', filters=[('normalizedGeography.state', '==', scope['state'])],
                       orderBy=[('cachedAt', 'DESCENDING')], limit=limit) or []
    # order_by(cachedAt) excludes old documents lacking that field. Keep a bounded, stable legacy fallback.
    legacy = read('destination_cache', orderBy=[('__name__', 'ASCENDING')], limit=limit) or []
    return merge_candidates(normalise(latest, scope, source='cache'), normalise(legacy, scope, source='cache'))


def provider_page(provider, query, scope, start=0):
    scope = scope if isinstance(scope, dict) else normalize_destination_scope(scope)
    if not scope.get('resolved'):
        raise ValueError('Unresolved Malaysian search scope')
    coords = {'latitude': scope.get('latitude'), 'longitude': scope.get('longitude')}
    if scope.get('geographicMode') == 'nearby':
        query = f"{query} near {scope['canonicalName']}"
    data = provider(query, scope['canonicalName'], coords, **({'start': start} if start else {}))
    if not isinstance(data, dict) or not isinstance(data.get('local_results'), list):
        raise ValueError('Malformed destination response')
    raw = [{**row, 'category': row.get('category') or row.get('type') or '',
            'description': row.get('description') or row.get('type') or row.get('address') or '',
            **({'ratingSource': 'provider'} if 'rating' in row else {})}
           for row in data['local_results'] if isinstance(row, dict)]
    return {'items': normalise(raw, scope, source='live_provider'),
            'diagnostics': discovery_diagnostics(raw, scope),
            **destination_pagination(data, start)}


def discovery_pool(read, provider, scope, preference, *, local=(), previous=(), queries=(), cursors=None,
                   used=0, allow_provider=False, cached=None):
    pool = merge_candidates(normalise(local, scope, source='local_catalog'),
                            normalise(previous, scope, source='snapshot'), cached if cached is not None else cached_candidates(read, scope))
    pages, calls, errors, live, failure_types = dict(cursors or {}), 0, 0, [], set()
    diagnostics = {'rawProviderCount': 0, 'geographicallyValidCount': 0, 'tourismCandidateCount': 0,
                   'geographicRejections': {}}
    for query in queries[:MAX_GENERATION_REQUESTS]:
        if not allow_provider or calls >= min(MAX_GENERATION_REQUESTS, MAX_DISCOVERY_REQUESTS - used):
            break
        offset = pages.get(query, 0)
        if offset is None or type(offset) is not int or offset not in (0, 20, 40):
            continue
        calls += 1
        try:
            page = provider(query, scope, offset)
            for key in ('rawProviderCount', 'geographicallyValidCount', 'tourismCandidateCount'):
                diagnostics[key] += (page.get('diagnostics') or {}).get(key, 0)
            diagnostics['geographicRejections'] = dict(Counter(diagnostics['geographicRejections']) +
                Counter((page.get('diagnostics') or {}).get('geographicRejections', {})))
            live += page['items']
            pool = merge_candidates(pool, page['items'])
            pages[query] = page['nextOffset'] if page.get('hasMore') else None
        except Exception as error:
            errors += 1  # Keep cache/prior facts available. Never expose provider exceptions.
            failure_types.add(type(error).__name__)
    feedback = preference.get('destinationFeedback') or {}
    pool = [r for r in pool if not any(feedback.get(key) == 'not_for_me' for key in
            [destination_id(r), *(r.get('identityAliases') or [])]) and is_planning_candidate(r)]
    total = used + calls
    return {'items': pool, 'cursors': pages, 'providerRequestsUsed': total, 'providerRequests': calls,
            'diagnostics': {**diagnostics, 'uniqueEligiblePoolCount': len(pool)},
            'providerItems': live,
            'providerFailureTypes': sorted(failure_types),
            'providerErrors': errors, 'providerHasMore': bool(total < MAX_DISCOVERY_REQUESTS and any(v is not None for v in pages.values())),
            'source': 'live_provider' if calls > errors else 'cache'}
