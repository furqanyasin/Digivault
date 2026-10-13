"""Celery tasks for heatmap aggregation.

The ingest view returns 202 immediately; summing the pre-aggregated cells into
the activity table (and updating the page stats summary) happens here, so the
snippet endpoint stays under 50ms like the rest of the ingest surface.
"""

from __future__ import annotations

import logging
import uuid

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.db.models.functions import Now

from apps.heatmap.models import HeatmapActivity, HeatmapPageStats
from apps.heatmap.page_urls import normalize_page_url
from apps.websites.models import Website

logger = logging.getLogger(__name__)

# Scroll depth buckets for the histogram, in page-height percent. The snippet
# reports the depth each observation reached; the task turns the observed
# depths into the share of visits that reached each bucket.
SCROLL_BUCKETS = list(range(5, 101, 5))


def _reached_buckets(max_scroll_percent: int, reported: dict) -> list[int]:
    """The depth bands this one visit revealed.

    The snippet reports its own per-visit reach (1 for every band it got to).
    Older snippet builds sent a share instead, and any value > 0 there still
    means "reached", so both shapes read correctly. If nothing usable arrived,
    fall back to deriving the bands from ``max_scroll_percent``, which carries
    the same information.
    """
    reached: set[int] = set()
    for bucket, value in (reported or {}).items():
        try:
            b = int(bucket)
            v = float(value)
        except (TypeError, ValueError):
            continue
        if b in SCROLL_BUCKETS and v > 0:
            reached.add(b)
    if reached:
        return sorted(reached)
    return [b for b in SCROLL_BUCKETS if b <= max_scroll_percent]


def _merge_scroll_counts(stored: dict, reached: list[int]) -> dict:
    """Add one visit's reached bands into the running per-bucket counts."""
    counts: dict[str, int] = {}
    for bucket, value in (stored or {}).items():
        try:
            b = int(bucket)
            n = int(value)
        except (TypeError, ValueError):
            continue
        if b in SCROLL_BUCKETS and n > 0:
            counts[str(b)] = n
    for b in reached:
        counts[str(b)] = counts.get(str(b), 0) + 1
    return counts


def _derive_scroll_histogram(counts: dict, visits: int) -> dict:
    """Turn per-bucket visit counts into {bucket: share_reached}.

    This is the number the scroll map actually means — "this share of visitors
    got at least this far". It used to be written straight from the incoming
    payload, which overwrote the population's curve with the single most recent
    visitor's reach on every flush, so it could never become a share at all.
    """
    if visits <= 0:
        return {}
    histogram: dict[str, float] = {}
    for bucket in sorted(counts, key=int):
        n = int(counts[bucket])
        if n > 0:
            histogram[bucket] = round(min(1.0, n / visits), 3)
    return histogram


#: Cells per INSERT. Bounds the statement's parameter count (15 per row, so
#: ~7500 placeholders) rather than the work — a payload is capped at
#: MAX_ACTIVITY_CELLS (5000) and is normally far below it.
_CELL_CHUNK = 500


def _clean_cells(cells: list) -> dict[tuple, dict]:
    """Validate and fold one payload's cells, keyed by (kind, x, y).

    Folding is not an optimisation. Postgres refuses an `INSERT ... ON CONFLICT
    DO UPDATE` whose *own* rows collide ("cannot affect row a second time"), and
    a payload may name one cell twice — the snippet aggregates per kind, and a
    malformed or hostile payload need not aggregate at all.
    """
    folded: dict[tuple, dict] = {}
    for cell in cells:
        kind = cell.get("kind")
        if not kind:
            continue
        try:
            x = int(cell["x"])
            y = int(cell["y"])
            count = int(cell["count"])
        except (KeyError, TypeError, ValueError):
            continue
        if count <= 0:
            continue
        element = (cell.get("element") or "")[:300]

        key = (kind, x, y)
        existing = folded.get(key)
        if existing is None:
            folded[key] = {"kind": kind, "x": x, "y": y, "count": count, "element": element}
        else:
            existing["count"] += count
            if element:
                existing["element"] = element
    return folded


