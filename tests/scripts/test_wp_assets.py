"""Passive WordPress plugin / theme / core change detection."""

from apps.scripts.wp_assets import CORE, PLUGIN, THEME, classify, diff_assets, version_of


def s(src: str) -> dict:
    return {"src": src, "location": "head", "is_async": False, "is_defer": False}


P = "https://site.example/wp-content/plugins/{}/js/app.js?ver={}"
T = "https://site.example/wp-content/themes/{}/main.js?ver={}"
CORE_JS = "https://site.example/wp-includes/js/jquery/jquery.min.js?ver={}"


class TestClassify:
    def test_plugin_theme_and_core(self):
        assert classify(P.format("wpforms", "1.8")) == (PLUGIN, "wpforms")
        assert classify(T.format("astra", "4.1")) == (THEME, "astra")
        assert classify(CORE_JS.format("6.7.1")) == (CORE, "wordpress")

    def test_mu_plugins_count_as_plugins(self):
        url = "https://site.example/wp-content/mu-plugins/security-headers/x.js"
        assert classify(url) == (PLUGIN, "security-headers")

    def test_slug_is_case_normalized(self):
        assert classify(P.format("WPForms", "1.8")) == (PLUGIN, "wpforms")

    def test_third_party_urls_are_not_wp_assets(self):
        assert classify("https://www.googletagmanager.com/gtm.js?id=GTM-X") is None
        assert classify("") is None


class TestVersionOf:
    def test_reads_the_ver_param(self):
        assert version_of(P.format("wpforms", "1.8.4")) == "1.8.4"

    def test_ignores_build_hashes_and_timestamps(self):
        # These rotate per deploy without the plugin changing, so treating them
        # as versions would manufacture an "updated" event on every page load.
        assert version_of(P.format("x", "a3f9c2b81e4d7a6f")) == ""
        assert version_of(P.format("x", "1699999999999")) == "1699999999999"
        assert version_of("https://site.example/a.js") == ""


class TestDiffAssets:
    def test_first_snapshot_reports_nothing(self):
        # Otherwise every plugin on the site reads as newly installed the first
        # time anyone loads a page.
        assert diff_assets([], [s(P.format("wpforms", "1.8"))]) == []

    def test_plugin_installed(self):
        events = diff_assets(
            [s(P.format("astra-sites", "3.0"))],
            [s(P.format("astra-sites", "3.0")), s(P.format("wpforms", "1.8"))],
        )
        assert len(events) == 1
        assert events[0]["event_type"] == "plugin_installed"
        assert "wpforms" in events[0]["summary"]

    def test_plugin_removed_is_a_warning(self):
        events = diff_assets(
            [s(P.format("wpforms", "1.8"))],
            [s(P.format("astra-sites", "3.0"))],
        )
        removed = [e for e in events if e["event_type"] == "plugin_removed"]
        assert len(removed) == 1
        # Losing a plugin can silently kill a form or a tracking tag.
        assert removed[0]["severity"] == "warning"

    def test_plugin_updated_records_both_versions(self):
        events = diff_assets(
            [s(P.format("wpforms", "1.8.4"))],
            [s(P.format("wpforms", "1.9.0"))],
        )
        assert len(events) == 1
        e = events[0]
        assert e["event_type"] == "plugin_updated"
        assert e["details"]["old_version"] == "1.8.4"
        assert e["details"]["new_version"] == "1.9.0"
        assert "1.8.4" in e["summary"] and "1.9.0" in e["summary"]

    def test_core_update_detected(self):
        events = diff_assets([s(CORE_JS.format("6.7.1"))], [s(CORE_JS.format("6.8"))])
        assert [e["event_type"] for e in events] == ["core_updated"]
        assert "WordPress core" in events[0]["summary"]

    def test_theme_switch_and_update_both_report_theme_changed(self):
        switched = diff_assets([s(T.format("astra", "4.1"))], [s(T.format("kadence", "1.2"))])
        assert {e["event_type"] for e in switched} == {"theme_changed"}
        assert len(switched) == 2  # one removed, one added

        updated = diff_assets([s(T.format("astra", "4.1"))], [s(T.format("astra", "4.2"))])
        assert [e["event_type"] for e in updated] == ["theme_changed"]

    def test_gaining_a_version_stamp_is_not_an_update(self):
        # "" -> "1.8" means the asset started declaring a version, not that the
        # plugin was upgraded.
        assert diff_assets(
            [s("https://site.example/wp-content/plugins/wpforms/a.js")],
            [s(P.format("wpforms", "1.8"))],
        ) == []

    def test_unchanged_site_reports_nothing(self):
        before = [s(P.format("wpforms", "1.8")), s(CORE_JS.format("6.7.1"))]
        assert diff_assets(before, list(before)) == []

    def test_partial_version_stamping_uses_the_known_version(self):
        # A plugin shipping several files may stamp only some of them; "" must
        # not mask the real version and cause a phantom update next time.
        before = [
            s("https://site.example/wp-content/plugins/wpforms/unversioned.js"),
            s(P.format("wpforms", "1.8")),
        ]
        after = [s(P.format("wpforms", "1.8"))]
        assert diff_assets(before, after) == []

    def test_unversioned_asset_does_not_replace_known_version(self):
        before = [s(P.format("elementor-pro", "4.0.1"))]
        after = [
            s(P.format("elementor-pro", "4.0.1")),
            s("https://site.example/wp-content/plugins/elementor-pro/js/loader.js"),
        ]
        events = diff_assets(before, after)
        assert events == []

    def test_highest_valid_version_wins_when_assets_disagree(self):
        before = [s(P.format("elementor-pro", "4.0.1"))]
        after = [
            s(P.format("elementor-pro", "1.2.1")),
            s(P.format("elementor-pro", "4.0.1")),
        ]
        assert diff_assets(before, after) == []

    def test_third_party_scripts_are_ignored_entirely(self):
        assert diff_assets(
            [s("https://connect.facebook.net/en_US/fbevents.js")],
            [s("https://static.hotjar.com/c/hotjar-1.js")],
        ) == []

    def test_label_prefixes_the_summary(self):
        events = diff_assets(
            [s(P.format("wpforms", "1.8"))],
            [s(P.format("wpforms", "1.9"))],
            label="Acme Ltd",
        )
        assert events[0]["summary"].startswith("Acme Ltd ")
