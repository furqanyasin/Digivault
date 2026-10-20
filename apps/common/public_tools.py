"""Free website tools for the marketing site. No login.

GET /api/v1/public/tools/ssl/?domain=example.com
GET /api/v1/public/tools/domain/?domain=example.com
GET /api/v1/public/tools/uptime/?url=https://example.com
GET /api/v1/public/tools/scripts/?url=https://example.com

Each one reuses a check the product already runs for paying teams. They are
throttled per IP (`public_tools` scope), cached per target for a few minutes
so a refresh costs nothing, and every outbound connection goes through the
SSRF guard so the tools cannot be pointed at internal addresses.
"""

from __future__ import annotations

import logging
import re
import socket
import ssl
from datetime import datetime, timezone as dt_timezone
from urllib.parse import urlparse

from django.core.cache import cache
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.common.ssrf import BlockedURLError, _ip_is_blocked

logger = logging.getLogger(__name__)

CACHE_SECONDS = 300
_HOST_RE = re.compile(r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$")


class PublicToolsThrottle(AnonRateThrottle):
    scope = "public_tools"


def _clean_host(raw: str) -> str | None:
    raw = (raw or "").strip().lower()
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    host = (urlparse(raw).hostname or "").rstrip(".")
    return host if _HOST_RE.match(host) else None


def _clean_url(raw: str) -> str | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        return None
    host = _clean_host(parsed.hostname or "")
    if not host:
        return None
    path = parsed.path or "/"
    return f"{parsed.scheme}://{host}{':' + str(parsed.port) if parsed.port else ''}{path}" + (
        f"?{parsed.query}" if parsed.query else ""
    )


def _public_ip(host: str) -> str:
    """The first address of `host`, refusing any private one."""
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BlockedURLError(f"We could not find {host}. Check the spelling.") from exc
    for info in infos:
        if _ip_is_blocked(info[4][0]):
            raise BlockedURLError("That address is not on the public internet.")
    return infos[0][4][0]


def _bad(message: str, code: int = status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"detail": message}, status=code)


class _ToolView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [PublicToolsThrottle]
    tool = ""

    def cached(self, key: str, compute):
        cache_key = f"public_tool:{self.tool}:{key}"
        hit = cache.get(cache_key)
        if hit is not None:
            return Response({**hit, "cached": True})
        try:
            result = compute()
        except BlockedURLError as exc:
            return _bad(str(exc))
        cache.set(cache_key, result, CACHE_SECONDS)
        return Response({**result, "cached": False})


def _days_left(when: datetime | None) -> int | None:
    if when is None:
        return None
    return (when - datetime.now(dt_timezone.utc)).days


class SslCheckView(_ToolView):
    tool = "ssl"

    def get(self, request):
        host = _clean_host(request.query_params.get("domain", ""))
        if not host:
            return _bad("Enter a domain like example.com.")
        return self.cached(host, lambda: self._check(host))

    @staticmethod
    def _check(host: str) -> dict:
        ip = _public_ip(host)
        ctx = ssl.create_default_context()
        result = {"domain": host, "ip": ip, "valid": False, "error": ""}
        try:
            with socket.create_connection((ip, 443), timeout=10) as raw:
                with ctx.wrap_socket(raw, server_hostname=host) as conn:
                    cert = conn.getpeercert()
                    result["protocol"] = conn.version()
        except ssl.SSLCertVerificationError as exc:
            result["error"] = f"The certificate is not trusted: {exc.verify_message or exc.reason}."
            return result
        except ssl.SSLError as exc:
            result["error"] = f"The SSL handshake failed ({exc.reason or exc})."
            return result
        except (socket.timeout, TimeoutError):
            result["error"] = "The server did not answer on port 443 within 10 seconds."
            return result
        except OSError as exc:
            result["error"] = f"Could not connect on port 443 ({exc.strerror or exc})."
            return result

        def _name(field):
            return dict(x[0] for x in cert.get(field, []))

        def _date(value):
            try:
                return datetime.strptime(value, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=dt_timezone.utc)
            except (TypeError, ValueError):
                return None

        not_before = _date(cert.get("notBefore"))
        not_after = _date(cert.get("notAfter"))
        issuer = _name("issuer")
        result.update({
            "valid": True,
            "subject": _name("subject").get("commonName", ""),
            "issuer": issuer.get("organizationName") or issuer.get("commonName", ""),
            "valid_from": not_before.isoformat() if not_before else None,
            "valid_to": not_after.isoformat() if not_after else None,
            "days_left": _days_left(not_after),
            "san": [v for k, v in cert.get("subjectAltName", []) if k == "DNS"][:50],
        })
        return result


