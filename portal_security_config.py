import os


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
    )
    return app
