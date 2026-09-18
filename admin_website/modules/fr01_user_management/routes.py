import time
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from firebase_auth_rest import authenticateCredentials, signOutUser
from api_client import call_api

bp = Blueprint("admin_fr01", __name__, template_folder="templates")

def _store_auth(data):
    session["id_token"] = data["idToken"]
    session["refresh_token"] = data.get("refreshToken")
    session["uid"] = data.get("localId")
    session["token_expires_at"] = time.time() + int(data.get("expiresIn", 3600))

@bp.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        try:
            data, status = authenticateCredentials(request.form["email"], request.form["password"])
        except Exception as exc:
            flash(str(exc), "error")
            return render_template("fr01_user_management/login.html")
        if status == 200:
            _store_auth(data)
            me = call_api("GET", "/api/fr1/me")
            profile = me.json().get("profile") if me.ok else None
            if profile and profile.get("role") == "admin":
                return redirect(url_for("admin_fr13.dashboard"))
            session.clear()
            flash("This account is not an Administrator account.", "error")
        else:
            flash(data.get("error", {}).get("message", "Login failed"), "error")
    return render_template("fr01_user_management/login.html")

@bp.route("/manage-user-account")
def manage_user_account():
    if not session.get("id_token"):
        return redirect(url_for("admin_fr01.login"))
    return redirect(url_for("admin_fr13.users"))

@bp.route("/logout")
def logout():
    signOutUser(session)
    return redirect(url_for("admin_fr01.login"))
