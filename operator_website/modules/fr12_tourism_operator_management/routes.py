from datetime import date
from math import isfinite
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, Response, jsonify
from api_client import call_api

bp = Blueprint("operator_fr12", __name__, template_folder="templates")


@bp.before_request
def verified_operator_gate():
    if session.get("id_token") and session.get("incomplete_setup"):
        return redirect(url_for("operator_fr01.complete_setup"))
    if session.get("id_token") and session.get("portal_role") and session.get("portal_role") not in {"admin", "administrator"}:
        if session.get("verification_status", "pending") not in {"approved", "verified"}:
            return redirect(url_for("operator_fr01.verification"))


def guard():
    return bool(session.get("id_token"))


def _error(response, fallback="Request failed"):
    try:
        message = response.json().get("error", fallback)
    except Exception:
        message = fallback
    text = str(message)
    replacements = {
        "Tourism Operator account is not verified": "Your operator account is still awaiting administrator approval.",
        "Promotional campaign requires an approved package": "Choose one of your approved packages before creating a campaign.",
        "Campaign under administrator review cannot be edited": "This campaign is under review and cannot be edited yet.",
        "Campaign cannot be deleted in its current state": "This campaign cannot be deleted in its current publishing state.",
    }
    return replacements.get(text, text if text and text != fallback else "We couldn't complete that request. Try again.")


def _float_field(name, default=0):
    try:
        return float(request.form.get(name) or default)
    except (TypeError, ValueError):
        return default


def _int_field(name, default=1):
    try:
        return int(request.form.get(name) or default)
    except (TypeError, ValueError):
        return default


def _optional_float(name):
    value = request.form.get(name, "").strip()
    try:
        return float(value) if value else ""
    except ValueError:
        return value


def _optional_int(name):
    value = request.form.get(name, "").strip()
    try:
        return int(value) if value else ""
    except ValueError:
        return value


def _items(name):
    values = request.form.getlist(name)
    return [item.strip() for value in values for item in value.replace("\r", "").split("\n") if item.strip()]


def _campaign_payload():
    return {
        "campaignTitle": request.form.get("campaignTitle", "").strip(),
        "description": request.form.get("description", "").strip(),
        "packageId": request.form.get("packageId", "").strip(),
        "startDate": request.form.get("startDate", ""),
        "endDate": request.form.get("endDate", ""),
        "promoCode": request.form.get("promoCode", "").strip(),
        "discountType": request.form.get("discountType", "percentage"),
        "discountValue": _optional_float("discountValue") if request.form.get('discountValue', '').strip() else 0,
        "bannerImageUrl": request.form.get("bannerImageUrl", "").strip(),
        "termsConditions": request.form.get("termsConditions", "").strip(),
    }


def _campaign_state(item):
    status = str(item.get("reviewStatus", "draft") or "draft").lower()
    if status == "approved" and item.get("endDate") and str(item["endDate"]) < date.today().isoformat():
        return "expired"
    if status == 'approved' and item.get('startDate') and str(item['startDate']) > date.today().isoformat():
        return 'scheduled'
    return status


def _decorate_campaigns(items, package_items):
    package_names = {
        str(package.get("id")): package.get("title") or package.get("packageTitle", "Package")
        for package in package_items
    }
    decorated = []
    for campaign in items:
        item = dict(campaign)
        item["packageTitle"] = package_names.get(str(item.get("packageId", "")), "Package")
        item["displayStatus"] = _campaign_state(item)
        decorated.append(item)
    return decorated


