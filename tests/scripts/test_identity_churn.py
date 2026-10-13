"""Regression tests for the four identity gaps that churned a live site.

Every URL here is a real one taken from the production database of a site that
logged 23 unacknowledged script changes across four days during which nobody
touched it. Each group below was one row in that alert list.
"""

from datetime import datetime, timedelta

import pytest

from apps.scripts.classifier import ScriptClassifier
from apps.scripts.diff_engine import DiffEngine
from apps.scripts.models import ScriptChange
from apps.scripts.normalize import (
    identity_label,
    is_identity_host,
    normalize_script_url,
)
from apps.scripts.tasks import _group_into_loads, _DIFF_LOADS, _should_track_script
from apps.scripts.tracked import is_tracked


def _ids(urls):
    return {normalize_script_url(u) for u in urls}


class TestOneTagOneIdentity:
    """Rotating runtime state must not mint a second identity."""

    def test_meta_pixel_release_channel_is_not_identity(self):
        # `r=stable` / `r=c2` / `im=1` held one pixel as three Script rows, which
        # then took turns going missing and reported each other as URL changes.
        assert len(_ids([
            "https://connect.facebook.net/signals/config/7847387958713764"
            "?domain=acme-agency.com&im=1&r=stable",
            "https://connect.facebook.net/signals/config/7847387958713764"
            "?domain=acme-agency.com&r=c2",
            "https://connect.facebook.net/signals/config/7847387958713764"
            "?domain=acme-agency.com&r=stable",
        ])) == 1

    def test_distinct_meta_pixels_stay_distinct(self):
        assert len(_ids([
            "https://connect.facebook.net/signals/config/7847387958713764?r=stable",
            "https://connect.facebook.net/signals/config/1024047359051930?r=stable",
            "https://connect.facebook.net/signals/config/2225858391073494?r=stable",
        ])) == 3

    def test_recaptcha_onload_callback_is_not_identity(self):
        # HubSpot's embed puts a fresh UUID in `onload=` on every page load.
        assert len(_ids([
            "https://www.recaptcha.net/recaptcha/enterprise.js?hl=en"
            "&onload=hsRecaptchaLoaded_4e806ea2_8308_46c5_9b89_3054d907db2c"
            "&render=explicit",
            "https://www.recaptcha.net/recaptcha/enterprise.js?hl=en"
            "&onload=hsRecaptchaLoaded_dc0ab914_03ae_4dd7_b12e_ec794369f0da"
            "&render=explicit",
        ])) == 1

    @pytest.mark.parametrize("url", [
        "js.hs-scripts.com/46377927.js",
        "s.ksrndkehqnwntyxlhgto.com/130730.js",
    ])
    def test_scheme_is_not_identity(self, url):
        assert normalize_script_url(f"http://{url}") == normalize_script_url(
            f"https://{url}"
        )

    def test_release_token_below_releases_dir_is_not_identity(self):
        assert len(_ids([
            "https://www.gstatic.com/recaptcha/releases/"
            "8x-4t2pegToiW8KmThtO4AQt/recaptcha__en.js",
            "https://www.gstatic.com/recaptcha/releases/"
            "ox8dsmiqR62P1bqhciWOn7Fg/recaptcha__en.js",
        ])) == 1

    def test_bare_uuid_path_segment_is_not_identity(self):
        assert len(_ids([
            "https://infird.com/cdn/986df696-a484-42dc-a3ed-0466520e31dc",
            "https://infird.com/cdn/c8d3a069-77c7-41b6-927e-06a4c17fac35",
        ])) == 1

    def test_account_paths_are_not_mistaken_for_build_tokens(self):
        # The conservative half of the rule. A bare "long opaque segment" rule
        # would merge unrelated third parties keyed by an account path.
        assert len(_ids([
            "https://spaces-us-1.nyc3.digitaloceanspaces.com/"
            "RMieIJj0M7RIDmr7/BLF9r_5XjpFWh0ZoYb47n/pixel.js",
            "https://spaces-us-1.nyc3.digitaloceanspaces.com/"
            "AAieIJj0M7RIDmr7/BBF9r_5XjpFWh0ZoYb47n/pixel.js",
        ])) == 2


