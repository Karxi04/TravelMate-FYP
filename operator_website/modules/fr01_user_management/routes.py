import time
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from firebase_auth_rest import authenticateCredentials, createUserAccount, sendPasswordResetEmail, signOutUser
from api_client import call_api

bp = Blueprint("operator_fr01", __name__, template_folder="templates")


def _store_auth(data):
    session["id_token"] = data["idToken"]
    session["refresh_token"] = data.get("refreshToken")
    session["uid"] = data.get("localId")
    session["token_expires_at"] = time.time() + int(data.get("expiresIn", 3600))


def _api_error(response, fallback="Request failed"):
    try:
        message = response.json().get("error", fallback)
    except Exception:
        message = fallback
    text = str(message)
    if "not verified" in text.lower():
        return "Your operator account is still awaiting administrator approval."
    if "deactivated" in text.lower():
        return "This operator account is disabled. Contact TravelMate support."
    return text if text and text != fallback else "We couldn't complete that request. Try again."


@bp.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        try:
            data, status = authenticateCredentials(request.form["email"], request.form["password"])
        except Exception as exc:
            flash("We couldn't sign you in. Check your connection and try again.", "error")
            return render_template("fr01_user_management/login.html")
        if status == 200:
            _store_auth(data)
            me = call_api("GET", "/api/fr1/me")
            profile = me.json().get("profile") if me.ok else None
            user_role = str(profile.get("role", "") if profile else "").strip().lower()
            if profile:
                session["portal_role"] = user_role
                session["verification_status"] = str(profile.get("verificationStatus", "pending")).lower()
            if not profile or user_role not in {"operator", "tourism_operator", "admin"}:
                session.clear()
                flash("This account is not a Tourism Operator account.", "error")
            elif user_role != "admin" and str(profile.get("verificationStatus", "pending")).lower() not in {"approved", "verified"}:
                verification = str(profile.get("verificationStatus", "pending")).lower()
                if verification in {"rejected", "disabled", "deactivated"}:
                    flash("Your operator account needs attention before publishing can begin.", "error")
                return redirect(url_for("operator_fr01.verification"))
            else:
                return redirect(url_for("operator_fr12.dashboard"))
        else:
            flash(data.get("error", {}).get("message", "Login failed"), "error")
    return render_template("fr01_user_management/login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        try:
            data, status = createUserAccount(request.form["email"], request.form["password"])
        except Exception as exc:
            flash("We couldn't create the account. Check your details and try again.", "error")
            return render_template("fr01_user_management/register.html")
        if status == 200:
            _store_auth(data)
            payload = {
                "role": "operator",
                "name": request.form["name"],
                "companyName": request.form["companyName"],
                "registrationNo": request.form["registrationNo"],
                "businessContact": request.form["businessContact"],
            }
            response = call_api("POST", "/api/fr1/profile", json=payload)
            if response.ok:
                session.clear()
                flash("Operator account created and awaiting administrator verification.", "success")
                return redirect(url_for("operator_fr01.login"))
            flash(_api_error(response, "Profile creation failed"), "error")
        else:
            flash(data.get("error", {}).get("message", "Registration failed"), "error")
    return render_template("fr01_user_management/register.html")


@bp.route("/reset", methods=["GET", "POST"])
def reset():
    if request.method == "POST":
        try:
            data, status = sendPasswordResetEmail(request.form["email"])
            flash("Password reset email sent." if status == 200 else data.get("error", {}).get("message", "Reset failed"), "success" if status == 200 else "error")
        except Exception as exc:
            flash("We couldn't send the reset email. Check your connection and try again.", "error")
    return render_template("fr01_user_management/reset.html")


@bp.get("/verification")
def verification():
    if not session.get("id_token"):
        return redirect(url_for("operator_fr01.login"))
    response = call_api("GET", "/api/fr1/me")
    profile = response.json().get("profile", {}) if response.ok else {}
    status = str(profile.get("verificationStatus", "pending")).lower()
    return render_template("fr01_user_management/verification.html", profile=profile, verification_status=status)


@bp.route("/profile", methods=["GET", "POST"])
def profile():
    if not session.get("id_token"):
        return redirect(url_for("operator_fr01.login"))
    if request.method == "POST":
        payload = {
            "name": request.form.get("name", ""),
            "companyName": request.form.get("companyName", ""),
            "businessContact": request.form.get("businessContact", ""),
            "phoneNo": request.form.get("phoneNo", ""),
        }
        response = call_api("PUT", "/api/fr1/me", json=payload)
        flash("Profile updated." if response.ok else _api_error(response), "success" if response.ok else "error")
        if response.ok:
            return redirect(url_for("operator_fr01.profile"))
        profile = {**(request.form.to_dict()), **payload}
        return render_template("fr01_user_management/profile.html", profile=profile, form=payload)
    response = call_api("GET", "/api/fr1/me")
    profile = response.json().get("profile", {}) if response.ok else {}
    if not response.ok:
        flash("We couldn't load your business profile. Try again.", "error")
    return render_template("fr01_user_management/profile.html", profile=profile, form=profile)


@bp.post("/logout")
def logout():
    signOutUser(session)
    return redirect(url_for("operator_fr01.login"))
