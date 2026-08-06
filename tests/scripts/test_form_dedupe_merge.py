"""Merging DetectedForm rows that the normalized action turned into duplicates.

`merge_duplicate_forms` ships with the 0018 migration. The dangerous part is not
the merge but what it throws away: these rows carry submission counts, and a
merge that dropped them would silently delete real conversions from the Forms
tab.
"""
import datetime

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.dedup import merge_duplicate_forms
from apps.scripts.models import DetectedForm
from apps.websites.models import Website

PAGE = "https://digilatics.com"
FIELDS = [{"name": "email", "type": "email", "label": "Email", "required": True}]


@pytest.fixture
def site(db):
    owner = User.objects.create_user(email="formdedupe@x.io", password="Pass123!")
    team = TeamService.create(name="Form Dedupe Co", owner=owner)
    return Website.objects.create(team=team, name="Digilatics", domain="digilatics.com")


def _form(site, action, *, submissions=0, days_ago=0, submitted_days_ago=None):
    """Create a DetectedForm with the pre-fix raw-action fingerprint."""
    form = DetectedForm.objects.create(
        website=site,
        page_url=PAGE,
        form_id="multiStepForm",
        form_name="",
        form_action=action,
        form_method="post",
        detection_type="native",
        fields=FIELDS,
        # Pre-fix rows hashed the action verbatim, query string and all.
        fingerprint=DetectedForm.compute_fingerprint({
            "detection_type": "native",
            "form_id": "multiStepForm",
            "form_name": "",
            "form_action": action,
            "fields": FIELDS,
        })[:16] + action[-16:].rjust(16, "0"),
        submission_count=submissions,
        last_submission_at=(
            timezone.now() - datetime.timedelta(days=submitted_days_ago)
            if submitted_days_ago is not None
            else None
        ),
    )
    DetectedForm.objects.filter(pk=form.pk).update(
        first_seen_at=timezone.now() - datetime.timedelta(days=days_ago),
        last_seen_at=timezone.now() - datetime.timedelta(days=days_ago),
    )
    return DetectedForm.objects.get(pk=form.pk)


@pytest.mark.django_db
class TestMergeDuplicateForms:
    def test_campaign_url_copies_collapse_into_one_row(self, site):
        _form(site, PAGE + "/", days_ago=9)
        _form(site, PAGE + "/?utm_source=newsletter", days_ago=5)
        _form(site, PAGE + "/?gclid=abc123#form", days_ago=2)

        deleted = merge_duplicate_forms(DetectedForm)

        assert deleted == 2
        assert DetectedForm.objects.filter(website=site).count() == 1

    def test_submissions_are_summed_not_lost(self, site):
        _form(site, PAGE + "/", submissions=4, days_ago=9, submitted_days_ago=6)
        _form(site, PAGE + "/?utm_source=ads", submissions=3, days_ago=5, submitted_days_ago=1)

        merge_duplicate_forms(DetectedForm)

        keeper = DetectedForm.objects.get(website=site)
        assert keeper.submission_count == 7
        # The most recent submit across the copies, not the keeper's own.
        assert (timezone.now() - keeper.last_submission_at).days < 2

    def test_keeper_is_the_earliest_row(self, site):
        oldest = _form(site, PAGE + "/", days_ago=30)
        _form(site, PAGE + "/?utm_source=x", days_ago=1)

        merge_duplicate_forms(DetectedForm)

        assert DetectedForm.objects.get(website=site).pk == oldest.pk

    def test_genuinely_different_forms_are_not_merged(self, site):
        _form(site, PAGE + "/", days_ago=4)
        DetectedForm.objects.create(
            website=site,
            page_url=PAGE,
            form_id="newsletter",
            form_action=PAGE + "/",
            detection_type="native",
            fields=FIELDS,
            fingerprint="a-different-form-entirely",
        )

        merge_duplicate_forms(DetectedForm)

        assert DetectedForm.objects.filter(website=site).count() == 2

    def test_rerunning_the_merge_is_a_no_op(self, site):
        _form(site, PAGE + "/", submissions=2, days_ago=9)
        _form(site, PAGE + "/?utm_source=x", submissions=1, days_ago=5)

        merge_duplicate_forms(DetectedForm)
        deleted_again = merge_duplicate_forms(DetectedForm)

        assert deleted_again == 0
        assert DetectedForm.objects.get(website=site).submission_count == 3