def _accumulate_cells(
    *, website, page_url: str, device: str, visitor_type: str, source: str, cells: list
) -> int:
    """Add one payload's cells into `HeatmapActivity`. Returns cells written.

    One statement per 500 cells, not two or three per cell.

    This is the highest write-amplification path in the codebase. It used to be
    a Python loop doing `get_or_create` (a SELECT, sometimes an INSERT) and then
    an `UPDATE`, for every cell. A payload carries up to `MAX_ACTIVITY_CELLS`
    (5000) of them, and the per-site budget is 100,000 payloads a day because a
    reading visitor flushes every 15-120 seconds — so the worst case was tens of
    thousands of round trips inside one transaction, per flush, while everything
    else queued behind the same worker slots.

    Written as explicit SQL rather than `bulk_create(update_conflicts=True)`,
    because `count` has to **add**. Django's conflict update assigns the
    incoming value verbatim, which would quietly replace a cell's running total
    with whatever the latest flush happened to carry — a heatmap that looks
    plausible and is wrong, which is worse than a slow one. `ignore_conflicts`
    would be worse still: every repeat observation silently dropped.

    Doing the addition in the database also keeps the increment atomic, the way
    the old `F("count") + count` was. Reading the counts into Python and writing
    them back would lose an increment whenever two visitors on the same page
    flush at once, which on a page worth heatmapping is the normal case.
    """
    from django.db import connection
    from django.utils import timezone

    folded = _clean_cells(cells)
    if not folded:
        return 0

    table = HeatmapActivity._meta.db_table
    now = timezone.now()

    columns = (
        "id", "created_at", "updated_at", "website_id", "page_url", "kind",
        "x", "y", "device", "visitor_type", "source", "count", "element",
        "first_seen_at", "last_seen_at",
    )
    placeholder = "(" + ", ".join(["%s"] * len(columns)) + ")"

    written = 0
    values = list(folded.values())
    for start in range(0, len(values), _CELL_CHUNK):
        chunk = values[start : start + _CELL_CHUNK]
        params: list = []
        for cell in chunk:
            params.extend([
                uuid.uuid4(), now, now, website.pk, page_url, cell["kind"],
                cell["x"], cell["y"], device, visitor_type, source,
                cell["count"], cell["element"], now, now,
            ])

        column_list = ", ".join('"%s"' % c for c in columns)
        sql = (
            f'INSERT INTO "{table}" ({column_list}) '
            f"VALUES {', '.join([placeholder] * len(chunk))} "
            f"ON CONFLICT ON CONSTRAINT heatmap_activity_cell_unique DO UPDATE SET "
            f'"count" = "{table}"."count" + EXCLUDED."count", '
            # `element` describes the cell, it is not part of its identity, so
            # the newest non-blank observation wins. A blank must never erase a
            # good descriptor: move and scroll cells never carry one and share
            # this table with clicks that do.
            f'"element" = CASE WHEN EXCLUDED."element" <> \'\' '
            f'THEN EXCLUDED."element" ELSE "{table}"."element" END, '
            f'"last_seen_at" = EXCLUDED."last_seen_at", '
            f'"updated_at" = EXCLUDED."updated_at"'
        )
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
        written += len(chunk)

    return written


