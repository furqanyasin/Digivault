"""Cross-cutting Celery tasks (observability / health)."""

import logging
import urllib.request
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db.models import DateTimeField, ExpressionWrapper, F, Q
from django.utils import timezone

logger = logging.getLogger(__name__)

DEFAULT_MONITOR_GRACE_SECONDS = 300

# Messages waiting per queue before the heartbeat treats it as backed up. Sized
# to what each queue normally holds, not to one shared number: ingest swallows
# bursts of thousands and drains them in seconds, while 200 waiting uptime
# checks already means checks are minutes late.
DEFAULT_QUEUE_LIMITS = {"ingest": 5000, "monitors": 200, "slow": 500, "celery": 1000}

# Kombu's Redis transport keeps one list per queue plus one per priority step
# (`<queue>\x06\x16<step>`) when a task is sent with a priority. Counting every
# step means a priority added later does not hide a backlog from this check.
_PRIORITY_SEP = "\x06\x16"
_PRIORITY_STEPS = (3, 6, 9)


def _broker_client():
    import redis

    return redis.Redis.from_url(settings.CELERY_BROKER_URL)


def backed_up_queues() -> dict[str, int]:
    """Queues holding more waiting messages than their limit, with the depth.

    A backlog is the failure every other check reports as healthy: beat is
    scheduling, workers answer pings, Postgres is fine, and ingest is simply
    an hour behind, so a script change surfaces an hour late. Folded into the
    heartbeat rather than given its own alert, so one external check and one
    alert route cover "Stacks Monitor is not keeping up" in every form.
    """
    limits = getattr(settings, "HEARTBEAT_QUEUE_LIMITS", DEFAULT_QUEUE_LIMITS)
    client = _broker_client()
    over = {}
    for queue, limit in limits.items():
        keys = [queue] + [f"{queue}{_PRIORITY_SEP}{step}" for step in _PRIORITY_STEPS]
        depth = sum(client.llen(key) for key in keys)
        if depth > limit:
            over[queue] = depth
    return over


def overdue_monitors():
    """Active monitors more than the grace period past their next due check.

    This is what makes the heartbeat mean "uptime checks are running" rather
    than "some worker is alive". The heartbeat itself runs on the default queue,
    which the *ingest* worker consumes — so on its own it proves beat and that
    worker, and kept pinging happily while the monitors worker was wedged and no
    site had been checked for an hour. run_due_checks runs on the monitors queue
    and claims each monitor by writing last_checked_at at dispatch, so a monitor
    that is long overdue means beat or the monitors worker has stopped.

    Measured against each monitor's own interval, not "a check happened in the
    last N minutes": a fleet on the default 15-minute interval can legitimately
    go ten minutes without a single check.
    """
    from apps.monitors.models import Monitor

    grace = timedelta(
        seconds=getattr(
            settings, "HEARTBEAT_MONITOR_GRACE_SECONDS", DEFAULT_MONITOR_GRACE_SECONDS
        )
    )
    cutoff = timezone.now() - grace
    due_at = ExpressionWrapper(
        F("last_checked_at") + timedelta(seconds=1) * F("check_interval"),
        output_field=DateTimeField(),
    )
    return (
        Monitor.objects.filter(is_active=True)
        .exclude(status=Monitor.Status.PAUSED)
        .annotate(due_at=due_at)
        .filter(
            # Never checked: only overdue once it has existed past the grace,
            # so a monitor created a minute ago does not trip the switch.
            Q(last_checked_at__isnull=True, created_at__lt=cutoff)
            | Q(due_at__lt=cutoff)
        )
    )


@shared_task(name="common.maintain_partitions")
def maintain_partitions() -> dict:
    """Keep three months of partitions ahead of every converted table.

    A no-op for tables that have not been converted (apps/common/partitions.py).
    Rows only reach a table's DEFAULT partition when this has not run for
    months; that is logged as an error, because a month cannot be created over
    rows already sitting in DEFAULT until they are moved.
    """
    from apps.common import partitions

    created = {}
    for table in partitions.PARTITIONED_TABLES:
        made = partitions.ensure_future_partitions(table)
        if made:
            created[table] = made
        stray = partitions.default_partition_rows(table)
        if stray:
            logger.error(
                "maintain_partitions: %d rows in %s_default — partitions fell "
                "behind; see docs/runbooks/capacity-checks.md", stray, table,
            )
    return created


@shared_task(name="common.system_heartbeat")
def system_heartbeat() -> bool:
    """Dead-man's-switch: ping an external uptime check so a stalled Celery
    beat/worker is itself detected.

    Set ``HEARTBEAT_PING_URL`` to a healthchecks.io / cronitor / Better Uptime
    heartbeat URL. If beat stops scheduling this task (or workers stall), the
    external service stops receiving pings and alerts. The ping is also withheld
    while any monitor is overdue (see ``overdue_monitors``), so a stopped
    monitors worker pages someone too, and while any queue is backed up (see
    ``backed_up_queues``). Returns True on success.
    """
    url = getattr(settings, "HEARTBEAT_PING_URL", "")
    if not url:
        return False

    # Deliberately not wrapped: a database that cannot answer this query is a
    # reason to withhold the ping, and letting it raise does exactly that.
    overdue = overdue_monitors()
    count = overdue.count()
    if count:
        oldest = overdue.order_by(F("last_checked_at").asc(nulls_first=True)).first()
        logger.error(
            "system_heartbeat: withholding ping — %d monitor(s) overdue, oldest "
            "%s (last checked %s). Beat or the monitors worker has stopped.",
            count,
            oldest.name if oldest else "?",
            oldest.last_checked_at if oldest else "?",
        )
        return False

    # Also unwrapped: a broker that cannot answer LLEN is not keeping up either.
    backlog = backed_up_queues()
    if backlog:
        logger.error(
            "system_heartbeat: withholding ping — queue backlog %s. Workers are "
            "running but not keeping up.",
            ", ".join(f"{q}={n}" for q, n in sorted(backlog.items())),
        )
        return False

    try:
        urllib.request.urlopen(url, timeout=10)
        return True
    except Exception:
        logger.warning("system_heartbeat: ping to %s failed", url)
        return False
