"""One form is one row, whichever source observed it.

The browser's `form.action` getter resolves an absent or relative action
attribute against the document URL; the server-side scan reads the raw
attribute. The action is part of a form's fingerprint, so the two sources used
to store two rows for one form on one page — the Forms tab listed it twice and
rendered whichever sorted first, which is how a seven-field Elementor contact
form came to display "Action: None" and "Fields (0)".
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.dedup import merge_duplicate_forms
from apps.scripts.models import DetectedForm
from apps.scripts.tasks import _upsert_form
from apps.websites.models import Website

PAGE = "https://actionid.io/contact-us"
FIELDS = [
    {"name": "form_fields[name]", "type": "text", "label": "Name", "required": True},
    {"name": "form_fields[email]", "type": "email", "label": "Email", "required": True},
]

# The same Elementor form as each collector describes it. The markup carries no
# action attribute at all; only the browser turns that into a URL.
BROWSER_DESC = {
    "form_id": "", "form_name": "Contact Form", "form_action": PAGE,
    "form_method": "post", "detection_type": "native", "provider": "",
    "fields": FIELDS,
}
SCAN_DESC = {
    "form_id": "", "form_name": "Contact Form", "form_action": "",
    "form_method": "post", "detection_type": "native", "provider": "",
    # The scan's regex extractor skips inputs with no `name`, and sees nothing
    # at all of a form rendered by JavaScript.
    "fields": [],
}


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="actionid@test.com", password="Pass123!")
    team = TeamService.create(name="ActionId Agency", owner=owner)
    return Website.objects.create(team=team, name="ActionId", domain="actionid.io")


@pytest.mark.django_db
class TestScanAndBrowserAgreeOnIdentity:
    def test_action_less_form_is_one_row_across_both_sources(self, website):
        _upsert_form(website, PAGE, BROWSER_DESC)
        _upsert_form(website, PAGE, SCAN_DESC)

        assert DetectedForm.objects.filter(website=website).count() == 1

    def test_scan_first_then_browser_is_also_one_row(self, website):
        # Order matters: the daily passive scan usually runs before the first
        # pageview of the day, so the scan's row is the one already on disk.
        _upsert_form(website, PAGE, SCAN_DESC)
        _upsert_form(website, PAGE, BROWSER_DESC)

        assert DetectedForm.objects.filter(website=website).count() == 1

    def test_relative_action_matches_the_browsers_absolute_one(self, website):
        # `<form action="/submit">` — the scan reads "/submit", the browser
        # reports the absolute URL. Same form.
        _upsert_form(website, PAGE, {**SCAN_DESC, "form_action": "/submit"})
        _upsert_form(
            website, PAGE,
            {**BROWSER_DESC, "form_action": "https://actionid.io/submit"},
        )

        assert DetectedForm.objects.filter(website=website).count() == 1

    def test_a_genuinely_different_action_is_still_a_different_form(self, website):
        _upsert_form(website, PAGE, BROWSER_DESC)
        _upsert_form(
            website, PAGE,
            {**BROWSER_DESC, "form_action": "https://formspree.io/f/abc"},
        )

        assert DetectedForm.objects.filter(website=website).count() == 2

    def test_mailto_action_is_not_resolved_into_the_page(self, website):
        # A mailto: action is the one case where the attribute really is what
        # the form does — and it is how such a form declares its recipient.
        _upsert_form(
            website, PAGE, {**BROWSER_DESC, "form_action": "mailto:sales@actionid.io"}
        )

        form = DetectedForm.objects.get(website=website)
        assert form.form_action == "mailto:sales@actionid.io"

    def test_a_submit_lands_on_the_row_the_scan_created(self, website):
        # The end-to-end consequence. The scan writes the row first; the
        # snippet, which describes the same form with a resolved action, must
        # increment it rather than mint a second.
        _upsert_form(website, PAGE, SCAN_DESC)

        resp = APIClient().post(
            "/api/ingest/form-submission/",
            {"site_id": website.site_id, "page_url": PAGE, "form": BROWSER_DESC},
            format="json",
        )

        assert resp.data["counted"] is True
        assert DetectedForm.objects.filter(website=website).count() == 1
        assert DetectedForm.objects.get(website=website).submission_count == 1


@pytest.mark.django_db
class TestAnEmptyObservationDoesNotErase:
    def test_a_scan_does_not_wipe_the_fields_the_browser_reported(self, website):
        # Now that both sources land on one row, the daily scan writes over it.
        # An observation that read nothing is not a form that has nothing — the
        # same rule `_apply_page_recipients` applies to recipients.
        _upsert_form(website, PAGE, BROWSER_DESC)
        _upsert_form(website, PAGE, SCAN_DESC)

        form = DetectedForm.objects.get(website=website)
        assert [f["name"] for f in form.fields] == [f["name"] for f in FIELDS]

    def test_a_new_row_with_no_readable_fields_still_stores_empty(self, website):
        # The guard must not invent fields for a form nobody has read yet.
        _upsert_form(website, PAGE, SCAN_DESC)

        assert DetectedForm.objects.get(website=website).fields == []

    def test_a_later_reading_with_fields_fills_an_empty_row_in(self, website):
        _upsert_form(website, PAGE, SCAN_DESC)
        _upsert_form(website, PAGE, BROWSER_DESC)

        assert len(DetectedForm.objects.get(website=website).fields) == 2


@pytest.mark.django_db
class TestMergingTheRowsAlreadyStored:
    def _legacy_pair(self, website):
        """The two rows a live site is carrying, with their pre-fix fingerprints."""
        scan = DetectedForm.objects.create(
            website=website, page_url=PAGE, form_name="Contact Form",
            form_action="", detection_type="native", fields=[],
            fingerprint="legacy-scan-fingerprint", submission_count=0,
        )
        browser = DetectedForm.objects.create(
            website=website, page_url=PAGE, form_name="Contact Form",
            form_action=PAGE, detection_type="native", fields=FIELDS,
            fingerprint="legacy-browser-fingerprint", submission_count=4,
        )
        return scan, browser

    def test_the_pair_collapses_to_one_row(self, website):
        self._legacy_pair(website)

        deleted = merge_duplicate_forms(DetectedForm)

        assert deleted == 1
        assert DetectedForm.objects.filter(website=website).count() == 1

    def test_submissions_survive_the_merge(self, website):
        self._legacy_pair(website)

        merge_duplicate_forms(DetectedForm)

        assert DetectedForm.objects.get(website=website).submission_count == 4

    def test_the_survivor_keeps_the_fields_that_were_actually_read(self, website):
        # The keeper is the earliest row, which here is the scan's empty one.
        # Merging onto its descriptor would throw the real reading away.
        self._legacy_pair(website)

        merge_duplicate_forms(DetectedForm)

        form = DetectedForm.objects.get(website=website)
        assert [f["name"] for f in form.fields] == [f["name"] for f in FIELDS]

    def test_rerunning_the_merge_changes_nothing(self, website):
        self._legacy_pair(website)

        merge_duplicate_forms(DetectedForm)

        assert merge_duplicate_forms(DetectedForm) == 0
        assert DetectedForm.objects.get(website=website).submission_count == 4
