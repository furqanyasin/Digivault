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


def _extract_script_urls(html: str) -> list[str]:
    """Extract external script URLs from raw HTML — both static tags and common inline loaders.

    Handles:
    - Static <script src="..."> tags
    - Google Tag Manager (container ID in function call)
    - Meta / Facebook Pixel (fbevents.js loader pattern)
    - Hotjar (hjid/hjsv settings object)
    - Microsoft Clarity (tag ID in IIFE args)
    - HubSpot (hs-scripts.com ID)
    - Generic https://*.js literals inside inline scripts
    """
    import re
    seen: set[str] = set()
    urls: list[str] = []

    def add(url: str) -> None:
        url = url.strip()
        if url.startswith("//"):
            url = "https:" + url
        if url and url not in seen:
            seen.add(url)
            urls.append(url)

    # 1. Static <script src="..."> tags
    for src in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE):
        add(src)

    # 2. Google Tag Manager — GTM container ID in IIFE args or any quoted literal
    for gtm_id in re.findall(r"""['"](GTM-[A-Z0-9]+)['"]""", html, re.IGNORECASE):
        add(f"https://www.googletagmanager.com/gtm.js?id={gtm_id}")

    # 2b. Google Analytics 4 — gtag/js URL (no .js extension, not caught by regex #7)
    # Covers both static <script src="...gtag/js?id=G-..."> and inline references.
    for ga_id in re.findall(r'googletagmanager\.com/gtag/js\?id=([A-Z0-9_-]+)', html, re.IGNORECASE):
        add(f"https://www.googletagmanager.com/gtag/js?id={ga_id}")
    # Also catch bare measurement IDs in gtag('config', 'G-XXXX') calls
    for ga_id in re.findall(r"""gtag\s*\(\s*['"]config['"]\s*,\s*['"]([A-Z0-9_-]+)['"]""", html, re.IGNORECASE):
        add(f"https://www.googletagmanager.com/gtag/js?id={ga_id}")

    # 3. Meta / Facebook Pixel — fbevents.js injected by the loader IIFE
    if re.search(r'connect\.facebook\.net', html, re.IGNORECASE):
        add("https://connect.facebook.net/en_US/fbevents.js")

    # 4. Hotjar — reconstruct from hjid / hjsv settings object
    m = re.search(r'hjid\s*:\s*(\d+).*?hjsv\s*:\s*(\d+)', html, re.DOTALL)
    if m:
        add(f"https://static.hotjar.com/c/hotjar-{m.group(1)}.js?sv={m.group(2)}")

    # 5. Microsoft Clarity — tag ID passed as 5th IIFE argument
    m = re.search(r'"clarity"\s*,\s*"script"\s*,\s*"([a-z0-9]+)"', html, re.IGNORECASE)
    if m:
        add(f"https://www.clarity.ms/tag/{m.group(1)}")

    # 6. HubSpot — hs-scripts.com/<id>.js (catches protocol-relative or https)
    for hub_id in re.findall(r'hs-scripts\.com/(\d+)', html, re.IGNORECASE):
        add(f"https://js.hs-scripts.com/{hub_id}.js")

    # 7. WhatConverts / generic: quoted https:// .js literals inside inline scripts
    for url in re.findall(r'''["'](https://[a-zA-Z0-9._\-]+/[^"'<>\s]*?\.js(?:\?[^"'<>\s]*)?)["']''', html):
        add(url)

    return urls


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

        import secrets as _secrets
        import requests as _requests

        url = website.domain if website.domain.startswith("http") else f"https://{website.domain}"
        bust = _secrets.token_hex(8)
        fetch_url = f"{url}{'&' if '?' in url else '?'}_dvv={bust}"

        _BROWSER_HEADERS = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache, no-store",
            "Pragma": "no-cache",
        }

        try:
            resp = _requests.get(fetch_url, headers=_BROWSER_HEADERS, timeout=20, allow_redirects=True)
            resp.raise_for_status()
            html = resp.text
            # Strip the cache-buster from the stored page URL.
            final_url = resp.url.replace(f"_dvv={bust}", "").rstrip("?&")
        except _requests.HTTPError as e:
            return Response({"detail": f"Could not fetch the page (HTTP {e.response.status_code})."}, status=400)
        except Exception as e:
            logger.warning("Scan fetch failed for website %s: %s", website.pk, e)
            return Response({"detail": "Could not reach the site. Check the domain is correct and publicly accessible."}, status=400)

        script_urls = _extract_script_urls(html)

        if not script_urls:
            return Response({"detail": "No external scripts found on the page.", "count": 0})

        scripts = [
            {"src": src, "location": "unknown", "async": False, "defer": False, "inline": False}
            for src in script_urls
        ]

        from apps.scripts.tasks import process_ingest_payload
        from apps.site_health.tasks import run_security_scan

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
        import secrets as _secrets
        import requests as _requests

        website = self.get_object()
        url = website.domain if website.domain.startswith("http") else f"https://{website.domain}"
        marker = f'data-site="{website.site_id}"'

        # Append a random cache-buster so CDNs/proxies return a fresh response.
        bust = _secrets.token_hex(8)
        fetch_url = f"{url}{'&' if '?' in url else '?'}_dvv={bust}"

        try:
            resp = _requests.get(
                fetch_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; Digivault-Verifier/1.0)",
                    "Cache-Control": "no-cache, no-store",
                    "Pragma": "no-cache",
                },
                timeout=15,
                allow_redirects=True,
            )
            html = resp.text
        except Exception as e:
            logger.warning("Snippet verify failed for website %s: %s", website.pk, e)
            return Response({"verified": False, "error": "Could not reach the site. Check the domain is correct and publicly accessible."})

        if marker in html:
            return Response({"verified": True})
        return Response({
            "verified": False,
            "error": f"Snippet not found on {url}. Checked {len(html):,} bytes of HTML.",
        })
