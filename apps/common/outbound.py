"""One HTTP client for every server-side fetch of a customer's own site.

Digivault reaches out to client origins from five places — the uptime monitor,
the SEO checker, the homepage scan, the snippet verifier and the WordPress form
sync — and every one of them leaves from the platform's single public IP. Before
this module they each rolled their own headers, none of them shared a rate
budget, and none honoured a 429. The SEO checker alone fetches up to fifteen
pages back-to-back, which reads to any WAF exactly like a scanner sweep. That is
how the IP gets challenged, then blocked, then blacklisted — at which point the
monitor starts reporting healthy sites as down.

Three responsibilities live here so that no caller can forget them:

**Identity.** One honest, stable user-agent, following the shape UptimeRobot
uses. We deliberately do *not* impersonate Chrome: from a single IP a spoofed
browser is caught on TLS fingerprint anyway, it gets that IP banned with no
route to appeal, and it permanently disqualifies us from Cloudflare's Verified
Bots programme. These are our own clients' sites — being allowlistable is worth
far more to us than being sneaky.

**A budget.** A per-host token bucket, keyed on the registrable domain so
``example.com`` and ``www.example.com`` cannot be used to double the rate. It
fails *open*: if Redis is unreachable, monitoring continues rather than stopping.

**Restraint.** A 429 or a ``Retry-After`` puts the host in cooldown; repeated
403s escalate that cooldown exponentially. Continuing to poll a host that has
just told us to back off is the specific behaviour that turns a rate-limit into
a ban.
"""
from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache

from apps.common.ssrf import assert_public_url

logger = logging.getLogger(__name__)

# ── identity ──────────────────────────────────────────────────────────────────

# The "Mozilla/5.0 (compatible; ...)" prefix is not an impersonation — it is the
# convention every well-behaved crawler follows, and it gets us past UA sniffers
# that reject anything not starting with "Mozilla". The +URL is the part that
# matters: it gives a site owner staring at their firewall log something to look
# up, and it is what a WAF vendor needs in order to allowlist us.
USER_AGENT = (
    "Mozilla/5.0 (compatible; Digivault-Monitor/1.0; "
    "+https://digivault.digilatics.co/bot)"
)

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": USER_AGENT,
    # A request with no Accept at all reads as a bot to every bot-management
    # edge, so we send a real one even though we mostly discard the body.
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ── errors ────────────────────────────────────────────────────────────────────

class OutboundError(Exception):
    """Base for refusals raised before any network call is made."""


class RateLimitedError(OutboundError):
    """Our own per-host budget declined this request."""


class HostCoolingDownError(OutboundError):
    """The host asked us to back off and the cooldown has not elapsed."""


# ── budget / backoff tuning ───────────────────────────────────────────────────

DEFAULT_MIN_INTERVAL_SECONDS = 20
DEFAULT_MAX_PER_HOUR = 60
BASE_COOLDOWN_SECONDS = 60
MAX_COOLDOWN_SECONDS = 3600


def _setting(name: str, default):
    return getattr(settings, name, default)


# ── host keying ───────────────────────────────────────────────────────────────

def registrable_host(url: str) -> str:
    """Normalise a URL to the key its rate budget is held under.

    Collapses scheme, port, case and a leading ``www.`` so that a caller cannot
    accidentally (or deliberately) double a host's budget by varying the form of
    the URL. Deeper subdomains stay distinct — ``shop.example.com`` really is a
    different origin, often on different infrastructure.
    """
    host = (urlsplit(url).hostname or url).lower()
    if host.startswith("www."):
        host = host[4:]
    return host


# ── block identification ──────────────────────────────────────────────────────

# Bodies a bot-protection edge or WAF serves in place of the real page. Matching
# any of these means we did not see the customer's HTML, so we cannot conclude
# anything about whether their site is healthy.
BLOCK_PAGE_MARKERS = (
    "just a moment",
    "cf-browser-verification",
    "cf_chl_opt",
    "checking your browser",
    "enable javascript and cookies to continue",
    "attention required! | cloudflare",
    "ddos protection by",
    "403 - forbidden",
    "403 forbidden",
    "access denied",
    "request blocked",
    "you have been blocked",
    "web application firewall",
    "mod_security",
    "are you a human",
    "captcha",
)

# Real pages are bigger than this. Interstitials and error stubs are not.
MIN_PLAUSIBLE_PAGE_BYTES = 1024

