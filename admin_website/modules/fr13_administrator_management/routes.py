from flask import Blueprint, render_template, request, redirect, url_for, session, flash, Response, g
from api_client import call_api
from uuid import uuid4

bp = Blueprint("admin_fr13", __name__, template_folder="templates", url_prefix="/admin")

def guard():
    return bool(session.get("id_token")) and session.get('portal_role') in {'admin','administrator'}


@bp.context_processor
def data_state():
    return {'backend_error':getattr(g,'admin_backend_error',False),
            'data_limited':getattr(g,'admin_data_limited',False)}


@bp.after_request
def expired_session(response):
    if getattr(g,'admin_auth_denied',False):
        return redirect(url_for('admin_fr01.login'))
    return response

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
    params = {key: request.args.get(key, "").strip() for key in ("q", "role", "status") if request.args.get(key, "").strip()}
    response = call_api("GET", "/api/fr13/users", params=params)
    return render_template("fr13_administrator_management/users.html", items=response.json().get("items", []) if response.ok else [], query=params.get("q", ""), role=params.get("role", "all"), status=params.get("status", "all"))

@bp.post("/users/<uid>/update")
def update_user(uid):
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    payload = {"role": request.form.get("role"), "status": request.form.get("status")}
    if request.form.get("verificationStatus"):
        if payload['role'] in {'operator','tourism_operator'}:
            payload["verificationStatus"] = request.form.get("verificationStatus")
    response = call_api("PUT", f"/api/fr13/users/{uid}", json=payload)
    flash("User account updated." if response.ok else _error(response), "success" if response.ok else "error")
    return redirect(url_for("admin_fr13.users"))

@bp.route("/packages")
def packages():
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    status = request.args.get("status", "all")
    query = request.args.get("q", "").strip()
    response = call_api("GET", "/api/fr13/packages", params={"status": status, "q": query})
    return render_template("fr13_administrator_management/packages.html", items=response.json().get("items", []) if response.ok else [], status=status, query=query)


@bp.get("/packages/<package_id>")
def package_details(package_id):
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    response = call_api("GET", f"/api/fr13/packages/{package_id}")
    if not response.ok:
        flash(_error(response, "Package not found."), "error")
        return redirect(url_for("admin_fr13.packages"))
    return render_template("fr13_administrator_management/package_review.html", item=response.json().get("package", {}))

@bp.post("/packages/<package_id>/review")
def review_package(package_id):
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    response = call_api("POST", f"/api/fr13/packages/{package_id}/review", json={
        "decision": request.form["decision"],
        "comment": request.form.get("comment", ""),
    })
    flash("Package review saved." if response.ok else _error(response), "success" if response.ok else "error")
    return redirect(url_for("admin_fr13.package_details", package_id=package_id) if not response.ok else url_for("admin_fr13.packages"))

@bp.post("/packages/<package_id>/suspend")
def suspend_package(package_id):
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    reason = request.form.get("reason", "").strip()
    if len(reason) < 10:
        flash("A meaningful suspension reason of at least 10 characters is required.", "error")
        return redirect(url_for("admin_fr13.package_details", package_id=package_id))
    if len(reason) > 500:
        flash("Suspension reason cannot exceed 500 characters.", "error")
        return redirect(url_for("admin_fr13.package_details", package_id=package_id))
    response = call_api("POST", f"/api/fr13/packages/{package_id}/suspend", json={"reason": reason})
    if response.ok:
        data = response.json() if hasattr(response, "json") else {}
        if data.get("idempotent"):
            flash("Package is already suspended with this reason.", "info")
        else:
            flash("Package suspended and unpublished successfully.", "success")
    else:
        flash(_error(response, "Failed to suspend package."), "error")
    return redirect(url_for("admin_fr13.package_details", package_id=package_id))

@bp.route("/campaigns")
def campaigns():
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    status = request.args.get("status", "pending")
    query = request.args.get("q", "").strip()
    response = call_api("GET", "/api/fr13/campaigns", params={"status": status, "q": query})
    return render_template("fr13_administrator_management/campaigns.html", items=response.json().get("items", []) if response.ok else [], status=status, query=query)

@bp.get("/campaigns/<campaign_id>")
def campaign_details(campaign_id):
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    response = call_api("GET", f"/api/fr13/campaigns/{campaign_id}")
    if not response.ok:
        flash(_error(response, "Campaign not found."), "error")
        return redirect(url_for("admin_fr13.campaigns"))
    return render_template("fr13_administrator_management/campaign_detail.html", item=response.json().get("campaign", {}))

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
    flash("Destination catalog management has been retired. Record creation is disabled.", "warning")
    return redirect(url_for("admin_fr13.destinations"))

