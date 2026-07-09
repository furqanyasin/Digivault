from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401, F403
from .base import env

DEBUG = False

# Email must be a real SMTP relay in production. The consolemail:// fallback
# makes send_mail() report success while discarding every onboarding /
# password-reset email — this once broke member onboarding silently.
_email_url = env("EMAIL_URL", default="")
if not _email_url or _email_url.startswith("consolemail"):
    raise ImproperlyConfigured(
        "EMAIL_URL must be set to a real SMTP URL in .env.production, e.g. "
        "smtp+tls://LOGIN%40smtp-brevo.com:SMTP_KEY@smtp-relay.brevo.com:587 — "
        "the consolemail:// default silently discards onboarding and "
        "password-reset emails."
    )

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS") + ["127.0.0.1", "localhost"]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_SSL_REDIRECT = False  # nginx enforces HTTPS; internal HTTP calls from Next.js must not be redirected
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS")
assert all(
    not o.startswith("http://localhost") for o in CORS_ALLOWED_ORIGINS
), "CORS_ALLOWED_ORIGINS contains a localhost origin in production — check your environment."

# Enforce CSP in production (report-only is set in base)
CSP_REPORT_ONLY = False

# Snippet JS served from the same domain — no external CDN needed
SNIPPET_CDN_URL = env("SNIPPET_CDN_URL", default="https://digivault.digilatics.co")

_sentry_dsn = env("SENTRY_DSN", default="")
if _sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    sentry_sdk.init(
        dsn=_sentry_dsn,
        integrations=[DjangoIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
    )
