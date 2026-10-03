import os
import uuid
import stripe


class SimulatedPaymentIntent:
    def __init__(self, id, amount, status='succeeded', client_secret=None):
        self.id = id
        self.amount = amount
        self.status = status
        self.client_secret = client_secret or f"{id}_secret_simulated"


def _fallback_mode():
    return os.getenv('FALLBACK_MODE', 'false').lower() in {'1', 'true', 'yes'}


def _setup():
    key = os.getenv('STRIPE_SECRET_KEY', '').strip()
    if not key or not key.startswith('sk_'):
        return False
    stripe.api_key = key
    return True


def createPaymentSession(paymentInput, travellerId=None, bookingId=''):
    has_live_key = _setup()
    amount = float(paymentInput.get('amount', 0) if isinstance(paymentInput, dict) else paymentInput)
    travellerId = travellerId or (paymentInput.get('travellerId', '') if isinstance(paymentInput, dict) else '')
    bookingId = bookingId or (paymentInput.get('bookingId', '') if isinstance(paymentInput, dict) else '')

    if has_live_key:
        return stripe.PaymentIntent.create(
            amount=int(round(amount * 100)),
            currency='myr',
            metadata={'travellerId': travellerId, 'bookingId': bookingId},
            automatic_payment_methods={'enabled': True},
        )
    if _fallback_mode():
        sim_id = f"pi_sim_{uuid.uuid4().hex[:16]}"
        return SimulatedPaymentIntent(sim_id, int(round(amount * 100)), status='requires_payment_method')
    raise RuntimeError('STRIPE_SECRET_KEY requires a secret key (sk_test_...), currently configured with publishable key (pk_test_...). Live Stripe blocked by credentials.')


def processSandboxPayment(paymentSessionId=None, paymentInput=None, travellerId=None, bookingId=''):
    has_live_key = _setup()
    if paymentInput:
        amount = float(paymentInput.get('amount', 0))
        travellerId = travellerId or paymentInput.get('travellerId', '')
        bookingId = bookingId or paymentInput.get('bookingId', '')
        if has_live_key:
            return stripe.PaymentIntent.create(
                amount=int(round(amount * 100)),
                currency='myr',
                payment_method='pm_card_visa',
                payment_method_types=['card'],
                confirm=True,
                metadata={'travellerId': travellerId, 'bookingId': bookingId, 'mode': 'fyp-sandbox-test'},
            )
        if _fallback_mode():
            sim_id = f"pi_sim_{uuid.uuid4().hex[:16]}"
            return SimulatedPaymentIntent(sim_id, int(round(amount * 100)), status='succeeded')
        raise RuntimeError('STRIPE_SECRET_KEY requires a secret key (sk_test_...), currently configured with publishable key (pk_test_...). Live Stripe blocked by credentials.')

    if not paymentSessionId:
        raise ValueError('paymentSessionId is required')
    if has_live_key and not paymentSessionId.startswith('pi_sim_'):
        return stripe.PaymentIntent.retrieve(paymentSessionId)
    return SimulatedPaymentIntent(paymentSessionId, 0, status='succeeded')


def returnPaymentStatus(paymentSessionId):
    has_live_key = _setup()
    if has_live_key and not paymentSessionId.startswith('pi_sim_'):
        return stripe.PaymentIntent.retrieve(paymentSessionId).status
    return 'succeeded'


def create_intent(amount_rm, traveller_id, booking_id=''):
    return createPaymentSession({'amount': amount_rm}, traveller_id, booking_id)
