from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.common.permissions import IsTeamMember
from apps.site_health.models import (
    FileManifest,
    PhpError,
    SecurityHeaderReport,
    SeoReport,
    SiteEvent,
    SiteScanState,
    VulnerabilityReport,
)
from apps.site_health.serializers import (
    PhpErrorIngestSerializer,
    PhpErrorSerializer,
    SecurityHeaderReportSerializer,
    SeoReportSerializer,
    SiteEventCreateSerializer,
    SiteEventSerializer,
    SiteScanStateSerializer,
    VulnerabilityReportSerializer,
    WpActivityIngestSerializer,
)
from apps.site_health.file_events import record_file_changes
from apps.site_health.wp_activity_auth import verify_signature
from apps.site_health.wp_activity_map import map_event
from apps.site_health.wp_activity_seq import check_sequence
from apps.site_health.wp_alerts import dispatch_for_site_event
from apps.site_health.wp_merge import merge_into_passive
from apps.websites.models import Website

logger = logging.getLogger(__name__)

# Categories where a passively-detected row may already exist for the same
# change. Users, content and commerce have no passive counterpart at all.
_MERGEABLE_CATEGORIES = (
    SiteEvent.Category.PLUGINS,
    SiteEvent.Category.THEMES,
    SiteEvent.Category.CORE,
)


def _csv(value: str | None) -> list[str]:
    """Split a comma-separated filter parameter into non-empty terms."""
    return [p.strip() for p in (value or "").split(",") if p.strip()]


def parse_date_only(value: str | None):
    """A bare YYYY-MM-DD as an aware datetime at midnight, or None.

    The filter bar sends dates, not timestamps, so `since=2026-08-01` has to
    work; parse_datetime returns None for those.
    """
    day = parse_date((value or "").strip()) if value else None
    if day is None:
        return None
    return timezone.make_aware(
        datetime.combine(day, datetime.min.time()), timezone.get_current_timezone()
    )


def _window_minutes(raw: str | None, default: int) -> int:
    """Parse a window like "30m", "2h" or a bare minute count.

    A bad value falls back to the default rather than erroring: this parameter
    comes from a URL somebody may have hand-edited, and the sensible response is
    a useful timeline, not a 400.
    """
    text = (raw or "").strip().lower()
    if not text:
        return default
    try:
        if text.endswith("h"):
            return max(1, int(float(text[:-1]) * 60))
        if text.endswith("m"):
            return max(1, int(float(text[:-1])))
        return max(1, int(float(text)))
    except ValueError:
        return default


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
    """The site's Change Log — passive detection and WP Connect on one timeline.

    Filterable by category, event type, actor, date range and a summary search,
    because once WordPress activity lands here an unfiltered 200-row slice is
    unusable: a busy WooCommerce site fills it with order transitions before
    anyone sees the plugin that broke the checkout.
    """

    serializer_class = SiteEventSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    MAX_ROWS = 500

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return SiteEvent.objects.none()

        qs = SiteEvent.objects.filter(
            website__team=team, website_id=self.kwargs["website_pk"]
        )
        params = self.request.query_params

        # Comma-separated so the UI can send a multi-select in one parameter.
        # An unrecognised value narrows to nothing rather than being dropped:
        # a typo must not silently widen the result set to the whole timeline.
        categories = _csv(params.get("category"))
        if categories:
            qs = qs.filter(category__in=categories)

        event_types = _csv(params.get("event_type"))
        if event_types:
            qs = qs.filter(event_type__in=event_types)

        actor = (params.get("actor") or "").strip()
        if actor:
            qs = qs.filter(actor__iexact=actor)

        since = parse_datetime(params.get("since") or "") or parse_date_only(
            params.get("since")
        )
        if since:
            qs = qs.filter(occurred_at__gte=since)

        until = parse_datetime(params.get("until") or "") or parse_date_only(
            params.get("until")
        )
        if until:
            qs = qs.filter(occurred_at__lte=until)

        search = (params.get("q") or "").strip()
        if search:
            qs = qs.filter(summary__icontains=search)

        return qs.order_by("-occurred_at")[: self.MAX_ROWS]


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


class WebsiteSecurityHeadersView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get(self, request, website_pk):
        team = request.user.active_team
        website = generics.get_object_or_404(Website, pk=website_pk, team=team)
        report, _ = SecurityHeaderReport.objects.get_or_create(website=website)
        return Response(SecurityHeaderReportSerializer(report).data)

    def post(self, request, website_pk):
        from apps.site_health.tasks import run_security_header_check
        team = request.user.active_team
        website = generics.get_object_or_404(Website, pk=website_pk, team=team)
        run_security_header_check.delay(str(website.pk))
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


