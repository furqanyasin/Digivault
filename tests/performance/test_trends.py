"""Phase 2.4 — performance trends + regression detection/alerts."""

import datetime

import pytest
from django.utils import timezone

from apps.alerts.models import Notification
from apps.performance.models import PerformanceReport
from apps.performance.trends import (
    alert_on_regression,
    detect_regression,
    weekly_trend,
)
from apps.websites.models import Website


@pytest.fixture
def perf_website(team):
    return Website.objects.create(team=team, name="Perf", domain="perf.io")


def _report(website, score, days_ago, strategy="mobile"):
    r = PerformanceReport.objects.create(
        website=website, url="https://perf.io", strategy=strategy,
        performance_score=score,
    )
    PerformanceReport.objects.filter(pk=r.pk).update(
        checked_at=timezone.now() - datetime.timedelta(days=days_ago)
    )
    return r


@pytest.mark.django_db
def test_weekly_trend_buckets_by_week(perf_website):
    _report(perf_website, 90, days_ago=10)
    _report(perf_website, 80, days_ago=9)
    _report(perf_website, 70, days_ago=2)
    trend = weekly_trend(perf_website, "mobile", weeks=8)
    assert len(trend) == 2
    assert all("avg_score" in row for row in trend)


@pytest.mark.django_db
def test_detect_regression_flags_drop(perf_website):
    _report(perf_website, 90, days_ago=7)
    _report(perf_website, 70, days_ago=0)  # 20-point drop
    info = detect_regression(perf_website, "mobile", drop_threshold=15)
    assert info is not None
    assert info["drop"] == 20


@pytest.mark.django_db
def test_no_regression_when_stable(perf_website):
    _report(perf_website, 90, days_ago=7)
    _report(perf_website, 88, days_ago=0)
    assert detect_regression(perf_website, "mobile", drop_threshold=15) is None


@pytest.mark.django_db
def test_alert_on_regression_creates_notification(perf_website):
    _report(perf_website, 90, days_ago=7)
    _report(perf_website, 60, days_ago=0)
    notif = alert_on_regression(perf_website, "mobile")
    assert notif is not None
    assert Notification.objects.filter(
        website=perf_website, channel="in_app"
    ).count() == 1


@pytest.mark.django_db
def test_trends_endpoint(auth_client, perf_website):
    _report(perf_website, 90, days_ago=7)
    _report(perf_website, 70, days_ago=0)
    resp = auth_client.get(
        f"/api/v1/websites/{perf_website.id}/performance/trends/",
        {"strategy": "mobile"},
    )
    assert resp.status_code == 200
    assert "weekly" in resp.data
    assert resp.data["regression"]["drop"] == 20
