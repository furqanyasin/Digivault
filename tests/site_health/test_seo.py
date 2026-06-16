import pytest

from apps.site_health.models import SeoReport
from apps.websites.models import Website


@pytest.mark.django_db
def test_website_seo_interval_defaults_to_off(team):
    w = Website.objects.create(team=team, name="S", domain="seo-test.example")
    assert w.seo_scan_interval_days == 0


@pytest.mark.django_db
def test_seo_report_defaults(team):
    w = Website.objects.create(team=team, name="S2", domain="seo2.example")
    r = SeoReport.objects.create(website=w)
    assert r.check_status == "never"
    assert r.robots_status == "unknown"
    assert r.sitemap_status == "unknown"
    assert r.homepage_indexable is None
    assert r.pages_checked == []
    assert r.noindex_count == 0


@pytest.mark.django_db
def test_seo_endpoint_get_creates_report(auth_client, team):
    w = Website.objects.create(team=team, name="S", domain="seo3.example")
    resp = auth_client.get(f"/api/v1/websites/{w.id}/seo/")
    assert resp.status_code == 200
    assert resp.data["check_status"] == "never"


@pytest.mark.django_db
def test_seo_endpoint_patch_sets_interval(auth_client, team):
    w = Website.objects.create(team=team, name="S", domain="seo4.example")
    resp = auth_client.patch(
        f"/api/v1/websites/{w.id}/seo/", {"seo_scan_interval_days": 7}, format="json"
    )
    assert resp.status_code == 200
    w.refresh_from_db()
    assert w.seo_scan_interval_days == 7


@pytest.mark.django_db
def test_seo_endpoint_patch_rejects_bad_interval(auth_client, team):
    w = Website.objects.create(team=team, name="S", domain="seo5.example")
    resp = auth_client.patch(
        f"/api/v1/websites/{w.id}/seo/", {"seo_scan_interval_days": 99}, format="json"
    )
    assert resp.status_code == 400