def _package_payload():
    legacy = bool(request.form.get("packageTitle")) and not request.form.get("title")
    titles = request.form.getlist("itineraryTitle")
    descriptions = request.form.getlist("itineraryDescription")
    activities = request.form.getlist("itineraryActivities")
    meals = request.form.getlist("itineraryMeals")
    accommodations = request.form.getlist("itineraryAccommodation")
    transport_notes = request.form.getlist("itineraryTransportNotes")
    itinerary = []
    for index in range(max(map(len, [titles, descriptions, activities, meals, accommodations, transport_notes]), default=0)):
        value = lambda items: items[index].strip() if index < len(items) else ""
        day = {
            "dayNumber": index + 1,
            "title": value(titles),
            "description": value(descriptions),
            "activities": [x for x in value(activities).replace("\r", "").split("\n") if x.strip()],
            "meals": [x for x in value(meals).replace("\r", "").split("\n") if x.strip()],
            "accommodation": value(accommodations),
            "transportNotes": value(transport_notes),
        }
        if any(v for key, v in day.items() if key != "dayNumber"):
            itinerary.append(day)
    return {
        "schemaVersion": 1 if legacy else 2,
        "title": (request.form.get("title") or request.form.get("packageTitle") or "").strip(),
        "shortDescription": request.form.get("shortDescription", "").strip(),
        "fullDescription": (request.form.get("fullDescription") or request.form.get("description") or "").strip(),
        "destination": (request.form.get("destination") or request.form.get("destinationName") or "").strip(),
        "destinationArea": request.form.get("destinationArea", "").strip(),
        "category": request.form.get("category", "").strip(),
        "heroImage": request.form.get("heroImage", "").strip(),
        "galleryImages": _items("galleryImages"),
        "durationDays": _optional_int("durationDays"),
        "durationNights": _optional_int("durationNights"),
        "currency": request.form.get("currency", "MYR").strip().upper(),
        "adultPrice": _optional_float("adultPrice") if request.form.get("adultPrice") is not None else _optional_float("price"),
        "childPrice": _optional_float("childPrice"),
        "originalPrice": _optional_float("originalPrice"),
        "promotionalPrice": _optional_float("promotionalPrice"),
        "promotionStart": request.form.get("promotionStart", ""),
        "promotionEnd": request.form.get("promotionEnd", ""),
        "priceBasis": request.form.get("priceBasis", "per_person"),
        "taxIncluded": request.form.get("taxIncluded") == "on",
        "taxNotes": request.form.get("taxNotes", "").strip(),
        "minimumTravellers": _optional_int("minimumTravellers"),
        "maximumTravellers": _optional_int("maximumTravellers") if request.form.get("maximumTravellers") is not None else _optional_int("maxTravellers"),
        "validFrom": request.form.get("validFrom", ""),
        "validUntil": request.form.get("validUntil", ""),
        "departureDates": _items("departureDates"),
        "departureLocation": request.form.get("departureLocation", "").strip(),
        "meetingPoint": request.form.get("meetingPoint", "").strip(),
        "departureNotes": request.form.get("departureNotes", "").strip(),
        "itineraryDays": itinerary,
        "highlights": _items("highlights"),
        "inclusions": _items("inclusions"),
        "exclusions": _items("exclusions"),
        "accommodationName": request.form.get("accommodationName", "").strip(),
        "accommodationCategory": request.form.get("accommodationCategory", "").strip(),
        "roomType": request.form.get("roomType", "").strip(),
        "accommodationNotes": request.form.get("accommodationNotes", "").strip(),
        "transportTypes": _items("transportTypes"),
        "transportNotes": request.form.get("transportNotes", "").strip(),
        "cancellationPolicy": request.form.get("cancellationPolicy", "").strip(),
        "refundPolicy": request.form.get("refundPolicy", "").strip(),
        "bookingTerms": request.form.get("bookingTerms", "").strip(),
        "importantNotes": request.form.get("importantNotes", "").strip(),
        "whatToBring": _items("whatToBring"),
        "availabilityStatus": request.form.get("availabilityStatus", "available"),
    }


