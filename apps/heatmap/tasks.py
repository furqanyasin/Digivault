"""Celery tasks for heatmap aggregation.

The ingest view returns 202 immediately; summing the pre-aggregated cells into
the activity table (and updating the page stats summary) happens here, so the
snippet endpoint stays under 50ms like the rest of the ingest surface.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction
from django.db.models import F

from apps.heatmap.models import HeatmapActivity, HeatmapPageStats
from apps.websites.models import Website

logger = logging.getLogger(__name__)

# Scroll depth buckets for the histogram, in page-height percent. The snippet
# reports the depth each observation reached; the task turns the observed
# depths into the share of visits that reached each bucket.
SCROLL_BUCKETS = list(range(5, 101, 5))


def _build_scroll_histogram(max_scroll_percent: int, reported: dict) -> dict:
    """Return {bucket: share_reached} for the page row.

    Prefers the snippet's own histogram (it can track scroll over the whole
    visit, including pagehide, more accurately than the final max depth of one
    post). Falls back to a synthetic curve anchored on max_scroll_percent if
    the snippet sent none.
    """
    histogram: dict[str, float] = {}
    if reported:
        for bucket, share in reported.items():
            try:
                b = int(bucket)
            except (TypeError, ValueError):
                continue
            if b in SCROLL_BUCKETS and 0.0 <= share <= 1.0:
                histogram[str(b)] = round(share, 3)
        if histogram:
            return histogram
    # Synthetic: assume linear decay from the deepest observed reach.
    for b in SCROLL_BUCKETS:
        if b <= max_scroll_percent:
            histogram[str(b)] = round(1.0 - (b - 1) / 100.0, 3)
        else:
            break
    return histogram


@shared_task
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

    page_url = payload.get("page_url", "") or ""
    if not page_url:
        return

    device = payload.get("device") or HeatmapPageStats.Device.DESKTOP
    visitor_type = payload.get("visitor_type") or HeatmapPageStats.VisitorType.NEW
    source = payload.get("source") or HeatmapPageStats.Source.DIRECT
    total_clicks = int(payload.get("total_clicks") or 0)
    max_scroll = int(payload.get("max_scroll_percent") or 0)
    reported_histogram = payload.get("scroll_histogram") or {}
    cells = payload.get("cells") or []
    is_final = bool(payload.get("final"))

    with transaction.atomic():
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
            element = cell.get("element") or ""
            element = element[:300]
            defaults = {"count": count}
            if element:
                defaults["element"] = element
            # Accumulate across observations: update_or_create with an F()
            # default is rejected on the create path, so get-or-create first
            # and then always add the incoming count.
            row, created = HeatmapActivity.objects.get_or_create(
                website=website,
                page_url=page_url,
                kind=kind,
                device=device,
                visitor_type=visitor_type,
                source=source,
                x=x,
                y=y,
                defaults=defaults,
            )
            if not created:
                upd = {"count": F("count") + count, "last_seen_at": row.last_seen_at or None}
                if element:
                    upd["element"] = element
                HeatmapActivity.objects.filter(pk=row.pk).update(**upd)

        histogram = _build_scroll_histogram(max_scroll, reported_histogram)
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
                "scroll_histogram": histogram,
            },
        )
        new_max_scroll = max_scroll if created else max(stats.max_scroll_percent, max_scroll)
        updates = {
            "total_clicks": F("total_clicks") + total_clicks,
            "max_scroll_percent": new_max_scroll,
            "scroll_histogram": histogram,
        }
        if is_final:
            updates["visits"] = F("visits") + 1
        HeatmapPageStats.objects.filter(pk=stats.pk).update(**updates)
