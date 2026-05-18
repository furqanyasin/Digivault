from .development import *  # noqa: F401, F403
from .development import env  # noqa: F401

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-cache",
    }
}
