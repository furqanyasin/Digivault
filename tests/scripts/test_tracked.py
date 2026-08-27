"""The tracking inventory: which scripts the Scripts tab lists, and under what name."""

import pytest

from apps.scripts.classifier import ScriptClassifier
from apps.scripts.models import Script
from apps.scripts.tracked import is_tracked, provider_family


def _classify(url: str) -> tuple[str, str]:
    """(family, category) for a URL, exactly as the serializer derives them."""
    result = ScriptClassifier.classify(url)
    return provider_family(result.provider), result.category


class TestProviderFamily:
    """One vendor, one name — however many products it ships."""

    def test_google_products_collapse_to_one_family(self):
        families = {
            provider_family(p)
            for p in (
                "Google Analytics 4",
                "Google Universal Analytics",
                "Google Tag Manager",
                "Google Ads",
                "Google AdSense",
                "Google Optimize",
                "Google Static CDN",
            )
        }
        assert families == {"Google"}

    def test_hubspot_products_collapse_to_one_family(self):
        families = {
            provider_family(p)
            for p in (
                "HubSpot",
                "HubSpot Analytics",
                "HubSpot Forms",
                "HubSpot Live Chat",
                "HubSpot Ads Pixel",
                "HubSpot Cookie Banner",
                "HubSpot Meetings",
                "HubSpot API",
            )
        }
        assert families == {"HubSpot"}

    def test_hotjar_and_whatconverts_keep_their_name(self):
        assert provider_family("Hotjar") == "Hotjar"
        assert provider_family("WhatConverts") == "WhatConverts"

    def test_unrelated_products_of_one_vendor_stay_apart(self):
        # A "first word of the name" shortcut would merge these two: session
        # recording and advertising, which a reader needs to tell apart.
        assert provider_family("Microsoft Clarity") == "Microsoft Clarity"
        assert provider_family("Microsoft Bing UET") == "Microsoft Bing UET"

    def test_unknown_and_blank_are_safe_labels(self):
        assert provider_family("unknown") == "unknown"
        assert provider_family("") == "unknown"

    def test_unrecognised_vendor_passes_through(self):
        assert provider_family("Klaviyo") == "Klaviyo"


class TestIsTracked:
    def test_tracking_categories_are_kept(self):
        for category in (
            Script.Category.ANALYTICS,
            Script.Category.ADVERTISING,
            Script.Category.TAG_MANAGEMENT,
            Script.Category.SESSION_RECORDING,
            Script.Category.CALL_TRACKING,
            Script.Category.CHAT,
            Script.Category.CRM,
            Script.Category.PAYMENT,
        ):
            assert is_tracked(category) is True, category

    def test_infrastructure_and_decoration_are_dropped(self):
        for category in (
            Script.Category.PERFORMANCE,
            Script.Category.SOCIAL,
            Script.Category.SECURITY,
            Script.Category.UNKNOWN,
        ):
            assert is_tracked(category) is False, category

    def test_suspicious_script_is_always_kept(self):
        # Injected code classifies as unknown by definition, so the category
        # rule alone would hide exactly what most needs looking at.
        assert is_tracked(Script.Category.UNKNOWN, is_suspicious=True) is True
        assert is_tracked(Script.Category.PERFORMANCE, is_suspicious=True) is True


