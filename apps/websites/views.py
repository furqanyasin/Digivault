import logging

from django.db.models import Count, Q
from rest_framework import generics, permissions, status

logger = logging.getLogger(__name__)
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from apps.common.mixins import TeamScopedMixin
from apps.common.permissions import IsTeamMember, RolePermission
from apps.websites.models import Website
from apps.site_health.models import SiteScanState
from apps.site_health.serializers import SiteScanStateSerializer
from apps.websites.serializers import (
    SnippetInstructionSerializer,
    WebsiteCreateSerializer,
    WebsiteSerializer,
)


class WebsiteViewSet(TeamScopedMixin, ModelViewSet):
    """
    /api/v1/websites/
    /api/v1/websites/<pk>/
    /api/v1/websites/<pk>/snippet/
    /api/v1/websites/<pk>/regenerate-snippet/
    """

    queryset = Website.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.annotate(
            script_count=Count("scripts", filter=Q(scripts__is_active=True)),
            unknown_script_count=Count(
                "scripts",
                filter=Q(scripts__is_active=True, scripts__provider="unknown"),
            ),
        ).select_related("team")

    def get_serializer_class(self):
        if self.action == "create":
            return WebsiteCreateSerializer
        return WebsiteSerializer

    def perform_create(self, serializer):
        serializer.save(team=self.request.user.active_team)

    @action(detail=True, methods=["get"], url_path="snippet")
    def snippet(self, request, pk=None):
        """Return snippet HTML and platform-specific installation instructions."""
        website = self.get_object()
        data = SnippetInstructionSerializer(website.snippet_instructions).data
        return Response(data)

    @action(detail=True, methods=["post"], url_path="regenerate-snippet")
    def regenerate_snippet(self, request, pk=None):
        """Issue a new site_id, invalidating the old snippet immediately."""
        website = self.get_object()
        new_id = website.regenerate_site_id()
        return Response(
            {"site_id": new_id, "snippet_html": website.snippet_html},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get", "post"], url_path="scan")
    def scan(self, request, pk=None):
        """GET: return current scan state. POST: trigger a new scan."""
        website = self.get_object()

        if request.method == "GET":
            state, _ = SiteScanState.objects.get_or_create(website=website)
            return Response(SiteScanStateSerializer(state).data)

        import re
        import urllib.request, urllib.error

        url = website.domain if website.domain.startswith("http") else f"https://{website.domain}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Digivault-Scanner/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read(1_500_000).decode("utf-8", errors="ignore")
                final_url = resp.geturl()
        except urllib.error.HTTPError as e:
            return Response({"detail": f"Could not fetch the page (HTTP {e.code})."}, status=400)
        except Exception as e:
            logger.warning("Scan fetch failed for website %s: %s", website.pk, e)
            return Response({"detail": "Could not reach the site. Check the domain is correct and publicly accessible."}, status=400)

        # Extract external script src values
        src_pattern = re.compile(r'<script[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
        scripts = [
            {"src": src, "location": "head", "async": False, "defer": False, "inline": False}
            for src in dict.fromkeys(src_pattern.findall(html))  # deduplicate, preserve order
        ]

        if not scripts:
            return Response({"detail": "No external scripts found on the page.", "count": 0})

        from apps.scripts.tasks import process_ingest_payload
        from apps.site_health.tasks import run_security_scan
        from apps.site_health.models import SiteScanState

        payload = {
            "page_url": final_url,
            "scripts": scripts,
            "user_agent": "Digivault-Scanner/1.0",
            "snippet_version": "server-scan",
        }
        process_ingest_payload.delay(website.site_id, payload)

        # Mark as running immediately so the UI can show progress
        state, _ = SiteScanState.objects.get_or_create(website=website)
        state.scan_status = "running"
        state.error = ""
        state.save(update_fields=["scan_status", "error"])

        run_security_scan.apply_async(args=[str(website.pk)], countdown=5)

        return Response({"detail": f"Scan queued — found {len(scripts)} scripts.", "count": len(scripts)})

    @action(detail=True, methods=["post"], url_path="verify-snippet")
    def verify_snippet(self, request, pk=None):
        """Fetch the website URL and confirm the tracking snippet is present."""
        import urllib.request, urllib.error

        website = self.get_object()
        url = website.domain if website.domain.startswith("http") else f"https://{website.domain}"
        marker = f'data-site="{website.site_id}"'

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Digivault-Verifier/1.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read(1_500_000).decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as e:
            return Response({"verified": False, "error": f"Could not fetch the page (HTTP {e.code})."})
        except Exception as e:
            logger.warning("Snippet verify failed for website %s: %s", website.pk, e)
            return Response({"verified": False, "error": "Could not reach the site. Check the domain is correct and publicly accessible."})

        if marker in html:
            return Response({"verified": True})
        return Response({
            "verified": False,
            "error": f"Snippet not found on {url}. Checked {len(html):,} bytes of HTML.",
        })
