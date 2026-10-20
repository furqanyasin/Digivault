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
    "apps.heatmap",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "csp.middleware.CSPMiddleware",
    # Before CorsMiddleware: the public ingest endpoints are reached from every
    # client website's own origin, which no allowlist can enumerate. See the
    # module docstring for why this is separate from CORS_ALLOWED_ORIGINS.
    "apps.common.ingest_cors.PublicIngestCorsMiddleware",
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

# Connection pool, for the uvicorn services only (DB_POOL=1 in their compose
# environment). Without it every request opened and closed its own Postgres
# connection — six or more times per pageview on /api/ingest/ alone. Django's
# pool is per process; under ASGI sync views share one thread per process, so a
# handful of connections per worker is plenty, and 4 + 2 uvicorn workers at
# max_size 4 stay far below Postgres's 100.
#
# Not for Celery: prefork children would each build their own pool and multiply
# connections, and Celery already opens and closes around each task. A pool
# also cannot be combined with CONN_MAX_AGE, which is why that stays unset.
if env.bool("DB_POOL", default=False):
    DATABASES["default"].setdefault("OPTIONS", {})["pool"] = {
        "min_size": env.int("DB_POOL_MIN_SIZE", default=1),
        "max_size": env.int("DB_POOL_MAX_SIZE", default=4),
        # Seconds to wait for a free connection before raising. Short, so a
        # saturated pool fails a request loudly instead of queueing it silently.
        "timeout": env.int("DB_POOL_TIMEOUT", default=10),
    }

# ------------------------------------------------------------------
# Cache — Redis
# ------------------------------------------------------------------

# One Redis instance, four jobs — cache, Celery broker, Celery results, and the
# Channels layer — and they used to share one DB index. That is survivable right
# up until it is not: `cache.clear()`, a stray `FLUSHDB`, or an eviction under
# memory pressure would take the queued task backlog with it, and a Celery
# result backend writing a key per task shares its memory budget with the
# sessions that hold people's logins.
#
# Split by index so each can be reasoned about (and flushed) on its own. Each is
# independently overridable, so moving one onto its own instance later is a
# config change rather than a code change.
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")


def _redis_db(url: str, index: int) -> str:
    """Point `url` at a specific Redis DB index, keeping everything else.

    Parsed rather than string-sliced: `redis://redis:6379` has no path at all,
    and rpartitioning on "/" turns it into `redis://2`, which resolves to a host
    called "2" and fails at connect time rather than at import.
    """
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    if parts.scheme not in ("redis", "rediss"):
        # A unix socket or anything else: the path is not a DB index and
        # rewriting it would break the URL. Set CACHE_URL / CELERY_BROKER_URL /
        # CHANNEL_REDIS_URL explicitly for those deployments.
        return url
    return urlunsplit(
        (parts.scheme, parts.netloc, f"/{index}", parts.query, parts.fragment)
    )


CACHE_URL = env("CACHE_URL", default=_redis_db(REDIS_URL, 1))
CELERY_BROKER_REDIS_URL = env("CELERY_BROKER_URL", default=_redis_db(REDIS_URL, 2))
CELERY_RESULT_REDIS_URL = env("CELERY_RESULT_URL", default=_redis_db(REDIS_URL, 3))
CHANNEL_REDIS_URL = env("CHANNEL_REDIS_URL", default=_redis_db(REDIS_URL, 4))

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": CACHE_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        "KEY_PREFIX": "stacksmonitor",
    }
}

