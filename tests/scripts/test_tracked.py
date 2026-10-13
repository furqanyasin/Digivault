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

    def test_gohighlevel_products_collapse_to_one_family(self):
        assert provider_family("LeadConnector (GoHighLevel)") == "GoHighLevel"
        assert provider_family("GoHighLevel Forms") == "GoHighLevel"
        assert provider_family("ClickUp Forms") == "ClickUp"

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
    """Only the six monitored vendors' installed tags. See apps/scripts/monitored.py."""

    def test_high_suspicion_is_always_kept(self):
        # Injected code is nobody's vendor; the allowlist must not hide it.
        assert is_tracked("https://cdn.example.net/x.js", "high") is True

    def test_weaker_suspicion_is_not_enough(self):
        assert is_tracked("https://cdn.example.net/x.js", "medium") is False


class TestTheSixVendorsTheTabMustShow:
    """Google, HubSpot, Hotjar, WhatConverts, ClickUp, GoHighLevel — the tags
    a site installs, each named by its family."""

    @pytest.mark.parametrize("url,family", [
        ("https://www.googletagmanager.com/gtag/js?id=G-XXXXXXXX", "Google"),
        ("https://www.googletagmanager.com/gtm.js?id=GTM-XXXX", "Google"),
        ("https://www.googletagmanager.com/gtag/destination?id=AW-123", "Google"),
        ("https://www.googleadservices.com/pagead/conversion.js", "Google"),
        ("https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js"
         "?client=ca-pub-7089372697568091", "Google"),
        ("https://static.hotjar.com/c/hotjar-123.js?sv=6", "Hotjar"),
        ("https://js.hs-scripts.com/1234567.js", "HubSpot"),
        ("https://js.hs-analytics.net/analytics/1700000000000/1234567.js", "HubSpot"),
        ("https://js.hsforms.net/forms/embed/v2.js", "HubSpot"),
        ("https://www.whatconverts.com/js/tracking.js", "WhatConverts"),
        ("https://ksrndkehqnwntyxlhgto.com/wc.js", "WhatConverts"),
        ("https://s.ksrndkehqnwntyxlhgto.com/130730.js", "WhatConverts"),
        ("https://app-cdn.clickup.com/assets/js/forms-embed/v1.js", "ClickUp"),
        ("https://widgets.leadconnectorhq.com/loader.js", "GoHighLevel"),
        ("https://link.msgsndr.com/js/form_embed.js", "GoHighLevel"),
    ])
    def test_kept_and_named(self, url, family):
        assert is_tracked(url) is True
        assert _classify(url)[0] == family


class TestNoiseTheTabMustNotShow:
    @pytest.mark.parametrize("url", [
        # Other vendors: not on the list, so not watched.
        "https://connect.facebook.net/en_US/fbevents.js",
        "https://www.clarity.ms/tag/i9x3wxzn9k",
        "https://analytics.tiktok.com/i18n/pixel/events.js?sdkid=X",
        "https://cdn-cookieyes.com/client_data/abc/script.js",
        "https://consent.trustarc.com/asset/notice.js/v/2872571",
        "https://spaces-us-1.nyc3.digitaloceanspaces.com/a/b/pixel.js",
        # Libraries, video players, widgets.
        "https://code.jquery.com/jquery-3.6.0.min.js",
        "https://www.youtube.com/iframe_api",
        "https://platform.twitter.com/widgets.js",
        # Google, but not a tag: fonts, maps, CDN, reCAPTCHA, a tag with no id.
        "https://fonts.googleapis.com/css2?family=Inter",
        "https://maps.googleapis.com/maps/api/js?key=abc",
        "https://www.gstatic.com/_/mss/boq-one-google/_/js/k=x.js",
        "https://www.google.com/recaptcha/api.js",
        "https://www.googletagmanager.com/gtm.js",
    ])
    def test_dropped(self, url):
        assert is_tracked(url) is False

    @pytest.mark.parametrize("url", [
        # Files a monitored tag's loader fetches on its own: the vendor's
        # business, not a change to the site.
        "https://script.hotjar.com/modules.06e2f0c4d4b1a3f9.js",
        "https://js.hsadspixel.net/fb.js",
        "https://js.hscollectedforms.net/collectedforms.js",
        "https://pagead2.googlesyndication.com/pagead/managed/js/adsense/"
        "m202609210101/show_ads_impl_fy2021.js",
    ])
    def test_loader_sub_resources_are_dropped(self, url):
        assert is_tracked(url) is False


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
