"""Digivault's own snippet/infra must not be tracked as a client third-party
script — otherwise it logs a hidden high-severity change that pins the site to
'critical' with nothing the user can clear."""

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.models import Script, ScriptChange
from apps.scripts.tasks import _should_track_script, process_ingest_payload
from apps.websites.models import Website


class TestNoiseFilter:
    def test_digivault_snippet_not_tracked(self):
        assert _should_track_script("https://digivault.digilatics.co/api/s.js", "client.com") is False
        assert _should_track_script("https://cdn.digivault.digilatics.co/x.js", "client.com") is False
        assert _should_track_script("https://digilaticsvps.digilatics.co/y.js", "client.com") is False

    def test_real_provider_still_tracked(self):
        assert _should_track_script("https://www.googletagmanager.com/gtm.js", "client.com") is True


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="noise_o@test.com", password="Pass123!")
    team = TeamService.create(name="Noise Agency", owner=owner)
    return Website.objects.create(team=team, name="Noise Site", domain="client.com")


@pytest.mark.django_db
def test_existing_internal_change_clears_critical_on_ingest(website):
    """A pre-existing unacknowledged HIGH change for the Digivault snippet gets
    auto-acknowledged on the next ingest, so the site is no longer 'critical'."""
    website.status = Website.Status.CRITICAL
    website.save(update_fields=["status"])

    snippet = Script.objects.create(
        website=website,
        src_url="https://digivault.digilatics.co/api/s.js",
        src_domain="digivault.digilatics.co",
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
