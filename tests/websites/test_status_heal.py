import pytest

from apps.websites.models import Website


@pytest.mark.django_db
def test_website_detail_heals_stale_critical(auth_client, team):
    w = Website.objects.create(team=team, name="S", domain="heal.example")
    # No open changes, but status left stuck at 'critical'.
    Website.objects.filter(pk=w.pk).update(status=Website.Status.CRITICAL)

    resp = auth_client.get(f"/api/v1/websites/{w.id}/")
    assert resp.status_code == 200
    assert resp.data["status"] == "active"  # recalculated on view


@pytest.mark.django_db
def test_website_list_heals_stale_health_and_status(auth_client, team):
    w = Website.objects.create(team=team, name="S", domain="heal-list.example")
    Website.objects.filter(pk=w.pk).update(status=Website.Status.CRITICAL, health_score=55)

    resp = auth_client.get("/api/v1/websites/")
    assert resp.status_code == 200
    rows = resp.data if isinstance(resp.data, list) else resp.data.get("results", resp.data)
    row = next(r for r in rows if r["id"] == str(w.id))
    assert row["status"] == "active"      # no open changes → healed
    assert row["health_score"] == 100
