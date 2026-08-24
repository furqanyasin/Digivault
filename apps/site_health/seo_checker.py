"""Pure SEO check helpers + fetch wrapper. Parse functions are network-free."""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

from apps.common import outbound

logger = logging.getLogger(__name__)

MAX_PAGES = 15
_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"

# How long a single page fetch will wait for its slot in the per-host budget
# before giving up. One full spacing window plus a little slack: an SEO scan
# walks up to MAX_PAGES pages of one host, and pacing them is the difference
# between polite traffic and a scanner sweep that gets our IP blocked.
_PACING_WAIT_SECONDS = 25


def fetch(url: str, timeout: int = 15):
    """Return (status_code, text, headers_dict).

    Routed through `apps.common.outbound`, so it shares the platform's single
    honest identity, the per-host budget, the SSRF guard on every redirect hop,
    and the backoff bookkeeping. Unlike the old urllib version this does *not*
    raise on 4xx/5xx — a 404 robots.txt is an answer, and every caller here
    already branches on `status_code == 200`.
    """
    result = outbound.fetch(
        url,
        timeout=timeout,
        wait_up_to=_PACING_WAIT_SECONDS,
        read_bytes=2_000_000,
    )
    return result.status_code, result.body, result.headers


def parse_robots(text: str) -> dict:
    """Parse robots.txt -> {'blocks_all': bool, 'sitemaps': [url, ...]}."""
    sitemaps: list[str] = []
    groups: dict[str, list[tuple[str, str]]] = {}
    current = "*"
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field, value = field.strip().lower(), value.strip()
        if field == "user-agent":
            current = value.lower()
            groups.setdefault(current, [])
        elif field == "sitemap":
            sitemaps.append(value)
        elif field in ("disallow", "allow"):
            groups.setdefault(current, []).append((field, value))
    star = groups.get("*", [])
    disallow_root = any(f == "disallow" and v == "/" for f, v in star)
    allow_root = any(f == "allow" and v == "/" for f, v in star)
    return {"blocks_all": disallow_root and not allow_root, "sitemaps": sitemaps}


def count_sitemap_urls(xml_text: str, fetch_fn=fetch, _depth: int = 0):
    """Return (url_count, [page_url, ...]). Follows <sitemapindex> one level
    deep, bounded to the first 10 child sitemaps."""
    try:
        root = ET.fromstring((xml_text or "").encode("utf-8"))
    except ET.ParseError:
        return 0, []
    tag = root.tag.split("}")[-1]
    if tag == "sitemapindex":
        total, urls = 0, []
        if _depth == 0:
            locs = [el.text.strip() for el in root.findall(f"{_SITEMAP_NS}sitemap/{_SITEMAP_NS}loc") if el.text]
            for child in locs[:10]:
                try:
                    _, body, _h = fetch_fn(child)
                except Exception:
                    continue
                c, u = count_sitemap_urls(body, fetch_fn, _depth + 1)
                total += c
                urls.extend(u)
        return total, urls
    locs = [el.text.strip() for el in root.findall(f"{_SITEMAP_NS}url/{_SITEMAP_NS}loc") if el.text]
    return len(locs), locs


def page_indexability(html: str, x_robots_tag: str = ""):
    """Return (indexable: bool, reason: str)."""
    if "noindex" in (x_robots_tag or "").lower():
        return False, "X-Robots-Tag: noindex"
    m = re.search(r'<meta[^>]+name=["\']robots["\'][^>]*>', html or "", re.I)
    if m and "noindex" in m.group(0).lower():
        return False, "meta robots noindex"
    return True, ""


def same_origin(base: str, candidate: str) -> bool:
    return urlparse(base).netloc == urlparse(candidate).netloc


def _attr(tag: str, name: str) -> str:
    """Extract an attribute value from a single HTML tag string."""
    m = re.search(rf'{name}\s*=\s*"([^"]*)"', tag, re.I) or re.search(
        rf"{name}\s*=\s*'([^']*)'", tag, re.I
    )
    return (m.group(1).strip() if m else "")


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _schema_types(html: str) -> list[str]:
    """Collect schema.org @type values from JSON-LD blocks (handles @graph and
    arrays). Best-effort: malformed JSON blocks are skipped."""
    import json

    types: list[str] = []

    def _collect(node):
        if isinstance(node, dict):
            t = node.get("@type")
            if isinstance(t, str):
                types.append(t)
            elif isinstance(t, list):
                types.extend(str(x) for x in t)
            for key in ("@graph", "mainEntity", "itemListElement"):
                if key in node:
                    _collect(node[key])
        elif isinstance(node, list):
            for item in node:
                _collect(item)

    for m in re.finditer(
        r'<script[^>]+type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html or "", re.I | re.S,
    ):
        try:
            _collect(json.loads(m.group(1).strip()))
        except (ValueError, TypeError):
            continue
    # de-dupe, preserve order
    seen, out = set(), []
    for t in types:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def parse_homepage_meta(html: str) -> dict:
    """Extract on-page SEO signals from a page's HTML. Network-free.

    Returns {meta_title, meta_description, h1, canonical_url, schema_types}.
    """
    html = html or ""

    title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    meta_title = _collapse_ws(_strip_tags(title_m.group(1))) if title_m else ""

    meta_description = ""
    for m in re.finditer(r"<meta\b[^>]*>", html, re.I):
        tag = m.group(0)
        if _attr(tag, "name").lower() == "description":
            meta_description = _collapse_ws(_attr(tag, "content"))
            break

    canonical_url = ""
    for m in re.finditer(r"<link\b[^>]*>", html, re.I):
        tag = m.group(0)
        if "canonical" in _attr(tag, "rel").lower():
            canonical_url = _attr(tag, "href")
            break

    h1_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    h1 = _collapse_ws(_strip_tags(h1_m.group(1))) if h1_m else ""

    return {
        "meta_title": meta_title[:500],
        "meta_description": meta_description[:1000],
        "h1": h1[:500],
        "canonical_url": canonical_url[:2048],
        "schema_types": _schema_types(html),
    }
