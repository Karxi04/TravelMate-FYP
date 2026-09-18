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
    if request.method == "POST":
        payload = {
            "packageTitle": request.form.get("packageTitle", ""),
            "destinationName": request.form.get("destinationName", ""),
            "description": request.form.get("description", ""),
            "price": _float_field("price"),
            "availabilityStatus": request.form.get("availabilityStatus", "available"),
            "durationDays": _int_field("durationDays"),
            "maxTravellers": _int_field("maxTravellers"),
            "validFrom": request.form.get("validFrom", ""),
            "validUntil": request.form.get("validUntil", ""),
            "meetingPoint": request.form.get("meetingPoint", ""),
            "imageUrl": request.form.get("imageUrl", ""),
            "highlights": request.form.get("highlights", ""),
            "inclusions": request.form.get("inclusions", ""),
            "exclusions": request.form.get("exclusions", ""),
        }
        response = call_api("POST", "/api/fr12/packages", json=payload)
        flash("Package created." if response.ok else _error(response), "success" if response.ok else "error")
        return redirect(url_for("operator_fr12.packages"))
    response = call_api("GET", "/api/fr12/packages")
    return render_template("fr12_tourism_operator_management/packages.html", items=response.json().get("items", []) if response.ok else [])


@bp.post("/packages/<package_id>/edit")
def edit_package(package_id):
    if not guard():
        return redirect(url_for("operator_fr01.login"))
    payload = {
        "packageTitle": request.form.get("packageTitle", ""),
        "destinationName": request.form.get("destinationName", ""),
        "description": request.form.get("description", ""),
        "price": _float_field("price"),
        "availabilityStatus": request.form.get("availabilityStatus", "available"),
        "durationDays": _int_field("durationDays"),
        "maxTravellers": _int_field("maxTravellers"),
        "validFrom": request.form.get("validFrom", ""),
        "validUntil": request.form.get("validUntil", ""),
        "meetingPoint": request.form.get("meetingPoint", ""),
        "imageUrl": request.form.get("imageUrl", ""),
        "highlights": request.form.get("highlights", ""),
        "inclusions": request.form.get("inclusions", ""),
        "exclusions": request.form.get("exclusions", ""),
    }
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
        payload = {
            "packageTitle": request.form.get("packageTitle", ""),
            "destinationName": request.form.get("destinationName", ""),
            "description": request.form.get("description", ""),
            "price": _float_field("price"),
            "availabilityStatus": request.form.get("availabilityStatus", "available"),
            "durationDays": _int_field("durationDays"),
            "maxTravellers": _int_field("maxTravellers"),
            "validFrom": request.form.get("validFrom", ""),
            "validUntil": request.form.get("validUntil", ""),
            "meetingPoint": request.form.get("meetingPoint", ""),
            "imageUrl": request.form.get("imageUrl", ""),
            "highlights": request.form.get("highlights", ""),
            "inclusions": request.form.get("inclusions", ""),
            "exclusions": request.form.get("exclusions", ""),
        }
        response = call_api("PUT", f"/api/fr12/packages/{package_id}", json=payload)
        flash("Package updated." if response.ok else _error(response), "success" if response.ok else "error")
        if response.ok:
            return redirect(url_for("operator_fr12.packages"))
    return render_template("fr12_tourism_operator_management/edit_package.html", item=item)


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
