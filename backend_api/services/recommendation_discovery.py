"""Evidence-based discovery selection; hybrid scoring and legacy thresholds stay intact."""
import re
from services.recommendation_taxonomy import concepts_for, candidate_concepts, normalize_phrase

DISCOVERY_MODE = 'relevant_v1'

# Exact place aliases only. Geography must independently resolve to Penang.
_PENANG_EVIDENCE = (
    (('armenian street', 'lebuh armenian', 'armenian street street art'),
     'Heritage street art', 'George Town heritage street with murals and street photography.',
     ('photography', 'culture'), 'https://mypenang.gov.my/view_directory.php?id=THVMRHBRb2V2ODlQc3hRTEkvalB4QT09'),
    (('pinang peranakan mansion', 'penang peranakan mansion'),
     'Heritage museum', 'Peranakan museum in a heritage mansion. The venue restricts indoor photography.',
     ('culture',), 'https://www.pinangperanakanmansion.com.my/'),
    (('penang botanic gardens', 'penang botanical gardens', 'taman botani pulau pinang'),
     'Botanical garden', 'Botanical gardens with tropical plants and wildlife for nature photography.',
     ('nature', 'photography'), 'https://www.mypenang.gov.my/view_directory.php?id=bDg0Kzh2NEs2UTdJNnpacitRUnlkdz09'),
    (('penang national park', 'taman negara pulau pinang'),
     'National park', 'Coastal trails and beaches around Teluk Bahang for landscape photography.',
     ('nature', 'adventure', 'photography'), 'https://mypenang.gov.my/uploads/downloads/SFA_Teluk-Bahang_Eng_V03Aug24.pdf'),
    (('escape penang',),
     'Adventure theme park', 'Outdoor adventure park with water rides and climbing activities.',
     ('adventure', 'family', 'leisure'), 'https://www.escape.my/pg/activities'),
    (('gurney plaza',),
     'Shopping mall', 'Shopping mall with a food hall and restaurant directory.',
     ('shopping', 'food'), 'https://gurneyplaza.com.my/store/gurney-food-hall/'),
    (('entopia by penang butterfly farm', 'entopia butterfly farm', 'entopia', 'penang butterfly farm'),
     'Butterfly garden', 'Butterfly garden and indoor exhibits in Teluk Bahang. The venue permits personal photography.',
     ('nature', 'family', 'photography'), 'https://www.entopia.com/faq/'),
)
_EVIDENCE_BY_ALIAS = {alias: (category, description, concepts, url)
                      for aliases, category, description, concepts, url in _PENANG_EVIDENCE for alias in aliases}
_GENERIC_CATEGORY = {'', 'attraction', 'tourist attraction', 'point of interest', 'establishment', 'place'}

_NON_VISITOR_CATEGORY = re.compile(
    r'\b(?:manufacturer|manufacturing|wholesaler|industrial supplier|building materials|'
    r'glass supplier|glass shop|aluminium supplier|aluminum supplier|contractor|corporate office)\b'
)
_GLAZING_TRADE_NAME = re.compile(r'\bglass (?:and )?(?:aluminium|aluminum)\b')


def is_planning_candidate(item):
    """Reject specific trade evidence without excluding visitor-facing shops or food."""
    types = item.get('types')
    categories = [item.get('category'), item.get('type'),
                  *(types if isinstance(types, (list, tuple)) else [types])]
    if any(_NON_VISITOR_CATEGORY.search(normalize_phrase(value)) for value in categories if value):
        return False
    title = normalize_phrase(item.get('title') or item.get('name'))
    return not _GLAZING_TRADE_NAME.search(title) or any(
        term in title.split() for term in ('museum', 'gallery', 'workshop')
    )


def enrich_discovery_candidate(item):
    """Keep provider fields intact and attach separately sourced scoring evidence."""
    geography = item.get('normalizedGeography') or {}
    alias = normalize_phrase(item.get('title') or item.get('name'))
    evidence = _EVIDENCE_BY_ALIAS.get(alias)
    result = {key: value for key, value in item.items() if key != 'verifiedDestinationEvidence'}
    if not evidence or geography.get('state') != 'Penang' or geography.get('conflict'):
        return result
    category, description, concepts, source_url = evidence
    provider_category = normalize_phrase(item.get('category') or item.get('type'))
    original_description = normalize_phrase(item.get('description'))
    evidence = {'category': category, 'description': description, 'concepts': list(concepts),
                'sourceUrl': source_url, 'matchedAlias': alias}
    if alias in {'pinang peranakan mansion', 'penang peranakan mansion'}:
        evidence['excludedConcepts'] = ['photography']
    if alias == 'gurney plaza':
        evidence['foodExperienceType'] = 'dining'
    result['verifiedDestinationEvidence'] = evidence
    if provider_category in _GENERIC_CATEGORY:
        evidence['suppliesCategory'] = True
    if original_description in _GENERIC_CATEGORY | {
        normalize_phrase(item.get('address')), normalize_phrase(item.get('type')),
    }:
        evidence['suppliesDescription'] = True
    return result


def discovery_queries(preference, candidates):
    excluded = concepts_for(preference.get('excludedInterests') or [])
    requested = concepts_for(preference.get('interests') or []) - excluded
    covered = set()
    for item in candidates:
        did = str(item.get('destinationId') or item.get('id') or '')
        if (preference.get('destinationFeedback') or {}).get(did) == 'not_for_me':
            continue
        concepts = candidate_concepts(enrich_discovery_candidate(item))
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
        food_type = (item.get('verifiedDestinationEvidence') or {}).get('foodExperienceType') or food_type
    return {'discoveryEligible': bool(matched and not excluded and not rejected),
            'discoveryMatchedConcepts': sorted(matched) if not excluded and not rejected else [],
            'foodExperienceType': food_type}