class TestGoogleTagProducts:
    """One loader path serves every Google product; the id prefix names it."""

    @pytest.mark.parametrize("url,provider,category", [
        ("https://www.googletagmanager.com/gtag/js?id=G-VEFCZRQMG4",
         "Google Analytics 4", "analytics"),
        ("https://www.googletagmanager.com/gtag/js?id=AW-925662148",
         "Google Ads", "advertising"),
        ("https://www.googletagmanager.com/gtag/js?id=GF-877",
         "Google Ads Call Forwarding", "call_tracking"),
        ("https://www.googletagmanager.com/gtag/destination?id=AW-925662148",
         "Google Ads", "advertising"),
        ("https://www.googletagmanager.com/gtag/destination?id=G-LC6FS8Y01E",
         "Google Analytics 4", "analytics"),
        ("https://www.googletagmanager.com/gtm.js?id=GTM-N32TK6DJ",
         "Google Tag Manager", "tag_management"),
    ])
    def test_prefix_decides_the_product(self, url, provider, category):
        result = ScriptClassifier.classify(url)
        assert (result.provider, result.category) == (provider, category)

    def test_id_must_start_a_query_param(self):
        # `cid=AW-1` must not make this an Ads tag.
        result = ScriptClassifier.classify(
            "https://www.googletagmanager.com/gtag/js?cid=AW-1&id=G-REAL"
        )
        assert result.provider == "Google Analytics 4"


class TestFabricatedUrlChanged:
    """A tag going missing while a different tag of the same vendor arrives."""

    def test_ads_and_ga4_swap_is_not_a_url_change(self):
        # The exact shape that produced "Google Analytics 4 URL changed" at high
        # severity: two unrelated tags, one loader path, one provider name.
        previous = [{"src": "https://www.googletagmanager.com/gtag/js?id=AW-861889798",
                     "location": "head"}]
        current = [{"src": "https://www.googletagmanager.com/gtag/js?id=G-VEFCZRQMG4",
                    "location": "head"}]
        changes = DiffEngine.diff(previous, current)
        assert not any(
            c.change_type == ScriptChange.ChangeType.URL_CHANGED for c in changes
        )
        assert {c.change_type for c in changes} == {
            ScriptChange.ChangeType.REMOVED, ScriptChange.ChangeType.ADDED
        }

    def test_meta_pixel_library_and_config_are_not_a_swap(self):
        previous = [{"src": "https://connect.facebook.net/en_US/pcm.js",
                     "location": "head"}]
        current = [{"src": "https://connect.facebook.net/signals/config/"
                           "7847387958713764?r=stable", "location": "head"}]
        changes = DiffEngine.diff(previous, current)
        assert not any(
            c.change_type == ScriptChange.ChangeType.URL_CHANGED for c in changes
        )

    def test_versioned_unknown_widget_still_collapses(self):
        # The case url_changed exists for, which must keep working.
        previous = [{"src": "https://widgets.example.com/embed-1.2.js",
                     "location": "head"}]
        current = [{"src": "https://widgets.example.com/embed-9.9.js",
                    "location": "head"}]
        changes = DiffEngine.diff(previous, current)
        assert [c.change_type for c in changes] == [
            ScriptChange.ChangeType.URL_CHANGED
        ]

    def test_same_vendor_different_file_is_not_a_swap(self):
        # LinkedIn serves both side by side; they are two integrations.
        previous = [{"src": "https://snap.licdn.com/li.lms-analytics/insight.min.js",
                     "location": "head"}]
        current = [{"src": "https://snap.licdn.com/li.lms-analytics/insight.old.min.js",
                    "location": "head"}]
        changes = DiffEngine.diff(previous, current)
        assert not any(
            c.change_type == ScriptChange.ChangeType.URL_CHANGED for c in changes
        )


