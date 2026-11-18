"""Consolidate automatic candidates, never saved activities or recalculation inputs."""
from copy import deepcopy
from services.review_destination import review_destination_id
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


# PHC documents Bukit Bendera as Penang Hill and the Lower Station as its
# transport terminus. Pins for the main visit can refer to either end.
# https://www.penanghill.gov.my/index.php/en/direction
# https://www.penanghill.gov.my/index.php/ms/soalan-lazim
_HILL_NAMES = {'penang hill', 'bukit bendera', 'penang hill bukit bendera', 'bukit bendera penang hill'}
_STATION_NAMES = {'penang hill lower station', 'penang hill railway lower station',
                  'penang hill funicular lower station', 'stesen bawah bukit bendera'}


def _hill_area(row):
    geo = normalize_candidate_geography(row)
    lat, lon = geo.get('latitude'), geo.get('longitude')
    return (geo.get('state') == 'Penang' and not geo.get('conflict')
            and (5.40 <= lat <= 5.44 and 100.25 <= lon <= 100.285
                 if lat is not None and lon is not None else geo.get('city') == 'Air Itam'))


def _hill_main(row):
    return (row.get('locationRole') not in {'access', 'entrance', 'boarding_station'}
            and _name(row) in _HILL_NAMES and _hill_area(row))


_ID_FIELDS = ('destinationId', 'place_id', 'data_id', 'data_cid', 'canonicalAttractionId', 'id')
POLICY = 'trip-wide-v1'


def _identities(row):
    ids = {review_destination_id(str(row[key])) for key in _ID_FIELDS if row.get(key)}
    for duplicate in row.get('identityConsolidation') or []:
        if not isinstance(duplicate, dict):
            continue
        if duplicate.get('destinationId'):
            ids.add(review_destination_id(str(duplicate['destinationId'])))
        ids.update(review_destination_id(str(value))
                   for value in (duplicate.get('sourceIds') or {}).values() if value)
    return ids


def _separate_tickets(a, b):
    return bool((a.get('independentSubAttraction') is True or b.get('independentSubAttraction') is True)
                and _ticket(a) and _ticket(b) and _ticket(a) != _ticket(b))


def same_attraction(a, b):
    if _separate_tickets(a, b):
        return False
    if _identities(a) & _identities(b):
        return True
    if a.get('independentSubAttraction') is True or b.get('independentSubAttraction') is True:
        return False
    if _name(a) in {'park', 'temple', 'museum', 'mosque', 'beach', 'viewpoint', 'viewing area', 'station'}:
        return False
    if _name(a) in _HILL_NAMES and _name(b) in _HILL_NAMES and _hill_main(a) and _hill_main(b):
        return True
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
    return _name(access) in _STATION_NAMES and _hill_main(main) and _hill_area(access)


def consolidate_generated_candidates(candidates, *, automatic=False):
    kept = []
    for source in candidates:
        row = deepcopy(source)
        if automatic:
            # A source candidate cannot grant itself a confirmed repeat.
            row.pop('intentionalRepeat', None)
        matches = [old for old in kept if not _repeat(row) and not _repeat(old)
                   and same_attraction(old, row)]
        if not matches:
            kept.append(row)
            continue
        existing = matches[0]
        for duplicate in [row, *matches[1:]]:
            if _separate_tickets(existing, duplicate):
                continue
            aliases = existing.setdefault('identityConsolidation', [])
            aliases.append({
                'destinationId': duplicate.get('destinationId') or duplicate.get('place_id') or duplicate.get('data_id') or duplicate.get('id'),
                'sourceIds': {key: duplicate[key] for key in _ID_FIELDS if duplicate.get(key)},
                'reason': 'same_attraction',
            })
            aliases.extend(duplicate.get('identityConsolidation') or [])
            if duplicate is not row:
                kept.remove(duplicate)
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



def validate_generated_partition(candidates, scheduled, unscheduled):
    """The scheduler must account for each unique input exactly once across all days."""
    ids = [str(row.get('activityId')) for row in candidates]
    output = [str(row.get('activityId')) for row in [*scheduled, *unscheduled]]
    if len(ids) != len(set(ids)) or sorted(ids) != sorted(output):
        raise ValueError('Generated schedule contains inconsistent activity identifiers.')
