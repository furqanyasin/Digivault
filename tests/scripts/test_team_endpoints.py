"""Team-wide list endpoints that replaced the per-website request fan-out."""

import pytest

from apps.scripts.models import ScriptChange


@pytest.mark.django_db
def test_team_changes_returns_all_sites_with_attribution(auth_client, team):
    from apps.scripts.models import Script
    from apps.websites.models import Website

    a = Website.objects.create(team=team, name="Site A", domain="a.io")
    b = Website.objects.create(team=team, name="Site B", domain="b.io")
    for site in (a, b):
        script = Script.objects.create(website=site, src_url=f"https://{site.domain}/x.js")
        ScriptChange.objects.create(
            website=site, script=script, change_type="added",
            severity="high", description=f"new on {site.domain}",
        )

    resp = auth_client.get("/api/v1/changes/")
    assert resp.status_code == 200, resp.data
    rows = resp.data
    assert len(rows) == 2
    # Each row must say which site it belongs to — that's what the per-site
    # fan-out used to provide by construction.
    assert {r["website_name"] for r in rows} == {"Site A", "Site B"}


@pytest.mark.django_db
def test_team_changes_excludes_other_teams(auth_client, team):
    from apps.accounts.models import Team, User
    from apps.scripts.models import Script
    from apps.websites.models import Website

    outsider = User.objects.create_user(email="out@example.com", password="pw12345!")
    other = Team.objects.create(name="Other", slug="other-t", owner=outsider)
    foreign = Website.objects.create(team=other, name="Foreign", domain="foreign.io")
    script = Script.objects.create(website=foreign, src_url="https://foreign.io/x.js")
    ScriptChange.objects.create(
        website=foreign, script=script, change_type="added",
        severity="high", description="not yours",
    )

    resp = auth_client.get("/api/v1/changes/")
    assert resp.status_code == 200
    assert resp.data == []


@pytest.mark.django_db
def test_team_changes_unacknowledged_filter(auth_client, team):
    from django.utils import timezone

    from apps.scripts.models import Script
    from apps.websites.models import Website

    site = Website.objects.create(team=team, name="S", domain="s.io")
    script = Script.objects.create(website=site, src_url="https://s.io/x.js")
    ScriptChange.objects.create(
        website=site, script=script, change_type="added",
        severity="high", description="open",
    )
    ScriptChange.objects.create(
        website=site, script=script, change_type="added", severity="low",
        description="done", acknowledged_at=timezone.now(),
    )

    resp = auth_client.get("/api/v1/changes/?unacknowledged=true")
    assert resp.status_code == 200
    assert [r["description"] for r in resp.data] == ["open"]


@pytest.mark.django_db
def test_team_forms_and_form_errors_are_team_scoped(auth_client, team):
    from apps.scripts.models import DetectedForm, FormSubmissionError
    from apps.websites.models import Website

    site = Website.objects.create(team=team, name="S", domain="s.io")
    DetectedForm.objects.create(
        website=site, page_url="https://s.io/", fingerprint="abc", form_id="contact",
    )
    FormSubmissionError.objects.create(
        website=site, page_url="https://s.io/", message="SMTP failed", form_id="contact",
    )

    forms = auth_client.get("/api/v1/forms/")
    errors = auth_client.get("/api/v1/form-errors/")
    assert forms.status_code == 200 and len(forms.data) == 1
    assert errors.status_code == 200 and len(errors.data) == 1