class TestChangeDescriptionsNameTheTag:
    """Three separate tags must not read as one event logged three times."""

    def test_removed_description_carries_the_tag_id(self):
        changes = DiffEngine.diff(
            [{"src": "https://www.googletagmanager.com/gtag/js?id=G-VEFCZRQMG4",
              "location": "head"}],
            [],
        )
        assert changes[0].description == (
            "Critical script removed: Google Analytics 4 (G-VEFCZRQMG4)"
        )

    def test_three_google_tags_produce_three_distinct_descriptions(self):
        previous = [
            {"src": f"https://www.googletagmanager.com/gtag/js?id={tag}",
             "location": "head"}
            for tag in ("G-VEFCZRQMG4", "AW-925662148", "AW-10903074564")
        ]
        changes = DiffEngine.diff(previous, [])
        assert len({c.description for c in changes}) == 3

    @pytest.mark.parametrize("url,label", [
        ("https://www.googletagmanager.com/gtag/js?id=G-VEFCZRQMG4", "G-VEFCZRQMG4"),
        ("https://connect.facebook.net/signals/config/7847387958713764?r=stable",
         "7847387958713764"),
        ("https://www.clarity.ms/tag/i9x3wxzn9k", "i9x3wxzn9k"),
        ("https://static.hotjar.com/c/hotjar-3065386.js", "hotjar-3065386"),
        # A filename is not an account id.
        ("https://connect.facebook.net/en_US/fbevents.js", ""),
        ("https://snap.licdn.com/li.lms-analytics/insight.min.js", ""),
    ])
    def test_identity_label(self, url, label):
        assert identity_label(url) == label

    @pytest.mark.parametrize("url,expected", [
        ("https://www.googletagmanager.com/gtm.js?id=GTM-A", True),
        ("https://connect.facebook.net/signals/config/123456", True),
        ("https://snap.licdn.com/li.lms-analytics/insight.min.js", False),
    ])
    def test_is_identity_host(self, url, expected):
        assert is_identity_host(url) is expected


class TestComparisonWindowsAreCountedInLoads:
    """A window of snapshots could sit entirely inside one page load."""

    @staticmethod
    def _rows(*offsets_and_scripts):
        base = datetime(2026, 9, 8, 10, 0, 0)
        return [
            (base + timedelta(seconds=off), scripts)
            for off, scripts in offsets_and_scripts
        ]

    def test_six_posts_of_one_load_are_one_load(self):
        # Live production data for one pageview: six posts across three seconds,
        # carrying 35-39 scripts as GTM injected them. Counted in snapshots,
        # both windows came from this single load and the four-script spread
        # surfaced as a removal.
        rows = self._rows(
            (161, ["a", "b", "c"]), (161, ["a", "b"]), (161, ["a", "b", "c"]),
            (160, ["a"]), (160, ["a", "b", "c"]), (159, ["a"]),
        )
        loads = _group_into_loads(rows)
        assert len(loads) == 1
        baseline = [
            s for load in loads[_DIFF_LOADS:_DIFF_LOADS * 2] for s in load
        ]
        assert baseline == []

    def test_separate_visits_are_separate_runs(self):
        # Homepage series: 10:14:39, 10:15:53, 10:15:54, 10:17:31.
        rows = self._rows((451, ["a"]), (354, ["a"]), (353, ["a"]), (279, ["a"]))
        assert len(_group_into_loads(rows)) == 3

    def test_bucket_boundary(self):
        assert len(_group_into_loads(self._rows((59, ["a"]), (0, ["b"])))) == 1
        assert len(_group_into_loads(self._rows((61, ["a"]), (0, ["b"])))) == 2

    def test_continuous_traffic_still_produces_a_baseline(self):
        # The failure mode that ruled out chaining on inter-post gaps: a page
        # getting a visit every twenty seconds has no gap anywhere in its
        # history, so gap-chaining collapsed all of it into one unbounded load
        # and left the baseline window permanently empty — removal detection
        # silently off on exactly the busiest pages.
        rows = self._rows(*[(600 - i * 20, ["a"]) for i in range(30)])
        runs = _group_into_loads(rows)
        assert len(runs) >= 6
        assert [s for run in runs[_DIFF_LOADS:_DIFF_LOADS * 2] for s in run]

    def test_windows_do_not_overlap(self):
        rows = self._rows(*[(1000 - i * 120, [f"s{i}"]) for i in range(6)])
        loads = _group_into_loads(rows)
        current = [s for load in loads[:_DIFF_LOADS] for s in load]
        baseline = [s for load in loads[_DIFF_LOADS:_DIFF_LOADS * 2] for s in load]
        assert len(current) == len(baseline) == _DIFF_LOADS
        assert not set(map(tuple, current)) & set(map(tuple, baseline))

    def test_empty_and_null_rows(self):
        assert _group_into_loads([]) == []
        assert _group_into_loads(self._rows((0, None))) == [[[]]]


