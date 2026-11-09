from datetime import datetime, timezone
from math import isfinite
from services.commerce_money import record_money, public_pricing_breakdown
from services.public_content_projection import active_campaign, eligible_package
from services.campaign_schedule import campaign_package_ids
from services.package_checkout_contract import build_initial_fulfillment_record, is_paid_order

RECORD_LIMIT = 500


def unique_package_orders(orders):
    seen_ids, seen_settlements = set(), set()
    # Prefer newer server records; without recency evidence a non-paid state is safer.
    ordered = sorted((o for o in orders if isinstance(o, dict)),
                     key=lambda o: (str(o.get('updatedAt') or o.get('createdAt') or ''), not is_paid_order(o)), reverse=True)
    for order in ordered:
        if not isinstance(order, dict) or _normalise(order.get('quoteType') or order.get('type')) != 'package':
            continue
        order_id = order.get('id')
        settlement = order.get('stripePaymentIntentId') or order.get('checkoutSessionId')
        key = (order.get('operatorId'), settlement)
        if (order_id and order_id in seen_ids) or (settlement and key in seen_settlements):
            continue
        if order_id:
            seen_ids.add(order_id)
        if settlement:
            seen_settlements.add(key)
        yield order


def _records(db, name, operator_id):
    query = db.collection(name)
    if operator_id:
        query = query.where('operatorId', '==', operator_id)
    docs = list(query.limit(RECORD_LIMIT + 1).stream())
    return [dict(doc.to_dict() or {}, id=doc.id) for doc in docs[:RECORD_LIMIT]], len(docs) > RECORD_LIMIT


def _normalise(value):
    return str(value or "").strip().lower()


