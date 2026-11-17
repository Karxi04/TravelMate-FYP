import logging
import re
import unicodedata
import json
import math
from pathlib import Path
from services.malaysia_boundary import coordinate_state


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
    'Langkawi': ('Kedah', {'langkawi', 'kuah'}),
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


def normalize_destination_scope(value):
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


def destination_locations():
    """Supported areas only; no attraction names, provider calls or guessed city centres."""
    rows = [dict(normalize_destination_scope('Malaysia'), kind='country', aliases=['malaysia', 'my'])]
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
        rows.append(dict(normalize_destination_scope(city),
                         kind='locality', aliases=sorted(aliases)))
    return rows


def resolve_destination_scope(value, scope_key=None):
    rows = destination_locations()
    if scope_key is not None:
        match = next((row for row in rows if row['scopeKey'] == scope_key), None)
        if not match or _text(value) != _text(match['canonicalName']):
            raise ValueError('Choose a supported destination area')
        return {key: val for key, val in match.items() if key not in ('kind', 'aliases')}
    # Fully qualified state labels are unambiguous; short legacy city aliases stay supported.
    match = next((row for row in rows if _text(value) == _text(row['canonicalName'])), None)
    known = {_text(label) for row in rows for alias in row['aliases'] for label in
             (alias, f'{alias}, Malaysia', f"{alias}, {row['state'] or ''}", f"{alias}, {row['state'] or ''}, Malaysia")}
    if not match and _text(value) not in known:
        return {**normalize_destination_scope(''), 'canonicalName': str(value or '').strip()}
    return ({key: val for key, val in match.items() if key not in ('kind', 'aliases')}
            if match else normalize_destination_scope(value))


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
    explicit_city = _locality_from_text(
        item.get('city') or item.get('locality') or item.get('town') or ''
    )
    city_state = LOCALITIES[explicit_city][0] if explicit_city else None
    address = ' '.join(str(item.get(key) or '') for key in (
        'address', 'formatted_address', 'formattedAddress', 'vicinity',
        'neighborhood', 'area',
    ))
    if isinstance(item.get('location'), str):
        address = f"{address} {item['location']}"
    address_city = _locality_from_text(address)
    address_state = _state_from_text(address)

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
    elif scope.get('city') and geography.get('city') != scope.get('city'):
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
