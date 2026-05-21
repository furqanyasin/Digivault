"""Celery tasks for uptime monitoring."""

import logging

from celery import shared_task
from django.utils import timezone

from apps.monitors.notifications import notify_status_change

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
    max_retries=0,
    name="monitors.check_single_monitor",
)
def check_single_monitor(self, monitor_id: str):
    """Run one health check and apply retry + dedup logic.

    Only fires a down alert after consecutive_failures reaches retry_count.
    Only fires a recovery alert when transitioning from is_alerting=True back to up.
    No duplicate alerts while a monitor stays down.
    """
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

    if new_status == "up":
        should_notify = monitor.is_alerting
        Monitor.objects.filter(pk=monitor.pk).update(
            status=new_status,
            last_checked_at=timezone.now(),
            last_response_time=result.get("response_time_ms"),
            consecutive_failures=0,
            is_alerting=False,
        )
    else:
        new_failures = monitor.consecutive_failures + 1
        fires_alert = new_failures >= monitor.retry_count and not monitor.is_alerting
        should_notify = fires_alert
        Monitor.objects.filter(pk=monitor.pk).update(
            status=new_status,
            last_checked_at=timezone.now(),
            last_response_time=result.get("response_time_ms"),
            consecutive_failures=new_failures,
            is_alerting=monitor.is_alerting or fires_alert,
        )

    monitor.refresh_from_db()
    monitor.recalculate_uptime()

    logger.info(
        "monitor %s (%s) → %s  %sms  failures=%d alerting=%s",
        monitor.name,
        monitor.url,
        new_status,
        result.get("response_time_ms"),
        monitor.consecutive_failures,
        monitor.is_alerting,
    )

    if should_notify and previous_status != "pending":
        try:
            notify_status_change(monitor, previous_status, new_status)
        except Exception:
            logger.exception("notify_status_change failed for monitor %s", monitor_id)