def _safe_analytics_booking(order_data, include_fulfillment=False, requirement_context=None, trip_state=None):
    """
    Project a raw checkout_orders document to an operator-safe analytics booking projection.

    Allowlisted fields:
    - id / orderReference: Booking document identifier
    - packageId: Associated tourism package ID
    - packageTitle: Human-readable package title
    - operatorId: Owning operator UID
    - quoteType: 'package'
    - amount: Order monetary value
    - groupTotal: Total group booking amount
    - currency: Transaction currency (e.g. 'MYR')
    - status / orderStatus: Order lifecycle status
    - paymentStatus: Payment settlement status
    - fulfillmentStatus: Fulfillment status
    - departureDate: Selected departure date
    - groupSize: Total group size
    - adults: Number of adult participants
    - children: Number of child participants
    - testMode: Boolean flag indicating test payment provider
    - supplierReservationStatus: Reservation status
    - createdAt: Creation timestamp
    - updatedAt: Last updated timestamp

    Strictly excluded:
    - checkoutUrl (Stripe Checkout direct session URL)
    - checkoutSessionId (Stripe session identifier)
    - providerIdempotencyKey (Idempotency key containing internal UUIDs)
    - stripePaymentIntentId, stripeSessionId, clientSecret, paymentMethodId (Payment secrets)
    - travellerId (Personal identity / user account ID of traveller)
    - packageAttemptId, orderAttemptId (Internal checkout state IDs)
    - packageSnapshot (Raw unverified data payload)
    """
    snapshot = order_data.get("packageSnapshot") or {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    participants = order_data.get("participants") or snapshot.get("participants") or {}
    if not isinstance(participants, dict):
        participants = {}

    order_id = order_data.get("id")
    package_id = order_data.get("packageId") or snapshot.get("packageId")
    package_title = snapshot.get("title") or order_data.get("packageTitle")
    departure_date = order_data.get("departureDate") or snapshot.get("selectedDepartureDate")
    group_size = order_data.get("groupSize") or snapshot.get("groupSize") or participants.get("total")
    adults = participants.get("adults")
    children = participants.get("children")

    amt_val = order_data.get("amount") if order_data.get("amount") is not None else order_data.get("totalAmount")
    if amt_val is None:
        amt_val = order_data.get("groupTotal")
    try:
        amt_val = float(amt_val)
        if not isfinite(amt_val) or amt_val < 0:
            amt_val = None
    except (TypeError, ValueError):
        amt_val = None
    group_total = amt_val

    ful_record = order_data.get("fulfillmentRecord")
    from services.booking_requirements import assessment, status_overview, trip_status
    context = requirement_context or assessment(order_data)
    required_services = context['requirements']
    if not ful_record and is_paid_order(order_data):
        ful_record = build_initial_fulfillment_record(snapshot, now=order_data.get("createdAt"))

    safe_snapshot = {
        "packageId": package_id,
        "title": package_title,
        "destination": snapshot.get("destination") or snapshot.get("destinationName"),
        "durationDays": snapshot.get("durationDays"),
        "durationNights": snapshot.get("durationNights"),
        "selectedDepartureDate": departure_date,
        "accommodation": snapshot.get("accommodation") or {},
        "transport": snapshot.get("transport") or {},
        "inclusions": snapshot.get("inclusions") or [],
        "exclusions": snapshot.get("exclusions") or [],
        "itineraryDays": snapshot.get("itineraryDays") or [],
        "priceBasis": snapshot.get("priceBasis"),
        "taxIncluded": snapshot.get("taxIncluded"),
    }

    res = {
        "id": order_id,
        "orderReference": order_id,
        "packageId": package_id,
        "packageTitle": package_title,
        "operatorId": order_data.get("operatorId"),
        "quoteType": "package",
        "departureDate": departure_date,
        "groupSize": group_size,
        "adults": adults,
        "children": children,
        "paymentStatus": order_data.get("paymentStatus"),
        "isPaid": is_paid_order(order_data),
        "orderStatus": order_data.get("status"),
        "status": order_data.get("status"),
        "fulfillmentStatus": order_data.get("fulfillmentStatus"),
        "amount": amt_val,
        "groupTotal": group_total,
        "currency": record_money(order_data)[1],
        "supplierReservationStatus": order_data.get("supplierReservationStatus") or "not_created",
        "testMode": bool(order_data.get("provider") == "stripe_checkout_test" or order_data.get("testMode")),
        "createdAt": order_data.get("createdAt"),
        "updatedAt": order_data.get("updatedAt"),
    }
    if include_fulfillment:
        overview, readiness = status_overview(order_data,context,ful_record,trip_state or trip_status(order_data,unavailable=True))
        res['statusOverview'] = overview
        res["readiness"] = readiness
        res['requirementClarification'] = context
        res["pricingBreakdown"] = public_pricing_breakdown(snapshot.get("pricingBreakdown"))
        res["packageTripId"] = order_data.get("fulfilledTripId")
        res["fulfillmentRecord"] = ful_record
        res["requiredServices"] = required_services
        res["packageBrochure"] = safe_snapshot
    return res



def generate_business_analytics(db, operator_id):
    """
    Generate the Tourism Operator Business Analytics Report.

    Uses:
    - tourism_packages
    - promotional_campaigns
    - checkout_orders (authoritative package checkout orders)
    """

    # ==========================================================
    # TOURISM PACKAGES
    # ==========================================================

    packages, packages_limited = _records(db, 'tourism_packages', operator_id)
    packages = [package for package in packages if not package.get('deletedAt')]

    total_packages = len(packages)

    approved_packages = sum(
        1 for p in packages
        if _normalise(p.get("approvalStatus")) == "approved"
    )

    pending_packages = sum(
        1 for p in packages
        if _normalise(p.get("approvalStatus"))
        in {"pending", "pending_approval", "under_review", "submitted"}
    )

    rejected_packages = sum(
        1 for p in packages
        if _normalise(p.get("approvalStatus")) == "rejected"
    )

    draft_packages = sum(
        1 for p in packages
        if _normalise(p.get("approvalStatus")) in {"", "draft"}
    )

    # ==========================================================
    # PROMOTIONAL CAMPAIGNS
    # ==========================================================

    campaigns, campaigns_limited = _records(db, 'promotional_campaigns', operator_id)

    total_campaigns = len(campaigns)

    approved_campaigns = sum(
        1 for c in campaigns
        if _normalise(c.get("reviewStatus")) == "approved"
    )

    pending_campaigns = sum(
        1 for c in campaigns
        if _normalise(c.get("reviewStatus"))
        in {"pending", "pending_approval", "under_review", "submitted"}
    )

    rejected_campaigns = sum(
        1 for c in campaigns
        if _normalise(c.get("reviewStatus")) == "rejected"
    )

    eligible_ids = {p['id'] for p in packages if eligible_package(p)}
    active_campaigns = sum(1 for c in campaigns if active_campaign(c) and bool(set(campaign_package_ids(c)) & eligible_ids))

    # ==========================================================
    # BOOKING RECORDS (PACKAGE CHECKOUT ORDERS)
    # ==========================================================

    # Authoritative package bookings are recorded in checkout_orders
    # with quoteType == 'package' and operatorId == operator_id.
    orders, orders_limited = _records(db, 'checkout_orders', operator_id)

    bookings = []
    total_paid_revenue = 0.0
    paid_bookings = 0
    pending_bookings = 0
    expired_bookings = 0
    failed_bookings = 0
    cancelled_bookings = 0
    test_mode_orders = 0
    test_paid_total = 0.0
    unpriced_paid_orders = 0

    for data in unique_package_orders(orders):

        # Exclude non-package orders (e.g. hotel room reservations or flight checkouts)
        quote_type = _normalise(data.get("quoteType") or data.get("type"))
        if quote_type != "package":
            continue

        # Enforce operator ownership
        booking_operator = str(data.get("operatorId", "")).strip()
        if operator_id and booking_operator != str(operator_id).strip():
            continue

        # Project raw checkout order to safe allowlisted booking
        safe_booking = _safe_analytics_booking(data)
        bookings.append(safe_booking)

        payment_status = _normalise(data.get("paymentStatus"))
        order_status = _normalise(data.get("status"))
        currency = str(data.get("currency") or "").strip().upper()

        if data.get("provider") == "stripe_checkout_test" or data.get("testMode"):
            test_mode_orders += 1

        is_paid = is_paid_order(data)

        if is_paid:
            paid_bookings += 1
            if currency == "MYR":
                amt_val = data.get("amount") if data.get("amount") is not None else data.get("totalAmount")
                if amt_val is None:
                    amt_val = data.get("groupTotal")
                try:
                    amt = float(amt_val)
                    if not isfinite(amt) or amt < 0:
                        raise ValueError
                    if amt > 0:
                        total_paid_revenue += amt
                        if safe_booking['testMode']:
                            test_paid_total += amt
                except (TypeError, ValueError):
                    unpriced_paid_orders += 1
        elif order_status in {"expired", "checkout_expired"} or payment_status in {"expired"}:
            expired_bookings += 1
        elif order_status in {"failed", "checkout_failed"} or payment_status in {"failed", "payment_failed"}:
            failed_bookings += 1
        elif order_status in {"cancelled", "checkout_cancelled"} or payment_status in {"cancelled", "payment_cancelled"}:
            cancelled_bookings += 1
        elif payment_status in {"pending", "payment_pending", "unpaid"}:
            pending_bookings += 1

    fulfilled_bookings = sum(
        1 for b in bookings
        if _normalise(b.get("fulfillmentStatus")) in {"fulfilled", "trip_ready"}
    )
    pending_fulfillment_bookings = sum(
        1 for b in bookings
        if _normalise(b.get("fulfillmentStatus")) in {"pending", "fulfillment_pending", "awaiting_operator_fulfillment", "partially_fulfilled"}
    )

    # ==========================================================
    # PACKAGE VALUE
    # ==========================================================

    total_package_value = 0.0

    for package in packages:
        # Valuation is calculated from active approved catalog inventory
        if not eligible_package(package) or str(package.get('currency') or 'MYR').upper() != 'MYR':
            continue
        try:
            price = float(package.get('adultPrice', package.get('price', 0)) or 0)
            if isfinite(price) and price >= 0:
                total_package_value += price
        except (TypeError, ValueError):
            pass

    # ==========================================================
    # FINAL REPORT
    # ==========================================================

    return {
        'dataLimited': packages_limited or campaigns_limited or orders_limited,
        'recordLimit': RECORD_LIMIT,
        "generatedAt": datetime.now(
            timezone.utc
        ).isoformat(),

        "summary": {
            "totalPackages": total_packages,
            "approvedPackages": approved_packages,
            "pendingPackages": pending_packages,
            "rejectedPackages": rejected_packages,
            "draftPackages": draft_packages,

            "totalCampaigns": total_campaigns,
            "approvedCampaigns": approved_campaigns,
            "pendingCampaigns": pending_campaigns,
            "rejectedCampaigns": rejected_campaigns,
            "activeCampaigns": active_campaigns,

            "bookingRecords": len(bookings),
            "paidBookings": paid_bookings,
            "pendingBookings": pending_bookings,
            "expiredBookings": expired_bookings,
            "failedBookings": failed_bookings,
            "cancelledBookings": cancelled_bookings,
            "fulfilledBookings": fulfilled_bookings,
            "pendingFulfillmentBookings": pending_fulfillment_bookings,
            "testModeOrders": test_mode_orders,
            "totalPaidRevenue": round(total_paid_revenue, 2),
            'testPaidTotal': round(test_paid_total, 2),
            'unpricedPaidOrders': unpriced_paid_orders,

            "totalPackageValue": round(
                total_package_value,
                2
            ),
        },

        "packageCount": total_packages,
        "approvedPackageCount": approved_packages,
        "campaignCount": total_campaigns,
        "bookingCount": len(bookings),
        "paidBookingCount": paid_bookings,
        "pendingBookingCount": pending_bookings,
        "expiredBookingCount": expired_bookings,
        "failedBookingCount": failed_bookings,
        "cancelledBookingCount": cancelled_bookings,
        "totalPaidRevenue": round(total_paid_revenue, 2),
        "packages": packages,
        "campaigns": campaigns,
        "bookings": bookings,
    }
