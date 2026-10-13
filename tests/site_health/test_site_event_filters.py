import pytest
from django.utils import timezone
from django.utils.timezone import timedelta

from apps.site_health.models import SiteEvent
from apps.websites.models import Website


@pytest.fixture
def website(db, team):
    return Website.objects.create(team=team, name="Acme", domain="acme.test")


def make(website, **kw):
    defaults = {
        "website": website,
        "event_type": SiteEvent.EventType.WP_USER_CREATED,
        "summary": "User bob created",
        "category": SiteEvent.Category.USERS,
        "source": SiteEvent.Source.WP_CONNECT,
        "actor": "jdoe",
        "occurred_at": timezone.now(),
    }
    defaults.update(kw)
    return SiteEvent.objects.create(**defaults)


def rows(resp):
    body = resp.data
    return body["results"] if isinstance(body, dict) and "results" in body else body


def test_wp_connect_events_are_now_surfaced(auth_client, website):
    make(website, summary="attributed one")
    resp = auth_client.get(f"/api/v1/websites/{website.id}/events/")
    assert resp.status_code == 200
    assert "attributed one" in [r["summary"] for r in rows(resp)]


def test_filter_by_category(auth_client, website):
    make(website, summary="a user thing", category=SiteEvent.Category.USERS)
    make(website, summary="a plugin thing", category=SiteEvent.Category.PLUGINS)
    resp = auth_client.get(f"/api/v1/websites/{website.id}/events/?category=plugins")
    summaries = [r["summary"] for r in rows(resp)]
    assert summaries == ["a plugin thing"]


def test_filter_by_several_categories(auth_client, website):
    make(website, summary="u", category=SiteEvent.Category.USERS)
    make(website, summary="p", category=SiteEvent.Category.PLUGINS)
    make(website, summary="c", category=SiteEvent.Category.CONTENT)
    resp = auth_client.get(
        f"/api/v1/websites/{website.id}/events/?category=users,plugins"
    )
    assert sorted(r["summary"] for r in rows(resp)) == ["p", "u"]


def test_filter_by_event_type(auth_client, website):
    make(website, summary="created", event_type=SiteEvent.EventType.WP_USER_CREATED)
    make(website, summary="deleted", event_type=SiteEvent.EventType.WP_USER_DELETED)
    resp = auth_client.get(
        f"/api/v1/websites/{website.id}/events/?event_type=wp_user_deleted"
    )
    assert [r["summary"] for r in rows(resp)] == ["deleted"]


def test_filter_by_actor_is_case_insensitive(auth_client, website):
    make(website, summary="by jdoe", actor="jdoe")
    make(website, summary="by alice", actor="alice")
    resp = auth_client.get(f"/api/v1/websites/{website.id}/events/?actor=JDOE")
    assert [r["summary"] for r in rows(resp)] == ["by jdoe"]


def test_filter_by_date_range(auth_client, website):
    make(website, summary="old", occurred_at=timezone.now() - timedelta(days=30))
    make(website, summary="recent", occurred_at=timezone.now() - timedelta(days=1))
    since = (timezone.now() - timedelta(days=7)).date().isoformat()
    resp = auth_client.get(f"/api/v1/websites/{website.id}/events/?since={since}")
    assert [r["summary"] for r in rows(resp)] == ["recent"]


def test_search_matches_summary_substring(auth_client, website):
    make(website, summary="Plugin wp-rocket updated")
    make(website, summary="User bob created")
    resp = auth_client.get(f"/api/v1/websites/{website.id}/events/?q=rocket")
    assert [r["summary"] for r in rows(resp)] == ["Plugin wp-rocket updated"]


def test_unknown_filter_value_returns_empty_not_everything(auth_client, website):
    """A typo must not silently widen the result set to the whole timeline."""
    make(website, summary="a thing")
    resp = auth_client.get(f"/api/v1/websites/{website.id}/events/?category=nonsense")
    assert rows(resp) == []


def test_another_teams_events_are_never_returned(auth_client, website, db):
    from apps.accounts.models import User
    from apps.accounts.services import TeamService

    other_owner = User.objects.create_user(email="other@example.com", password="Xy1!aaaa")
    other_team = TeamService.create(name="Other", owner=other_owner)
    other_site = Website.objects.create(team=other_team, name="Other", domain="other.test")
    make(other_site, summary="not yours")
    make(website, summary="yours")

    resp = auth_client.get(f"/api/v1/websites/{website.id}/events/")
    assert [r["summary"] for r in rows(resp)] == ["yours"]
