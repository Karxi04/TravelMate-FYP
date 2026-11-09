"""Evidence-based discovery selection; hybrid scoring and legacy thresholds stay intact."""
import re
from services.recommendation_taxonomy import concepts_for, candidate_concepts, normalize_phrase

DISCOVERY_MODE = 'relevant_v1'


def discovery_queries(preference, candidates):
    excluded = concepts_for(preference.get('excludedInterests') or [])
    requested = concepts_for(preference.get('interests') or []) - excluded
    covered = set()
    for item in candidates:
        did = str(item.get('destinationId') or item.get('id') or '')
        if (preference.get('destinationFeedback') or {}).get(did) == 'not_for_me':
            continue
        concepts = candidate_concepts(item)
        if not concepts & excluded:
            covered.update(concepts)
    missing = requested - covered
    queries = [query for concept,query in [('photography','street art'),('food','hawker centres')]
               if concept in missing]
    return queries or ['tourist attractions']


def discovery_annotations(item, preference):
    concepts = set(item.get('destinationConcepts') or [])
    requested = concepts_for(preference.get('interests') or [])
    if not requested and not preference.get('interests'):
        requested = concepts_for(preference.get('travelType'))
    matched = concepts & requested
    if not requested and not preference.get('interests'):
        affinities = preference.get('learnedAffinities') or {}
        matched = {key for key in concepts if isinstance(affinities.get(key),(int,float))
                   and not isinstance(affinities[key],bool) and affinities[key] >= .1}
    did = str(item.get('destinationId') or item.get('id') or '')
    excluded = concepts & concepts_for(preference.get('excludedInterests') or [])
    rejected = (preference.get('destinationFeedback') or {}).get(did) == 'not_for_me'
    food_type = None
    if 'food' in matched:
        text = normalize_phrase(' '.join(str(item.get(key) or '') for key in ('title','name','category','type','interests')))
        food_type = ('food_museum' if re.search(r'\bmuseum\b',text) else
                     'cooking' if re.search(r'\bcooking (class|school|workshop|experience)\b',text) else
                     'dining' if re.search(r'\b(hawker|restaurant|cafe|kopitiam|food (court|street|market))\b',text) else
                     'culinary_culture' if re.search(r'\b(spice|spices|garden)\b',text) else 'food_related')
    return {'discoveryEligible': bool(matched and not excluded and not rejected),
            'discoveryMatchedConcepts': sorted(matched) if not excluded and not rejected else [],
            'foodExperienceType': food_type}
