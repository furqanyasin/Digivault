"""Tests for apps.scripts.normalize — stable URL identity."""


from apps.scripts.normalize import (
    normalize_page_url,
    normalize_recipient_email,
    normalize_script_url,
)


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


class TestTimestampedPathSegments:
    """Cache-busters also live in path segments, not just filenames and queries.

    HubSpot serves analytics from `/analytics/<epoch_ms>/<portal_id>.js` and
    rotates the timestamp roughly every 30 minutes, so one portal minted a fresh
    Script row on every visit — seven rows for one tag in a single day. The
    filename rule never sees it: the volatile part is a directory, and it is all
    digits rather than hex.
    """

    def test_hubspot_analytics_timestamp_is_volatile(self):
        assert (
            normalize_script_url("https://js.hs-analytics.net/analytics/1785996600000/46377927.js")
            == "https://js.hs-analytics.net/analytics/46377927.js"
        )

    def test_every_rotation_yields_the_same_identity(self):
        seen = {
            normalize_script_url(f"https://js.hs-analytics.net/analytics/{ts}/46377927.js")
            for ts in (
                "1785996600000",
                "1785964500000",
                "1785958800000",
                "1785982500000",
                "1785962700000",
                "1785960600000",
                "1785993900000",
            )
        }
        assert len(seen) == 1

    def test_two_portals_stay_separate(self):
        """The portal id is the identity — only the timestamp may be dropped."""
        a = normalize_script_url("https://js.hs-analytics.net/analytics/1785996600000/46377927.js")
        b = normalize_script_url("https://js.hs-analytics.net/analytics/1785996600000/11223344.js")
        assert a != b

    def test_a_meta_pixel_id_in_the_path_is_kept(self):
        """A 16-digit pixel id is an account, not a timestamp — never strip it."""
        out = normalize_script_url(
            "https://connect.facebook.net/signals/config/7847387958713764?v=2.9.370"
        )
        assert out == "https://connect.facebook.net/signals/config/7847387958713764"

    def test_a_short_numeric_path_segment_is_kept(self):
        """Account/version directories like /v3/ or /12345/ are identity."""
        url = "https://cdn.example.com/v3/12345/widget.js"
        assert normalize_script_url(url) == url

    def test_a_digit_run_that_is_not_a_plausible_date_is_kept(self):
        """13 digits alone is not enough — it has to land in a sane date range."""
        url = "https://cdn.example.com/9999999999999/widget.js"
        assert normalize_script_url(url) == url

    def test_epoch_seconds_segment_is_volatile(self):
        a = normalize_script_url("https://cdn.example.com/build/1785996600/app.js")
        b = normalize_script_url("https://cdn.example.com/build/1785964500/app.js")
        assert a == b == "https://cdn.example.com/build/app.js"


class TestMetaPixelRuntimeParams:
    """Meta's pixel config carries its library version and an experiment list.

    `v=2.9.370` moves on every Meta release and `ex_m=` is a rotating list of
    experiment ids, so the same pixel would start listing twice the next time
    either changed.
    """

    def test_library_version_is_volatile(self):
        a = normalize_script_url("https://connect.facebook.net/signals/config/123?v=2.9.370")
        b = normalize_script_url("https://connect.facebook.net/signals/config/123?v=2.9.371")
        assert a == b == "https://connect.facebook.net/signals/config/123"

    def test_experiment_list_is_volatile(self):
        out = normalize_script_url(
            "https://connect.facebook.net/signals/config/7847387958713764"
            "?v=2.9.370&r=stable&domain=digilatics.com"
            "&hme=589ca7d2e122c6385be4e33d0bc38dace8e88b62db3f4bee0e6f01d386858e70"
            "&ex_m=108%2C210%2C160%2C22%2C73"
        )
        assert out == (
            "https://connect.facebook.net/signals/config/7847387958713764"
            "?domain=digilatics.com&r=stable"
        )


