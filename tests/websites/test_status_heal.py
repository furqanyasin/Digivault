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
def test_website_list_does_not_recalculate(auth_client, team):
    """The list endpoint reports stored values; it must not recompute them.

    It used to heal every listed site per request, which cost ~8 queries and a
    write per site and made this the slowest call the dashboard makes (1.03s for
    13 sites, growing linearly). Health now has real triggers — ingest,
    acknowledge/review, monitor flip, domain check, security scan — plus a
    nightly sweep, so the per-request heal was redundant work on the hot path.
    """
    w = Website.objects.create(team=team, name="S", domain="heal-list.example")
    Website.objects.filter(pk=w.pk).update(status=Website.Status.CRITICAL, health_score=55)

    resp = auth_client.get("/api/v1/websites/")
    assert resp.status_code == 200
    rows = resp.data if isinstance(resp.data, list) else resp.data.get("results", resp.data)
    row = next(r for r in rows if r["id"] == str(w.id))
    assert row["status"] == "critical"
    assert row["health_score"] == 55


@pytest.mark.django_db
def test_website_list_query_count_is_flat_in_site_count(auth_client, team, django_assert_max_num_queries):
    """Guards the regression: listing must not issue work per site.

    With the old per-request heal this grew ~8 queries + 1 write per website, so
    a team with 60 sites paid for ~500 queries to render a dashboard.
    """
    for n in range(12):
        Website.objects.create(team=team, name=f"S{n}", domain=f"s{n}.example")

    # Comfortably above the fixed cost (auth, team, count, page, annotations)
    # but far below anything that scales with 12 sites.
    with django_assert_max_num_queries(20):
        assert auth_client.get("/api/v1/websites/?page_size=100").status_code == 200
