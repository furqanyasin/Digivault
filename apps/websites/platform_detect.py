"""Best-effort CMS / site-builder detection from a page's HTML + headers.

Pure functions, no DB or network — the caller fetches the page (the websites
``scan`` action already does) and passes the response in. Returns a
``Website.Platform`` value; falls back to ``OTHER`` when nothing matches.
"""
from __future__ import annotations

import re

# Platform string values mirror websites.models.Website.Platform. Kept as plain
# strings so this module stays import-light and trivially testable.
WORDPRESS = "wordpress"
WEBFLOW = "webflow"
WIX = "wix"
FRAMER = "framer"
SHOPIFY = "shopify"
SQUARESPACE = "squarespace"
OTHER = "other"

_GENERATOR_RE = re.compile(
    r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)

# Ordered most-specific first. Each entry: (platform, html substrings, header hints).
# A platform matches if ANY of its html markers appear OR any header hint is present.
_SIGNATURES = [
    (SHOPIFY, ["cdn.shopify.com", "shopify.theme", "/cdn/shop/"], ["x-shopid", "x-shopify-stage"]),
    (WIX, ["static.wixstatic.com", "wix.com", "_wixcss", "wixsite.com"], ["x-wix-request-id"]),
    (SQUARESPACE, ["static1.squarespace.com", "squarespace.com", "static.squarespace.com"], ["x-served-by-squarespace"]),
    (WEBFLOW, ["data-wf-page", "data-wf-site", ".webflow.io", "assets.website-files.com"], []),
    (FRAMER, ["framerusercontent.com", "framer.com", "__framer", "data-framer-name"], []),
    # WordPress last among markers but its generator/REST signals are decisive below.
    (WORDPRESS, ["/wp-content/", "/wp-includes/", "wp-json", "wp-emoji", "wp-block-"], []),
]

# generator meta-tag content keyword -> platform
_GENERATOR_MAP = [
    ("wordpress", WORDPRESS),
    ("woocommerce", WORDPRESS),
    ("elementor", WORDPRESS),
    ("wix", WIX),
    ("squarespace", SQUARESPACE),
    ("webflow", WEBFLOW),
    ("framer", FRAMER),
    ("shopify", SHOPIFY),
]


def detect_platform(html: str, headers: dict | None = None) -> str:
    """Return a Website.Platform value for the given page, or ``OTHER``.

    ``headers`` may be any mapping (e.g. ``requests`` response headers); keys are
    matched case-insensitively.
    """
    html = html or ""
    lower_html = html.lower()

    # 1. The <meta name="generator"> tag is the most reliable single signal.
    m = _GENERATOR_RE.search(html)
    if m:
        gen = m.group(1).lower()
        for keyword, platform in _GENERATOR_MAP:
            if keyword in gen:
                return platform

    # 2. Header hints (case-insensitive key match).
    header_keys = {k.lower() for k in (headers or {}).keys()}
    for platform, _markers, header_hints in _SIGNATURES:
        if any(hint in header_keys for hint in header_hints):
            return platform

    # 3. HTML body markers.
    for platform, markers, _hints in _SIGNATURES:
        if any(marker in lower_html for marker in markers):
            return platform

    return OTHER
