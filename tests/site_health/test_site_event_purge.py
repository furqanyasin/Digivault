import pytest
from django.utils import timezone
from django.utils.timezone import timedelta

from apps.site_health.models import SiteEvent
from apps.site_health.tasks import purge_old_site_events
from apps.websites.models import Website


@pytest.fixture
def website(db, team):
    return Website.objects.create(team=team, name="Acme", domain="acme.test")


def make(website, category, age_days):
    return SiteEvent.objects.create(
        website=website,
        event_type=SiteEvent.EventType.WP_USER_CREATED,
        summary="x",
        category=category,
        occurred_at=timezone.now() - timedelta(days=age_days),
    )


def test_security_events_survive_to_365_days(website):
    keep = make(website, SiteEvent.Category.USERS, 300)
    purge_old_site_events()
    assert SiteEvent.objects.filter(pk=keep.pk).exists()


def test_security_events_purged_past_365_days(website):
    old = make(website, SiteEvent.Category.USERS, 400)
    purge_old_site_events()
    assert not SiteEvent.objects.filter(pk=old.pk).exists()


def test_content_events_purged_past_90_days(website):
    old = make(website, SiteEvent.Category.CONTENT, 100)
    purge_old_site_events()
    assert not SiteEvent.objects.filter(pk=old.pk).exists()


def test_content_events_survive_to_90_days(website):
    keep = make(website, SiteEvent.Category.CONTENT, 30)
    purge_old_site_events()
    assert SiteEvent.objects.filter(pk=keep.pk).exists()


def test_uncategorised_legacy_events_use_default_tier(website):
    keep = make(website, "", 30)
    old = make(website, "", 100)
    purge_old_site_events()
    assert SiteEvent.objects.filter(pk=keep.pk).exists()
    assert not SiteEvent.objects.filter(pk=old.pk).exists()


def test_returns_number_deleted(website):
    make(website, SiteEvent.Category.CONTENT, 100)
    make(website, SiteEvent.Category.CONTENT, 100)
    assert purge_old_site_events() == 2
