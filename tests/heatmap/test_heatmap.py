import pytest
from unittest.mock import patch

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.heatmap.models import HeatmapActivity, HeatmapPageStats
from apps.heatmap.tasks import process_heatmap_payload
from apps.websites.models import Website


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="heatmap_o@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Heatmap Agency", owner=owner)


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="Heatmap Site", domain="ingest.io")


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient

    return APIClient()


def _payload(site_id, page_url="https://ingest.io/", **overrides):
    payload = {
        "site_id": site_id,
        "page_url": page_url,
        "device": "desktop",
        "user_agent": "Mozilla/5.0",
        "final": True,
        "total_clicks": 10,
        "max_scroll_percent": 80,
        "scroll_histogram": {"20": 0.9, "80": 0.4},
        "cells": [
            {"kind": "click", "x": 50, "y": 30, "count": 6},
            {"kind": "click", "x": 20, "y": 10, "count": 4},
            {"kind": "move", "x": 50, "y": 30, "count": 40},
        ],
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
class TestHeatmapIngestEndpoint:
    def test_valid_payload_returns_202(self, api_client, website):
        with patch("apps.heatmap.views.process_heatmap_payload.delay") as mock_task:
            resp = api_client.post(
                "/api/ingest/heatmap/", _payload(website.site_id), format="json"
            )
        assert resp.status_code == 202
        mock_task.assert_called_once()

    def test_unknown_site_id_returns_404(self, api_client):
        resp = api_client.post(
            "/api/ingest/heatmap/", _payload("nonexistent-site"), format="json"
        )
        assert resp.status_code == 404

    def test_missing_page_url_returns_400(self, api_client, website):
        payload = _payload(website.site_id)
        del payload["page_url"]
        resp = api_client.post("/api/ingest/heatmap/", payload, format="json")
        assert resp.status_code == 400

    def test_invalid_cell_coords_rejected(self, api_client, website):
        payload = _payload(
            website.site_id, cells=[{"kind": "click", "x": 999, "y": 30, "count": 1}]
        )
        resp = api_client.post("/api/ingest/heatmap/", payload, format="json")
        assert resp.status_code == 400

    def test_no_auth_required(self, api_client, website):
        with patch("apps.heatmap.views.process_heatmap_payload.delay"):
            resp = api_client.post(
                "/api/ingest/heatmap/", _payload(website.site_id), format="json"
            )
        assert resp.status_code == 202

    def test_domain_mismatch_returns_403(self, api_client, website):
        with patch("apps.heatmap.views.process_heatmap_payload.delay") as mock_task:
            resp = api_client.post(
                "/api/ingest/heatmap/",
                _payload(website.site_id, page_url="https://evil.com/"),
                format="json",
                HTTP_ORIGIN="https://evil.com",
            )
        assert resp.status_code == 403
        mock_task.assert_not_called()

    def test_matching_domain_origin_allowed(self, api_client, website):
        with patch("apps.heatmap.views.process_heatmap_payload.delay") as mock_task:
            resp = api_client.post(
                "/api/ingest/heatmap/",
                _payload(website.site_id),
                format="json",
                HTTP_ORIGIN="https://ingest.io",
            )
        assert resp.status_code == 202
        mock_task.assert_called_once()

    def test_ingest_forwards_element_to_task(self, api_client, website):
        with patch("apps.heatmap.views.process_heatmap_payload.delay") as mock_task:
            resp = api_client.post(
                "/api/ingest/heatmap/",
                _payload(
                    website.site_id,
                    cells=[
                        {"kind": "click", "x": 10, "y": 10, "count": 1, "element": "button#go"}
                    ],
                ),
                format="json",
            )
        assert resp.status_code == 202
        call_cells = mock_task.call_args.kwargs["payload"]["cells"]
        assert call_cells[0]["element"] == "button#go"


@pytest.mark.django_db
class TestHeatmapAggregation:
    def _seed_activity(self, website):
        return HeatmapActivity.objects.create(
            website=website,
            page_url="https://ingest.io/",
            kind="click",
            device="desktop",
            x=50,
            y=30,
            count=1,
        )

    def test_accumulates_cells_and_stats(self, website):
        process_heatmap_payload(
            website.site_id, _payload(website.site_id)
        )
        page = HeatmapPageStats.objects.get(
            website=website, page_url="https://ingest.io/", device="desktop"
        )
        assert page.visits == 1
        assert page.total_clicks == 10
        assert page.max_scroll_percent == 80
        assert page.scroll_histogram["80"] == 0.4

        click = HeatmapActivity.objects.get(
            website=website, page_url="https://ingest.io/", kind="click", x=50, y=30
        )
        assert click.count == 6
        move = HeatmapActivity.objects.get(
            website=website, page_url="https://ingest.io/", kind="move", x=50, y=30
        )
        assert move.count == 40

    def test_same_cell_sums_across_posts(self, website):
        p = _payload(website.site_id)
        process_heatmap_payload(website.site_id, p)
        p2 = _payload(website.site_id, final=False, total_clicks=5)
        process_heatmap_payload(website.site_id, p2)

        click = HeatmapActivity.objects.get(
            website=website, page_url="https://ingest.io/", kind="click", x=50, y=30
        )
        assert click.count == 12  # 6 + 6 from the same payload twice

        page = HeatmapPageStats.objects.get(
            website=website, page_url="https://ingest.io/", device="desktop"
        )
        # final=False must NOT increment visits
        assert page.visits == 1
        assert page.total_clicks == 15  # 10 + 5

    def test_final_false_does_not_increment_visits(self, website):
        process_heatmap_payload(website.site_id, _payload(website.site_id, final=False))
        page = HeatmapPageStats.objects.get(
            website=website, page_url="https://ingest.io/", device="desktop"
        )
        assert page.visits == 0

    def test_unknown_site_silently_dropped(self, website):
        process_heatmap_payload("nonexistent-site", _payload("nonexistent-site"))
        assert not HeatmapPageStats.objects.exists()

    def test_same_cell_accumulates_via_existing_row(self, website):
        existing = self._seed_activity(website)
        assert existing.count == 1
        process_heatmap_payload(
            website.site_id,
            _payload(website.site_id, cells=[{"kind": "click", "x": 50, "y": 30, "count": 6}]),
        )
        existing.refresh_from_db()
        assert existing.count == 7

    def test_mobile_is_separate_bucket(self, website):
        process_heatmap_payload(website.site_id, _payload(website.site_id, device="mobile"))
        desktop = HeatmapActivity.objects.filter(
            website=website, kind="click", x=50, y=30, device="desktop"
        )
        mobile = HeatmapActivity.objects.filter(
            website=website, kind="click", x=50, y=30, device="mobile"
        )
        assert not desktop.exists()
        assert mobile.exists()

    def test_max_scroll_keeps_highest(self, website):
        process_heatmap_payload(website.site_id, _payload(website.site_id, max_scroll_percent=40))
        process_heatmap_payload(website.site_id, _payload(website.site_id, max_scroll_percent=95))
        page = HeatmapPageStats.objects.get(
            website=website, page_url="https://ingest.io/", device="desktop"
        )
        assert page.max_scroll_percent == 95

    def test_invalid_cells_are_skipped(self, website):
        payload = _payload(website.site_id)
        payload["cells"] = [
            {"kind": "click", "x": 10, "y": 10, "count": 3},
            {"kind": "click", "x": "abc", "y": 10, "count": 1},
            {"kind": "click", "x": 20, "y": 20, "count": 0},
        ]
        process_heatmap_payload(website.site_id, payload)
        cells = HeatmapActivity.objects.filter(website=website)
        assert cells.count() == 1
        assert cells.get().count == 3

    def test_rage_cells_accepted_and_accumulated(self, website):
        process_heatmap_payload(
            website.site_id,
            _payload(
                website.site_id,
                total_clicks=6,
                cells=[
                    {"kind": "rage", "x": 40, "y": 25, "count": 2},
                    {"kind": "rage", "x": 40, "y": 25, "count": 3},
                ],
            ),
        )
        rage = HeatmapActivity.objects.get(
            website=website, page_url="https://ingest.io/", kind="rage", x=40, y=25
        )
        assert rage.count == 5
        assert HeatmapActivity.objects.filter(website=website, kind="click").count() == 0

    def test_element_stored_on_cell(self, website):
        process_heatmap_payload(
            website.site_id,
            _payload(
                website.site_id,
                cells=[
                    {"kind": "click", "x": 50, "y": 30, "count": 2, "element": 'button#buy "Buy now"'},
                ],
            ),
        )
        cell = HeatmapActivity.objects.get(website=website, kind="click", x=50, y=30)
        assert cell.element == 'button#buy "Buy now"'

    def test_blank_element_does_not_wipe_existing(self, website):
        process_heatmap_payload(
            website.site_id,
            _payload(
                website.site_id,
                cells=[{"kind": "click", "x": 50, "y": 30, "count": 2, "element": "button#buy"}],
            ),
        )
        # A later flush arriving without an element must not clear the descriptor.
        process_heatmap_payload(
            website.site_id,
            _payload(
                website.site_id,
                cells=[{"kind": "click", "x": 50, "y": 30, "count": 1, "element": ""}],
            ),
        )
        cell = HeatmapActivity.objects.get(website=website, kind="click", x=50, y=30)
        assert cell.count == 3
        assert cell.element == "button#buy"

    def test_ingest_rejects_unknown_kind(self, api_client, website):
        payload = _payload(
            website.site_id, cells=[{"kind": "nope", "x": 10, "y": 10, "count": 1}]
        )
        resp = api_client.post("/api/ingest/heatmap/", payload, format="json")
        assert resp.status_code == 400

