"""Owner-scoped package retirement; retain identities and purchased history."""
from copy import deepcopy
from utils import utc_now_iso


def lifecycle_patch(current, actor, action, status):
    now = utc_now_iso()
    history = deepcopy(current.get('lifecycleHistory') or [])
    history.append({'action': action, 'actorId': actor, 'at': now,
                    'fromStatus': current.get('approvalStatus'), 'toStatus': status})
    return {'approvalStatus': status, 'updatedAt': now, 'lifecycleHistory': history}


def deletion_blocker(retrieve, package_id):
    dependencies = [
        ('checkout_orders', [('packageId', '==', package_id)], 'order history'),
        ('checkout_orders', [('packageSnapshot.packageId', '==', package_id)], 'order history'),
        ('package_checkout_attempts', [('packageId', '==', package_id)], 'payment attempts'),
        ('package_checkout_attempts', [('packageSnapshot.packageId', '==', package_id)], 'payment attempts'),
        ('payment_records', [('packageId', '==', package_id)], 'payment history'),
        ('payment_records', [('bookingId', '==', package_id), ('bookingType', '==', 'package')], 'payment history'),
        ('itineraries', [('packageId', '==', package_id)], 'saved Package Trips'),
        ('itineraries', [('packageSnapshot.packageId', '==', package_id)], 'saved Package Trips'),
        ('promotional_campaigns', [('packageId', '==', package_id)], 'promotional campaigns'),
        ('hotel_bookings', [('packageId', '==', package_id)], 'linked supplier bookings'),
    ]
    for collection, filters, label in dependencies:
        if retrieve(collection, filters=filters, limit=1):
            return f'This package has {label} and cannot be deleted. Keep it archived.'
    return None
