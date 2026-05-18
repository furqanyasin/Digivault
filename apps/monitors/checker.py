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
import urllib.request
from datetime import datetime, timezone as dt_timezone


def check_http(url: str, method: str = "GET", expected_status: int = 200,
               timeout: int = 30, headers: dict | None = None,
               keyword: str = "") -> dict:
    try:
        req = urllib.request.Request(url, method=method)
        req.add_header("User-Agent", "Digivault-Monitor/1.0")
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)

        start = time.monotonic()
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
        return {"status": "down", "response_time_ms": None, "status_code": e.code, "error_message": str(e)}
    except Exception as e:
        return {"status": "down", "response_time_ms": None, "status_code": None, "error_message": str(e)[:300]}


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
