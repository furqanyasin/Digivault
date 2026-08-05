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


class TestGoogleTagRuntimeParams:
    """gtag/GTM append runtime state to their own src.

    `gtm=` is a container-version fingerprint that changes on every GTM publish,
    and it is short enough to slip past the hex-value heuristic. Left in the
    identity, one container mints a fresh Script row per publish — which is how
    the same tag ends up listed several times.
    """

    def test_gtm_container_version_is_volatile(self):
        assert (
            normalize_script_url(
                "https://www.googletagmanager.com/gtag/js?id=G-LC6FS8Y01E&cx=c&gtm=4e6840"
            )
            == "https://www.googletagmanager.com/gtag/js?id=G-LC6FS8Y01E"
        )

    def test_a_gtm_republish_yields_the_same_identity(self):
        a = normalize_script_url("https://www.googletagmanager.com/gtag/js?id=G-ABC&gtm=4e6840")
        b = normalize_script_url("https://www.googletagmanager.com/gtag/js?id=G-ABC&gtm=45He51r0")
        assert a == b

    def test_consent_and_experiment_state_is_volatile(self):
        out = normalize_script_url(
            "https://www.googletagmanager.com/gtag/js?id=G-ABC"
            "&gcs=G111&gcd=13r3r3r5l1&dma=0&npa=0&tag_exp=101509157~103116026&_p=17"
        )
        assert out == "https://www.googletagmanager.com/gtag/js?id=G-ABC"

    def test_different_containers_stay_separate(self):
        """Two GTM containers are two real scripts — never merge them."""
        a = normalize_script_url("https://www.googletagmanager.com/gtm.js?id=GTM-N32TK6DJ")
        b = normalize_script_url("https://www.googletagmanager.com/gtm.js?id=GTM-NDF77KHJ")
        assert a != b

    def test_a_blank_id_carries_no_identity(self):
        """`?id=` with nothing after it is a misconfigured tag, not an identity."""
        assert (
            normalize_script_url("https://www.googletagmanager.com/gtm.js?id=")
            == "https://www.googletagmanager.com/gtm.js"
        )

    def test_a_blank_param_does_not_merge_into_a_real_container(self):
        blank = normalize_script_url("https://www.googletagmanager.com/gtm.js?id=")
        real = normalize_script_url("https://www.googletagmanager.com/gtm.js?id=GTM-N32TK6DJ")
        assert blank != real

    def test_the_datalayer_name_is_kept(self):
        """`l=` is a stable site config choice, not runtime state."""
        url = "https://www.googletagmanager.com/gtm.js?id=GTM-ABC&l=myDataLayer"
        assert normalize_script_url(url) == url


class TestHashedFilenames:
    """Content hashes also live in filenames, not just query params.

    Hotjar ships `modules.<hash>.js`, and webpack/Vite builds do the same. Each
    release changes the hash, so the identity moves and the same bundle is listed
    again — the query-param rules never see it because there is no query at all.
    """

    def test_hotjar_module_bundle_hash_is_volatile(self):
        assert (
            normalize_script_url("https://script.hotjar.com/modules.75bf3488a101739acfe9.js")
            == "https://script.hotjar.com/modules.js"
        )

    def test_a_hotjar_release_yields_the_same_identity(self):
        a = normalize_script_url("https://script.hotjar.com/modules.75bf3488a101739acfe9.js")
        b = normalize_script_url("https://script.hotjar.com/modules.0f1e2d3c4b5a69788796.js")
        assert a == b

    def test_dash_separated_hashes_are_volatile(self):
        a = normalize_script_url("https://cdn.example.com/app-a1b2c3d4e5f60718.js")
        b = normalize_script_url("https://cdn.example.com/app-99887766554433221.js")
        assert a == b == "https://cdn.example.com/app.js"

    def test_webpack_chunk_hashes_are_volatile(self):
        assert (
            normalize_script_url("https://cdn.example.com/static/js/main.4f2b8c1d9e0a.chunk.js")
            == "https://cdn.example.com/static/js/main.chunk.js"
        )

    def test_a_site_container_id_in_the_filename_is_kept(self):
        """hotjar-3065386.js identifies the account — that is not a hash."""
        url = "https://static.hotjar.com/c/hotjar-3065386.js?sv=6"
        assert normalize_script_url(url) == url

    def test_a_version_number_in_the_filename_is_kept(self):
        url = "https://cdn.example.com/jquery-3.6.0.min.js"
        assert normalize_script_url(url) == url

    def test_a_plain_filename_is_untouched(self):
        url = "https://cdn.example.com/analytics.js"
        assert normalize_script_url(url) == url

    def test_a_short_word_segment_is_not_mistaken_for_a_hash(self):
        """`bundle.min.js` — `min` is not a hash, however hex-ish it looks."""
        url = "https://cdn.example.com/bundle.min.js"
        assert normalize_script_url(url) == url

    def test_two_different_bundles_on_the_same_host_stay_separate(self):
        a = normalize_script_url("https://script.hotjar.com/modules.aabbccddeeff00112233.js")
        b = normalize_script_url("https://script.hotjar.com/widget.aabbccddeeff00112233.js")
        assert a != b

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
