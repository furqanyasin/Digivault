"""Batched ingest must say exactly what unbatched ingest says, just once.

`INGEST_BATCH_SITES` collects a page's posts in Redis and diffs them in one
pass (apps/scripts/ingest_batch.py). The danger in that is not the batching,
it is what a batch could quietly change: posts landing in the wrong 60s load
bucket because they were stamped with the flush time, a script's
`last_seen_at` moving to when we *processed* it rather than when it was
*seen* (which can hide a removal for good), or a crash losing the only copy
of a burst of observations. Each of those is pinned here.
"""

import fnmatch
from datetime import timedelta
from unittest.mock import patch

import pytest
from celery.exceptions import Retry
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts import ingest_batch
from apps.scripts.models import DetectedForm, Script, ScriptChange, ScriptSnapshot
from apps.scripts.tasks import (
    Observation,
    _ingest_observations,
    _opens_a_load,
    process_ingest_payload,
)
from apps.websites.models import Website

pytestmark = pytest.mark.django_db


# ── A Redis stand-in: the handful of commands ingest_batch uses ───────────


class FakeRedis:
    def __init__(self):
        self.lists: dict[str, list[bytes]] = {}
        self.strings: dict[str, bytes] = {}

    def _all(self):
        return {**self.lists, **self.strings}

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value.encode() if isinstance(value, str) else value)
        return len(self.lists[key])

    def expire(self, key, seconds):
        return key in self._all()

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self._all():
            return None
        self.strings[key] = value.encode() if isinstance(value, str) else value
        return True

    def exists(self, key):
        return int(key in self._all())

    def delete(self, *keys):
        n = 0
        for key in keys:
            n += int(self.lists.pop(key, None) is not None)
            n += int(self.strings.pop(key, None) is not None)
        return n

    def rename(self, src, dst):
        if src not in self.lists:
            raise Exception("ERR no such key")  # redis.ResponseError in production
        self.lists[dst] = self.lists.pop(src)
        return True

    def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        return items[start:] if end == -1 else items[start : end + 1]

    def scan_iter(self, match="*", count=None):
        return [k.encode() for k in list(self._all()) if fnmatch.fnmatch(k, match)]

    def pipeline(self):
        return _Pipeline(self)


class _Pipeline:
    def __init__(self, redis):
        self.redis, self.calls = redis, []

    def __getattr__(self, name):
        def queue(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self
        return queue

    def execute(self):
        return [getattr(self.redis, name)(*a, **kw) for name, a, kw in self.calls]


@pytest.fixture
def redis():
    fake = FakeRedis()
    with patch("apps.scripts.ingest_batch._redis", return_value=fake):
        yield fake


# ── Fixtures and payloads ──────────────────────────────────────────────────


@pytest.fixture
def team(db):
    owner = User.objects.create_user(email="batch_o@test.com", password="Pass123!")
    return TeamService.create(name="Batch Agency", owner=owner)


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="Batch Site", domain="batch.io")


@pytest.fixture
def twin(team):
    """A second site, fed the same posts one at a time, for comparison."""
    return Website.objects.create(team=team, name="Twin Site", domain="twin.io")


def _script(src):
    return {
        "src": src, "location": "head", "is_async": True, "is_defer": False,
        "is_inline": False, "inline_hash": "", "wp_plugin": "", "wp_post_id": None,
    }


GTM = "https://www.googletagmanager.com/gtm.js?id=GTM-BATCH"
GA4 = "https://www.googletagmanager.com/gtag/js?id=G-BATCH"
HOTJAR = "https://static.hotjar.com/c/hotjar-1122334.js?sv=6"
HUBSPOT = "https://js.hs-scripts.com/1122334.js"

FORM = {
    "form_id": "contact", "form_name": "Contact", "form_action": "",
    "form_method": "post", "detection_type": "native", "provider": "",
    "recipient_email": "", "recipients": {}, "fields": [{"name": "email", "type": "email"}],
}