class TestKnownInfrastructureLeavesTheInventory:
    """performance / social / security are dropped, not merely hidden."""

    @pytest.mark.parametrize("url", [
        "https://www.youtube.com/iframe_api",
        "https://www.youtube.com/www-widgetapi.js",
        "https://www.youtube.com/s/player/9470c977/"
        "www-widgetapi.vflset/www-widgetapi.js",
        "https://www.gstatic.com/recaptcha/releases/x/recaptcha__en.js",
        "https://www.gstatic.cn/recaptcha/releases/x/recaptcha__en.js",
        "https://www.google.com/recaptcha/api.js?render=explicit",
        "https://code.jquery.com/jquery-3.6.0.min.js",
    ])
    def test_dropped(self, url):
        assert _should_track_script(url, "acme-agency.com") is False

    @pytest.mark.parametrize("url", [
        # Not a monitored vendor: unknown third parties and other vendors alike.
        "https://infird.com/cdn/986df696-a484-42dc-a3ed-0466520e31dc",
        "https://spaces-us-1.nyc3.digitaloceanspaces.com/a/b/pixel.js",
        "https://bat.bing.com/p/action/13001299.js",
        "https://tags.creativecdn.com/VKCPIkUjhj4YmK37qf62.js",
        "https://connect.facebook.net/en_US/fbevents.js",
    ])
    def test_unmonitored_vendors_are_dropped(self, url):
        assert _should_track_script(url, "acme-agency.com") is False

    @pytest.mark.parametrize("url", [
        "https://app-cdn.clickup.com/assets/js/forms-embed/v1.js",
        "https://www.googletagmanager.com/gtag/js?id=G-VEFCZRQMG4",
        "https://static.hotjar.com/c/hotjar-3065386.js",
    ])
    def test_kept(self, url):
        assert _should_track_script(url, "acme-agency.com") is True

    def test_injected_code_overrides_the_vendor_rule(self):
        # The invariant that keeps this a noise filter rather than a blind spot.
        assert _should_track_script("https://45.12.9.1/wp.js", "acme-agency.com") is True
        assert is_tracked("https://45.12.9.1/wp.js", "high") is True

    @pytest.mark.parametrize("url,provider", [
        ("https://bat.bing.com/p/action/13001299.js", "Microsoft Bing UET"),
        ("https://bat.bing.com/p/insights/t/13001299", "Microsoft Bing UET"),
        ("https://tags.creativecdn.com/VKCPIkUjhj4YmK37qf62.js", "RTB House"),
        ("https://app-cdn.clickup.com/assets/js/forms-embed/v1.js", "ClickUp Forms"),
        ("https://www.gstatic.cn/recaptcha/releases/x/recaptcha__en.js",
         "Google Static CDN"),
        ("https://www.youtube.com/www-widgetapi.js", "YouTube IFrame API"),
    ])
    def test_previously_unknown_vendors_are_named(self, url, provider):
        # Each of these was scoring as a high-severity "Unknown script detected".
        assert ScriptClassifier.classify(url).provider == provider


class TestCriticalProvidersHaveOneSourceOfTruth:
    @pytest.mark.parametrize("provider,critical", [
        ("Google Tag Manager", True),
        ("Google Analytics 4", True),
        ("Google Ads", True),
        ("Meta Pixel", True),
        ("Hotjar", False),
        ("Google Static CDN", False),
    ])
    def test_diff_engine_and_classifier_agree(self, provider, critical):
        assert ScriptClassifier.is_critical_provider(provider) is critical
        assert DiffEngine._is_critical(provider) is critical