# ------------------------------------------------------------------
# Django Channels
# ------------------------------------------------------------------

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [CHANNEL_REDIS_URL],
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
    # 0 = throttle on REMOTE_ADDR, which uvicorn has already resolved from the
    # proxy chain (apps/common/client_ip.py). Unset, DRF keys anonymous
    # throttles on the raw X-Forwarded-For string, which the client writes: a
    # different value per request was a fresh bucket per request.
    "NUM_PROXIES": 0,
    # Auth (login + token refresh) is proxied server-side by the Next.js app, so
    # Django sees a single shared IP for it — a tight per-IP "anon" cap then locks
    # everyone out (refresh alone fires every few minutes). Keep anon generous and
    # env-tunable; brute-force protection on login is a dedicated "auth" scope.
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("THROTTLE_ANON", default="1000/hour"),
        "user": env("THROTTLE_USER", default="10000/day"),
        "auth": env("THROTTLE_AUTH", default="120/minute"),
        # Public signup and email verification, per client IP.
        "signup": env("THROTTLE_SIGNUP", default="20/hour"),
        # Free website tools on the marketing site (SSL, domain, uptime,
        # script checks). Each call makes outbound requests, so keep it tight.
        "public_tools": env("THROTTLE_PUBLIC_TOOLS", default="30/hour"),
        # All three ingest scopes are keyed per site_id, not per IP. They are
        # separate buckets because the endpoints are not comparable: the script
        # ingest posts several times per pageview, while a form submission
        # happens once per conversion. Sharing one bucket let the loud endpoint
        # spend it and answered 429 to every conversion for the rest of the day.
        "ingest": env("THROTTLE_INGEST", default="10000/day"),
        # Sized for conversions, not pageviews: a site taking a thousand form
        # submissions a day is having a very good day, and anything past this is
        # a loop or a bot rather than business.
        "ingest_forms": env("THROTTLE_INGEST_FORMS", default="1000/day"),
        # The snippet already caps itself at 10 distinct errors per page load,
        # deduplicated; this bounds a site that is broken on every page.
        "ingest_js_errors": env("THROTTLE_INGEST_JS_ERRORS", default="2000/day"),
        "extension": env("THROTTLE_EXTENSION", default="300/hour"),
        # The extension's password-only sign-in, per IP. It is called straight
        # from each user's browser (not through the Next.js proxy), so the IP is
        # the user's own — this is the brute-force bound on a login with no
        # second factor.
        "extension_login": env("THROTTLE_EXTENSION_LOGIN", default="20/minute"),
        # Keyed per site, not per IP. The snippet flushes on shutdown plus a
        # 5-minute cron, so a busy site is well under this; the cap exists to
        # bound a runaway hook loop, not to shape normal traffic.
        "wp_activity": env("THROTTLE_WP_ACTIVITY", default="2000/hour"),
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

CELERY_BROKER_URL = CELERY_BROKER_REDIS_URL
CELERY_RESULT_BACKEND = CELERY_RESULT_REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300  # 5 minutes hard limit per task

# Nothing reads a task's result — no AsyncResult, no `.get()` — yet every task
# wrote one (plus a STARTED state, via TRACK_STARTED) into Redis and kept it for
# a day. Ingest alone is six or more tasks per pageview across every client
# site. That Redis runs `maxmemory-policy noeviction`, so the keys accumulate
# until it is full and then refuses *all* writes — including the broker's, which
# stops ingest and uptime checks together. Ignoring results also skips the
# STARTED write (celery/app/trace.py). A task that ever needs its result can set
# `ignore_result=False` on itself.
CELERY_TASK_IGNORE_RESULT = env.bool("CELERY_TASK_IGNORE_RESULT", default=True)

# ------------------------------------------------------------------
# Celery queues
# ------------------------------------------------------------------

# Everything used to run on one queue behind one worker at concurrency 2, which
# meant the platform's fastest and slowest work competed for the same two slots:
# a PageSpeed call (60s timeout), a whois lookup, a headless-Chromium capture, a
# monthly PDF, or an SEO walk that deliberately paces itself through the
# per-host budget would each hold a slot for a minute or more. Two of those at
# once and script ingest stopped — six posts per pageview across every client
# site, queued behind a report nobody was waiting for. Uptime checks queued
# behind it too, which is the failure that matters most: a monitoring platform
# whose checks are late reports outages late.
#
# Three queues, split by what the work *is*, not by which app it lives in:
#
#   ingest    — public, traffic-driven, high-frequency, must never wait.
#   monitors  — time-critical and self-scheduling. A check confirmed at 15s and
#               45s is worthless if it sits in a queue for two minutes.
#   slow      — anything that talks to a third party on its own schedule, walks
#               many pages, renders, or sweeps a table. Nobody is watching it.
#
# Anything unrouted stays on the default `celery` queue (alert delivery, chat,
# credential jobs) — short work with no special timing needs.
#
# **Routing and the worker command line are one change.** A task routed to a
# queue nothing consumes is not slow, it is lost; see the compose files.
CELERY_TASK_DEFAULT_QUEUE = "celery"

