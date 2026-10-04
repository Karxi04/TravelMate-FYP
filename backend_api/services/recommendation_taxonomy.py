"""Explainable concept normalization for TravelMate recommendations.

This module deliberately uses a small, report-friendly taxonomy instead of an
opaque model.  Both preference phrases and provider categories are translated
to the same canonical concepts before FR04 calculates suitability.
"""

import re
import unicodedata


CONCEPT_TERMS = {
    'food': {
        'food', 'local food', 'local cuisine', 'cuisine', 'restaurant',
        'hawker', 'street food', 'cafe', 'coffee shop', 'food market',
        'food court', 'culinary',
    },
    'culture': {
        'culture', 'local culture', 'heritage', 'history', 'historical',
        'museum', 'temple', 'mosque', 'church', 'architecture',
        'historic site', 'religion', 'religious', 'art', 'gallery',
    },
    'nature': {
        'nature', 'park', 'beach', 'garden', 'botanic', 'botanical',
        'forest', 'hiking', 'outdoor', 'scenery', 'scenic', 'wildlife',
        'hill', 'waterfall',
    },
    'shopping': {
        'shopping', 'mall', 'market', 'retail', 'bazaar', 'night market',
        'shopping centre', 'shopping center',
    },
    'adventure': {
        'adventure', 'hiking', 'watersport', 'water sport',
        'outdoor activity', 'cycling', 'theme park', 'climbing', 'kayak',
    },
    'leisure': {
        'leisure', 'entertainment', 'nightlife', 'spa', 'relaxation',
        'relaxed', 'beach', 'theme park',
    },
    'photography': {
        'photography', 'photo', 'scenic', 'scenery', 'viewpoint',
        'architecture', 'street art',
    },
    'family': {
        'family', 'children', 'kids', 'wildlife', 'education',
        'educational', 'theme park', 'aquarium', 'zoo',
    },
    'social': {
        'social', 'nightlife', 'event', 'festival', 'night market',
        'food market',
    },
}

DISPLAY_NAMES = {
    'food': 'Food and local cuisine',
    'culture': 'Culture and heritage',
    'nature': 'Nature and outdoors',
    'shopping': 'Shopping',
    'adventure': 'Adventure',
    'leisure': 'Leisure and entertainment',
    'photography': 'Photography',
    'family': 'Family-friendly experiences',
    'social': 'Social experiences',
}


def normalize_phrase(value):
    raw = unicodedata.normalize('NFKD', str(value or ''))
    raw = ''.join(char for char in raw if not unicodedata.combining(char))
    return re.sub(r'[^a-z0-9]+', ' ', raw.lower()).strip()


def _values(value):
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if str(item or '').strip()]
    return [value] if str(value or '').strip() else []


def concepts_for(value):
    """Return canonical concepts represented by one or more text values."""
    concepts = set()
    for entry in _values(value):
        phrase = normalize_phrase(entry)
        if not phrase:
            continue
        padded = f' {phrase} '
        for concept, terms in CONCEPT_TERMS.items():
            if any(f' {normalize_phrase(term)} ' in padded for term in terms):
                concepts.add(concept)
    return concepts


def candidate_concepts(item):
    values = []
    for field in (
        'interests', 'tags', 'categories', 'category', 'type', 'subtype',
        'title', 'name', 'description',
    ):
        values.extend(_values((item or {}).get(field)))
    return concepts_for(values)


def display_concepts(concepts):
    return [DISPLAY_NAMES.get(value, value.replace('_', ' ').title())
            for value in sorted(set(concepts or []))]


def normalize_budget(value):
    phrase = normalize_phrase(value)
    if any(term in phrase for term in ('budget', 'free', 'cheap', 'low cost')):
        return 'budget'
    if any(term in phrase for term in ('premium', 'luxury', 'expensive')):
        return 'premium'
    if any(term in phrase for term in ('moderate', 'mid range', 'standard')):
        return 'moderate'
    return ''


def normalize_pace(value):
    phrase = normalize_phrase(value)
    if any(term in phrase for term in ('packed', 'active', 'fast')):
        return 'active'
    if any(term in phrase for term in ('relaxed', 'slow', 'easy')):
        return 'relaxed'
    if 'moderate' in phrase or 'balanced' in phrase:
        return 'moderate'
    return ''


def normalize_purpose(value):
    phrase = normalize_phrase(value)
    aliases = {
        'family': ('family',),
        'solo': ('solo',),
        'business': ('business', 'work'),
        'educational': ('education', 'educational', 'study'),
        'holiday': ('holiday', 'vacation', 'leisure'),
    }
    for canonical, terms in aliases.items():
        if any(term in phrase for term in terms):
            return canonical
    return ''


def normalize_personality(value):
    phrase = normalize_phrase(value)
    for canonical in ('explorer', 'planner', 'social', 'relaxed', 'balanced'):
        if canonical in phrase:
            return canonical
    return ''
