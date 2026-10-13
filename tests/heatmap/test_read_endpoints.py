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
        page_url="https://viewmap.io/page/",
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
        page_url="https://viewmap.io/page/",
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
        assert urls == ["https://viewmap.io/page/"]
        assert other_website.domain not in str(resp.data)

    def test_pages_filters_by_device(self, auth_client, website):
        _seed(website)
        HeatmapPageStats.objects.get_or_create(
            website=website,
            page_url="https://viewmap.io/page/",
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
            page_url="https://viewmap.io/page/",
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
            page_url="https://viewmap.io/page/",
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
            page_url="https://viewmap.io/page/",
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
            page_url="https://viewmap.io/other/",
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


@pytest.mark.django_db
class TestSegmentAggregation:
    """One page must read as one page, whatever segments it was collected in.

    `HeatmapPageStats` and `HeatmapActivity` are both stored per segment — one
    row per (page, device, visitor type, source). Served raw, the same URL
    appeared in the page selector once per segment and the dashboard filled its
    summary tiles from whichever row it happened to match first: a page with a
    hundred visits reported "1 observation, 0 clicks" because the row it found
    was the single visitor who arrived from email.
    """

    def _seed_segments(self, website):
        for visitor, source, visits, clicks, scroll in (
            ("new", "direct", 40, 120, 90),
            ("new", "organic", 35, 90, 70),
            ("returning", "email", 1, 0, 40),
        ):
            HeatmapPageStats.objects.create(
                website=website,
                page_url="https://viewmap.io/seg/",
                device="desktop",
                visitor_type=visitor,
                source=source,
                visits=visits,
                total_clicks=clicks,
                max_scroll_percent=scroll,
                scroll_histogram={"50": 1.0},
            )

    def test_page_appears_once_with_summed_totals(self, auth_client, website):
        self._seed_segments(website)
        resp = auth_client.get(
            f"/api/v1/heatmap/pages/?website={website.id}&device=desktop"
        )
        assert resp.status_code == 200
        rows = [r for r in resp.data if r["page_url"] == "https://viewmap.io/seg/"]
        assert len(rows) == 1
        assert rows[0]["visits"] == 76
        assert rows[0]["total_clicks"] == 210
        assert rows[0]["max_scroll_percent"] == 90

    def test_segment_filter_still_narrows(self, auth_client, website):
        self._seed_segments(website)
        resp = auth_client.get(
            f"/api/v1/heatmap/pages/?website={website.id}"
            "&device=desktop&source=email"
        )
        assert resp.status_code == 200
        rows = [r for r in resp.data if r["page_url"] == "https://viewmap.io/seg/"]
        assert len(rows) == 1
        assert rows[0]["visits"] == 1

    def test_scroll_histogram_is_visit_weighted_not_summed(self, auth_client, website):
        """A share cannot be added up — three 100% segments are still 100%."""
        self._seed_segments(website)
        resp = auth_client.get(
            f"/api/v1/heatmap/pages/?website={website.id}&device=desktop"
        )
        rows = [r for r in resp.data if r["page_url"] == "https://viewmap.io/seg/"]
        assert rows[0]["scroll_histogram"]["50"] == 1.0

    def test_pages_are_ordered_by_visits(self, auth_client, website):
        self._seed_segments(website)
        HeatmapPageStats.objects.create(
            website=website,
            page_url="https://viewmap.io/quiet/",
            device="desktop",
            visits=1,
        )
        resp = auth_client.get(
            f"/api/v1/heatmap/pages/?website={website.id}&device=desktop"
        )
        assert resp.data[0]["page_url"] == "https://viewmap.io/seg/"

    def test_cells_sum_across_segments(self, auth_client, website):
        for visitor, source, count in (
            ("new", "direct", 12),
            ("new", "organic", 7),
            ("returning", "email", 2),
        ):
            HeatmapActivity.objects.create(
                website=website,
                page_url="https://viewmap.io/seg/",
                kind="click",
                device="desktop",
                visitor_type=visitor,
                source=source,
                x=50,
                y=30,
                count=count,
            )
        resp = auth_client.get(
            f"/api/v1/heatmap/activity/?website={website.id}"
            "&page_url=https%3A%2F%2Fviewmap.io%2Fseg%2F&kind=click&device=desktop"
        )
        assert resp.status_code == 200
        # One cell, not three: the overlay drew three faint blobs where one hot
        # one belonged, and "peak cell" reported the biggest segment.
        assert len(resp.data) == 1
        assert resp.data[0]["count"] == 21

    def test_cell_element_comes_from_the_heaviest_segment(self, auth_client, website):
        for source, count, element in (
            ("direct", 12, 'button#buy "Buy now"'),
            ("email", 1, ""),
        ):
            HeatmapActivity.objects.create(
                website=website,
                page_url="https://viewmap.io/seg/",
                kind="click",
                device="desktop",
                source=source,
                x=50,
                y=30,
                count=count,
                element=element,
            )
        resp = auth_client.get(
            f"/api/v1/heatmap/activity/?website={website.id}&kind=click&device=desktop"
        )
        assert resp.data[0]["element"] == 'button#buy "Buy now"'

    def test_page_url_param_is_normalised(self, auth_client, website):
        """The stored key is normalised, so a hand-typed URL has to be too."""
        HeatmapActivity.objects.create(
            website=website,
            page_url="https://viewmap.io/seg/",
            kind="click",
            device="desktop",
            x=1,
            y=1,
            count=3,
        )
        resp = auth_client.get(
            f"/api/v1/heatmap/activity/?website={website.id}"
            "&page_url=http%3A%2F%2Fwww.viewmap.io%2Fseg%3Futm_source%3Dx%23top"
            "&kind=click&device=desktop"
        )
        assert resp.status_code == 200
        assert len(resp.data) == 1
        assert resp.data[0]["count"] == 3
