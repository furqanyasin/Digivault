"""Domain & SSL intelligence service.

Performs WHOIS lookups, hosting detection, and SSL certificate inspection.
All network calls are isolated here so the rest of the app stays testable.
"""

from __future__ import annotations

import logging
import re
import socket
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Known hosting providers — matched against ASN org or reverse DNS
# ------------------------------------------------------------------

_HOSTING_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"godaddy", re.I), "GoDaddy"),
    (re.compile(r"namecheap", re.I), "Namecheap"),
    (re.compile(r"hostinger", re.I), "Hostinger"),
    (re.compile(r"siteground|sgcpanel|sgvps", re.I), "SiteGround"),
    (re.compile(r"bluehost", re.I), "Bluehost"),
    (re.compile(r"wp\s*engine|wpengine", re.I), "WP Engine"),
    (re.compile(r"kinsta", re.I), "Kinsta"),
    (re.compile(r"vercel", re.I), "Vercel"),
    (re.compile(r"netlify", re.I), "Netlify"),
    (re.compile(r"squarespace", re.I), "Squarespace"),
    (re.compile(r"cloudflare", re.I), "Cloudflare"),
    (re.compile(r"amazon|aws|amazonaws", re.I), "AWS"),
    (re.compile(r"digitalocean", re.I), "DigitalOcean"),
    (re.compile(r"linode|akamai", re.I), "Akamai / Linode"),
    (re.compile(r"vultr", re.I), "Vultr"),
    (re.compile(r"hetzner", re.I), "Hetzner"),
    (re.compile(r"google|gcp", re.I), "Google Cloud"),
    (re.compile(r"microsoft|azure", re.I), "Microsoft Azure"),
]

_CLOUDFLARE_NS_PATTERN = re.compile(r"\.ns\.cloudflare\.com$", re.I)

# Domain expiry thresholds that trigger alerts (days before expiry)
DOMAIN_ALERT_THRESHOLDS = [90, 60, 30, 14, 7]
SSL_ALERT_THRESHOLDS = [90, 30, 7]


@dataclass
class DomainCheckResult:
    registrar: str = ""
    registered_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    nameservers: list[str] = field(default_factory=list)
    whois_privacy: bool = False
    auto_renew: Optional[bool] = None
    hosting_provider: str = ""
    hosting_ip: str = ""
    uses_cloudflare: bool = False
    ssl_issuer: str = ""
    ssl_expires_at: Optional[datetime] = None
    ssl_auto_renew: Optional[bool] = None
    error: str = ""


class DomainIntelligenceService:
    """Performs WHOIS, hosting, and SSL checks for a domain string.

    Usage::

        result = DomainIntelligenceService.check("acmecorp.com")
        result.registrar       # "GoDaddy"
        result.expires_at      # datetime(...)
        result.hosting_provider # "Kinsta"
    """

    @classmethod
    def _normalise(cls, domain: str) -> str:
        """Strip protocol, www prefix, port, and path from a domain string."""
        from urllib.parse import urlparse
        if "://" not in domain:
            domain = "https://" + domain
        parsed = urlparse(domain)
        host = parsed.hostname or domain
        return host.lstrip("www.") if host.startswith("www.") else host

    @classmethod
    def check(cls, domain: str) -> DomainCheckResult:
        """Run all checks and return a consolidated result.  Never raises."""
        hostname = cls._normalise(domain)
        result = DomainCheckResult()
        try:
            cls._whois(hostname, result)
        except Exception as exc:
            logger.warning("WHOIS failed for %s: %s", hostname, exc)
            result.error = str(exc)

        try:
            cls._hosting(hostname, result)
        except Exception as exc:
            logger.warning("Hosting detection failed for %s: %s", hostname, exc)

        try:
            cls._ssl(hostname, result)
        except Exception as exc:
            logger.warning("SSL check failed for %s: %s", hostname, exc)

        return result

    # ------------------------------------------------------------------
    # WHOIS
    # ------------------------------------------------------------------

    @classmethod
    def _whois(cls, domain: str, result: DomainCheckResult) -> None:
        import whois  # python-whois

        w = whois.whois(domain)

        result.registrar = cls._first_str(w.registrar)

        # python-whois returns dates as a list or a single value
        result.registered_at = cls._first_date(w.creation_date)
        result.expires_at = cls._first_date(w.expiration_date)

        ns = w.name_servers or []
        if isinstance(ns, str):
            ns = [ns]
        result.nameservers = [n.lower() for n in ns if n]

        # Privacy registrars commonly include "privacy" or "proxy" in registrar name
        registrar_lower = (result.registrar or "").lower()
        result.whois_privacy = any(
            kw in registrar_lower for kw in ("privacy", "proxy", "whoisguard", "protect")
        )

        # Detect Cloudflare DNS from nameservers
        result.uses_cloudflare = any(
            _CLOUDFLARE_NS_PATTERN.search(ns) for ns in result.nameservers
        )

    # ------------------------------------------------------------------
    # Hosting detection
    # ------------------------------------------------------------------

    @classmethod
    def _hosting(cls, domain: str, result: DomainCheckResult) -> None:
        # 1. Try to detect provider from nameservers (already populated by WHOIS)
        ns_combined = " ".join(result.nameservers)
        for pattern, provider in _HOSTING_PATTERNS:
            if pattern.search(ns_combined):
                result.hosting_provider = provider
                # Cloudflare NS → uses_cloudflare already set by WHOIS; also mark provider
                break

        # 2. Resolve IP
        try:
            ip = socket.gethostbyname(domain)
            result.hosting_ip = ip
        except socket.gaierror as exc:
            logger.debug("DNS resolution failed for %s: %s", domain, exc)
            return

        # 3. Reverse DNS — may override NS-based detection with a more specific match
        try:
            reverse = socket.gethostbyaddr(ip)[0]
        except Exception:
            reverse = ""

        if reverse:
            for pattern, provider in _HOSTING_PATTERNS:
                if pattern.search(reverse):
                    result.hosting_provider = provider
                    return

        # 4. If nothing matched yet, mark as unknown
        if not result.hosting_provider:
            result.hosting_provider = "Unknown"

    # ------------------------------------------------------------------
    # SSL
    # ------------------------------------------------------------------

    @classmethod
    def _ssl(cls, domain: str, result: DomainCheckResult) -> None:
        ctx = ssl.create_default_context()
        try:
            with ctx.wrap_socket(
                socket.create_connection((domain, 443), timeout=10),
                server_hostname=domain,
            ) as conn:
                cert = conn.getpeercert()
        except Exception:
            return

        # Issuer organisation
        issuer = dict(x[0] for x in cert.get("issuer", []))
        result.ssl_issuer = issuer.get("organizationName", "")

        # Expiry — format: 'Nov  3 00:00:00 2025 GMT'
        not_after = cert.get("notAfter", "")
        if not_after:
            try:
                result.ssl_expires_at = datetime.strptime(
                    not_after, "%b %d %H:%M:%S %Y %Z"
                ).replace(tzinfo=dt_timezone.utc)
            except ValueError:
                pass

        # Let's Encrypt certificates auto-renew by convention
        result.ssl_auto_renew = "Let's Encrypt" in result.ssl_issuer

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _first_str(value) -> str:
        if isinstance(value, list):
            return str(value[0]) if value else ""
        return str(value) if value else ""

    @staticmethod
    def _first_date(value) -> Optional[datetime]:
        if isinstance(value, list):
            value = value[0] if value else None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=dt_timezone.utc)
            return value
        return None
