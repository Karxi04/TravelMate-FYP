"""F3-P1A-R evidence, qualified for new candidates only (not stored snapshots).

Place IDs below establish reported provider-cache continuity, not external identity
verification. Only explicitly evidenced, universal grounds admission is automatic.
Tariffs remain research metadata: travellerCount alone establishes no age,
residency, visit-date price or ticket-product eligibility.
"""
from copy import deepcopy
from datetime import date
from math import asin, cos, isfinite, radians, sin, sqrt
import re
from urllib.parse import urlparse

from services.activity_pricing import PRICING_UNITS


CHECKED_AT = '2026-10-26'
REGISTRY = (
    {
        'venueId': 'local_botanical_gardens',
        'googlePlaceId': 'ChIJWeDiIPHCSjAROzyNNz_QUx8',
        'aliases': ('Penang Botanic Gardens', 'Botanical Gardens Penang'),
        'coordinates': (5.4377324, 100.2906982), 'radiusMeters': 600,
        'ticketProductId': 'universal_free_admission', 'ticketProduct': 'General park entry',
        'unitPrice': 0.0, 'pricingUnit': 'per_person', 'currency': 'MYR',
        'applicability': 'applicable', 'eligibility': 'all_visitors',
        'priceSourceUrl': 'https://botanicalgardens.penang.gov.my/index.php/hubungi-kami/soalan-lazim-faq',
        'verifiedAt': '2026-11-08', 'openingHours': '06:30-19:30',
        'limitations': 'General entry only. Official tram availability statements conflict; availability and optional charges are not established.',
    },
    {
        'venueId': 'local_kek_lok_si', 'googlePlaceId': 'ChIJZYb8XRjCSjARxD5Df-qEkCw',
        'aliases': ('Kek Lok Si Temple',),
        'coordinates': (5.3996413, 100.2736126), 'radiusMeters': 400,
        'ticketProductId': 'temple_grounds_free', 'ticketProduct': 'Main temple grounds admission',
        'unitPrice': 0.0, 'pricingUnit': 'per_person', 'currency': 'MYR',
        'applicability': 'applicable', 'eligibility': 'all_visitors',
        'priceSourceUrl': 'https://mypenang.gov.my/view_directory.php?id=c2pkMG9tMEw2UUwzUk1hVTNWV3ZXZz09',
        'limitations': 'Grounds only. Optional pagoda and lift access are separate, excluded and unpriced here; reported optional tariffs disagree.',
    },
    {
        'venueId': 'local_peranakan_mansion', 'googlePlaceId': 'ChIJCWvz3I_DSjAR5hveCXjdfIs',
        'aliases': ('Pinang Peranakan Mansion',),
        'coordinates': (5.4178275, 100.3412046), 'radiusMeters': 250,
        'ticketProductId': 'adult_admission', 'ticketProduct': 'Adult mansion admission with tour',
        'unitPrice': 30.0, 'pricingUnit': 'per_person', 'currency': 'MYR',
        'applicability': 'conditional', 'eligibility': 'adult_tariff_only',
        'priceSourceUrl': 'http://pinangperanakanmansion.com.my/',
        'limitations': 'Research reports adult RM30, child 6-12 RM18 and under-6 free. Adult/child age-12 boundary is ambiguous in the research. Group ages and applicable tickets are not established.',
    },
    {
        'venueId': 'the_top_penang', 'googlePlaceId': 'ChIJ-8pjzpXDSjARhqQbf7o4ang',
        'aliases': ('The TOP Penang (Komtar)', 'The TOP Penang', 'The TOP Penang, Theme Park Penang', 'Windows of The TOP'),
        'coordinates': (5.4144544, 100.3295496), 'radiusMeters': 350,
        'ticketProductId': 'windows_of_the_top_adult',
        'ticketProduct': 'Windows of The TOP: Rainbow Skywalk + Observatory Deck adult pass',
        'unitPrice': 78.0, 'pricingUnit': 'per_person', 'currency': 'MYR',
        'applicability': 'conditional', 'eligibility': 'specific_adult_pass_only',
        'priceSourceUrl': 'https://thetop.com.my/product/ticket-1/',
        'limitations': 'Research adult 13+ RM78; child/senior/OKU RM58. Venue identity does not select this pass. Other attractions and passes are separate; group eligibility is unknown.',
    },
    {
        'venueId': 'local_penang_hill', 'googlePlaceId': 'ChIJQ-rUOIfCSjARuSuxHi7HYvg',
        'aliases': ('Penang Hill', 'Penang Hill Funicular Railway'),
        'coordinates': (5.4084613, 100.2773317), 'radiusMeters': 500,
        'ticketProductId': 'standard_adult_return', 'ticketProduct': 'Normal-lane international adult funicular return',
        'unitPrice': 40.0, 'pricingUnit': 'per_person', 'currency': 'MYR',
        'applicability': 'conditional', 'eligibility': 'residency_age_lane_and_return_ticket_required',
        'priceSourceUrl': 'https://www.penanghill.gov.my/index.php/en/tickets',
        'limitations': 'Research international adult RM40 / MyKad adult RM16; child/senior/lane tiers differ. Generic hill access is not a funicular purchase. The Habitat is separate.',
    },
    {
        'venueId': 'local_wonderfood', 'googlePlaceId': 'ChIJv4nHaI7DSjAR8peeKMlaKok',
        'aliases': ('Wonderfood Museum', 'Wonderfood Museum Penang'),
        'coordinates': (5.4163117, 100.3411846), 'radiusMeters': 200,
        'ticketProductId': 'standard_adult', 'ticketProduct': 'International adult museum admission',
        'unitPrice': 30.0, 'pricingUnit': 'per_person', 'currency': 'MYR',
        'applicability': 'conditional', 'eligibility': 'residency_and_age_required',
        'priceSourceUrl': 'https://mypenang.gov.my/',
        'limitations': 'Research international adult RM30 / MyKad adult RM20; child/senior tiers differ. A homepage link is not a newly verified applicable quote.',
    },
    {
        'venueId': 'local_esc', 'googlePlaceId': 'ChIJdd8lXaTDSjARYLK8T3hGW-U',
        'aliases': ('ESCAPE Penang',),
        'coordinates': (5.4497405, 100.214038), 'radiusMeters': 500,
        'ticketProductId': 'big_kid_walkin_ceiling', 'ticketProduct': 'Research adult day-pass tariff, not a quote',
        'unitPrice': 184.0, 'pricingUnit': 'per_person', 'currency': 'MYR',
        'applicability': 'conditional', 'eligibility': 'visit_date_age_and_purchase_channel_required',
        'priceSourceUrl': 'https://www.escape.my/penang',
        'limitations': 'Dynamic advance-booking prices; research RM184 is neither a guaranteed price nor a universal ceiling. Obtain a date-specific applicable quote.',
    },
    {
        'venueId': 'local_chew_jetty', 'googlePlaceId': 'ChIJ50W1D43DSjARlPqYV1MqscE',
        'aliases': ('Chew Jetty',),
        'coordinates': (5.4127175, 100.3397723), 'radiusMeters': 300,
        'ticketProductId': 'public_boardwalk_free', 'ticketProduct': 'Public boardwalk admission',
        'unitPrice': 0.0, 'pricingUnit': 'per_person', 'currency': 'MYR',
        'applicability': 'unverified', 'eligibility': 'explicit_authoritative_free_entry_evidence_missing',
        'priceSourceUrl': 'https://mypenang.gov.my/explore/directory/684/chew-jetty/',
        'limitations': 'Research claims free access, but the cited entry was inaccessible and explicit authoritative free-entry text was not established. Food and souvenirs are not admission.',
    },
    {
        'venueId': 'local_cheong_fatt_tze', 'googlePlaceId': None,
        'aliases': ('Cheong Fatt Tze - The Blue Mansion',),
        'coordinates': (5.4215, 100.3347), 'radiusMeters': 250,
        'ticketProductId': 'adult_tour', 'ticketProduct': 'Timed adult guided mansion tour',
        'unitPrice': 25.0, 'pricingUnit': 'per_person', 'currency': 'MYR',
        'applicability': 'unverified', 'eligibility': 'venue_identity_tour_and_age_unverified',
        'priceSourceUrl': 'https://www.cheongfatttzemansion.com/',
        'limitations': 'No verified provider-cache Place ID. Research adult RM25 / child RM12.50; hotel accommodation is not this guided tour. Manual evidence confirmation required.',
    },
)


