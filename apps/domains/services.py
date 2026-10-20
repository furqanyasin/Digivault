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
DOMAIN_ALERT_THRESHOLDS = [90, 60, 30, 14, 7, 3]
SSL_ALERT_THRESHOLDS = [90, 30, 7]
HOSTING_ALERT_THRESHOLDS = [90, 60, 30, 14, 7, 3]


def _resolve_mx(domain: str) -> list[str]:
    """Return MX hostnames ordered by preference. Requires dnspython."""
    import dns.resolver

    answers = dns.resolver.resolve(domain, "MX", lifetime=8)
    records = sorted((r.preference, str(r.exchange).rstrip(".")) for r in answers)
    return [host for _pref, host in records]


def _resolve_txt(name: str) -> list[str]:
    """TXT records for a name, each joined from its string chunks.

    Long TXT values arrive split into 255-byte chunks; DMARC and SPF policies
    routinely exceed that, so the chunks must be concatenated before parsing or
    the record reads as truncated.
    """
    import dns.resolver

    answers = dns.resolver.resolve(name, "TXT", lifetime=8)
    return ["".join(part.decode() for part in r.strings) for r in answers]


# Selectors are not discoverable from DNS — you can only ask for ones you know.
# These cover Google Workspace, Microsoft 365, Mailchimp, SendGrid, Zoho and the
# common self-hosted default, which is most agency-managed mail.
DKIM_SELECTORS = ["google", "selector1", "selector2", "k1", "s1", "s2", "zoho", "default", "dkim"]


def check_email_auth(domain: str, *, resolve_txt=None) -> dict:
    """Check SPF, DKIM and DMARC for a domain.

    Returns spf_status/dmarc_status of pass|missing|error, the raw records for
    display, and dkim_status of pass|missing|error with the selector that
    answered. Never raises — a mail-auth failure must not fail the whole domain
    check.

    Statuses describe *presence and syntax*, not correctness: verifying that an
    SPF policy actually lists the right senders needs the sending
    infrastructure, which Stacks Monitor does not know.
    """
    resolve_txt = resolve_txt or _resolve_txt
    out = {
        "spf_status": "missing", "spf_record": "",
        "dmarc_status": "missing", "dmarc_record": "",
        "dkim_status": "missing", "dkim_selector": "",
    }

    # SPF lives on the domain apex as a TXT record starting v=spf1.
    try:
        for txt in resolve_txt(domain):
            if txt.lower().startswith("v=spf1"):
                out["spf_status"] = "pass"
                out["spf_record"] = txt[:500]
                break
    except Exception as exc:
        logger.warning("SPF lookup failed for %s: %s", domain, exc)
        out["spf_status"] = "error"

    # DMARC lives at _dmarc.<domain>.
    try:
        for txt in resolve_txt(f"_dmarc.{domain}"):
            if txt.lower().startswith("v=dmarc1"):
                out["dmarc_status"] = "pass"
                out["dmarc_record"] = txt[:500]
                break
    except Exception as exc:
        logger.warning("DMARC lookup failed for %s: %s", domain, exc)
        out["dmarc_status"] = "error"

    # DKIM: probe the known selectors and stop at the first that answers.
    for selector in DKIM_SELECTORS:
        try:
            for txt in resolve_txt(f"{selector}._domainkey.{domain}"):
                if "v=dkim1" in txt.lower() or "p=" in txt:
                    out["dkim_status"] = "pass"
                    out["dkim_selector"] = selector
                    break
        except Exception:
            # A missing selector is the normal case — keep trying the rest.
            continue
        if out["dkim_status"] == "pass":
            break

    return out


def _probe_smtp(host: str, timeout: int = 8) -> bool:
    """Open an SMTP connection and read the greeting. True if it responds."""
    import smtplib

    with smtplib.SMTP(host, 25, timeout=timeout) as smtp:
        code = smtp.noop()[0]
        return 200 <= code < 400


def check_smtp(domain: str, *, resolve_mx=None, probe=None) -> dict:
    """Check a domain's mail setup. Returns {'smtp_status', 'mx_hosts'}.

    smtp_status: ok / unreachable / no_mx / error. Never raises.
    `resolve_mx` and `probe` are injectable for testing.
    """
    resolve_mx = resolve_mx or _resolve_mx
    probe = probe or _probe_smtp
    try:
        hosts = resolve_mx(domain)
    except Exception as exc:
        logger.warning("MX resolution failed for %s: %s", domain, exc)
        return {"smtp_status": "error", "mx_hosts": []}
    if not hosts:
        return {"smtp_status": "no_mx", "mx_hosts": []}
    for host in hosts[:3]:
        try:
            if probe(host):
                return {"smtp_status": "ok", "mx_hosts": hosts}
        except Exception:
            continue
    return {"smtp_status": "unreachable", "mx_hosts": hosts}


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