# Explicitly named, like every other task in the codebase. It was the one
# exception, so it registered under its import path
# (`apps.heatmap.tasks.process_heatmap_payload`) — which is invisible until
# something has to address the task by name, as queue routing does. The rename
# costs one deploy's worth of in-flight messages, which for sampled behaviour
# data collected continuously is not a loss worth designing around.
@shared_task(name="heatmap.process_heatmap_payload")
def process_heatmap_payload(site_id: str, payload: dict) -> None:
    """Sum the snippet's aggregated interaction cells into the activity table.

    Runs inside one transaction. Every cell is upserted with `count += N`; the
    page stats row is updated with the running totals. Aborts silently on an
    unknown site_id — the ingest view already validated it, this is a guard
    against a stale queued message after a website is deleted.
    """
    try:
        website = Website.objects.get(site_id=site_id)
    except Website.DoesNotExist:
        logger.warning("Heatmap ingest for unknown site_id=%s dropped", site_id)
        return

    # The toggle is re-read here, not just in the view: a payload can sit in the
    # queue across a settings change, and a task that writes rows for a site
    # whose owner has just switched collection off is the one outcome the
    # toggle exists to prevent.
    if not website.heatmap_enabled:
        return

    # Normalised server-side so the rule reaches every install without a
    # re-paste. `#anchor`, `?utm_*` and a `www.`/scheme/trailing-slash
    # difference are all the same page, and keying on the raw href split one
    # page's heat across a row per campaign and a row per in-page link.
    page_url = normalize_page_url(payload.get("page_url", "") or "")
    if not page_url:
        return

    device = payload.get("device") or HeatmapPageStats.Device.DESKTOP
    visitor_type = payload.get("visitor_type") or HeatmapPageStats.VisitorType.NEW
    source = payload.get("source") or HeatmapPageStats.Source.DIRECT
    total_clicks = int(payload.get("total_clicks") or 0)
    max_scroll = int(payload.get("max_scroll_percent") or 0)
    reported_histogram = payload.get("scroll_histogram") or {}
    page_height = int(payload.get("page_height") or 0)
    viewport_width = int(payload.get("viewport_width") or 0)
    cells = payload.get("cells") or []
    is_final = bool(payload.get("final"))

    with transaction.atomic():
        _accumulate_cells(
            website=website,
            page_url=page_url,
            device=device,
            visitor_type=visitor_type,
            source=source,
            cells=cells,
        )

        stats, created = HeatmapPageStats.objects.get_or_create(
            website=website,
            page_url=page_url,
            device=device,
            visitor_type=visitor_type,
            source=source,
            defaults={
                "visits": 0,
                "total_clicks": 0,
                "max_scroll_percent": max_scroll,
                "scroll_histogram": {},
                "scroll_bucket_counts": {},
                "page_height": page_height,
                "viewport_width": viewport_width,
            },
        )
        new_max_scroll = max_scroll if created else max(stats.max_scroll_percent, max_scroll)
        updates = {
            "total_clicks": F("total_clicks") + total_clicks,
            "max_scroll_percent": new_max_scroll,
            "last_seen_at": Now(),
        }
        # Page geometry is "as last observed" — only overwrite when the snippet
        # actually reported it, so an older snippet build (which sends neither)
        # cannot wipe a good measurement back to zero.
        if page_height > 0:
            updates["page_height"] = page_height
        if viewport_width > 0:
            updates["viewport_width"] = viewport_width

        # Scroll reach is counted per *visit*, so it accumulates only on the
        # final flush — the same flush that increments `visits`. Counting the
        # periodic flushes too would credit one visitor with five visits' worth
        # of reach and cap every share at 1.0 regardless of the real drop-off.
        if is_final:
            counts = _merge_scroll_counts(
                stats.scroll_bucket_counts,
                _reached_buckets(max_scroll, reported_histogram),
            )
            updates["visits"] = F("visits") + 1
            updates["scroll_bucket_counts"] = counts
            updates["scroll_histogram"] = _derive_scroll_histogram(
                counts, stats.visits + 1
            )
        HeatmapPageStats.objects.filter(pk=stats.pk).update(**updates)


@shared_task(name="heatmap.capture_page_snapshot")
def capture_page_snapshot(website_id: str, page_url: str, device: str = "desktop") -> None:
    """Screenshot one page and attach it to its `HeatmapPageSnapshot` row.

    Every outcome is recorded on the row rather than raised, because the
    dashboard reads status to decide what to show: a `blocked` or `unavailable`
    page falls back to the live iframe, which is a worse backdrop but not a
    broken one. Nothing here may take the heatmap itself down.
    """
    from django.core.files.base import ContentFile
    from django.utils import timezone

    from apps.heatmap.capture import (
        BlockedURLError,
        CaptureBlocked,
        CaptureUnavailable,
        capture_page,
    )
    from apps.heatmap.models import HeatmapPageSnapshot

    try:
        website = Website.objects.get(pk=website_id)
    except Website.DoesNotExist:
        logger.warning("Snapshot capture for unknown website=%s dropped", website_id)
        return

    snapshot, _ = HeatmapPageSnapshot.objects.get_or_create(
        website=website,
        page_url=page_url,
        device=device,
        defaults={"status": HeatmapPageSnapshot.Status.PENDING},
    )

    try:
        result = capture_page(page_url, device)
    except CaptureUnavailable as exc:
        # Chromium is not installed here. Not a failure of this page — recorded
        # so a retry sweep can skip it instead of re-attempting every page.
        snapshot.status = HeatmapPageSnapshot.Status.UNAVAILABLE
        snapshot.error_message = str(exc)[:500]
        snapshot.save(update_fields=["status", "error_message", "updated_at"])
        return
    except (CaptureBlocked, BlockedURLError) as exc:
        snapshot.status = HeatmapPageSnapshot.Status.BLOCKED
        snapshot.error_message = str(exc)[:500]
        snapshot.save(update_fields=["status", "error_message", "updated_at"])
        return
    except Exception as exc:  # noqa: BLE001 — a capture must never break ingest
        logger.warning("Snapshot capture failed for %s: %s", page_url, exc, exc_info=True)
        snapshot.status = HeatmapPageSnapshot.Status.FAILED
        snapshot.error_message = str(exc)[:500]
        snapshot.save(update_fields=["status", "error_message", "updated_at"])
        return

    snapshot.width = result.width
    snapshot.height = result.height
    snapshot.status = HeatmapPageSnapshot.Status.READY
    snapshot.error_message = ""
    snapshot.captured_at = timezone.now()
    # save() first so the upload path can use a real pk, then attach the image.
    snapshot.save(
        update_fields=[
            "width", "height", "status", "error_message", "captured_at", "updated_at",
        ]
    )
    snapshot.image.save(f"{snapshot.pk}.png", ContentFile(result.png), save=True)


