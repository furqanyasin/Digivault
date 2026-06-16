import pytest

from apps.site_health import seo_checker
from apps.site_health.models import SeoReport, SiteEvent
from apps.site_health.tasks import run_seo_check
from apps.websites.models import Website

ROBOTS_OK = "User-agent: *\nDisallow:\nSitemap: https://m.example/sitemap.xml"
SITEMAP = (
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>https://m.example/</loc></url></urlset>"
)

HOME = """
<html><head>
<title> My Shop — Best Deals </title>
<meta name="description" content="We sell the best widgets online.">
<link rel="canonical" href="https://m.example/">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Organization","name":"My Shop"}
</script>
</head><body><h1>Welcome to <em>My Shop</em></h1></body></html>
"""


# ── pure parser ──────────────────────────────────────────────────────────

def test_parse_homepage_meta_extracts_all_fields():
    meta = seo_checker.parse_homepage_meta(HOME)
    assert meta["meta_title"] == "My Shop — Best Deals"
    assert meta["meta_description"] == "We sell the best widgets online."
    assert meta["h1"] == "Welcome to My Shop"          # tags stripped
    assert meta["canonical_url"] == "https://m.example/"
    assert meta["schema_types"] == ["Organization"]


def test_parse_homepage_meta_handles_graph_and_arrays():
    html = """<script type="application/ld+json">
    {"@graph":[{"@type":"WebSite"},{"@type":["Product","Offer"]}]}</script>"""
    assert seo_checker.parse_homepage_meta(html)["schema_types"] == ["WebSite", "Product", "Offer"]


def test_parse_homepage_meta_empty_on_blank():
    meta = seo_checker.parse_homepage_meta("<html></html>")
    assert meta == {"meta_title": "", "meta_description": "", "h1": "", "canonical_url": "", "schema_types": []}


def test_parse_homepage_meta_skips_malformed_jsonld():
    html = '<script type="application/ld+json">{not valid json}</script>'
    assert seo_checker.parse_homepage_meta(html)["schema_types"] == []


# ── change detection in run_seo_check ─────────────────────────────────────

def _fetch(pages):
    def _f(url, timeout=15):
        return pages.get(url, (200, "<html><head></head></html>", {}))
    return _f


@pytest.mark.django_db
def test_seo_check_captures_meta(monkeypatch, team):
    w = Website.objects.create(team=team, name="M", domain="m.example")
    pages = {
        "https://m.example/robots.txt": (200, ROBOTS_OK, {}),
        "https://m.example/sitemap.xml": (200, SITEMAP, {}),
        "https://m.example/": (200, HOME, {}),
    }
    monkeypatch.setattr(seo_checker, "fetch", _fetch(pages))

    run_seo_check(str(w.pk))

    r = SeoReport.objects.get(website=w)
    assert r.meta_title == "My Shop — Best Deals"
    assert r.h1 == "Welcome to My Shop"
    assert r.canonical_url == "https://m.example/"
    assert r.schema_types == ["Organization"]


@pytest.mark.django_db
def test_seo_check_alerts_on_meta_change(monkeypatch, team):
    w = Website.objects.create(team=team, name="M", domain="m.example")
    base = {
        "https://m.example/robots.txt": (200, ROBOTS_OK, {}),
        "https://m.example/sitemap.xml": (200, SITEMAP, {}),
        "https://m.example/": (200, HOME, {}),
    }
    monkeypatch.setattr(seo_checker, "fetch", _fetch(base))
    run_seo_check(str(w.pk))  # baseline run — no alert
    assert SiteEvent.objects.filter(website=w, event_type=SiteEvent.EventType.SEO_META_CHANGED).count() == 0

    changed_home = HOME.replace("My Shop — Best Deals", "My Shop — CLOSED")
    changed = dict(base, **{"https://m.example/": (200, changed_home, {})})
    monkeypatch.setattr(seo_checker, "fetch", _fetch(changed))
    run_seo_check(str(w.pk))

    events = SiteEvent.objects.filter(website=w, event_type=SiteEvent.EventType.SEO_META_CHANGED)
    assert events.count() == 1
    ev = events.first()
    assert ev.details["changes"][0]["field"] == "title"
    assert ev.details["changes"][0]["new"] == "My Shop — CLOSED"


@pytest.mark.django_db
def test_seo_check_no_meta_alert_when_unchanged(monkeypatch, team):
    w = Website.objects.create(team=team, name="M", domain="m.example")
    pages = {
        "https://m.example/robots.txt": (200, ROBOTS_OK, {}),
        "https://m.example/sitemap.xml": (200, SITEMAP, {}),
        "https://m.example/": (200, HOME, {}),
    }
    monkeypatch.setattr(seo_checker, "fetch", _fetch(pages))
    run_seo_check(str(w.pk))
    run_seo_check(str(w.pk))  # identical second run

    assert SiteEvent.objects.filter(website=w, event_type=SiteEvent.EventType.SEO_META_CHANGED).count() == 0
