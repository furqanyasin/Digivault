import logging

from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.common.mixins import TeamScopedMixin
from apps.common.pagination import StandardPagination
from apps.common.permissions import IsTeamMember
from apps.heatmap.models import HeatmapActivity, HeatmapPageStats
from apps.heatmap.serializers import (
    HeatmapCellSerializer,
    HeatmapIngestSerializer,
    HeatmapPageSerializer,
)
from apps.heatmap.tasks import process_heatmap_payload
from apps.websites.models import Website

logger = logging.getLogger(__name__)


class HeatmapIngestThrottle(AnonRateThrottle):
    """Per-site_id rate limit so one site cannot starve others behind one IP."""

    rate = "2000/day"
    scope = "heatmap_ingest"

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

        origin = request.META.get("HTTP_ORIGIN") or request.META.get("HTTP_REFERER", "")
        if origin and website.domain:
            from urllib.parse import urlparse

            origin_host = urlparse(origin).netloc.lower().removeprefix("www.")
            site_host = (
                website.domain.lower()
                .removeprefix("www.")
                .removeprefix("https://")
                .removeprefix("http://")
                .split("/")[0]
            )
            if origin_host and site_host and origin_host != site_host:
                logger.warning(
                    "Heatmap ingest domain mismatch: site_id=%s origin=%s registered=%s",
                    data["site_id"], origin_host, site_host,
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


class HeatmapPageListView(TeamScopedMixin, generics.ListAPIView):
    """GET /api/v1/heatmap/pages/ — pages with heatmap data for this team.

    Query params: ?website=<website_id>&device=desktop&page=...
    """

    permission_classes = [IsTeamMember]
    serializer_class = HeatmapPageSerializer
    pagination_class = StandardPagination
    queryset = HeatmapPageStats.objects.all()

    def get_queryset(self):
        qs = super().get_queryset()
        qs = apply_segment_filters(qs, self.request)
        website = self.request.query_params.get("website")
        if website:
            qs = qs.filter(website_id=website)
        return qs


class HeatmapCellListView(TeamScopedMixin, generics.ListAPIView):
    """GET /api/v1/heatmap/activity/?website=&page_url=&kind=click — cells.

    Returns the aggregated percentage cells for one page + kind (click/move/
    scroll), optionally filtered by device, ready to render as a heatmap
    overlay. Not paginated: one page's cells are bounded by the 100x100 grid.
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
            qs = qs.filter(page_url=page_url)
        kind = self.request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        return qs.order_by("x", "y")


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
        summary = {}
        for stat in qs:
            key = stat.device
            entry = summary.setdefault(
                key, {"visits": 0, "total_clicks": 0, "max_scroll_percent": 0}
            )
            entry["visits"] += stat.visits
            entry["total_clicks"] += stat.total_clicks
            entry["max_scroll_percent"] = max(
                entry["max_scroll_percent"], stat.max_scroll_percent
            )
        return Response(summary)