class DomainExpiryView(_ToolView):
    tool = "domain"

    def get(self, request):
        host = _clean_host(request.query_params.get("domain", ""))
        if not host:
            return _bad("Enter a domain like example.com.")
        if host.startswith("www."):
            host = host[4:]
        return self.cached(host, lambda: self._check(host))

    @staticmethod
    def _check(host: str) -> dict:
        from apps.domains.services import DomainCheckResult, DomainIntelligenceService

        data = DomainCheckResult()
        error = ""
        try:
            DomainIntelligenceService._whois(host, data)
        except Exception as exc:
            logger.info("Public WHOIS lookup failed for %s: %s", host, exc)
            error = "The registry did not return WHOIS data for this domain."
        if not error and data.expires_at is None:
            error = "The registry did not publish an expiry date for this domain."
        return {
            "domain": host,
            "registrar": data.registrar,
            "registered_at": data.registered_at.isoformat() if data.registered_at else None,
            "expires_at": data.expires_at.isoformat() if data.expires_at else None,
            "days_left": _days_left(data.expires_at),
            "nameservers": data.nameservers[:10],
            "uses_cloudflare": data.uses_cloudflare,
            "error": error,
        }


class UptimeCheckView(_ToolView):
    tool = "uptime"

    def get(self, request):
        url = _clean_url(request.query_params.get("url", ""))
        if not url:
            return _bad("Enter a website address like example.com.")
        return self.cached(url, lambda: self._check(url))

    @staticmethod
    def _check(url: str) -> dict:
        from apps.common import outbound

        try:
            res = outbound.fetch(url, method="GET", timeout=15, wait_up_to=3, read_bytes=8192)
        except BlockedURLError:
            raise
        except (outbound.RateLimitedError, outbound.HostCoolingDownError):
            return {"url": url, "status": "unknown", "status_code": None, "response_time_ms": None,
                    "error": "We checked this site a moment ago. Try again in a minute."}
        except Exception as exc:
            reason = getattr(exc, "reason", exc)
            return {"url": url, "status": "down", "status_code": None, "response_time_ms": None,
                    "error": f"The site did not answer: {reason}"[:300]}
        code = res.status_code
        if res.blocked_by:
            state = "blocked"
            error = f"{res.blocked_by} answered instead of the site (HTTP {code}). Visitors may still see it."
        elif code < 400:
            state, error = "up", ""
        else:
            state, error = "down", f"The site answered with HTTP {code}."
        return {"url": url, "final_url": res.final_url, "status": state, "status_code": code,
                "response_time_ms": res.elapsed_ms, "error": error}


class ScriptScanView(_ToolView):
    tool = "scripts"

    def get(self, request):
        url = _clean_url(request.query_params.get("url", ""))
        if not url:
            return _bad("Enter a website address like example.com.")
        return self.cached(url, lambda: self._scan(url))

    @staticmethod
    def _scan(url: str) -> dict:
        from apps.common import outbound
        from apps.scripts.classifier import ScriptClassifier
        from apps.websites.views import _extract_script_urls

        try:
            res = outbound.fetch(url, method="GET", timeout=20, wait_up_to=3, read_bytes=2 * 1024 * 1024)
        except BlockedURLError:
            raise
        except (outbound.RateLimitedError, outbound.HostCoolingDownError):
            return {"url": url, "scripts": [], "error": "We scanned this site a moment ago. Try again in a minute."}
        except Exception as exc:
            reason = getattr(exc, "reason", exc)
            return {"url": url, "scripts": [], "error": f"We could not load the page: {reason}"[:300]}
        if res.status_code >= 400:
            msg = (f"{res.blocked_by} blocked our scanner (HTTP {res.status_code})." if res.blocked_by
                   else f"The page answered with HTTP {res.status_code}.")
            return {"url": url, "scripts": [], "error": msg}

        page_host = urlparse(res.final_url).hostname or ""
        scripts = []
        for src in _extract_script_urls(res.body)[:200]:
            if src.startswith("/"):
                continue  # relative path, the site's own file
            host = ScriptClassifier.extract_domain(src)
            c = ScriptClassifier.classify(src)
            scripts.append({
                "url": src[:500],
                "host": host,
                "provider": c.provider if c.is_known else "",
                "category": c.category if c.is_known else "unknown",
                "first_party": bool(host) and (host == page_host or host.endswith("." + page_host)),
            })
        third = [s for s in scripts if not s["first_party"]]
        return {
            "url": url,
            "final_url": res.final_url,
            "scripts": scripts,
            "third_party_count": len(third),
            "unknown_count": sum(1 for s in third if not s["provider"]),
            "truncated": res.truncated,
            "error": "",
        }
