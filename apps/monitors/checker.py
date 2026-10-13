"""Monitor check execution logic.

Each check_* function performs one health check and returns a dict:
    {
        "status": "up" | "down" | "degraded" | "blocked",
        "response_time_ms": int | None,
        "status_code": int | None,
        "error_message": str,
    }

`blocked` is the status that matters most here. It means a named WAF answered
instead of the customer's server: we learned nothing about the origin, so the
result is neither up nor down. Folding it into "down" — which is what this
module used to do for every firewall except Cloudflare and Sucuri — is what made
healthy sites page their owners at 3am.
"""

import socket
import ssl
import time
import urllib.error
from datetime import datetime, timezone as dt_timezone
from urllib.parse import urlsplit

from apps.common import outbound
from apps.common.ssrf import BlockedURLError

# Cloudflare's 52x range reports on the origin behind the edge, not on the edge
# itself — a real outage of the customer's server, worth naming precisely.
_CLOUDFLARE_ORIGIN_ERRORS = {
    520: "origin returned an unknown error",
    521: "origin server refused the connection",
    522: "connection to the origin server timed out",
    523: "origin server is unreachable",
    524: "origin server did not respond in time",
    525: "TLS handshake with the origin failed",
    526: "origin server has an invalid certificate",
}

_ALLOWLIST_PAGE = "https://digivault.digilatics.co/bot"


# Where each vendor's allowlist lives, because "allowlist our monitor" is a dead
# end for a vendor that gives its customers no allowlist. SiteGround is the
# case that forced this: its anti-bot has no customer-side setting at all, so
# the only route is its support desk — and "set the expected status to 202"
# would report the site up while it was down, since the challenge page is
# served whatever state the origin is in.
_VENDOR_FIX = {
    "SiteGround": (
        "SiteGround's bot protection has no customer allowlist: open a ticket "
        "with SiteGround support asking them to allowlist our monitor's IP for "
        "this site"
    ),
    "Cloudflare": (
        "In Cloudflare, allowlist our monitor with a WAF custom rule that skips "
        "bot protection for user-agent \"Digivault-Monitor\""
    ),
    "Wordfence": "In Wordfence → Firewall → Blocking, allowlist our monitor's IP",
    "Sucuri": "In the Sucuri dashboard → Access Control, allowlist our monitor's IP",
    "Imunify360": "Ask the host to allowlist our monitor's IP in Imunify360",
}


def _block_message(vendor: str, status_code: int) -> str:
    """Say who stopped us and what the operator can do about it."""
    fix = _VENDOR_FIX.get(vendor) or (
        "Ask the host to allowlist our monitor's IP — an answer this uniform "
        "is usually a server firewall (Imunify360, CSF, ModSecurity) that has "
        "blocked the IP rather than the site being down"
    )
    from apps.common.outbound import egress_ips

    ips = egress_ips()
    ip_text = f"our IP is {', '.join(ips)}" if ips else "our IP"
    return (
        f"Blocked by {vendor} (HTTP {status_code}) — we received the firewall's "
        f"page, not the site's, so this is not an outage. {fix}; {ip_text}. "
        f"Details: {_ALLOWLIST_PAGE}"
    )


def _transport_message(reason, url: str, timeout: int) -> str:
    """Turn an opaque URLError reason into something an operator can act on."""
    host = urlsplit(url).hostname or url

    # socket.timeout is an alias of TimeoutError, so this covers both.
    if isinstance(reason, TimeoutError):
        return f"Timed out after {timeout}s with no response from {host}"
    if isinstance(reason, ssl.SSLCertVerificationError):
        return f"TLS certificate verification failed for {host}: {reason}"
    if isinstance(reason, ssl.SSLError):
        return (
            f"TLS handshake failed with {host} ({reason}) — the host may not serve "
            "HTTPS on this name, or requires a protocol/cipher this client rejects."
        )
    if isinstance(reason, socket.gaierror):
        return f"DNS lookup failed for {host}: {reason}"
    if isinstance(reason, ConnectionRefusedError):
        return f"Connection refused by {host}"
    if isinstance(reason, ConnectionResetError):
        return f"Connection reset by {host}"
    return str(reason)


