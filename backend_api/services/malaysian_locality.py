import logging
import re
import unicodedata
import json
import math
from pathlib import Path
from functools import lru_cache
from services.malaysia_boundary import coordinate_state
from services import malaysia_locations as locations


logger = logging.getLogger(__name__)


def _text(value):
    value = unicodedata.normalize('NFKD', str(value or ''))
    value = ''.join(char for char in value if not unicodedata.combining(char))
    return re.sub(r'[^a-z0-9]+', ' ', value.lower()).strip()


STATE_ALIASES = {
    'Johor': {'johor'},
    'Kedah': {'kedah'},
    'Kelantan': {'kelantan'},
    'Melaka': {'melaka', 'malacca'},
    'Negeri Sembilan': {'negeri sembilan'},
    'Pahang': {'pahang'},
    'Penang': {'penang', 'pulau pinang'},
    'Perak': {'perak'},
    'Perlis': {'perlis'},
    'Sabah': {'sabah'},
    'Sarawak': {'sarawak'},
    'Selangor': {'selangor'},
    'Terengganu': {'terengganu', 'trengganu'},
    'Kuala Lumpur': {'kuala lumpur', 'wilayah persekutuan kuala lumpur'},
    'Putrajaya': {'putrajaya', 'wilayah persekutuan putrajaya'},
    'Labuan': {'labuan', 'wilayah persekutuan labuan'},
}


LOCALITIES = {
    'George Town': ('Penang', {'george town', 'georgetown'}),
    'Air Itam': ('Penang', {'air itam', 'ayer itam'}),
    'Bayan Lepas': ('Penang', {'bayan lepas'}),
    'Batu Ferringhi': ('Penang', {'batu ferringhi', 'batu ferenggi'}),
    'Tanjung Bungah': ('Penang', {'tanjung bungah'}),
    'Tanjung Tokong': ('Penang', {'tanjung tokong'}),
    'Balik Pulau': ('Penang', {'balik pulau'}),
    'Butterworth': ('Penang', {'butterworth'}),
    'Bukit Mertajam': ('Penang', {'bukit mertajam'}),
    'Seberang Perai': ('Penang', {'seberang perai', 'province wellesley'}),
    'Kuala Lumpur': ('Kuala Lumpur', {'kuala lumpur', 'kl'}),
    'Bukit Bintang': ('Kuala Lumpur', {'bukit bintang'}),
    'KLCC': ('Kuala Lumpur', {'klcc'}),
    'Petaling Jaya': ('Selangor', {'petaling jaya', 'pj'}),
    'Shah Alam': ('Selangor', {'shah alam'}),
    'Ipoh': ('Perak', {'ipoh'}),
    'Taiping': ('Perak', {'taiping'}),
    'Johor Bahru': ('Johor', {'johor bahru', 'jb'}),
    'Desaru': ('Johor', {'desaru'}),
    'Alor Setar': ('Kedah', {'alor setar', 'alor star'}),
    'Langkawi': ('Kedah', {'langkawi', 'kuah', 'langkawi islands'}),
    'Kota Bharu': ('Kelantan', {'kota bharu'}),
    'Kuantan': ('Pahang', {'kuantan'}),
    'Cameron Highlands': ('Pahang', {'cameron highlands', 'cameron'}),
    'Genting Highlands': ('Pahang', {'genting highlands', 'genting'}),
    'Seremban': ('Negeri Sembilan', {'seremban'}),
    'Port Dickson': ('Negeri Sembilan', {'port dickson', 'pd'}),
    'Kota Kinabalu': ('Sabah', {'kota kinabalu', 'kk'}),
    'Kundasang': ('Sabah', {'kundasang'}),
    'Sandakan': ('Sabah', {'sandakan'}),
    'Kuching': ('Sarawak', {'kuching'}),
    'Miri': ('Sarawak', {'miri'}),
    'Kuala Terengganu': ('Terengganu', {'kuala terengganu'}),
    'Kuala Besut': ('Terengganu', {'kuala besut'}),
    'Redang Island': ('Terengganu', {'redang', 'redang island', 'pulau redang'}),
    'Perhentian': ('Terengganu', {'perhentian', 'perhentian island', 'pulau perhentian'}),
    'Melaka City': ('Melaka', {'melaka city', 'bandar melaka', 'malacca city', 'melaka', 'malacca'}),
    'Kangar': ('Perlis', {'kangar'}),
    'Putrajaya': ('Putrajaya', {'putrajaya'}),
    'Labuan': ('Labuan', {'labuan'}),
    'Semporna': ('Sabah', {'semporna'}),
    'Sibu': ('Sarawak', {'sibu'}),
    'Kuala Selangor': ('Selangor', {'kuala selangor'}),
    'Kuala Kangsar': ('Perak', {'kuala kangsar'}),
    'Muar': ('Johor', {'muar'}),
    'Sungai Petani': ('Kedah', {'sungai petani'}),
}


