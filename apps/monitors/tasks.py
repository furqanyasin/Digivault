"""Celery tasks for uptime monitoring."""

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="monitors.run_due_checks")
def run_due_checks():
    """Check every active monitor whose next check is due.

    Called by Celery Beat every 30 seconds. Each monitor gets its own
    lightweight task so failures are isolated.
    """
    from apps.monitors.models import Monitor

    now = timezone.now()
    monitors = Monitor.objects.filter(is_active=True).exclude(status="paused")

    due = []
    for m in monitors:
        if m.last_checked_at is None:
            due.append(m.pk)
        else:
            seconds_since = (now - m.last_checked_at).total_seconds()
            if seconds_since >= m.check_interval:
                due.append(m.pk)

    logger.info("run_due_checks: %d monitors due", len(due))
    for pk in due:
        check_single_monitor.delay(str(pk))


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=5,
    name="monitors.check_single_monitor",
)
def check_single_monitor(self, monitor_id: str):
    """Run one health check for a monitor and persist the result."""
    from apps.monitors.checker import run_check
    from apps.monitors.models import Monitor, MonitorCheck

    try:
        monitor = Monitor.objects.get(pk=monitor_id)
    except Monitor.DoesNotExist:
        return

    if not monitor.is_active or monitor.status == "paused":
        return

    try:
        result = run_check(monitor)
    except Exception as exc:
        logger.exception("check_single_monitor: checker raised for %s", monitor_id)
        result = {
            "status": "down",
            "response_time_ms": None,
            "status_code": None,
            "error_message": str(exc)[:300],
        }

    previous_status = monitor.status
    new_status = result["status"]

    MonitorCheck.objects.create(
        monitor=monitor,
        status=new_status,
        response_time_ms=result.get("response_time_ms"),
        status_code=result.get("status_code"),
        error_message=result.get("error_message", ""),
    )

    # Update monitor state
    Monitor.objects.filter(pk=monitor.pk).update(
        status=new_status,
        last_checked_at=timezone.now(),
        last_response_time=result.get("response_time_ms"),
    )

    # Recalculate uptime stats
    monitor.refresh_from_db()
    monitor.recalculate_uptime()

    logger.info(
        "monitor %s (%s) → %s  %sms",
        monitor.name,
        monitor.url,
        new_status,
        result.get("response_time_ms"),
    )

    # Fire notifications if status changed (skip "pending" as initial state)
    if previous_status != new_status and previous_status != "pending":
        try:
            from apps.monitors.notifications import notify_status_change
            notify_status_change(monitor, previous_status, new_status)
        except Exception:
            logger.exception("notify_status_change failed for monitor %s", monitor_id)