def _request_shape(method: str, keyword: str, attempt: int) -> tuple[str, dict]:
    """Pick the method and extra headers for this confirmation attempt.

    Each attempt in a confirmation sequence looks different on the wire. A
    single WAF rule can otherwise produce three identical failures in a row and
    manufacture an outage that never happened; three differently-shaped requests
    are much harder to fail identically by accident.

    Attempt 1 prefers HEAD — roughly 95% less bandwidth on the common path,
    which is itself a rate-limit reduction across the whole fleet. A keyword
    monitor always uses GET, because a HEAD has no body to search.
    """
    method = (method or "GET").upper()
    extra: dict[str, str] = {}

    if attempt >= 3:
        extra["Cache-Control"] = "no-cache"

    if keyword or method not in ("GET", "HEAD"):
        return method, extra
    if attempt == 1:
        return "HEAD", extra
    return "GET", extra


def check_http(url: str, method: str = "GET", expected_status: int = 200,
               timeout: int = 30, headers: dict | None = None,
               keyword: str = "", attempt: int = 1) -> dict:
    """One HTTP health check.

    Routed through `apps.common.outbound` so it inherits the platform's single
    honest identity, the SSRF guard on every redirect hop, and the per-host
    backoff bookkeeping. It deliberately bypasses the per-host *budget*: a
    monitor on a 15-minute interval is already far gentler than the bucket, and
    a monitoring platform that skipped checks because a burst caller had spent
    the budget would go blind exactly when it matters.
    """
    effective_method, extra = _request_shape(method, keyword, attempt)
    if headers:
        extra.update(headers)

    try:
        result = outbound.fetch(
            url,
            method=effective_method,
            timeout=timeout,
            extra_headers=extra,
            bypass_budget=True,
        )
        # Some origins reject HEAD outright. That is a quirk of the server, not
        # a fault of the site, so fall back rather than reporting it as one.
        if effective_method == "HEAD" and result.status_code in (405, 501):
            result = outbound.fetch(
                url, method="GET", timeout=timeout,
                extra_headers=extra, bypass_budget=True,
            )
    except BlockedURLError as exc:
        return {"status": "down", "response_time_ms": None, "status_code": None,
                "error_message": str(exc)[:300]}
    except urllib.error.URLError as exc:
        return {"status": "down", "response_time_ms": None, "status_code": None,
                "error_message": _transport_message(exc.reason, url, timeout)[:300]}
    except Exception as exc:
        return {"status": "down", "response_time_ms": None, "status_code": None,
                "error_message": _transport_message(exc, url, timeout)[:300]}

    outcome = _classify_http(result, expected_status, keyword)
    if result.host_fallback:
        # The name we were given is not served but its www twin is. Report the
        # twin's answer, and hand the working URL back so the caller can adopt
        # it instead of failing a handshake on every check.
        outcome["resolved_url"] = outbound.sibling_url(url)
    return outcome


def _classify_http(result, expected_status: int, keyword: str) -> dict:
    code = result.status_code
    elapsed = result.elapsed_ms

    def _keyword_missing():
        return keyword and keyword not in result.body

    # Checked before anything else so a monitor deliberately set to expect
    # 401/403/429 can actually report up, instead of the setting silently doing
    # nothing because urlopen raised on the way past.
    if code == expected_status:
        if _keyword_missing():
            return {"status": "down", "response_time_ms": elapsed, "status_code": code,
                    "error_message": f"Keyword '{keyword}' not found in response"}
        return {"status": "up", "response_time_ms": elapsed, "status_code": code,
                "error_message": ""}

    vendor = result.blocked_by
    if vendor:
        return {"status": "blocked", "response_time_ms": elapsed, "status_code": code,
                "error_message": _block_message(vendor, code)}

    if 200 <= code < 400:
        if _keyword_missing():
            return {"status": "down", "response_time_ms": elapsed, "status_code": code,
                    "error_message": f"Keyword '{keyword}' not found in response"}
        return {"status": "degraded", "response_time_ms": elapsed, "status_code": code,
                "error_message": f"Got {code}, expected {expected_status}"}

    origin_error = _CLOUDFLARE_ORIGIN_ERRORS.get(code)
    message = (
        f"HTTP {code}: Cloudflare reached, but the {origin_error}"
        if origin_error
        else f"HTTP {code}"
    )
    return {"status": "down", "response_time_ms": elapsed, "status_code": code,
            "error_message": message[:300]}


def check_ping(host: str, timeout: int = 10) -> dict:
    """TCP-based reachability check (ICMP requires root; we use socket instead)."""
    # Strip scheme if accidentally included
    host = host.replace("https://", "").replace("http://", "").split("/")[0]
    try:
        start = time.monotonic()
        socket.setdefaulttimeout(timeout)
        socket.gethostbyname(host)
        elapsed = int((time.monotonic() - start) * 1000)
        return {"status": "up", "response_time_ms": elapsed, "status_code": None, "error_message": ""}
    except socket.gaierror as e:
        return {"status": "down", "response_time_ms": None, "status_code": None, "error_message": f"DNS lookup failed: {e}"}
    except Exception as e:
        return {"status": "down", "response_time_ms": None, "status_code": None, "error_message": str(e)[:300]}


