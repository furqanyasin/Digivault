"""Page identity for the heatmap.

A heatmap is *of a page*, so the answer to "which page is this?" has to be the
same on every pageview or one page's heat splits across a dozen rows that each
look like a lonely, barely-visited page. These are pure-function tests — no DB,
no request — because `normalize_page_url` is the whole rule.
"""

import pytest

from apps.heatmap.page_urls import normalize_page_url


class TestNormalizePageUrl:
    @pytest.mark.parametrize(
        "raw",
        [
            "https://example.com/pricing/",
            "http://example.com/pricing/",
            "https://www.example.com/pricing/",
            "https://EXAMPLE.com/pricing/",
            "https://example.com/pricing",
            "https://example.com/pricing/index.html",
            "https://example.com/pricing/#plans",
            "https://example.com/pricing/?utm_source=google&utm_medium=cpc",
            "https://example.com/pricing/?gclid=abc",
            "https://example.com:443/pricing/",
        ],
    )
    def test_all_spellings_of_one_page_agree(self, raw):
        assert normalize_page_url(raw) == "https://example.com/pricing/"

    def test_routing_params_are_kept(self):
        """`?p=12` selects content; `?utm_source=x` describes the referrer."""
        assert normalize_page_url("https://example.com/?p=12") == (
            "https://example.com/?p=12"
        )

    def test_routing_params_are_order_independent(self):
        a = normalize_page_url("https://example.com/shop/?lang=fr&page=2")
        b = normalize_page_url("https://example.com/shop/?page=2&lang=fr")
        assert a == b == "https://example.com/shop/?lang=fr&page=2"

    def test_unknown_params_are_dropped_but_known_ones_survive(self):
        assert normalize_page_url(
            "https://example.com/shop/?utm_campaign=spring&product=hat"
        ) == "https://example.com/shop/?product=hat"

    def test_different_routing_values_stay_different_pages(self):
        assert normalize_page_url("https://example.com/?p=11") != normalize_page_url(
            "https://example.com/?p=12"
        )

    def test_a_file_path_keeps_its_extension(self):
        """Only directory-ish paths gain a trailing slash."""
        assert normalize_page_url("https://example.com/report.pdf") == (
            "https://example.com/report.pdf"
        )

    def test_non_default_port_is_preserved(self):
        assert normalize_page_url("https://example.com:8443/x/") == (
            "https://example.com:8443/x/"
        )

    @pytest.mark.parametrize("raw", ["", "   ", None, "not a url", "/relative/path"])
    def test_unusable_input_returns_empty(self, raw):
        # Callers treat "" as "drop this payload": a page that cannot be keyed
        # cannot be aggregated into anything.
        assert normalize_page_url(raw) == ""

    def test_result_is_length_capped(self):
        long_url = "https://example.com/" + ("a" * 5000) + "/"
        assert len(normalize_page_url(long_url)) <= 2048
