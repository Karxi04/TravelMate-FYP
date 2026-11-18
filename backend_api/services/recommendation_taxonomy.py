"""Explainable concept normalization for TravelMate recommendations.

This module deliberately uses a small, report-friendly taxonomy instead of an
opaque model.  Both preference phrases and provider categories are translated
to the same canonical concepts before FR04 calculates suitability.
"""

import re
import unicodedata

# Provider identifiers describe an experience, never affordability, pace or access.
# IDs follow Google's Places category vocabulary; SerpApi also returns type/type_ids.
PROVIDER_CATEGORIES = {
    'restaurant': ('dining', {'food'}), 'pizza_restaurant': ('dining', {'food'}),
    'food_court': ('dining', {'food'}), 'cafe': ('cafe', {'food'}),
    'market': ('market', {'shopping'}), 'shopping_mall': ('shopping', {'shopping'}),
    'night_market': ('night_market', {'shopping', 'social'}),
    'museum': ('museum', {'culture'}), 'art_museum': ('art_museum', {'culture'}),
    'art_gallery': ('art_gallery', {'culture'}), 'historical_landmark': ('heritage', {'culture'}),
    'cultural_landmark': ('heritage', {'culture'}), 'cultural_center': ('culture', {'culture'}),
    'hindu_temple': ('religious_site', {'culture'}), 'mosque': ('religious_site', {'culture'}),
    'botanical_garden': ('botanical_garden', {'nature'}), 'garden': ('garden', {'nature'}),
    'national_park': ('national_park', {'nature'}), 'park': ('park', {'nature'}),
    'hiking_area': ('hiking', {'nature', 'adventure'}), 'beach': ('beach', {'nature', 'leisure'}),
    'observation_deck': ('viewpoint', {'photography'}), 'scenic_spot': ('viewpoint', {'photography'}),
    'wildlife_park': ('wildlife', {'nature'}), 'zoo': ('zoo', {'family'}),
    'aquarium': ('aquarium', {'family'}), 'amusement_park': ('theme_park', {'adventure', 'family', 'leisure'}),
    'adventure_sports_center': ('adventure_sports', {'adventure'}),
    'community_center': ('community', {'social'}), 'event_venue': ('event_venue', {'social'}),
}


def provider_categories(item):
    values = [item.get('type_id'), *(item.get('type_ids') if isinstance(item.get('type_ids'), list) else [])]
    return sorted({value for value in values if isinstance(value, str) and value in PROVIDER_CATEGORIES})


def experience_types(item):
    types = {PROVIDER_CATEGORIES[key][0] for key in provider_categories(item)}
    text = normalize_phrase(' '.join(str(item.get(k) or '') for k in ('category', 'type', 'subtype')))
    evidence = item.get('verifiedDestinationEvidence') or {}
    if evidence.get('suppliesCategory'):
        text += ' ' + normalize_phrase(evidence.get('category'))
    if not types and all(normalize_phrase(item.get(key)) in {
            'nature', 'culture', 'shopping', 'attraction', 'tourist attraction', ''}
            for key in ('category', 'type', 'subtype')):
        text += ' ' + normalize_phrase(item.get('title') or item.get('name') or item.get('activityName'))
    for phrase, kind in (('botanical', 'botanical_garden'), ('botanic', 'botanical_garden'),
                        ('national park', 'national_park'), ('hiking', 'hiking'), ('beach', 'beach'),
                        ('wildlife', 'wildlife'), ('viewpoint', 'viewpoint'), ('museum', 'museum'),
                        ('heritage', 'heritage'), ('temple', 'religious_site'), ('street art', 'street_art'),
                        ('hawker', 'dining'), ('restaurant', 'dining'), ('night market', 'night_market'),
                        ('shopping mall', 'shopping'), ('art gallery', 'art_gallery')):
        if phrase in text:
            types.add(kind)
    return sorted(types)


