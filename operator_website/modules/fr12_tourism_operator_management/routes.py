from flask import Blueprint, render_template, request, redirect, url_for, session, flash, Response
from api_client import call_api

bp = Blueprint("operator_fr12", __name__, template_folder="templates")


def guard():
    return bool(session.get("id_token"))


def _error(response, fallback="Request failed"):
    try:
        return response.json().get("error", fallback)
    except Exception:
        return fallback


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
    analytics = call_api("GET", "/api/fr12/analytics")
    me = call_api("GET", "/api/fr1/me")
    return render_template("fr12_tourism_operator_management/dashboard.html", analytics=analytics.json().get("analytics", {}) if analytics.ok else {}, profile=me.json().get("profile", {}) if me.ok else {})


@bp.route("/packages", methods=["GET", "POST"])
def packages():
    if not guard():
        return redirect(url_for("operator_fr01.login"))
    listing = call_api("GET", "/api/fr12/packages")
    items = listing.json().get("items", []) if listing.ok else []
    status = request.args.get("status", "all").lower()
    query = request.args.get("q", "").strip().lower()
    if status != "all":
        expected = {"pending", "submitted"} if status == "pending" else {status}
        items = [item for item in items if str(item.get("approvalStatus", "draft")).lower() in expected]
    if query:
        items = [item for item in items if query in str(item.get("title") or item.get("packageTitle") or "").lower()]
    if request.method == "POST":
        payload = _package_payload()
        response = call_api("POST", "/api/fr12/packages", json=payload)
        flash("Package created." if response.ok else _error(response), "success" if response.ok else "error")
        if response.ok:
            return redirect(url_for("operator_fr12.packages"))
        return render_template("fr12_tourism_operator_management/packages.html", items=items, form=payload, status=status, query=query)
    return render_template("fr12_tourism_operator_management/packages.html", items=items, form={}, status=status, query=query)


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
        payload = {
            "campaignTitle": request.form.get("campaignTitle", ""),
            "description": request.form.get("description", ""),
            "packageId": request.form.get("packageId", ""),
            "startDate": request.form.get("startDate", ""),
            "endDate": request.form.get("endDate", ""),
            "promoCode": request.form.get("promoCode", ""),
            "discountType": request.form.get("discountType", "percentage"),
            "discountValue": _float_field("discountValue"),
            "bannerImageUrl": request.form.get("bannerImageUrl", ""),
            "termsConditions": request.form.get("termsConditions", ""),
        }
        response = call_api("POST", "/api/fr12/campaigns", json=payload)
        flash("Campaign created." if response.ok else _error(response), "success" if response.ok else "error")
        return redirect(url_for("operator_fr12.campaigns"))
    response = call_api("GET", "/api/fr12/campaigns")
    campaign_items = response.json().get("items", []) if response.ok else []
    package_names = {str(p.get("id")): p.get("packageTitle", "Package") for p in package_items}
    for campaign in campaign_items:
        campaign["packageTitle"] = package_names.get(str(campaign.get("packageId", "")), "-")
    return render_template("fr12_tourism_operator_management/campaigns.html", items=campaign_items, approved_packages=approved_packages)


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
    editable = [p for p in items if str(p.get("approvalStatus", "draft")).lower() in {"draft", "rejected"}]
    return render_template("fr12_tourism_operator_management/submit_package.html", items=editable)


@bp.route("/analytics")
def analytics():
    if not guard():
        return redirect(url_for("operator_fr01.login"))
    response = call_api("GET", "/api/fr12/analytics")
    return render_template(
        "fr12_tourism_operator_management/analytics.html",
        analytics=response.json().get("analytics", {}) if response.ok else {},
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
        payload = {
            "campaignTitle": request.form.get("campaignTitle", ""),
            "description": request.form.get("description", ""),
            "packageId": request.form.get("packageId", ""),
            "startDate": request.form.get("startDate", ""),
            "endDate": request.form.get("endDate", ""),
            "promoCode": request.form.get("promoCode", ""),
            "discountType": request.form.get("discountType", "percentage"),
            "discountValue": _float_field("discountValue"),
            "bannerImageUrl": request.form.get("bannerImageUrl", ""),
            "termsConditions": request.form.get("termsConditions", ""),
        }
        response = call_api("PUT", f"/api/fr12/campaigns/{campaign_id}", json=payload)
        flash("Campaign updated." if response.ok else _error(response), "success" if response.ok else "error")
        if response.ok:
            return redirect(url_for("operator_fr12.campaigns"))
    return render_template("fr12_tourism_operator_management/edit_campaign.html", item=item, approved_packages=approved_packages)


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