STATE_CENTERS = {
    'Penang': (5.4141, 100.3288),
    'Kuala Lumpur': (3.1390, 101.6869),
    'Selangor': (3.0738, 101.5183),
    'Perak': (4.5921, 101.0901),
    'Johor': (1.4854, 103.7618),
    'Kedah': (6.1184, 100.3685),
    'Melaka': (2.1896, 102.2501),
    'Pahang': (3.8126, 103.3256),
    'Negeri Sembilan': (2.7258, 101.9424),
    'Kelantan': (6.1254, 102.2381),
    'Terengganu': (5.3117, 103.1324),
    'Perlis': (6.4449, 100.1986),
    'Sabah': (5.9804, 116.0735),
    'Sarawak': (1.5533, 110.3592),
    'Putrajaya': (2.9264, 101.6964),
    'Labuan': (5.2831, 115.2308),
}

LOCALITY_CENTRES = json.loads((Path(__file__).parent / 'data/malaysia_locality_centres.json').read_text(encoding='utf-8'))['localities']


FOREIGN_DESTINATIONS = {
    'singapore': 'Singapore',
    'tokyo': 'Tokyo, Japan',
    'japan': 'Japan',
    'kyoto': 'Kyoto, Japan',
    'osaka': 'Osaka, Japan',
    'bangkok': 'Bangkok, Thailand',
    'phuket': 'Phuket, Thailand',
    'thailand': 'Thailand',
    'chiang mai': 'Chiang Mai, Thailand',
    'pattaya': 'Pattaya, Thailand',
    'krabi': 'Krabi, Thailand',
    'bali': 'Bali, Indonesia',
    'jakarta': 'Jakarta, Indonesia',
    'indonesia': 'Indonesia',
    'seoul': 'Seoul, South Korea',
    'korea': 'South Korea',
    'london': 'London, UK',
    'paris': 'Paris, France',
    'new york': 'New York, USA',
    'sydney': 'Sydney, Australia',
    'melbourne': 'Melbourne, Australia',
    'australia': 'Australia',
    'vietnam': 'Vietnam',
    'hanoi': 'Hanoi, Vietnam',
    'taiwan': 'Taiwan',
    'hong kong': 'Hong Kong',
}


def _contains_alias(text, alias):
    return bool(alias and re.search(rf'\b{re.escape(alias)}\b', text))


def _last_alias_match(text, entries):
    matches = []
    for canonical, aliases in entries:
        for alias in aliases:
            for match in re.finditer(rf'\b{re.escape(alias)}\b', text):
                matches.append((match.start(), len(alias), canonical))
    return max(matches, default=None)


def _state_from_text(value):
    text = _text(value)
    state_match = _last_alias_match(text, STATE_ALIASES.items())
    locality_match = _last_alias_match(
        text,
        ((state, aliases) for _, (state, aliases) in LOCALITIES.items()),
    )
    match = max(
        (candidate for candidate in (state_match, locality_match) if candidate),
        default=None,
    )
    return match[2] if match else None


def _locality_from_text(value):
    text = _text(value)
    # A qualified area label starts with its locality; a street containing a city word does not.
    if ',' in str(value):
        first = _text(str(value).split(',')[0])
        exact = next((name for name, (_, aliases) in LOCALITIES.items() if first in aliases), None)
        if exact:
            return exact
    match = _last_alias_match(
        text,
        ((name, aliases) for name, (_, aliases) in LOCALITIES.items()),
    )
    return match[2] if match else None


