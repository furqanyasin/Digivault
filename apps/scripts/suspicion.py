"""Flag scripts that look like injected or malicious code.

Pure functions over a script URL — no DB access, no network — so this is cheap to
unit test and cheap to run over every script on every ingest.

This is deliberately **heuristic and advisory**, not a verdict. Stacks Monitor sees a
URL and where it was loaded from, not the script body, so it cannot prove intent.
Every signal here is something a human should look at, and the reasons are always
reported alongside the flag so nobody has to trust a bare "suspicious" label.

False positives are the expected failure mode and are much cheaper than false
negatives: a legitimate script wrongly flagged costs one glance, whereas missed
injected code costs a client's search ranking or their customers' card details.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Free hosts and shorteners that legitimate site tooling essentially never serves
# production JavaScript from, but injected code frequently does — they are free,
# disposable, and hide the real origin.
_BAD_HOSTS = re.compile(
    r"(?:^|\.)(?:"
    r"bit\.ly|tinyurl\.com|is\.gd|t\.co|goo\.gl|ow\.ly|cutt\.ly|rebrand\.ly"
    r"|000webhostapp\.com|weebly\.com|blogspot\.com|herokuapp\.com"
    r"|pages\.dev|workers\.dev|repl\.co|glitch\.me|ngrok\.io|trycloudflare\.com"
    r")$",
    re.I,
)

# A bare IP address as a script host. Legitimate CDNs use names; an IP avoids
# DNS-based blocklists and certificate scrutiny.
_IP_HOST = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")

# Data and javascript URIs carry the payload inline, which is how obfuscated
# injections avoid an external request that a monitor might notice.
_INLINE_URI = re.compile(r"^\s*(?:data:|javascript:|blob:)", re.I)

# Hallmarks of obfuscated payloads in the URL itself.
_OBFUSCATION = re.compile(r"(?:eval\(|atob\(|fromCharCode|unescape\(|%3Cscript)", re.I)

# Long random-looking hostname labels — typical of algorithmically generated
# domains used by injection campaigns.
_DGA_LABEL = re.compile(r"^[a-z0-9]{16,}$", re.I)

# Wording that shows up in SEO-spam and pharma-hack injections.
_SPAM_WORDS = re.compile(
    r"(?:viagra|cialis|casino|porn|payday[-_]?loan|replica[-_]?watch|essay[-_]?writ)",
    re.I,
)

# Known-good hosts that would otherwise trip a rule below. Cloudflare Workers,
# for instance, is a legitimate place to host a tag — but only on a subdomain the
# site owner controls, which we cannot tell apart, so this list stays explicit.
_ALLOWED = re.compile(
    r"(?:^|\.)(?:"
    r"googletagmanager\.com|google-analytics\.com|googleapis\.com|gstatic\.com"
    r"|facebook\.net|connect\.facebook\.net|hotjar\.com|stripe\.com"
    r"|jsdelivr\.net|unpkg\.com|cdnjs\.cloudflare\.com|cloudflareinsights\.com"
    r"|hubspot\.com|hs-scripts\.com|intercom\.io|intercomcdn\.com"
    r"|clarity\.ms|bing\.com|doubleclick\.net|adservice\.google\.com"
    r")$",
    re.I,
)

# Severity mirrors ScriptChange.Severity so the UI can reuse its styling.
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"


@dataclass(frozen=True)
class SuspicionResult:
    """Whether a script looks injected, and why."""

    is_suspicious: bool
    severity: str = ""
    reasons: tuple[str, ...] = field(default_factory=tuple)


_CLEAN = SuspicionResult(is_suspicious=False)


def _host_of(src_url: str) -> str:
    """Hostname from a URL, tolerating protocol-relative and malformed input."""
    from urllib.parse import urlparse

    candidate = src_url.strip()
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"
    try:
        return (urlparse(candidate).hostname or "").lower()
    except ValueError:
        return ""


def analyse(src_url: str, *, site_domain: str = "") -> SuspicionResult:
    """Assess one script URL. Never raises.

    `site_domain` is the site the script was found on; a script served from the
    site's own domain is held to a lower bar, since that is where its own theme
    and plugin code lives.
    """
    if not src_url:
        return _CLEAN

    reasons: list[str] = []
    severity = SEVERITY_LOW

    # Inline payloads — highest confidence signal we have.
    if _INLINE_URI.match(src_url):
        reasons.append("Loads code from an inline data/javascript URI")
        severity = SEVERITY_HIGH

    if _OBFUSCATION.search(src_url):
        reasons.append("URL contains obfuscation markers (eval/atob/fromCharCode)")
        severity = SEVERITY_HIGH

    if _SPAM_WORDS.search(src_url):
        reasons.append("URL contains SEO-spam keywords")
        severity = SEVERITY_HIGH

    host = _host_of(src_url)
    if host and not _ALLOWED.search(host):
        if _IP_HOST.match(host):
            reasons.append("Served from a bare IP address rather than a hostname")
            severity = SEVERITY_HIGH
        elif _BAD_HOSTS.search(host):
            reasons.append(f"Served from a disposable or shortener host ({host})")
            severity = SEVERITY_HIGH if severity != SEVERITY_HIGH else severity
        else:
            # A long random label is only suspicious off the site's own domain.
            label = host.split(".")[0]
            own = site_domain and (host == site_domain or host.endswith(f".{site_domain}"))
            if not own and _DGA_LABEL.match(label):
                reasons.append(f"Hostname looks machine-generated ({host})")
                severity = SEVERITY_MEDIUM if severity == SEVERITY_LOW else severity

    if not reasons:
        return _CLEAN
    return SuspicionResult(True, severity, tuple(reasons))
