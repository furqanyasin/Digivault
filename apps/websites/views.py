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
from apps.websites.models import Website, WebsiteAssignment
from apps.audit.services import AuditService
from apps.audit.models import ActivityLog
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


_MANAGER_ROLES = {"owner", "manager"}


def _user_role(user, team) -> str:
    from apps.accounts.models import TeamMembership

    try:
        return TeamMembership.objects.get(user=user, team=team).role
    except TeamMembership.DoesNotExist:
        return "viewer"


def _restrict_to_assignments(qs, request):
    """Non-managers with at least one website assignment see only those sites.

    Managers/owners — and members with no assignments at all (backwards
    compatible default) — see the whole team.
    """
    team = request.user.active_team
    if team is None:
        return qs
    if _user_role(request.user, team) in _MANAGER_ROLES:
        return qs
    assigned_ids = list(
        WebsiteAssignment.objects.filter(
            user=request.user, website__team=team
        ).values_list("website_id", flat=True)
    )
    if not assigned_ids:
        return qs
    return qs.filter(pk__in=assigned_ids)


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
        from apps.scripts.tasks import _internal_hosts

        qs = _restrict_to_assignments(super().get_queryset(), self.request)
        # Exclude Digivault's own infra scripts (the tracking snippet etc.) so the
        # dashboard counts match the website detail page, which hides them.
        internal_q = Q()
        for host in _internal_hosts():
            internal_q |= Q(scripts__src_url__icontains=host)
        not_internal = ~internal_q

        return qs.annotate(
            script_count=Count(
                "scripts",
                filter=Q(scripts__is_active=True) & not_internal,
            ),
            # Only unreviewed unknowns count — approving/ignoring clears them,
            # matching the website detail page's "Unknown scripts" KPI.
            unknown_script_count=Count(
                "scripts",
                filter=Q(
                    scripts__is_active=True,
                    scripts__provider="unknown",
                    scripts__review_status="pending",
                ) & not_internal,
            ),
        ).select_related("team", "notification_channel", "client", "domain_info").prefetch_related("monitors")

    def get_serializer_class(self):
        if self.action == "create":
            return WebsiteCreateSerializer
        return WebsiteSerializer

    # Digivault role → WordPress role for one-click wp-admin login.
    _WP_ROLE_MAP = {
        "owner": "administrator",
        "manager": "administrator",
        "developer": "editor",
    }

    @action(detail=True, methods=["post"], url_path="wp-sso-secret")
    def wp_sso_secret(self, request, pk=None):
        """Generate (or rotate) the shared secret for the Digivault Connect
        WordPress plugin. Managers/owners only. Rotating invalidates all
        previously issued login links."""
        import secrets as _secrets

        website = self.get_object()
        team = request.user.active_team
        if _user_role(request.user, team) not in _MANAGER_ROLES:
            return Response(
                {"detail": "Only managers can manage the WP login secret."},
                status=status.HTTP_403_FORBIDDEN,
            )
        secret = _secrets.token_urlsafe(32)
        Website.objects.filter(pk=website.pk).update(wp_sso_secret=secret)
        website.wp_sso_secret = secret
        AuditService.log_request(
            request, ActivityLog.Action.WEBSITE_WP_SSO_SECRET_ROTATED,
            description=f"Generated WP SSO secret for '{website.domain}'",
            resource_type="website", resource_id=website.pk,
            metadata={"website_id": str(website.pk)},
        )
        # The user pastes `snippet` into WPCode/Code Snippets (same tool as the
        # tracking script); the raw secret is returned only for reference.
        return Response({"secret": secret, "snippet": website.wp_sso_snippet})

    @action(detail=True, methods=["post"], url_path="wp-login")
    def wp_login(self, request, pk=None):
        """Issue a signed, single-use, 2-minute wp-admin login URL for the
        current user, role-mapped from their team role."""
        import base64
        import hashlib
        import hmac as _hmac
        import json as _json
        import time
        import uuid

        website = self.get_object()
        team = request.user.active_team

        wp_role = self._WP_ROLE_MAP.get(_user_role(request.user, team))
        if wp_role is None:
            return Response(
                {"detail": "Your role does not permit WP admin login."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not website.wp_sso_secret:
            return Response(
                {"detail": "WP login is not set up for this website yet."},
                status=status.HTTP_409_CONFLICT,
            )

        payload = {
            "email": request.user.email,
            "name": f"{request.user.first_name} {request.user.last_name}".strip()
            or request.user.email,
            "role": wp_role,
            "exp": int(time.time()) + 120,
            "jti": uuid.uuid4().hex,
        }
        raw = _json.dumps(payload, separators=(",", ":")).encode()
        payload_b64 = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        sig = _hmac.new(
            website.wp_sso_secret.encode(), payload_b64.encode(), hashlib.sha256
        ).hexdigest()

        domain = website.domain
        if not domain.startswith(("http://", "https://")):
            domain = f"https://{domain}"
        url = f"{domain.rstrip('/')}/wp-json/digivault/v1/sso?p={payload_b64}&s={sig}"

        AuditService.log_request(
            request, ActivityLog.Action.WEBSITE_WP_LOGIN,
            description=f"Issued wp-admin login link for '{website.domain}' as {wp_role}",
            resource_type="website", resource_id=website.pk,
            metadata={"website_id": str(website.pk), "wp_role": wp_role},
        )
        return Response({"url": url, "expires_in": 120, "wp_role": wp_role})

    @action(detail=True, methods=["get", "put"], url_path="assignments")
    def assignments(self, request, pk=None):
        """GET: users assigned to this website. PUT {"user_ids": [...]}:
        replace the assignment set (managers/owners only)."""
        website = self.get_object()
        team = request.user.active_team

        if request.method == "PUT":
            if _user_role(request.user, team) not in _MANAGER_ROLES:
                return Response(
                    {"detail": "Only managers can change website assignments."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            from apps.accounts.models import TeamMembership

            user_ids = request.data.get("user_ids")
            if not isinstance(user_ids, list):
                return Response(
                    {"detail": "user_ids must be a list."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            member_ids = set(
                str(uid)
                for uid in TeamMembership.objects.filter(team=team).values_list(
                    "user_id", flat=True
                )
            )
            invalid = [uid for uid in user_ids if str(uid) not in member_ids]
            if invalid:
                return Response(
                    {"detail": "Some users are not members of this team."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            WebsiteAssignment.objects.filter(website=website).exclude(
                user_id__in=user_ids
            ).delete()
            for uid in user_ids:
                WebsiteAssignment.objects.get_or_create(
                    website=website, user_id=uid,
                    defaults={"assigned_by": request.user},
                )
            AuditService.log_request(
                request, ActivityLog.Action.WEBSITE_UPDATED,
                description=f"Updated user assignments on '{website.domain}' ({len(user_ids)} user(s))",
                resource_type="website", resource_id=website.pk,
                metadata={"website_id": str(website.pk), "assigned_user_ids": [str(u) for u in user_ids]},
            )

        from apps.accounts.models import TeamMembership

        def _user_row(user):
            return {
                "user_id": str(user.id),
                "email": user.email,
                "name": f"{user.first_name} {user.last_name}".strip() or user.email,
            }

        rows = WebsiteAssignment.objects.filter(website=website).select_related("user")
        memberships = TeamMembership.objects.filter(team=team).select_related("user")
        return Response({
            "assigned": [_user_row(a.user) for a in rows],
            "members": [
                {**_user_row(m.user), "role": m.role} for m in memberships
            ],
            "can_edit": _user_role(request.user, team) in _MANAGER_ROLES,
        })

    def list(self, request, *args, **kwargs):
        # Self-heal status/health for the listed sites so the dashboard reflects
        # reality without the user opening each site. One recalc per site — it
        # writes status and health together. (The nightly
        # websites.recalculate_all_health sweep is the backstop; revisit this
        # per-request heal if a team ever has enough sites to feel it.)
        for w in self.filter_queryset(self.get_queryset()):
            w.recalculate_health_score()
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        # Self-heal a stale status/health on view — e.g. a site left 'critical'
        # after its changes were cleared but the status wasn't recomputed.
        obj = self.get_object()
        obj.recalculate_health_score()
        obj = self.get_queryset().get(pk=obj.pk)  # re-read with annotations + fresh status
        return Response(self.get_serializer(obj).data)

    def perform_create(self, serializer):
        website = serializer.save(team=self.request.user.active_team)
        AuditService.log_request(
            self.request, ActivityLog.Action.WEBSITE_CREATED,
            description=f"Added website '{website.domain}'",
            resource_type="website", resource_id=website.pk,
        )
        return website

    def perform_update(self, serializer):
        website = serializer.save()
        AuditService.log_request(
            self.request, ActivityLog.Action.WEBSITE_UPDATED,
            description=f"Updated website '{website.domain}'",
            resource_type="website", resource_id=website.pk,
        )

    def perform_destroy(self, instance):
        AuditService.log_request(
            self.request, ActivityLog.Action.WEBSITE_DELETED,
            description=f"Deleted website '{instance.domain}'",
            resource_type="website", resource_id=instance.pk,
        )
        instance.delete()

    @action(detail=True, methods=["get"], url_path="health")
    def health(self, request, pk=None):
        """Aggregated Health Center snapshot for one website (Phase 2.1)."""
        from apps.websites.health import build_health_snapshot

        website = self.get_object()
        return Response(build_health_snapshot(website))

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
        AuditService.log_request(
            request, ActivityLog.Action.WEBSITE_SNIPPET_REGENERATED,
            description=f"Regenerated tracking snippet for '{website.domain}'",
            resource_type="website", resource_id=website.pk,
        )
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

        from apps.common.ssrf import BlockedURLError, assert_public_url
        try:
            assert_public_url(url)
        except BlockedURLError as e:
            return Response({"detail": str(e)}, status=400)

        _BROWSER_HEADERS = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
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

        # Detect the CMS / site builder from the fetched page and persist it.
        # Done before the script check so platform is set even for pages with
        # no external scripts.
        from apps.websites.platform_detect import detect_platform

        detected = detect_platform(html, dict(resp.headers))
        if detected and detected != website.platform:
            website.platform = detected
            website.save(update_fields=["platform"])

        script_urls = _extract_script_urls(html)

        if not script_urls:
            return Response({
                "detail": "No external scripts found on the page.",
                "count": 0,
                "platform": website.platform,
            })

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

        from apps.site_health.tasks import run_seo_check
        run_seo_check.apply_async(args=[str(website.pk)], countdown=5)

        AuditService.log_request(
            request, ActivityLog.Action.WEBSITE_SCAN_TRIGGERED,
            description=f"Triggered scan for '{website.domain}'",
            resource_type="website", resource_id=website.pk,
        )
        return Response({
            "detail": f"Scan queued — found {len(scripts)} scripts.",
            "count": len(scripts),
            "platform": website.platform,
        })

    @action(detail=True, methods=["post"], url_path="verify-snippet")
    def verify_snippet(self, request, pk=None):
        """Fetch the website URL and confirm the tracking snippet is present."""
        import secrets as _secrets
        import requests as _requests

        website = self.get_object()
        url = website.domain if website.domain.startswith("http") else f"https://{website.domain}"
        marker = f'data-site="{website.site_id}"'

        from apps.common.ssrf import BlockedURLError, assert_public_url
        try:
            assert_public_url(url)
        except BlockedURLError as e:
            return Response({"verified": False, "error": str(e)})

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
            AuditService.log_request(
                request, ActivityLog.Action.WEBSITE_SNIPPET_VERIFIED,
                description=f"Snippet verified for '{website.domain}'",
                resource_type="website", resource_id=website.pk,
            )
            return Response({"verified": True})
        return Response({
            "verified": False,
            "error": f"Snippet not found on {url}. Checked {len(html):,} bytes of HTML.",
        })

    @action(detail=False, methods=["get"], url_path="expiring-domains")
    def expiring_domains(self, request):
        from datetime import timedelta
        from django.utils import timezone
        days = int(request.query_params.get("days", 30))
        threshold = timezone.now() + timedelta(days=days)
        qs = (
            self.get_queryset()
            .select_related("domain_info")
            .filter(
                domain_info__expires_at__isnull=False,
                domain_info__expires_at__lte=threshold,
            )
            .order_by("domain_info__expires_at")
        )
        data = [
            {
                "id": str(w.id),
                "name": w.name,
                "domain": w.domain,
                "days_until_expiry": w.domain_info.domain_days_until_expiry,
            }
            for w in qs
        ]
        return Response(data)

    @action(detail=False, methods=["get"], url_path="expiring-ssl")
    def expiring_ssl(self, request):
        from datetime import timedelta
        from django.utils import timezone
        days = int(request.query_params.get("days", 14))
        threshold = timezone.now() + timedelta(days=days)
        qs = (
            self.get_queryset()
            .select_related("domain_info")
            .filter(
                domain_info__ssl_expires_at__isnull=False,
                domain_info__ssl_expires_at__lte=threshold,
            )
            .order_by("domain_info__ssl_expires_at")
        )
        data = [
            {
                "id": str(w.id),
                "name": w.name,
                "domain": w.domain,
                "days_until_expiry": w.domain_info.ssl_days_until_expiry,
            }
            for w in qs
        ]
        return Response(data)

    @action(detail=False, methods=["get"], url_path="expiring-hosting")
    def expiring_hosting(self, request):
        from datetime import timedelta
        from django.utils import timezone
        days = int(request.query_params.get("days", 30))
        threshold = timezone.now() + timedelta(days=days)
        qs = (
            self.get_queryset()
            .select_related("domain_info")
            .filter(
                domain_info__hosting_expires_at__isnull=False,
                domain_info__hosting_expires_at__lte=threshold,
            )
            .order_by("domain_info__hosting_expires_at")
        )
        data = [
            {
                "id": str(w.id),
                "name": w.name,
                "domain": w.domain,
                "days_until_expiry": w.domain_info.hosting_days_until_expiry,
            }
            for w in qs
        ]
        return Response(data)