# Header fingerprints, checked first because they are unambiguous. Each entry is
# (header name, substring to look for in its lowercased value, vendor). An empty
# substring matches on the header's mere presence.
_HEADER_FINGERPRINTS: tuple[tuple[str, str, str], ...] = (
    ("cf-mitigated", "challenge", "Cloudflare"),
    ("x-sucuri-block", "", "Sucuri"),
    ("x-imunify360-request-id", "", "Imunify360"),
    ("x-amzn-waf-action", "", "AWS WAF"),
    ("x-iinfo", "", "Imperva"),
    ("x-cdn", "incapsula", "Imperva"),
    ("server", "sucuri", "Sucuri"),
    ("server", "mod_security", "ModSecurity"),
    ("server", "cloudflare", "Cloudflare"),
    ("server", "awselb", "AWS WAF"),
    ("server", "akamaighost", "Akamai"),
    ("server", "litespeed", "LiteSpeed"),
)

# Body fingerprints for WAFs that add no distinguishing header — the WordPress
# plugin firewalls, mostly, which run inside PHP and cannot set edge headers.
_BODY_FINGERPRINTS: tuple[tuple[str, str], ...] = (
    ("wordfence", "Wordfence"),
    ("generated by wordfence", "Wordfence"),
    ("mod_security", "ModSecurity"),
    ("imunify360", "Imunify360"),
    ("sucuri website firewall", "Sucuri"),
    ("cloudflare", "Cloudflare"),
)

# Only these codes can be a block. A 500 is the origin failing and must never be
# excused; a 404 is a real missing page.
_BLOCKABLE_CODES = frozenset({401, 403, 406, 429, 503})


def looks_like_block_page(html: str) -> bool:
    """True when the body is an interstitial rather than the site's real page."""
    head = (html or "")[:8192].lower()
    if any(marker in head for marker in BLOCK_PAGE_MARKERS):
        return True
    return len(html or "") < MIN_PLAUSIBLE_PAGE_BYTES


def identify_block(status_code: int, headers: Mapping[str, str], body: str) -> str:
    """Name the WAF that blocked us, or return "" if this is not a block.

    Deliberately conservative in both directions. It refuses to look at 2xx/5xx
    at all — a Cloudflare-fronted site serves its real pages with
    ``server: cloudflare`` too, and a 500 behind Cloudflare is a genuine origin
    outage. And an unattributable 403 stays unattributed: a site that simply
    forbids us is down as far as we can tell, and blanket-excusing every 403
    would let a real misconfiguration hide forever behind a "blocked" badge.
    """
    if status_code not in _BLOCKABLE_CODES:
        return ""

    lowered = {str(k).lower(): str(v).lower() for k, v in (headers or {}).items()}
    for header, needle, vendor in _HEADER_FINGERPRINTS:
        value = lowered.get(header)
        if value is None:
            continue
        if not needle or needle in value:
            return vendor

    head = (body or "")[:8192].lower()
    for needle, vendor in _BODY_FINGERPRINTS:
        if needle in head:
            return vendor

    # No vendor named, but the body is plainly an interstitial rather than a
    # page. Worth flagging as a block without claiming to know who did it.
    if body and looks_like_block_page(body):
        return "an unidentified firewall"

    return ""


# ── per-host budget ───────────────────────────────────────────────────────────

def consume_budget(host: str) -> bool:
    """Take one token for `host`. False means the caller must not fetch.

    Fails open. If the cache is unreachable we allow the request: a monitoring
    platform that stops monitoring because Redis blinked is worse than one that
    briefly polls a little faster than intended.
    """
    min_interval = _setting("OUTBOUND_MIN_INTERVAL_SECONDS", DEFAULT_MIN_INTERVAL_SECONDS)
    max_per_hour = _setting("OUTBOUND_MAX_PER_HOUR", DEFAULT_MAX_PER_HOUR)
    now = time.time()

    try:
        if min_interval:
            last = cache.get(f"outbound:last:{host}")
            if last is not None and (now - float(last)) < min_interval:
                return False

        hour_key = f"outbound:count:{host}:{int(now // 3600)}"
        used = cache.get(hour_key) or 0
        if max_per_hour and used >= max_per_hour:
            return False

        cache.set(f"outbound:last:{host}", now, timeout=max(int(min_interval) * 2, 60))
        cache.set(hour_key, int(used) + 1, timeout=3600)
    except Exception:
        logger.warning("outbound: budget check failed for %s, allowing", host, exc_info=True)
        return True

    return True


# ── per-host backoff ──────────────────────────────────────────────────────────

