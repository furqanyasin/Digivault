"""Heuristic detection of injected / malicious scripts."""

import pytest

from apps.scripts.suspicion import analyse


@pytest.mark.parametrize("url", [
    "https://www.googletagmanager.com/gtm.js?id=GTM-ABC123",
    "https://connect.facebook.net/en_US/fbevents.js",
    "https://cdn.jsdelivr.net/npm/swiper@8/swiper-bundle.min.js",
    "https://js.stripe.com/v3",
    "https://static.hotjar.com/c/hotjar-123.js",
])
def test_known_good_scripts_are_clean(url):
    """The everyday tag stack must never be flagged — a scanner that cries wolf
    on Google Tag Manager gets ignored entirely."""
    assert analyse(url).is_suspicious is False


@pytest.mark.parametrize("url,fragment", [
    ("data:text/javascript;base64,YWxlcnQoMSk=", "inline"),
    ("https://evil.test/x.js?cb=eval(atob('...'))", "obfuscation"),
    ("https://bit.ly/3xYz", "disposable"),
    ("http://203.0.113.9/inject.js", "bare IP"),
    ("https://cheap-viagra-online.test/a.js", "SEO-spam"),
])
def test_injected_patterns_are_flagged(url, fragment):
    out = analyse(url)
    assert out.is_suspicious is True
    assert out.severity in {"high", "medium", "low"}
    assert any(fragment.lower() in r.lower() for r in out.reasons), out.reasons


def test_reasons_are_always_reported():
    """A bare "suspicious" label is unactionable; the reason must travel with it."""
    out = analyse("http://198.51.100.4/x.js")
    assert out.reasons and all(isinstance(r, str) and r for r in out.reasons)


def test_random_looking_host_on_own_domain_is_allowed():
    """A site's own build output often has hashed filenames and subdomains; only
    off-domain machine-generated hosts are interesting."""
    own = analyse("https://a8f3ke92mfk20dls.acme.test/app.js", site_domain="acme.test")
    other = analyse("https://a8f3ke92mfk20dls.random.test/app.js", site_domain="acme.test")
    assert own.is_suspicious is False
    assert other.is_suspicious is True


def test_empty_and_malformed_input_never_raises():
    for value in ["", "   ", "not a url", "//", "https://", "javascript:void(0)"]:
        analyse(value)  # must not raise


def test_protocol_relative_url_is_parsed():
    """Snippets frequently emit //host/path; the host still has to be checked."""
    assert analyse("//bit.ly/abc").is_suspicious is True


@pytest.fixture
def site(team):
    from apps.websites.models import Website
    return Website.objects.create(team=team, name="Suspect Site", domain="suspect.test")


def _ingest(api_client, site, *srcs):
    """POST scripts through the real ingest endpoint. Celery runs eagerly in the
    test settings, so the whole pipeline executes inline."""
    return api_client.post("/api/ingest/", {
        "site_id": site.site_id,
        "page_url": f"https://{site.domain}/",
        "scripts": [{"src": s} for s in srcs],
    }, format="json")


@pytest.mark.django_db
def test_ingest_flags_a_suspicious_script(api_client, site):
    """End to end: a disposable-host script arriving via /api/ingest/ lands with
    the flag and its reasons attached, and a legitimate one does not."""
    from apps.scripts.models import Script

    # GTM rather than a CDN: utility CDNs are filtered out of tracking entirely
    # by _should_track_script, so they never reach the suspicion check.
    resp = _ingest(api_client, site,
                   "https://www.googletagmanager.com/gtm.js?id=GTM-ABC123",
                   "https://bit.ly/evilpayload")
    assert resp.status_code in (200, 201, 202), resp.data

    good = Script.objects.get(website=site, src_url__contains="googletagmanager")
    bad = Script.objects.get(website=site, src_url__contains="bit.ly")
    assert good.is_suspicious is False
    assert bad.is_suspicious is True
    assert bad.suspicion_severity == "high"
    assert bad.suspicion_reasons, "the reason must be stored alongside the flag"


@pytest.mark.django_db
def test_suspicion_is_reassessed_on_every_ingest(api_client, site):
    """Re-evaluated on update, not only on create — a URL can start benign and be
    swapped for something hostile later, which is the case worth catching."""
    from apps.scripts.models import Script

    _ingest(api_client, site, "http://203.0.113.9/a.js")
    flagged = Script.objects.get(website=site, src_url__contains="203.0.113.9")
    assert flagged.is_suspicious is True
    assert "bare IP" in " ".join(flagged.suspicion_reasons)
