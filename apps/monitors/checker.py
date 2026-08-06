"""Monitor check execution logic.

Each check_* function performs one health check and returns a dict:
    {
        "status": "up" | "down" | "degraded",
        "response_time_ms": int | None,
        "status_code": int | None,
        "error_message": str,
    }
"""

import socket
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone as dt_timezone
from urllib.parse import urlsplit

# Edge networks answer clients that fail their bot heuristics with a challenge
# instead of the page. The edge is healthy and real visitors are being served,
# so this is not an outage — but the origin behind it was never consulted, so
# it is not a clean "up" either. Reported as degraded with a fix in the message.
_CHALLENGE_SERVERS = {"cloudflare", "sucuri/cloudproxy"}

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


def _challenge_message(status_code: int, resp_headers) -> str:
    """Return an operator-actionable message if this looks like a bot challenge."""
    if status_code not in (401, 403, 429):
        return ""

    get = getattr(resp_headers, "get", lambda *_: None)
    mitigated = (get("cf-mitigated") or "").strip().lower()
    server = (get("server") or "").strip().lower()

    if mitigated == "challenge" or (status_code == 403 and server in _CHALLENGE_SERVERS):
        edge = server or "the CDN"
        return (
            f"Blocked by {edge} bot protection (HTTP {status_code}) — the edge "
            "responded, so the site is serving visitors, but the origin could not "
            "be verified. Allowlist the monitor, or set the expected status to "
            f"{status_code}."
        )
    return ""


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


def check_http(url: str, method: str = "GET", expected_status: int = 200,
               timeout: int = 30, headers: dict | None = None,
               keyword: str = "") -> dict:
    start = time.monotonic()
    try:
        req = urllib.request.Request(url, method=method)
        req.add_header("User-Agent", "Digivault-Monitor/1.0")
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed = int((time.monotonic() - start) * 1000)
            body = resp.read(4096).decode("utf-8", errors="ignore")
            code = resp.status

        if keyword and keyword not in body:
            return {
                "status": "down",
                "response_time_ms": elapsed,
                "status_code": code,
                "error_message": f"Keyword '{keyword}' not found in response",
            }

        if code == expected_status:
            return {"status": "up", "response_time_ms": elapsed, "status_code": code, "error_message": ""}
        elif 200 <= code < 400:
            return {"status": "degraded", "response_time_ms": elapsed, "status_code": code, "error_message": f"Got {code}, expected {expected_status}"}
        else:
            return {"status": "down", "response_time_ms": elapsed, "status_code": code, "error_message": f"HTTP {code}"}

    except urllib.error.HTTPError as e:
        # urlopen raises on every 4xx/5xx, so expected_status has to be honoured
        # here too — otherwise a monitor set to expect 401/403/429 can never
        # report up, and the setting silently does nothing.
        elapsed = int((time.monotonic() - start) * 1000)
        if e.code == expected_status:
            return {"status": "up", "response_time_ms": elapsed, "status_code": e.code, "error_message": ""}

        challenge = _challenge_message(e.code, e.headers)
        if challenge:
            return {"status": "degraded", "response_time_ms": elapsed, "status_code": e.code, "error_message": challenge}

        origin_error = _CLOUDFLARE_ORIGIN_ERRORS.get(e.code)
        if origin_error:
            message = f"HTTP {e.code}: Cloudflare reached, but the {origin_error}"
        else:
            message = f"HTTP {e.code}: {e.reason}" if e.reason else f"HTTP {e.code}"

        return {"status": "down", "response_time_ms": elapsed, "status_code": e.code, "error_message": message[:300]}

    except urllib.error.URLError as e:
        return {"status": "down", "response_time_ms": None, "status_code": None,
                "error_message": _transport_message(e.reason, url, timeout)[:300]}
    except Exception as e:
        return {"status": "down", "response_time_ms": None, "status_code": None,
                "error_message": _transport_message(e, url, timeout)[:300]}


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


def check_ssl(host: str, timeout: int = 10) -> dict:
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
        return {"status": "down", "response_time_ms": None, "status_code": None, "error_message": f"SSL error: {e}"}
    except Exception as e:
        return {"status": "down", "response_time_ms": None, "status_code": None, "error_message": str(e)[:300]}


def run_check(monitor) -> dict:
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
        )
    elif t == "ping":
        return check_ping(monitor.url, timeout=monitor.timeout)
    elif t == "port":
        return check_port(monitor.url, port=monitor.port or 80, timeout=monitor.timeout)
    elif t == "ssl":
        return check_ssl(monitor.url, timeout=monitor.timeout)
    else:
        return {"status": "down", "response_time_ms": None, "status_code": None, "error_message": f"Unknown monitor type: {t}"}