def _cool_key(host: str) -> str:
    return f"outbound:cool:{host}"


def _strikes_key(host: str) -> str:
    return f"outbound:strikes:{host}"


def cooldown_remaining(host: str) -> int:
    """Seconds left before `host` may be contacted again. 0 means go ahead."""
    try:
        until = cache.get(_cool_key(host))
    except Exception:
        return 0
    if not until:
        return 0
    return max(0, int(float(until) - time.time()))


def _set_cooldown(host: str, seconds: int) -> None:
    seconds = min(int(seconds), MAX_COOLDOWN_SECONDS)
    try:
        cache.set(_cool_key(host), time.time() + seconds, timeout=seconds + 60)
    except Exception:
        logger.warning("outbound: could not set cooldown for %s", host, exc_info=True)


def note_rate_limited(host: str, retry_after: int | None = None) -> None:
    """The host returned 429/503. Respect its Retry-After if it gave us one."""
    _set_cooldown(host, retry_after or BASE_COOLDOWN_SECONDS)


def note_blocked(host: str) -> None:
    """The host blocked us. Escalate the cooldown so we stop making it worse."""
    try:
        strikes = int(cache.get(_strikes_key(host)) or 0) + 1
        cache.set(_strikes_key(host), strikes, timeout=MAX_COOLDOWN_SECONDS)
    except Exception:
        strikes = 1
    _set_cooldown(host, BASE_COOLDOWN_SECONDS * (2 ** (strikes - 1)))


def note_success(host: str) -> None:
    """The host answered normally. Forget the strikes and lift any cooldown."""
    try:
        cache.delete(_cool_key(host))
        cache.delete(_strikes_key(host))
    except Exception:
        pass


# ── fetch ─────────────────────────────────────────────────────────────────────

@dataclass
class FetchResult:
    status_code: int
    body: str
    headers: dict[str, str]
    elapsed_ms: int
    final_url: str

    @property
    def blocked_by(self) -> str:
        return identify_block(self.status_code, self.headers, self.body)


def fetch(
    url: str,
    *,
    method: str = "GET",
    timeout: int = 30,
    extra_headers: Mapping[str, str] | None = None,
    bypass_budget: bool = False,
    read_bytes: int = 65536,
) -> FetchResult:
    """Fetch `url` under the shared identity, budget and backoff rules.

    Raises ``BlockedURLError`` (SSRF guard), ``HostCoolingDownError`` or
    ``RateLimitedError`` *before* touching the network. HTTP error statuses are
    returned as a ``FetchResult``, not raised — a 403 is an answer, and the
    caller needs the headers to work out who sent it.

    `bypass_budget` exists for uptime confirmation re-checks: three requests
    inside a minute during a suspected outage is proportionate, and it is
    bounded at three.
    """
    assert_public_url(url)
    host = registrable_host(url)

    cooling = cooldown_remaining(host)
    if cooling and not bypass_budget:
        raise HostCoolingDownError(f"{host} is in backoff for another {cooling}s")

    if not bypass_budget and not consume_budget(host):
        raise RateLimitedError(f"per-host budget exhausted for {host}")

    headers = dict(DEFAULT_HEADERS)
    if extra_headers:
        headers.update(extra_headers)

    req = urllib.request.Request(url, method=method.upper())
    for key, value in headers.items():
        req.add_header(key, value)

    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(read_bytes).decode("utf-8", errors="ignore")
            result = FetchResult(
                status_code=resp.status,
                body=body,
                headers={k.lower(): v for k, v in resp.headers.items()},
                elapsed_ms=int((time.monotonic() - start) * 1000),
                final_url=resp.geturl(),
            )
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read(read_bytes).decode("utf-8", errors="ignore")
        except Exception:
            pass
        result = FetchResult(
            status_code=exc.code,
            body=body,
            headers={k.lower(): v for k, v in (exc.headers or {}).items()},
            elapsed_ms=int((time.monotonic() - start) * 1000),
            final_url=url,
        )

    _record_outcome(host, result)
    return result


def _record_outcome(host: str, result: FetchResult) -> None:
    """Feed the response back into the backoff state."""
    if result.status_code in (429, 503):
        retry_after = result.headers.get("retry-after")
        seconds = None
        if retry_after and str(retry_after).strip().isdigit():
            seconds = int(str(retry_after).strip())
        note_rate_limited(host, seconds)
        return

    if result.blocked_by:
        note_blocked(host)
        return

    if result.status_code < 400:
        note_success(host)
