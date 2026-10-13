import pytest
from django.utils import timezone

from apps.site_health.models import FileManifest, SiteEvent
from apps.websites.models import Website


@pytest.fixture
def website(db, team):
    return Website.objects.create(team=team, name="Acme", domain="acme.test")


def test_site_event_defaults_to_passive_source(website):
    event = SiteEvent.objects.create(
        website=website,
        event_type=SiteEvent.EventType.PAGE_DISCOVERED,
        summary="new page",
    )
    assert event.source == SiteEvent.Source.PASSIVE
    assert event.category == ""
    assert event.actor_ip is None
    assert event.actor_wp_id is None
    assert event.sequence is None


def test_site_event_accepts_wp_connect_attribution(website):
    event = SiteEvent.objects.create(
        website=website,
        event_type=SiteEvent.EventType.WP_PLUGIN_UPDATED,
        summary="wp-rocket updated",
        source=SiteEvent.Source.WP_CONNECT,
        category=SiteEvent.Category.PLUGINS,
        actor="jdoe",
        actor_wp_id=7,
        actor_ip="41.1.2.3",
        object_type="plugin",
        object_id="wp-rocket",
        sequence=1042,
    )
    event.refresh_from_db()
    assert event.source == SiteEvent.Source.WP_CONNECT
    assert event.actor_ip == "41.1.2.3"
    assert event.sequence == 1042


def test_file_manifest_is_one_per_website_walk(website):
    FileManifest.objects.create(
        website=website,
        walk_id="w1",
        entries={"a.php": "abc"},
        is_complete=True,
        walked_at=timezone.now(),
    )
    assert FileManifest.objects.filter(website=website).count() == 1


def test_website_wp_connect_defaults(website):
    assert website.wp_connect_version == 0
    assert website.wp_connect_last_ack is None
    assert website.wp_connect_last_seq == 0
