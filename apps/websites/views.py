import logging
import re
from html import unescape
from urllib.parse import parse_qs

from django.conf import settings
from django.db.models import Count, Q
from rest_framework import permissions, status
from rest_framework.throttling import UserRateThrottle
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.common.mixins import TeamScopedMixin
from apps.common.permissions import (
    ROLE_MANAGER,
    IsTeamMember,
    TeamRolePermission,
)
from apps.websites.models import Website, WebsiteAssignment
from apps.audit.services import AuditService
from apps.audit.models import ActivityLog
from apps.site_health.models import SiteScanState
from apps.site_health.serializers import SiteScanStateSerializer
from apps.scripts.normalize import normalize_recipient_email
from apps.scripts.recipients import build_recipients
from apps.common import outbound
from apps.websites.serializers import (
    SnippetInstructionSerializer,
    WebsiteCreateSerializer,
    WebsiteSerializer,
)

logger = logging.getLogger(__name__)


class SyncFormRecipientsThrottle(UserRateThrottle):
    scope = "sync_form_recipients"
    rate = "2/minute"

# Headers these two actions add on top of the shared outbound identity.
#
# They used to include a spoofed Chrome `User-Agent` and a full set of
# `Sec-Fetch-*` headers, and they went out through a bare `requests.get` rather
# than `apps.common.outbound` — so both actions skipped the per-host budget, the
# 429/Retry-After cooldown, the WAF fingerprinting, and, most importantly, the
# SSRF guard that `outbound` re-applies on *every redirect hop*. A single
# `assert_public_url` on the URL we were handed is not a guard: the site being
# scanned only has to answer 302 with `Location: http://169.254.169.254/`.
#
# The UA is gone deliberately. Every other server-side fetch in the platform
# leaves from one IP under one honest identity, because from one IP a spoofed
# browser is caught on TLS fingerprint anyway, gets that IP banned with no
# appeal, and disqualifies us from Cloudflare's Verified Bots programme. Two
# endpoints quietly opting out of that put every client's uptime monitoring at
# risk to save a handful of scans from a 403 — and a 403 here is already handled
# well, with a message naming the WAF and the fix.
_PAGE_FETCH_HEADERS = {
    "Cache-Control": "no-cache, no-store",
    "Pragma": "no-cache",
}

# A homepage's `<head>` is what both actions read, but `_extract_script_urls`
# also walks inline loaders anywhere in the body, so the whole document matters.
# Generous enough for a page-builder homepage; `truncated` is checked so a
# partial read is never mistaken for a page with fewer scripts on it.
_SCAN_READ_BYTES = 2 * 1024 * 1024

# How long a human-triggered fetch will wait for a per-host token before giving
# up. Someone is watching a spinner, so this cannot be the SEO checker's patient
# pacing — but failing instantly the moment another job touched the same host is
# worse than a short wait.
_PAGE_FETCH_WAIT_SECONDS = 8

# Block-page detection lives in the shared outbound client so the monitor and
# the verifier agree on what "we did not see the real page" looks like.
_looks_like_block_page = outbound.looks_like_block_page


