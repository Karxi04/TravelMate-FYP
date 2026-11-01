import time
import requests
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
    if "expired" in text.lower() or "id token" in text.lower():
        return "Your session expired while creating your account. Please try continuing your registration."
    if "not verified" in text.lower():
        return "Your operator account is still awaiting administrator approval."
    if "deactivated" in text.lower():
        return "This operator account is disabled. Contact TravelMate support."
    if "required" in text.lower() or "company" in text.lower():
        return "Please complete the required company information."
    if response.status_code >= 500:
        return "Unable to connect to TravelMate. Check your connection and try again."
    return text if text and text != fallback else "We couldn't complete that request. Try again."


def _clean_firebase_error(data):
    error_code = data.get("error", {}).get("message", "Login failed") if isinstance(data, dict) else "Login failed"
    if error_code in {"INVALID_LOGIN_CREDENTIALS", "INVALID_PASSWORD", "EMAIL_NOT_FOUND"}:
        return "Invalid email or password."
    if "EMAIL_EXISTS" in error_code:
        return "This email is already registered. Sign in to continue your account setup."
    if "EXPIRED" in error_code or "TOKEN_EXPIRED" in error_code:
        return "Your session expired while creating your account. Please try continuing your registration."
    if error_code == "USER_DISABLED":
        return "This account has been disabled. Please contact support."
    if error_code == "TOO_MANY_ATTEMPTS_TRY_LATER":
        return "Too many failed attempts. Please try again later."
    return str(error_code).replace("_", " ").capitalize() if error_code else "Login failed."


