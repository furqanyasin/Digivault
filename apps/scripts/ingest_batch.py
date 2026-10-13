"""Batched ingest: one diff per page per burst of posts, not one per post.

**Off unless a site is listed in INGEST_BATCH_SITES** (`*` for every site).
The unbatched path (`tasks.process_ingest_payload`) is unchanged and remains
the default. Turn batching on for a site when its `ingest_lock` log lines say
its posts are queueing behind each other (docs/runbooks/capacity-checks.md),
not before: it is a change to the busiest path in the product, and it exists
to fix contention, not to be tidier.

Why it helps. The snippet posts six or more times per pageview (load, 2.5s,
then per DOM-mutation burst for 30s). Unbatched, every post takes the
website's row lock, saves its snapshot, reloads up to 120 rows of history and
diffs it, so one page load was six diffs, serialized. The diff windows are
unions of 60s buckets, so those six posts were always going to be unioned into
one window anyway. Batched, a page's posts collect in Redis for
INGEST_BATCH_DELAY_SECONDS and are diffed once (`tasks._ingest_observations`).
The per-post parts still happen per post: each post keeps its own snapshot,
stamped with its *arrival* time, so the 60s load buckets are cut exactly where
they always were.

Delivery rules, because a batch is the only copy of those observations:

* **No post is left behind.** The flush deletes the page's "flush scheduled"
  marker *before* it takes the list. A post that arrives mid-flush either
  lands in the list being taken, or finds no marker and schedules the next
  flush itself. `sweep_ingest_buffers` reschedules any list whose flush was
  lost anyway (worker restart, broker hiccup).
* **No batch is lost to a crash.** The flush *renames* the list to a key named
  after its own Celery task id instead of reading and deleting it. The task is
  `acks_late`, so a worker killed mid-batch has the same task (same id)
  redelivered, and it resumes that exact batch. A retry keeps the id too. The
  key is deleted only after the database transaction has committed.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.scripts.normalize import normalize_page_url

logger = logging.getLogger(__name__)

# A page's list lives at most this long without a flush. Refreshed on every
# push, so only an abandoned list expires.
BUFFER_TTL_SECONDS = 3600
# The "flush scheduled" marker. Outlives the flush delay with room to spare,
# and expires on its own if the scheduled flush is lost, so the next post (or
# the sweeper) schedules another.
SCHEDULE_TTL_SECONDS = 120
DEFAULT_DELAY_SECONDS = 15

_BUF = "ingest:buf:"
_SCHED = "ingest:sched:"
_PROC = "ingest:proc:"


def enabled_for(site_id: str) -> bool:
    sites = getattr(settings, "INGEST_BATCH_SITES", []) or []
    return "*" in sites or str(site_id) in sites


def _redis():
    from django_redis import get_redis_connection

    return get_redis_connection("default")


def _text(value) -> str:
    return value.decode() if isinstance(value, bytes) else value


def buffer_key(site_id: str, page_url: str) -> str:
    # Keyed on the normalized page, the same rule the task applies, so a page
    # reached with and without a campaign param fills one batch, not two.
    page = hashlib.sha1(normalize_page_url(page_url).encode()).hexdigest()[:16]
    return f"{_BUF}{site_id}:{page}"


def _schedule_key(buf: str) -> str:
    return _SCHED + buf[len(_BUF):]


def _processing_key(buf: str, token: str) -> str:
    return f"{_PROC}{buf[len(_BUF):]}:{token}"


def _site_of(buf: str) -> str:
    return buf[len(_BUF):].split(":", 1)[0]


def enqueue(site_id: str, payload: dict) -> None:
    """Buffer one post and make sure a flush is scheduled for its page."""
    buf = buffer_key(site_id, payload["page_url"])
    item = json.dumps({"received_at": timezone.now().isoformat(), "payload": payload})
    pipe = _redis().pipeline()
    pipe.rpush(buf, item)
    pipe.expire(buf, BUFFER_TTL_SECONDS)
    pipe.set(_schedule_key(buf), "1", nx=True, ex=SCHEDULE_TTL_SECONDS)
    scheduled = pipe.execute()[-1]
    if scheduled:
        delay = getattr(settings, "INGEST_BATCH_DELAY_SECONDS", DEFAULT_DELAY_SECONDS)
        flush_ingest_batch.apply_async(args=[str(site_id), buf], countdown=delay)


def take(redis, buf: str, token: str) -> tuple[str, list[dict]]:
    """Claim the page's buffered posts for the flush identified by `token`.

    Returns `(processing_key, items)`. Called again with the same token (a
    redelivered or retried task), it returns the batch it claimed before
    instead of claiming a new one.
    """
    proc = _processing_key(buf, token)
    if not redis.exists(proc):
        # Marker first, list second: see "No post is left behind" above.
        redis.delete(_schedule_key(buf))
        try:
            redis.rename(buf, proc)
        except Exception:  # redis.ResponseError("no such key"): nothing buffered
            return proc, []
    return proc, [json.loads(_text(raw)) for raw in redis.lrange(proc, 0, -1)]


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    name="scripts.flush_ingest_batch",
)
def flush_ingest_batch(self, site_id: str, buf: str) -> int:
    """Diff one page's buffered posts in a single pass. Returns posts processed."""
    from apps.scripts.tasks import Observation, _ingest_observations
    from apps.websites.models import Website

    redis = _redis()
    proc, items = take(redis, buf, self.request.id or "eager")
    if not items:
        redis.delete(proc)
        return 0

    try:
        website = Website.objects.get(site_id=site_id)
    except Website.DoesNotExist:
        logger.warning("flush_ingest_batch: unknown site_id %s, dropping %d posts", site_id, len(items))
        redis.delete(proc)
        return 0

    observations = [
        Observation(item["payload"], datetime.fromisoformat(item["received_at"]))
        for item in items
    ]
    try:
        _ingest_observations(website, observations)
    except Exception as exc:
        # The processing key is kept, and a retry has the same task id, so the
        # retry resumes this batch rather than losing it.
        logger.exception("flush_ingest_batch failed for site_id=%s (%d posts)", site_id, len(items))
        raise self.retry(exc=exc)

    redis.delete(proc)
    return len(items)


@shared_task(name="scripts.sweep_ingest_buffers")
def sweep_ingest_buffers() -> int:
    """Schedule a flush for any buffered page whose flush was lost.

    A list with a live "scheduled" marker has a flush on the way and is left
    alone. One without has had its marker expire with no flush having taken the
    list, which only happens when the scheduled task never ran.
    """
    redis = _redis()
    rescheduled = 0
    for raw in redis.scan_iter(match=f"{_BUF}*", count=500):
        buf = _text(raw)
        if redis.set(_schedule_key(buf), "1", nx=True, ex=SCHEDULE_TTL_SECONDS):
            flush_ingest_batch.apply_async(args=[_site_of(buf), buf], countdown=0)
            rescheduled += 1
    if rescheduled:
        logger.warning("sweep_ingest_buffers: rescheduled %d lost flushes", rescheduled)
    return rescheduled
