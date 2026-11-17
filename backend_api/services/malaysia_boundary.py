"""Offline point-in-polygon against the pinned, unmodified DOSM state geometry."""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _polygons():
    source = json.loads((Path(__file__).parent / 'data/malaysia_states.geojson').read_text(encoding='utf-8'))
    output = []
    aliases = {'Pulau Pinang': 'Penang', 'W.P. Kuala Lumpur': 'Kuala Lumpur',
               'W.P. Putrajaya': 'Putrajaya', 'W.P. Labuan': 'Labuan'}
    for feature in source['features']:
        name = feature['properties']['state']
        geometry = feature['geometry']
        polygons = geometry['coordinates'] if geometry['type'] == 'MultiPolygon' else [geometry['coordinates']]
        for rings in polygons:
            xs, ys = zip(*rings[0])
            output.append((aliases.get(name, name), (min(xs), min(ys), max(xs), max(ys)), rings))
    return output


def _ring(x, y, ring):
    inside = False
    for (ax, ay), (bx, by) in zip(ring, ring[1:]):
        cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
        if abs(cross) <= 1e-12 and min(ax, bx) <= x <= max(ax, bx) and min(ay, by) <= y <= max(ay, by):
            return 2  # Boundary points are ambiguous, never assigned by polygon order.
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return int(inside)


@lru_cache(maxsize=4096)
def coordinate_state(latitude, longitude):
    found = set()
    for state, (west, south, east, north), rings in _polygons():
        if not west <= longitude <= east or not south <= latitude <= north:
            continue
        outer = _ring(longitude, latitude, rings[0])
        if outer == 2:
            return None
        if outer and not any(_ring(longitude, latitude, hole) for hole in rings[1:]):
            found.add(state)
    return next(iter(found)) if len(found) == 1 else None
