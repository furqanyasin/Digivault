import datetime

import pytest
from django.utils import timezone

from apps.domains.models import DomainInfo
from apps.scripts.models import Script, ScriptChange
from apps.websites.models import Website


@pytest.mark.django_db
def test_health_ignores_internal_snippet_changes(team):
    w = Website.objects.create(team=team, name="S", domain="health.example")
    # An internal (Digivault snippet) script + a high-severity change for it.
    s = Script.objects.create(
        website=w, src_url="https://digivault.digilatics.co/api/s.js",
        src_domain="digivault.digilatics.co", provider="unknown", is_active=True,
    )
    ScriptChange.objects.create(
        website=w, script=s, change_type="added", severity="critical",
        description="New script added: digivault.digilatics.co/api/s.js",
    )

    w.recalculate_health_score()
    w.refresh_from_db()
    # Internal-only change must not drag health down.
    assert w.health_score == 100


@pytest.mark.django_db
def test_expiring_hosting_endpoint(auth_client, team):
    w = Website.objects.create(team=team, name="S", domain="host.example")
    DomainInfo.objects.create(
        website=w, hosting_expires_at=timezone.now() + datetime.timedelta(days=13)
    )
    resp = auth_client.get("/api/v1/websites/expiring-hosting/?days=30")
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.data]
    assert str(w.id) in ids

    # Outside the window → excluded.
    resp2 = auth_client.get("/api/v1/websites/expiring-hosting/?days=7")
    assert str(w.id) not in [r["id"] for r in resp2.data]