def _payload(domain, scripts, page="/"):
    return {
        "page_url": f"https://{domain}{page}",
        "scripts": [_script(s) for s in scripts],
        "forms": [FORM],
        "user_agent": "Mozilla/5.0",
        "snippet_version": "1.14",
    }


# One page load as the snippet really reports it: GTM first, then the tags it
# injects arriving across later posts.
LOAD = [[GTM], [GTM, GA4], [GTM, GA4, HOTJAR, HUBSPOT]]


def _changes(site):
    return sorted(
        (c.change_type, c.script.normalized_url if c.script else c.description)
        for c in ScriptChange.objects.filter(website=site)
    )


# ── Same answer as the unbatched path ──────────────────────────────────────


def test_a_batch_records_what_the_same_posts_record_one_at_a_time(website, twin):
    start = timezone.now() - timedelta(seconds=5)
    _ingest_observations(website, [
        Observation(_payload("batch.io", scripts), start + timedelta(seconds=i))
        for i, scripts in enumerate(LOAD)
    ])
    for scripts in LOAD:
        process_ingest_payload(site_id=twin.site_id, payload=_payload("twin.io", scripts))

    assert set(Script.objects.filter(website=website).values_list("normalized_url", flat=True)) == \
        set(Script.objects.filter(website=twin).values_list("normalized_url", flat=True))
    assert _changes(website) == _changes(twin)
    assert ScriptSnapshot.objects.filter(website=website).count() == len(LOAD)
    assert DetectedForm.objects.filter(website=website).count() == \
        DetectedForm.objects.filter(website=twin).count() == 1


def test_each_post_keeps_its_arrival_time(website):
    # Stamped with the flush time, posts would land in the wrong 60s bucket.
    start = timezone.now() - timedelta(seconds=40)
    arrivals = [start, start + timedelta(seconds=3), start + timedelta(seconds=25)]
    _ingest_observations(website, [
        Observation(_payload("batch.io", scripts), at) for scripts, at in zip(LOAD, arrivals)
    ])
    stored = sorted(ScriptSnapshot.objects.filter(website=website).values_list("captured_at", flat=True))
    assert stored == arrivals


def test_a_script_is_last_seen_when_it_was_seen_not_when_it_was_processed(website):
    # Hotjar was in the first post only. Stamped with the flush time, a tag
    # removed just after would read as "seen since the absence began", and
    # _confirmed_removals would never report the removal.
    seen = timezone.now() - timedelta(seconds=14)
    _ingest_observations(website, [
        Observation(_payload("batch.io", [GTM, HOTJAR]), seen),
        Observation(_payload("batch.io", [GTM]), seen + timedelta(seconds=10)),
    ])
    hotjar = Script.objects.get(website=website, src_url=HOTJAR)
    assert hotjar.last_seen_at == seen


def test_last_seen_is_corrected_on_an_existing_row_too(website):
    _ingest_observations(website, [Observation(_payload("batch.io", [GTM, HOTJAR]))])
    seen = timezone.now() - timedelta(seconds=12)
    _ingest_observations(website, [Observation(_payload("batch.io", [GTM, HOTJAR]), seen)])
    assert Script.objects.get(website=website, src_url=HOTJAR).last_seen_at == seen


def test_website_last_seen_is_the_newest_arrival(website):
    newest = timezone.now() - timedelta(seconds=2)
    _ingest_observations(website, [
        Observation(_payload("batch.io", [GTM]), newest - timedelta(seconds=8)),
        Observation(_payload("batch.io", [GTM]), newest),
    ])
    website.refresh_from_db()
    assert website.last_seen_at == newest


def test_identical_form_reports_are_written_once(website):
    with patch("apps.scripts.tasks._upsert_form") as upsert:
        _ingest_observations(website, [Observation(_payload("batch.io", s)) for s in LOAD])
    assert upsert.call_count == 1


# ── When removal evidence is weighed ───────────────────────────────────────


