from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

# ------------------------------------------------------------------
# Application definition
# ------------------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "channels",
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "csp",
]

LOCAL_APPS = [
    "apps.common",
    "apps.accounts",
    "apps.websites",
    "apps.scripts",
    "apps.credentials",
    "apps.domains",
    "apps.alerts",
    "apps.monitors",
    "apps.performance",
    "apps.status_pages",
    "apps.clients",
    "apps.chat",
    "apps.site_health",
    "apps.audit",
    "apps.reports",
    "apps.integrations",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "csp.middleware.CSPMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ------------------------------------------------------------------
# Database
# ------------------------------------------------------------------

DATABASES = {"default": env.db("DATABASE_URL")}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ------------------------------------------------------------------
# Cache — Redis
# ------------------------------------------------------------------

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://localhost:6379/0"),
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        "KEY_PREFIX": "digivault_hub",
    }
}

# ------------------------------------------------------------------
# Django Channels
# ------------------------------------------------------------------

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [env("REDIS_URL", default="redis://localhost:6379/0")],
            "capacity": 1500,
            "expiry": 10,
        },
    }
}

# ------------------------------------------------------------------
# Auth
# ------------------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ------------------------------------------------------------------
# REST Framework
# ------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "apps.common.renderers.EnvelopeJSONRenderer",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.StandardPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    # Auth (login + token refresh) is proxied server-side by the Next.js app, so
    # Django sees a single shared IP for it — a tight per-IP "anon" cap then locks
    # everyone out (refresh alone fires every few minutes). Keep anon generous and
    # env-tunable; brute-force protection on login is a dedicated "auth" scope.
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("THROTTLE_ANON", default="1000/hour"),
        "user": env("THROTTLE_USER", default="10000/day"),
        "auth": env("THROTTLE_AUTH", default="120/minute"),
        "ingest": env("THROTTLE_INGEST", default="10000/day"),
        "extension": env("THROTTLE_EXTENSION", default="300/hour"),
        "totp_verify": "10/minute",
        "totp_setup": "10/hour",
    },
    "EXCEPTION_HANDLER": "apps.common.exceptions.custom_exception_handler",
}

# ------------------------------------------------------------------
# SimpleJWT
# ------------------------------------------------------------------

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=env.int("JWT_ACCESS_TOKEN_LIFETIME_MINUTES", default=15)
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=env.int("JWT_REFRESH_TOKEN_LIFETIME_DAYS", default=7)
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
}

# ------------------------------------------------------------------
# Celery
# ------------------------------------------------------------------

CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300  # 5 minutes hard limit per task

# ------------------------------------------------------------------
# Celery Beat — scheduled tasks
# ------------------------------------------------------------------

