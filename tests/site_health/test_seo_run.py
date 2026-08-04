
import pytest
from django.utils import timezone

from apps.site_health import seo_checker
from apps.site_health.models import SeoReport, SiteEvent
from apps.site_health.tasks import run_due_seo_checks, run_seo_check
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
    healthy = {
        "https://seo.example/robots.txt": (200, ROBOTS_OK, {}),
        "https://seo.example/sitemap.xml": (200, SITEMAP, {}),
        "https://seo.example/": (200, "<html><head></head></html>", {}),
    }
    monkeypatch.setattr(seo_checker, "fetch", _fake_fetch(healthy))
    run_seo_check(str(w.pk))
    assert SiteEvent.objects.filter(website=w).count() == 0  # baseline: no alert

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
def test_run_seo_check_rotates_and_accumulates(monkeypatch, team):
    w = Website.objects.create(team=team, name="S", domain="seo.example")
    locs = "".join(f"<url><loc>https://seo.example/p{i}</loc></url>" for i in range(20))
    sitemap = f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>'
    pages = {
        "https://seo.example/robots.txt": (200, ROBOTS_OK, {}),
        "https://seo.example/sitemap.xml": (200, sitemap, {}),
    }
    monkeypatch.setattr(seo_checker, "fetch", _fake_fetch(pages))

    run_seo_check(str(w.pk))
    r = SeoReport.objects.get(website=w)
    first = len(r.pages_checked)
    assert first <= seo_checker.MAX_PAGES       # one rotating batch (home + window)
    assert r.scan_cursor > 0                    # cursor advanced
    assert r.sitemap_url_count == 20
    assert len(r.sitemap_pages) == 20           # sitemap URLs stored for display

    run_seo_check(str(w.pk))
    r.refresh_from_db()
    assert len(r.pages_checked) > first         # second run accumulated more pages


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
