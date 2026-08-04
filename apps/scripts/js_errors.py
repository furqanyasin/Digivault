"""Helpers for JavaScript error capture.

Pure functions: fingerprinting, browser labelling and noise filtering. Kept out
of the view so each can be unit tested without a request.
"""

from __future__ import annotations

import hashlib
import re

# Errors that say nothing actionable. "Script error." is what browsers report for
# any exception thrown by a cross-origin script without CORS headers — it carries
# no message, file or line, so storing it only adds noise.
_NOISE = (
    "script error.",
    "script error",
    "resizeobserver loop limit exceeded",
    "resizeobserver loop completed with undelivered notifications.",
    "non-error promise rejection captured",
)

# Extension schemes — an error thrown by the visitor's own browser extension is
# not the site's bug and must not be reported as one.
_EXTENSION_SOURCE = re.compile(
    r"^(?:chrome-extension|moz-extension|safari-extension|safari-web-extension)://",
    re.I,
)

_BROWSERS = (
    ("Edg/", "Edge"),
    ("OPR/", "Opera"),
    ("Chrome/", "Chrome"),
    ("Firefox/", "Firefox"),
    ("Safari/", "Safari"),
)


def is_reportable(message: str, source_url: str = "") -> bool:
    """False for errors that are noise or not the site's fault."""
    if not (message or "").strip():
        return False
    if message.strip().lower() in _NOISE:
        return False
    if source_url and _EXTENSION_SOURCE.match(source_url.strip()):
        return False
    return True


def fingerprint(message: str, source_url: str = "", line_no: int | None = None) -> str:
    """Stable identity for an error so repeats collapse onto one row.

    Deliberately excludes the column number and the page URL: the same bug fires
    at slightly different columns after a re-minify, and on every page of the
    site, but it is still one bug to fix.
    """
    # Numbers inside the message are normalised away — ids and timestamps in an
    # error string would otherwise make every occurrence unique.
    normalised = re.sub(r"\d+", "#", (message or "").strip().lower())[:300]
    basis = f"{normalised}|{(source_url or '').strip()}|{line_no if line_no is not None else ''}"
    return hashlib.sha256(basis.encode("utf-8", "replace")).hexdigest()[:40]


def browser_label(user_agent: str) -> str:
    """Coarse browser name from a UA string.

    Only the family, never the full UA: the point is spotting a browser-specific
    break, and a full UA string is a fingerprinting surface we have no need for.
    """
    ua = user_agent or ""
    for token, name in _BROWSERS:
        if token in ua:
            return name
    return ""