def _bucket_start(offset_buckets=0):
    now = timezone.now()
    base = now.replace(second=0, microsecond=0) - timedelta(minutes=5)
    return base + timedelta(minutes=offset_buckets)


def test_a_batch_that_opens_a_bucket_weighs_the_evidence():
    t = _bucket_start()
    batch = [Observation({}, t + timedelta(seconds=1)), Observation({}, t + timedelta(seconds=5))]
    rows = [(o.received_at, []) for o in reversed(batch)] + [(t - timedelta(seconds=30), [])]
    assert _opens_a_load(rows, batch, timezone.now())


def test_a_batch_joining_an_open_bucket_does_not():
    t = _bucket_start()
    batch = [Observation({}, t + timedelta(seconds=20))]
    rows = [(t + timedelta(seconds=20), []), (t + timedelta(seconds=2), [])]
    assert not _opens_a_load(rows, batch, timezone.now())


def test_single_post_rule_is_unchanged():
    # One post opening a bucket is "the newest bucket holds one row".
    t = _bucket_start()
    now = t + timedelta(seconds=1)
    assert _opens_a_load([(now, [])], [Observation({})], now)
    assert not _opens_a_load([(now, []), (t, [])], [Observation({})], now)


# ── Delivery: nothing left behind, nothing lost ────────────────────────────


@override_settings(INGEST_BATCH_SITES=["*"])
def test_enabled_for_every_site_with_a_star():
    assert ingest_batch.enabled_for("any-site")


@override_settings(INGEST_BATCH_SITES=["site-a"])
def test_enabled_only_for_listed_sites():
    assert ingest_batch.enabled_for("site-a")
    assert not ingest_batch.enabled_for("site-b")


def test_off_by_default():
    assert not ingest_batch.enabled_for("site-a")


def test_one_flush_is_scheduled_per_burst(redis, website):
    with patch.object(ingest_batch.flush_ingest_batch, "apply_async") as schedule:
        for scripts in LOAD:
            ingest_batch.enqueue(str(website.site_id), _payload("batch.io", scripts))
    assert schedule.call_count == 1
    buf = ingest_batch.buffer_key(str(website.site_id), "https://batch.io/")
    assert len(redis.lists[buf]) == len(LOAD)


def test_campaign_params_fill_the_same_batch(redis, website):
    a = ingest_batch.buffer_key("s", "https://batch.io/landing")
    b = ingest_batch.buffer_key("s", "https://batch.io/landing?utm_source=ad&gclid=1")
    assert a == b


def test_a_post_arriving_mid_flush_schedules_the_next_flush(redis, website):
    site = str(website.site_id)
    with patch.object(ingest_batch.flush_ingest_batch, "apply_async") as schedule:
        ingest_batch.enqueue(site, _payload("batch.io", [GTM]))
        buf = ingest_batch.buffer_key(site, "https://batch.io/")
        ingest_batch.take(redis, buf, "flush-1")  # the flush has claimed the list
        ingest_batch.enqueue(site, _payload("batch.io", [GTM, GA4]))
    assert schedule.call_count == 2  # the late post was not stranded


def test_a_redelivered_flush_resumes_its_own_batch(redis, website):
    site = str(website.site_id)
    with patch.object(ingest_batch.flush_ingest_batch, "apply_async"):
        ingest_batch.enqueue(site, _payload("batch.io", [GTM]))
        ingest_batch.enqueue(site, _payload("batch.io", [GTM, GA4]))
    buf = ingest_batch.buffer_key(site, "https://batch.io/")
    _, first = ingest_batch.take(redis, buf, "task-1")
    # Worker killed before finishing: the same task id comes back.
    _, again = ingest_batch.take(redis, buf, "task-1")
    assert len(first) == 2 and again == first


