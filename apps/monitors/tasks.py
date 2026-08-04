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

    # Downtime feeds the website health score, so a state flip has to push the
    # score immediately — otherwise a site can sit at 100 while it is down. Only
    # on a flip, not on every 30-second check, to keep write volume flat.
    if previous_status != new_status and monitor.website_id:
        try:
            monitor.website.recalculate_health_score()
        except Exception:
            logger.exception(
                "health recalc failed for website %s after monitor %s flip",
                monitor.website_id, monitor_id,
            )

    if should_notify and previous_status != "pending":
        try:
            notify_status_change(monitor, previous_status, new_status)
        except Exception:
            logger.exception("notify_status_change failed for monitor %s", monitor_id)


@shared_task(name="monitors.rollup_daily_uptime")
def rollup_daily_uptime(target_date: str | None = None) -> int:
    """Aggregate one day of MonitorCheck rows into MonitorUptimeRollup.

    Idempotent: re-running for the same date upserts the existing rollup.
    `target_date` is an ISO date string (YYYY-MM-DD); defaults to yesterday (UTC).
    Returns the number of monitor rollups written.
    """
    import datetime

    from django.conf import settings
    from django.db.models import Avg, Count, Q

    from apps.monitors.models import MonitorCheck, MonitorUptimeRollup

    if target_date:
        day = datetime.date.fromisoformat(target_date)
    else:
        day = (timezone.now() - datetime.timedelta(days=1)).date()

    naive_start = datetime.datetime.combine(day, datetime.time.min)
    start = timezone.make_aware(naive_start) if settings.USE_TZ else naive_start
    end = start + datetime.timedelta(days=1)

    stats = (
        MonitorCheck.objects.filter(checked_at__gte=start, checked_at__lt=end)
        .values("monitor_id")
        .annotate(
            total=Count("id"),
            up=Count("id", filter=Q(status=MonitorCheck.Status.UP)),
            degraded=Count("id", filter=Q(status=MonitorCheck.Status.DEGRADED)),
            avg_rt=Avg("response_time_ms"),
        )
    )

    written = 0
    for row in stats:
        total = row["total"]
        up = row["up"]
        uptime_pct = round((up / total) * 100, 2) if total else 0.0
        avg_rt = round(row["avg_rt"], 2) if row["avg_rt"] is not None else None
        MonitorUptimeRollup.objects.update_or_create(
            monitor_id=row["monitor_id"],
            date=day,
            defaults={
                "checks_total": total,
                "checks_up": up,
                "checks_degraded": row["degraded"],
                "avg_response_time_ms": avg_rt,
                "uptime_pct": uptime_pct,
            },
        )
        written += 1

    logger.info("monitors.rollup_daily_uptime: %s → %d monitor rollups", day, written)
    return written


@shared_task(name="monitors.purge_old_checks")
def purge_old_checks(days: int = 35) -> int:
    """Delete raw MonitorCheck rows older than `days`. Chunked to avoid long locks.

    Default 35 days keeps a safety margin over the 30-day uptime window so
    recalculate_uptime() still has full raw data; rollups hold older history.
    """
    from apps.monitors.models import MonitorCheck

    cutoff = timezone.now() - timezone.timedelta(days=days)
    total = 0
    chunk = 1000
    while True:
        ids = list(
            MonitorCheck.objects.filter(checked_at__lt=cutoff).values_list(
                "pk", flat=True
            )[:chunk]
        )
        if not ids:
            break
        deleted, _ = MonitorCheck.objects.filter(pk__in=ids).delete()
        total += deleted

    logger.info("monitors.purge_old_checks: removed %d rows older than %dd", total, days)
    return total
