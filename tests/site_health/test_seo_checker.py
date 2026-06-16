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
