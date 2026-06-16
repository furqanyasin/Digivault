from __future__ import annotations

import logging

from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsTeamMember
from apps.site_health.models import PhpError, SeoReport, SiteEvent, SiteScanState, VulnerabilityReport
from apps.site_health.serializers import (
    PhpErrorIngestSerializer,
    PhpErrorSerializer,
    SeoReportSerializer,
    SiteEventCreateSerializer,
    SiteEventSerializer,
    SiteScanStateSerializer,
    VulnerabilityReportSerializer,
)
from apps.websites.models import Website

logger = logging.getLogger(__name__)


class PhpErrorIngestView(APIView):
    """POST /api/php-errors/ — public, authenticated only by site_id."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        ser = PhpErrorIngestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            website = Website.objects.get(site_id=ser.validated_data["site_id"])
        except Website.DoesNotExist:
            return Response({"detail": "Unknown site_id."}, status=status.HTTP_404_NOT_FOUND)

        # Domain-binding: the request must originate from the registered domain,
        # mirroring the main ingest endpoint. site_id is public (embedded in
        # page HTML), so this stops a third party injecting PHP errors.
        origin = request.META.get("HTTP_ORIGIN") or request.META.get("HTTP_REFERER", "")
        if origin and website.domain:
            from urllib.parse import urlparse
            origin_host = urlparse(origin).netloc.lower().removeprefix("www.")
            site_host = website.domain.lower().removeprefix("www.").removeprefix("https://").removeprefix("http://").split("/")[0]
            if origin_host and site_host and origin_host != site_host:
                return Response(status=status.HTTP_403_FORBIDDEN)

        errors = ser.validated_data.get("errors", [])
        for err in errors:
            PhpError.objects.create(
                website=website,
                level=err.get("level", "error"),
                message=err.get("message", ""),
                file=err.get("file", ""),
                line=err.get("line"),
                url=err.get("url", ""),
                raw=err.get("raw", ""),
            )

        return Response({"accepted": len(errors)}, status=status.HTTP_202_ACCEPTED)


class WebsitePhpErrorListView(generics.ListAPIView):
    serializer_class = PhpErrorSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return PhpError.objects.none()
        return (
            PhpError.objects
            .filter(website__team=team, website_id=self.kwargs["website_pk"])
            .order_by("-captured_at")[:200]
        )


class WebsiteSiteEventListView(generics.ListAPIView):
    serializer_class = SiteEventSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return SiteEvent.objects.none()
        return (
            SiteEvent.objects
            .filter(website__team=team, website_id=self.kwargs["website_pk"])
            .order_by("-occurred_at")[:200]
        )


class WebsiteSiteEventCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, website_pk):
        team = request.user.active_team
        website = generics.get_object_or_404(Website, pk=website_pk, team=team)

        ser = SiteEventCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        event = SiteEvent.objects.create(
            website=website,
            event_type=d["event_type"],
            summary=d["summary"],
            details=d.get("details", {}),
            actor=d.get("actor", ""),
            severity=d.get("severity", SiteEvent.Severity.INFO),
            occurred_at=d.get("occurred_at") or timezone.now(),
        )
        return Response(SiteEventSerializer(event).data, status=status.HTTP_201_CREATED)


class WebsiteVulnerabilityListView(generics.ListAPIView):
    serializer_class = VulnerabilityReportSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return VulnerabilityReport.objects.none()
        return VulnerabilityReport.objects.filter(
            website__team=team, website_id=self.kwargs["website_pk"]
        )


class WebsiteSecurityScanView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get(self, request, website_pk):
        team = request.user.active_team
        website = generics.get_object_or_404(Website, pk=website_pk, team=team)
        state, _ = SiteScanState.objects.get_or_create(website=website)
        return Response(SiteScanStateSerializer(state).data)

    def post(self, request, website_pk):
        from apps.site_health.tasks import run_security_scan
        team = request.user.active_team
        website = generics.get_object_or_404(Website, pk=website_pk, team=team)
        run_security_scan.delay(str(website.pk))
        return Response({"queued": True}, status=status.HTTP_202_ACCEPTED)


class WebsiteSeoView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get(self, request, website_pk):
        team = request.user.active_team
        website = generics.get_object_or_404(Website, pk=website_pk, team=team)
        report, _ = SeoReport.objects.get_or_create(website=website)
        data = SeoReportSerializer(report).data
        data["seo_scan_interval_days"] = website.seo_scan_interval_days
        return Response(data)

    def post(self, request, website_pk):
        from apps.site_health.tasks import run_seo_check
        team = request.user.active_team
        website = generics.get_object_or_404(Website, pk=website_pk, team=team)
        run_seo_check.delay(str(website.pk))
        return Response({"queued": True}, status=status.HTTP_202_ACCEPTED)

    def patch(self, request, website_pk):
        team = request.user.active_team
        website = generics.get_object_or_404(Website, pk=website_pk, team=team)
        valid = {c[0] for c in Website.SEO_INTERVAL_CHOICES}
        try:
            interval = int(request.data.get("seo_scan_interval_days"))
        except (TypeError, ValueError):
            return Response({"detail": "Invalid interval."}, status=status.HTTP_400_BAD_REQUEST)
        if interval not in valid:
            return Response({"detail": "Invalid interval."}, status=status.HTTP_400_BAD_REQUEST)
        website.seo_scan_interval_days = interval
        website.save(update_fields=["seo_scan_interval_days"])
        return Response({"seo_scan_interval_days": interval})
