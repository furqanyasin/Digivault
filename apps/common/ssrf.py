"""SSRF guard for server-side fetches of user-supplied URLs.

The scan / snippet-verify endpoints fetch a URL the user controls and return
parts of the response. Without a guard, a registered user could point that at
internal addresses (127.0.0.1, the Django API, Redis, other CloudPanel sites,
cloud metadata) and read internal responses. `assert_public_url` blocks any
URL whose host resolves to a private, loopback, link-local, or reserved IP.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class BlockedURLError(ValueError):
    """Raised when a URL targets a non-public / internal address."""


def _ip_is_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable → refuse
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local      # 169.254.0.0/16 — cloud metadata
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified     # 0.0.0.0
    )


def assert_public_url(url: str) -> None:
    """Raise BlockedURLError unless `url` is http(s) and resolves only to
    public IPs. Resolves the hostname and checks every returned address so a
    DNS name that points at an internal IP is also blocked.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise BlockedURLError("Only http(s) URLs are allowed.")
    host = parsed.hostname
    if not host:
        raise BlockedURLError("URL has no host.")

    # Resolve all A/AAAA records; block if ANY is internal.
    try:
        infos = socket.getaddrinfo(host, parsed.port or None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BlockedURLError(f"Could not resolve host: {host}") from exc

    for info in infos:
        ip_str = info[4][0]
        if _ip_is_blocked(ip_str):
            raise BlockedURLError(
                f"URL resolves to a non-public address ({ip_str}) and was blocked."
            )
