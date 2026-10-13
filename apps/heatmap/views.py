import logging

from django.conf import settings
from django.db.models import F, Max, Sum
from django.http import FileResponse
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.common.mixins import TeamScopedMixin
from apps.common.permissions import IsTeamMember
from apps.heatmap.models import (
    HeatmapActivity,
    HeatmapPageSnapshot,
    HeatmapPageStats,
)
from apps.heatmap.page_urls import normalize_page_url
from apps.heatmap.serializers import (
    HeatmapCellSerializer,
    HeatmapIngestSerializer,
    HeatmapPageSerializer,
    HeatmapSnapshotSerializer,
)
from apps.heatmap.tasks import capture_page_snapshot, process_heatmap_payload
from apps.scripts.ingest_origin import origin_matches
from apps.websites.models import Website

logger = logging.getLogger(__name__)


class HeatmapIngestThrottle(AnonRateThrottle):
    """Per-site_id rate limit so one site cannot starve others behind one IP.

    Deliberately far looser than the script ingest scope: a script payload
    is posted a handful of times per *page load*, whereas this is posted every
    time a reading visitor's flush timer fires. At 2000 a site with a few
    hundred daily visitors hit the ceiling before lunch and the rest of the
    day's behaviour silently vanished — which looks exactly like the heatmap
    not collecting, because it is.
    """

    scope = "heatmap_ingest"
    rate = None  # resolved from settings by get_rate()

    def get_rate(self):
        return getattr(settings, "HEATMAP_INGEST_RATE", "100000/day")

    def get_cache_key(self, request, view):
        site_id = (request.data.get("site_id") or "").strip()
        if site_id:
            return self.cache_format % {"scope": self.scope, "ident": site_id}
        return super().get_cache_key(request, view)


