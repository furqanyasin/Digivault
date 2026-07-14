from .base import *  # noqa: F401, F403
from .base import env

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0", "testserver"]

INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405

MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]  # noqa: F405

INTERNAL_IPS = ["127.0.0.1"]

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS", default=["http://localhost:3000"]
)

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Use in-memory channel layer during development / testing so Redis is not required
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

# Local-memory cache so Redis is not required for dev (login/rate-limit/device
# trust all read the cache). Mirrors the channel-layer override above.
CACHES = {  # type: ignore[assignment]
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Run Celery tasks inline in dev so the ingest pipeline works without a broker.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Local dev only: let login skip the mandatory 2FA gate and issue tokens
# directly. NEVER set in production settings.
ALLOW_2FA_BYPASS = True

# Disable throttling during tests so rate limits don't interfere
REST_FRAMEWORK = {  # type: ignore[assignment]
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_CLASSES": [],
}

# Disable CSP enforcement in development — report-only is still too noisy locally
CSP_REPORT_ONLY = False
MIDDLEWARE = [m for m in MIDDLEWARE if m != "csp.middleware.CSPMiddleware"]  # noqa: F405
