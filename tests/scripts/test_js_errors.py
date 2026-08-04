"""JavaScript error capture — fingerprinting, noise filtering and ingest."""

import pytest

from apps.scripts.js_errors import browser_label, fingerprint, is_reportable
from apps.scripts.models import JsError


class TestReportable:
    def test_cross_origin_script_error_is_dropped(self):
        """Browsers report "Script error." for any cross-origin exception without
        CORS headers — no message, file or line, so it is unactionable."""
        assert is_reportable("Script error.") is False

    def test_browser_extension_errors_are_dropped(self):
        """A visitor's extension throwing is not the site's bug."""
        assert is_reportable("boom", "chrome-extension://abc/inject.js") is False
        assert is_reportable("boom", "moz-extension://abc/inject.js") is False

    def test_resize_observer_noise_is_dropped(self):
        assert is_reportable("ResizeObserver loop limit exceeded") is False

    def test_empty_message_is_dropped(self):
        assert is_reportable("") is False
        assert is_reportable("   ") is False

    def test_a_real_error_is_kept(self):
        assert is_reportable("TypeError: x.foo is not a function", "https://s.test/a.js") is True


class TestFingerprint:
    def test_same_error_same_fingerprint(self):
        a = fingerprint("TypeError: x is undefined", "https://s.test/a.js", 12)
        b = fingerprint("TypeError: x is undefined", "https://s.test/a.js", 12)
        assert a == b

    def test_ids_in_the_message_do_not_split_the_group(self):
        """Numbers are normalised, so an error carrying an id or timestamp does
        not become a brand-new row every time it fires."""
        a = fingerprint("Failed to load order 12345")
        b = fingerprint("Failed to load order 98765")
        assert a == b

    def test_different_file_is_a_different_error(self):
        a = fingerprint("TypeError: x", "https://s.test/a.js", 1)
        b = fingerprint("TypeError: x", "https://s.test/b.js", 1)
        assert a != b


class TestBrowserLabel:
    @pytest.mark.parametrize("ua,expected", [
        ("Mozilla/5.0 ... Chrome/120.0 Safari/537.36", "Chrome"),
        ("Mozilla/5.0 ... Chrome/120 Safari/537.36 Edg/120.0", "Edge"),
        ("Mozilla/5.0 ... Firefox/121.0", "Firefox"),
        ("Mozilla/5.0 ... Version/17.0 Safari/605.1.15", "Safari"),
        ("", ""),
    ])
    def test_family_only(self, ua, expected):
        """Only the family is stored — a full UA string is a fingerprinting
        surface with no benefit here."""
        assert browser_label(ua) == expected


@pytest.fixture
def site(team):
    from apps.websites.models import Website
    return Website.objects.create(team=team, name="JS Site", domain="jssite.test")


def _post(api_client, site, **over):
    body = {
        "site_id": site.site_id,
        "page_url": f"https://{site.domain}/pricing",
        "message": "TypeError: cart.total is not a function",
        "source_url": "https://jssite.test/app.js",
        "line_no": 42,
        "col_no": 7,
    }
    body.update(over)
    return api_client.post("/api/ingest/js-errors/", body, format="json")


@pytest.mark.django_db
class TestJsErrorIngest:
    def test_stores_a_real_error(self, api_client, site):
        resp = _post(api_client, site)
        assert resp.status_code == 202
        err = JsError.objects.get(website=site)
        assert err.line_no == 42 and err.col_no == 7
        assert err.hits == 1
        assert "cart.total" in err.message

    def test_repeats_increment_hits_instead_of_adding_rows(self, api_client, site):
        """A broken script on a busy page throws thousands of identical errors;
        one row per occurrence would bury everything else."""
        for _ in range(4):
            _post(api_client, site)
        assert JsError.objects.filter(website=site).count() == 1
        assert JsError.objects.get(website=site).hits == 4

    def test_noise_is_accepted_but_not_stored(self, api_client, site):
        """202 either way, so probing the endpoint reveals nothing."""
        resp = _post(api_client, site, message="Script error.")
        assert resp.status_code == 202
        assert JsError.objects.filter(website=site).count() == 0

    def test_unknown_site_id_is_404(self, api_client):
        resp = api_client.post("/api/ingest/js-errors/", {
            "site_id": "nope", "page_url": "https://x.test/",
            "message": "TypeError: boom",
        }, format="json")
        assert resp.status_code == 404

    def test_recurrence_reopens_a_resolved_error(self, api_client, site):
        """An error marked resolved that fires again is not resolved."""
        _post(api_client, site)
        JsError.objects.filter(website=site).update(is_resolved=True)
        _post(api_client, site)
        assert JsError.objects.get(website=site).is_resolved is False

    def test_list_endpoint_is_team_scoped(self, auth_client, site):
        _post_client = auth_client
        JsError.objects.create(
            website=site, fingerprint="abc", message="TypeError: x",
            page_url="https://jssite.test/", hits=3,
        )
        resp = _post_client.get(f"/api/v1/websites/{site.id}/js-errors/")
        assert resp.status_code == 200
        assert len(resp.data) == 1
        assert resp.data[0]["hits"] == 3
