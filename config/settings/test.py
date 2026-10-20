from .development import *  # noqa: F401, F403
from .development import env  # noqa: F401

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-cache",
    }
}

# Run Celery tasks synchronously and store results in memory — no Redis needed in tests
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_RESULT_BACKEND = "cache+memory://"

# Never call an IP-echo service from the test suite.
MONITOR_DETECT_EGRESS_IP = False

# Never call Google PageSpeed from the suite; tests that need it enable it and
# mock the HTTP call.
MONITOR_SECOND_OPINION = False

# Fixtures build teams of every size on the default (free) plan. Tests that
# check the limits turn this back on with override_settings.
ENFORCE_PLAN_LIMITS = False