def _coordinates(item):
    gps = item.get('gps_coordinates') or item.get('gpsCoordinates')
    if not isinstance(gps, dict) and isinstance(item.get('location'), dict):
        gps = item.get('location')
    gps = gps if isinstance(gps, dict) else {}
    latitude = gps.get('latitude', gps.get('lat', item.get('latitude', item.get('lat'))))
    longitude = gps.get('longitude', gps.get('lng', gps.get('lon', item.get('longitude', item.get('lng')))))
    try:
        lat, lon = float(latitude), float(longitude)
        if isinstance(latitude, bool) or isinstance(longitude, bool) or not math.isfinite(lat) or not math.isfinite(lon) or abs(lat) > 90 or abs(lon) > 180:
            return None, None
        return lat, lon
    except (TypeError, ValueError):
        return None, None


def _state_from_coordinates(latitude, longitude):
    if latitude is None or longitude is None:
        return None
    return coordinate_state(latitude, longitude)


def _legacy_destination_scope(value):
    raw = str(value or '').strip()
    text = _text(raw)
    city = _locality_from_text(text)
    state = LOCALITIES[city][0] if city else _state_from_text(text)
    country = 'Malaysia' if text in {'malaysia', 'my'} or state else None
    if city:
        canonical_name = f'{city}, {state}, Malaysia'
        scope_key = f"my:{_text(state).replace(' ', '_')}:{_text(city).replace(' ', '_')}"
    elif state:
        canonical_name = f'{state}, Malaysia'
        scope_key = f"my:{_text(state).replace(' ', '_')}"
    elif text in {'malaysia', 'my'}:
        canonical_name = 'Malaysia'
        scope_key = 'my'
    else:
        canonical_name = raw
        scope_key = ''
    locality = LOCALITY_CENTRES.get(city)
    compatible = bool(locality and coordinate_state(locality['latitude'], locality['longitude']) == state)
    center = (locality['latitude'], locality['longitude']) if compatible else (None if city else STATE_CENTERS.get(state))
    return {
        'country': country,
        'state': state,
        'city': city,
        'canonicalName': canonical_name,
        'scopeKey': scope_key,
        'latitude': center[0] if center else None,
        'longitude': center[1] if center else None,
        'coordinateSource': locality['sourceUrl'] if compatible else ('legacy_state_centre' if center else None),
        'coordinateStatus': 'verified_locality' if compatible else ('unavailable_or_boundary_conflict' if city else 'state_hint'),
        'resolved': bool(scope_key),
    }


@lru_cache(maxsize=1)
def _legacy_destination_locations():
    """Supported areas only; no attraction names, provider calls or guessed city centres."""
    rows = [dict(_legacy_destination_scope('Malaysia'), kind='country', aliases=['malaysia', 'my'])]
    for state, aliases in STATE_ALIASES.items():
        lat, lon = STATE_CENTERS[state]
        rows.append({'country': 'Malaysia', 'state': state, 'city': None, 'kind': 'state',
                     'canonicalName': f'{state}, Malaysia', 'scopeKey': f"my:{_text(state).replace(' ', '_')}",
                     'latitude': lat, 'longitude': lon, 'coordinateSource': 'legacy_state_centre',
                     'coordinateStatus': 'state_hint', 'resolved': True,
                     'aliases': sorted(aliases | (LOCALITIES[state][1] if state in LOCALITIES else set()))})
    for city, (state, aliases) in LOCALITIES.items():
        if city == state:
            continue
        rows.append(dict(_legacy_destination_scope(city),
                         kind='locality', aliases=sorted(aliases)))
    return rows