class TestLibraryVersionPathSegments:
    """Vendors that put the library version in the path, not a query param.

    Microsoft Clarity serves /0.8.69/clarity.js and ships a release every few
    days, so the raw path minted a new identity — and a high-severity "Unknown
    script detected" — on every release.
    """

    def test_clarity_release_yields_same_identity(self):
        a = normalize_script_url("https://scripts.clarity.ms/0.8.69/clarity.js")
        b = normalize_script_url("https://scripts.clarity.ms/0.8.71/clarity.js")
        assert a == b == "https://scripts.clarity.ms/clarity.js"

    def test_prerelease_and_v_prefixed_versions_collapse_too(self):
        base = "https://scripts.clarity.ms/clarity.js"
        assert normalize_script_url("https://scripts.clarity.ms/0.8.67-beta/clarity.js") == base
        assert normalize_script_url("https://scripts.clarity.ms/v0.8.67/clarity.js") == base

    def test_account_id_segments_are_not_mistaken_for_versions(self):
        # The identity of a tag IS its account id — these must not collapse.
        assert (
            normalize_script_url("https://js.hs-banner.com/v2/46377927/banner.js")
            != normalize_script_url("https://js.hs-banner.com/v2/99999999/banner.js")
        )
        assert (
            normalize_script_url("https://www.clarity.ms/tag/i9x3wxzn9k")
            == "https://www.clarity.ms/tag/i9x3wxzn9k"
        )

    def test_locale_and_word_segments_survive(self):
        assert (
            normalize_script_url("https://connect.facebook.net/en_US/fbevents.js")
            == "https://connect.facebook.net/en_US/fbevents.js"
        )


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


class TestPageContextParams:
    """A tracker that carries the current page in its src is one script, not one
    per page. ActiveCampaign's prism/trackcmp beacons put the whole page URL in
    `u=`/`url=` and a per-visit UUID in `prismid=`, which minted a Script row —
    and a high-severity "unknown script" change — for every page on the site.
    """

    def test_a_url_valued_param_is_dropped(self):
        a = normalize_script_url(
            "https://prism.app-us1.com/?a=224932943&u=https%3A%2F%2Fsite.com%2Fblog%2F4%2F"
        )
        b = normalize_script_url(
            "https://prism.app-us1.com/?a=224932943&u=https%3A%2F%2Fsite.com%2Fblog%2F5%2F"
        )
        assert a == b
        assert "site.com" not in a
        # The account id is identity and must survive.
        assert "a=224932943" in a

    def test_a_uuid_valued_param_is_dropped(self):
        a = normalize_script_url(
            "https://trackcmp.net/t.php?trackid=2249&prismid=df38e203-e545-42a5-a998-0e3a1df09038"
        )
        b = normalize_script_url(
            "https://trackcmp.net/t.php?trackid=2249&prismid=c444ff8d-d018-4061-b1af-682006e3d3eb"
        )
        assert a == b
        assert "trackid=2249" in a

    def test_the_whole_activecampaign_beacon_collapses_to_one_identity(self):
        urls = [
            "https://trackcmp.net/t_prism_sitemessages.php?trackid=224932943"
            "&prismid=df38e203-e545-42a5-a998-0e3a1df09038"
            "&url=https%3A%2F%2Fsite.com%2Fblog%2F16%2F",
            "https://trackcmp.net/t_prism_sitemessages.php?trackid=224932943"
            "&prismid=b0488a7a-4958-4ece-8e1e-c954ea5e9fec"
            "&url=https%3A%2F%2Fsite.com%2Fcategory%2Fblog%2Fpage%2F4%2F",
        ]
        assert len({normalize_script_url(u) for u in urls}) == 1

    def test_a_non_url_non_uuid_param_still_counts_as_identity(self):
        a = normalize_script_url("https://vendor.io/tag.js?id=GTM-ABC")
        b = normalize_script_url("https://vendor.io/tag.js?id=GTM-XYZ")
        assert a != b


class TestNormalizeRecipientEmail:
    def test_lowercases_and_strips(self):
        assert normalize_recipient_email("  Info@Site.com  ") == "info@site.com"

    def test_keeps_plus_addressing(self):
        assert normalize_recipient_email("sales+quotes@site.com") == "sales+quotes@site.com"

    def test_strips_name_angle_bracket_form(self):
        assert normalize_recipient_email("Sales <sales@site.com>") == "sales@site.com"

    def test_empty_and_garbage_rejected(self):
        assert normalize_recipient_email("") == ""
        assert normalize_recipient_email("not-an-email") == ""
        assert normalize_recipient_email("a@b") == ""
        assert normalize_recipient_email("sales@site.com, dev@site.com") == ""
