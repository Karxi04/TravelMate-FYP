from datetime import datetime, timezone


def _normalise(value):
    return str(value or "").strip().lower()


def generate_business_analytics(db, operator_id):
    """
    Generate the Tourism Operator Business Analytics Report.

    Uses:
    - tourism_packages
    - promotional_campaigns
    - hotel_bookings
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
        data["id"] = doc.id
        packages.append(data)

    total_packages = len(packages)

    approved_packages = sum(
        1 for p in packages
        if _normalise(p.get("approvalStatus")) == "approved"
    )

    pending_packages = sum(
        1 for p in packages
        if _normalise(p.get("approvalStatus"))
        in {"pending", "pending_approval", "under_review"}
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
        data["id"] = doc.id
        campaigns.append(data)

    total_campaigns = len(campaigns)

    approved_campaigns = sum(
        1 for c in campaigns
        if _normalise(c.get("reviewStatus")) == "approved"
    )

    pending_campaigns = sum(
        1 for c in campaigns
        if _normalise(c.get("reviewStatus"))
        in {"pending", "pending_approval", "under_review"}
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
    # BOOKING RECORDS
    # ==========================================================

    # Your existing system stores hotel bookings in hotel_bookings.
    # Some booking records may not contain operatorId, therefore
    # retrieve all and filter where possible.
    booking_docs = db.collection("hotel_bookings").stream()

    bookings = []

    for doc in booking_docs:
        data = doc.to_dict() or {}
        data["id"] = doc.id

        booking_operator = str(
            data.get("operatorId", "")
        ).strip()

        if not booking_operator or booking_operator == operator_id:
            bookings.append(data)

    # ==========================================================
    # PACKAGE VALUE
    # ==========================================================

    total_package_value = 0.0

    for package in packages:
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

            "totalPackageValue": round(
                total_package_value,
                2
            ),
        },

        "packageCount": total_packages,
        "approvedPackageCount": approved_packages,
        "campaignCount": total_campaigns,
        "bookingCount": len(bookings),
        "packages": packages,
        "campaigns": campaigns,
        "bookings": bookings,
    }