class HeatmapIngestView(APIView):
    """POST /api/ingest/heatmap/ — aggregated interaction data from the snippet.

    Mirrors the script ingest surface: unauthenticated (authorised by site_id),
    domain-bound, throttled per site, and returns 202 while the aggregation
    runs in Celery. The payload is already aggregated by the snippet into
    100x100 percentage cells, so this stays small and fast.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [HeatmapIngestThrottle]

    MAX_BODY_BYTES = 512 * 1024  # 512 KB

    def post(self, request):
        content_length = request.META.get("CONTENT_LENGTH")
        try:
            if content_length and int(content_length) > self.MAX_BODY_BYTES:
                return Response(status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        except (TypeError, ValueError):
            pass

        serializer = HeatmapIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            website = Website.objects.get(site_id=data["site_id"])
        except Website.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        # Behaviour analytics is opt-in per site. This is the gate — the snippet
        # is one cached file shared by every client, so it cannot be the thing
        # that decides. 204 rather than 403: nothing is wrong, there is simply
        # nothing to send, and the snippet reads it as "stop asking" and stops
        # collecting for the rest of the visit. A 403 would look like a domain
        # mismatch in the logs and read as a fault worth investigating.
        if not website.heatmap_enabled:
            return Response(status=status.HTTP_204_NO_CONTENT)

        # Domain-binding, through the one shared helper. This was a fifth
        # inlined copy of the check and carried the same bug the other four
        # did: it stripped `www.` *before* the scheme, so a site saved as
        # `https://www.example.com` reduced to `www.example.com`, never matched
        # the browser's `example.com`, and answered 403 to every heatmap post
        # that site ever sent.
        if not origin_matches(request, website):
            logger.warning(
                "Heatmap ingest domain mismatch: site_id=%s origin=%s registered=%s",
                data["site_id"],
                request.META.get("HTTP_ORIGIN") or request.META.get("HTTP_REFERER", ""),
                website.domain,
            )
            return Response(status=status.HTTP_403_FORBIDDEN)

        process_heatmap_payload.delay(
            site_id=website.site_id,
            payload={
                "page_url": data["page_url"],
                "device": data["device"],
                "visitor_type": data["visitor_type"],
                "source": data["source"],
                "final": data["final"],
                "total_clicks": data["total_clicks"],
                "max_scroll_percent": data["max_scroll_percent"],
                "page_height": data["page_height"],
                "viewport_width": data["viewport_width"],
                "scroll_histogram": sanitize_histogram(data["scroll_histogram"]),
                "cells": [
                    {
                        "kind": c["kind"],
                        "x": c["x"],
                        "y": c["y"],
                        "count": c["count"],
                        "element": c.get("element") or "",
                    }
                    for c in data["cells"]
                ],
            },
        )
        return Response(status=status.HTTP_202_ACCEPTED)


def sanitize_histogram(histogram: dict) -> dict:
    """Keep only integer buckets within the supported range."""
    return {
        str(k): float(v)
        for k, v in (histogram or {}).items()
        if str(k).isdigit() and 0 <= float(v) <= 1.0
    }


def apply_segment_filters(queryset, request):
    """Filter a heatmap queryset by the optional segment dimensions.

    Each of device / visitor_type / source narrows the segment. An absent or
    "all" value means "don't filter" — the frontend omits the param entirely
    for the segmented filters it isn't constraining.
    """
    device = request.query_params.get("device")
    if device and device != "all":
        queryset = queryset.filter(device=device)
    visitor_type = request.query_params.get("visitor_type")
    if visitor_type and visitor_type != "all":
        queryset = queryset.filter(visitor_type=visitor_type)
    source = request.query_params.get("source")
    if source and source != "all":
        queryset = queryset.filter(source=source)
    return queryset


# A site can legitimately have thousands of distinct pages, but the page
# selector is a dropdown a human reads. Ordering by visits and capping keeps
# the response bounded without the silent-truncation trap a paginated list
# would be here: the caller reads one array and the busiest pages are in it.
MAX_PAGES_RETURNED = 500


class HeatmapPageListView(TeamScopedMixin, generics.ListAPIView):
    """GET /api/v1/heatmap/pages/ — pages with heatmap data for this team.

    Query params: ?website=<website_id>&device=desktop&visitor_type=&source=

    **Rows are aggregated to one per page URL before they are returned**, and
    that is the whole point of this view rather than a plain list.
    ``HeatmapPageStats`` is stored per *segment* — one row per (page, device,
    visitor type, source), so twenty rows for a page that has seen a bit of
    every kind of traffic. Serving those raw put the same URL in the selector
    ten times over, and the dashboard picked the first match to fill its
    summary tiles: a page with a hundred visits reported "1 observation, 0
    clicks" because the first row it happened to find was the one visitor who
    arrived from email. Narrowing by segment still works — the filters are
    applied first and the aggregate is taken over whatever survives.

    `scroll_histogram` cannot be summed (it is a share), so it is re-derived as
    a visit-weighted average of the rows being merged. Page geometry is taken
    from the row seen most recently, which is what "as last observed" means.
    """

    permission_classes = [IsTeamMember]
    serializer_class = HeatmapPageSerializer
    pagination_class = None
    queryset = HeatmapPageStats.objects.all()

    def get_queryset(self):
        qs = super().get_queryset()
        qs = apply_segment_filters(qs, self.request)
        website = self.request.query_params.get("website")
        if website:
            qs = qs.filter(website_id=website)
        return qs

    def list(self, request, *args, **kwargs):
        rows = list(self.filter_queryset(self.get_queryset()))
        return Response(_aggregate_page_rows(rows)[:MAX_PAGES_RETURNED])


def _aggregate_page_rows(rows) -> list[dict]:
    """Collapse per-segment page stats to one entry per (page_url, device)."""
    merged: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row.page_url, row.device)
        entry = merged.get(key)
        if entry is None:
            entry = {
                "id": str(row.pk),
                "page_url": row.page_url,
                "device": row.device,
                # The merged row spans segments, so naming one would be a lie.
                "visitor_type": "all",
                "source": "all",
                "visits": 0,
                "total_clicks": 0,
                "max_scroll_percent": 0,
                "scroll_histogram": {},
                "page_height": 0,
                "viewport_width": 0,
                "first_seen_at": row.first_seen_at,
                "last_seen_at": row.last_seen_at,
                "_geometry_at": None,
                "_weighted": {},
            }
            merged[key] = entry
        entry["visits"] += row.visits
        entry["total_clicks"] += row.total_clicks
        entry["max_scroll_percent"] = max(
            entry["max_scroll_percent"], row.max_scroll_percent
        )
        if row.first_seen_at and (
            entry["first_seen_at"] is None or row.first_seen_at < entry["first_seen_at"]
        ):
            entry["first_seen_at"] = row.first_seen_at
        if row.last_seen_at and (
            entry["last_seen_at"] is None or row.last_seen_at > entry["last_seen_at"]
        ):
            entry["last_seen_at"] = row.last_seen_at
        # Geometry is "as last observed", so the freshest row wins outright
        # rather than being averaged with a stale measurement of a page that
        # has since grown a section.
        if row.page_height > 0 and row.viewport_width > 0:
            if entry["_geometry_at"] is None or (
                row.last_seen_at and row.last_seen_at >= entry["_geometry_at"]
            ):
                entry["_geometry_at"] = row.last_seen_at
                entry["page_height"] = row.page_height
                entry["viewport_width"] = row.viewport_width
        # A share is not additive. Weight each segment's curve by the visits it
        # was measured over, then divide by the merged visit total below.
        for bucket, share in (row.scroll_histogram or {}).items():
            try:
                key_int = int(bucket)
                value = float(share)
            except (TypeError, ValueError):
                continue
            slot = str(key_int)
            entry["_weighted"][slot] = (
                entry["_weighted"].get(slot, 0.0) + value * row.visits
            )

    out = []
    for entry in merged.values():
        visits = entry["visits"]
        weighted = entry.pop("_weighted")
        entry.pop("_geometry_at")
        entry["scroll_histogram"] = (
            {
                bucket: round(min(1.0, total / visits), 3)
                for bucket, total in sorted(weighted.items(), key=lambda kv: int(kv[0]))
                if total > 0
            }
            if visits > 0
            else {}
        )
        for field in ("first_seen_at", "last_seen_at"):
            value = entry[field]
            entry[field] = value.isoformat() if value else None
        out.append(entry)
    out.sort(key=lambda e: (-e["visits"], e["page_url"]))
    return out


class HeatmapCellListView(TeamScopedMixin, generics.ListAPIView):
    """GET /api/v1/heatmap/activity/?website=&page_url=&kind=click — cells.

    Returns the percentage cells for one page + kind (click/move/rage), ready
    to render as a heatmap overlay.

    **Cells are summed across segments in SQL**, for the same reason the page
    list is aggregated: storage is per (device, visitor type, source), so with
    no segment filter the same grid position came back as up to ten separate
    rows. The overlay then drew ten faint blobs where one hot one belonged, the
    "peak cell" figure reported the largest *segment* rather than the largest
    cell, and the hotspot list repeated one button ten times. Aggregating also
    bounds the response at the grid size (100x100) regardless of how many
    segments a busy page has accumulated, which is what makes it safe to serve
    unpaginated.

    `element` is carried through as the descriptor from the heaviest
    contributing row — it is an attribute of the cell, not part of its
    identity, so any one of them is as true as the others and the busiest is
    the most representative.
    """

    permission_classes = [IsTeamMember]
    serializer_class = HeatmapCellSerializer
    pagination_class = None
    queryset = HeatmapActivity.objects.all()

    def get_queryset(self):
        qs = super().get_queryset()
        qs = apply_segment_filters(qs, self.request)
        website = self.request.query_params.get("website")
        if website:
            qs = qs.filter(website_id=website)
        page_url = self.request.query_params.get("page_url")
        if page_url:
            qs = qs.filter(page_url=normalize_page_url(page_url) or page_url)
        kind = self.request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        return qs

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        # Aliased `total`, not `count`: Django refuses an annotation that
        # shadows a model field, and `count` is one. The explicit order_by also
        # has to stay — the model's default `-count` ordering would otherwise be
        # folded into the GROUP BY and un-group every row it was meant to merge.
        totals = (
            qs.values("kind", "x", "y")
            .annotate(total=Sum("count"))
            .order_by("x", "y")
        )
        # One extra query for the labels, rather than a correlated subquery per
        # cell: order by count so the last write per position is the heaviest.
        elements = {}
        for kind, x, y, element in (
            qs.exclude(element="")
            .order_by("count")
            .values_list("kind", "x", "y", "element")
        ):
            elements[(kind, x, y)] = element
        device = request.query_params.get("device") or "all"
        visitor_type = request.query_params.get("visitor_type") or "all"
        source = request.query_params.get("source") or "all"
        return Response(
            [
                {
                    "kind": row["kind"],
                    "x": row["x"],
                    "y": row["y"],
                    "count": row["total"],
                    # Echo the segment that was asked for. The rows behind this
                    # cell may span several, so reporting one of theirs would
                    # claim a precision the number does not have.
                    "device": device,
                    "visitor_type": visitor_type,
                    "source": source,
                    "element": elements.get((row["kind"], row["x"], row["y"]), ""),
                }
                for row in totals
            ]
        )


class HeatmapSiteSummaryView(TeamScopedMixin, generics.ListAPIView):
    """GET /api/v1/heatmap/summary/?website= — totals across pages for a site.

    Returns one row per device with summed visits / clicks / max scroll so the
    dashboard header can show the site-wide picture before a page is chosen.
    """

    permission_classes = [IsTeamMember]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        qs = HeatmapPageStats.objects.for_team(request.user.active_team)
        qs = apply_segment_filters(qs, request)
        website = request.query_params.get("website")
        if website:
            qs = qs.filter(website_id=website)
        # Every alias is prefixed: Django refuses an annotation that shadows a
        # model field, and `visits`, `total_clicks` and `max_scroll_percent`
        # are all fields on this model. `.order_by()` clears the model's
        # default ordering, which would otherwise join the GROUP BY and give
        # one row per page instead of one per device.
        aggregated = (
            qs.values("device")
            .annotate(
                sum_visits=Sum("visits"),
                sum_clicks=Sum("total_clicks"),
                peak_scroll=Max("max_scroll_percent"),
            )
            .order_by()
        )
        return Response(
            {
                row["device"]: {
                    "visits": row["sum_visits"] or 0,
                    "total_clicks": row["sum_clicks"] or 0,
                    "max_scroll_percent": row["peak_scroll"] or 0,
                }
                for row in aggregated
            }
        )


class HeatmapSnapshotView(TeamScopedMixin, generics.RetrieveAPIView):
    """GET /api/v1/heatmap/snapshot/?website=&page_url=&device= — the backdrop.

    Returns the snapshot row for one page + device, or 404 when none has been
    captured. The dashboard treats a 404 (and any non-`ready` status) as "fall
    back to the live iframe", so this deliberately does not invent a placeholder.
    """

    permission_classes = [IsTeamMember]
    serializer_class = HeatmapSnapshotSerializer
    queryset = HeatmapPageSnapshot.objects.all()

    def get_object(self):
        qs = self.filter_queryset(self.get_queryset())
        website = self.request.query_params.get("website")
        if website:
            qs = qs.filter(website_id=website)
        page_url = self.request.query_params.get("page_url")
        if page_url:
            qs = qs.filter(page_url=normalize_page_url(page_url) or page_url)
        device = self.request.query_params.get("device")
        if device and device != "all":
            qs = qs.filter(device=device)
        # `captured_at` is null until a capture succeeds, and Postgres sorts
        # nulls first on a descending order — so a pending or failed row for
        # this page outranked the ready one and the dashboard showed "no
        # screenshot yet" next to a screenshot it already had.
        obj = qs.order_by(F("captured_at").desc(nulls_last=True)).first()
        if obj is None:
            raise NotFound("No snapshot captured for this page yet.")
        return obj


class HeatmapSnapshotImageView(TeamScopedMixin, generics.GenericAPIView):
    """GET /api/v1/heatmap/snapshots/<pk>/image/ — the PNG itself.

    Served through the API rather than MEDIA_URL on purpose: these are pictures
    of clients' pages and can contain pricing, staging or pre-launch content, so
    they go through the same team scoping as every other resource instead of
    sitting behind a guessable static path.
    """

    permission_classes = [IsTeamMember]
    queryset = HeatmapPageSnapshot.objects.all()

    def get(self, request, *args, **kwargs):
        snapshot = self.get_object()
        if snapshot.status != HeatmapPageSnapshot.Status.READY or not snapshot.image:
            raise NotFound("Snapshot image is not available.")
        try:
            handle = snapshot.image.open("rb")
        except (FileNotFoundError, OSError):
            # The row says ready but the file is gone (volume reset, manual
            # cleanup). Answer 404 so the dashboard falls back to the iframe
            # instead of rendering a broken image.
            logger.warning("Snapshot image missing on disk for %s", snapshot.pk)
            raise NotFound("Snapshot image is not available.")
        return FileResponse(handle, content_type="image/png")


class HeatmapSnapshotRefreshView(TeamScopedMixin, APIView):
    """POST /api/v1/heatmap/snapshot/refresh/ — recapture one page on demand.

    Queues a capture for {website, page_url, device} and returns 202. Human
    triggered, so it bypasses the freshness check the nightly sweep applies —
    but not the per-host budget, which the capture task still consults.
    """

    permission_classes = [IsTeamMember]

    def post(self, request):
        website_id = request.data.get("website")
        page_url = request.data.get("page_url")
        device = request.data.get("device") or "desktop"
        if not website_id or not page_url:
            return Response(
                {"detail": "website and page_url are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Team scoping: the caller may only capture their own team's sites.
        if not Website.objects.for_team(request.user.active_team).filter(
            pk=website_id
        ).exists():
            raise NotFound("Website not found.")

        # Answer now rather than queueing work that will only ever record
        # `unavailable`. The dashboard polls for ~36 seconds after this returns
        # 202, so on a deployment without Chromium the button span the whole
        # poll and then quietly gave up — indistinguishable from a capture that
        # was simply slow, and the single loudest "the heatmap is broken"
        # symptom. 503 says *why*, immediately.
        from apps.heatmap.capture import capture_available

        if not capture_available():
            return Response(
                {
                    "detail": (
                        "Screenshot capture is not enabled on this deployment. "
                        "Install Playwright and Chromium on the API and Celery "
                        "images to turn it on."
                    ),
                    "code": "capture_unavailable",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Capture the same key the heatmap is stored under, or the snapshot
        # lands on a row nothing reads.
        capture_page_snapshot.delay(
            str(website_id), normalize_page_url(page_url) or page_url, device
        )
        return Response(status=status.HTTP_202_ACCEPTED)
