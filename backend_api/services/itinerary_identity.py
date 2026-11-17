"""Consolidate automatic candidates, never saved activities or recalculation inputs."""
from copy import deepcopy
from services.destination_candidates import same_place
from services.malaysian_locality import normalize_candidate_geography
from services.recommendation_taxonomy import normalize_phrase

IDENTITY_FIELDS = ('place_id', 'data_id', 'data_cid', 'canonicalAttractionId',
                   'attractionFamilyId', 'parentDestinationId', 'locationRole',
                   'independentSubAttraction', 'intentionalRepeat', 'supportingAccess',
                   'identityConsolidation', 'ticketProductId', 'ticketProduct')


def _name(row):
    return normalize_phrase(row.get('title') or row.get('name') or row.get('activityName'))


def _repeat(row):
    return row.get('intentionalRepeat') is True


def _ticket(row):
    evidence = row.get('pricingEvidence')
    if (row.get('costProvenance') == 'verified_ticket' and isinstance(evidence, dict)
            and evidence.get('applicability') == 'applicable'
            and row.get('priceSourceUrl') and row.get('priceVerifiedAt')):
        return evidence.get('ticketProductId') or row.get('ticketProductId')
    return None


def _same(a, b):
    # Explicit independent experiences can have separate applicable tickets at one venue.
    if ((a.get('independentSubAttraction') is True or b.get('independentSubAttraction') is True)
            and _ticket(a) and _ticket(b) and _ticket(a) != _ticket(b)):
        return False
    fields = ('destinationId', 'place_id', 'data_id', 'data_cid', 'canonicalAttractionId')
    if {str(a[k]) for k in fields if a.get(k)} & {str(b[k]) for k in fields if b.get(k)}:
        return True
    if a.get('independentSubAttraction') is True or b.get('independentSubAttraction') is True:
        return False
    if _name(a) in {'park', 'temple', 'museum', 'mosque', 'beach', 'viewpoint', 'viewing area', 'station'}:
        return False
    if not same_place({**a, 'title': _name(a)}, {**b, 'title': _name(b)}):
        return False
    ga, gb = normalize_candidate_geography(a), normalize_candidate_geography(b)
    # Matching generic names without geographic evidence are not proof of identity.
    if ga.get('conflict') or gb.get('conflict') or not ga.get('state') or ga.get('state') != gb.get('state'):
        return False
    if not (ga.get('latitude') is not None and gb.get('latitude') is not None):
        if not ga.get('city') or ga.get('city') != gb.get('city'):
            return False
    return True


def _access_for(access, main):
    if main.get('locationRole') in {'access', 'entrance', 'boarding_station'}:
        return False
    if access.get('independentSubAttraction') is True or _repeat(access):
        return False
    # A distinct verified charge remains a scheduled activity, not hidden access advice.
    if (access.get('priceVerified') is True or access.get('admissionPriceVerified') is True
            or access.get('costProvenance') == 'verified_ticket'):
        return False
    if access.get('locationRole') in {'access', 'entrance', 'boarding_station'}:
        parent = str(access.get('parentDestinationId') or '')
        if parent and parent in {str(main.get(k) or '') for k in
                                ('destinationId', 'place_id', 'data_id', 'canonicalAttractionId')}:
            return True
        family = access.get('attractionFamilyId')
        if family and family == main.get('attractionFamilyId') and main.get('locationRole') == 'main':
            return True
    # PHC identifies the Lower Station as the funicular terminus at the foot of the hill:
    # https://www.penanghill.gov.my/index.php/en/direction (checked 2026-11-17).
    # No timetable, fare, journey time or ticket entitlement is inferred from this relation.
    return (_name(access) in {'penang hill lower station', 'penang hill railway lower station'}
            and _name(main) in {'penang hill', 'bukit bendera'}
            and all(normalize_candidate_geography(row).get('state') == 'Penang'
                    and not normalize_candidate_geography(row).get('conflict') for row in (access, main)))


def consolidate_generated_candidates(candidates):
    kept = []
    for source in candidates:
        row = deepcopy(source)
        existing = next((old for old in kept if not _repeat(row) and not _repeat(old) and _same(old, row)), None)
        if existing is None:
            kept.append(row)
        else:
            existing.setdefault('identityConsolidation', []).append({
                'destinationId': row.get('destinationId') or row.get('place_id') or row.get('data_id') or row.get('id'),
                'sourceIds': {key: row[key] for key in ('place_id', 'data_id', 'data_cid') if row.get(key)},
                'title': row.get('title') or row.get('activityName'), 'reason': 'same_attraction'})
    output = []
    for row in kept:
        main = next((other for other in kept if other is not row and not _repeat(other) and _access_for(row, other)), None)
        if main is None:
            output.append(row)
        else:
            main.setdefault('supportingAccess', []).append({
                'destinationId': row.get('destinationId') or row.get('place_id'),
                'title': row.get('title') or row.get('activityName'),
                'gps_coordinates': row.get('gps_coordinates') or {},
                'role': 'access', 'transportDetailsVerified': False,
                'note': 'Access point; confirm transport, journey time and any separate ticket cost before visiting.'})
    return output