@bp.post("/destinations/<destination_id>/update")
def update_destination(destination_id):
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    flash("Destination catalog management has been retired. Record updates are disabled.", "warning")
    return redirect(url_for("admin_fr13.destinations"))

@bp.post("/destinations/<destination_id>/delete")
def delete_destination(destination_id):
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    flash("Destination catalog management has been retired. Record deletion is disabled.", "warning")
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
    flash("Activity catalog management has been retired. Record creation is disabled.", "warning")
    return redirect(url_for("admin_fr13.activities"))

@bp.post("/activities/<activity_id>/update")
def update_activity(activity_id):
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    flash("Activity catalog management has been retired. Record updates are disabled.", "warning")
    return redirect(url_for("admin_fr13.activities"))

@bp.post("/activities/<activity_id>/delete")
def delete_activity(activity_id):
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    flash("Activity catalog management has been retired. Record deletion is disabled.", "warning")
    return redirect(url_for("admin_fr13.activities"))
    return redirect(url_for("admin_fr13.activities"))

@bp.route("/bookings")
def bookings():
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    booking_type = request.args.get("type", "hotel")
    params = {"type": booking_type}
    if request.args.get("q"):
        params["q"] = request.args.get("q").strip()
    if request.args.get("status"):
        params["status"] = request.args.get("status").strip()
    response = call_api("GET", "/api/fr13/bookings", params=params)
    return render_template(
        "fr13_administrator_management/bookings.html",
        items=response.json().get("items", []) if response.ok else [],
        booking_type=booking_type,
        query=params.get("q", ""),
        status=params.get("status", ""),
    )

@bp.route("/payments")
def payments():
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    params = {
        key: request.args.get(key, "").strip()
        for key in ("q", "status", "product", "startDate", "endDate")
        if request.args.get(key, "").strip()
    }
    response = call_api("GET", "/api/fr13/payments", params=params)
    data = response.json() if response.ok else {}
    return render_template(
        "fr13_administrator_management/payments.html",
        items=data.get("items", []) if response.ok else [],
        backend_error=not response.ok,
        data_limited=bool(data.get("dataLimited", False)),
        **params,
    )


@bp.route('/booking-clarifications')
def booking_clarifications():
    if not guard():return redirect(url_for('admin_fr01.login'))
    response=call_api('GET','/api/fr12/booking-clarifications')
    data=response.json() if response.ok else {}
    return render_template('fr13_administrator_management/booking_clarifications.html',
        items=data.get('items',[]),backend_error=not response.ok,data_limited=data.get('dataLimited',False))


@bp.route('/bookings/<order_reference>/clarification',methods=['GET','POST'])
def booking_clarification_review(order_reference):
    if not guard():return redirect(url_for('admin_fr01.login'))
    if request.method=='POST':
        try:revision=int(request.form.get('expectedRevision',''))
        except ValueError:revision=-1
        response=call_api('POST',f'/api/fr12/bookings/{order_reference}/clarifications/review',json={
            'expectedRevision':revision,'requestId':request.form.get('requestId',''),
            'decision':request.form.get('decision',''),'reason':request.form.get('reason','').strip(),
            'evidenceReference':request.form.get('evidenceReference','').strip(),
            'entitlementVerified':request.form.get('entitlementVerified')=='true'})
        data=response.json()
        flash('Clarification decision recorded.' if response.ok else data.get('error','Decision could not be saved.'),'success' if response.ok else 'error')
        return redirect(url_for('admin_fr13.booking_clarification_review',order_reference=order_reference))
    response=call_api('GET',f'/api/fr12/bookings/{order_reference}')
    if not response.ok:
        flash('Booking review is unavailable.','error')
        return redirect(url_for('admin_fr13.booking_clarifications'))
    return render_template('fr13_administrator_management/booking_clarification_review.html',booking=response.json()['booking'],request_id=uuid4().hex)


@bp.post("/feedback/<feedback_id>/review")
def review_feedback(feedback_id):
    if not guard():
        return redirect(url_for("admin_fr01.login"))
    decision = request.form.get("decision", "keep")
    response = call_api("POST", f"/api/fr13/feedback/{feedback_id}/review", json={
        "decision": decision,
        "comment": request.form.get("comment", ""),
        "expectedUpdatedAt": request.form.get("expectedUpdatedAt", ""),
        **({"expectedRevision": request.form["expectedRevision"]} if "expectedRevision" in request.form else {}),
    })
    if response.ok:
        flash("Review approved." if decision == "keep" else "Review removed from Traveller view.", "success")
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
