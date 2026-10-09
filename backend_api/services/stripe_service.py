import os
import hashlib
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


def _payment_simulation_mode():
    """Keep payment simulation opt-in without changing other provider fallbacks."""
    explicit = os.getenv('PAYMENT_SIMULATION_MODE')
    if explicit is not None:
        return explicit.strip().lower() in {'1', 'true', 'yes', 'on'}
    return os.getenv('TRAVELMATE_TESTING', '').strip().lower() in {'1', 'true', 'yes'} and _fallback_mode()


def normalizePaymentStatus(status):
    value = str(status or 'unknown').strip().lower()
    aliases = {
        'successful': 'succeeded',
        'success': 'succeeded',
        'completed': 'succeeded',
        'canceled': 'cancelled',
    }
    return aliases.get(value, value)


def stripePaymentMode():
    key = os.getenv('STRIPE_SECRET_KEY', '').strip()
    if key.startswith('sk_test_'):
        return 'sandbox'
    if _payment_simulation_mode():
        return 'simulation'
    return 'unavailable'


def _setup():
    key = os.getenv('STRIPE_SECRET_KEY', '').strip()
    # TravelMate is an FYP/sandbox application. Never accept a live Stripe
    # secret, a publishable key, or an ambiguous generic sk_ credential.
    if not key.startswith('sk_test_'):
        return False
    stripe.api_key = key
    # Keep the provider mutation below the 90-second mobile mutation window and
    # do not let the SDK blindly retry mutations. TravelMate supplies an
    # explicit stable idempotency key when a mutation is safe to repeat.
    stripe.default_http_client = stripe.RequestsClient(timeout=75)
    stripe.max_network_retries = 0
    return True


def createPaymentSession(paymentInput, travellerId=None, bookingId='', idempotencyKey=None):
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
            idempotency_key=idempotencyKey,
            max_network_retries=0,
        )
    if _payment_simulation_mode():
        sim_id = _simulation_id(idempotencyKey)
        return SimulatedPaymentIntent(sim_id, int(round(amount * 100)), status='requires_payment_method')
    raise RuntimeError('Stripe sandbox is unavailable. Configure an sk_test_ credential or enable explicit simulation mode.')


def _simulation_id(idempotency_key):
    if idempotency_key:
        digest = hashlib.sha256(str(idempotency_key).encode('utf-8')).hexdigest()
        return f"pi_sim_{digest[:16]}"
    return f"pi_sim_{uuid.uuid4().hex[:16]}"


def processPaymentAttempt(paymentInput, travellerId, bookingId, idempotencyKey):
    """Create and confirm exactly one authoritative payment attempt."""
    has_live_key = _setup()
    amount = float(paymentInput.get('amount', 0))
    if has_live_key:
        return stripe.PaymentIntent.create(
            amount=int(round(amount * 100)),
            currency='myr',
            payment_method='pm_card_visa',
            payment_method_types=['card'],
            confirm=True,
            metadata={
                'travellerId': travellerId,
                'bookingId': bookingId,
                'mode': 'fyp-sandbox-test',
            },
            idempotency_key=idempotencyKey,
            max_network_retries=0,
        )
    if _payment_simulation_mode():
        sim_id = _simulation_id(idempotencyKey)
        return SimulatedPaymentIntent(sim_id, int(round(amount * 100)), status='succeeded')
    raise RuntimeError('Stripe sandbox is unavailable. Configure an sk_test_ credential or enable explicit simulation mode.')


def processSandboxPayment(paymentSessionId=None, paymentInput=None, travellerId=None, bookingId='', idempotencyKey=None):
    if paymentInput:
        travellerId = travellerId or paymentInput.get('travellerId', '')
        bookingId = bookingId or paymentInput.get('bookingId', '')
        return processPaymentAttempt(
            paymentInput,
            travellerId,
            bookingId,
            idempotencyKey,
        )

    if not paymentSessionId:
        raise ValueError('paymentSessionId is required')
    has_live_key = _setup()
    if has_live_key and not paymentSessionId.startswith('pi_sim_'):
        return stripe.PaymentIntent.retrieve(paymentSessionId)
    if _payment_simulation_mode():
        return SimulatedPaymentIntent(paymentSessionId, 0, status='succeeded')
    raise RuntimeError('Stripe sandbox is unavailable. Configure an sk_test_ credential or enable explicit payment simulation mode.')


def returnPaymentStatus(paymentSessionId):
    has_live_key = _setup()
    if has_live_key and not paymentSessionId.startswith('pi_sim_'):
        return stripe.PaymentIntent.retrieve(paymentSessionId).status
    if _payment_simulation_mode():
        return 'succeeded'
    raise RuntimeError('Stripe sandbox is unavailable. Configure an sk_test_ credential or enable explicit payment simulation mode.')


def create_intent(amount_rm, traveller_id, booking_id=''):
    return createPaymentSession({'amount': amount_rm}, traveller_id, booking_id)
