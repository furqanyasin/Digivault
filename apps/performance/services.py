"""PageSpeed Insights v5 — wraps Google's free Lighthouse API.

No API key required for light usage (~25 req/100s per IP).
Set PAGESPEED_API_KEY in .env for higher rate limits.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


@dataclass
class PageSpeedResult:
    url: str
    strategy: str
    performance_score: Optional[int] = None
    fcp_ms: Optional[int] = None
    lcp_ms: Optional[int] = None
    cls_score: Optional[float] = None
    tbt_ms: Optional[int] = None
    ttfb_ms: Optional[int] = None
    si_ms: Optional[int] = None
    tti_ms: Optional[int] = None
    inp_ms: Optional[int] = None
    fcp_rating: str = ""
    lcp_rating: str = ""
    cls_rating: str = ""
    tbt_rating: str = ""
    error: str = ""


def _rating(score: Optional[float]) -> str:
    if score is None:
        return ""
    if score >= 0.9:
        return "fast"
    if score >= 0.5:
        return "average"
    return "slow"


def _ms(audit: dict) -> Optional[int]:
    v = audit.get("numericValue")
    return int(round(v)) if v is not None else None


class PageSpeedService:

    @classmethod
    def check(cls, url: str, strategy: str = "mobile") -> PageSpeedResult:
        result = PageSpeedResult(url=url, strategy=strategy)
        try:
            cls._fetch(url, strategy, result)
        except Exception as exc:
            logger.warning("PageSpeed check failed for %s (%s): %s", url, strategy, exc)
            result.error = str(exc)[:500]
        return result

    @classmethod
    def _fetch(cls, url: str, strategy: str, result: PageSpeedResult) -> None:
        import urllib.error
        from django.conf import settings

        params: dict = {"url": url, "strategy": strategy, "category": "performance"}
        api_key = getattr(settings, "PAGESPEED_API_KEY", "") or ""
        if api_key:
            params["key"] = api_key

        endpoint = f"{PSI_ENDPOINT}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(endpoint, headers={"Accept": "application/json"})

        try:
            resp_ctx = urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise RuntimeError(
                    "Google PageSpeed Insights rate limit reached (429). "
                    "Add PAGESPEED_API_KEY to your .env file to get a higher quota. "
                    "Get a free key at: https://developers.google.com/speed/docs/insights/v5/get-started"
                ) from e
            raise

        with resp_ctx as resp:
            raw = json.loads(resp.read().decode("utf-8"))

        lhr = raw.get("lighthouseResult", {})
        audits = lhr.get("audits", {})

        score = lhr.get("categories", {}).get("performance", {}).get("score")
        result.performance_score = int(round(score * 100)) if score is not None else None

        fcp = audits.get("first-contentful-paint", {})
        lcp = audits.get("largest-contentful-paint", {})
        cls_ = audits.get("cumulative-layout-shift", {})
        tbt = audits.get("total-blocking-time", {})
        ttfb = audits.get("server-response-time", {})
        si = audits.get("speed-index", {})
        tti = audits.get("interactive", {})
        inp = audits.get("interaction-to-next-paint", {})

        result.fcp_ms = _ms(fcp)
        result.lcp_ms = _ms(lcp)
        result.tbt_ms = _ms(tbt)
        result.ttfb_ms = _ms(ttfb)
        result.si_ms = _ms(si)
        result.tti_ms = _ms(tti)
        result.inp_ms = _ms(inp)

        cls_val = cls_.get("numericValue")
        result.cls_score = round(cls_val, 3) if cls_val is not None else None

        result.fcp_rating = _rating(fcp.get("score"))
        result.lcp_rating = _rating(lcp.get("score"))
        result.cls_rating = _rating(cls_.get("score"))
        result.tbt_rating = _rating(tbt.get("score"))


# ── Chrome UX Report (CrUX) ──────────────────────────────────────────────────

CRUX_ENDPOINT = "https://chromeuxreport.googleapis.com/v1/records:queryRecord"

CRUX_METRICS = [
    "largest_contentful_paint",
    "first_contentful_paint",
    "cumulative_layout_shift",
    "interaction_to_next_paint",
    "experimental_time_to_first_byte",
    "first_input_delay",
]


@dataclass
class CruxResult:
    origin: str
    lcp_p75_ms: Optional[int] = None
    fcp_p75_ms: Optional[int] = None
    cls_p75: Optional[float] = None
    inp_p75_ms: Optional[int] = None
    ttfb_p75_ms: Optional[int] = None
    fid_p75_ms: Optional[int] = None
    lcp_good: Optional[float] = None
    lcp_ni: Optional[float] = None
    lcp_poor: Optional[float] = None
    fcp_good: Optional[float] = None
    fcp_ni: Optional[float] = None
    fcp_poor: Optional[float] = None
    cls_good: Optional[float] = None
    cls_ni: Optional[float] = None
    cls_poor: Optional[float] = None
    inp_good: Optional[float] = None
    inp_ni: Optional[float] = None
    inp_poor: Optional[float] = None
    error: str = ""


def _p75(metric_data: dict) -> Optional[float]:
    return metric_data.get("percentiles", {}).get("p75")


def _dist(metric_data: dict) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Return (good, needs_improvement, poor) fractions (0-1) or None."""
    histo = metric_data.get("histogram", [])
    if len(histo) < 3:
        return None, None, None
    return histo[0].get("density"), histo[1].get("density"), histo[2].get("density")


