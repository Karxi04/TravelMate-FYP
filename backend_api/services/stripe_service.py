import os
import stripe

def _setup():
    key=os.getenv('STRIPE_SECRET_KEY','').strip()
    if not key: raise RuntimeError('STRIPE_SECRET_KEY is not configured')
    stripe.api_key=key

def createPaymentSession(paymentInput, travellerId=None, bookingId=''):
    _setup()
    amount=float(paymentInput.get('amount',0) if isinstance(paymentInput,dict) else paymentInput)
    travellerId=travellerId or (paymentInput.get('travellerId','') if isinstance(paymentInput,dict) else '')
    bookingId=bookingId or (paymentInput.get('bookingId','') if isinstance(paymentInput,dict) else '')
    return stripe.PaymentIntent.create(amount=int(round(amount*100)),currency='myr',metadata={'travellerId':travellerId,'bookingId':bookingId},automatic_payment_methods={'enabled':True})

def processSandboxPayment(paymentSessionId=None, paymentInput=None, travellerId=None, bookingId=''):
    _setup()
    if paymentInput:
        amount=float(paymentInput.get('amount',0)); travellerId=travellerId or paymentInput.get('travellerId',''); bookingId=bookingId or paymentInput.get('bookingId','')
        return stripe.PaymentIntent.create(amount=int(round(amount*100)),currency='myr',payment_method='pm_card_visa',payment_method_types=['card'],confirm=True,metadata={'travellerId':travellerId,'bookingId':bookingId,'mode':'fyp-sandbox-test'})
    if not paymentSessionId: raise ValueError('paymentSessionId is required')
    return stripe.PaymentIntent.retrieve(paymentSessionId)

def returnPaymentStatus(paymentSessionId):
    _setup(); return stripe.PaymentIntent.retrieve(paymentSessionId).status

# Backward aliases
def create_intent(amount_rm, traveller_id, booking_id=''):
    return createPaymentSession({'amount':amount_rm},traveller_id,booking_id)