def _fetch_page(fetch_url: str, *, website, what: str, read_bytes: int):
    """Fetch one page of a customer origin for a human-triggered action.

    Returns `(FetchResult, None)` on success or `(None, Response)` on failure,
    so the caller can `if error is not None: return error`. Everything this
    wraps — identity, budget, cooldown, per-hop SSRF guard — comes from
    `apps.common.outbound`; the point of the helper is that neither caller can
    reach the network without it.
    """
    from apps.common.ssrf import BlockedURLError

    try:
        result = outbound.fetch(
            fetch_url,
            timeout=20,
            extra_headers=_PAGE_FETCH_HEADERS,
            read_bytes=read_bytes,
            wait_up_to=_PAGE_FETCH_WAIT_SECONDS,
        )
    except BlockedURLError as exc:
        return None, Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except outbound.HostCoolingDownError as exc:
        # The host told us to back off. Saying so is more useful than a generic
        # failure, because the answer is "wait", not "check your domain".
        logger.info("%s deferred for website %s: %s", what, website.pk, exc)
        return None, Response(
            {
                "detail": (
                    f"{website.domain} asked us to slow down, so we are waiting "
                    "before contacting it again. Try in a few minutes."
                ),
                "code": "cooling_down",
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )
    except outbound.RateLimitedError:
        return None, Response(
            {
                "detail": (
                    "Another check is already talking to this site. "
                    "Try again in a moment."
                ),
                "code": "rate_limited",
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )
    except Exception as exc:
        logger.warning("%s fetch failed for website %s: %s", what, website.pk, exc)
        return None, Response(
            {
                "detail": (
                    "Could not reach the site. Check the domain is correct and "
                    "publicly accessible."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    return result, None


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


# Hidden-field name classifiers for the recipient bucketer below. Must stay in
# lockstep with apps/scripts/snippet.js's RECIPIENT_NAME / CC_NAME / BCC_NAME —
# the two cannot literally share code (one is server-side Python, the other
# browser JS), so this comment is what keeps the word-boundary-ish rule
# identical on both sides. A bare `"cc" in name` substring test — the previous
# version of this module — misclassified any field merely *containing* "cc"
# (success_url, account_email, occupation) as a Cc address.
#
# To used to gate on nothing at all: every hidden email that wasn't Cc/Bcc
# went straight into `hidden_to`, unconditionally. The snippet, by contrast,
# only promotes a hidden email to To when its name matches `RECIPIENT_NAME`,
# and otherwise holds it as a single `fallback` used only when nothing else
# supplied a To. The two writers feed the same `recipient_source="page"` row,
# so disagreeing here reads as a same-source *change* and posts a false
# ClickUp alert on every page that has both a `mailto:` action and an
# unrelated hidden field (an "admin_email" input alongside a mailto: action,
# say) — the alert flips back and forth as the snippet and a Scan take turns
# writing the row.
_HIDDEN_TO_RE = re.compile(
    r"(_to|^to$|sendto|send_to|recipient|receiver|notify|mailto|mail_to|"
    r"admin_email|notification|target_email|forward|destination|deliver|report)",
    re.IGNORECASE,
)
_HIDDEN_CC_RE = re.compile(r"(^cc$|_cc$|carbon)", re.IGNORECASE)
_HIDDEN_BCC_RE = re.compile(r"(^bcc$|_bcc$|blind)", re.IGNORECASE)


def _parse_mailto(action: str) -> tuple[list[str], list[str], list[str]]:
    """To, Cc and Bcc out of a `mailto:` action.

    `mailto:a@x.com,b@x.com?cc=c@x.com&bcc=d@x.com` is a fully specified
    destination — the whole address list and both copy headers. Earlier code
    split on "?" and took only the first address before the first comma, so a
    form addressed to two people reported one and its Cc not at all.
    """
    if not re.match(r"^mailto:", action, re.IGNORECASE):
        return [], [], []
    body = action[len("mailto:"):]
    path, _, query = body.partition("?")
    params = parse_qs(unescape(query))
    return (
        [unescape(path)],
        params.get("cc", []),
        params.get("bcc", []),
    )


def _extract_forms(html: str) -> list[dict]:
    """Best-effort native <form> extraction from raw server-side HTML.

    Mirrors the field shape the snippet's collectForms() reports for native
    forms (see apps/scripts/snippet.js) so descriptors flow through the same
    upsert path and produce rows the snippet's submission counter can match.
    Regex-based like _extract_script_urls: div-based and embedded iframe forms
    are invisible in static HTML and there is no HTML-parser dependency.
    """
    forms: list[dict] = []

    def tag_attrs(tag: str) -> dict:
        out: dict = {}
        for m in re.finditer(
            r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""",
            tag,
        ):
            out[m.group(1).lower()] = m.group(2) or m.group(3) or m.group(4) or ""
        return out

    def field_type(tag: str, attrs: dict) -> str:
        if tag == "textarea":
            return "textarea"
        if tag == "select":
            return "select"
        return (attrs.get("type") or "text").lower()

    for form_match in re.finditer(r"<form\b[^>]*>", html, re.IGNORECASE):
        form_attrs = tag_attrs(form_match.group(0))
        end = html.find("</form>", form_match.end())
        # A stray unclosed <form> must not swallow the rest of the page.
        block = html[form_match.end():end if end != -1 else form_match.end() + 8000]

        fields: list[dict] = []
        hidden_to: list[str] = []
        hidden_cc: list[str] = []
        hidden_bcc: list[str] = []
        # A single held-back guess, used only if nothing else supplies a To —
        # see the fallback discussion below and in the RE block's comment.
        hidden_fallback = ""
        for field_match in re.finditer(r"<(input|textarea|select)\b[^>]*>", block, re.IGNORECASE):
            tag = field_match.group(1).lower()
            field_attrs = tag_attrs(field_match.group(0))
            name = field_attrs.get("name", "")
            ftype = field_type(tag, field_attrs)
            if tag == "input" and ftype in ("submit", "button", "reset", "image"):
                continue
            # Hidden inputs carry the form's *configuration* — most commonly
            # its recipient address(es) — never a visitor's typed value. Captured
            # for recipients but kept out of the field list, matching the
            # snippet's collectForms().
            if tag == "input" and ftype == "hidden":
                hidden_name = (field_attrs.get("name") or "").lower()
                hidden_value = field_attrs.get("value", "")
                # A non-email value must be skipped *before* it can claim any
                # bucket, fallback included — matching the order snippet.js's
                # detectRecipients() runs `isEmailAddress` in, ahead of every
                # bucket check. Bucketing first and normalizing later (as
                # build_recipients does for the to/cc/bcc lists themselves)
                # would let a `_wpnonce` or CSRF token permanently claim the
                # one fallback slot ahead of a later hidden field that is a
                # genuine unnamed recipient address, at which point no amount
                # of downstream normalization gets the address back.
                if not normalize_recipient_email(hidden_value):
                    continue
                if _HIDDEN_BCC_RE.search(hidden_name):
                    hidden_bcc.append(hidden_value)
                elif _HIDDEN_CC_RE.search(hidden_name):
                    hidden_cc.append(hidden_value)
                elif _HIDDEN_TO_RE.search(hidden_name):
                    hidden_to.append(hidden_value)
                elif not hidden_fallback:
                    # A hidden field whose name says nothing about being a
                    # destination (a multi-step form's carried-over visitor
                    # email, say) is only a guess — held back rather than
                    # treated as To, and used below only when nothing else
                    # supplied one.
                    hidden_fallback = hidden_value
                continue
            if not name:
                continue
            label = ""
            fid = field_attrs.get("id")
            if fid:
                lm = re.search(
                    r'<label\b[^>]*\bfor=["\']' + re.escape(fid) + r'["\'][^>]*>(.*?)</label>',
                    block,
                    re.IGNORECASE | re.DOTALL,
                )
                if lm:
                    label = re.sub(r"<[^>]+>", "", lm.group(1)).strip()
            if not label:
                label = field_attrs.get("placeholder", "")
            fields.append({
                "name": name,
                "type": ftype,
                "label": label,
                # `required` is a bare boolean attribute — it never has a value,
                # so it cannot be captured by the key="value" regex above.
                "required": "required" in field_attrs
                or bool(re.search(r"\brequired\b", field_match.group(0), re.IGNORECASE)),
            })

        action = form_attrs.get("action", "")
        mailto_to, mailto_cc, mailto_bcc = _parse_mailto(action)
        # A mailto: action and a hidden recipient field are independent
        # statements of where the form goes, not alternatives — a mailto: form
        # can still carry a hidden copy — so To is their union, matching the
        # snippet's detectRecipients(). The fallback only fills in when
        # *neither* said anything.
        form_to = mailto_to + hidden_to
        if not form_to and hidden_fallback:
            form_to = [hidden_fallback]
        forms.append({
            "form_id": form_attrs.get("id", ""),
            "form_name": form_attrs.get("name", ""),
            "form_action": action,
            "form_method": (form_attrs.get("method") or "post").lower(),
            "detection_type": "native",
            "provider": "",
            "recipients": build_recipients(
                to=form_to,
                cc=mailto_cc or hidden_cc,
                bcc=mailto_bcc or hidden_bcc,
            ),
            "fields": fields[:200],
        })

    return forms


_MANAGER_ROLES = {"owner", "manager"}

# Roles kept out of the per-website assignment picker. SEO staff work across
# the whole client base rather than a slice of it, so a per-site assignment
# would only ever narrow what they can do; leaving them unassigned is what
# gives them every site (the team default in _restrict_to_assignments).
_UNASSIGNABLE_ROLES = {"seo", "seo_executive"}


def _user_role(user, team) -> str:
    from apps.accounts.models import TeamMembership

    try:
        return TeamMembership.objects.get(user=user, team=team).role
    except TeamMembership.DoesNotExist:
        return "viewer"


def _restrict_to_assignments(qs, request):
    """Non-managers with at least one website assignment see only those sites.

    Managers/owners, SEO roles (never assignable — see _UNASSIGNABLE_ROLES) and
    members with no assignments at all (backwards compatible default) see the
    whole team.
    """
    team = request.user.active_team
    if team is None:
        return qs
    role = _user_role(request.user, team)
    if role in _MANAGER_ROLES or role in _UNASSIGNABLE_ROLES:
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
    permission_classes = [permissions.IsAuthenticated, IsTeamMember, TeamRolePermission]

    #: Reads stay open to every member. Writes need staff; the structural and
    #: destructive ones need a manager.
    #:
    #: `regenerate_snippet` rotates the site_id, which invalidates the tag on
    #: the client's live site and stops all ingest until they re-paste it — the
    #: single most disruptive button in the product, and it was reachable by a
    #: viewer. `wp_sso_secret` mints the shared secret behind one-click
    #: wp-admin login, which is a credential for the client's WordPress. Both
    #: belong with the vault, not with day-to-day work.
    action_roles = {
        "regenerate_snippet": ROLE_MANAGER,
        "wp_sso_secret": ROLE_MANAGER,
        # Who may see a site is a manager's decision; who *is* assigned is
        # readable by anyone who can already see the site.
        "assignments:PUT": ROLE_MANAGER,
    }
    # `wp_login` is deliberately absent. It carries its own, finer gate:
    # `_WP_ROLE_MAP` translates the caller's team role into a WordPress role and
    # refuses anyone it cannot map, so a developer gets an `editor` login and a
    # viewer gets a 403. Adding it here as manager-only did not tighten that —
    # it contradicted it, locking developers out of the one thing the role map
    # exists to give them.

    def get_queryset(self):
        from apps.scripts.tasks import _internal_hosts

        qs = _restrict_to_assignments(super().get_queryset(), self.request)
        # Exclude Stacks Monitor's own infra scripts (the tracking snippet etc.) so the
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

    # Stacks Monitor role → WordPress role for one-click wp-admin login.
    _WP_ROLE_MAP = {
        "owner": "administrator",
        "manager": "administrator",
        "developer": "editor",
    }

    @action(detail=True, methods=["get", "post"], url_path="wp-sso-secret")
    def wp_sso_secret(self, request, pk=None):
        """GET: the current WP Connect snippet, for a re-paste. POST: generate
        (or rotate) the shared secret and return the new snippet. Managers and
        owners only. Rotating invalidates all previously issued login links,
        and the old snippet's posts are refused until the new one is pasted —
        its buffer survives that and is re-sent, so nothing is lost.

        GET exists because a re-paste (the uptime heartbeat, any snippet
        change) should not have to rotate a secret that is working."""
        import secrets as _secrets

        website = self.get_object()
        team = request.user.active_team
        if _user_role(request.user, team) not in _MANAGER_ROLES:
            return Response(
                {"detail": "Only managers can manage the WP login secret."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if request.method == "GET":
            if not website.wp_sso_secret:
                return Response(
                    {"detail": "This site has no WP Connect snippet yet. Generate one first."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            # The snippet carries the secret, so reading it is audited.
            AuditService.log_request(
                request, ActivityLog.Action.WEBSITE_WP_SNIPPET_VIEWED,
                description=f"Viewed WP Connect snippet for '{website.domain}'",
                resource_type="website", resource_id=website.pk,
                metadata={"website_id": str(website.pk)},
            )
            return Response({"snippet": website.wp_sso_snippet})
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

    @action(detail=True, methods=["post"], url_path="sync-form-recipients")
    def sync_form_recipients(self, request, pk=None):
        """Ask this site where its forms deliver, now.

        The nightly tasks do the same sweep; this exists so setting a site up
        and seeing the Forms tab fill in are the same minute rather than a day
        apart.

        Recipient lookup uses only the encrypted WordPress credential and
        authenticated plugin REST APIs. Plugins that do not expose recipient
        settings through their API are reported as unsupported; no browser
        script or client-side access to the WordPress database is used.

        Note this is deliberately *not* the WP Connect snippet — that path was
        retired, and `wp_forms.fetch_recipients` no longer has a caller. The
        Forms tab used to tell the user to set up WP Connect while this endpoint
        demanded an Application Password, which is a dead end dressed up as an
        instruction; the tab's copy now names the credential this actually
        needs.
        """
        from apps.websites import wp_api_forms

        website = self.get_object()
        throttle = SyncFormRecipientsThrottle()
        if not throttle.allow_request(request, self):
            return Response(
                {"detail": "Recipient lookup is limited to two requests per minute."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        try:
            result = wp_api_forms.sync_website_detailed(website)
        except Exception:
            logger.exception("sync_form_recipients failed for website %s", website.pk)
            return Response(
                {"detail": "Could not read the site's form settings."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        if result.get("reason") == "no_credentials":
            return Response(
                {
                    **result,
                    "detail": (
                        "Add a WordPress credential for this site in the "
                        "Credentials tab, using an Application Password, and "
                        "Stacks Monitor can read where these forms deliver."
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response(result)

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
                for uid in TeamMembership.objects.filter(team=team)
                .exclude(role__in=_UNASSIGNABLE_ROLES)
                .values_list("user_id", flat=True)
            )
            invalid = [uid for uid in user_ids if str(uid) not in member_ids]
            if invalid:
                return Response(
                    {"detail": "Some users cannot be assigned to this website."},
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

        memberships = (
            TeamMembership.objects.filter(team=team)
            .exclude(role__in=_UNASSIGNABLE_ROLES)
            .select_related("user")
        )
        assignable_user_ids = {m.user_id for m in memberships}
        # Stale rows for a now-unassignable member are hidden rather than
        # listed: the picker cannot untick what it never shows, so surfacing
        # them would strand an assignment nobody can clear.
        rows = [
            a for a in
            WebsiteAssignment.objects.filter(website=website).select_related("user")
            if a.user_id in assignable_user_ids
        ]
        return Response({
            "assigned": [_user_row(a.user) for a in rows],
            "members": [
                {**_user_row(m.user), "role": m.role} for m in memberships
            ],
            "can_edit": _user_role(request.user, team) in _MANAGER_ROLES,
        })

    # NOTE: list() deliberately does NOT recalculate health.
    #
    # It used to recalculate every listed site on every request. That cost ~8
    # queries and a write per site, making this endpoint 1.03s for 13 sites —
    # six to seventeen times every other call the dashboard makes, on the
    # critical path of every page load and every filter change, and growing
    # linearly with the number of sites.
    #
    # It was a safety net from before the score had proper triggers. Health is
    # now recalculated on ingest, on acknowledge/review, on a monitor state flip,
    # after a domain check and after a security scan, plus a nightly
    # websites.recalculate_all_health sweep. retrieve() still heals the single
    # site being opened, which is cheap and is where a stale number would
    # actually be noticed.

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

        if website.snippet_status != Website.SnippetStatus.INSTALLED:
            return Response(
                {
                    "detail": "Install the tracking snippet and open the website before scanning scripts.",
                    "code": "snippet_required",
                },
                status=status.HTTP_409_CONFLICT,
            )

        import secrets as _secrets

        url = website.domain if website.domain.startswith("http") else f"https://{website.domain}"
        bust = _secrets.token_hex(8)
        fetch_url = f"{url}{'&' if '?' in url else '?'}_dvv={bust}"

        result, error = _fetch_page(
            fetch_url, website=website, what="scan", read_bytes=_SCAN_READ_BYTES
        )
        if error is not None:
            return error

        if result.status_code >= 400:
            # `blocked_by` names the WAF when one is identifiable. Saying which
            # one, and that the site itself is fine, is the difference between a
            # message someone can act on and one that sends them re-checking a
            # domain that was never wrong.
            vendor = result.blocked_by
            if vendor:
                return Response(
                    {
                        "detail": (
                            f"{vendor} answered instead of {website.domain} "
                            f"(HTTP {result.status_code}), so we never saw the page. "
                            "Allowlist our scanner "
                            f"({settings.BOT_INFO_URL}) and try again."
                        ),
                        "code": "blocked",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response(
                {"detail": f"Could not fetch the page (HTTP {result.status_code})."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        html = result.body
        if result.truncated:
            # A partial read is the same failure mode as a partial snapshot: the
            # scripts past the cut look exactly like scripts that are not there.
            # The scan feeds process_ingest_payload, which would record that as
            # an observation, so refuse rather than under-report.
            logger.warning(
                "Scan of website %s truncated at %d bytes", website.pk, _SCAN_READ_BYTES
            )
            return Response(
                {
                    "detail": (
                        "The page is larger than we can read in one scan, so the "
                        "result would be incomplete. The tracking snippet reports "
                        "this page in full on the next visit."
                    ),
                    "code": "page_too_large",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Strip the cache-buster from the stored page URL.
        final_url = result.final_url.replace(f"_dvv={bust}", "").rstrip("?&")

        # Detect the CMS / site builder from the fetched page and persist it.
        # Done before the script check so platform is set even for pages with
        # no external scripts.
        from apps.websites.platform_detect import detect_platform

        detected = detect_platform(html, result.headers)
        if detected and detected != website.platform:
            website.platform = detected
            website.save(update_fields=["platform"])

        script_urls = _extract_script_urls(html)
        forms = _extract_forms(html)

        if not script_urls and not forms:
            return Response({
                "detail": "No external scripts or forms found on the page.",
                "count": 0,
                "forms": 0,
                "platform": website.platform,
            })

        scripts = [
            {"src": src, "location": "unknown", "async": False, "defer": False, "inline": False}
            for src in script_urls
        ]

        from apps.scripts.models import ScriptSnapshot
        from apps.scripts.tasks import process_ingest_payload
        from apps.site_health.tasks import run_security_scan

        payload = {
            "page_url": final_url,
            "scripts": scripts,
            "forms": forms,
            "user_agent": "Digivault-Scanner/1.0",
            "snippet_version": ScriptSnapshot.SERVER_SCAN_VERSION,
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
            "detail": f"Scan queued — found {len(scripts)} scripts and {len(forms)} forms.",
            "count": len(scripts),
            "forms": len(forms),
            "platform": website.platform,
        })

    @action(detail=True, methods=["post"], url_path="verify-snippet")
    def verify_snippet(self, request, pk=None):
        """Confirm the tracking snippet is installed.

        Two signals, strongest first:

        1. Ingest traffic. Only a real browser loading a page that carries the
           snippet can produce a snapshot, so its existence proves installation
           outright. Server-side `scan` snapshots are excluded — those come from
           us, not from the snippet.
        2. A server-side fetch of the homepage. This is best-effort: sites behind
           Cloudflare bot management or a host WAF serve us a challenge or a 403
           instead of their real HTML, and we must not read that as "the snippet
           is missing" — doing so sent users re-pasting HTML that was correct.
        """
        import secrets as _secrets

        from apps.scripts.models import ScriptSnapshot

        website = self.get_object()
        url = website.domain if website.domain.startswith("http") else f"https://{website.domain}"

        def _verified(reason, **extra):
            AuditService.log_request(
                request, ActivityLog.Action.WEBSITE_SNIPPET_VERIFIED,
                description=f"Snippet verified for '{website.domain}'",
                resource_type="website", resource_id=website.pk,
            )
            return Response({"verified": True, "reason": reason, **extra})

        # 1. Ingest traffic is authoritative — check it before touching the network.
        traffic = (
            ScriptSnapshot.objects.filter(website=website)
            .exclude(snippet_version=ScriptSnapshot.SERVER_SCAN_VERSION)
            .order_by("-captured_at")
            .first()
        )
        if traffic is not None:
            return _verified(
                "ingest_traffic",
                detail=(
                    "The snippet is reporting in — we last received data from "
                    f"{traffic.page_url} on {traffic.captured_at:%d %b %Y at %H:%M} UTC."
                ),
            )

        # Append a random cache-buster so CDNs/proxies return a fresh response.
        bust = _secrets.token_hex(8)
        fetch_url = f"{url}{'&' if '?' in url else '?'}_dvv={bust}"

        result, error = _fetch_page(
            fetch_url, website=website, what="verify", read_bytes=_SCAN_READ_BYTES
        )
        if error is not None:
            # This endpoint answers 200 with `verified: false` rather than an
            # HTTP error, because "we could not look" is an answer the setup
            # page renders, not a request failure. Carry the reason across.
            detail = error.data.get("detail", "") if isinstance(error.data, dict) else ""
            return Response({
                "verified": False,
                "reason": "unreachable",
                "error": detail or (
                    "Could not reach the site. Check the domain is correct and "
                    "publicly accessible."
                ),
            })

        html = result.body

        # Match on the site ID alone, not on `data-site="<id>"` — HTML minifiers
        # and page builders re-quote attributes, and the ID is a 43-char random
        # token, so its presence anywhere in the page is proof enough.
        if website.site_id in html:
            return _verified("html_match")

        from apps.common.outbound import egress_ips

        ips = egress_ips()
        # The block is on *our* server's request, not on the snippet — visitors'
        # browsers load it fine. The old wording ("add the snippet to your
        # allowlist") asked for something no firewall offers.
        blocked_note = (
            " This does not affect the snippet itself — visitors' browsers are not "
            "blocked. It verifies itself as soon as a visitor loads the page. To let "
            "our checks through, allowlist our monitor"
            + (f" (IP {', '.join(ips)})" if ips else "")
            + f" — see {settings.BOT_INFO_URL}."
        )

        if result.status_code >= 400:
            # `blocked_by` names the vendor when the headers or body identify
            # one; unattributed stays unattributed rather than guessing.
            who = result.blocked_by or "the site's firewall or CDN"
            return Response({
                "verified": False,
                "reason": "blocked",
                "error": (
                    f"{url} answered our check with HTTP {result.status_code}, so we never saw "
                    f"your page — this is {who} blocking us, not a "
                    f"problem with your snippet.{blocked_note}"
                ),
            })

        if _looks_like_block_page(html):
            return Response({
                "verified": False,
                "reason": "blocked",
                "error": (
                    f"{url} served a bot-protection page ({len(html):,} bytes) instead of your "
                    f"HTML, so we could not check the snippet.{blocked_note}"
                ),
            })

        return Response({
            "verified": False,
            "reason": "not_found",
            "error": (
                f"Snippet not found on {url}. Checked {len(html):,} bytes of HTML. "
                f"Make sure the tag is in the <head> of the published page and that any "
                f"page cache has been cleared."
            ),
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

    @action(detail=False, methods=["get"], url_path="fleet-summary")
    def fleet_summary(self, request):
        """Team-wide roll-up of SEO, performance, security-header and
        vulnerability state.

        One query per area rather than per website: the dashboard needs all four
        for every site, and fanning out would be 4 requests x N sites. Only
        reads stored scan results — never triggers a scan.
        """
        from django.db.models import Avg, Count, Q, Sum
        from django.db.models.functions import Coalesce

        from apps.performance.models import PerformanceReport
        from apps.site_health.models import (
            SecurityHeaderReport,
            SeoReport,
            VulnerabilityReport,
        )

        site_ids = list(self.get_queryset().values_list("id", flat=True))
        total = len(site_ids)
        if not total:
            return Response({
                "total_sites": 0,
                "seo": {}, "performance": {}, "security": {}, "vulnerabilities": {},
            })

        # ---- SEO -----------------------------------------------------------
        seo = SeoReport.objects.filter(website_id__in=site_ids, check_status="done")
        seo_agg = seo.aggregate(
            checked=Count("id"),
            indexable=Count("id", filter=Q(homepage_indexable=True)),
            blocked=Count(
                "id", filter=Q(robots_blocks_all=True) | Q(homepage_indexable=False)
            ),
            noindex_pages=Coalesce(Sum("noindex_count"), 0),
        )

        # ---- Performance: the newest run per site, per strategy -------------
        # Ordered newest-first by the model's own Meta, so the first row seen for
        # a (site, strategy) pair is the current one.
        latest = {}
        for row in (
            PerformanceReport.objects
            .filter(website_id__in=site_ids, performance_score__isnull=False)
            # PerformanceReport keeps its own timestamp — checked_at, not the
            # BaseModel created_at, since it does not inherit from it.
            .order_by("website_id", "strategy", "-checked_at")
            .values("website_id", "strategy", "performance_score")
        ):
            latest.setdefault((row["website_id"], row["strategy"]), row["performance_score"])
        mobile = [v for (_, strat), v in latest.items() if strat == "mobile"]
        desktop = [v for (_, strat), v in latest.items() if strat == "desktop"]
        avg = lambda xs: round(sum(xs) / len(xs)) if xs else None

        # ---- Security headers ----------------------------------------------
        headers = SecurityHeaderReport.objects.filter(
            website_id__in=site_ids, check_status="done"
        )
        header_agg = headers.aggregate(checked=Count("id"), avg_score=Avg("score"))
        grades = dict(
            headers.values_list("grade").annotate(n=Count("id")).values_list("grade", "n")
        )

        # ---- Vulnerabilities ------------------------------------------------
        vulns = VulnerabilityReport.objects.filter(website_id__in=site_ids)
        vuln_agg = vulns.aggregate(
            critical=Count("id", filter=Q(severity="critical")),
            high=Count("id", filter=Q(severity="high")),
            medium=Count("id", filter=Q(severity="medium")),
            low=Count("id", filter=Q(severity="low")),
        )
        vuln_agg["sites_affected"] = (
            vulns.values("website_id").distinct().count()
        )

        # ---- Tracking coverage ---------------------------------------------
        # Distinct sites carrying each kind of tag, from the classifier's own
        # categories. "Has analytics" is the question an agency actually asks —
        # a site with no measurement is invisible to the client's reporting.
        from apps.scripts.models import Script

        def sites_with(**flt):
            return (
                Script.objects.filter(website_id__in=site_ids, is_active=True, **flt)
                .values("website_id").distinct().count()
            )

        analytics_sites = sites_with(category__in=["analytics", "tag_management"])
        tracking = {
            "analytics": analytics_sites,
            "missing_analytics": total - analytics_sites,
            "tag_manager": sites_with(category="tag_management"),
            "advertising": sites_with(category="advertising"),
            "call_tracking": sites_with(category="call_tracking"),
            "unknown_scripts": sites_with(provider="unknown"),
            "suspicious_sites": sites_with(is_suspicious=True),
            "suspicious_scripts": Script.objects.filter(
                website_id__in=site_ids, is_active=True, is_suspicious=True
            ).count(),
        }

        return Response({
            "total_sites": total,
            "tracking": tracking,
            "seo": {
                "checked": seo_agg["checked"],
                "not_checked": total - seo_agg["checked"],
                "indexable": seo_agg["indexable"],
                "blocked": seo_agg["blocked"],
                "noindex_pages": seo_agg["noindex_pages"],
            },
            "performance": {
                "measured": len({wid for wid, _ in latest}),
                "not_measured": total - len({wid for wid, _ in latest}),
                "avg_mobile": avg(mobile),
                "avg_desktop": avg(desktop),
                # Lighthouse's own bands: <50 poor, 50-89 needs work, 90+ good.
                "poor_mobile": sum(1 for v in mobile if v < 50),
                "good_mobile": sum(1 for v in mobile if v >= 90),
            },
            "security": {
                "checked": header_agg["checked"],
                "not_checked": total - header_agg["checked"],
                "avg_score": round(header_agg["avg_score"]) if header_agg["avg_score"] is not None else None,
                "grades": grades,
                # A and B pass; C and below need work.
                "failing": sum(n for g, n in grades.items() if g and g[0] in "CDF"),
            },
            "vulnerabilities": vuln_agg,
        })

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
