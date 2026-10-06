from flask import Blueprint, render_template, request, redirect, url_for, session, flash, Response
from api_client import call_api

bp = Blueprint("admin_fr13", __name__, template_folder="templates", url_prefix="/admin")

def guard():
    return bool(session.get("id_token"))

def _error(response, fallback="Request failed"):
    try:
        return response.json().get("error", fallback)
    except Exception:
        return fallback

def _report_params():
    return {
        "reportType": request.args.get("reportType", "system_summary"),
        "startDate": request.args.get("startDate", ""),
        "endDate": request.args.get("endDate", ""),
        "filter": request.args.get("filter", ""),
    }

@bp.route("/dashboard")
def dashboard():
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    response = call_api("GET", "/api/fr13/reports/summary")
    return render_template("fr13_administrator_management/dashboard.html", report=response.json().get("report", {}) if response.ok else {})

@bp.route("/users")
def users():
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    response = call_api("GET", "/api/fr13/users")
    return render_template("fr13_administrator_management/users.html", items=response.json().get("items", []) if response.ok else [])

@bp.post("/users/<uid>/update")
def update_user(uid):
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    payload = {"role": request.form.get("role"), "status": request.form.get("status")}
    if request.form.get("verificationStatus"):
        payload["verificationStatus"] = request.form.get("verificationStatus")
    response = call_api("PUT", f"/api/fr13/users/{uid}", json=payload)
    flash("User account updated." if response.ok else _error(response), "success" if response.ok else "error")
    return redirect(url_for("admin_fr13.users"))

@bp.route("/packages")
def packages():
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    response = call_api("GET", "/api/fr13/packages/pending")
    return render_template("fr13_administrator_management/packages.html", items=response.json().get("items", []) if response.ok else [])

@bp.post("/packages/<package_id>/review")
def review_package(package_id):
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    response = call_api("POST", f"/api/fr13/packages/{package_id}/review", json={
        "decision": request.form["decision"],
        "comment": request.form.get("comment", ""),
    })
    flash("Package review saved." if response.ok else _error(response), "success" if response.ok else "error")
    return redirect(url_for("admin_fr13.packages"))

@bp.route("/campaigns")
def campaigns():
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    response = call_api("GET", "/api/fr13/campaigns/pending")
    return render_template("fr13_administrator_management/campaigns.html", items=response.json().get("items", []) if response.ok else [])

@bp.post("/campaigns/<campaign_id>/review")
def review_campaign(campaign_id):
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    response = call_api("POST", f"/api/fr13/campaigns/{campaign_id}/review", json={
        "decision": request.form["decision"],
        "comment": request.form.get("comment", ""),
    })
    flash("Promotional content review saved." if response.ok else _error(response), "success" if response.ok else "error")
    return redirect(url_for("admin_fr13.campaigns"))

@bp.route("/feedback")
def feedback():
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    response = call_api("GET", "/api/fr13/feedback")
    return render_template("fr13_administrator_management/feedback.html", items=response.json().get("items", []) if response.ok else [])

@bp.route("/destinations")
def destinations():
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    response = call_api("GET", "/api/fr13/destinations")
    return render_template("fr13_administrator_management/destinations.html", items=response.json().get("items", []) if response.ok else [])

@bp.post("/destinations")
def create_destination():
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    payload = {
        "title": request.form.get("title", ""),
        "address": request.form.get("address", ""),
        "category": request.form.get("category", ""),
        "type": request.form.get("type", ""),
        "description": request.form.get("description", ""),
        "openingHours": request.form.get("openingHours", ""),
        "estimatedCost": request.form.get("estimatedCost", "0"),
        "status": request.form.get("status", "active"),
    }
    response = call_api("POST", "/api/fr13/destinations", json=payload)
    flash("Destination record created." if response.ok else _error(response), "success" if response.ok else "error")
    return redirect(url_for("admin_fr13.destinations"))

@bp.post("/destinations/<destination_id>/update")
def update_destination(destination_id):
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    payload = {
        "title": request.form.get("title", ""),
        "address": request.form.get("address", ""),
        "category": request.form.get("category", ""),
        "type": request.form.get("type", ""),
        "description": request.form.get("description", ""),
        "openingHours": request.form.get("openingHours", ""),
        "estimatedCost": request.form.get("estimatedCost", "0"),
        "status": request.form.get("status", "active"),
    }
    response = call_api("PUT", f"/api/fr13/destinations/{destination_id}", json=payload)
    flash("Destination record updated." if response.ok else _error(response), "success" if response.ok else "error")
    return redirect(url_for("admin_fr13.destinations"))

