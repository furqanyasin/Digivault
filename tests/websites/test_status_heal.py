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
