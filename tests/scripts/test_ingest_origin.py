"""Domain-binding on the four public ingest endpoints.

`Website.domain` is a free-text field: users type `example.com`,
`https://example.com` or `https://www.example.com/` and all three mean the same
site. The check that compares it to the browser's Origin was inlined in four
views, each stripping `www.` *before* the scheme — which never matched on a
stored `https://www.example.com`, left the host as `www.example.com`, and
answered 403 to every payload the site sent. Scripts, forms, submissions and
errors all went silently missing for such a site.
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.models import DetectedForm, FormSubmissionError, JsError
from apps.websites.models import Website

PAGE = "https://origins.io/contact"
FORM = {
    "form_id": "cf7", "form_name": "contact", "form_action": PAGE,
    "form_method": "post", "detection_type": "native", "provider": "",
    "fields": [{"name": "email", "type": "email", "label": "Email", "required": True}],
}

# Every shape a user has actually saved for one and the same site.
SAME_SITE_DOMAINS = [
    "origins.io",
    "www.origins.io",
    "https://origins.io",
    "https://www.origins.io",
    "https://www.origins.io/",
    "http://origins.io",
]


def _site(domain, email):
    owner = User.objects.create_user(email=email, password="Pass123!")
    team = TeamService.create(name=f"Origin {email}", owner=owner)
    return Website.objects.create(team=team, name="Origins", domain=domain)


@pytest.mark.django_db
class TestOriginAcceptedForEveryStoredDomainShape:
    @pytest.mark.parametrize("domain", SAME_SITE_DOMAINS)
    @pytest.mark.parametrize("origin", ["https://origins.io", "https://www.origins.io"])
    def test_script_ingest_is_accepted(self, domain, origin):
        site = _site(domain, f"ing_{abs(hash(domain + origin))}@t.io")

        resp = APIClient().post(
            "/api/ingest/",
            {"site_id": site.site_id, "page_url": PAGE, "scripts": [], "forms": []},
            format="json",
            HTTP_ORIGIN=origin,
        )

        assert resp.status_code != 403

    @pytest.mark.parametrize("domain", SAME_SITE_DOMAINS)
    def test_form_submission_is_counted(self, domain):
        site = _site(domain, f"sub_{abs(hash(domain))}@t.io")

        resp = APIClient().post(
            "/api/ingest/form-submission/",
            {"site_id": site.site_id, "page_url": PAGE, "form": FORM},
            format="json",
            HTTP_ORIGIN="https://www.origins.io",
        )

        assert resp.status_code == 202
        assert DetectedForm.objects.filter(website=site).count() == 1

    @pytest.mark.parametrize("domain", SAME_SITE_DOMAINS)
    def test_form_error_is_stored(self, domain):
        site = _site(domain, f"err_{abs(hash(domain))}@t.io")

        resp = APIClient().post(
            "/api/ingest/form-errors/",
            {
                "site_id": site.site_id, "page_url": PAGE, "source": "Elementor Forms",
                "form_id": "contact", "message": "Your submission failed because of a server error.",
            },
            format="json",
            HTTP_ORIGIN="https://www.origins.io",
        )

        assert resp.status_code == 202
        assert FormSubmissionError.objects.filter(website=site).count() == 1

    @pytest.mark.parametrize("domain", SAME_SITE_DOMAINS)
    def test_js_error_is_stored(self, domain):
        site = _site(domain, f"js_{abs(hash(domain))}@t.io")

        resp = APIClient().post(
            "/api/ingest/js-errors/",
            {"site_id": site.site_id, "page_url": PAGE, "message": "x is not defined"},
            format="json",
            HTTP_ORIGIN="https://www.origins.io",
        )

        assert resp.status_code == 202
        assert JsError.objects.filter(website=site).count() == 1

    def test_a_port_on_the_origin_is_not_part_of_identity(self):
        site = _site("origins.io", "port@t.io")

        resp = APIClient().post(
            "/api/ingest/",
            {"site_id": site.site_id, "page_url": PAGE, "scripts": [], "forms": []},
            format="json",
            HTTP_ORIGIN="https://origins.io:443",
        )

        assert resp.status_code != 403


@pytest.mark.django_db
class TestOriginStillRejectsAnotherSite:
    """The check must stay a check — loosening the parsing must not loosen this."""

    @pytest.mark.parametrize("origin", [
        "https://evil.example",
        "https://origins.io.evil.example",
        "https://notorigins.io",
    ])
    def test_script_ingest_from_elsewhere_is_403(self, origin):
        site = _site("https://www.origins.io", f"evil_{abs(hash(origin))}@t.io")

        resp = APIClient().post(
            "/api/ingest/",
            {"site_id": site.site_id, "page_url": PAGE, "scripts": [], "forms": []},
            format="json",
            HTTP_ORIGIN=origin,
        )

        assert resp.status_code == 403

    def test_form_submission_from_elsewhere_is_403(self):
        site = _site("https://www.origins.io", "evilsub@t.io")

        resp = APIClient().post(
            "/api/ingest/form-submission/",
            {"site_id": site.site_id, "page_url": PAGE, "form": FORM},
            format="json",
            HTTP_ORIGIN="https://evil.example",
        )

        assert resp.status_code == 403
        assert DetectedForm.objects.filter(website=site).count() == 0

    def test_no_origin_header_is_allowed_through(self):
        # Not every client sends one, and the check exists to reject a payload
        # attributed to the wrong site, not to require the header.
        site = _site("https://www.origins.io", "noorigin@t.io")

        resp = APIClient().post(
            "/api/ingest/",
            {"site_id": site.site_id, "page_url": PAGE, "scripts": [], "forms": []},
            format="json",
        )

        assert resp.status_code != 403