def location_scope(row):
    legacy = next((name for name, centre in LOCALITY_CENTRES.items()
                   if str(centre.get('id')) == row['id']), None)
    if not legacy and row['name'] in LOCALITIES and row['name'] not in LOCALITY_CENTRES:
        if LOCALITIES[row['name']][0] == row['state'] and row['kind'] != 'district':
            legacy = row['name']
    if not legacy and row['kind'] == 'locality':
        aliases = {_text(a) for a in [row['name'], *row['aliases']]}
        matches = [name for name, (state, known) in LOCALITIES.items()
                   if name not in LOCALITY_CENTRES and state == row['state'] and aliases & known]
        if len(matches) == 1:
            legacy = matches[0]
    base = _legacy_destination_scope(legacy) if legacy else {
        'country': 'Malaysia', 'state': row['state'], 'city': row['name'],
        'canonicalName': locations.label(row), 'scopeKey': f"my:geonames:{row['id']}", 'resolved': True}
    return {**base, 'latitude': row['latitude'], 'longitude': row['longitude'],
            'locationId': f"geonames:{row['id']}", 'district': row.get('district'),
            'kind': 'region' if legacy and row['kind'] == 'district' else row['kind'],
            'coordinateSource': f"https://www.geonames.org/{row['id']}/",
            'coordinateStatus': 'verified_locality', 'aliases': row['aliases'][:16],
            'dataSource': row.get('source', 'geonames_dump'),
            'dataLicense': 'CC BY-NC 4.0' if row.get('source') == 'open_meteo_geonames' else 'CC BY 4.0'}


def normalize_destination_scope(value):
    plain = _text(value)
    marked = _labelled_location(value)
    if marked is not None:
        return marked
    if plain in {'malaysia', 'my'} or any(plain in {alias, alias + ' malaysia'}
            for aliases in STATE_ALIASES.values() for alias in aliases):
        return _legacy_destination_scope(value)
    legacy = _legacy_input_names().get(plain)
    if legacy:
        centre = LOCALITY_CENTRES.get(legacy)
        if centre:
            record = locations.by_id(centre['id'])
            return location_scope(record) if record else _legacy_destination_scope(value)
        rows = locations.exact(value, state=LOCALITIES[legacy][0])
        return location_scope(rows[0]) if len(rows) == 1 and rows[0]['kind'] == 'locality' else _legacy_destination_scope(value)
    rows = locations.exact(value)
    if len(rows) == 1:
        return location_scope(rows[0])
    if len(rows) > 1:
        return {**_legacy_destination_scope(''), 'canonicalName': str(value or '').strip()}
    return _legacy_destination_scope(value)


@lru_cache(maxsize=1)
def _legacy_input_names():
    return {_text(label): name for name, (state, aliases) in LOCALITIES.items() for alias in aliases
            for label in (alias, f'{alias}, Malaysia', f'{alias}, {state}', f'{alias}, {state}, Malaysia')}


def _labelled_location(value):
    marker = re.search(r'\bgeonames\s+([0-9]{1,16})\b', _text(value))
    if not marker:
        return None
    row = locations.by_id(marker[1])
    scope = location_scope(row) if row else None
    return scope if scope and _text(value) == _text(scope['canonicalName']) else {
        **_legacy_destination_scope(''), 'canonicalName': str(value or '').strip()}


@lru_cache(maxsize=1)
def destination_locations():
    rows = [dict(row) for row in _legacy_destination_locations()]
    for row in rows:
        if row.get('city'):
            enriched = normalize_destination_scope(row['city'])
            row.update({**enriched, 'aliases': sorted(set(row['aliases']) | set(enriched.get('aliases', [])))})
    known = {row['scopeKey'] for row in rows}
    for item in locations.dataset()['places']:
        if not item['fast'] or item['name'] == item['state']:
            continue
        row = {**location_scope(item), 'population': item['population']}
        if row['scopeKey'] not in known:
            rows.append(row)
            known.add(row['scopeKey'])
    return rows