@bp.post("/destinations/<destination_id>/delete")
def delete_destination(destination_id):
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    response = call_api("DELETE", f"/api/fr13/destinations/{destination_id}")
    flash("Destination record deleted." if response.ok else _error(response), "success" if response.ok else "error")
    return redirect(url_for("admin_fr13.destinations"))

@bp.route("/activities")
def activities():
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    response = call_api("GET", "/api/fr13/activities")
    return render_template("fr13_administrator_management/activities.html", items=response.json().get("items", []) if response.ok else [])

@bp.post("/activities")
def create_activity():
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    payload = {
        "activityName": request.form.get("activityName", ""),
        "destinationName": request.form.get("destinationName", ""),
        "category": request.form.get("category", ""),
        "description": request.form.get("description", ""),
        "estimatedCost": request.form.get("estimatedCost", "0"),
        "recommendedDurationMinutes": request.form.get("recommendedDurationMinutes", "90"),
        "status": request.form.get("status", "active"),
    }
    response = call_api("POST", "/api/fr13/activities", json=payload)
    flash("Activity record created." if response.ok else _error(response), "success" if response.ok else "error")
    return redirect(url_for("admin_fr13.activities"))

@bp.post("/activities/<activity_id>/update")
def update_activity(activity_id):
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    payload = {
        "activityName": request.form.get("activityName", ""),
        "destinationName": request.form.get("destinationName", ""),
        "category": request.form.get("category", ""),
        "description": request.form.get("description", ""),
        "estimatedCost": request.form.get("estimatedCost", "0"),
        "recommendedDurationMinutes": request.form.get("recommendedDurationMinutes", "90"),
        "status": request.form.get("status", "active"),
    }
    response = call_api("PUT", f"/api/fr13/activities/{activity_id}", json=payload)
    flash("Activity record updated." if response.ok else _error(response), "success" if response.ok else "error")
    return redirect(url_for("admin_fr13.activities"))

@bp.post("/activities/<activity_id>/delete")
def delete_activity(activity_id):
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    response = call_api("DELETE", f"/api/fr13/activities/{activity_id}")
    flash("Activity record deleted." if response.ok else _error(response), "success" if response.ok else "error")
    return redirect(url_for("admin_fr13.activities"))

@bp.route("/bookings")
def bookings():
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    response = call_api("GET", "/api/fr13/bookings")
    return render_template("fr13_administrator_management/bookings.html", items=response.json().get("items", []) if response.ok else [])

@bp.route("/payments")
def payments():
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    response = call_api("GET", "/api/fr13/payments")
    return render_template("fr13_administrator_management/payments.html", items=response.json().get("items", []) if response.ok else [])


@bp.post("/feedback/<feedback_id>/review")
def review_feedback(feedback_id):
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    decision = request.form.get("decision", "keep")
    response = call_api("POST", f"/api/fr13/feedback/{feedback_id}/review", json={
        "decision": decision,
        "comment": request.form.get("comment", ""),
    })
    if response.ok:
        flash("Feedback kept visible." if decision == "keep" else "Feedback removed from Traveller view.", "success")
    else:
        flash(_error(response), "error")
    return redirect(url_for("admin_fr13.feedback"))

@bp.post("/feedback/<feedback_id>/remove")
def remove_feedback(feedback_id):
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    response = call_api("DELETE", f"/api/fr13/feedback/{feedback_id}")
    flash("Feedback removed." if response.ok else _error(response), "success" if response.ok else "error")
    return redirect(url_for("admin_fr13.feedback"))

@bp.route("/reports")
def reports():
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    params = _report_params()
    response = call_api("GET", "/api/fr13/reports/summary", params=params)
    if not response.ok:
        flash(_error(response), "error")
    return render_template("fr13_administrator_management/reports.html", report=response.json().get("report", {}) if response.ok else {}, criteria=params)

@bp.route("/reports/export")
def export_report():
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    params = _report_params()
    export_format = request.args.get("format", "pdf")
    if export_format == "csv":
        response = call_api("GET", "/api/fr13/reports/export.csv", params=params)
        mimetype = "text/csv"
        filename = "TravelMate_System_Report.csv"
    else:
        response = call_api("GET", "/api/fr13/reports/export", params=params)
        mimetype = "application/pdf"
        filename = "TravelMate_System_Report.pdf"
    if not response.ok:
        flash(_error(response), "error")
        return redirect(url_for("admin_fr13.reports", **params))
    return Response(response.content, mimetype=mimetype, headers={"Content-Disposition": f"attachment; filename={filename}"})