def check_port(host: str, port: int, timeout: int = 10) -> dict:
    host = host.replace("https://", "").replace("http://", "").split("/")[0]
    try:
        start = time.monotonic()
        with socket.create_connection((host, port), timeout=timeout):
            elapsed = int((time.monotonic() - start) * 1000)
        return {"status": "up", "response_time_ms": elapsed, "status_code": None, "error_message": ""}
    except ConnectionRefusedError:
        return {"status": "down", "response_time_ms": None, "status_code": None, "error_message": f"Port {port} refused"}
    except Exception as e:
        return {"status": "down", "response_time_ms": None, "status_code": None, "error_message": str(e)[:300]}


def _ssl_twin(url: str) -> str | None:
    """The www-toggled form of an SSL monitor's target, in the form it was given."""
    if url.startswith(("http://", "https://")):
        return outbound.sibling_url(url)
    twin = outbound.sibling_url(f"https://{url}")
    return twin[len("https://"):] if twin else None


def check_ssl(host: str, timeout: int = 10) -> dict:
    result = _check_ssl(host, timeout)
    if result["status"] != "down" or not result.pop("name_failure", False):
        return result
    # Same rule as check_http: a certificate served on only one of example.com
    # and www.example.com is the site's setup, and the twin's certificate is the
    # one visitors actually get.
    twin = _ssl_twin(host)
    if twin is None:
        return result
    twin_result = _check_ssl(twin, timeout)
    if twin_result.pop("name_failure", False):
        return result
    twin_result["resolved_url"] = twin
    return twin_result


def _check_ssl(host: str, timeout: int = 10) -> dict:
    host = host.replace("https://", "").replace("http://", "").split("/")[0]
    try:
        ctx = ssl.create_default_context()
        start = time.monotonic()
        with ctx.wrap_socket(socket.create_connection((host, 443), timeout=timeout), server_hostname=host) as s:
            elapsed = int((time.monotonic() - start) * 1000)
            cert = s.getpeercert()

        # Parse expiry
        expiry_str = cert.get("notAfter", "")
        if expiry_str:
            expiry = datetime.strptime(expiry_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=dt_timezone.utc)
            days_left = (expiry - datetime.now(dt_timezone.utc)).days
            if days_left <= 0:
                return {"status": "down", "response_time_ms": elapsed, "status_code": None, "error_message": "SSL certificate expired"}
            if days_left <= 7:
                return {"status": "down", "response_time_ms": elapsed, "status_code": None, "error_message": f"SSL expires in {days_left} days"}
            if days_left <= 30:
                return {"status": "degraded", "response_time_ms": elapsed, "status_code": None, "error_message": f"SSL expires in {days_left} days"}
        return {"status": "up", "response_time_ms": elapsed, "status_code": None, "error_message": ""}
    except ssl.SSLError as e:
        return {"status": "down", "response_time_ms": None, "status_code": None,
                "error_message": f"SSL error: {e}", "name_failure": True}
    except (socket.gaierror, ConnectionRefusedError) as e:
        return {"status": "down", "response_time_ms": None, "status_code": None,
                "error_message": str(e)[:300], "name_failure": True}
    except Exception as e:
        return {"status": "down", "response_time_ms": None, "status_code": None, "error_message": str(e)[:300]}


def run_check(monitor, attempt: int = 1) -> dict:
    """Dispatch to the correct checker based on monitor type."""
    t = monitor.monitor_type
    if t == "http":
        return check_http(
            monitor.url,
            method=monitor.request_method,
            expected_status=monitor.expected_status_code,
            timeout=monitor.timeout,
            headers=monitor.request_headers or {},
            keyword=monitor.keyword or "",
            attempt=attempt,
        )
    elif t == "ping":
        return check_ping(monitor.url, timeout=monitor.timeout)
    elif t == "port":
        return check_port(monitor.url, port=monitor.port or 80, timeout=monitor.timeout)
    elif t == "ssl":
        return check_ssl(monitor.url, timeout=monitor.timeout)
    else:
        return {"status": "down", "response_time_ms": None, "status_code": None, "error_message": f"Unknown monitor type: {t}"}