def test_flush_processes_the_batch_and_cleans_up(redis, website):
    site = str(website.site_id)
    with patch.object(ingest_batch.flush_ingest_batch, "apply_async"):
        for scripts in LOAD:
            ingest_batch.enqueue(site, _payload("batch.io", scripts))
    buf = ingest_batch.buffer_key(site, "https://batch.io/")

    result = ingest_batch.flush_ingest_batch.apply(args=[site, buf], task_id="t-1").get()

    assert result == len(LOAD)
    assert ScriptSnapshot.objects.filter(website=website).count() == len(LOAD)
    assert redis.lists == {} and redis.strings == {}


def test_a_failed_flush_retries_the_same_posts(redis, website):
    site = str(website.site_id)
    with patch.object(ingest_batch.flush_ingest_batch, "apply_async"):
        for scripts in LOAD:
            ingest_batch.enqueue(site, _payload("batch.io", scripts))
    buf = ingest_batch.buffer_key(site, "https://batch.io/")

    calls = []

    def flaky(site_obj, observations):
        calls.append(len(observations))
        if len(calls) == 1:
            raise RuntimeError("database went away")

    with patch("apps.scripts.tasks._ingest_observations", side_effect=flaky):
        # Eager mode raises Retry instead of re-running; a real retry, like a
        # redelivery after a killed worker, comes back with the same task id.
        with pytest.raises(Retry):
            ingest_batch.flush_ingest_batch.apply(args=[site, buf], task_id="t-2")
        assert redis.lists  # the claimed batch survived the failure
        ingest_batch.flush_ingest_batch.apply(args=[site, buf], task_id="t-2")

    assert calls == [len(LOAD), len(LOAD)]  # the retry saw the whole batch
    assert redis.lists == {}


def test_sweeper_reschedules_only_lost_flushes(redis, website):
    site = str(website.site_id)
    with patch.object(ingest_batch.flush_ingest_batch, "apply_async"):
        ingest_batch.enqueue(site, _payload("batch.io", [GTM]))
        ingest_batch.enqueue(site, _payload("batch.io", [GTM], page="/about"))
    lost = ingest_batch.buffer_key(site, "https://batch.io/about")
    redis.delete(ingest_batch._schedule_key(lost))  # its flush never ran

    with patch.object(ingest_batch.flush_ingest_batch, "apply_async") as schedule:
        assert ingest_batch.sweep_ingest_buffers() == 1
    schedule.assert_called_once_with(args=[site, lost], countdown=0)


# ── The endpoint ───────────────────────────────────────────────────────────


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient
    return APIClient()


def _wire(site_id, scripts):
    return {"site_id": site_id, **_payload("batch.io", scripts), "forms": []}


@override_settings(INGEST_BATCH_SITES=["*"])
def test_endpoint_buffers_when_batching_is_on(redis, api_client, website):
    with patch("apps.scripts.views.process_ingest_payload.delay") as unbatched:
        resp = api_client.post("/api/ingest/", _wire(website.site_id, [GTM, GA4]), format="json")
    assert resp.status_code == 202
    unbatched.assert_not_called()
    # Celery runs eagerly in tests, so the scheduled flush has already run.
    assert ScriptSnapshot.objects.filter(website=website).count() == 1


def test_endpoint_is_unbatched_by_default(redis, api_client, website):
    with patch("apps.scripts.views.process_ingest_payload.delay") as unbatched:
        resp = api_client.post("/api/ingest/", _wire(website.site_id, [GTM]), format="json")
    assert resp.status_code == 202
    unbatched.assert_called_once()
    assert redis.lists == {}


@override_settings(INGEST_BATCH_SITES=["*"])
def test_endpoint_falls_back_when_the_buffer_is_unavailable(api_client, website):
    with patch("apps.scripts.ingest_batch._redis", side_effect=ConnectionError("redis down")), \
            patch("apps.scripts.views.process_ingest_payload.delay") as unbatched:
        resp = api_client.post("/api/ingest/", _wire(website.site_id, [GTM]), format="json")
    assert resp.status_code == 202
    unbatched.assert_called_once()  # the post was not lost
