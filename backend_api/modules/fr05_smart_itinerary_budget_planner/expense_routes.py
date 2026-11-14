"""Traveller-entered expenses for ordinary itineraries."""
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import uuid4

from flask import g, jsonify, request
from auth_utils import auth_required
from services.packing_checklist_service import valid_trip_id
from sequence_contract.domain_functions import calculateBudget
from sequence_contract import firebase_firestore
from utils import utc_now_iso

from .routes import _is_package_trip, bp

CATEGORIES = ('Food', 'Transportation', 'Accommodation', 'Activities', 'Shopping', 'Other')


class ExpenseError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _minor(value, *, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)) or len(str(value)) > 24:
        raise ExpenseError('Enter a valid MYR amount with up to two decimal places.')
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ExpenseError('Enter a valid MYR amount with up to two decimal places.') from None
    if (not amount.is_finite() or amount < 0 or (not allow_zero and amount == 0)
            or amount > 1_000_000 or amount.as_tuple().exponent < -2):
        raise ExpenseError('Enter a valid MYR amount with up to two decimal places.')
    return int(amount * 100)


def _expense(data, trip):
    if not isinstance(data, dict) or set(data) - {'name', 'category', 'amount', 'currency', 'description', 'date', 'type'}:
        raise ExpenseError('Use the supported expense fields.')
    name, description = data.get('name'), data.get('description', '')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise ExpenseError('Use an expense name of 1–100 characters.')
    if not isinstance(description, str) or len(description) > 500:
        raise ExpenseError('Use at most 500 characters for the description.')
    if data.get('category') not in CATEGORIES or data.get('type') not in ('planned', 'actual'):
        raise ExpenseError('Choose a category and an expense type.')
    if data.get('currency', 'MYR') != 'MYR':
        raise ExpenseError('Expenses use MYR.')
    day = data.get('date')
    if day is not None:
        try:
            day = date.fromisoformat(day).isoformat()
            if day != data['date'] or not trip['startDate'][:10] <= day <= trip['endDate'][:10]:
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise ExpenseError('Choose a date within this trip.') from None
    return {'name': name.strip(), 'description': description.strip(), 'date': day,
            'category': data['category'], 'type': data['type'], 'currency': 'MYR',
            'amountMinor': _minor(data.get('amount'))}


def expense_overview(trip, paid_orders, committed_hotel=0):
    estimate = calculateBudget(trip)
    entries = trip.get('manualExpenses', [])
    total = {kind: sum(row['amountMinor'] for row in entries if row['type'] == kind)
             for kind in ('planned', 'actual')}
    limit = int(round(estimate['limit'] * 100))
    return {'currency': 'MYR', 'budgetLimitMinor': limit, 'systemEstimateMinor': int(round(estimate['total'] * 100)),
            'verifiedMinor': sum(order['amountMinor'] for order in paid_orders),
            'committedHotelMinor': committed_hotel,
            'plannedMinor': total['planned'], 'actualMinor': total['actual'],
            'balanceAfterRecordedActualMinor': limit - total['actual'] if limit > 0 else None,
            'unknownCategories': sorted(set(estimate['pendingExpenseCategories'] + estimate['excludedExpenseCategories']))}


def update_expenses(trip, payload, new_id):
    revision = trip.get('manualExpenseRevision', 0)
    if not isinstance(payload, dict) or type(payload.get('expectedRevision')) is not int:
        raise ExpenseError('Reload the trip budget before saving.')
    if payload['expectedRevision'] != revision:
        raise ExpenseError('The trip budget changed. Reload and try again.', 409)
    action = payload.get('action')
    now = utc_now_iso()
    patch = {'manualExpenseRevision': revision + 1, 'updatedAt': now}
    allowed = {'action', 'expectedRevision'}
    if action == 'limit' and set(payload) == allowed | {'budgetLimit', 'expectedBudgetLimit'}:
        if payload['expectedBudgetLimit'] != trip.get('budgetLimit', 0):
            raise ExpenseError('The trip budget limit changed. Reload and try again.', 409)
        patch['budgetLimit'] = _minor(payload['budgetLimit'], allow_zero=True) / 100
        patch['budgetEstimate'] = calculateBudget({**trip, **patch})
        return patch
    entries = list(trip.get('manualExpenses', []))
    if action == 'add' and set(payload) == allowed | {'expense'}:
        if len(entries) >= 200:
            raise ExpenseError('This trip already has 200 expenses.')
        entries.append({**_expense(payload['expense'], trip), 'id': new_id, 'createdAt': now, 'updatedAt': now})
    elif ((action == 'edit' and set(payload) == allowed | {'expenseId', 'expense'})
          or (action == 'delete' and set(payload) == allowed | {'expenseId'})):
        index = next((i for i, row in enumerate(entries) if row['id'] == payload['expenseId']), None)
        if index is None:
            raise ExpenseError('Expense not found.', 404)
        if action == 'delete':
            entries.pop(index)
        else:
            entries[index] = {**entries[index], **_expense(payload['expense'], trip), 'updatedAt': now}
    else:
        raise ExpenseError('Use a supported budget action.')
    patch['manualExpenses'] = entries
    return patch


