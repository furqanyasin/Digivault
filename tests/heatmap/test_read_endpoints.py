import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.heatmap.models import HeatmapActivity, HeatmapPageStats
from apps.websites.models import Website


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="VM Site", domain="viewmap.io")


@pytest.fixture
def other_website(db):
    owner2 = User.objects.create_user(email="other_o@test.com", password="Pass123!")
    team2 = TeamService.create(name="Other Agency", owner=owner2)
    return Website.objects.create(team=team2, name="Other Site", domain="other.io")


def _seed(website, **overrides):
    page, _ = HeatmapPageStats.objects.get_or_create(
        website=website,
        page_url="https://viewmap.io/page",
        device="desktop",
        defaults={
            "visits": 5,
            "total_clicks": 42,
            "max_scroll_percent": 90,
            "scroll_histogram": {"50": 0.8},
        },
    )
    HeatmapActivity.objects.get_or_create(
        website=website,
        page_url="https://viewmap.io/page",
        kind="click",
        device="desktop",
        x=50,
        y=30,
        defaults={"count": 7},
    )
    return page


@pytest.mark.django_db
class TestHeatmapReadEndpoints:
    def test_pages_require_auth(self, api_client, website):
        _seed(website)
        resp = api_client.get("/api/v1/heatmap/pages/")
        assert resp.status_code in (401, 403)

    def test_pages_scoped_to_team(self, auth_client, website, other_website):
        _seed(website)
        _seed(other_website)
        resp = auth_client.get(f"/api/v1/heatmap/pages/?website={website.id}")
        assert resp.status_code == 200
        urls = [r["page_url"] for r in resp.data]
        assert urls == ["https://viewmap.io/page"]
        assert other_website.domain not in str(resp.data)

    def test_pages_filters_by_device(self, auth_client, website):
        _seed(website)
        HeatmapPageStats.objects.get_or_create(
            website=website,
            page_url="https://viewmap.io/page",
            device="mobile",
            defaults={"visits": 2, "total_clicks": 3},
        )
        resp = auth_client.get(
            f"/api/v1/heatmap/pages/?website={website.id}&device=mobile"
        )
        assert resp.status_code == 200
        assert all(r["device"] == "mobile" for r in resp.data)

    def test_activity_requires_auth(self, api_client, website):
        _seed(website)
        resp = api_client.get("/api/v1/heatmap/activity/")
        assert resp.status_code in (401, 403)

    def test_activity_filters_kind_and_device(self, auth_client, website):
        _seed(website)
        HeatmapActivity.objects.get_or_create(
            website=website,
            page_url="https://viewmap.io/page",
            kind="move",
            device="desktop",
            x=10,
            y=10,
            defaults={"count": 3},
        )
        resp = auth_client.get(
            f"/api/v1/heatmap/activity/?website={website.id}"
            f"&page_url=https%3A%2F%2Fviewmap.io%2Fpage&kind=click&device=desktop"
        )
        assert resp.status_code == 200
        data = resp.data
        assert len(data) == 1
        assert data[0]["kind"] == "click"
        assert data[0]["x"] == 50
        assert data[0]["count"] == 7

    def test_activity_returns_element(self, auth_client, website):
        HeatmapActivity.objects.get_or_create(
            website=website,
            page_url="https://viewmap.io/page",
            kind="click",
            device="desktop",
            x=50,
            y=30,
            defaults={"count": 7, "element": 'a[href="/pricing"] "Pricing"'},
        )
        resp = auth_client.get(
            f"/api/v1/heatmap/activity/?website={website.id}&kind=click&device=desktop"
        )
        assert resp.status_code == 200
        assert resp.data[0]["element"] == 'a[href="/pricing"] "Pricing"'

    def test_activity_filters_rage_kind(self, auth_client, website):
        _seed(website)
        HeatmapActivity.objects.get_or_create(
            website=website,
            page_url="https://viewmap.io/page",
            kind="rage",
            device="desktop",
            x=40,
            y=25,
            defaults={"count": 4},
        )
        resp = auth_client.get(
            f"/api/v1/heatmap/activity/?website={website.id}"
            f"&page_url=https%3A%2F%2Fviewmap.io%2Fpage&kind=rage&device=desktop"
        )
        assert resp.status_code == 200
        # kind=rage must return only the rage row (the seeded click is excluded).
        data = resp.data
        assert len(data) == 1
        assert data[0]["kind"] == "rage"
        assert data[0]["count"] == 4

    def test_activity_scoped_to_team(self, auth_client, website, other_website):
        _seed(website)
        _seed(other_website)
        # other_website belongs to a different team — asking for its activity
        # must return nothing, not leak the other team's cells.
        resp = auth_client.get(f"/api/v1/heatmap/activity/?website={other_website.id}")
        assert resp.status_code == 200
        assert resp.data == []

    def test_summary(self, auth_client, website):
        _seed(website)
        HeatmapPageStats.objects.get_or_create(
            website=website,
            page_url="https://viewmap.io/other",
            device="desktop",
            defaults={"visits": 3, "total_clicks": 10, "max_scroll_percent": 60},
        )
        resp = auth_client.get(f"/api/v1/heatmap/summary/?website={website.id}")
        assert resp.status_code == 200
        desktop = resp.data["desktop"]
        assert desktop["visits"] == 8
        assert desktop["total_clicks"] == 52
        assert desktop["max_scroll_percent"] == 90

    def test_summary_scoped_to_team(self, auth_client, website, other_website):
        _seed(website)
        _seed(other_website)
        # other_website is in a different team — requesting its summary must
        # not leak the other team's stats.
        resp = auth_client.get(f"/api/v1/heatmap/summary/?website={other_website.id}")
        assert resp.status_code == 200
        assert resp.data == {}
