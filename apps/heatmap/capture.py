"""Full-page screenshots used as the heatmap's backdrop.

The dashboard needs a picture of the page to draw the overlay on. It used to
frame the live site, which fails for most origins (``X-Frame-Options`` / CSP
``frame-ancestors``) and, even when it works, has no fixed height to align
against. Capturing the page once at a known width and height is what makes a
Hotjar-style overlay possible at all.

**This is the one place Digivault drives a real browser at a customer origin,
and that needs care.** ``apps/common/outbound.py`` exists because every
server-side fetch leaves from one public IP, and the rule there is: one honest
user-agent, a shared per-host budget, and back off when told to. A headless
Chromium does not get an exemption — if anything it is louder, because it also
pulls every image, font and script on the page. So this module:

* takes a token from the **same** per-host bucket as the monitor and the SEO
  checker, so a capture sweep cannot eat the monitoring budget,
* honours the same cooldowns — a host that just 429'd is not screenshotted,
* sets the **Digivault-Monitor user-agent**, not Chrome's. The TLS fingerprint
  really is Chrome's here (it *is* Chrome), which is exactly why the UA must
  stay honest: we want to be allowlistable, not to look like a scraper,
* re-applies the SSRF guard to the URL before navigating.

Playwright is imported lazily and is **not** in ``requirements/base.txt``.
Chromium adds roughly 400MB to an image shared by api/celery/beat, so a
deployment opts in by installing ``playwright`` and running
``playwright install --with-deps chromium``. Without it, capture records
``unavailable`` and the dashboard falls back to the live iframe. Screenshots are
an enhancement to the heatmap, never a prerequisite for it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlsplit

from django.conf import settings

from apps.common.outbound import (
    USER_AGENT,
    cooldown_remaining,
    consume_budget,
    note_blocked,
    note_success,
    registrable_host,
)
from apps.common.ssrf import BlockedURLError, assert_public_url

logger = logging.getLogger(__name__)

# Reference viewports. These are the widths the overlay is rendered at, so they
# must match the frontend's `REFERENCE_WIDTH` for desktop/mobile exactly — the
# heatmap's x axis is a percentage of viewport width, and capturing at a
# different width than we render at reintroduces the misalignment this whole
# module exists to remove.
VIEWPORTS = {
    "desktop": (1280, 800),
    "mobile": (375, 812),
}

# A page taller than this is almost always an infinite-scroll feed; capturing it
# in full would produce a hundred-megabyte PNG for no analytical gain, since the
# heatmap grid only has 100 vertical bands anyway.
MAX_CAPTURE_HEIGHT = 20000

NAV_TIMEOUT_MS = 30000
# Give lazy-loaded imagery and above-the-fold animation a moment to settle after
# the network goes quiet, so the screenshot is not full of empty placeholders.
SETTLE_MS = 1500


class CaptureUnavailable(RuntimeError):
    """Playwright/Chromium is not installed in this deployment."""


def _guard_factory():
    """Build a Playwright route handler that applies the SSRF guard per request.

    Validating only the URL we were handed is not a guard at all. Chromium
    follows redirects inside its own network stack, so a perfectly public page
    can answer 302 with ``Location: http://169.254.169.254/`` (cloud metadata)
    or ``http://127.0.0.1:8000/`` (this very API) and the browser walks straight
    there — the attacker never has to supply an internal URL, only a public one
    that points at one. ``apps/common/outbound.py`` learned this already and
    re-runs the guard on every hop; a headless browser needs the same treatment.

    Subresources are checked too, not just navigations: a screenshot is data
    leaving the network, so an ``<img>`` or ``<iframe>`` pointed at an internal
    address would render internal content into a picture the customer can then
    read back.

    Results are memoised per host:port because the guard resolves DNS, and a
    real page issues dozens of requests to the same few origins.
    """
    verdicts: dict[str, bool] = {}

    def allowed(url: str) -> bool:
        key = urlsplit(url).netloc.lower()
        cached = verdicts.get(key)
        if cached is not None:
            return cached
        try:
            assert_public_url(url)
            verdicts[key] = True
        except BlockedURLError:
            verdicts[key] = False
        except Exception:
            # An unparseable or unresolvable URL is refused, matching the
            # guard's own "unparseable -> refuse" stance.
            verdicts[key] = False
        return verdicts[key]

    return allowed


class CaptureBlocked(RuntimeError):
    """The origin refused us, or we are inside a cooldown for that host."""


@dataclass
class CaptureResult:
    png: bytes
    width: int
    height: int


def capture_available() -> bool:
    """True when this deployment can actually take screenshots."""
    try:
        import playwright.sync_api  # noqa: F401
    except Exception:
        return False
    return True


def capture_page(page_url: str, device: str = "desktop") -> CaptureResult:
    """Screenshot ``page_url`` at the reference viewport for ``device``.

    Raises `CaptureUnavailable` when Chromium is absent, `CaptureBlocked` when
    the host budget or a cooldown says not to fetch, and `BlockedURLError` when
    the URL resolves somewhere private.
    """
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # ImportError, or a broken install
        raise CaptureUnavailable(str(exc)) from exc

    # Same guard the monitor applies. A customer can set any page_url, and the
    # snippet reports whatever URL the browser was on, so this is untrusted.
    assert_public_url(page_url)

    host = registrable_host(page_url)
    remaining = cooldown_remaining(host)
    if remaining:
        raise CaptureBlocked(f"{host} is in cooldown for another {remaining}s")
    if not consume_budget(host):
        raise CaptureBlocked(f"{host} has no outbound budget left")

    width, height = VIEWPORTS.get(device, VIEWPORTS["desktop"])

    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                user_agent=USER_AGENT,
                # Capture at 1x: the stored width/height are CSS pixels and the
                # overlay maps its percentage cells straight onto them.
                device_scale_factor=1,
                is_mobile=device == "mobile",
            )
            # Every request the page makes — the navigation, each redirect hop
            # it follows, and every subresource — is re-checked against the SSRF
            # guard before it leaves. Without this, `assert_public_url` above
            # only ever vetted the first URL.
            allowed = _guard_factory()
            blocked_urls: list[str] = []

            def _route(route, request):
                if allowed(request.url):
                    route.continue_()
                else:
                    blocked_urls.append(request.url)
                    route.abort()

            context.route("**/*", _route)

            page = context.new_page()
            try:
                response = page.goto(
                    page_url, wait_until="networkidle", timeout=NAV_TIMEOUT_MS
                )
            except PlaywrightError as exc:
                if blocked_urls:
                    raise BlockedURLError(
                        f"Navigation reached a non-public address: {blocked_urls[0]}"
                    ) from exc
                raise CaptureBlocked(f"navigation failed: {exc}") from exc

            # The page can land somewhere else entirely via a redirect chain or
            # a client-side location change; the final resting URL gets the same
            # guard as the first one.
            assert_public_url(page.url)

            status = response.status if response is not None else 0
            if status in (403, 429) or status >= 500:
                note_blocked(host)
                raise CaptureBlocked(f"origin returned HTTP {status}")

            page.wait_for_timeout(SETTLE_MS)

            full_height = int(
                page.evaluate(
                    "() => Math.max("
                    "document.documentElement.scrollHeight,"
                    "document.body ? document.body.scrollHeight : 0,"
                    "window.innerHeight)"
                )
                or height
            )
            clipped = min(full_height, MAX_CAPTURE_HEIGHT)
            png = page.screenshot(
                type="png",
                clip={"x": 0, "y": 0, "width": width, "height": clipped},
            )
            note_success(host)
            return CaptureResult(png=png, width=width, height=clipped)
        finally:
            browser.close()


def snapshot_max_age_days() -> int:
    """How long a snapshot stays fresh before it is recaptured."""
    return getattr(settings, "HEATMAP_SNAPSHOT_MAX_AGE_DAYS", 14)


__all__ = [
    "CaptureBlocked",
    "CaptureResult",
    "CaptureUnavailable",
    "BlockedURLError",
    "VIEWPORTS",
    "capture_available",
    "capture_page",
    "snapshot_max_age_days",
]
