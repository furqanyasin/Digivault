"""Form submission counting via the /api/ingest/form-submission/ endpoint."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.models import DetectedForm
from apps.scripts.normalize import normalize_page_url
from apps.scripts.tasks import _upsert_form
from apps.websites.models import Website

PAGE = "https://forms.io/contact"
FORM = {
    "form_id": "cf7", "form_name": "contact", "form_action": "/submit",
    "form_method": "POST", "detection_type": "native", "provider": "",
    "fields": [{"name": "email", "type": "email", "label": "Email", "required": True}],
}


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="fs_o@test.com", password="Pass123!")
    team = TeamService.create(name="FS Agency", owner=owner)
    return Website.objects.create(team=team, name="FS Site", domain="forms.io")


@pytest.mark.django_db
class TestFormSubmissionCount:
    def _post(self, site_id, form=FORM, page=PAGE):
        return APIClient().post(
            "/api/ingest/form-submission/",
            {"site_id": site_id, "page_url": page, "form": form},
            format="json",
        )

    def test_submission_increments_detected_form_count(self, website):
        _upsert_form(website, PAGE, FORM)
        assert self._post(website.site_id).status_code == 202
        assert self._post(website.site_id).status_code == 202
        form = DetectedForm.objects.get(website=website, page_url=PAGE)
        assert form.submission_count == 2

    def test_submission_counted_when_href_carries_www_query_and_slash(self, website):
        # Reality check. Ingest stores the *normalized* page identity, while the
        # snippet reports window.location.href verbatim — which in the wild has
        # www., UTM params, a fragment and a trailing slash. Matching those two
        # against each other raw is why counts sat at 0 on live sites.
        stored = normalize_page_url("https://www.forms.io/contact/")
        _upsert_form(website, stored, FORM)

        resp = self._post(
            website.site_id,
            page="https://www.forms.io/contact/?utm_source=newsletter&gclid=abc#form",
        )

        assert resp.data["counted"] is True
        assert DetectedForm.objects.get(website=website, page_url=stored).submission_count == 1

    def test_div_based_form_submission_is_counted(self, website):
        # A form with no <form> element is stored with detection_type "dom", and
        # the fingerprint covers detection_type — so the snippet must report the
        # descriptor it catalogued, not rebuild one as "native". It used to
        # hardcode "native", which could never match a stored dom form.
        dom_form = {
            "form_id": "multiStepForm", "form_name": "", "form_action": "",
            "form_method": "post", "detection_type": "dom", "provider": "",
            "fields": [{"name": "email", "type": "email", "label": "Email", "required": True}],
        }
        _upsert_form(website, PAGE, dom_form)

        resp = self._post(website.site_id, form=dom_form)

        assert resp.data["counted"] is True
        assert DetectedForm.objects.get(website=website, page_url=PAGE).submission_count == 1

    def test_native_descriptor_does_not_count_against_a_dom_form(self, website):
        # The old bug, pinned: same form, described as native, must not match.
        dom_form = {
            "form_id": "multiStepForm", "form_name": "", "form_action": "",
            "form_method": "post", "detection_type": "dom", "provider": "",
            "fields": [{"name": "email", "type": "email", "label": "Email", "required": True}],
        }
        _upsert_form(website, PAGE, dom_form)

        self._post(website.site_id, form={**dom_form, "detection_type": "native"})

        # The submit is still recorded (against its own descriptor), but it must
        # never land on the dom row — that mis-attribution was the original bug.
        dom_row = DetectedForm.objects.get(
            website=website, page_url=PAGE, detection_type="dom"
        )
        assert dom_row.submission_count == 0

    def test_submission_for_a_not_yet_catalogued_form_is_recorded(self, website):
        # A form can first appear *after* the last collectForms() of the page —
        # an Elementor popup opened past the snippet's 30s observer window, say.
        # Dropping that submit lost the real conversion and left the form
        # invisible. The descriptor arrives through the same serializer ingest
        # uses, so record it exactly as ingest would have.
        resp = self._post(website.site_id)

        assert resp.status_code == 202
        assert resp.data["counted"] is True
        form = DetectedForm.objects.get(website=website, page_url=PAGE)
        assert form.submission_count == 1
        assert form.form_name == "contact"
        assert form.last_submission_at is not None

    def test_late_form_is_not_duplicated_by_a_later_ingest(self, website):
        # The row created from a submit must be the same row ingest then updates,
        # or the form would appear twice with the count on the wrong copy.
        self._post(website.site_id)
        _upsert_form(website, PAGE, FORM)

        form = DetectedForm.objects.get(website=website, page_url=PAGE)
        assert form.submission_count == 1

    def test_submission_from_a_campaign_url_counts_on_the_canonical_row(self, website):
        # `form.action` resolves to the document URL for an action-less form, so
        # a visitor arriving on a UTM link reports a different action than the
        # one already stored. That used to mint a duplicate row per campaign and
        # scatter the counts; identity must ignore the query string.
        action_less = {**FORM, "form_action": "https://forms.io/contact"}
        _upsert_form(website, PAGE, action_less)

        resp = self._post(
            website.site_id,
            form={**action_less, "form_action": "https://forms.io/contact?utm_source=ads"},
            page="https://forms.io/contact?utm_source=ads",
        )

        assert resp.data["counted"] is True
        assert DetectedForm.objects.filter(website=website).count() == 1
        assert DetectedForm.objects.get(website=website).submission_count == 1

    def test_unknown_site_returns_404(self):
        assert self._post("does-not-exist").status_code == 404
