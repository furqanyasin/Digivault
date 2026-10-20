import hashlib
import hmac
import json
import time

import pytest

from apps.site_health.models import FileManifest, SiteEvent
from apps.websites.models import Website

SECRET = "s" * 32


@pytest.fixture
def website(db, team):
    return Website.objects.create(
        team=team, name="Acme", domain="acme.test", wp_sso_secret=SECRET
    )


def post(client, website, payload, secret=SECRET, timestamp=None):
    body = json.dumps(payload).encode()
    ts = timestamp or str(int(time.time()))
    sig = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return client.post(
        "/api/wp-activity/",
        data=body,
        content_type="application/json",
        HTTP_X_STACKSMONITOR_SITE=website.site_id,
        HTTP_X_STACKSMONITOR_TIMESTAMP=ts,
        HTTP_X_STACKSMONITOR_SIGNATURE=sig,
    )


def _event(seq, wp_type="user_created", **kw):
    base = {
        "seq": seq,
        "type": wp_type,
        "occurred_at": "2026-09-01T10:00:00Z",
        "summary": "admin user bob created",
        "actor_login": "jdoe",
        "actor_id": 7,
        "actor_ip": "41.1.2.3",
        "object_type": "user",
        "object_id": "42",
        "details": {"role": "administrator"},
    }
    base.update(kw)
    return base


def test_valid_batch_creates_attributed_site_events(api_client, website):
    resp = post(api_client, website, {"snippet_version": 2, "events": [_event(1)]})
    assert resp.status_code == 202
    assert resp.data["accepted"] == 1
    assert resp.data["resend_from"] is None

    event = SiteEvent.objects.get(website=website)
    assert event.source == SiteEvent.Source.WP_CONNECT
    assert event.category == SiteEvent.Category.USERS
    assert event.actor == "jdoe"
    assert event.actor_wp_id == 7
    assert event.actor_ip == "41.1.2.3"
    assert event.sequence == 1


def test_bad_signature_rejected(api_client, website):
    resp = post(
        api_client, website, {"snippet_version": 2, "events": [_event(1)]}, secret="wrong"
    )
    assert resp.status_code == 403
    assert SiteEvent.objects.count() == 0


def test_stale_timestamp_rejected(api_client, website):
    stale = str(int(time.time()) - 400)
    resp = post(
        api_client, website, {"snippet_version": 2, "events": [_event(1)]}, timestamp=stale
    )
    assert resp.status_code == 403


def test_unknown_site_id_returns_404(api_client, website):
    website.site_id = "nope"
    resp = post(api_client, website, {"snippet_version": 2, "events": []})
    assert resp.status_code == 404


def test_site_without_secret_rejected(api_client, website):
    website.wp_sso_secret = ""
    website.save(update_fields=["wp_sso_secret"])
    resp = post(
        api_client, website, {"snippet_version": 2, "events": [_event(1)]}, secret=""
    )
    assert resp.status_code == 403


def test_sequence_gap_requests_resend(api_client, website):
    website.wp_connect_last_seq = 10
    website.save(update_fields=["wp_connect_last_seq"])
    resp = post(api_client, website, {"snippet_version": 2, "events": [_event(15)]})
    assert resp.status_code == 202
    assert resp.data["resend_from"] == 11


def test_replayed_batch_does_not_duplicate(api_client, website):
    payload = {"snippet_version": 2, "events": [_event(1)]}
    post(api_client, website, payload)
    post(api_client, website, payload)
    assert SiteEvent.objects.filter(website=website).count() == 1


def test_unknown_event_type_skipped_batch_still_accepted(api_client, website):
    resp = post(
        api_client,
        website,
        {
            "snippet_version": 2,
            "events": [_event(1, wp_type="from_the_future"), _event(2)],
        },
    )
    assert resp.status_code == 202
    assert resp.data["accepted"] == 1
    assert SiteEvent.objects.count() == 1


def test_skipped_trailing_event_still_advances_the_offset(api_client, website):
    # The snippet deletes every row it sent. If an unmapped trailing row did not
    # advance last_seq, the next batch would read as a gap forever.
    post(
        api_client,
        website,
        {"snippet_version": 2, "events": [_event(1), _event(2, wp_type="from_the_future")]},
    )
    website.refresh_from_db()
    assert website.wp_connect_last_seq == 2


def test_accepting_a_batch_records_snippet_version_and_ack(api_client, website):
    post(api_client, website, {"snippet_version": 2, "events": [_event(3)]})
    website.refresh_from_db()
    assert website.wp_connect_version == 2
    assert website.wp_connect_last_ack is not None
    assert website.wp_connect_last_seq == 3


def test_manifest_slice_stored_incomplete(api_client, website):
    post(
        api_client,
        website,
        {
            "snippet_version": 2,
            "events": [],
            "manifest": {"walk_id": "w1", "entries": {"a.php": "h1"}, "complete": False},
        },
    )
    manifest = FileManifest.objects.get(website=website, walk_id="w1")
    assert manifest.is_complete is False
    assert manifest.entries == {"a.php": "h1"}


def test_manifest_slices_accumulate_and_complete(api_client, website):
    post(
        api_client,
        website,
        {
            "snippet_version": 2,
            "events": [],
            "manifest": {"walk_id": "w1", "entries": {"a.php": "h1"}, "complete": False},
        },
    )
    post(
        api_client,
        website,
        {
            "snippet_version": 2,
            "events": [],
            "manifest": {"walk_id": "w1", "entries": {"b.php": "h2"}, "complete": True},
        },
    )
    manifest = FileManifest.objects.get(website=website, walk_id="w1")
    assert manifest.entries == {"a.php": "h1", "b.php": "h2"}
    assert manifest.is_complete is True
    assert manifest.walked_at is not None


def test_heartbeat_records_the_sites_own_homepage_check(api_client, website):
    resp = post(api_client, website, {
        "snippet_version": 2, "events": [],
        "heartbeat": {"loopback_status": 200, "loopback_ms": 340},
    })
    assert resp.status_code == 202
    website.refresh_from_db()
    assert website.wp_connect_loopback_status == 200
    assert website.wp_connect_loopback_ms == 340
    assert website.wp_connect_loopback_at == website.wp_connect_last_ack


def test_failed_loopback_clears_the_previous_answer(api_client, website):
    post(api_client, website, {"snippet_version": 2, "heartbeat": {"loopback_status": 200, "loopback_ms": 300}})
    post(api_client, website, {"snippet_version": 2, "heartbeat": {"loopback_status": None, "loopback_ms": None}})
    website.refresh_from_db()
    # A stale 200 must not keep vouching for a site whose loopback now fails.
    assert website.wp_connect_loopback_status is None
    assert website.wp_connect_loopback_at is not None


def test_batch_without_heartbeat_leaves_loopback_alone(api_client, website):
    post(api_client, website, {"snippet_version": 2, "heartbeat": {"loopback_status": 200, "loopback_ms": 300}})
    post(api_client, website, {"snippet_version": 2, "events": [_event(1)]})
    website.refresh_from_db()
    assert website.wp_connect_loopback_status == 200
