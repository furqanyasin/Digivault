
from apps.scripts.classifier import ScriptClassifier
from apps.scripts.models import Script


class TestScriptClassifier:
    def test_google_tag_manager(self):
        result = ScriptClassifier.classify(
            "https://www.googletagmanager.com/gtm.js?id=GTM-XXXX"
        )
        assert result.provider == "Google Tag Manager"
        assert result.category == Script.Category.TAG_MANAGEMENT
        assert result.is_known is True

    def test_google_analytics_4(self):
        result = ScriptClassifier.classify(
            "https://www.googletagmanager.com/gtag/js?id=G-XXXXXXXX"
        )
        assert result.provider == "Google Analytics 4"
        assert result.is_known is True

    def test_meta_pixel(self):
        result = ScriptClassifier.classify(
            "https://connect.facebook.net/en_US/fbevents.js"
        )
        assert result.provider == "Meta Pixel"
        assert result.category == Script.Category.ADVERTISING

    def test_hotjar(self):
        result = ScriptClassifier.classify(
            "https://static.hotjar.com/c/hotjar-12345.js"
        )
        assert result.provider == "Hotjar"
        assert result.category == Script.Category.SESSION_RECORDING

    def test_hubspot_analytics(self):
        """The rotating timestamp in the path must not defeat the match."""
        result = ScriptClassifier.classify(
            "https://js.hs-analytics.net/analytics/1785996600000/46377927.js"
        )
        assert result.provider == "HubSpot Analytics"
        assert result.category == Script.Category.ANALYTICS
        assert result.is_known is True

    def test_stripe(self):
        result = ScriptClassifier.classify("https://js.stripe.com/v3/")
        assert result.provider == "Stripe"
        assert result.category == Script.Category.PAYMENT

    def test_unknown_script(self):
        result = ScriptClassifier.classify(
            "https://sketchy-injected-ads.xyz/tracker.js"
        )
        assert result.provider == "unknown"
        assert result.is_known is False

    def test_empty_src(self):
        result = ScriptClassifier.classify("")
        assert result.provider == "unknown"
        assert result.is_known is False

    def test_extract_domain(self):
        assert (
            ScriptClassifier.extract_domain(
                "https://static.hotjar.com/c/hotjar.js"
            )
            == "static.hotjar.com"
        )

    def test_is_critical_provider(self):
        assert ScriptClassifier.is_critical_provider("Google Tag Manager") is True
        assert ScriptClassifier.is_critical_provider("Meta Pixel") is True
        assert ScriptClassifier.is_critical_provider("Hotjar") is False

    def test_whatconverts(self):
        result = ScriptClassifier.classify(
            "https://www.whatconverts.com/js/tracking.js"
        )
        assert result.provider == "WhatConverts"
        assert result.category == Script.Category.CALL_TRACKING

    def test_intercom(self):
        result = ScriptClassifier.classify(
            "https://widget.intercom.io/widget/abc123"
        )
        assert result.provider == "Intercom"
        assert result.category == Script.Category.CHAT

    def test_jquery_cdn(self):
        result = ScriptClassifier.classify(
            "https://ajax.googleapis.com/ajax/libs/jquery/3.6.0/jquery.min.js"
        )
        assert result.provider == "jQuery CDN"
        assert result.category == Script.Category.PERFORMANCE

    def test_clarity_library_host(self):
        # scripts.clarity.ms serves the library; www.clarity.ms/tag serves the
        # per-account tag. Only the latter was recognised, so the library half
        # of every Clarity install was reported as an unknown script.
        result = ScriptClassifier.classify("https://scripts.clarity.ms/0.8.69/clarity.js")
        assert result.provider == "Microsoft Clarity"
        assert result.category == Script.Category.SESSION_RECORDING

    def test_hubspot_ads_pixel(self):
        result = ScriptClassifier.classify("https://js.hsadspixel.net/pixels.js")
        assert result.provider == "HubSpot Ads Pixel"
        assert result.category == Script.Category.ADVERTISING
