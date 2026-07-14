"""Form submission counting via the /api/ingest/form-submission/ endpoint."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.models import DetectedForm
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

    def test_submission_for_undetected_form_is_ignored(self, website):
        # No _upsert_form first → nothing to increment, but still a clean 202.
        resp = self._post(website.site_id)
        assert resp.status_code == 202
        assert resp.data["counted"] is False

    def test_unknown_site_returns_404(self):
        assert self._post("does-not-exist").status_code == 404