class TestTheFourVendorsTheTabMustShow:
    """Google, Hotjar, HubSpot and WhatConverts, each named once and kept."""

    def test_google_analytics_and_tag_manager_are_both_google_and_tracked(self):
        for url in (
            "https://www.googletagmanager.com/gtag/js?id=G-XXXXXXXX",
            "https://www.googletagmanager.com/gtm.js?id=GTM-XXXX",
            "https://www.googletagmanager.com/gtag/destination?id=AW-123",
            "https://www.googleadservices.com/pagead/conversion.js",
        ):
            family, category = _classify(url)
            assert family == "Google", url
            assert is_tracked(category) is True, url

    def test_hotjar_from_both_of_its_hosts(self):
        for url in (
            "https://static.hotjar.com/c/hotjar-123.js?sv=6",
            "https://script.hotjar.com/modules.06e2f0c4d4b1a3f9.js",
        ):
            family, category = _classify(url)
            assert family == "Hotjar", url
            assert is_tracked(category) is True, url

    def test_hubspot_across_its_products(self):
        for url in (
            "https://js.hs-scripts.com/1234567.js",
            "https://js.hs-analytics.net/analytics/1700000000000/1234567.js",
            "https://js.hsforms.net/forms/embed/v2.js",
            "https://js.hsadspixel.net/fb.js",
        ):
            family, category = _classify(url)
            assert family == "HubSpot", url
            assert is_tracked(category) is True, url

    def test_whatconverts_including_its_obfuscated_host(self):
        for url in (
            "https://www.whatconverts.com/js/tracking.js",
            "https://ksrndkehqnwntyxlhgto.com/wc.js",
        ):
            family, category = _classify(url)
            assert family == "WhatConverts", url
            assert is_tracked(category) is True, url


class TestNoiseTheTabMustNotShow:
    def test_js_libraries_and_cdns_are_dropped(self):
        for url in (
            "https://code.jquery.com/jquery-3.6.0.min.js",
            "https://cdn.jsdelivr.net/npm/bootstrap@5/dist/js/bootstrap.min.js",
            "https://cdnjs.cloudflare.com/ajax/libs/gsap/3.11/gsap.min.js",
            "https://unpkg.com/react@18/umd/react.production.min.js",
            "https://cdn.tailwindcss.com",
        ):
            _, category = _classify(url)
            assert is_tracked(category) is False, url

    def test_video_players_are_dropped(self):
        for url in (
            "https://www.youtube.com/iframe_api",
            "https://s.ytimg.com/yts/jsbin/www-widgetapi.js",
            "https://player.vimeo.com/api/player.js",
            "https://fast.wistia.net/assets/external/E-v1.js",
        ):
            _, category = _classify(url)
            assert is_tracked(category) is False, url

    def test_google_fonts_maps_and_cdn_are_dropped_despite_the_family(self):
        # Same vendor family as GA4, deliberately not the same verdict: the
        # category rule runs independently of the family.
        for url in (
            "https://fonts.googleapis.com/css2?family=Inter",
            "https://maps.googleapis.com/maps/api/js?key=abc",
            "https://www.gstatic.com/_/mss/boq-one-google/_/js/k=x.js",
        ):
            family, category = _classify(url)
            assert family == "Google", url
            assert is_tracked(category) is False, url

    def test_share_buttons_and_review_widgets_are_dropped(self):
        for url in (
            "https://platform.twitter.com/widgets.js",
            "https://static.addtoany.com/menu/page.js",
            "https://widget.trustpilot.com/bootstrap/v5/tp.widget.bootstrap.min.js",
        ):
            _, category = _classify(url)
            assert is_tracked(category) is False, url

    def test_recaptcha_is_dropped(self):
        _, category = _classify("https://www.google.com/recaptcha/api.js")
        assert is_tracked(category) is False


@pytest.mark.django_db
def test_script_list_endpoint_carries_family_and_tracked(auth_client, team):
    """The API is the single source of truth for both — the frontend reads it."""
    from apps.websites.models import Website

    site = Website.objects.create(team=team, name="Site", domain="site.io")
    Script.objects.create(
        website=site,
        src_url="https://www.googletagmanager.com/gtag/js?id=G-ABC",
        provider="Google Analytics 4",
        category=Script.Category.ANALYTICS,
    )
    Script.objects.create(
        website=site,
        src_url="https://code.jquery.com/jquery-3.6.0.min.js",
        provider="jQuery CDN",
        category=Script.Category.PERFORMANCE,
    )

    resp = auth_client.get(f"/api/v1/websites/{site.id}/scripts/")
    assert resp.status_code == 200

    rows = {r["src_url"]: r for r in resp.data}
    ga4 = rows["https://www.googletagmanager.com/gtag/js?id=G-ABC"]
    assert ga4["provider_family"] == "Google"
    assert ga4["is_tracked"] is True

    jquery = rows["https://code.jquery.com/jquery-3.6.0.min.js"]
    assert jquery["is_tracked"] is False