@bp.route("/dashboard")
def dashboard():
    if not guard():
        return redirect(url_for("operator_fr01.login"))
    package_response = call_api("GET", "/api/fr12/packages")
    campaign_response = call_api("GET", "/api/fr12/campaigns")
    booking_response = call_api("GET", "/api/fr12/bookings")
    me = call_api("GET", "/api/fr1/me")
    packages = package_response.json().get("items", []) if package_response.ok else []
    campaigns = campaign_response.json().get("items", []) if campaign_response.ok else []
    bookings_data = booking_response.json().get("items", []) if booking_response.ok else []
    summary = {
        "totalPackages": len(packages),
        "draftPackages": sum(1 for item in packages if str(item.get("approvalStatus", "draft")).lower() in {"", "draft"}),
        "pendingPackages": sum(1 for item in packages if str(item.get("approvalStatus", "")).lower() in {"pending", "submitted"}),
        "approvedPackages": sum(1 for item in packages if str(item.get("approvalStatus", "")).lower() == "approved"),
        "rejectedPackages": sum(1 for item in packages if str(item.get("approvalStatus", "")).lower() == "rejected"),
        "suspendedPackages": sum(1 for item in packages if str(item.get("approvalStatus", "")).lower() == "suspended"),
        "totalCampaigns": len(campaigns),
        "pendingCampaigns": sum(1 for item in campaigns if str(item.get("reviewStatus", "")).lower() in {"pending", "submitted"}),
        "activeCampaigns": sum(1 for item in campaigns if _campaign_state(item) == 'approved'
            and str(item.get('campaignStatus', 'approved')).lower() in {'active', 'approved'}
            and any(p.get('id') == item.get('packageId') and p.get('approvalStatus') == 'approved'
                    and p.get('availabilityStatus', 'available') == 'available' for p in packages)),
        "totalBookings": len(bookings_data),
        "paidBookings": sum(1 for item in bookings_data if _is_paid_booking(item)),
    }
    attention = []
    for package in packages:
        if str(package.get("approvalStatus", "")).lower() == "rejected":
            attention.append({
                "kind": "Package needs changes",
                "title": package.get("title") or package.get("packageTitle", "Package"),
                "reason": package.get("reviewReason") or package.get("reviewComment") or "Please review the Administrator feedback.",
                "url": url_for("operator_fr12.edit_package_page", package_id=package.get("id")),
            })
        elif str(package.get("approvalStatus", "")).lower() == "suspended":
            attention.append({
                "kind": "Package suspended by Admin",
                "title": package.get("title") or package.get("packageTitle", "Package"),
                "reason": package.get("suspensionReason") or "This package was suspended by an administrator. Please update and resubmit.",
                "url": url_for("operator_fr12.edit_package_page", package_id=package.get("id")),
            })
    for campaign in campaigns:
        if str(campaign.get("reviewStatus", "")).lower() == "rejected":
            attention.append({
                "kind": "Campaign needs changes",
                "title": campaign.get("campaignTitle", "Campaign"),
                "reason": campaign.get("reviewComment") or "Please review the Administrator feedback.",
                "url": url_for("operator_fr12.edit_campaign_page", campaign_id=campaign.get("id")),
            })
    return render_template(
        "fr12_tourism_operator_management/dashboard.html",
        analytics={"packages": packages, "campaigns": campaigns},
        summary=summary,
        profile=me.json().get("profile", {}) if me.ok else {},
        attention=attention,
        backend_error=not all(r.ok for r in (package_response, campaign_response, booking_response, me)),
        data_limited=any(r.json().get('dataLimited', False) for r in (package_response, campaign_response, booking_response) if r.ok),
    )


def _safe_float(val, default=0.0):
    try:
        number = float(val or default)
        return number if isfinite(number) else default
    except (ValueError, TypeError):
        return default


def _is_paid_booking(booking):
    if isinstance(booking.get('isPaid'), bool):
        return booking['isPaid']
    pay = str(booking.get('paymentStatus') or '').lower()
    status = str(booking.get('orderStatus') or '').lower()
    terminal = {'expired', 'checkout_expired', 'failed', 'checkout_failed', 'payment_failed',
                'cancelled', 'checkout_cancelled', 'refunded', 'partially_refunded', 'rejected'}
    return status not in terminal and (pay in {'paid', 'succeeded'} or (not pay and status in {'paid', 'succeeded'}))


def _is_pending_booking(b):
    if not isinstance(b, dict):
        return False
    pay = str(b.get("paymentStatus") or "").strip().lower()
    order = str(b.get("orderStatus") or "").strip().lower()
    terminal_orders = {
        "expired", "checkout_expired",
        "failed", "checkout_failed",
        "cancelled", "checkout_cancelled",
        "rejected",
    }
    terminal_pays = {
        "paid", "succeeded",
        "failed", "payment_failed",
        "expired",
        "cancelled",
        "refunded",
    }
    if order in terminal_orders or pay in terminal_pays:
        return False
    return pay in {"pending", "payment_pending", "unpaid"}


