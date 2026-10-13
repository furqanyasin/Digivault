import pytest
from django.utils import timezone
from django.utils.timezone import timedelta

from apps.monitors.models import Monitor, MonitorCheck
from apps.site_health.models import PhpError, SiteEvent
from apps.websites.models import Website

INCIDENT = "2026-09-01T14:32:00Z"


@pytest.fixture
def website(db, team):
    return Website.objects.create(team=team, name="Acme", domain="acme.test")


@pytest.fixture
def at():
    from django.utils.dateparse import parse_datetime

    return parse_datetime(INCIDENT)


def url(website, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"/api/v1/websites/{website.id}/timeline/?{query}"


def test_returns_events_around_the_incident(auth_client, website, at):
    SiteEvent.objects.create(
        website=website,
        event_type=SiteEvent.EventType.WP_PLUGIN_UPDATED,
        summary="Plugin wp-rocket updated",
        actor="jdoe",
        actor_ip="41.1.2.3",
        category=SiteEvent.Category.PLUGINS,
        occurred_at=at - timedelta(minutes=1),
    )
    resp = auth_client.get(url(website, around=INCIDENT, window="30m"))
    assert resp.status_code == 200
    kinds = [row["kind"] for row in resp.data["entries"]]
    assert "site_event" in kinds
    entry = next(r for r in resp.data["entries"] if r["kind"] == "site_event")
    assert entry["actor"] == "jdoe"
    assert entry["actor_ip"] == "41.1.2.3"


def test_excludes_anything_outside_the_window(auth_client, website, at):
    SiteEvent.objects.create(
        website=website,
        event_type=SiteEvent.EventType.WP_PLUGIN_UPDATED,
        summary="way earlier",
        occurred_at=at - timedelta(hours=5),
    )
    resp = auth_client.get(url(website, around=INCIDENT, window="30m"))
    assert resp.data["entries"] == []


def test_php_errors_appear_on_the_timeline(auth_client, website, at):
    error = PhpError.objects.create(
        website=website, level="fatal", message="Call to undefined function"
    )
    PhpError.objects.filter(pk=error.pk).update(captured_at=at - timedelta(seconds=20))
    resp = auth_client.get(url(website, around=INCIDENT, window="30m"))
    kinds = [r["kind"] for r in resp.data["entries"]]
    assert "php_error" in kinds


def test_down_checks_appear_but_up_checks_do_not(auth_client, website, at):
    monitor = Monitor.objects.filter(website=website).first() or Monitor.objects.create(
        website=website, name="m", check_type="http", target=website.domain
    )
    # checked_at is auto_now_add, so it has to be set after the insert.
    down = MonitorCheck.objects.create(monitor=monitor, status="down")
    MonitorCheck.objects.filter(pk=down.pk).update(checked_at=at)
    up = MonitorCheck.objects.create(monitor=monitor, status="up")
    MonitorCheck.objects.filter(pk=up.pk).update(checked_at=at - timedelta(minutes=2))
    resp = auth_client.get(url(website, around=INCIDENT, window="30m"))
    statuses = [r.get("status") for r in resp.data["entries"] if r["kind"] == "monitor_check"]
    assert "down" in statuses
    assert "up" not in statuses


def test_entries_are_ordered_newest_first(auth_client, website, at):
    SiteEvent.objects.create(
        website=website,
        event_type=SiteEvent.EventType.WP_PLUGIN_UPDATED,
        summary="older",
        occurred_at=at - timedelta(minutes=10),
    )
    SiteEvent.objects.create(
        website=website,
        event_type=SiteEvent.EventType.WP_USER_CREATED,
        summary="newer",
        occurred_at=at - timedelta(minutes=1),
    )
    resp = auth_client.get(url(website, around=INCIDENT, window="30m"))
    summaries = [r["title"] for r in resp.data["entries"]]
    assert summaries.index("newer") < summaries.index("older")


def test_defaults_to_now_when_no_anchor_is_given(auth_client, website):
    SiteEvent.objects.create(
        website=website,
        event_type=SiteEvent.EventType.WP_USER_CREATED,
        summary="just happened",
        occurred_at=timezone.now(),
    )
    resp = auth_client.get(f"/api/v1/websites/{website.id}/timeline/")
    assert resp.status_code == 200
    assert "just happened" in [r["title"] for r in resp.data["entries"]]


def test_window_is_capped_so_one_request_cannot_scan_a_year(auth_client, website):
    resp = auth_client.get(url(website, around=INCIDENT, window="9999h"))
    assert resp.status_code == 200
    assert resp.data["window_minutes"] <= 1440


def test_another_teams_website_is_not_reachable(auth_client, db, team):
    from apps.accounts.models import User
    from apps.accounts.services import TeamService

    other_owner = User.objects.create_user(email="other2@example.com", password="Xy1!aaaa")
    other_team = TeamService.create(name="Other", owner=other_owner)
    other_site = Website.objects.create(team=other_team, name="O", domain="other2.test")
    resp = auth_client.get(f"/api/v1/websites/{other_site.id}/timeline/")
    assert resp.status_code == 404
