"""Re-record SiteGround's 202 challenge as `blocked`, not `degraded`.

`identify_block` used to refuse every 2xx, so SiteGround's anti-bot — which
answers an unrecognised client with a 202 challenge page instead of the site —
was recorded as "degraded: Got 202, expected 200". Degraded counts against
uptime, so eight client sites on SiteGround read 0.00% uptime for 24h, 7d and
30d while serving every visitor normally.

A 202 from a monitored page is a challenge interstitial in practice, and the
checks being rewritten are exactly the ones carrying the old "Got 202" message.
`blocked` is excluded from both sides of the uptime ratio, so the history stops
reading as an outage it never was. Monitors whose latest check was one of these
move to `blocked` too, rather than waiting for their next check.

Their daily rollups and cached uptime figures are recomputed from the
corrected rows, with the same rule as rollup_daily_uptime and
Monitor.recalculate_uptime.

Reversing is a no-op: the old rows described a firewall as a degraded site.
"""
from django.db import migrations

_OLD_MESSAGE = "Got 202, expected"
_NEW_MESSAGE = (
    "Blocked by SiteGround (HTTP 202) — we received the firewall's page, not "
    "the site's, so this is not an outage. (Re-recorded from an earlier check.)"
)


def forwards(apps, schema_editor):
    Monitor = apps.get_model("monitors", "Monitor")
    MonitorCheck = apps.get_model("monitors", "MonitorCheck")

    stale = MonitorCheck.objects.filter(
        status="degraded", status_code=202, error_message__startswith=_OLD_MESSAGE
    )
    affected = set(stale.values_list("monitor_id", flat=True).distinct())
    rewritten = stale.update(status="blocked", error_message=_NEW_MESSAGE)

    # The daily rollups were computed from the old rows. Recompute them the way
    # rollup_daily_uptime does (blocked excluded), and drop a day that was
    # nothing but blocks — no observation of the site, so no uptime figure.
    # Only for days whose checks still exist: after purge_old_checks the rollup
    # is the sole record and there is nothing to recompute it from.
    _recompute_rollups(apps, affected)
    _recompute_cached_uptime(apps, affected)

    moved = 0
    for monitor in Monitor.objects.filter(status="degraded"):
        latest = monitor.checks.order_by("-checked_at").first()
        if latest is not None and latest.status == "blocked" and latest.status_code == 202:
            Monitor.objects.filter(pk=monitor.pk).update(status="blocked")
            moved += 1
    if rewritten or moved:
        print(f"  re-recorded {rewritten} checks and {moved} monitors as blocked")


def _recompute_cached_uptime(apps, monitor_ids):
    """Monitor.recalculate_uptime, which a historical model does not carry."""
    from django.utils import timezone

    Monitor = apps.get_model("monitors", "Monitor")
    MonitorCheck = apps.get_model("monitors", "MonitorCheck")
    now = timezone.now()
    windows = {
        "uptime_24h": now - timezone.timedelta(hours=24),
        "uptime_7d": now - timezone.timedelta(days=7),
        "uptime_30d": now - timezone.timedelta(days=30),
    }
    for monitor_id in monitor_ids:
        values = {}
        for field, since in windows.items():
            observable = MonitorCheck.objects.filter(
                monitor_id=monitor_id, checked_at__gte=since
            ).exclude(status="blocked")
            total = observable.count()
            up = observable.filter(status="up").count()
            values[field] = round(up / total * 100, 2) if total else None
        Monitor.objects.filter(pk=monitor_id).update(**values)


def _recompute_rollups(apps, monitor_ids):
    import datetime

    from django.db.models import Avg, Count, Q
    from django.utils import timezone

    MonitorCheck = apps.get_model("monitors", "MonitorCheck")
    Rollup = apps.get_model("monitors", "MonitorUptimeRollup")

    for rollup in Rollup.objects.filter(monitor_id__in=monitor_ids):
        start = timezone.make_aware(datetime.datetime.combine(rollup.date, datetime.time.min))
        day = MonitorCheck.objects.filter(
            monitor_id=rollup.monitor_id,
            checked_at__gte=start,
            checked_at__lt=start + datetime.timedelta(days=1),
        )
        if not day.exists():
            continue
        stats = day.exclude(status="blocked").aggregate(
            total=Count("id"),
            up=Count("id", filter=Q(status="up")),
            degraded=Count("id", filter=Q(status="degraded")),
            avg_rt=Avg("response_time_ms"),
        )
        if not stats["total"]:
            rollup.delete()
            continue
        rollup.checks_total = stats["total"]
        rollup.checks_up = stats["up"]
        rollup.checks_degraded = stats["degraded"]
        rollup.avg_response_time_ms = (
            round(stats["avg_rt"], 2) if stats["avg_rt"] is not None else None
        )
        rollup.uptime_pct = round(stats["up"] / stats["total"] * 100, 2)
        rollup.save()


class Migration(migrations.Migration):

    dependencies = [
        ("monitors", "0011_monitor_consecutive_blocks_alter_monitor_status_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