class CruxService:

    @classmethod
    def fetch(cls, url: str) -> CruxResult:
        from urllib.parse import urlparse
        parsed = urlparse(url if "://" in url else f"https://{url}")
        origin = f"{parsed.scheme}://{parsed.netloc}"
        result = CruxResult(origin=origin)
        try:
            cls._fetch(origin, result)
        except Exception as exc:
            logger.warning("CrUX fetch failed for %s: %s", origin, exc)
            result.error = str(exc)[:500]
        return result

    @classmethod
    def _fetch(cls, origin: str, result: CruxResult) -> None:
        from django.conf import settings as _settings
        api_key = getattr(_settings, "PAGESPEED_API_KEY", "") or ""
        endpoint = f"{CRUX_ENDPOINT}?key={api_key}" if api_key else CRUX_ENDPOINT
        payload = json.dumps({"origin": origin, "metrics": CRUX_METRICS}).encode()
        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            ctx = urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            if e.code == 404:
                raise RuntimeError(
                    f"No Chrome UX data for {origin}. "
                    "The origin must have sufficient real-user traffic to appear in CrUX."
                ) from e
            raise RuntimeError(f"CrUX API HTTP {e.code}: {body[:200]}") from e

        with ctx as resp:
            raw = json.loads(resp.read().decode("utf-8"))

        metrics = raw.get("record", {}).get("metrics", {})

        lcp = metrics.get("largest_contentful_paint", {})
        fcp = metrics.get("first_contentful_paint", {})
        cls_ = metrics.get("cumulative_layout_shift", {})
        inp = metrics.get("interaction_to_next_paint", {})
        ttfb = metrics.get("experimental_time_to_first_byte", {})
        fid = metrics.get("first_input_delay", {})

        lcp_p75 = _p75(lcp)
        result.lcp_p75_ms = int(round(lcp_p75)) if lcp_p75 is not None else None

        fcp_p75 = _p75(fcp)
        result.fcp_p75_ms = int(round(fcp_p75)) if fcp_p75 is not None else None

        cls_p75 = _p75(cls_)
        result.cls_p75 = round(float(cls_p75), 3) if cls_p75 is not None else None

        inp_p75 = _p75(inp)
        result.inp_p75_ms = int(round(inp_p75)) if inp_p75 is not None else None

        ttfb_p75 = _p75(ttfb)
        result.ttfb_p75_ms = int(round(ttfb_p75)) if ttfb_p75 is not None else None

        fid_p75 = _p75(fid)
        result.fid_p75_ms = int(round(fid_p75)) if fid_p75 is not None else None

        result.lcp_good, result.lcp_ni, result.lcp_poor = _dist(lcp)
        result.fcp_good, result.fcp_ni, result.fcp_poor = _dist(fcp)
        result.cls_good, result.cls_ni, result.cls_poor = _dist(cls_)
        result.inp_good, result.inp_ni, result.inp_poor = _dist(inp)
