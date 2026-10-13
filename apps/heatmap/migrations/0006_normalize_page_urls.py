"""Re-key existing heatmap rows onto normalised page URLs.

`apps/heatmap/page_urls.py` collapses `#anchor`, `?utm_*`, `www.`, the scheme
and a trailing-slash difference to one key. Applying that rule only to new
payloads would leave every page already in the table split across the spellings
it was collected under, so this walks the three tables and merges.

Merging is not a rename: each table has a uniqueness constraint that the
normalised key can collide on, and the collision *is* the fix — two rows that
were always the same page. So counts are summed rather than one row winning.
The same follow-up a `normalize_script_url` change needs (`scripts/0019`,
`scripts/0031`), for the same reason.

Every write here goes through ``QuerySet.update()`` rather than ``save()``.
``first_seen_at``/``last_seen_at`` are ``auto_now_add``/``auto_now``, which
``save()`` applies and ``update()`` does not — saving would stamp every merged
row with the migration's own timestamp, resetting the ages the retention purge
reads and making a year-old page look like it was visited during the deploy.
"""

from django.db import migrations

from apps.heatmap.page_urls import normalize_page_url

SCROLL_BUCKETS = set(range(5, 101, 5))


def _merge_counts(target: dict, incoming: dict) -> dict:
    out = {}
    for source in (target or {}, incoming or {}):
        for bucket, value in source.items():
            try:
                b = int(bucket)
                n = int(value)
            except (TypeError, ValueError):
                continue
            if b in SCROLL_BUCKETS and n > 0:
                out[str(b)] = out.get(str(b), 0) + n
    return out


def _derive_histogram(counts: dict, visits: int) -> dict:
    if visits <= 0:
        return {}
    return {
        bucket: round(min(1.0, int(n) / visits), 3)
        for bucket, n in sorted(counts.items(), key=lambda kv: int(kv[0]))
        if int(n) > 0
    }


def _normalize_activity(Activity):
    keepers: dict[tuple, object] = {}
    doomed: list = []
    for row in Activity.objects.all().order_by("created_at").iterator():
        normalized = normalize_page_url(row.page_url)
        if not normalized:
            doomed.append(row.pk)
            continue
        key = (
            row.website_id, normalized, row.kind, row.device,
            row.visitor_type, row.source, row.x, row.y,
        )
        winner = keepers.get(key)
        if winner is None:
            if row.page_url != normalized:
                Activity.objects.filter(pk=row.pk).update(page_url=normalized)
                row.page_url = normalized
            keepers[key] = row
            continue
        # Same cell under a second spelling: fold its count into the keeper.
        winner.count += row.count
        if not winner.element and row.element:
            winner.element = row.element
        if row.last_seen_at and row.last_seen_at > winner.last_seen_at:
            winner.last_seen_at = row.last_seen_at
        if row.first_seen_at and row.first_seen_at < winner.first_seen_at:
            winner.first_seen_at = row.first_seen_at
        Activity.objects.filter(pk=winner.pk).update(
            count=winner.count,
            element=winner.element,
            first_seen_at=winner.first_seen_at,
            last_seen_at=winner.last_seen_at,
        )
        doomed.append(row.pk)
    if doomed:
        Activity.objects.filter(pk__in=doomed).delete()


def _normalize_stats(Stats):
    keepers: dict[tuple, object] = {}
    doomed: list = []
    for row in Stats.objects.all().order_by("created_at").iterator():
        normalized = normalize_page_url(row.page_url)
        if not normalized:
            doomed.append(row.pk)
            continue
        key = (row.website_id, normalized, row.device, row.visitor_type, row.source)
        winner = keepers.get(key)
        if winner is None:
            if row.page_url != normalized:
                Stats.objects.filter(pk=row.pk).update(page_url=normalized)
                row.page_url = normalized
            keepers[key] = row
            continue
        winner.visits += row.visits
        winner.total_clicks += row.total_clicks
        winner.max_scroll_percent = max(
            winner.max_scroll_percent, row.max_scroll_percent
        )
        winner.scroll_bucket_counts = _merge_counts(
            winner.scroll_bucket_counts, row.scroll_bucket_counts
        )
        winner.scroll_histogram = _derive_histogram(
            winner.scroll_bucket_counts, winner.visits
        )
        # Geometry is "as last observed", so the fresher measurement wins
        # outright rather than being averaged with a stale one.
        if row.last_seen_at and row.last_seen_at > winner.last_seen_at:
            winner.last_seen_at = row.last_seen_at
            if row.page_height > 0:
                winner.page_height = row.page_height
                winner.viewport_width = row.viewport_width
        elif winner.page_height == 0 and row.page_height > 0:
            winner.page_height = row.page_height
            winner.viewport_width = row.viewport_width
        if row.first_seen_at and row.first_seen_at < winner.first_seen_at:
            winner.first_seen_at = row.first_seen_at
        Stats.objects.filter(pk=winner.pk).update(
            visits=winner.visits,
            total_clicks=winner.total_clicks,
            max_scroll_percent=winner.max_scroll_percent,
            scroll_bucket_counts=winner.scroll_bucket_counts,
            scroll_histogram=winner.scroll_histogram,
            page_height=winner.page_height,
            viewport_width=winner.viewport_width,
            first_seen_at=winner.first_seen_at,
            last_seen_at=winner.last_seen_at,
        )
        doomed.append(row.pk)
    if doomed:
        Stats.objects.filter(pk__in=doomed).delete()


def _normalize_snapshots(Snapshot):
    # A picture cannot be merged, so the most recent capture of the page wins
    # and the rest go. Ordered newest-first so the first one seen is the keeper.
    keepers: set[tuple] = set()
    doomed: list = []
    for row in (
        Snapshot.objects.all().order_by("-captured_at", "-created_at").iterator()
    ):
        normalized = normalize_page_url(row.page_url)
        if not normalized:
            doomed.append(row.pk)
            continue
        key = (row.website_id, normalized, row.device)
        if key in keepers:
            doomed.append(row.pk)
            continue
        keepers.add(key)
        if row.page_url != normalized:
            Snapshot.objects.filter(pk=row.pk).update(page_url=normalized)
    if doomed:
        Snapshot.objects.filter(pk__in=doomed).delete()


def normalize(apps, schema_editor):
    _normalize_activity(apps.get_model("heatmap", "HeatmapActivity"))
    _normalize_stats(apps.get_model("heatmap", "HeatmapPageStats"))
    _normalize_snapshots(apps.get_model("heatmap", "HeatmapPageSnapshot"))


def noop(apps, schema_editor):
    """Irreversible: merged counts cannot be split back apart."""


class Migration(migrations.Migration):

    dependencies = [
        ("heatmap", "0005_heatmappagestats_page_height_and_more"),
    ]

    operations = [
        migrations.RunPython(normalize, noop),
    ]
