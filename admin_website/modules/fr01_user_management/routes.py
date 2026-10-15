import time
import requests
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from firebase_auth_rest import authenticateCredentials, signOutUser
from api_client import call_api

bp = Blueprint("admin_fr01", __name__, template_folder="templates")

def _store_auth(data):
    session["id_token"] = data["idToken"]
    session["refresh_token"] = data.get("refreshToken")
    session["uid"] = data.get("localId")
    session["token_expires_at"] = time.time() + int(data.get("expiresIn", 3600))


def _clean_firebase_error(data):
    error_code = data.get("error", {}).get("message", "Login failed") if isinstance(data, dict) else "Login failed"
    if error_code in {"INVALID_LOGIN_CREDENTIALS", "INVALID_PASSWORD", "EMAIL_NOT_FOUND"}:
        return "Invalid email or password."
    if error_code == "USER_DISABLED":
        return "This account has been disabled. Please contact support."
    if error_code == "TOO_MANY_ATTEMPTS_TRY_LATER":
        return "Too many failed attempts. Please try again later."
    return str(error_code).replace("_", " ").capitalize() if error_code else "Login failed."


@bp.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        try:
            data, status = authenticateCredentials(request.form["email"], request.form["password"])
        except Exception:
            flash("Unable to sign in. Please check your connection and try again.", "error")
            return render_template("fr01_user_management/login.html")

        if status == 200:
            _store_auth(data)
            try:
                me = call_api("GET", "/api/fr1/me")
            except requests.RequestException:
                session.clear()
                flash("Backend service is temporarily unavailable. Please try again shortly.", "error")
                return render_template("fr01_user_management/login.html")

            if not me.ok:
                session.clear()
                if me.status_code in (401, 403):
                    flash("Authentication session expired or invalid. Please sign in again.", "error")
                elif me.status_code >= 500:
                    flash("Backend service is temporarily unavailable. Please try again shortly.", "error")
                else:
                    flash("Unable to verify account with backend service. Please try again.", "error")
                return render_template("fr01_user_management/login.html")

            try:
                body = me.json()
            except (ValueError, AttributeError):
                session.clear()
                flash("Received an invalid response from backend service. Please try again.", "error")
                return render_template("fr01_user_management/login.html")

            profile = body.get("profile") if isinstance(body, dict) else None
            if not profile or not isinstance(profile, dict):
                session.clear()
                flash("User profile could not be found. Please contact support.", "error")
                return render_template("fr01_user_management/login.html")

            raw_role = str(profile.get("role", "")).strip().lower()
            if raw_role in {"admin", "administrator"}:
                session["portal_role"] = "admin"
                return redirect(url_for("admin_fr13.dashboard"))

            session.clear()
            flash("This account is not an Administrator account.", "error")
        else:
            flash(_clean_firebase_error(data), "error")
    return render_template("fr01_user_management/login.html")

@bp.route("/manage-user-account")
def manage_user_account():
    if not session.get("id_token"):
        return redirect(url_for("admin_fr01.login"))
    return redirect(url_for("admin_fr13.users"))

@bp.post("/logout")
def logout():
    signOutUser(session)
    return redirect(url_for("admin_fr01.login"))
