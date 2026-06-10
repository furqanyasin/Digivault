"""CMS / site-builder detection from page HTML + headers."""

from apps.websites.platform_detect import (
    FRAMER, OTHER, SHOPIFY, SQUARESPACE, WEBFLOW, WIX, WORDPRESS,
    detect_platform,
)


class TestGeneratorMeta:
    def test_wordpress_generator(self):
        html = '<meta name="generator" content="WordPress 6.5.2" />'
        assert detect_platform(html) == WORDPRESS

    def test_generator_case_insensitive_and_single_quotes(self):
        html = "<META NAME='generator' CONTENT='Wix.com Website Builder'>"
        assert detect_platform(html) == WIX

    def test_woocommerce_generator_maps_to_wordpress(self):
        html = '<meta name="generator" content="WooCommerce 8.0">'
        assert detect_platform(html) == WORDPRESS


class TestHtmlMarkers:
    def test_wordpress_wp_content_path(self):
        html = '<link href="/wp-content/themes/x/style.css">'
        assert detect_platform(html) == WORDPRESS

    def test_shopify_cdn(self):
        html = '<script src="https://cdn.shopify.com/s/files/app.js"></script>'
        assert detect_platform(html) == SHOPIFY

    def test_webflow_attributes(self):
        html = '<html data-wf-site="abc" data-wf-page="def">'
        assert detect_platform(html) == WEBFLOW

    def test_framer_usercontent(self):
        html = '<img src="https://framerusercontent.com/images/x.png">'
        assert detect_platform(html) == FRAMER

    def test_squarespace_static(self):
        html = '<link href="https://static1.squarespace.com/x.css">'
        assert detect_platform(html) == SQUARESPACE


class TestHeaders:
    def test_shopify_header(self):
        assert detect_platform("<html></html>", {"X-ShopId": "12345"}) == SHOPIFY

    def test_header_key_case_insensitive(self):
        assert detect_platform("<html></html>", {"x-wix-request-id": "abc"}) == WIX


class TestFallback:
    def test_unknown_is_other(self):
        assert detect_platform("<html><body>hello</body></html>", {}) == OTHER

    def test_empty_input(self):
        assert detect_platform("", None) == OTHER

    def test_generator_wins_over_marker(self):
        # A WP site embedding a Shopify buy-button shouldn't be misread as Shopify.
        html = ('<meta name="generator" content="WordPress 6.5">'
                '<script src="https://cdn.shopify.com/buy.js"></script>')
        assert detect_platform(html) == WORDPRESS