@bp.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        if not email or not password:
            flash("Please enter both email and password.", "error")
            return render_template("fr01_user_management/login.html")

        try:
            data, status = authenticateCredentials(email, password)
        except Exception:
            flash("Unable to connect to TravelMate. Check your connection and try again.", "error")
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

            # Recovery for interrupted registrations: Firebase user exists but Firestore profile is missing
            if not profile or not isinstance(profile, dict):
                session["portal_role"] = "operator"
                session["incomplete_setup"] = True
                flash("Please complete your business details to continue your account setup.", "info")
                return redirect(url_for("operator_fr01.complete_setup"))

            user_role = str(profile.get("role", "")).strip().lower()
            if user_role not in {"operator", "tourism_operator", "admin"}:
                session.clear()
                flash("This account is not a Tourism Operator account.", "error")
                return render_template("fr01_user_management/login.html")

            session.pop("incomplete_setup", None)
            session["portal_role"] = user_role
            verification_status = str(profile.get("verificationStatus", "pending")).strip().lower()
            session["verification_status"] = verification_status

            if user_role != "admin" and verification_status not in {"approved", "verified"}:
                if verification_status in {"rejected", "disabled", "deactivated"}:
                    flash("Your operator account needs attention before publishing can begin.", "error")
                return redirect(url_for("operator_fr01.verification"))
            else:
                return redirect(url_for("operator_fr12.dashboard"))
        else:
            flash(_clean_firebase_error(data), "error")
    return render_template("fr01_user_management/login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        name = (request.form.get("name") or "").strip()
        company_name = (request.form.get("companyName") or "").strip()
        reg_no = (request.form.get("registrationNo") or "").strip()
        business_contact = (request.form.get("businessContact") or "").strip()

        if not name or not company_name or not reg_no or not business_contact or not email or not password:
            flash("Please complete all required fields.", "error")
            return render_template("fr01_user_management/register.html", form=request.form)

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return render_template("fr01_user_management/register.html", form=request.form)

        try:
            data, status = createUserAccount(email, password)
        except Exception:
            flash("Unable to connect to TravelMate. Check your connection and try again.", "error")
            return render_template("fr01_user_management/register.html", form=request.form)

        if status == 200:
            _store_auth(data)
            payload = {
                "role": "operator",
                "name": name,
                "companyName": company_name,
                "registrationNo": reg_no,
                "businessContact": business_contact,
            }
            response = call_api("POST", "/api/fr1/profile", json=payload)
            if response.ok:
                session.clear()
                flash("Your Operator account has been created and is awaiting Administrator verification.", "success")
                return redirect(url_for("operator_fr01.login"))

            flash("We couldn't complete your account setup. Your email may already be registered. Please sign in to continue.", "error")
            return redirect(url_for("operator_fr01.login"))
        else:
            error_code = data.get("error", {}).get("message", "") if isinstance(data, dict) else ""
            if "EMAIL_EXISTS" in error_code:
                flash("This email is already registered. Sign in to continue your account setup.", "error")
                return redirect(url_for("operator_fr01.login"))
            elif "WEAK_PASSWORD" in error_code:
                flash("Password must be at least 8 characters with a mix of letters and numbers.", "error")
            elif "INVALID_EMAIL" in error_code:
                flash("Please enter a valid business email address.", "error")
            elif "TOO_MANY_ATTEMPTS_TRY_LATER" in error_code:
                flash("Too many failed attempts. Please try again later.", "error")
            else:
                flash("Registration failed. Please check your details and try again.", "error")
            return render_template("fr01_user_management/register.html", form=request.form)

    # Clean session state when opening register page
    session.clear()
    return render_template("fr01_user_management/register.html")


@bp.route("/complete-setup", methods=["GET", "POST"])
def complete_setup():
    if not session.get("id_token"):
        return redirect(url_for("operator_fr01.login"))

    profile = {}
    try:
        me = call_api("GET", "/api/fr1/me")
        if me.ok and isinstance(me.json(), dict):
            profile = me.json().get("profile") or {}
    except Exception:
        profile = {}

    if profile and isinstance(profile, dict):
        user_role = str(profile.get("role", "")).strip().lower()
        if user_role and user_role not in {"operator", "tourism_operator"}:
            session.clear()
            flash("This account is not authorized for operator setup.", "error")
            return redirect(url_for("operator_fr01.login"))

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        company_name = (request.form.get("companyName") or "").strip()
        reg_no = (request.form.get("registrationNo") or "").strip()
        business_contact = (request.form.get("businessContact") or "").strip()

        if not name or not company_name or not reg_no or not business_contact:
            flash("Please complete all required fields.", "error")
            return render_template("fr01_user_management/complete_setup.html", profile=profile, form=request.form)

        payload = {
            "role": "operator",
            "name": name,
            "companyName": company_name,
            "registrationNo": reg_no,
            "businessContact": business_contact,
        }
        response = call_api("POST", "/api/fr1/profile", json=payload)
        if response.ok:
            session.pop("incomplete_setup", None)
            session["portal_role"] = "operator"
            session["verification_status"] = "pending"
            flash("Your Operator account has been created and is awaiting Administrator verification.", "success")
            return redirect(url_for("operator_fr01.verification"))
        else:
            flash(_api_error(response, "Setup failed. Please check your details and try again."), "error")
            return render_template("fr01_user_management/complete_setup.html", profile=profile, form=request.form)

    return render_template("fr01_user_management/complete_setup.html", profile=profile, form=profile)


@bp.route("/reset", methods=["GET", "POST"])
def reset():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        try:
            data, status = sendPasswordResetEmail(email)
            if status == 200:
                flash("Password reset email sent. Check your inbox to proceed.", "success")
            else:
                flash("If this email is registered, a password reset link has been sent.", "info")
        except Exception:
            flash("Unable to connect to TravelMate. Check your connection and try again.", "error")
    return render_template("fr01_user_management/reset.html")


@bp.get("/verification")
def verification():
    if not session.get("id_token"):
        return redirect(url_for("operator_fr01.login"))
    if session.get("incomplete_setup"):
        return redirect(url_for("operator_fr01.complete_setup"))
    response = call_api("GET", "/api/fr1/me")
    profile = response.json().get("profile", {}) if response.ok else {}
    status = str(profile.get("verificationStatus", "pending")).lower()
    if response.ok:
        session['verification_status'] = status
    return render_template("fr01_user_management/verification.html", profile=profile, verification_status=status)


@bp.route("/profile", methods=["GET", "POST"])
def profile():
    if not session.get("id_token"):
        return redirect(url_for("operator_fr01.login"))
    if session.get("incomplete_setup"):
        return redirect(url_for("operator_fr01.complete_setup"))
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
