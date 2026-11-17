"""Extract a short public-fact overview; no reviews, AI, storage or provider requests."""
import html
import re


def _sentences(value):
    if isinstance(value, dict):
        value = value.get('overview') or value.get('snippet') or ''
    if not isinstance(value, str):
        return []
    text = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', '', value))).strip()
    sentences = re.split(r'(?<=[.!?])\s+', text)
    # Operational claims change independently; display them only in the dedicated evidence UI.
    unsafe = r'\b(ignore|instructions?|system prompt|reviews?|rated|rating|best time|crowd|accessible|accessibility|open daily|opens?|closes?|hours?|tickets?|admission|free entry|RM\s*\d|MYR|\d{1,2}:\d{2})\b'
    return [s for s in sentences if 8 <= len(s) <= 350 and not re.search(unsafe, s, re.I)]


def place_summary(place):
    facts, fields = [], []
    for key in ('description', 'editorial_summary', 'snippet', 'about'):
        values = _sentences(place.get(key))
        if values:
            facts.extend(s for s in values if s not in facts)
            fields.append(key)
            break  # Do not blend potentially conflicting descriptions.
    if not facts:
        category = str(place.get('category') or place.get('type') or '').strip().lower()
        allowed = {'museum', 'temple', 'mosque', 'beach', 'park', 'garden', 'shopping mall',
                   'shopping', 'nature reserve', 'art gallery', 'historical landmark', 'tourist attraction'}
        title = str(place.get('title') or place.get('name') or '').strip()
        if category in allowed and title and len(title) <= 150 and not place.get('metadataConflict'):
            facts = [f'{title} is listed as a {category}.']
            fields = ['title', 'category']
    text = ' '.join(facts[:3]) if facts else 'More information about this place is unavailable from the current source.'
    return {'text': text, 'additionalText': ' '.join(facts[3:6]), 'source': 'recorded_public_facts',
            'sourceFields': fields, 'facts': facts[:6], 'aiGenerated': False}