from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    "run-monitor-checks": {
        "task": "monitors.run_due_checks",
        "schedule": 30.0,  # every 30 seconds
    },
    "check-all-domains-daily": {
        "task": "domains.check_all_domains",
        "schedule": crontab(hour=6, minute=0),
    },
    # Runs after check-all-domains so it scores the freshest expiry data, and
    # gives time-based deductions (expiry windows, reporting gap) a daily decay.
    "recalculate-all-health-daily": {
        "task": "websites.recalculate_all_health",
        "schedule": crontab(hour=6, minute=30),
    },
    "run-due-seo-checks": {
        "task": "site_health.run_due_seo_checks",
        "schedule": crontab(hour=4, minute=0),
    },
    "purge-old-snapshots-weekly": {
        "task": "scripts.purge_old_snapshots",
        "schedule": crontab(hour=3, minute=0, day_of_week="sunday"),
    },
    "purge-old-audit-logs-weekly": {
        "task": "audit.purge_old_logs",
        "schedule": crontab(hour=3, minute=30, day_of_week="sunday"),
    },
    "send-hourly-digest": {
        "task": "alerts.send_digest",
        "schedule": crontab(minute=0),
        "kwargs": {"mode": "hourly_digest"},
    },
    "send-daily-digest": {
        "task": "alerts.send_digest",
        "schedule": crontab(hour=8, minute=0),
        "kwargs": {"mode": "daily_digest"},
    },
    # Retention & rollups (Phase 0.1)
    "rollup-daily-uptime": {
        "task": "monitors.rollup_daily_uptime",
        "schedule": crontab(hour=0, minute=15),
    },
    "purge-old-monitor-checks": {
        "task": "monitors.purge_old_checks",
        "schedule": crontab(hour=1, minute=0),
    },
    "purge-old-performance-reports-weekly": {
        "task": "performance.purge_old_reports",
        "schedule": crontab(hour=2, minute=0, day_of_week="sunday"),
    },
    "purge-old-php-errors-weekly": {
        "task": "site_health.purge_old_php_errors",
        "schedule": crontab(hour=2, minute=30, day_of_week="sunday"),
    },
    "purge-old-notifications-weekly": {
        "task": "alerts.purge_old_notifications",
        "schedule": crontab(hour=2, minute=45, day_of_week="sunday"),
    },
    # Dead-man's-switch heartbeat (Phase 0.5) — no-op unless HEARTBEAT_PING_URL set
    "system-heartbeat": {
        "task": "common.system_heartbeat",
        "schedule": 300.0,  # every 5 minutes
    },
    # Monthly client reports (Phase 2.3) — 1st of month, 04:00 UTC
    "generate-monthly-reports": {
        "task": "reports.generate_monthly",
        "schedule": crontab(day_of_month=1, hour=4, minute=0),
    },
}

# ------------------------------------------------------------------
# Vault
# ------------------------------------------------------------------

# Legacy single key (still honored). Prefer VAULT_ENCRYPTION_KEYS for rotation.
VAULT_ENCRYPTION_KEY = env("VAULT_ENCRYPTION_KEY", default="")
# Ordered list of Fernet keys: first encrypts new data, all are tried on decrypt.
VAULT_ENCRYPTION_KEYS = env.list("VAULT_ENCRYPTION_KEYS", default=[])

# ------------------------------------------------------------------
# Frontend
# ------------------------------------------------------------------

FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:3000")

# ------------------------------------------------------------------
# Email
# ------------------------------------------------------------------

_email_config = env.email_url("EMAIL_URL", default="consolemail://")
globals().update(_email_config)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Digivault <noreply@digivault.digilatics.co>")

# ------------------------------------------------------------------
# Google PageSpeed Insights
# ------------------------------------------------------------------

PAGESPEED_API_KEY = env("PAGESPEED_API_KEY", default="")

# ------------------------------------------------------------------
# ClickUp integration
# ------------------------------------------------------------------

CLICKUP_API_TOKEN = env("CLICKUP_API_TOKEN", default="")

# ------------------------------------------------------------------
# Internationalisation
# ------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ------------------------------------------------------------------
# Static / Media
# ------------------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ------------------------------------------------------------------
# Content Security Policy (django-csp)
# ------------------------------------------------------------------

CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'",)
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'")  # inline styles needed by Tailwind
CSP_IMG_SRC = ("'self'", "data:", "https:")
CSP_FONT_SRC = ("'self'", "data:")
CSP_CONNECT_SRC = ("'self'",)
CSP_FRAME_ANCESTORS = ("'none'",)
CSP_BASE_URI = ("'none'",)
CSP_FORM_ACTION = ("'self'",)
# Report-only in dev — enforced in production via override
CSP_REPORT_ONLY = True

# ------------------------------------------------------------------
# Observability (Phase 0.5)
# ------------------------------------------------------------------

LOG_LEVEL = env("LOG_LEVEL", default="INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# Dead-man's-switch heartbeat ping URL (healthchecks.io / cronitor / etc.)
HEARTBEAT_PING_URL = env("HEARTBEAT_PING_URL", default="")

# Sentry — only initialised when SENTRY_DSN is provided. Guarded import so the
# project loads whether or not sentry-sdk is installed in the active env.
SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.django import DjangoIntegration

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[DjangoIntegration(), CeleryIntegration()],
            traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.0),
            send_default_pii=False,
            environment=env("SENTRY_ENVIRONMENT", default="production"),
        )
    except ImportError:
        pass
