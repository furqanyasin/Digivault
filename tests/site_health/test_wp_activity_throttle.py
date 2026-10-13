import hashlib
import hmac
import json
import time

import pytest
from django.core.cache import cache

from apps.site_health.views import WpActivityIngestView, WpActivityThrottle
from apps.websites.models import Website

SECRET = "s" * 32


@pytest.fixture
def website(db, team):
    return Website.objects.create(
        team=team, name="Acme", domain="acme.test", wp_sso_secret=SECRET
    )


@pytest.fixture(autouse=True)
def clear_throttle_cache():
    cache.clear()
    yield
    cache.clear()


def post(client, website, payload, site_header=None):
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))
    sig = hmac.new(SECRET.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return client.post(
        "/api/wp-activity/",
        data=body,
        content_type="application/json",
        HTTP_X_DIGIVAULT_SITE=site_header or website.site_id,
        HTTP_X_DIGIVAULT_TIMESTAMP=ts,
        HTTP_X_DIGIVAULT_SIGNATURE=sig,
    )


def _drf_request(**headers):
    """A DRF Request — AnonRateThrottle reads request.user, which a bare
    WSGIRequest from RequestFactory does not have."""
    from django.contrib.auth.models import AnonymousUser
    from rest_framework.request import Request
    from rest_framework.test import APIRequestFactory

    raw = APIRequestFactory().post("/api/wp-activity/", **headers)
    request = Request(raw)
    request.user = AnonymousUser()
    return request


def test_throttle_is_keyed_on_the_site_header_not_the_ip(website):
    """One noisy site must not spend another site's budget. Every client posts
    from its own server, but they can share a host, a CDN egress or a NAT."""
    throttle = WpActivityThrottle()
    key_one = throttle.get_cache_key(
        _drf_request(HTTP_X_DIGIVAULT_SITE="site-one"), WpActivityIngestView()
    )
    key_two = throttle.get_cache_key(
        _drf_request(HTTP_X_DIGIVAULT_SITE="site-two"), WpActivityIngestView()
    )
    assert key_one != key_two
    assert "site-one" in key_one


def test_throttle_falls_back_to_ip_when_the_header_is_missing():
    throttle = WpActivityThrottle()
    key = throttle.get_cache_key(_drf_request(), WpActivityIngestView())
    assert key is not None


def test_a_normal_batch_is_not_throttled(api_client, website):
    resp = post(api_client, website, {"snippet_version": 2, "events": []})
    assert resp.status_code == 202


def test_oversized_batch_is_rejected_before_parsing(api_client, website):
    """A single event is capped so a runaway site cannot post a 200k-row batch
    that ties up a worker before the serializer ever sees it."""
    too_many = [
        {
            "seq": i,
            "type": "post_updated",
            "occurred_at": "2026-09-01T10:00:00Z",
            "summary": "x",
        }
        for i in range(WpActivityIngestView.MAX_EVENTS_PER_BATCH + 1)
    ]
    resp = post(api_client, website, {"snippet_version": 2, "events": too_many})
    assert resp.status_code == 400
