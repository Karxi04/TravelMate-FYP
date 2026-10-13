"""Server-owned package checkout preparation; Stripe activation is deliberately separate."""
from copy import deepcopy
from datetime import datetime, timezone

from services.public_content_projection import eligible_package

PACKAGE_FULFILLMENT_STATES = {
    'checkout_pending', 'payment_pending', 'payment_verified',
    'fulfillment_pending', 'fulfilled', 'fulfillment_failed',
    'payment_failed', 'payment_cancelled',
}


def prepare_package_snapshot(package, operator, quantity=1, now=None):
    if not eligible_package(package):
        raise ValueError('Package is not approved and available for checkout.')
    if not package.get('operatorId') or not operator:
        raise ValueError('Package operator could not be verified.')
    try:
        price = float(package.get('adultPrice', package.get('price')))
    except (TypeError, ValueError):
        raise ValueError('Package has no authoritative payable price.')
    currency = str(package.get('currency') or '').upper()
    if price < 0 or currency != 'MYR':
        raise ValueError('Package has no supported authoritative currency.')
    if package.get('taxIncluded') is None and not package.get('taxNotes'):
        raise ValueError('Package tax and fee treatment is not established.')
    if int(quantity) != 1:
        raise ValueError('Package quantity is not supported by the current contract.')
    return {
        'packageId': str(package.get('id') or ''), 'operatorId': str(package['operatorId']),
        'title': package.get('title') or package.get('packageTitle'),
        'destination': package.get('destination') or package.get('destinationName'),
        'durationDays': package.get('durationDays'), 'departureDates': deepcopy(package.get('departureDates') or []),
        'itineraryDays': deepcopy(package.get('itineraryDays') or []),
        'inclusions': deepcopy(package.get('inclusions') or []), 'exclusions': deepcopy(package.get('exclusions') or []),
        'accommodation': {k: package.get(k) for k in ('accommodationName', 'accommodationCategory', 'roomType', 'accommodationNotes')},
        'transport': {k: package.get(k) for k in ('transportTypes', 'transportNotes')},
        'price': price, 'currency': currency, 'taxIncluded': package.get('taxIncluded'), 'taxNotes': package.get('taxNotes'),
        'revision': package.get('updatedAt') or package.get('createdAt'),
        'snapshotCreatedAt': now or datetime.now(timezone.utc).isoformat(),
    }
