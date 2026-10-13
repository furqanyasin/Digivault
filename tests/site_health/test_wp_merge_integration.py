import hashlib
import hmac
import json
import time

import pytest
from django.utils import timezone

from apps.scripts.tasks import _record_wp_asset_events
from apps.site_health.models import SiteEvent
from apps.websites.models import Website

SECRET = "s" * 32


@pytest.fixture
def website(db, team):
    return Website.objects.create(
        team=team, name="Acme", domain="acme.test", wp_sso_secret=SECRET
    )


def post(client, website, payload):
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))
    sig = hmac.new(SECRET.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return client.post(
        "/api/wp-activity/",
        data=body,
        content_type="application/json",
        HTTP_X_DIGIVAULT_SITE=website.site_id,
        HTTP_X_DIGIVAULT_TIMESTAMP=ts,
        HTTP_X_DIGIVAULT_SIGNATURE=sig,
    )


def _script(url):
    return {"src": url}


def test_passive_component_events_get_a_category(website):
    _record_wp_asset_events(
        website,
        [_script("https://acme.test/wp-content/plugins/wp-rocket/a.js?ver=3.4")],
        [_script("https://acme.test/wp-content/plugins/wp-rocket/a.js?ver=3.5")],
    )
    event = SiteEvent.objects.get(website=website)
    assert event.category == SiteEvent.Category.PLUGINS
    assert event.source == SiteEvent.Source.PASSIVE


def test_attributed_event_upgrades_the_passive_row_rather_than_duplicating(
    api_client, website
):
    _record_wp_asset_events(
        website,
        [_script("https://acme.test/wp-content/plugins/wp-rocket/a.js?ver=3.4")],
        [_script("https://acme.test/wp-content/plugins/wp-rocket/a.js?ver=3.5")],
    )
    assert SiteEvent.objects.filter(website=website).count() == 1

    resp = post(api_client, website, {
        "snippet_version": 2,
        "events": [{
            "seq": 1,
            "type": "plugin_updated",
            "occurred_at": timezone.now().isoformat(),
            "summary": "Plugin wp-rocket updated",
            "actor_login": "jdoe",
            "actor_id": 7,
            "actor_ip": "41.1.2.3",
            "object_type": "plugin",
            "object_id": "wp-rocket",
            "details": {"kind": "plugin", "slug": "wp-rocket", "version": "3.5"},
        }],
    })
    assert resp.status_code == 202

    # One row, not two — and it now carries the actor.
    assert SiteEvent.objects.filter(website=website).count() == 1
    event = SiteEvent.objects.get(website=website)
    assert event.source == SiteEvent.Source.WP_CONNECT
    assert event.actor == "jdoe"
    assert event.actor_ip == "41.1.2.3"


def test_attributed_event_with_no_passive_twin_creates_its_own_row(api_client, website):
    resp = post(api_client, website, {
        "snippet_version": 2,
        "events": [{
            "seq": 1,
            "type": "plugin_activated",
            "occurred_at": timezone.now().isoformat(),
            "summary": "Plugin akismet activated",
            "actor_login": "jdoe",
            "actor_id": 7,
            "actor_ip": "41.1.2.3",
            "object_type": "plugin",
            "object_id": "akismet",
            "details": {"kind": "plugin", "slug": "akismet", "version": ""},
        }],
    })
    assert resp.status_code == 202
    assert resp.data["accepted"] == 1
    event = SiteEvent.objects.get(website=website)
    assert event.source == SiteEvent.Source.WP_CONNECT
    assert event.actor == "jdoe"


def test_non_component_events_never_attempt_a_merge(api_client, website):
    """A user event has no passive counterpart; it must always create its own
    row even if a passive plugin row happens to be sitting there."""
    _record_wp_asset_events(
        website,
        [_script("https://acme.test/wp-content/plugins/wp-rocket/a.js?ver=3.4")],
        [_script("https://acme.test/wp-content/plugins/wp-rocket/a.js?ver=3.5")],
    )
    post(api_client, website, {
        "snippet_version": 2,
        "events": [{
            "seq": 1,
            "type": "user_created",
            "occurred_at": timezone.now().isoformat(),
            "summary": "User bob created",
            "actor_login": "jdoe",
            "actor_id": 7,
            "actor_ip": "41.1.2.3",
            "object_type": "user",
            "object_id": "42",
            "details": {"role": "administrator"},
        }],
    })
    assert SiteEvent.objects.filter(website=website).count() == 2