class WpActivityThrottle(AnonRateThrottle):
    """Rate limit per site, not per IP.

    Every client posts from its own server, but they can share a host, a CDN
    egress or a NAT — so an IP-keyed limit lets one noisy WooCommerce site spend
    the budget of every other site behind the same address.
    """

    rate = "2000/hour"
    scope = "wp_activity"

    def get_cache_key(self, request, view):
        site_id = (request.META.get("HTTP_X_STACKSMONITOR_SITE") or "").strip()
        if site_id:
            return self.cache_format % {"scope": self.scope, "ident": site_id}
        return super().get_cache_key(request, view)


class WpActivityIngestView(APIView):
    """POST /api/wp-activity/ — WP Connect snippet v2 event push.

    Authenticated by an HMAC over the raw body, not by Origin/Referer: a
    server-side PHP POST sends neither, so the `PhpErrorIngestView` check would
    pass vacuously — tolerable for PHP warnings, not for a payload carrying
    usernames, email addresses and IPs.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [WpActivityThrottle]

    MAX_BODY_BYTES = 2 * 1024 * 1024
    # The snippet flushes 200 at a time. The cap is generous against that but
    # still bounded, so a runaway site cannot tie up a worker with one enormous
    # batch before the serializer has even looked at it.
    MAX_EVENTS_PER_BATCH = 1000

    def post(self, request):
        content_length = request.META.get("CONTENT_LENGTH")
        try:
            if content_length and int(content_length) > self.MAX_BODY_BYTES:
                return Response(status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        except (TypeError, ValueError):
            pass

        site_id = request.META.get("HTTP_X_STACKSMONITOR_SITE", "")
        try:
            website = Website.objects.get(site_id=site_id)
        except Website.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if not verify_signature(
            website.wp_sso_secret,
            request.META.get("HTTP_X_STACKSMONITOR_TIMESTAMP", ""),
            request.body,
            request.META.get("HTTP_X_STACKSMONITOR_SIGNATURE", ""),
        ):
            return Response(status=status.HTTP_403_FORBIDDEN)

        ser = WpActivityIngestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        events = data["events"]
        if len(events) > self.MAX_EVENTS_PER_BATCH:
            return Response(
                {"detail": f"Batch exceeds {self.MAX_EVENTS_PER_BATCH} events."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        resend_from = check_sequence(
            website.wp_connect_last_seq, [e["seq"] for e in events]
        )

        accepted = 0
        highest = website.wp_connect_last_seq
        for entry in events:
            # Advance the offset for EVERY row received, including ones we
            # choose not to store. The snippet deletes what it sent, so leaving
            # a skipped row out of `highest` would make the next batch look like
            # it had a gap and trigger a resend the snippet cannot satisfy.
            highest = max(highest, entry["seq"])

            mapped = map_event(entry["type"])
            # An unrecognised type means the site runs a newer snippet than this
            # backend — normal during rollout. Skip the row, keep the batch.
            if mapped is None:
                continue
            event_type, category, severity = mapped

            # A component change may already be on the timeline, detected
            # passively from asset versions. Claim that row instead of adding a
            # second one saying the same thing with a name attached.
            if category in _MERGEABLE_CATEGORIES and merge_into_passive(
                website,
                entry["details"],
                actor=entry["actor_login"],
                actor_wp_id=entry["actor_id"],
                actor_ip=entry["actor_ip"],
                sequence=entry["seq"],
            ):
                accepted += 1
                continue

            event, created = SiteEvent.objects.get_or_create(
                website=website,
                sequence=entry["seq"],
                defaults={
                    "event_type": event_type,
                    "category": category,
                    "severity": severity,
                    "source": SiteEvent.Source.WP_CONNECT,
                    "summary": entry["summary"],
                    "details": entry["details"],
                    "actor": entry["actor_login"],
                    "actor_wp_id": entry["actor_id"],
                    "actor_ip": entry["actor_ip"],
                    "object_type": entry["object_type"],
                    "object_id": entry["object_id"],
                    "occurred_at": entry["occurred_at"],
                },
            )
            if created:
                accepted += 1
                # Alerting is narrow by design (see wp_alerts): only the
                # handful of events worth interrupting someone for.
                dispatch_for_site_event(event)

        manifest = data.get("manifest")
        if manifest:
            self._store_manifest(website, manifest)

        website.wp_connect_version = data["snippet_version"]
        website.wp_connect_last_ack = timezone.now()
        website.wp_connect_last_seq = highest
        fields = ["wp_connect_version", "wp_connect_last_ack", "wp_connect_last_seq"]

        # Uptime evidence for sites whose firewall blocks our monitor: see
        # apps/monitors/evidence.py. A null status is stored as null, so a
        # failed loopback never leaves a stale "200" standing in for it.
        heartbeat = data.get("heartbeat")
        if heartbeat is not None:
            website.wp_connect_loopback_status = heartbeat["loopback_status"]
            website.wp_connect_loopback_ms = heartbeat["loopback_ms"]
            website.wp_connect_loopback_at = website.wp_connect_last_ack
            fields += [
                "wp_connect_loopback_status", "wp_connect_loopback_ms",
                "wp_connect_loopback_at",
            ]
        website.save(update_fields=fields)

        return Response(
            {"accepted": accepted, "resend_from": resend_from},
            status=status.HTTP_202_ACCEPTED,
        )

    @staticmethod
    def _store_manifest(website, slice_data):
        """Accumulate one walk slice, and diff it once the walk finishes.

        Slices merge into one row per walk_id and are only marked complete when
        the snippet says the walk finished — diffing a partial manifest would
        report every not-yet-walked file as removed.
        """
        manifest, _ = FileManifest.objects.get_or_create(
            website=website, walk_id=slice_data["walk_id"]
        )
        merged = dict(manifest.entries)
        merged.update(slice_data["entries"])
        manifest.entries = merged
        if slice_data["complete"]:
            manifest.is_complete = True
            manifest.walked_at = timezone.now()
        manifest.save(update_fields=["entries", "is_complete", "walked_at"])

        # Only a finished walk is worth diffing — a partial one would report
        # every not-yet-walked file as removed.
        if manifest.is_complete:
            record_file_changes(website, manifest)


class WebsiteTimelineView(APIView):
    """GET /api/v1/websites/{id}/timeline/?around=<iso>&window=30m

    Everything that happened around one moment, from every source Stacks Monitor
    already holds: WordPress activity, script changes, PHP errors and failed
    monitor checks, interleaved newest-first.

    This is the reason the activity log is worth building rather than bought.
    An activity log alone answers "what changed"; a monitor alone answers "when
    did it break". Only the join answers the question an agency actually has at
    14:32 on a Tuesday — *the site went down; here is the plugin someone updated
    a minute earlier, who did it, and the three fatals it threw.* A vendor with
    only a WordPress plugin cannot produce it, because they do not hold the
    uptime data.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    DEFAULT_WINDOW_MINUTES = 30
    # One request must not be able to scan a year of checks.
    MAX_WINDOW_MINUTES = 1440
    MAX_ENTRIES = 200

    def get(self, request, website_pk):
        team = request.user.active_team
        website = generics.get_object_or_404(Website, pk=website_pk, team=team)

        anchor = parse_datetime(request.query_params.get("around") or "") or timezone.now()
        minutes = _window_minutes(
            request.query_params.get("window"), self.DEFAULT_WINDOW_MINUTES
        )
        minutes = min(minutes, self.MAX_WINDOW_MINUTES)
        start = anchor - timedelta(minutes=minutes)
        end = anchor + timedelta(minutes=minutes)

        entries: list[dict] = []

        for event in SiteEvent.objects.filter(
            website=website, occurred_at__gte=start, occurred_at__lte=end
        )[: self.MAX_ENTRIES]:
            entries.append({
                "kind": "site_event",
                "at": event.occurred_at,
                "title": event.summary,
                "severity": event.severity,
                "category": event.category,
                "actor": event.actor,
                "actor_ip": event.actor_ip,
                "source": event.source,
            })

        for error in PhpError.objects.filter(
            website=website, captured_at__gte=start, captured_at__lte=end
        )[: self.MAX_ENTRIES]:
            entries.append({
                "kind": "php_error",
                "at": error.captured_at,
                "title": error.message[:300],
                "severity": error.level,
                "file": error.file,
                "line": error.line,
            })

        # Only failures. An up check is the absence of news, and one every 30
        # seconds would bury everything else on the timeline.
        from apps.monitors.models import MonitorCheck

        for check in MonitorCheck.objects.filter(
            monitor__website=website,
            checked_at__gte=start,
            checked_at__lte=end,
            status__in=["down", "degraded", "blocked"],
        ).select_related("monitor")[: self.MAX_ENTRIES]:
            entries.append({
                "kind": "monitor_check",
                "at": check.checked_at,
                "title": f"{check.monitor.name}: {check.status}",
                "status": check.status,
                "severity": "critical" if check.status == "down" else "warning",
                "status_code": check.status_code,
                "error_message": check.error_message[:300],
            })

        from apps.scripts.models import ScriptChange

        for change in ScriptChange.objects.filter(
            website=website, created_at__gte=start, created_at__lte=end
        )[: self.MAX_ENTRIES]:
            entries.append({
                "kind": "script_change",
                "at": change.created_at,
                "title": change.description[:300],
                "severity": change.severity,
                "change_type": change.change_type,
            })

        entries.sort(key=lambda e: e["at"], reverse=True)
        return Response({
            "around": anchor,
            "window_minutes": minutes,
            "entries": entries[: self.MAX_ENTRIES],
        })
