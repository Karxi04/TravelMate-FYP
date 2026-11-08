"""Read-only commerce labels shared by the two portals."""
from datetime import datetime, timedelta, timezone


def payment_label(value, order_status=''):
    status = str(value or '').lower()
    order = str(order_status or '').lower()
    if order in {'failed', 'checkout_failed', 'refunded', 'rejected', 'cancelled', 'checkout_cancelled', 'expired', 'checkout_expired'}:
        status = order
    if status in {'paid', 'succeeded', 'successful', 'completed', 'payment_verified'}:
        return 'Paid'
    if status == 'refunded':
        return 'Refunded'
    if status in {'failed', 'checkout_failed', 'payment_failed', 'requires_payment_method', 'rejected'}:
        return 'Failed'
    if status in {'cancelled', 'canceled', 'payment_cancelled'} or order in {'cancelled', 'checkout_cancelled'}:
        return 'Cancelled'
    if status in {'expired', 'checkout_expired'} or order in {'expired', 'checkout_expired'}:
        return 'Expired'
    return 'Pending'


def register_commerce_presentation(app):
    app.jinja_env.filters['payment_label'] = payment_label

    @app.context_processor
    def commerce_calendar():
        return {'malaysia_today': datetime.now(timezone(timedelta(hours=8))).date().isoformat()}
