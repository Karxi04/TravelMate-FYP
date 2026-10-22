from datetime import datetime, timezone


def _normalise(value):
    return str(value or "").strip().lower()


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

    if operator_id:
        package_docs = (
            db.collection("tourism_packages")
            .where("operatorId", "==", operator_id)
            .stream()
        )
    else:
        package_docs = db.collection("tourism_packages").stream()

    packages = []

    for doc in package_docs:
        data = doc.to_dict() or {}
        data["id"] = getattr(doc, "id", None) or data.get("id")
        packages.append(data)

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

    if operator_id:
        campaign_docs = (
            db.collection("promotional_campaigns")
            .where("operatorId", "==", operator_id)
            .stream()
        )
    else:
        campaign_docs = db.collection("promotional_campaigns").stream()

    campaigns = []

    for doc in campaign_docs:
        data = doc.to_dict() or {}
        data["id"] = getattr(doc, "id", None) or data.get("id")
        campaigns.append(data)

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

    active_campaigns = sum(
        1 for c in campaigns
        if _normalise(c.get("campaignStatus")) == "active"
    )

    # ==========================================================
    # BOOKING RECORDS (PACKAGE CHECKOUT ORDERS)
    # ==========================================================

    # Authoritative package bookings are recorded in checkout_orders
    # with quoteType == 'package' and operatorId == operator_id.
    coll = db.collection("checkout_orders")
    if operator_id:
        try:
            order_docs = coll.where("operatorId", "==", str(operator_id).strip()).stream()
        except (AttributeError, TypeError):
            order_docs = coll.stream()
    else:
        order_docs = coll.stream()

    bookings = []
    total_paid_revenue = 0.0
    paid_bookings = 0
    expired_bookings = 0
    test_mode_orders = 0

    for doc in order_docs:
        data = doc.to_dict() or {}
        data["id"] = getattr(doc, "id", None) or data.get("id")

        # Exclude non-package orders (e.g. hotel room reservations or flight checkouts)
        quote_type = _normalise(data.get("quoteType") or data.get("type"))
        if quote_type != "package":
            continue

        # Enforce operator ownership
        booking_operator = str(data.get("operatorId", "")).strip()
        if operator_id and booking_operator != str(operator_id).strip():
            continue

        # Strip sensitive payment provider tokens before inclusion
        for secret_key in ("stripePaymentIntentId", "stripeSessionId", "clientSecret", "paymentMethodId"):
            data.pop(secret_key, None)

        bookings.append(data)

        payment_status = _normalise(data.get("paymentStatus"))
        order_status = _normalise(data.get("status"))
        currency = str(data.get("currency") or "MYR").strip().upper()

        if data.get("provider") == "stripe_checkout_test" or data.get("testMode"):
            test_mode_orders += 1

        # Determine settlement validity:
        # 1. Confirmed payment provider settlement is primary authority
        has_settled_payment = payment_status in {"paid", "succeeded"}

        # 2. Legacy orders with absent/empty paymentStatus fall back to server order status
        legacy_paid_fallback = (not payment_status) and order_status in {"paid", "succeeded"}

        # 3. Explicit non-paid payment statuses, or cancelled/failed/expired order lifecycles, strictly disqualify
        is_disqualified = (
            order_status in {"cancelled", "failed", "payment_failed", "expired"}
            or payment_status in {"cancelled", "failed", "payment_failed", "unpaid", "pending", "payment_pending"}
        )

        is_paid = (has_settled_payment or legacy_paid_fallback) and not is_disqualified

        if is_paid:
            paid_bookings += 1
            if currency == "MYR":
                amt_val = data.get("amount") if data.get("amount") is not None else data.get("totalAmount")
                if amt_val is None:
                    amt_val = data.get("groupTotal")
                try:
                    amt = float(amt_val or 0)
                    if amt > 0:
                        total_paid_revenue += amt
                except (TypeError, ValueError):
                    pass
        elif order_status in {"expired", "unpaid"} or payment_status in {"expired", "unpaid"}:
            expired_bookings += 1

    # ==========================================================
    # PACKAGE VALUE
    # ==========================================================

    total_package_value = 0.0

    for package in packages:
        # Valuation is calculated from active approved catalog inventory
        if _normalise(package.get("approvalStatus")) != "approved":
            continue
        try:
            total_package_value += float(
                package.get("price", 0) or 0
            )
        except (TypeError, ValueError):
            pass

    # ==========================================================
    # FINAL REPORT
    # ==========================================================

    return {
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
            "expiredBookings": expired_bookings,
            "testModeOrders": test_mode_orders,
            "totalPaidRevenue": round(total_paid_revenue, 2),

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
        "expiredBookingCount": expired_bookings,
        "totalPaidRevenue": round(total_paid_revenue, 2),
        "packages": packages,
        "campaigns": campaigns,
        "bookings": bookings,
    }
