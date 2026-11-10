"""Read-only money projection; currency must belong to the recorded amount."""
from math import isfinite


def record_money(record, orders=None):
    amount = record_amount(record)
    amount_key = next((key for key in ('amount', 'totalAmount', 'groupTotal', 'hotelCost', 'price') if record.get(key) is not None), None)
    if amount_key == 'hotelCost' and record.get('hotelCurrency'):
        return amount, str(record['hotelCurrency']).strip().upper()
    currency = str(record.get('currency') or '').strip().upper()
    if currency and currency != 'UNKNOWN':
        return amount, currency
    # Pair the stored amount with its own validated currency, never a default MYR.
    if record.get('hotelCost') is not None and amount == record_amount({'amount': record['hotelCost']}):
        currency = str(record.get('hotelCurrency') or '').strip().upper()
        if currency and currency != 'UNKNOWN':
            return amount, currency
    for key in ('packageSnapshot', 'quoteSnapshot', 'acceptedPrebookSnapshot', 'selectedHotel', 'validatedOffer'):
        snapshot = record.get(key)
        if isinstance(snapshot, dict) and record_amount(snapshot) == amount and amount is not None:
            currency = str(snapshot.get('currency') or '').strip().upper()
            if currency and currency != 'UNKNOWN':
                return amount, currency
    reference = str(record.get('checkoutOrderId') or record.get('orderReference') or record.get('orderId') or '')
    order = (orders or {}).get(reference)
    if (order and record.get('travellerId') and order.get('travellerId') == record['travellerId'] and
            amount is not None and record_amount(order) == amount):
        currency = str(order.get('currency') or '').strip().upper()
        if currency and currency != 'UNKNOWN':
            return amount, currency
    return amount, 'UNKNOWN'


def record_amount(record):
    value=next((record[key] for key in ('amount','totalAmount','groupTotal','hotelCost','price') if record.get(key) is not None),None)
    try:
        amount=float(value)
        return amount if not isinstance(value,bool) and isfinite(amount) and amount >= 0 else None
    except (ValueError,TypeError,OverflowError):
        return None


def public_pricing_breakdown(value):
    if not isinstance(value, dict):
        return None
    result = {key: record_amount({'amount': value.get(key)}) for key in ('originalSubtotal', 'promotionDiscount', 'finalPayable')}
    if any(amount is None for amount in result.values()) or not isinstance(value.get('currency'), str):
        return None
    result['currency'] = value['currency']
    for key in ('pricingVersion', 'priceBasis', 'regularAdultUnitPrice', 'childUnitPrice', 'amountMinor', 'taxIncluded', 'taxNotes', 'stackingPolicy'):
        if key in value: result[key] = value[key]
    if isinstance(value.get('participants'), dict): result['participants'] = {k:value['participants'][k] for k in ('adults','children','total') if k in value['participants']}
    promotion = value.get('promotion') or {}
    result['promotion'] = {key: promotion[key] for key in ('id', 'campaignTitle', 'discountType', 'discountValue', 'source', 'promoCode', 'startDate', 'endDate', 'termsConditions')
                           if isinstance(promotion, dict) and isinstance(promotion.get(key), (str, int, float))}
    return result