def _name(value):
    return ' '.join(re.findall(r'\w+', str(value or '').casefold()))


def _valid_record(record):
    try:
        amount = record['unitPrice']
        date.fromisoformat(CHECKED_AT)
        source = urlparse(record['priceSourceUrl'])
        return (not isinstance(amount, bool) and isfinite(amount) and amount >= 0
                and record['currency'] == 'MYR' and record['pricingUnit'] in PRICING_UNITS
                and source.scheme in {'http', 'https'} and bool(source.netloc)
                and bool(record['ticketProductId']) and bool(record['eligibility'])
                and record['applicability'] in {'applicable', 'conditional', 'unverified'}
                and (record['applicability'] != 'applicable'
                     or (amount == 0 and record['eligibility'] == 'all_visitors')))
    except (KeyError, TypeError, ValueError):
        return False


def _nearby(item, record):
    gps = item.get('gps_coordinates') or item.get('gpsCoordinates') or {}
    try:
        lat, lon = float(gps['latitude']), float(gps['longitude'])
        if not isfinite(lat) or not isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            return False
        lat1, lon1, lat2, lon2 = map(radians, (lat, lon, *record['coordinates']))
        distance = 12742000 * asin(sqrt(min(1, sin((lat2-lat1)/2)**2
                                      + cos(lat1)*cos(lat2)*sin((lon2-lon1)/2)**2)))
        return distance <= record['radiusMeters']
    except (KeyError, TypeError, ValueError):
        return False


