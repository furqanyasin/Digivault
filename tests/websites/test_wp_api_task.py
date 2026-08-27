"""The daily sweep that reads recipients from sites' own WordPress APIs."""

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.models import DetectedForm
from apps.websites.models import Website
from apps.websites.tasks import sync_wp_api_form_recipients


@pytest.fixture
def team(db):
    owner = User.objects.create_user(email="wpat_o@test.com", password="Pass123!")
    return TeamService.create(name="Sweep Agency", owner=owner)


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="Sweep Site", domain="sweep.test")


def _with_form(website):
    return DetectedForm.objects.create(
        website=website, page_url="https://sweep.test/c", fingerprint="f1"
    )


def test_skips_sites_with_no_detected_forms(website, monkeypatch):
    """Nothing to join an answer onto, so do not spend a request finding out."""
    calls = []
    monkeypatch.setattr(
        "apps.websites.wp_api_forms.sync_website",
        lambda site: calls.append(site) or 0,
    )

    assert sync_wp_api_form_recipients() == 0
    assert calls == []


def test_visits_a_site_that_has_forms(website, monkeypatch):
    _with_form(website)
    monkeypatch.setattr("apps.websites.wp_api_forms.sync_website", lambda site: 3)

    assert sync_wp_api_form_recipients() == 3


def test_skips_a_site_whose_credential_was_rejected(website, monkeypatch):
    _with_form(website)
    website.wp_api_auth_failed_at = timezone.now()
    website.save(update_fields=["wp_api_auth_failed_at"])

    calls = []
    monkeypatch.setattr(
        "apps.websites.wp_api_forms.sync_website",
        lambda site: calls.append(site) or 0,
    )

    assert sync_wp_api_form_recipients() == 0
    assert calls == []


def test_skips_an_inactive_site(website, monkeypatch):
    _with_form(website)
    website.status = Website.Status.INACTIVE
    website.save(update_fields=["status"])

    calls = []
    monkeypatch.setattr(
        "apps.websites.wp_api_forms.sync_website",
        lambda site: calls.append(site) or 0,
    )

    assert sync_wp_api_form_recipients() == 0
    assert calls == []


def test_one_failing_site_does_not_stop_the_sweep(website, monkeypatch):
    _with_form(website)

    def _boom(site):
        raise RuntimeError("nope")

    monkeypatch.setattr("apps.websites.wp_api_forms.sync_website", _boom)

    assert sync_wp_api_form_recipients() == 0


def test_a_single_website_can_be_targeted(team, website, monkeypatch):
    _with_form(website)
    other = Website.objects.create(team=team, name="Other", domain="other.test")
    DetectedForm.objects.create(
        website=other, page_url="https://other.test/c", fingerprint="f2"
    )

    seen = []
    monkeypatch.setattr(
        "apps.websites.wp_api_forms.sync_website",
        lambda site: seen.append(site.domain) or 1,
    )

    assert sync_wp_api_form_recipients(website_pk=str(website.pk)) == 1
    assert seen == ["sweep.test"]