def resolve_destination_scope(value, scope_key=None):
    rows = _legacy_destination_locations()
    if scope_key is not None:
        match = next((row for row in rows if row['scopeKey'] == scope_key), None)
        if not match and re.fullmatch(r'my:geonames:[0-9]{1,16}', str(scope_key)):
            record = locations.by_id(str(scope_key).split(':')[-1])
            match = location_scope(record) if record else None
        if not match or _text(value) != _text(match['canonicalName']):
            raise ValueError('Choose a supported destination area')
        if match.get('locationId'):
            return dict(match)
        if match.get('city'):
            return normalize_destination_scope(match['city'])
        return {key: val for key, val in match.items() if key not in ('kind', 'aliases')}
    marked = _labelled_location(value)
    if marked is not None:
        return marked
    # Fully qualified state labels are unambiguous; short legacy city aliases stay supported.
    match = next((row for row in rows if _text(value) == _text(row['canonicalName'])), None)
    if not match and (_text(value) in _legacy_input_names() or any(_text(value) == alias for aliases in STATE_ALIASES.values() for alias in aliases)):
        return normalize_destination_scope(value)
    if match and match.get('city'):
        return normalize_destination_scope(match['city'])
    sourced = locations.exact(value)
    if not match and len(sourced) == 1:
        return location_scope(sourced[0])
    known = {_text(label) for row in rows for alias in row['aliases'] for label in
             (alias, f'{alias}, Malaysia', f"{alias}, {row['state'] or ''}", f"{alias}, {row['state'] or ''}, Malaysia")}
    if not match and _text(value) not in known:
        return {**normalize_destination_scope(''), 'canonicalName': str(value or '').strip()}
    return ({key: val for key, val in match.items() if key not in ('kind', 'aliases')}
            if match else normalize_destination_scope(value))


def resolve_selected_scope(value, scope_key=None, location_id=None):
    if location_id is not None:
        identity = str(location_id).removeprefix('geonames:')
        if not re.fullmatch(r'[0-9]{1,10}', identity) or not 0 < int(identity) < 2**31:
            raise ValueError('Invalid geographic identifier')
        record = locations.by_id(identity) or locations.online_id(identity)
        if not record:
            raise ValueError('The location could not be verified in Malaysia')
        selected = location_scope(record)
        if _text(value) != _text(selected['canonicalName']) or (scope_key and scope_key != selected['scopeKey']):
            raise ValueError('Choose the matching verified location')
        return selected
    return resolve_destination_scope(value, scope_key)


def search_destination_locations(value, *, remote=False):
    found = [location_scope(row) for row in locations.search(value)]
    query = _text(value)
    for row in _legacy_destination_locations():
        if any(_text(name).startswith(query) for name in [row['canonicalName'], *row['aliases']]):
            found.insert(0, dict(row))
    if not found and remote and len(query) >= 3:
        found = [location_scope(row) for row in locations.online_search(value)]
    unique = {}
    for row in found:
        unique.setdefault(row['scopeKey'], row)
    return list(unique.values())[:30]


def resolve_area_query(value, *, remote=False):
    scope = resolve_destination_scope(value)
    if scope.get('resolved'):
        return scope
    spelling = locations.confident_spelling(value)
    if spelling:
        return location_scope(spelling)
    choices = search_destination_locations(value, remote=remote)
    exact = [row for row in choices if _text(value) in {
        _text(row.get('city')), _text(row['canonicalName']), *(_text(a) for a in row.get('aliases', []))}]
    if len(exact) == 1 and _text(value) not in locations.GENERIC_AREA_WORDS:
        return exact[0]
    return {**scope, 'clarificationChoices': choices}