@bp.route("/bookings")
def bookings():
    if not guard():
        return redirect(url_for("operator_fr01.login"))
    response = call_api("GET", "/api/fr12/bookings")
    backend_error = not response.ok
    if backend_error:
        flash(_error(response, fallback="Unable to retrieve bookings from the server."), "error")
        all_items = []
    else:
        all_items = response.json().get("items", []) or []

    query = request.args.get("q", "").strip().lower()
    status = request.args.get("status", "all").strip().lower()

    items = list(all_items)
    if status != "all":
        if status == "paid":
            items = [b for b in items if _is_paid_booking(b)]
        elif status == "pending":
            items = [b for b in items if _is_pending_booking(b)]
        elif status == "fulfilled":
            items = [b for b in items if str(b.get("fulfillmentStatus", "")).lower() == "fulfilled"]
        elif status == "test":
            items = [b for b in items if b.get("testMode")]

    if query:
        items = [
            b for b in items
            if query in " ".join([
                str(b.get("orderReference") or ""),
                str(b.get("packageTitle") or ""),
                str(b.get("departureDate") or ""),
                str(b.get("paymentStatus") or ""),
            ]).lower()
        ]

    summary = {
        "total": len(all_items),
        "paid": sum(1 for b in all_items if _is_paid_booking(b)),
        "pending": sum(1 for b in all_items if _is_pending_booking(b)),
        "fulfilled": sum(1 for b in all_items if str(b.get("fulfillmentStatus", "")).lower() == "fulfilled"),
        "unconfirmed_supplier": sum(1 for b in all_items if b.get("supplierReservationStatus") == "not_created"),
        "test_orders": sum(1 for b in all_items if b.get("testMode")),
        "total_revenue": sum(
            _safe_float(b.get("groupTotal"))
            for b in all_items
            if _is_paid_booking(b) and str(b.get('currency') or '').upper() == 'MYR'
        ),
    }

    return render_template(
        "fr12_tourism_operator_management/bookings.html",
        items=items,
        total_items_count=len(all_items),
        summary=summary,
        status=status,
        query=query,
        backend_error=backend_error,
        is_pending_booking=_is_pending_booking,
        data_limited=response.json().get('dataLimited', False) if response.ok else False,
    )


@bp.route("/bookings/<order_reference>")
def booking_detail(order_reference):
    if not guard():
        return redirect(url_for("operator_fr01.login"))
    response = call_api("GET", f"/api/fr12/bookings/{order_reference}")
    if not response.ok:
        flash(_error(response, fallback="Unable to retrieve booking details."), "error")
        return redirect(url_for("operator_fr12.bookings"))
    item = response.json().get('booking')
    if not item:
        flash(f"Booking reference '{order_reference}' not found or not accessible.", "error")
        return redirect(url_for("operator_fr12.bookings"))
    return render_template(
        "fr12_tourism_operator_management/booking_detail.html",
        booking=item,
    )


@bp.route("/packages", methods=["GET", "POST"])
def packages():
    if not guard():
        return redirect(url_for("operator_fr01.login"))
    listing = call_api("GET", "/api/fr12/packages")
    if not listing.ok:
        flash(_error(listing), 'error')
    items = listing.json().get("items", []) if listing.ok else []
    status = request.args.get("status", "all").lower()
    query = request.args.get("q", "").strip().lower()
    if status != "all":
        expected = {"pending", "submitted"} if status == "pending" else {status}
        items = [item for item in items if str(item.get("approvalStatus", "draft")).lower() in expected]
    if query:
        items = [item for item in items if query in " ".join(str(item.get(field) or "") for field in ("title", "packageTitle", "destination", "destinationName")).lower()]
    if request.method == "POST":
        payload = _package_payload()
        response = call_api("POST", "/api/fr12/packages", json=payload)
        flash("Package created." if response.ok else _error(response), "success" if response.ok else "error")
        if response.ok:
            return redirect(url_for("operator_fr12.packages"))
        return render_template("fr12_tourism_operator_management/package_new.html", form=payload)
    for item in items:
        item["displayStatus"] = str(item.get("approvalStatus", "draft") or "draft").lower()
    return render_template("fr12_tourism_operator_management/packages.html", items=items, status=status, query=query)


@bp.route("/packages/new", methods=["GET", "POST"])
def new_package():
    if not guard():
        return redirect(url_for("operator_fr01.login"))
    if request.method == "POST":
        payload = _package_payload()
        response = call_api("POST", "/api/fr12/packages", json=payload)
        flash("Package saved as a draft." if response.ok else _error(response), "success" if response.ok else "error")
        if response.ok:
            return redirect(url_for("operator_fr12.packages"))
        return render_template("fr12_tourism_operator_management/package_new.html", form=payload)
    return render_template("fr12_tourism_operator_management/package_new.html", form={})