CELERY_TASK_ROUTES = {
    # ── ingest ───────────────────────────────────────────────────────────────
    "scripts.process_ingest_payload": {"queue": "ingest"},
    "heatmap.process_heatmap_payload": {"queue": "ingest"},
    # The name this task registered under before it was given an explicit one.
    # Kept for one deploy so messages already in flight are not misrouted.
    "apps.heatmap.tasks.process_heatmap_payload": {"queue": "ingest"},
    "scripts.deliver_form_error_alert": {"queue": "ingest"},
    "scripts.deliver_recipient_change_alert": {"queue": "ingest"},
    "scripts.flush_ingest_batch": {"queue": "ingest"},
    "scripts.sweep_ingest_buffers": {"queue": "ingest"},
    # ── monitors ─────────────────────────────────────────────────────────────
    "monitors.run_due_checks": {"queue": "monitors"},
    "monitors.check_single_monitor": {"queue": "monitors"},
    # ── slow ─────────────────────────────────────────────────────────────────
    "performance.*": {"queue": "slow"},
    "reports.*": {"queue": "slow"},
    "domains.*": {"queue": "slow"},
    "site_health.*": {"queue": "slow"},
    "heatmap.run_due_snapshot_captures": {"queue": "slow"},
    "heatmap.capture_page_snapshot": {"queue": "slow"},
    "heatmap.purge_old_heatmap_data": {"queue": "slow"},
    "websites.run_initial_checks": {"queue": "slow"},
    "websites.run_due_passive_scans": {"queue": "slow"},
    "websites.passive_scan_website": {"queue": "slow"},
    "websites.recalculate_all_health": {"queue": "slow"},
    "websites.sync_wp_api_form_recipients": {"queue": "slow"},
    "scripts.purge_old_snapshots": {"queue": "slow"},
    "monitors.rollup_daily_uptime": {"queue": "slow"},
    "monitors.purge_old_checks": {"queue": "slow"},
    "common.maintain_partitions": {"queue": "slow"},
    "alerts.purge_old_notifications": {"queue": "slow"},
    "audit.purge_old_logs": {"queue": "slow"},
    "credentials.purge_expired_shares": {"queue": "slow"},
    # 10-20s per call to Google; never on the monitors queue, where it would
    # delay every other site's checks.
    "monitors.google_second_opinion": {"queue": "slow"},
}

# A worker that has taken a long task should not also be sitting on a dozen
# short ones it has reserved and cannot start. The default prefetch of 4 is
# tuned for tasks measured in milliseconds; half of ours are measured in
# seconds, and a reserved-but-unstarted uptime check is a late uptime check.
CELERY_WORKER_PREFETCH_MULTIPLIER = env.int("CELERY_WORKER_PREFETCH_MULTIPLIER", default=1)

