# SEO Health (Robots + Sitemap + Index/noindex) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-website SEO health checks (robots.txt, sitemap.xml, index/noindex on homepage + key pages) with a configurable scan cadence, regression alerts, and an SEO tab.

**Architecture:** Pure parse/check functions in `apps/site_health/seo_checker.py` (testable without network) wrapped by a `run_seo_check` Celery task that fetches via the existing SSRF guard, persists a one-per-website `SeoReport`, and emits `SiteEvent` + channel notifications on regressions. A configurable `Website.seo_scan_interval_days` drives a daily `run_due_seo_checks` beat task; the check also runs inside the existing `scan` action and on demand. A React `seo-tab.tsx` surfaces it.

**Tech Stack:** Django 5.1 + DRF, Celery (`@shared_task`), urllib + `apps/common/ssrf.py`, stdlib `xml.etree`, Next.js 16 App Router, pytest.

---

## Reference facts (verified against the codebase)

- SSRF guard: `from apps.common.ssrf import assert_public_url, BlockedURLError` (used in [apps/websites/views.py](../../../apps/websites/views.py)).
- Tasks are `@shared_task(name="site_health.<func>")` ([apps/site_health/tasks.py:40](../../../apps/site_health/tasks.py#L40)).
- Website-scoped endpoints mount at `/api/v1/websites/<uuid:website_pk>/` via `site_health` `website_urlpatterns` ([apps/site_health/urls.py](../../../apps/site_health/urls.py)).
- View pattern: `generics.get_object_or_404(Website, pk=website_pk, team=request.user.active_team)` + `[permissions.IsAuthenticated, IsTeamMember]` ([apps/site_health/views.py:131](../../../apps/site_health/views.py#L131)).
- Channel delivery pattern: `NotificationChannel.objects.filter(team=team, is_active=True)`, `channel.channel_type`, `channel.config` ([apps/domains/notifications.py](../../../apps/domains/notifications.py)).
- Beat schedule lives in `config/settings/base.py` `CELERY_BEAT_SCHEDULE` (uses `crontab`).
- Authed Next proxy pattern: cookie `ss_access` → `Authorization: Bearer`; unwrap `envelope?.data ?? envelope` ([scan route](../../../frontend/src/app/api/websites/[id]/scan/route.ts)).
- Tests: `config.settings.test`, locmem cache, `--create-db` after model changes. Run with `./.venv/Scripts/python.exe -m pytest` (bare `pytest` may hit the wrong venv).

---

## Task 1: `Website.seo_scan_interval_days` field

**Files:**
- Modify: `apps/websites/models.py` (Website model)
- Test: `tests/site_health/test_seo.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/site_health/test_seo.py`:

```python
import pytest

from apps.websites.models import Website


@pytest.mark.django_db
def test_website_seo_interval_defaults_to_off(team):
    w = Website.objects.create(team=team, name="S", domain="seo-test.example")
    assert w.seo_scan_interval_days == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/site_health/test_seo.py::test_website_seo_interval_defaults_to_off -v`
Expected: FAIL — `AttributeError`/no such field.

- [ ] **Step 3: Add the field**

In `apps/websites/models.py`, inside the `Website` model, add:

```python
    SEO_INTERVAL_CHOICES = [
        (0, "Off"),
        (3, "Every 3 days"),
        (7, "Every 7 days"),
        (14, "Every 14 days"),
        (30, "Every 30 days"),
    ]
    seo_scan_interval_days = models.PositiveSmallIntegerField(
        choices=SEO_INTERVAL_CHOICES, default=0,
        help_text="How often to auto-run the SEO health check. 0 = off.",
    )
```

- [ ] **Step 4: Make + run migration, verify test passes**

Run:
```
./.venv/Scripts/python.exe manage.py makemigrations websites
./.venv/Scripts/python.exe -m pytest tests/site_health/test_seo.py::test_website_seo_interval_defaults_to_off -v --create-db
```
Expected: migration created; test PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/websites/models.py apps/websites/migrations/ tests/site_health/test_seo.py
git commit -m "feat(websites): add seo_scan_interval_days field"
```

---

## Task 2: `SeoReport` model + serializer

**Files:**
- Modify: `apps/site_health/models.py`
- Modify: `apps/site_health/serializers.py`
- Test: `tests/site_health/test_seo.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/site_health/test_seo.py`:

```python
from apps.site_health.models import SeoReport


@pytest.mark.django_db
def test_seo_report_defaults(team):
    w = Website.objects.create(team=team, name="S2", domain="seo2.example")
    r = SeoReport.objects.create(website=w)
    assert r.check_status == "never"
    assert r.robots_status == "unknown"
    assert r.sitemap_status == "unknown"
    assert r.homepage_indexable is None
    assert r.pages_checked == []
    assert r.noindex_count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/site_health/test_seo.py::test_seo_report_defaults -v`
Expected: FAIL — cannot import `SeoReport`.

- [ ] **Step 3: Add the model**

In `apps/site_health/models.py`, append:

```python
class SeoReport(BaseModel):
    """One-per-website snapshot of robots/sitemap/indexability health."""

    website = models.OneToOneField(
        "websites.Website", on_delete=models.CASCADE, related_name="seo_report"
    )
    last_checked_at = models.DateTimeField(null=True, blank=True)
    check_status = models.CharField(max_length=20, default="never")  # never/running/done/failed
    error = models.TextField(blank=True)

    robots_status = models.CharField(max_length=20, default="unknown")  # found/missing/error
    robots_blocks_all = models.BooleanField(default=False)

    sitemap_status = models.CharField(max_length=20, default="unknown")  # found/missing/error
    sitemap_url = models.CharField(max_length=2048, blank=True)
    sitemap_url_count = models.PositiveIntegerField(default=0)

    homepage_indexable = models.BooleanField(null=True, blank=True)
    pages_checked = models.JSONField(default=list)  # [{"url","indexable","reason"}]
    noindex_count = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"SeoReport({self.website})"
```

- [ ] **Step 4: Add the serializer**

In `apps/site_health/serializers.py`, add (mirroring `SiteScanStateSerializer`):

```python
class SeoReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = SeoReport
        fields = (
            "last_checked_at", "check_status", "error",
            "robots_status", "robots_blocks_all",
            "sitemap_status", "sitemap_url", "sitemap_url_count",
            "homepage_indexable", "pages_checked", "noindex_count",
        )
```

Add `SeoReport` to the models import at the top of `serializers.py`.

- [ ] **Step 5: Migrate + verify**

Run:
```
./.venv/Scripts/python.exe manage.py makemigrations site_health
./.venv/Scripts/python.exe -m pytest tests/site_health/test_seo.py::test_seo_report_defaults -v --create-db
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/site_health/models.py apps/site_health/serializers.py apps/site_health/migrations/ tests/site_health/test_seo.py
git commit -m "feat(site_health): add SeoReport model + serializer"
```

---

## Task 3: `SiteEvent` SEO event types

**Files:**
- Modify: `apps/site_health/models.py` (`SiteEvent.EventType`)

- [ ] **Step 1: Add the choices**

In `apps/site_health/models.py`, in `SiteEvent.EventType`, add:

```python
        SEO_NOINDEX_DETECTED = "seo_noindex_detected", "SEO: noindex detected"
        SEO_ROBOTS_BLOCK = "seo_robots_block", "SEO: robots.txt blocks all"
        SEO_SITEMAP_MISSING = "seo_sitemap_missing", "SEO: sitemap missing"
```

- [ ] **Step 2: Migrate**

Run: `./.venv/Scripts/python.exe manage.py makemigrations site_health`
Expected: a migration altering `SiteEvent.event_type` choices.

- [ ] **Step 3: Commit**

```bash
git add apps/site_health/models.py apps/site_health/migrations/
git commit -m "feat(site_health): add SEO SiteEvent types"
```

---

## Task 4: Pure check functions in `seo_checker.py`

**Files:**
- Create: `apps/site_health/seo_checker.py`
- Test: `tests/site_health/test_seo_checker.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/site_health/test_seo_checker.py`:

```python
from apps.site_health.seo_checker import (
    count_sitemap_urls,
    page_indexability,
    parse_robots,
)


def test_parse_robots_blocks_all():
    r = parse_robots("User-agent: *\nDisallow: /")
    assert r["blocks_all"] is True


def test_parse_robots_open_with_sitemap():
    r = parse_robots("User-agent: *\nDisallow:\nSitemap: https://x.com/sitemap.xml")
    assert r["blocks_all"] is False
    assert r["sitemaps"] == ["https://x.com/sitemap.xml"]


def test_parse_robots_allow_overrides_disallow_root():
    r = parse_robots("User-agent: *\nDisallow: /\nAllow: /")
    assert r["blocks_all"] is False


def test_count_sitemap_urlset():
    xml = (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://x.com/a</loc></url>"
        "<url><loc>https://x.com/b</loc></url>"
        "</urlset>"
    )
    count, urls = count_sitemap_urls(xml, fetch_fn=lambda u: (200, "", {}))
    assert count == 2
    assert urls == ["https://x.com/a", "https://x.com/b"]


def test_count_sitemap_index_aggregates_children():
    index = (
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<sitemap><loc>https://x.com/s1.xml</loc></sitemap>"
        "</sitemapindex>"
    )
    child = (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://x.com/a</loc></url>"
        "</urlset>"
    )
    count, urls = count_sitemap_urls(index, fetch_fn=lambda u: (200, child, {}))
    assert count == 1
    assert urls == ["https://x.com/a"]


def test_page_indexability_meta_noindex():
    indexable, reason = page_indexability('<meta name="robots" content="noindex,follow">')
    assert indexable is False
    assert "meta" in reason


def test_page_indexability_header_noindex():
    indexable, reason = page_indexability("<html></html>", x_robots_tag="noindex")
    assert indexable is False
    assert "X-Robots-Tag" in reason


def test_page_indexability_default_true():
    indexable, reason = page_indexability("<html><head></head></html>")
    assert indexable is True
    assert reason == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/site_health/test_seo_checker.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the module**

Create `apps/site_health/seo_checker.py`:

```python
"""Pure SEO check helpers + fetch wrapper. Parse functions are network-free."""
from __future__ import annotations

import logging
import re
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/site_health/test_seo_checker.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/site_health/seo_checker.py tests/site_health/test_seo_checker.py
git commit -m "feat(site_health): pure robots/sitemap/indexability check functions"
```

---

## Task 5: Regression notifications helper

**Files:**
- Create: `apps/site_health/notifications.py`

- [ ] **Step 1: Implement the helper** (delivery mirrors `apps/domains/notifications.py`)

Create `apps/site_health/notifications.py`:

```python
"""Deliver SEO regression alerts to a team's notification channels."""
from __future__ import annotations

import json
import logging
import urllib.request

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def notify_team(team, subject: str, body: str) -> None:
    """Best-effort delivery to every active channel for the team."""
    from apps.monitors.models import NotificationChannel

    for ch in NotificationChannel.objects.filter(team=team, is_active=True):
        try:
            if ch.channel_type == "email":
                addrs = ch.config.get("addresses", [])
                if addrs:
                    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, addrs, fail_silently=True)
            elif ch.channel_type == "clickup":
                token, task_id = ch.config.get("api_token", ""), ch.config.get("task_id", "")
                if token and task_id:
                    data = json.dumps({"comment_text": f"**{subject}**\n{body}"}).encode()
                    req = urllib.request.Request(
                        f"https://api.clickup.com/api/v2/task/{task_id}/comment",
                        data=data,
                        headers={"Content-Type": "application/json", "Authorization": token},
                        method="POST",
                    )
                    urllib.request.urlopen(req, timeout=10).close()
        except Exception:
            logger.exception("SEO alert delivery failed via channel %s", ch.id)
```

- [ ] **Step 2: Commit**

```bash
git add apps/site_health/notifications.py
git commit -m "feat(site_health): SEO regression notification helper"
```

---

## Task 6: `run_seo_check` orchestrator task

**Files:**
- Modify: `apps/site_health/tasks.py`
- Test: `tests/site_health/test_seo_run.py` (new)

- [ ] **Step 1: Write the failing tests** (mock `seo_checker.fetch`)

Create `tests/site_health/test_seo_run.py`:

```python
import pytest

from apps.site_health import seo_checker
from apps.site_health.models import SeoReport, SiteEvent
from apps.site_health.tasks import run_seo_check
from apps.websites.models import Website

ROBOTS_OK = "User-agent: *\nDisallow:\nSitemap: https://seo.example/sitemap.xml"
SITEMAP = (
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>https://seo.example/</loc></url>"
    "</urlset>"
)


def _fake_fetch(pages):
    """pages: dict url -> (status, body, headers)."""
    def _f(url, timeout=15):
        if url in pages:
            return pages[url]
        # default: an indexable HTML page
        return 200, "<html><head></head></html>", {}
    return _f


@pytest.mark.django_db
def test_run_seo_check_healthy(monkeypatch, team):
    w = Website.objects.create(team=team, name="S", domain="seo.example")
    pages = {
        "https://seo.example/robots.txt": (200, ROBOTS_OK, {}),
        "https://seo.example/sitemap.xml": (200, SITEMAP, {}),
        "https://seo.example/": (200, "<html><head></head></html>", {}),
    }
    monkeypatch.setattr(seo_checker, "fetch", _fake_fetch(pages))

    run_seo_check(str(w.pk))

    r = SeoReport.objects.get(website=w)
    assert r.check_status == "done"
    assert r.robots_status == "found"
    assert r.robots_blocks_all is False
    assert r.sitemap_status == "found"
    assert r.sitemap_url_count == 1
    assert r.homepage_indexable is True
    assert r.noindex_count == 0


@pytest.mark.django_db
def test_run_seo_check_detects_noindex_and_alerts(monkeypatch, team):
    w = Website.objects.create(team=team, name="S", domain="seo.example")
    # Baseline healthy run
    healthy = {
        "https://seo.example/robots.txt": (200, ROBOTS_OK, {}),
        "https://seo.example/sitemap.xml": (200, SITEMAP, {}),
        "https://seo.example/": (200, "<html><head></head></html>", {}),
    }
    monkeypatch.setattr(seo_checker, "fetch", _fake_fetch(healthy))
    run_seo_check(str(w.pk))
    assert SiteEvent.objects.filter(website=w).count() == 0  # baseline: no alert

    # Now homepage flips to noindex
    broken = dict(healthy)
    broken["https://seo.example/"] = (200, '<meta name="robots" content="noindex">', {})
    monkeypatch.setattr(seo_checker, "fetch", _fake_fetch(broken))
    run_seo_check(str(w.pk))

    r = SeoReport.objects.get(website=w)
    assert r.homepage_indexable is False
    assert SiteEvent.objects.filter(
        website=w, event_type=SiteEvent.EventType.SEO_NOINDEX_DETECTED
    ).count() == 1


@pytest.mark.django_db
def test_run_seo_check_handles_unreachable_robots(monkeypatch, team):
    w = Website.objects.create(team=team, name="S", domain="seo.example")

    def _f(url, timeout=15):
        if url.endswith("/robots.txt") or url.endswith("/sitemap.xml"):
            raise OSError("unreachable")
        return 200, "<html><head></head></html>", {}

    monkeypatch.setattr(seo_checker, "fetch", _f)
    run_seo_check(str(w.pk))

    r = SeoReport.objects.get(website=w)
    assert r.check_status == "done"
    assert r.robots_status == "missing"
    assert r.sitemap_status == "missing"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/site_health/test_seo_run.py -v`
Expected: FAIL — `run_seo_check` not defined.

- [ ] **Step 3: Implement the task**

In `apps/site_health/tasks.py`, add near the top: `from datetime import timedelta` (if missing) and append:

```python
@shared_task(name="site_health.run_seo_check")
def run_seo_check(website_id: str) -> None:
    from apps.site_health import seo_checker
    from apps.site_health.models import SeoReport, SiteEvent
    from apps.site_health.notifications import notify_team
    from apps.websites.models import Website

    try:
        website = Website.objects.get(pk=website_id)
    except Website.DoesNotExist:
        return

    report, _ = SeoReport.objects.get_or_create(website=website)
    prev = {
        "homepage_indexable": report.homepage_indexable,
        "robots_blocks_all": report.robots_blocks_all,
        "sitemap_status": report.sitemap_status,
        "first_run": report.check_status == "never",
    }
    report.check_status = "running"
    report.error = ""
    report.save(update_fields=["check_status", "error"])

    domain = website.domain if website.domain.startswith("http") else f"https://{website.domain}"
    base = domain.rstrip("/")

    try:
        # --- robots.txt ---
        robots = {"blocks_all": False, "sitemaps": []}
        try:
            status_code, body, _h = seo_checker.fetch(f"{base}/robots.txt")
            if status_code == 200 and body.strip():
                robots = seo_checker.parse_robots(body)
                report.robots_status = "found"
            else:
                report.robots_status = "missing"
        except Exception:
            report.robots_status = "missing"
        report.robots_blocks_all = robots["blocks_all"]

        # --- sitemap ---
        sitemap_url = robots["sitemaps"][0] if robots["sitemaps"] else f"{base}/sitemap.xml"
        sitemap_urls: list[str] = []
        try:
            status_code, body, _h = seo_checker.fetch(sitemap_url)
            if status_code == 200 and body.strip():
                count, sitemap_urls = seo_checker.count_sitemap_urls(body, seo_checker.fetch)
                report.sitemap_status = "found"
                report.sitemap_url = sitemap_url
                report.sitemap_url_count = count
            else:
                report.sitemap_status = "missing"
        except Exception:
            report.sitemap_status = "missing"

        # --- indexability: homepage + up to MAX_PAGES sitemap pages ---
        candidates = [base + "/"]
        for u in sitemap_urls:
            if seo_checker.same_origin(base, u) and u not in candidates:
                candidates.append(u)
            if len(candidates) >= seo_checker.MAX_PAGES:
                break

        pages_checked = []
        for url in candidates:
            try:
                _sc, html, headers = seo_checker.fetch(url)
                indexable, reason = seo_checker.page_indexability(html, headers.get("x-robots-tag", ""))
            except Exception:
                continue
            pages_checked.append({"url": url, "indexable": indexable, "reason": reason})

        report.pages_checked = pages_checked
        report.noindex_count = sum(1 for p in pages_checked if not p["indexable"])
        home = next((p for p in pages_checked if p["url"] == base + "/"), None)
        report.homepage_indexable = home["indexable"] if home else None

        report.check_status = "done"
        report.last_checked_at = timezone.now()
        report.save()
    except Exception as exc:
        logger.exception("run_seo_check failed for %s", website_id)
        report.check_status = "failed"
        report.error = str(exc)[:500]
        report.save(update_fields=["check_status", "error"])
        return

    # --- regression alerts (skip on the first-ever run) ---
    if prev["first_run"]:
        return

    def _alert(event_type, severity, summary):
        SiteEvent.objects.create(
            website=website, event_type=event_type, severity=severity, summary=summary,
        )
        notify_team(website.team, f"[Digivault] {summary}", f"{summary} — {website.domain}")

    label = website.name or website.domain
    if prev["homepage_indexable"] is True and report.homepage_indexable is False:
        _alert(SiteEvent.EventType.SEO_NOINDEX_DETECTED, SiteEvent.Severity.CRITICAL,
               f"{label} homepage is now set to noindex")
    if not prev["robots_blocks_all"] and report.robots_blocks_all:
        _alert(SiteEvent.EventType.SEO_ROBOTS_BLOCK, SiteEvent.Severity.CRITICAL,
               f"{label} robots.txt now blocks all crawlers")
    if prev["sitemap_status"] == "found" and report.sitemap_status == "missing":
        _alert(SiteEvent.EventType.SEO_SITEMAP_MISSING, SiteEvent.Severity.WARNING,
               f"{label} sitemap is no longer reachable")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/site_health/test_seo_run.py -v --create-db`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/site_health/tasks.py tests/site_health/test_seo_run.py
git commit -m "feat(site_health): run_seo_check orchestrator with regression alerts"
```

---

## Task 7: `WebsiteSeoView` endpoint (GET / POST / PATCH)

**Files:**
- Modify: `apps/site_health/views.py`
- Modify: `apps/site_health/urls.py`
- Test: `tests/site_health/test_seo.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/site_health/test_seo.py`:

```python
from apps.site_health.models import SeoReport


@pytest.mark.django_db
def test_seo_endpoint_get_creates_report(auth_client, team):
    w = Website.objects.create(team=team, name="S", domain="seo3.example")
    resp = auth_client.get(f"/api/v1/websites/{w.id}/seo/")
    assert resp.status_code == 200
    assert resp.data["check_status"] == "never"


@pytest.mark.django_db
def test_seo_endpoint_patch_sets_interval(auth_client, team):
    w = Website.objects.create(team=team, name="S", domain="seo4.example")
    resp = auth_client.patch(
        f"/api/v1/websites/{w.id}/seo/", {"seo_scan_interval_days": 7}, format="json"
    )
    assert resp.status_code == 200
    w.refresh_from_db()
    assert w.seo_scan_interval_days == 7


@pytest.mark.django_db
def test_seo_endpoint_patch_rejects_bad_interval(auth_client, team):
    w = Website.objects.create(team=team, name="S", domain="seo5.example")
    resp = auth_client.patch(
        f"/api/v1/websites/{w.id}/seo/", {"seo_scan_interval_days": 99}, format="json"
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/site_health/test_seo.py -k seo_endpoint -v`
Expected: FAIL — 404 (route missing).

- [ ] **Step 3: Add the view**

In `apps/site_health/views.py`, import `SeoReport` and `SeoReportSerializer`, then add:

```python
class WebsiteSeoView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get(self, request, website_pk):
        team = request.user.active_team
        website = generics.get_object_or_404(Website, pk=website_pk, team=team)
        report, _ = SeoReport.objects.get_or_create(website=website)
        data = SeoReportSerializer(report).data
        data["seo_scan_interval_days"] = website.seo_scan_interval_days
        return Response(data)

    def post(self, request, website_pk):
        from apps.site_health.tasks import run_seo_check
        team = request.user.active_team
        website = generics.get_object_or_404(Website, pk=website_pk, team=team)
        run_seo_check.delay(str(website.pk))
        return Response({"queued": True}, status=status.HTTP_202_ACCEPTED)

    def patch(self, request, website_pk):
        team = request.user.active_team
        website = generics.get_object_or_404(Website, pk=website_pk, team=team)
        valid = {c[0] for c in Website.SEO_INTERVAL_CHOICES}
        try:
            interval = int(request.data.get("seo_scan_interval_days"))
        except (TypeError, ValueError):
            return Response({"detail": "Invalid interval."}, status=status.HTTP_400_BAD_REQUEST)
        if interval not in valid:
            return Response({"detail": "Invalid interval."}, status=status.HTTP_400_BAD_REQUEST)
        website.seo_scan_interval_days = interval
        website.save(update_fields=["seo_scan_interval_days"])
        return Response({"seo_scan_interval_days": interval})
```

- [ ] **Step 4: Wire the URL**

In `apps/site_health/urls.py`, import `WebsiteSeoView` and add to `website_urlpatterns`:

```python
    path("seo/", WebsiteSeoView.as_view(), name="website-seo"),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/site_health/test_seo.py -k seo_endpoint -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/site_health/views.py apps/site_health/urls.py tests/site_health/test_seo.py
git commit -m "feat(site_health): SEO endpoint (get report / recheck / set interval)"
```

---

## Task 8: Run SEO check inside the existing Scan action

**Files:**
- Modify: `apps/websites/views.py` (`scan` action, the POST branch that enqueues `run_security_scan`)

- [ ] **Step 1: Add the enqueue**

In `apps/websites/views.py`, in the `scan` action right after `run_security_scan.apply_async(args=[str(website.pk)], countdown=5)`, add:

```python
        from apps.site_health.tasks import run_seo_check
        run_seo_check.apply_async(args=[str(website.pk)], countdown=5)
```

- [ ] **Step 2: Verify existing website tests still pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/websites/ -q`
Expected: PASS (eager Celery runs `run_seo_check`; it will mark a report `failed`/`missing` on the fake test domain but must not error the request).

- [ ] **Step 3: Commit**

```bash
git add apps/websites/views.py
git commit -m "feat(websites): trigger SEO check from the scan action"
```

---

## Task 9: Scheduled `run_due_seo_checks` beat task

**Files:**
- Modify: `apps/site_health/tasks.py`
- Modify: `config/settings/base.py` (`CELERY_BEAT_SCHEDULE`)
- Test: `tests/site_health/test_seo_run.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/site_health/test_seo_run.py`:

```python
from datetime import timedelta

from django.utils import timezone

from apps.site_health.tasks import run_due_seo_checks


@pytest.mark.django_db
def test_run_due_seo_checks_selects_only_due(monkeypatch, team):
    off = Website.objects.create(team=team, name="off", domain="off.example", seo_scan_interval_days=0)
    due = Website.objects.create(team=team, name="due", domain="due.example", seo_scan_interval_days=7)
    fresh = Website.objects.create(team=team, name="fresh", domain="fresh.example", seo_scan_interval_days=7)
    SeoReport.objects.create(website=fresh, last_checked_at=timezone.now())

    enqueued = []
    monkeypatch.setattr(
        "apps.site_health.tasks.run_seo_check.delay", lambda wid: enqueued.append(wid)
    )
    n = run_due_seo_checks()

    assert str(due.pk) in enqueued
    assert str(off.pk) not in enqueued
    assert str(fresh.pk) not in enqueued
    assert n == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/site_health/test_seo_run.py::test_run_due_seo_checks_selects_only_due -v`
Expected: FAIL — `run_due_seo_checks` not defined.

- [ ] **Step 3: Implement the task**

In `apps/site_health/tasks.py`, append (ensure `from datetime import timedelta` is imported at top):

```python
@shared_task(name="site_health.run_due_seo_checks")
def run_due_seo_checks() -> int:
    from apps.site_health.models import SeoReport
    from apps.websites.models import Website

    now = timezone.now()
    enqueued = 0
    for w in Website.objects.exclude(seo_scan_interval_days=0).iterator():
        report = SeoReport.objects.filter(website=w).first()
        due = (
            report is None
            or report.last_checked_at is None
            or report.last_checked_at + timedelta(days=w.seo_scan_interval_days) <= now
        )
        if due:
            run_seo_check.delay(str(w.pk))
            enqueued += 1
    return enqueued
```

- [ ] **Step 4: Add the beat schedule entry**

In `config/settings/base.py`, inside `CELERY_BEAT_SCHEDULE`, add:

```python
    "run-due-seo-checks": {
        "task": "site_health.run_due_seo_checks",
        "schedule": crontab(hour=4, minute=0),
    },
```

- [ ] **Step 5: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/site_health/test_seo_run.py::test_run_due_seo_checks_selects_only_due -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/site_health/tasks.py config/settings/base.py tests/site_health/test_seo_run.py
git commit -m "feat(site_health): daily run_due_seo_checks beat task"
```

---

## Task 10: Frontend proxy route

**Files:**
- Create: `frontend/src/app/api/websites/[id]/seo/route.ts`

- [ ] **Step 1: Create the proxy** (mirrors the scan route; adds PATCH)

```typescript
import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function token() {
  const jar = await cookies();
  return jar.get("ss_access")?.value;
}

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const t = await token();
  if (!t) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  const upstream = await fetch(`${API_BASE}/api/v1/websites/${id}/seo/`, {
    headers: { Authorization: `Bearer ${t}` },
  });
  const envelope = await upstream.json().catch(() => ({}));
  return NextResponse.json(envelope?.data ?? envelope, { status: upstream.status });
}

export async function POST(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const t = await token();
  if (!t) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  const upstream = await fetch(`${API_BASE}/api/v1/websites/${id}/seo/`, {
    method: "POST",
    headers: { Authorization: `Bearer ${t}`, "Content-Type": "application/json" },
  });
  const envelope = await upstream.json().catch(() => ({}));
  return NextResponse.json(envelope?.data ?? envelope, { status: upstream.status });
}

export async function PATCH(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const t = await token();
  if (!t) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  const body = await req.json();
  const upstream = await fetch(`${API_BASE}/api/v1/websites/${id}/seo/`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${t}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const envelope = await upstream.json().catch(() => ({}));
  return NextResponse.json(envelope?.data ?? envelope, { status: upstream.status });
}
```

- [ ] **Step 2: Lint**

Run: `cd frontend && npx eslint "src/app/api/websites/[id]/seo/route.ts"`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add "frontend/src/app/api/websites/[id]/seo/route.ts"
git commit -m "feat(frontend): SEO proxy route (get/recheck/interval)"
```

---

## Task 11: `seo-tab.tsx` component

**Files:**
- Create: `frontend/src/components/seo-tab.tsx`

- [ ] **Step 1: Create the component**

```tsx
"use client";

import { useState } from "react";
import { Loader2, RefreshCw, CheckCircle2, XCircle, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

interface PageRow { url: string; indexable: boolean; reason: string }
interface SeoReport {
  last_checked_at: string | null;
  check_status: string;
  robots_status: string;
  robots_blocks_all: boolean;
  sitemap_status: string;
  sitemap_url: string;
  sitemap_url_count: number;
  homepage_indexable: boolean | null;
  pages_checked: PageRow[];
  noindex_count: number;
  seo_scan_interval_days: number;
}

const INTERVALS = [
  { v: 0, label: "Off" },
  { v: 3, label: "Every 3 days" },
  { v: 7, label: "Every 7 days" },
  { v: 14, label: "Every 14 days" },
  { v: 30, label: "Every 30 days" },
];

function StatusIcon({ ok, warn }: { ok: boolean; warn?: boolean }) {
  if (warn) return <AlertTriangle className="h-4 w-4 text-amber-500" />;
  return ok ? <CheckCircle2 className="h-4 w-4 text-emerald-500" /> : <XCircle className="h-4 w-4 text-red-500" />;
}

export function SeoTab({ websiteId, report }: { websiteId: string; report: SeoReport | null }) {
  const [data, setData] = useState<SeoReport | null>(report);
  const [busy, setBusy] = useState(false);
  const [interval, setIntervalVal] = useState<number>(report?.seo_scan_interval_days ?? 0);

  async function recheck() {
    setBusy(true);
    try {
      await fetch(`/api/websites/${websiteId}/seo`, { method: "POST" });
      // Poll once after a short delay for fresh results.
      setTimeout(async () => {
        const res = await fetch(`/api/websites/${websiteId}/seo`);
        if (res.ok) setData(await res.json());
        setBusy(false);
      }, 4000);
    } catch {
      setBusy(false);
    }
  }

  async function changeInterval(v: number) {
    setIntervalVal(v);
    await fetch(`/api/websites/${websiteId}/seo`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ seo_scan_interval_days: v }),
    });
  }

  if (!data || data.check_status === "never") {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">No SEO check has run yet.</p>
          <Button size="sm" variant="outline" onClick={recheck} disabled={busy}>
            {busy ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5 mr-1.5" />}
            Run check
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-4">
        <p className="text-xs text-muted-foreground">
          {data.last_checked_at ? `Last checked ${new Date(data.last_checked_at).toLocaleString()}` : "Never checked"}
        </p>
        <div className="flex items-center gap-2">
          <select
            value={interval}
            onChange={(e) => changeInterval(Number(e.target.value))}
            className="border rounded-md px-2 py-1 text-xs bg-background"
          >
            {INTERVALS.map((i) => <option key={i.v} value={i.v}>{i.label}</option>)}
          </select>
          <Button size="sm" variant="outline" onClick={recheck} disabled={busy}>
            {busy ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5 mr-1.5" />}
            Re-check
          </Button>
        </div>
      </div>

      <div className="grid sm:grid-cols-3 gap-3">
        <div className="border rounded-lg p-3 space-y-1">
          <div className="flex items-center gap-2 text-sm font-medium">
            <StatusIcon ok={data.robots_status === "found" && !data.robots_blocks_all} warn={data.robots_blocks_all} />
            robots.txt
          </div>
          <p className="text-xs text-muted-foreground">
            {data.robots_status === "found"
              ? (data.robots_blocks_all ? "Blocks all crawlers" : "Present")
              : "Missing"}
          </p>
        </div>
        <div className="border rounded-lg p-3 space-y-1">
          <div className="flex items-center gap-2 text-sm font-medium">
            <StatusIcon ok={data.sitemap_status === "found"} />
            Sitemap
          </div>
          <p className="text-xs text-muted-foreground">
            {data.sitemap_status === "found" ? `${data.sitemap_url_count} URLs` : "Missing"}
          </p>
        </div>
        <div className="border rounded-lg p-3 space-y-1">
          <div className="flex items-center gap-2 text-sm font-medium">
            <StatusIcon ok={data.homepage_indexable === true} />
            Indexable
          </div>
          <p className="text-xs text-muted-foreground">
            {data.homepage_indexable === false
              ? "Homepage is noindex"
              : `${data.noindex_count} noindex of ${data.pages_checked.length} checked`}
          </p>
        </div>
      </div>

      {data.pages_checked.length > 0 && (
        <div className="border rounded-lg divide-y">
          {data.pages_checked.map((p) => (
            <div key={p.url} className="flex items-center justify-between px-3 py-2 text-xs">
              <span className="font-mono truncate max-w-[60%]" title={p.url}>{p.url}</span>
              <span className={p.indexable ? "text-emerald-600" : "text-red-600"}>
                {p.indexable ? "indexable" : (p.reason || "noindex")}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Lint**

Run: `cd frontend && npx eslint src/components/seo-tab.tsx`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/seo-tab.tsx
git commit -m "feat(frontend): SEO tab component"
```

---

## Task 12: Wire the SEO tab into the website detail page

**Files:**
- Modify: `frontend/src/app/(dashboard)/websites/[id]/page.tsx`

- [ ] **Step 1: Import + fetch the report**

At the top with the other tab imports, add:

```tsx
import { SeoTab } from "@/components/seo-tab";
```

Where the page server-fetches per-tab data (alongside the existing `getAccessToken()` + `api.get` calls), add a fetch for the SEO report (best-effort, null on failure):

```tsx
  const seoReport = await api
    .get(`/websites/${id}/seo/`, token)
    .then((r) => r?.data ?? null)
    .catch(() => null);
```

(Match the exact `api.get` signature already used in this file for other tabs — adjust the call to mirror neighbouring fetches.)

- [ ] **Step 2: Add the trigger + panel**

In the `<TabsList>`, after the Performance trigger, add:

```tsx
          <TabsTrigger value="seo" asChild>
            <Link href={`/websites/${id}?tab=seo`} prefetch>SEO</Link>
          </TabsTrigger>
```

After the matching performance `<TabsContent>`, add:

```tsx
        <TabsContent value="seo">
          <SeoTab websiteId={id} report={seoReport} />
        </TabsContent>
```

- [ ] **Step 3: Lint + typecheck**

Run: `cd frontend && npx eslint "src/app/(dashboard)/websites/[id]/page.tsx" && npx tsc --noEmit`
Expected: no errors (fix the `api.get` call shape if tsc complains).

- [ ] **Step 4: Commit**

```bash
git add "frontend/src/app/(dashboard)/websites/[id]/page.tsx"
git commit -m "feat(frontend): add SEO tab to website detail page"
```

---

## Task 13: Full regression + smoke

- [ ] **Step 1: Backend suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/site_health/ tests/websites/ -q --create-db`
Expected: all PASS.

- [ ] **Step 2: Frontend lint**

Run: `cd frontend && npm run lint`
Expected: no new errors (a pre-existing unused-`Badge` warning in `team-management-client.tsx` may remain).

- [ ] **Step 3: Manual smoke (dev)**

1. Open a website → SEO tab → "Run check" → confirm robots/sitemap/indexable cards populate.
2. Set interval to "Every 7 days" → reload → confirm it persists.
3. (Optional) Point at a site with `<meta name="robots" content="noindex">`, run twice → confirm a SiteEvent regression alert is logged on the second run.

- [ ] **Step 4: Final commit (if cleanup)**

```bash
git add -A && git commit -m "test: SEO health regression pass"
```

---

## Self-Review

- **Spec coverage:** interval field (T1), `SeoReport` (T2), SiteEvent types (T3), robots/sitemap/index check fns (T4), notifications (T5), orchestrator + regression alerts + baseline-silent (T6), endpoint GET/POST/PATCH (T7), scan-action hook (T8), scheduled due-selection (T9), frontend proxy/tab/wiring (T10-12). ✅
- **Placeholder scan:** all code blocks complete; the only "match neighbouring call" note is in T12 step 1 for `api.get` — flagged because that helper's exact signature is file-local; the engineer mirrors adjacent fetches. No TBDs.
- **Type consistency:** `SeoReport` fields (`robots_status`, `robots_blocks_all`, `sitemap_status`, `sitemap_url_count`, `homepage_indexable`, `pages_checked`, `noindex_count`) identical across model (T2), serializer (T2), task writes (T6), and the TS `SeoReport` interface (T11). `seo_checker.fetch` / `parse_robots` / `count_sitemap_urls` / `page_indexability` / `same_origin` / `MAX_PAGES` names consistent between T4 and T6. Endpoint path `/api/v1/websites/<id>/seo/` consistent across T7, T10. Task names `site_health.run_seo_check` / `site_health.run_due_seo_checks` consistent (T6, T9, beat).
- **Out of scope (per spec):** PDF report inclusion, team-level default interval, per-page checks beyond N=10 / sitemap recursion beyond one level.