@bp.post("/packages/<package_id>/edit")
def edit_package(package_id):
    if not guard():
        return redirect(url_for("operator_fr01.login"))
    payload = _package_payload()
    response = call_api("PUT", f"/api/fr12/packages/{package_id}", json=payload)
    flash("Package updated." if response.ok else _error(response), "success" if response.ok else "error")
    return redirect(url_for("operator_fr12.packages"))


@bp.post("/packages/<package_id>/delete")
def delete_package(package_id):
    if not guard():
        return redirect(url_for("operator_fr01.login"))
    response = call_api("DELETE", f"/api/fr12/packages/{package_id}")
    flash("Package deleted." if response.ok else _error(response), "success" if response.ok else "error")
    return redirect(url_for("operator_fr12.packages"))


@bp.post("/packages/<package_id>/submit")
def submit_package(package_id):
    if not guard():
        return redirect(url_for("operator_fr01.login"))
    response = call_api("POST", f"/api/fr12/packages/{package_id}/submit")
    flash("Package submitted for approval." if response.ok else _error(response), "success" if response.ok else "error")
    return redirect(url_for("operator_fr12.packages"))


@bp.post("/packages/<package_id>/archive")
def archive_package(package_id):
    if not guard():
        return redirect(url_for("operator_fr01.login"))
    response = call_api("POST", f"/api/fr12/packages/{package_id}/archive")
    flash("Package archived." if response.ok else _error(response), "success" if response.ok else "error")
    return redirect(url_for("operator_fr12.packages"))


@bp.route("/campaigns", methods=["GET", "POST"])
def campaigns():
    if not guard():
        return redirect(url_for("operator_fr01.login"))
    package_response = call_api("GET", "/api/fr12/packages")
    package_items = package_response.json().get("items", []) if package_response.ok else []
    approved_packages = [p for p in package_items if p.get("approvalStatus") == "approved"]
    if request.method == "POST":
        payload = _campaign_payload()
        response = call_api("POST", "/api/fr12/campaigns", json=payload)
        flash("Campaign created." if response.ok else _error(response), "success" if response.ok else "error")
        if response.ok:
            return redirect(url_for("operator_fr12.campaigns"))
        campaign_response = call_api("GET", "/api/fr12/campaigns")
        campaigns = campaign_response.json().get("items", []) if campaign_response.ok else []
        decorated = _decorate_campaigns(campaigns, package_items)
        return render_template("fr12_tourism_operator_management/campaigns.html", items=decorated, approved_packages=approved_packages, form=payload, status="all", query="")
    response = call_api("GET", "/api/fr12/campaigns")
    if not response.ok:
        flash(_error(response), 'error')
    campaign_items = response.json().get("items", []) if response.ok else []
    decorated = _decorate_campaigns(campaign_items, package_items)
    status = request.args.get("status", "all").lower()
    query = request.args.get("q", "").strip().lower()
    if status != "all":
        decorated = [item for item in decorated if item.get("displayStatus") == status]
    if query:
        decorated = [item for item in decorated if query in " ".join(str(item.get(field) or "") for field in ("campaignTitle", "packageTitle", "description")).lower()]
    return render_template("fr12_tourism_operator_management/campaigns.html", items=decorated, approved_packages=approved_packages, form={}, status=status, query=query)


@bp.post("/campaigns/<campaign_id>/delete")
def delete_campaign(campaign_id):
    if not guard():
        return redirect(url_for("operator_fr01.login"))
    response = call_api("DELETE", f"/api/fr12/campaigns/{campaign_id}")
    flash("Campaign deleted." if response.ok else _error(response), "success" if response.ok else "error")
    return redirect(url_for("operator_fr12.campaigns"))


@bp.post("/campaigns/<campaign_id>/submit")
def submit_campaign(campaign_id):
    if not guard():
        return redirect(url_for("operator_fr01.login"))
    response = call_api("POST", f"/api/fr12/campaigns/{campaign_id}/submit")
    flash("Campaign submitted for review." if response.ok else _error(response), "success" if response.ok else "error")
    return redirect(url_for("operator_fr12.campaigns"))


@bp.route("/package-status")
def package_status():
    if not guard():
        return redirect(url_for("operator_fr01.login"))
    response = call_api("GET", "/api/fr12/packages")
    if not response.ok:
        flash(_error(response), 'error')
    return render_template(
        "fr12_tourism_operator_management/package_status.html",
        items=response.json().get("items", []) if response.ok else [],
    )