def enrich_candidate_pricing(candidate):
    """Copy and enrich a fresh candidate; never infer a paid ticket from a venue."""
    item = deepcopy(candidate)
    # Preserve specific existing pricing, including unresolved inputs; do not reprice snapshots.
    if (item.get('pricingUnit') or 'unitPrice' in item or 'pricingEvidence' in item
            or item.get('costCategory') not in (None, '', 'admission')):
        return item
    title = _name(item.get('title') or item.get('name'))
    ids = {str(item.get(key) or '') for key in ('place_id', 'googlePlaceId', 'destinationId', 'id')}
    identities = {value for value in ids if value.startswith(('ChIJ', 'local_'))}
    matches = []
    for record in REGISTRY:
        allowed = {record['venueId'], record['googlePlaceId']}
        if (not _valid_record(record) or title not in {_name(alias) for alias in record['aliases']}
                or (identities and not identities.issubset(allowed)) or not _nearby(item, record)
                or (item.get('ticketProductId') and item['ticketProductId'] != record['ticketProductId'])):
            continue
        if record['applicability'] == 'applicable' and not identities:
            continue
        experience = item.get('activityName') or item.get('ticketProduct') or item.get('experienceName')
        if experience and _name(experience) not in {_name(alias) for alias in (*record['aliases'], record['ticketProduct'])}:
            continue
        # Unverified provider identity cannot be promoted through a name-only match.
        if not record['googlePlaceId'] and record['venueId'] not in ids:
            continue
        matches.append(record)
    if len(matches) != 1:
        return item
    record = matches[0]
    evidence = {key: deepcopy(record[key]) for key in (
        'venueId', 'googlePlaceId', 'ticketProductId', 'ticketProduct', 'unitPrice',
        'pricingUnit', 'currency', 'applicability', 'eligibility', 'priceSourceUrl', 'limitations',
    )}
    checked_at = record.get('verifiedAt',CHECKED_AT)
    evidence.update({'priceVerifiedAt': checked_at, 'researchBatch': 'F3-P1A-R',
                     'identityEvidence': 'provider_cache_continuity_only' if record['googlePlaceId'] else 'unverified',
                     'matchedBy': 'known_id_and_exact_alias_and_coordinates' if identities else 'exact_alias_and_coordinates'})
    item['pricingEvidence'] = evidence
    if record['applicability'] == 'applicable':
        item.update({'pricingUnit': record['pricingUnit'], 'unitPrice': record['unitPrice'],
                     'estimatedCost': record['unitPrice'], 'costCategory': 'admission',
                     'costProvenance': 'verified_ticket', 'priceSourceUrl': record['priceSourceUrl'],
                     'priceVerifiedAt': checked_at, 'overlapsAllowance': False})
    if record.get('openingHours') and not item.get('openingHours') and not item.get('opening_hours'):
        item.update({'openingHours':record['openingHours'],'openingHoursSourceUrl':record['priceSourceUrl'],
                     'openingHoursVerifiedAt':checked_at})
    return item
