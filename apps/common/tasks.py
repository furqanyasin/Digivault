"""Cross-cutting Celery tasks (observability / health)."""

import logging
import urllib.request

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(name="common.system_heartbeat")
def system_heartbeat() -> bool:
    """Dead-man's-switch: ping an external uptime check so a stalled Celery
    beat/worker is itself detected.

    Set ``HEARTBEAT_PING_URL`` to a healthchecks.io / cronitor / Better Uptime
    heartbeat URL. If beat stops scheduling this task (or workers stall), the
    external service stops receiving pings and alerts. Returns True on success.
    """
    url = getattr(settings, "HEARTBEAT_PING_URL", "")
    if not url:
        return False
    try:
        urllib.request.urlopen(url, timeout=10)
        return True
    except Exception:
        logger.warning("system_heartbeat: ping to %s failed", url)
        return False
