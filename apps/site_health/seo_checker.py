"""Pure SEO check helpers + fetch wrapper. Parse functions are network-free."""
from __future__ import annotations

import logging
import re
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

from apps.common.ssrf import assert_public_url

logger = logging.getLogger(__name__)

MAX_PAGES = 10
_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def fetch(url: str, timeout: int = 15):
    """Return (status_code, text, headers_dict). Raises on network/SSRF failure."""
    assert_public_url(url)
    req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read(2_000_000).decode("utf-8", "ignore")
        headers = {k.lower(): v for k, v in resp.headers.items()}
        return resp.status, body, headers


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
