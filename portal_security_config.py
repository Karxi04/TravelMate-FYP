import os

from flask import request, session
from flask_wtf.csrf import CSRFError, CSRFProtect

from request_rate_limit import init_rate_limiter, rate_limit_response


LOCAL_ENVIRONMENTS = {"development", "dev", "local", "test", "testing"}
WEAK_SECRETS = {
    "",
    "change-me",
    "change-this-development-secret",
    "replace-with-a-random-string",
    "replace-with-another-random-string",
}


def env_flag(name, default=False, environ=None):
    source = environ if environ is not None else os.environ
    value = source.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def resolve_secret(environ=None, portal_name="portal"):
    source = environ if environ is not None else os.environ
    environment = str(source.get("APP_ENV", "development")).strip().lower()
    secret = str(source.get("SECRET_KEY", "")).strip()
    if environment not in LOCAL_ENVIRONMENTS and secret.lower() in WEAK_SECRETS:
        raise RuntimeError(
            f"{portal_name} SECRET_KEY must be configured with strong deployment secret material"
        )
    if secret:
        return secret
    return f"travelmate-{portal_name}-local-development-only"


def configure_portal_app(app, cookie_name, portal_name, environ=None):
    source = environ if environ is not None else os.environ
    environment = str(source.get("APP_ENV", "development")).strip().lower()
    production = environment not in LOCAL_ENVIRONMENTS
    app.config.update(
        SECRET_KEY=resolve_secret(source, portal_name),
        SESSION_COOKIE_NAME=cookie_name,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=env_flag(
            "SESSION_COOKIE_SECURE",
            default=production,
            environ=source,
        ),
        WTF_CSRF_ENABLED=True,
        WTF_CSRF_CHECK_DEFAULT=True,
        WTF_CSRF_TIME_LIMIT=3600,
    )
    CSRFProtect(app)
    init_rate_limiter(app)

    @app.errorhandler(CSRFError)
    def csrf_error(_error):
        return (
            "This form has expired or could not be verified. Reload the page and try again.",
            400,
            {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"},
        )

    @app.before_request
    def limit_authentication():
        if request.method == "POST" and request.endpoint in {
            "admin_fr01.login", "operator_fr01.login",
            "operator_fr01.register", "operator_fr01.reset",
        }:
            return rate_limit_response("authentication", session.get("uid"))

    return app
