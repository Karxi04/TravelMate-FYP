"""Extract a short public-fact overview; no reviews, AI, storage or provider requests."""
import html
import re


_FIELDS = ('descriptionDetails', 'description', 'editorial_summary', 'summary', 'snippet', 'about')
_CATEGORY_LABELS = {
    'museum': 'a museum', 'temple': 'a temple', 'mosque': 'a mosque',
    'beach': 'a beach', 'park': 'a park', 'garden': 'a garden',
    'shopping mall': 'a shopping mall', 'shopping': 'a shopping destination',
    'nature reserve': 'a nature reserve', 'art gallery': 'an art gallery',
    'historical landmark': 'a historical landmark', 'tourist attraction': 'a visitor attraction',
    'scenic attraction': 'a scenic attraction', 'scenic spot': 'a scenic spot',
    'places of interest': 'a point of interest', 'point of interest': 'a point of interest',
    'national park': 'a national park', 'hiking area': 'a hiking area',
    'observation deck': 'an observation deck', 'botanical garden': 'a botanical garden',
    'nature scenic attraction': 'a scenic nature attraction',
}
# Current operational claims belong in the dedicated evidence sections.
_NON_OVERVIEW = re.compile(
    r'\b(ignore|instructions?|system prompt|reviews?|rated|rating|best time|crowd(?:ed|s)?|'
    r'accessible|accessibility|open daily|opens?|closes?|hours?|tickets?|admission|free entry|'
    r'RM\s*\d|MYR|\d{1,2}:\d{2})\b|'
    r'^(discover the magic|a must.visit|an unforgettable experience|book now)\b', re.I)


def _sentences(value):
    if isinstance(value, dict):
        sections = [value.get(key) for key in ('overview', 'description', 'details', 'text', 'snippet')]
        return _distinct(sentence for section in sections if isinstance(section, str)
                         for sentence in _sentences(section))
    if not isinstance(value, str):
        return []
    text = re.sub(r'<[^>]*>', ' ', html.unescape(value[:16000])).strip()
    parts = re.split(r'(?<=[.!?])\s+|\n\s*\n', text)
    return _distinct(sentence for part in parts
                     if len(sentence := ' '.join(part.split())) >= 8 and not _NON_OVERVIEW.search(sentence))


def _distinct(sentences):
    result, seen = [], set()
    for sentence in sentences:
        key = re.sub(r'[^\w]+', ' ', sentence.lower()).strip()
        if key and key not in seen:
            seen.add(key)
            result.append(sentence)
    return result


def place_summary(place):
    facts, fields = [], []
    if not place.get('metadataConflict'):
        for key in _FIELDS:
            values = _sentences(place.get(key))
            # Choose the richest coherent source. Competing descriptions can disagree.
            if (len(values), sum(map(len, values))) > (len(facts), sum(map(len, facts))):
                facts, fields = values, [key]
        if not facts:
            for field in ('category', 'type'):
                category = re.sub(r'[^a-z]+', ' ', str(place.get(field) or '').lower()).strip()
                title = str(place.get('title') or place.get('name') or '').strip()
                if category in _CATEGORY_LABELS and title and len(title) <= 150:
                    facts = [f'{title} is listed as {_CATEGORY_LABELS[category]}.']
                    fields = ['title', field]
                    break
    text = ' '.join(facts[:3]) if facts else 'More information about this place is unavailable from the current source.'
    return {'text': text, 'additionalText': ' '.join(facts[3:]), 'source': 'recorded_public_facts',
            'sourceFields': fields, 'facts': facts, 'aiGenerated': False}
