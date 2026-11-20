"""Confirmed Penang review identities. Keep in sync with Flutter ReviewContract."""

_ALIASES = {
    'local_penang_hill': ('penang_hill',),
    'local_kek_lok_si': ('kek_lok_si', 'ChIJZYb8XRjCSjARxD5Df-qEkCw'),
    'local_peranakan_mansion': ('peranakan_mansion', 'ChIJCWvz3I_DSjAR5hveCXjdfIs'),
    'local_wonderfood': ('wonderfood_museum', 'ChIJv4nHaI7DSjAR8peeKMlaKok'),
    'local_batu_ferringhi': ('batu_ferringhi',),
    'local_botanical_gardens': ('penang_botanic_gardens', 'ChIJWeDiIPHCSjAROzyNNz_QUx8'),
    'local_chew_jetty': ('ChIJ50W1D43DSjARlPqYV1MqscE',),
}
_CANONICAL = {alias: identity for identity, aliases in _ALIASES.items() for alias in aliases}


def review_destination_id(identity):
    identity = identity.strip()
    return _CANONICAL.get(identity, identity)


def review_destination_ids(identity):
    canonical = review_destination_id(identity)
    return (canonical, *_ALIASES.get(canonical, ()))


def review_candidate_id(item):
    return review_destination_id(str(item.get('reviewDestinationId') or item.get('destinationId')
        or item.get('place_id') or item.get('data_id') or item.get('id') or item.get('title') or ''))