# Redis is not durable here (see the compose files) and a worker can be killed
# mid-task by a deploy. Acknowledging after the task finishes means an
# interrupted task is redelivered rather than silently lost. Every task routed
# above is idempotent or naturally repeatable — an ingest payload re-diffs to
# the same result, a monitor check just checks again.
CELERY_TASK_ACKS_LATE = env.bool("CELERY_TASK_ACKS_LATE", default=True)
CELERY_WORKER_MAX_TASKS_PER_CHILD = env.int(
    "CELERY_WORKER_MAX_TASKS_PER_CHILD", default=500
)

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
    # Where each WordPress form delivers, read from the site's own plugin REST
    # API with a vaulted Application Password. Config, not traffic, so it only
    # moves when someone edits a form — a daily read is plenty, and the Forms
    # tab can trigger one on demand.
    #
    # There were two of these. `sync-wp-form-recipients-daily` was named for the
    # retired WP Connect route but had been repointed at the same function this
    # one calls, so the identical sweep ran twice a day — and the older entry
    # did not skip sites whose credential had already been rejected, spending
    # every 06:45 re-presenting a known-bad password from our one egress IP.
    "sync-wp-api-form-recipients-daily": {
        "task": "websites.sync_wp_api_form_recipients",
        "schedule": crontab(hour=7, minute=45),
    },
    "run-due-seo-checks": {
        "task": "site_health.run_due_seo_checks",
        "schedule": crontab(hour=4, minute=0),
    },
    # Script detection for sites with no snippet installed. One homepage fetch
    # per site per day, through the shared per-host budget. Without it the
    # Scripts tab stayed empty forever and the agency could not tell "no
    # third-party scripts" from "we have never looked".
    "run-due-passive-scans": {
        "task": "websites.run_due_passive_scans",
        "schedule": crontab(hour=5, minute=0),
    },
    # Performance used to be measured once, in the post-save signal, and never
    # again — a site could regress for months while the dashboard quoted its
    # day-one score. Calls Google's API, not the customer's origin, so it
    # carries no blacklist risk.
    "run-due-performance-checks": {
        "task": "performance.run_due_checks",
        "schedule": crontab(hour=5, minute=30, day_of_week="monday"),
    },
    # Backdrop screenshots for the heatmap. Only pages that already carry
    # interaction data are captured, and each capture takes a token from the
    # same per-host budget as uptime monitoring — so it runs at 02:00, well
    # clear of the 04:00-07:00 block where the SEO, scan and WP sweeps live.
    # A no-op unless Playwright/Chromium is installed.
    "run-due-snapshot-captures": {
        "task": "heatmap.run_due_snapshot_captures",
        "schedule": crontab(hour=2, minute=0),
    },
    # SiteEvent grew a WordPress activity feed; without a purge that table is
    # unbounded across every client. Sunday 03:30, right after the snapshot
    # purge and well clear of the 04:00-07:00 block where the SEO, scan and WP
    # sweeps contend for the per-host budget.
    # A component change with no matching wp-admin action means an SFTP or
    # WP-CLI edit -- or a compromise. Hourly, because the merge window is 24h
    # and a daily pass would leave a real finding sitting for up to a day.
    "flag-unattributed-changes-hourly": {
        "task": "site_health.flag_unattributed_changes",
        "schedule": crontab(minute=20),
    },
    "purge-old-site-events-weekly": {
        "task": "site_health.purge_old_site_events",
        "schedule": crontab(hour=3, minute=30, day_of_week="sunday"),
    },
    # Heatmap cells are the highest-cardinality rows in the codebase and were
    # the last event table with no purge at all. Sunday 03:45, in the same
    # quiet window as the other purges and clear of the 04:00-07:00 block where
    # the SEO, scan and WP sweeps contend for the per-host budget.
    "purge-old-heatmap-data-weekly": {
        "task": "heatmap.purge_old_heatmap_data",
        "schedule": crontab(hour=3, minute=45, day_of_week="sunday"),
    },
    "purge-old-snapshots-weekly": {
        "task": "scripts.purge_old_snapshots",
        "schedule": crontab(hour=3, minute=0, day_of_week="sunday"),
    },
    # Expired temporary shares already grant nothing (every read filters on
    # `.active()`); this only keeps the table from collecting them.
    "purge-expired-credential-shares-daily": {
        "task": "credentials.purge_expired_shares",
        "schedule": crontab(hour=3, minute=15),
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
    # Batched ingest: reschedule any buffered page whose flush was lost. A no-op
    # scan of nothing while no site is batched (INGEST_BATCH_SITES empty).
    # Monthly partitions three months ahead, for tables converted with
    # `manage.py partition_table`. A no-op until one has been.
    "maintain-partitions": {
        "task": "common.maintain_partitions",
        "schedule": crontab(hour=3, minute=30),
    },
    "sweep-ingest-buffers": {
        "task": "scripts.sweep_ingest_buffers",
        "schedule": 300.0,
    },
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
# Monitors
# ------------------------------------------------------------------

# Ceiling on how many uptime checks leave the platform per beat tick (30s).
# All checks share one public egress IP, so a simultaneous fleet-wide burst
# reads as a scanner sweep to Cloudflare/Sucuri/AWS WAF and gets that IP
# challenged or blackholed. Raise only if outbound checks fall behind.
MONITOR_MAX_CHECKS_PER_TICK = env.int("MONITOR_MAX_CHECKS_PER_TICK", default=8)

# A failing request is confirmed this many times before it counts as an outage,
# with these gaps (seconds) between attempts. Three requests, one data point.
MONITOR_CONFIRM_ATTEMPTS = env.int("MONITOR_CONFIRM_ATTEMPTS", default=3)
MONITOR_CONFIRM_DELAYS = env.list("MONITOR_CONFIRM_DELAYS", cast=int, default=[15, 45])

# Every outbound fetch of a customer origin draws on a per-host budget, keyed on
# the registrable domain. The monitor bypasses it (its own interval is gentler);
# the burst callers — SEO checker, scan, verify — do not.
OUTBOUND_MIN_INTERVAL_SECONDS = env.int("OUTBOUND_MIN_INTERVAL_SECONDS", default=20)
OUTBOUND_MAX_PER_HOUR = env.int("OUTBOUND_MAX_PER_HOUR", default=60)

# Before a confirmed failure becomes a down alert, the monitor checks whether
# real visitors were being served (website.last_seen_at, bumped on every ingest).
# Recent traffic means we are blocked, not the site down. Capped so a
# permanently blocked monitor cannot go permanently silent.
# ── heatmap backdrop screenshots ─────────────────────────────────────────────
# How long a captured page snapshot stays fresh. Marketing pages change slowly
# and every recapture spends the shared per-host budget, so this is generous.
HEATMAP_SNAPSHOT_MAX_AGE_DAYS = env.int("HEATMAP_SNAPSHOT_MAX_AGE_DAYS", default=14)
# Captures dispatched per nightly sweep. Capped because the budget is shared
# with uptime monitoring, and monitoring wins.
HEATMAP_SNAPSHOT_MAX_PER_RUN = env.int("HEATMAP_SNAPSHOT_MAX_PER_RUN", default=20)
# How long interaction cells and page stats are kept, aged on `last_seen_at` so
# a page that is still being visited is never purged. `HeatmapActivity` is the
# highest-cardinality table here — up to 100x100 grid cells times twenty
# segment buckets per page — and it shipped without a purge, which is fine at
# one site and is not across an agency's whole book.
HEATMAP_DATA_MAX_AGE_DAYS = env.int("HEATMAP_DATA_MAX_AGE_DAYS", default=180)
# Heatmap ingest posts per site per day. Much higher than the script ingest's
# 2000 because these are per *pageview*, not per site change: a visitor reading
# for five minutes flushes several times, so a modestly busy site legitimately
# posts thousands of times a day. It is an abuse ceiling, not a sampling knob.
HEATMAP_INGEST_RATE = env.str("HEATMAP_INGEST_RATE", default="100000/day")

LIVENESS_WINDOW_SECONDS = env.int("LIVENESS_WINDOW_SECONDS", default=600)
LIVENESS_MAX_SUPPRESSED_CHECKS = env.int("LIVENESS_MAX_SUPPRESSED_CHECKS", default=6)

# Published at /api/monitoring-info/ so a client can allowlist us. UptimeRobot
# publishes its IPs for the same reason: an unidentifiable prober is one a WAF
# has no choice but to block.
MONITOR_EGRESS_IPS = env.list("MONITOR_EGRESS_IPS", default=[])
# Override the outbound User-Agent (apps/common/outbound.py). Leave unset to
# use the default; it must keep naming Stacks Monitor and linking to /bot.
MONITOR_USER_AGENT = env("MONITOR_USER_AGENT", default="")
# When MONITOR_EGRESS_IPS is unset, ask an IP-echo service what our public IP
# is (cached 6h) so allowlist instructions can name it. Off in tests.
MONITOR_DETECT_EGRESS_IP = env.bool("MONITOR_DETECT_EGRESS_IP", default=True)
# When a firewall blocks our checks, ask Google PageSpeed whether the site is up
# (needs PAGESPEED_API_KEY). See apps/monitors/second_opinion.py. Off in tests.
MONITOR_SECOND_OPINION = env.bool("MONITOR_SECOND_OPINION", default=True)

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
# Plans
# ------------------------------------------------------------------

# Per-plan caps (websites, monitors, members...) from apps/accounts/plans.py.
# Off in the test settings, where fixtures build teams of any size; the plan
# tests switch it back on.
ENFORCE_PLAN_LIMITS = env.bool("ENFORCE_PLAN_LIMITS", default=True)

# Accounts that run the platform itself: superuser + staff, see /platform and
# Django admin. Applied on every api start by `make_platform_owner`.
PLATFORM_OWNER_EMAILS = env.list("PLATFORM_OWNER_EMAILS", default=["furqanyasin1997@gmail.com"])

# ------------------------------------------------------------------
# Product identity
# ------------------------------------------------------------------

# The public name and home of the product. Emails, reports and firewall
# instructions read these instead of hardcoding them, so a rename is one line.
PRODUCT_NAME = env("PRODUCT_NAME", default="Stacks Monitor")
PRODUCT_URL = env("PRODUCT_URL", default="https://stacksmonitor.com").rstrip("/")
# The public allowlist page a client's firewall admin is sent to. It must stay
# reachable without a login: the reader is not one of our users.
BOT_INFO_URL = f"{PRODUCT_URL}/bot"

# ------------------------------------------------------------------
# Tracking snippet origin
# ------------------------------------------------------------------

# Where `Website.snippet_html` points the client's <script src>, and the host
# `apps.scripts.tasks._internal_hosts()` refuses to track as a third party.
#
# Declared here rather than only in production.py, which is where it used to
# live. Everything reads it through `getattr(settings, "SNIPPET_CDN_URL", ...)`,
# so under development and test settings it simply was not there and the
# fallback took over — a snippet pointing at a `cdn.` host that had no DNS
# record and never had one. A setting that exists in exactly
# one environment is a setting that is wrong in the others.
#
# The `/api` suffix is load-bearing: nginx only proxies `/api/...` to Django, so
# a base without it yields `https://host/s.js`, which nginx hands to the Next.js
# frontend and the snippet 404s.
SNIPPET_CDN_URL = env("SNIPPET_CDN_URL", default="http://localhost:8000/api")

# ------------------------------------------------------------------
# WPScan — WordPress vulnerability data
# ------------------------------------------------------------------

# `apps.site_health.tasks` reads this to look up real CVEs for the plugins it
# detects. It was read via getattr and never declared anywhere, so it was
# permanently empty: every "vulnerability" the product reported came from the
# hardcoded `_RISKY_PLUGINS` substring list instead, and those reports feed the
# health score. Declaring it does not switch the feature on — that still needs a
# key — but it makes the difference between "no key configured" and "silently
# disabled forever" visible in one place.
WPSCAN_API_KEY = env("WPSCAN_API_KEY", default="")

# ------------------------------------------------------------------
# Email
# ------------------------------------------------------------------

_email_config = env.email_url("EMAIL_URL", default="consolemail://")
globals().update(_email_config)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Stacks Monitor <noreply@stacksmonitor.com>")

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
# How far past its due time an active monitor may be before the heartbeat stops
# pinging. run_due_checks claims a monitor (writes last_checked_at) the moment it
# dispatches, so a healthy schedule is never more than one 30s tick late; five
# minutes only trips when beat or the monitors worker has actually stopped, or
# the fleet has outgrown MONITOR_MAX_CHECKS_PER_TICK — both worth a page.
HEARTBEAT_MONITOR_GRACE_SECONDS = env.int("HEARTBEAT_MONITOR_GRACE_SECONDS", default=300)
# Waiting messages per queue above which the heartbeat is withheld (a backlog:
# workers alive but not keeping up). Override as
# HEARTBEAT_QUEUE_LIMITS=ingest=5000;monitors=200;slow=500;celery=1000 —
# semicolons: with a typed cast django-environ splits entries on ";", and a
# comma-separated value fails at startup trying to read "5000,monitors" as int.
# Batched ingest (apps/scripts/ingest_batch.py): site_ids whose posts are
# buffered per page and diffed once per burst instead of once per post. Empty
# (the default) means every site uses the unbatched path; "*" means all. Turn a
# site on when its `ingest_lock` log lines show contention, not before
# (docs/runbooks/capacity-checks.md). Comma-separated.
INGEST_BATCH_SITES = env.list("INGEST_BATCH_SITES", default=[])
# How long a page's posts collect before they are diffed together. A page
# load posts over ~30s, so 15s gathers most of a load into two batches.
INGEST_BATCH_DELAY_SECONDS = env.int("INGEST_BATCH_DELAY_SECONDS", default=15)

HEARTBEAT_QUEUE_LIMITS = env.dict(
    "HEARTBEAT_QUEUE_LIMITS",
    cast={"value": int},
    default={"ingest": 5000, "monitors": 200, "slow": 500, "celery": 1000},
)

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
            # 5%: enough to rank slow endpoints and tasks without spending the
            # quota on ingest, which is six or more requests and six or more
            # tasks per pageview across every client site.
            traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.05),
            send_default_pii=False,
            environment=env("SENTRY_ENVIRONMENT", default="production"),
        )
    except ImportError:
        pass
