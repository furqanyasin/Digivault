"""Performance trend aggregation + regression detection (Phase 2.4)."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)


def weekly_trend(website, strategy: str = "mobile", weeks: int = 8) -> list[dict]:
    """Average performance score per ISO week (Monday-anchored) over `weeks`."""
    from apps.performance.models import PerformanceReport

    cutoff = timezone.now() - timedelta(weeks=weeks)
    reports = PerformanceReport.objects.filter(
        website=website,
        strategy=strategy,
        performance_score__isnull=False,
        checked_at__gte=cutoff,
    ).order_by("checked_at")

    buckets: dict = {}
    for r in reports:
        d = r.checked_at.date()
        week_start = d - timedelta(days=d.weekday())
        buckets.setdefault(week_start, []).append(r.performance_score)

    return [
        {
            "week_start": wk.isoformat(),
            "avg_score": round(sum(scores) / len(scores), 1),
            "count": len(scores),
        }
        for wk, scores in sorted(buckets.items())
    ]


def detect_regression(website, strategy: str = "mobile", drop_threshold: int = 15):
    """Compare the two most recent reports; return regression info if score
    dropped by >= drop_threshold, else None."""
    from apps.performance.models import PerformanceReport

    latest_two = list(
        PerformanceReport.objects.filter(
            website=website, strategy=strategy, performance_score__isnull=False
        ).order_by("-checked_at")[:2]
    )
    if len(latest_two) < 2:
        return None
    latest, previous = latest_two[0], latest_two[1]
    drop = previous.performance_score - latest.performance_score
    if drop >= drop_threshold:
        return {
            "strategy": strategy,
            "previous": previous.performance_score,
            "current": latest.performance_score,
            "drop": drop,
        }
    return None


def alert_on_regression(website, strategy: str = "mobile", drop_threshold: int = 15):
    """Create an in-app Notification if a regression is detected. Returns it or None."""
    info = detect_regression(website, strategy, drop_threshold)
    if not info:
        return None

    from apps.alerts.models import AlertRule, Notification

    logger.warning(
        "Performance regression for %s (%s): %s → %s (-%s)",
        website.domain, strategy, info["previous"], info["current"], info["drop"],
    )
    return Notification.objects.create(
        team=website.team,
        website=website,
        channel=AlertRule.Channel.IN_APP,
    )