CONCEPT_TERMS = {
    'food': {
        'food', 'local food', 'local cuisine', 'cuisine', 'restaurant',
        'hawker', 'street food', 'cafe', 'coffee shop', 'food market',
        'food court', 'culinary', 'restaurants', 'food street', 'food streets',
        'hawker centre', 'hawker center', 'kopitiam', 'medan selera', 'pasar makanan',
        'cooking class', 'cooking school', 'cooking workshop',
    },
    'culture': {
        'culture', 'local culture', 'heritage', 'history', 'historical',
        'museum', 'temple', 'mosque', 'church', 'architecture',
        'historic site', 'religion', 'religious', 'art', 'gallery', 'cultural', 'museums',
    },
    'nature': {
        'nature', 'park', 'beach', 'garden', 'botanic', 'botanical',
        'forest', 'hiking', 'outdoor', 'scenery', 'scenic', 'wildlife',
        'hill', 'waterfall', 'parks', 'gardens',
    },
    'shopping': {
        'shopping', 'mall', 'market', 'retail', 'bazaar', 'night market',
        'shopping centre', 'shopping center',
    },
    'adventure': {
        'adventure', 'hiking', 'watersport', 'water sport',
        'outdoor activity', 'outdoor activities', 'cycling', 'theme park', 'climbing', 'kayak', 'watersports', 'theme parks',
    },
    'leisure': {
        'leisure', 'entertainment', 'nightlife', 'spa', 'relaxation',
        'relaxed', 'beach', 'theme park',
    },
    'photography': {
        'photography', 'photo', 'scenic', 'scenery', 'viewpoint',
        'architecture', 'street art', 'photogenic', 'street photography',
        'viewpoints', 'panoramic view', 'panoramic views', 'murals', 'mural',
    },
    'family': {
        'family', 'children', 'kids', 'education',
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
    for term in ('没有', '沒有', '不含'):
        raw = raw.replace(term, ' no ')
    # Bounded literal provider labels, not inferred attributes of tourist places.
    for term, alias in {'街头摄影':'street photography', '街頭攝影':'street photography',
                        '摄影':'photography', '攝影':'photography', '观景台':'viewpoint', '觀景台':'viewpoint',
                        '壁画':'mural', '壁畫':'mural', '美食街':'food street', '美食':'food',
                        '小贩中心':'hawker centre', '小販中心':'hawker centre', '茶室':'kopitiam',
                        '夜市':'night market'}.items():
        raw = raw.replace(term, ' ' + alias + ' ')
    raw = ''.join(char for char in raw if not unicodedata.combining(char))
    return re.sub(r'[^a-z0-9]+', ' ', raw.lower()).strip()


def _values(value):
    if isinstance(value,dict):
        return [value[key] for key in ('name','title','value') if value.get(key)]
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if str(item or '').strip()]
    return [value] if str(value or '').strip() else []


def concepts_for(value):
    """Return canonical concepts represented by one or more text values."""
    concepts = set()
    for entry in _values(value):
        if isinstance(entry,dict):
            concepts.update(concepts_for(_values(entry)))
            continue
        phrase = normalize_phrase(entry)
        if not phrase:
            continue
        padded = f' {phrase} '
        for concept, terms in CONCEPT_TERMS.items():
            searchable = re.sub(r'\b(theme parks?|car parks?)\b', '', padded) if concept == 'nature' else padded
            if any(f' {normalize_phrase(term)} ' in searchable for term in terms):
                concepts.add(concept)
    return concepts


# Conversational phrases describe traveller intent. Do not use them as evidence
# about a provider destination or its facilities.
PREFERENCE_PHRASES = {
    'photography': r'\b(?:tak(?:e|ing)|snap(?:ping)?) (?:some )?(?:pictures|photos)\b',
    'culture': r'\b(?:historical|old) (?:places|sites|buildings)\b',
    'family': r'\b(?:child|kid|family) friendly\b|\b(?:suitable|good) for (?:kids|children)\b',
    'leisure': r'\b(?:peaceful|quiet|unhurried|laid back|relaxing)\b',
}


def preference_concepts(value):
    result = set()
    for entry in _values(value):
        for clause in re.split(r'[.!?;,]|\bbut\b', str(entry).lower()):
            phrase = normalize_phrase(clause)
            if re.search(r'\b(?:avoid|do not|don t|dislike|without|no|not)\b', phrase):
                continue
            result.update(concepts_for(phrase))
            result.update(concept for concept, pattern in PREFERENCE_PHRASES.items()
                          if re.search(pattern, phrase))
    return result


def primary_concepts(item):
    values = []
    for field in (
        'interests', 'tags', 'categories', 'category', 'type', 'subtype',
        'title', 'name', 'destinationType', 'types',
    ):
        values.extend(_values((item or {}).get(field)))
    evidence = (item or {}).get('verifiedDestinationEvidence') or {}
    if evidence.get('suppliesCategory'):
        values.append(evidence['category'])
    provider = set().union(*(PROVIDER_CATEGORIES[key][1] for key in provider_categories(item))) if provider_categories(item) else set()
    concepts = concepts_for(values) | provider
    name_words = set(normalize_phrase((item or {}).get('title') or (item or {}).get('name')).split())
    marketing = {'nature','shopping','family','culture','food','social','leisure','photography','adventure'}
    if not provider and len(name_words & marketing) >= 3 and not concepts_for(' '.join(name_words - marketing)):
        concepts = concepts_for([v for field in ('category','type','tags','interests') for v in _values((item or {}).get(field))])
    if provider_categories(item):
        # Generic brand words do not extend an explicit provider category.
        factual = [v for field in ('interests','tags','categories','category','type','subtype','destinationType','types')
                   for v in _values((item or {}).get(field))]
        generic_title = {'nature','shopping','family','culture','food','social','leisure','photography','adventure'}
        title = normalize_phrase((item or {}).get('title') or (item or {}).get('name'))
        title = ' '.join(word for word in title.split() if word not in generic_title)
        concepts = concepts_for([*factual,title]) | provider
    text = normalize_phrase(' '.join(map(str, values)))
    if 'nature' not in provider and not concepts_for(re.sub(r'\b(?:theme|car) parks?\b','',text)) & {'nature'}:
        concepts.discard('nature')
    return concepts - set(evidence.get('excludedConcepts') or [])


def candidate_concepts(item):
    concepts = primary_concepts(item)
    # Generic marketing and nearby amenities are not evidence of the attraction's offering.
    generic = {'food','culture','history','nature','outdoor','leisure','relaxed','social','family',
               'children','kids','shopping','photo','art','education','educational','scenic','scenery','park','market'}
    description = str((item or {}).get('description') or '')
    if normalize_phrase(description) == normalize_phrase((item or {}).get('address')):
        description = ''
    for clause in re.split(r'[.;!?]', description):
        if re.search(r'\b(near|nearby|close to|walking distance)\b|附近|邻近|鄰近',clause,re.I):
            continue
        phrase = ' ' + normalize_phrase(clause) + ' '
        for concept,terms in CONCEPT_TERMS.items():
            searchable = re.sub(r'\b(theme parks?|car parks?)\b','',phrase) if concept=='nature' else phrase
            if any(not re.search(r'\b(no|not|without)(?: an?| any| actual| real)?\s*$',searchable[:match.start()])
                   for term in terms-generic
                   for match in re.finditer(r'\b'+re.escape(normalize_phrase(term))+r'\b',searchable)):
                concepts.add(concept)
    evidence = (item or {}).get('verifiedDestinationEvidence') or {}
    concepts.update(evidence.get('concepts') or [])
    return concepts - set(evidence.get('excludedConcepts') or [])


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


PLANNING_PREFERENCE_FIELDS = ('travelPersonality', 'sleepingType', 'travelType',
                              'interests', 'budgetRange', 'travelPace', 'travelPurpose')


def planning_preferences(profile):
    return {field: profile[field] for field in PLANNING_PREFERENCE_FIELDS
            if profile.get(field)}


def travel_style_suitability(style, item):
    style = normalize_phrase(style)
    count = item.get('reviews')
    # Review counts indicate relative visibility, not venue quality or crowd levels.
    if style == 'mixed' or item.get('ratingSource') != 'provider' or type(count) not in (int, float) or not 1 <= count <= 100000000:
        return .60, False
    if style == 'popular landmarks':
        return (.90 if count >= 1000 else .45 if count <= 100 else .60), True
    return (.90 if count <= 100 else .45 if count >= 1000 else .60), True
