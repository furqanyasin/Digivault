"""Tests for apps.scripts.normalize — stable URL identity."""


from apps.scripts.normalize import normalize_page_url, normalize_script_url


class TestNormalizeScriptUrl:
    def test_strips_wordpress_ver_param(self):
        assert (
            normalize_script_url("https://example.com/wp-content/plugins/x/a.js?ver=6.4.2")
            == "https://example.com/wp-content/plugins/x/a.js"
        )

    def test_ver_bump_yields_same_identity(self):
        a = normalize_script_url("https://example.com/a.js?ver=1.0")
        b = normalize_script_url("https://example.com/a.js?ver=2.0")
        assert a == b

    def test_strips_nonce_cb_and_timestamp_params(self):
        assert (
            normalize_script_url("https://cdn.example.com/a.js?nonce=abc123&cb=999&t=1700000000")
            == "https://cdn.example.com/a.js"
        )

    def test_keeps_gtm_container_id(self):
        assert (
            normalize_script_url("https://www.googletagmanager.com/gtag/js?id=AW-123456789")
            == "https://www.googletagmanager.com/gtag/js?id=AW-123456789"
        )

    def test_keeps_recaptcha_render_param(self):
        url = "https://www.google.com/recaptcha/api.js?render=6LcSiteKey"
        assert normalize_script_url(url) == url

    def test_mixed_params_keeps_meaningful_drops_volatile(self):
        out = normalize_script_url("https://x.com/a.js?ver=1.2&id=GTM-ABC&_=123")
        assert out == "https://x.com/a.js?id=GTM-ABC"

    def test_param_order_is_stable(self):
        a = normalize_script_url("https://x.com/a.js?b=2&a=1")
        b = normalize_script_url("https://x.com/a.js?a=1&b=2")
        assert a == b

    def test_drops_hexlike_param_values(self):
        # Cache-bust hashes as values of arbitrary params
        out = normalize_script_url("https://x.com/a.js?h=0123456789abcdef0123")
        assert out == "https://x.com/a.js"

    def test_protocol_relative_becomes_https(self):
        assert (
            normalize_script_url("//cdn.example.com/a.js?ver=1")
            == "https://cdn.example.com/a.js"
        )

    def test_host_lowercased(self):
        assert (
            normalize_script_url("https://CDN.Example.COM/a.js")
            == "https://cdn.example.com/a.js"
        )

    def test_fragment_removed(self):
        assert normalize_script_url("https://x.com/a.js#frag") == "https://x.com/a.js"

    def test_garbage_input_returned_unchanged(self):
        assert normalize_script_url("not a url") == "not a url"
        assert normalize_script_url("") == ""


class TestNormalizePageUrl:
    def test_strips_query_and_fragment(self):
        assert (
            normalize_page_url("https://example.com/contact?utm_source=x#top")
            == "https://example.com/contact"
        )

    def test_trailing_slash_variants_collapse(self):
        a = normalize_page_url("https://example.com/contact/")
        b = normalize_page_url("https://example.com/contact")
        assert a == b

    def test_root_path_preserved(self):
        assert normalize_page_url("https://example.com/") == "https://example.com/"
        assert normalize_page_url("https://example.com") == "https://example.com/"

    def test_www_stripped_and_host_lowercased(self):
        assert (
            normalize_page_url("https://WWW.Example.com/About/")
            == "https://example.com/About"
        )

    def test_garbage_input_returned_unchanged(self):
        assert normalize_page_url("nonsense") == "nonsense"
        assert normalize_page_url("") == ""