@bp.route("/submit-package", methods=["GET", "POST"])
def submit_package_page():
    if not guard():
        return redirect(url_for("operator_fr01.login"))
    if request.method == "POST":
        package_id = request.form.get("packageId", "")
        if not package_id:
            flash("Please select a package.", "error")
        else:
            response = call_api("POST", f"/api/fr12/packages/{package_id}/submit")
            flash(
                "Package submitted for approval." if response.ok else _error(response),
                "success" if response.ok else "error",
            )
            if response.ok:
                return redirect(url_for("operator_fr12.package_status"))
    response = call_api("GET", "/api/fr12/packages")
    items = response.json().get("items", []) if response.ok else []
    editable = [p for p in items if str(p.get("approvalStatus", "draft")).lower() in {"draft", "rejected", "suspended"}]
    return render_template("fr12_tourism_operator_management/submit_package.html", items=editable)


@bp.route("/analytics")
def analytics():
    if not guard():
        return redirect(url_for("operator_fr01.login"))
    response = call_api("GET", "/api/fr12/analytics")
    return render_template(
        "fr12_tourism_operator_management/analytics.html",
        analytics=response.json().get("analytics", {}) if response.ok else {},
        backend_error=not response.ok,
    )


@bp.route("/packages/<package_id>/edit-page", methods=["GET", "POST"])
def edit_package_page(package_id):
    if not guard():
        return redirect(url_for("operator_fr01.login"))
    listing = call_api("GET", "/api/fr12/packages")
    items = listing.json().get("items", []) if listing.ok else []
    item = next((x for x in items if x.get("id") == package_id), None)
    if item is None:
        flash("Package not found.", "error")
        return redirect(url_for("operator_fr12.packages"))
    if request.method == "POST":
        payload = _package_payload()
        response = call_api("PUT", f"/api/fr12/packages/{package_id}", json=payload)
        flash("Package updated." if response.ok else _error(response), "success" if response.ok else "error")
        if response.ok:
            return redirect(url_for("operator_fr12.packages"))
        item = {**item, **payload}
    return render_template("fr12_tourism_operator_management/edit_package.html", item=item, form=item)


@bp.route("/campaigns/<campaign_id>/edit-page", methods=["GET", "POST"])
def edit_campaign_page(campaign_id):
    if not guard():
        return redirect(url_for("operator_fr01.login"))
    campaigns_response = call_api("GET", "/api/fr12/campaigns")
    campaigns = campaigns_response.json().get("items", []) if campaigns_response.ok else []
    item = next((x for x in campaigns if x.get("id") == campaign_id), None)
    if item is None:
        flash("Campaign not found.", "error")
        return redirect(url_for("operator_fr12.campaigns"))
    package_response = call_api("GET", "/api/fr12/packages")
    package_items = package_response.json().get("items", []) if package_response.ok else []
    approved_packages = [x for x in package_items if x.get("approvalStatus") == "approved"]
    if request.method == "POST":
        payload = _campaign_payload()
        response = call_api("PUT", f"/api/fr12/campaigns/{campaign_id}", json=payload)
        flash("Campaign updated." if response.ok else _error(response), "success" if response.ok else "error")
        if response.ok:
            return redirect(url_for("operator_fr12.campaigns"))
        item = {**item, **payload}
    return render_template("fr12_tourism_operator_management/edit_campaign.html", item=item, approved_packages=approved_packages, form=item)


@bp.route("/reports/export")
def export_report():
    if not guard():
        return redirect(url_for("operator_fr01.login"))
    response = call_api("GET", "/api/fr12/reports/export")
    if not response.ok:
        flash(_error(response), "error")
        return redirect(url_for("operator_fr12.analytics"))
    return Response(
        response.content,
        mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=Tourism_Operator_Business_Report.pdf"},
    )


@bp.post("/packages/upload-image")
def upload_package_image_proxy():
    if not guard():
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    file = request.files.get("file") or request.files.get("image")
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "No image file provided"}), 400

    response = call_api(
        "POST",
        "/api/fr12/package-images/upload",
        files={"file": (file.filename, file.stream, file.mimetype)},
    )
    if not response.ok:
        try:
            err = response.json().get("error", "Failed to upload image")
        except Exception:
            err = "Failed to upload image"
        return jsonify({"ok": False, "error": err}), response.status_code
    return jsonify(response.json()), response.status_code

