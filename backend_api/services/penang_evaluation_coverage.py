"""Fictional local evaluation contributions; no Firebase accounts or record imports."""
from copy import deepcopy
from functools import lru_cache
from services.review_service import review_id, screen_submission

DATASET = 'fyp-penang-coverage-v1'
# Existing canonical identities only. Ratings are curated evaluation inputs, not targets.
ATTRACTIONS = {
    'demo_penang_street_art': ('George Town Street Art', (5, 4, 3, 2, 4, 3)),
    'penang_armenian_street': ('Armenian Street', (4, 5, 2, 3, 4, 3)),
    'local_kek_lok_si': ('Kek Lok Si Temple', (5, 4, 3, 2, 4, 3)),
    'local_penang_hill': ('Penang Hill', (4, 3, 5, 4, 3, 2)),
    'local_peranakan_mansion': ('Pinang Peranakan Mansion', (5, 4, 2, 3, 4, 3)),
    'local_chew_jetty': ('Chew Jetty', (4, 3, 3, 2, 5, 4)),
    'local_botanical_gardens': ('Penang Botanic Gardens', (3, 2, 5, 4, 4, 3)),
    'penang_gurney_drive': ('Gurney Drive Hawker Centre', (5, 4, 2, 3, 4, 3)),
    'local_batu_ferringhi': ('Batu Ferringhi Beach', (3, 2, 4, 5, 5, 4)),
    'entopia': ('Entopia by Penang Butterfly Farm', (3, 2, 5, 4, 5, 4)),
    'tropical_spice_garden': ('Tropical Spice Garden', (4, 3, 5, 4, 3, 2)),
    'local_wonderfood': ('Wonderfood Museum', (5, 4, 2, 3, 5, 4)),
}

# Assigned independently of ratings; these identities are explicitly not Firebase users.
_PERSONAS = (
    ('culture-a', ['Culture', 'Photography', 'Food'], 'Mixed', 'Relaxed', 'Holiday', 'Explorer'),
    ('culture-b', ['Culture', 'Photography', 'Food'], 'Mixed', 'Relaxed', 'Holiday', 'Explorer'),
    ('nature-a', ['Nature', 'Adventure', 'Photography'], 'Lesser-known places', 'Packed', 'Solo travel', 'Explorer'),
    ('nature-b', ['Nature', 'Adventure', 'Photography'], 'Lesser-known places', 'Packed', 'Solo travel', 'Explorer'),
    ('family-a', ['Family', 'Relaxation', 'Culture'], 'Popular landmarks', 'Relaxed', 'Family trip', 'Planner'),
    ('family-b', ['Family', 'Relaxation', 'Culture'], 'Popular landmarks', 'Relaxed', 'Family trip', 'Planner'),
)
REVIEWER_PROFILES = {f'{DATASET}-{key}': {
    'interests': interests, 'travelType': style, 'travelPace': pace,
    'travelPurpose': purpose, 'travelPersonality': personality,
    'synthetic': True, 'dataset': DATASET,
} for key, interests, style, pace, purpose, personality in _PERSONAS}

_COMMENTS = {
    5: 'A wonderful visit to {name}. I enjoyed taking time to explore and look around.',
    4: 'A lovely visit to {name}. I enjoyed looking around at my own pace.',
    3: 'The visit to {name} was interesting, but felt rushed and a little disappointing.',
    2: 'I found {name} disappointing. The busy visit felt tiring, and I left frustrated.',
}


@lru_cache(maxsize=12)
def _sources(identity):
    if identity not in ATTRACTIONS:
        return []
    name, ratings = ATTRACTIONS[identity]
    rows = []
    for index, (uid, rating) in enumerate(zip(REVIEWER_PROFILES, ratings), 1):
        comment = _COMMENTS[rating].format(name=name)
        rows.append({'id': review_id(uid, identity), 'travellerId': uid,
            'travellerName': f'Reviewer {index}', 'destinationId': identity,
            'destinationName': name, 'destinationAddress': 'Penang, Malaysia',
            'rating': rating, 'comment': comment, 'synthetic': True, 'source': 'fyp_private',
            'dataset': DATASET, 'submittedAt': f'2026-11-21T02:0{index}:00+00:00',
            **screen_submission(comment, rating)})
    return rows


def sources(identity):
    return deepcopy(_sources(identity))
