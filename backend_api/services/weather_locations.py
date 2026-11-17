"""Malaysia-only weather points projected from the shared geographic catalogue."""
from functools import lru_cache
from services import malaysia_locations as locations
from services.malaysian_locality import destination_locations, location_scope, search_destination_locations
from services.malaysia_boundary import coordinate_state
from services.local_catalog import DESTINATIONS


def weather_point(row):
    state = row.get('state')
    if not state:
        return None
    is_state = row.get('kind') == 'state' or not row.get('city')
    lat, lon = row.get('latitude'), row.get('longitude')
    if not is_state and (lat is None or lon is None or coordinate_state(lat, lon) != state):
        return None
    return {'id': row.get('locationId') or row['scopeKey'],
            'name': row.get('city') or state, 'admin1': state, 'country': 'Malaysia',
            'label': row['canonicalName'], 'requiresCity': is_state,
            'latitude': None if is_state else lat, 'longitude': None if is_state else lon,
            'aliases': row.get('aliases', []), 'population': row.get('population', 0),
            'pointDescription': ('Choose a city or locality; weather varies across the state.' if is_state else
                                 'Representative locality point; conditions vary within the area.')}


@lru_cache(maxsize=1)
def weather_locations():
    rows = list(destination_locations())
    rows.extend(location_scope(row) for row in locations.dataset()['places']
                if row['kind'] == 'locality' and row['name'] == row['state'] and row['fast'])
    return list({point['id']: point for row in rows if (point := weather_point(row))}.values())


def search_weather_locations(query, *, remote=False):
    state = locations.state_name(query.removesuffix(', Malaysia'))
    if state:
        choices = [p for p in weather_locations() if p['admin1'] == state]
        def rank(point):
            row = locations.by_id(point['id']) or {}
            return (not point['requiresCity'], -row.get('population', 0), point['label'])
        return sorted(choices, key=rank)[:20]
    # Search raw sourced rows first: legacy aliases can contain an obsolete withheld centre.
    sourced = [location_scope(row) for row in locations.search(query)]
    found = [p for row in sourced if (p := weather_point(row))]
    if not found:
        found = [p for row in search_destination_locations(query, remote=remote) if (p := weather_point(row))]
    if found:
        return found
    # Landmark compatibility uses recorded coordinates, never a guessed parent city.
    for row in DESTINATIONS:
        name = row.get('title') or row.get('name') or ''
        gps = row.get('gps_coordinates') or {}
        if (locations.text(name) == locations.text(query) and isinstance(gps.get('latitude'), (int, float))
                and isinstance(gps.get('longitude'), (int, float)) and coordinate_state(gps['latitude'], gps['longitude'])):
            state = coordinate_state(gps['latitude'], gps['longitude'])
            found.append({'id': 'landmark:' + str(row.get('destinationId') or name), 'name': name,
                          'label': f'{name}, {state}, Malaysia', 'admin1': state, 'country': 'Malaysia',
                          'latitude': gps['latitude'], 'longitude': gps['longitude'], 'requiresCity': False})
    return found


def selected_weather_point(identity):
    if str(identity).startswith('geonames:'):
        row = locations.by_id(identity)
        return weather_point(location_scope(row)) if row else None
    if str(identity).startswith('landmark:'):
        for row in DESTINATIONS:
            for point in search_weather_locations(row.get('title') or row.get('name') or ''):
                if point['id'] == identity:
                    return point
        return None
    return next((p for p in weather_locations() if p['id'] == identity), None)
