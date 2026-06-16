import pytest

from apps.scripts.models import Script, ScriptChange
from apps.websites.models import Website


@pytest.mark.django_db
def test_bulk_acknowledge_clears_critical_status(auth_client, team):
    w = Website.objects.create(team=team, name="S", domain="biz.example")
    s = Script.objects.create(
        website=w, src_url="https://evil.com/a.js", src_domain="evil.com",
        provider="unknown", is_active=True,
    )
    ScriptChange.objects.create(
        website=w, script=s, change_type="added", severity="high", description="High-risk add",
    )
    # The high-severity open change pins the site to 'critical'.
    Website.objects.filter(pk=w.pk).update(status=Website.Status.CRITICAL)

    ids = [str(c.pk) for c in ScriptChange.objects.filter(website=w)]
    resp = auth_client.post(
        "/api/v1/changes/bulk-acknowledge/", {"change_ids": ids}, format="json"
    )
    assert resp.status_code == 200
    assert resp.data["updated"] == len(ids)

    w.refresh_from_db()
    # No open changes left → status recalculated to active (was stuck critical).
    assert w.status == Website.Status.ACTIVE


@pytest.mark.django_db
def test_bulk_acknowledge_requires_ids(auth_client):
    resp = auth_client.post("/api/v1/changes/bulk-acknowledge/", {"change_ids": []}, format="json")
    assert resp.status_code == 400
