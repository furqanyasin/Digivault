import pytest
from django.utils import timezone
from django.utils.timezone import timedelta

from apps.websites.models import Website
from apps.websites.serializers import WebsiteSerializer


@pytest.fixture
def website(db, team):
    return Website.objects.create(team=team, name="Acme", domain="acme.test")


def test_absent_when_never_reported(website):
    assert WebsiteSerializer(website).data["wp_connect_status"] == "absent"


def test_current_when_latest_version_and_recent_ack(website):
    website.wp_connect_version = 2
    website.wp_connect_last_ack = timezone.now()
    website.wp_connect_loopback_at = timezone.now()
    assert WebsiteSerializer(website).data["wp_connect_status"] == "current"


def test_outdated_when_older_snippet_version(website):
    website.wp_connect_version = 1
    website.wp_connect_last_ack = timezone.now()
    assert WebsiteSerializer(website).data["wp_connect_status"] == "outdated"


def test_stale_when_ack_older_than_the_dead_man_window(website):
    website.wp_connect_version = 2
    website.wp_connect_last_ack = timezone.now() - timedelta(days=8)
    assert WebsiteSerializer(website).data["wp_connect_status"] == "stale"


def test_v2_without_a_heartbeat_is_outdated(website):
    # Pasted before the uptime heartbeat: same version number, but it cannot
    # vouch for the site when a firewall blocks our monitor. Re-paste it.
    website.wp_connect_version = 2
    website.wp_connect_last_ack = timezone.now()
    assert WebsiteSerializer(website).data["wp_connect_status"] == "outdated"