def normalize_candidate_geography(item):
    item = item or {}
    latitude, longitude = _coordinates(item)
    coordinate_state = _state_from_coordinates(latitude, longitude)

    explicit_state = _state_from_text(
        item.get('state')
        or item.get('administrative_area')
        or item.get('administrativeArea')
        or item.get('region')
        or ''
    )
    city_text = item.get('city') or item.get('locality') or item.get('town') or ''
    district_text = item.get('district') or item.get('admin2')
    city_lookup = f'{city_text}, {district_text}, {explicit_state or coordinate_state}' if district_text and (explicit_state or coordinate_state) else city_text
    city_rows = ([] if locations.state_name(city_text) and not _locality_from_text(city_text)
                 else locations.exact(city_lookup, state=explicit_state or coordinate_state))
    city_row = city_rows[0] if len(city_rows) == 1 else None
    explicit_city = location_scope(city_row)['city'] if city_row else _locality_from_text(city_text)
    city_state = city_row['state'] if city_row else LOCALITIES[explicit_city][0] if explicit_city else None
    address = ' '.join(str(item.get(key) or '') for key in (
        'address', 'formatted_address', 'formattedAddress', 'vicinity',
        'neighborhood', 'area',
    ))
    if isinstance(item.get('location'), str):
        address = f"{address} {item['location']}"
    address_city = _locality_from_text(address)
    address_state = _state_from_text(address)
    if not address_city:
        matches = [(len(segment), row) for segment in address.split(',')
                   if not locations.state_name(segment) and _text(segment) not in {'malaysia', 'my'}
                   for row in locations.exact(re.sub(r'^\s*\d{5}\s+', '', segment).strip(),
                                              state=coordinate_state or explicit_state or address_state)]
        if matches:
            best = max(length for length, _ in matches)
            choices = {row['id']: row for length, row in matches if length == best}
            if len(choices) == 1:
                address_row = next(iter(choices.values()))
                address_city = location_scope(address_row)['city']
                address_state = address_state or address_row['state']

    textual_state = explicit_state or city_state or address_state
    outside = latitude is not None and longitude is not None and coordinate_state is None
    country = str(item.get('country') or item.get('countryCode') or '').strip().lower()
    foreign_country = bool(country and country not in {'my', 'mys', 'malaysia'})
    conflict = bool((coordinate_state and textual_state and coordinate_state != textual_state) or outside or foreign_country)
    if conflict:
        logger.warning(
            'Candidate geographic conflict: id=%s coordinate_state=%s text_state=%s',
            item.get('destinationId') or item.get('place_id') or item.get('title'),
            coordinate_state,
            textual_state,
        )

    if coordinate_state:
        state, evidence = coordinate_state, 'coordinates'
    elif explicit_state:
        state, evidence = explicit_state, 'state'
    elif city_state:
        state, evidence = city_state, 'city'
    elif address_state:
        state, evidence = address_state, 'address'
    else:
        state, evidence = None, 'unresolved'

    city = explicit_city or address_city
    return {
        'country': 'Malaysia' if state else None,
        'state': state,
        'city': city,
        'district': city_row.get('district') if city_row else None,
        'locationId': f"geonames:{city_row['id']}" if city_row else None,
        'latitude': latitude,
        'longitude': longitude,
        'evidence': evidence,
        'conflict': conflict,
        'resolved': bool(state),
    }


def validate_candidate(item, requested_scope):
    scope = requested_scope if isinstance(requested_scope, dict) else normalize_destination_scope(requested_scope)
    geography = normalize_candidate_geography(item)
    eligible = False
    reason = 'unresolved_candidate_geography'

    if not scope.get('resolved'):
        reason = 'unresolved_requested_destination'
    elif geography.get('conflict'):
        reason = 'conflicting_candidate_geography'
    elif not geography.get('resolved'):
        reason = 'unresolved_candidate_geography'
    elif scope.get('state') and geography.get('state') != scope.get('state'):
        reason = 'state_out_of_scope'
    elif (scope.get('kind') == 'locality' and scope.get('locationId') and geography.get('locationId')
          and scope['locationId'] != geography['locationId']):
        reason = 'locality_identity_out_of_scope'
    elif scope.get('city') and geography.get('city') != scope.get('city') and not (
            scope.get('kind') in {'district', 'region'}
            and _text(geography.get('district')) == _text(scope['city'])):
        reason = 'city_out_of_scope_or_unresolved'
    else:
        eligible = True
        reason = 'geographically_eligible'

    enriched = dict(item or {})
    enriched['normalizedGeography'] = geography
    enriched['geographicEligibility'] = {
        'eligible': eligible,
        'reason': reason,
        'evidence': geography.get('evidence'),
        'requestedScope': scope.get('scopeKey'),
    }
    return eligible, enriched


def filter_candidates(items, requested_scope):
    accepted = []
    rejected = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        eligible, normalized = validate_candidate(item, requested_scope)
        (accepted if eligible else rejected).append(normalized)
    return accepted, rejected
