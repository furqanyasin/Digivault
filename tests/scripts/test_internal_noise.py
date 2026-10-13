"""Stacks Monitor's own snippet/infra must not be tracked as a client third-party
script — otherwise it logs a hidden high-severity change that pins the site to
'critical' with nothing the user can clear."""

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.models import Script, ScriptChange
from apps.scripts.tasks import _should_track_script, _update_website_status, process_ingest_payload
from apps.websites.models import Website


class TestNoiseFilter:
    def test_own_snippet_not_tracked(self):
        assert _should_track_script("https://stacksmonitor.com/api/s.js", "client.com") is False
        assert _should_track_script("https://www.stacksmonitor.com/x.js", "client.com") is False

    def test_real_provider_still_tracked(self):
        assert _should_track_script("https://www.googletagmanager.com/gtm.js?id=GTM-ABC1", "client.com") is True


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="noise_o@test.com", password="Pass123!")
    team = TeamService.create(name="Noise Agency", owner=owner)
    return Website.objects.create(team=team, name="Noise Site", domain="client.com")


@pytest.mark.django_db
def test_existing_internal_change_clears_critical_on_ingest(website):
    """A pre-existing unacknowledged HIGH change for the Stacks Monitor snippet gets
    auto-acknowledged on the next ingest, so the site is no longer 'critical'."""
    website.status = Website.Status.CRITICAL
    website.save(update_fields=["status"])

    snippet = Script.objects.create(
        website=website,
        src_url="https://stacksmonitor.com/api/s.js",
        src_domain="stacksmonitor.com",
        provider="unknown",
        is_active=True,
    )
    ScriptChange.objects.create(
        website=website, script=snippet, change_type="added",
        severity=ScriptChange.Severity.HIGH, description="Added tracking snippet",
    )

    process_ingest_payload(
        site_id=website.site_id,
        payload={
            "page_url": "https://client.com/",
            "scripts": [],
            "forms": [],
            "user_agent": "test",
            "snippet_version": "1.5",
        },
    )

    snippet.refresh_from_db()
    website.refresh_from_db()
    change = ScriptChange.objects.get(script=snippet)
    assert change.acknowledged_at is not None  # auto-acknowledged
    assert snippet.is_active is False           # deactivated as noise
    assert website.status != Website.Status.CRITICAL


@pytest.mark.django_db
def test_status_recalc_ignores_internal_change(website):
    """An unacknowledged HIGH change on an internal host must not make a site
    critical when status is recalculated."""
    snippet = Script.objects.create(
        website=website,
        src_url="https://stacksmonitor.com/api/s.js",
        src_domain="stacksmonitor.com",
        provider="unknown",
        is_active=True,
    )
    ScriptChange.objects.create(
        website=website, script=snippet, change_type="added",
        severity=ScriptChange.Severity.HIGH, description="Added tracking snippet",
    )
    _update_website_status(website)
    website.refresh_from_db()
    assert website.status == Website.Status.ACTIVE