def _verified_costs(db, transaction, iid, uid, trip):
    ids = {row.get('checkoutOrderId') for row in trip.get('purchasedPackages') or []
           if isinstance(row, dict) and valid_trip_id(row.get('checkoutOrderId'))}
    booking_id = trip.get('hotelBookingId')
    committed_hotel = 0
    hotel_payment = None
    if valid_trip_id(booking_id):
        snap = db.collection('hotel_bookings').document(booking_id).get(transaction=transaction)
        booking = snap.to_dict() or {}
        if booking.get('travellerId') == uid:
            if booking.get('saveDetailsOnly') or booking.get('confirmationLabel') == 'Hotel Details Saved':
                hotel_payment = {'status': 'unpaid', 'hotelBookingId': booking_id}
                if booking.get('itineraryId') == iid and booking.get('itineraryAttachmentStatus') == 'succeeded':
                    from modules.fr08_hotel_booking.routes import _public_accepted_snapshot
                    hotel_payment['acceptedPrebook'] = _public_accepted_snapshot(booking.get('acceptedPrebookSnapshot'))
            if valid_trip_id(booking.get('checkoutOrderId')):
                ids.add(booking['checkoutOrderId'])
            if (booking.get('bookingStatus') in {'confirmed', 'paid'}
                    and booking.get('hotelCurrency') == 'MYR'
                    and booking.get('amountSource') in {'validated_offer', 'legacy_verified_myr'}
                    and not any(booking.get(key) for key in ('isSimulated', 'sandbox', 'isDemo'))
                    and booking.get('source') not in {'sandbox', 'sandbox_fixture', 'demo', 'emulator_fixture'}):
                try:
                    value = Decimal(str(booking.get('hotelCost')))
                    if value.is_finite() and 0 < value <= 1_000_000:
                        committed_hotel = int((value * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
                except InvalidOperation:
                    pass
    paid_orders = []
    for identity in sorted(key for key in ids if valid_trip_id(key)):
        snap = db.collection('checkout_orders').document(identity).get(transaction=transaction)
        order = snap.to_dict() or {}
        if (hotel_payment is not None and order.get('travellerId') == uid
                and order.get('quoteType') == 'hotel' and order.get('hotelBookingId') == booking_id
                and order.get('itineraryId') == iid):
            hotel_payment.update(status=order.get('status'), paymentStatus=order.get('paymentStatus'),
                                 orderId=identity)
        if (order.get('travellerId') == uid and order.get('status') == order.get('paymentStatus') == 'paid'
                and order.get('currency') == 'MYR' and type(order.get('amountMinor')) is int
                and order['amountMinor'] >= 0
                and (order.get('fulfilledTripId') == iid
                     or (valid_trip_id(booking_id) and order.get('hotelBookingId') == booking_id))):
            paid_orders.append(order)
    return paid_orders, committed_hotel, hotel_payment


def _transact_expenses(iid, uid, payload):
    from google.cloud import firestore

    db = firebase_firestore.get_db()
    ref = db.collection('itineraries').document(iid)
    new_id = uuid4().hex

    @firestore.transactional
    def commit(transaction):
        snap = ref.get(transaction=transaction)
        trip = snap.to_dict() if snap.exists else None
        if not trip or trip.get('travellerId') != uid:
            raise ExpenseError('Trip not found.', 404)
        if _is_package_trip(trip):
            raise ExpenseError('Manual expenses are available for ordinary saved trips.', 409)
        patch = update_expenses(trip, payload, new_id) if payload is not None else {}
        updated = {**trip, **patch}
        paid_orders, committed_hotel, hotel_payment = _verified_costs(db, transaction, iid, uid, trip)
        overview = expense_overview(updated, paid_orders, committed_hotel)
        if hotel_payment:
            overview['hotelPayment'] = hotel_payment
        if patch:
            transaction.update(ref, patch)
        return {'ok': True, 'expenses': updated.get('manualExpenses', []),
                'revision': updated.get('manualExpenseRevision', 0), 'overview': overview,
                'startDate': updated.get('startDate'), 'endDate': updated.get('endDate'),
                'budgetLimit': updated.get('budgetLimit', 0)}

    return commit(db.transaction())


@bp.route('/itineraries/<iid>/expenses', methods=['GET', 'PATCH'])
@auth_required(['traveller'])
def expenses(iid):
    try:
        if not valid_trip_id(iid):
            raise ExpenseError('Invalid trip ID.')
        payload = None
        if request.method == 'PATCH':
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                raise ExpenseError('Use a JSON object.')
        return jsonify(_transact_expenses(iid, g.uid, payload))
    except ExpenseError as error:
        return jsonify(ok=False, error=str(error)), error.status
    except Exception:
        return jsonify(ok=False, error='Trip budget is temporarily unavailable. Reload before trying again.'), 503