@shared_task(name="heatmap.run_due_snapshot_captures")
def run_due_snapshot_captures() -> int:
    """Refresh snapshots for the pages that actually have heatmap traffic.

    Only pages already carrying interaction data are captured — the point of a
    snapshot is to back a heatmap, so capturing a page nobody has interacted
    with spends the shared per-host budget for nothing. Capped per run for the
    same reason: this budget is shared with uptime monitoring, and monitoring
    wins.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.heatmap.capture import capture_available, snapshot_max_age_days
    from apps.heatmap.models import HeatmapPageSnapshot

    if not capture_available():
        logger.info("Snapshot capture skipped: Playwright/Chromium not installed")
        return 0

    cap = getattr(settings, "HEATMAP_SNAPSHOT_MAX_PER_RUN", 20)
    stale_before = timezone.now() - timedelta(days=snapshot_max_age_days())

    # One capture per (website, page_url, device) that has traffic. Segments
    # share a backdrop, so collapse them. Sites whose heatmap has been switched
    # off are skipped: their stats rows linger until the purge, and spending the
    # per-host budget photographing a page nobody can open a heatmap for is the
    # exact waste the toggle was added to stop.
    targets = (
        HeatmapPageStats.objects.filter(
            visits__gt=0, website__heatmap_enabled=True
        )
        .values_list("website_id", "page_url", "device")
        .distinct()
    )

    dispatched = 0
    for website_id, page_url, device in targets:
        if dispatched >= cap:
            break
        existing = HeatmapPageSnapshot.objects.filter(
            website_id=website_id, page_url=page_url, device=device
        ).first()
        if existing is not None:
            # `unavailable` means Chromium was missing; we already know it is
            # present now, so those are eligible again.
            fresh = (
                existing.status == HeatmapPageSnapshot.Status.READY
                and existing.captured_at is not None
                and existing.captured_at > stale_before
            )
            if fresh:
                continue
        capture_page_snapshot.delay(str(website_id), page_url, device)
        dispatched += 1

    return dispatched


@shared_task(name="heatmap.purge_old_heatmap_data")
def purge_old_heatmap_data() -> dict:
    """Drop interaction data nobody is looking at any more.

    `HeatmapActivity` is the highest-cardinality table in the codebase: one row
    per (page, kind, device, visitor type, source, x, y), which is up to
    100x100 cells times twenty segment buckets *per page*. Every other event
    table here already has a purge — snapshots at 90 days, SiteEvent tiered at
    365/90 — and this one shipped without, which is survivable at a handful of
    sites and is not once behaviour analytics is on across an agency's book.

    Cells and page rows are aged on `last_seen_at`, so a page that is still
    being visited is never purged no matter how old its first observation is.
    Snapshots are purged only when the page they back has gone: the picture is
    worthless without the heat, and it is the expensive row to re-acquire.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.heatmap.models import HeatmapPageSnapshot

    max_age_days = getattr(settings, "HEATMAP_DATA_MAX_AGE_DAYS", 180)
    cutoff = timezone.now() - timedelta(days=max_age_days)

    cells_deleted, _ = HeatmapActivity.objects.filter(last_seen_at__lt=cutoff).delete()
    stats_deleted, _ = HeatmapPageStats.objects.filter(last_seen_at__lt=cutoff).delete()

    # A snapshot whose page stats row has just gone is backing nothing. Compare
    # against the surviving (website, page_url) set rather than the snapshot's
    # own age: a picture of a page that is still busy stays useful for as long
    # as the page does.
    live_pages = set(
        HeatmapPageStats.objects.values_list("website_id", "page_url").distinct()
    )
    orphan_ids = [
        pk
        for pk, website_id, page_url in HeatmapPageSnapshot.objects.values_list(
            "pk", "website_id", "page_url"
        )
        if (website_id, page_url) not in live_pages
    ]
    snapshots_deleted = 0
    if orphan_ids:
        for snapshot in HeatmapPageSnapshot.objects.filter(pk__in=orphan_ids):
            # Delete the file too — the row going away does not reclaim the PNG.
            if snapshot.image:
                snapshot.image.delete(save=False)
            snapshot.delete()
            snapshots_deleted += 1

    logger.info(
        "Heatmap purge: %s cells, %s page rows, %s snapshots older than %sd",
        cells_deleted, stats_deleted, snapshots_deleted, max_age_days,
    )
    return {
        "cells": cells_deleted,
        "pages": stats_deleted,
        "snapshots": snapshots_deleted,
    }
