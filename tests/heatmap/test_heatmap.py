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
    """A site with behaviour collection switched on.

    Collection is opt-in per site and defaults to off, so this has to be
    explicit — a fixture that left it off would make every ingest test below
    assert against the "not collecting" path by accident.
    """
    return Website.objects.create(
        team=team, name="Heatmap Site", domain="ingest.io", heatmap_enabled=True
    )


@pytest.fixture
def disabled_website(team):
    return Website.objects.create(
        team=team, name="Quiet Site", domain="quiet.io", heatmap_enabled=False
    )


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
        # The payload's per-bucket values mark which bands *this visit* reached,
        # not a population share. With one visit on record, every band it
        # reached was reached by 100% of visits.
        assert page.scroll_histogram["20"] == 1.0
        assert page.scroll_histogram["80"] == 1.0

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



@pytest.mark.django_db
class TestScrollHistogram:
    """The scroll map's whole claim is "this share of visitors got this far".

    That number is a property of the population, so it can only come from
    counting visits per depth band. The histogram used to be written straight
    from each incoming payload, which meant it always described the single most
    recent visitor — a fresh overwrite on every flush, never a share.
    """

    def _page(self, website):
        return HeatmapPageStats.objects.get(
            website=website, page_url="https://ingest.io/", device="desktop"
        )

    def test_share_falls_off_with_depth_across_visits(self, website):
        # Three visits: all three reach 20%, only one reaches 80%.
        deep = _payload(website.site_id, scroll_histogram={"20": 1, "80": 1},
                        max_scroll_percent=80)
        shallow = _payload(website.site_id, scroll_histogram={"20": 1},
                           max_scroll_percent=20)
        process_heatmap_payload(website.site_id, deep)
        process_heatmap_payload(website.site_id, shallow)
        process_heatmap_payload(website.site_id, shallow)

        page = self._page(website)
        assert page.visits == 3
        assert page.scroll_histogram["20"] == 1.0
        # 1 of 3 visits reached 80% — the drop-off the gradient is meant to show.
        assert page.scroll_histogram["80"] == round(1 / 3, 3)

    def test_histogram_is_not_flat(self, website):
        """A flat histogram paints one flat colour and shows no drop-off.

        The snippet used to write its max-scroll value into *every* reached
        bucket, so the 20% band and the 80% band reported the identical number.
        """
        process_heatmap_payload(
            website.site_id,
            _payload(website.site_id, scroll_histogram={"20": 1}, max_scroll_percent=20),
        )
        process_heatmap_payload(
            website.site_id,
            _payload(
                website.site_id,
                scroll_histogram={"20": 1, "60": 1, "100": 1},
                max_scroll_percent=100,
            ),
        )
        page = self._page(website)
        assert page.scroll_histogram["20"] > page.scroll_histogram["100"]

    def test_periodic_flush_does_not_inflate_share(self, website):
        """Only final flushes count as visits, so only they may count reach.

        A visitor produces several periodic flushes plus one final one. Crediting
        each of those with a visit's worth of reach would pin every share at 1.0.
        """
        for _ in range(4):
            process_heatmap_payload(
                website.site_id,
                _payload(
                    website.site_id, final=False,
                    scroll_histogram={"20": 1, "80": 1}, max_scroll_percent=80,
                ),
            )
        process_heatmap_payload(
            website.site_id,
            _payload(website.site_id, scroll_histogram={"20": 1}, max_scroll_percent=20),
        )
        page = self._page(website)
        assert page.visits == 1
        assert page.scroll_histogram["20"] == 1.0
        assert "80" not in page.scroll_histogram

    def test_falls_back_to_max_scroll_when_no_histogram_sent(self, website):
        process_heatmap_payload(
            website.site_id,
            _payload(website.site_id, scroll_histogram={}, max_scroll_percent=40),
        )
        page = self._page(website)
        assert page.scroll_histogram["40"] == 1.0
        assert "45" not in page.scroll_histogram


@pytest.mark.django_db
class TestPageGeometry:
    """The overlay needs the page's real aspect ratio.

    Without page_height the dashboard cannot know how tall the page it is
    drawing on actually is, which is why it used to ask a human to guess with a
    "page height x1-4" slider.
    """

    def test_page_height_and_viewport_width_recorded(self, website):
        process_heatmap_payload(
            website.site_id,
            _payload(website.site_id, page_height=4200, viewport_width=1440),
        )
        page = HeatmapPageStats.objects.get(
            website=website, page_url="https://ingest.io/", device="desktop"
        )
        assert page.page_height == 4200
        assert page.viewport_width == 1440

    def test_absent_geometry_does_not_wipe_a_good_measurement(self, website):
        """An older snippet build sends neither field; it must not zero them."""
        process_heatmap_payload(
            website.site_id,
            _payload(website.site_id, page_height=4200, viewport_width=1440),
        )
        process_heatmap_payload(website.site_id, _payload(website.site_id))
        page = HeatmapPageStats.objects.get(
            website=website, page_url="https://ingest.io/", device="desktop"
        )
        assert page.page_height == 4200
        assert page.viewport_width == 1440


@pytest.mark.django_db
class TestSegmentDimensions:
    """visitor_type / source are in the schema, the constraints and the view
    filters, but the snippet never sent them, so every row was new/direct."""

    def test_segments_bucket_into_separate_rows(self, website):
        process_heatmap_payload(
            website.site_id,
            _payload(website.site_id, visitor_type="returning", source="organic"),
        )
        process_heatmap_payload(
            website.site_id,
            _payload(website.site_id, visitor_type="new", source="direct"),
        )
        assert HeatmapPageStats.objects.filter(website=website).count() == 2
        returning = HeatmapPageStats.objects.get(
            website=website, visitor_type="returning", source="organic"
        )
        assert returning.visits == 1

    def test_ingest_endpoint_forwards_segments(self, api_client, website):
        with patch("apps.heatmap.views.process_heatmap_payload.delay") as mock_task:
            resp = api_client.post(
                "/api/ingest/heatmap/",
                _payload(website.site_id, visitor_type="returning", source="social"),
                format="json",
            )
        assert resp.status_code == 202
        payload = mock_task.call_args.kwargs["payload"]
        assert payload["visitor_type"] == "returning"
        assert payload["source"] == "social"

    def test_ingest_endpoint_forwards_page_geometry(self, api_client, website):
        with patch("apps.heatmap.views.process_heatmap_payload.delay") as mock_task:
            resp = api_client.post(
                "/api/ingest/heatmap/",
                _payload(website.site_id, page_height=3300, viewport_width=1280),
                format="json",
            )
        assert resp.status_code == 202
        payload = mock_task.call_args.kwargs["payload"]
        assert payload["page_height"] == 3300
        assert payload["viewport_width"] == 1280


@pytest.mark.django_db
class TestPerSiteOptIn:
    """Behaviour collection is enabled per site, the way Hotjar is.

    The tracking snippet is one cached file every client pastes, so it cannot
    be the thing that decides — before this gate existed, every site carrying
    the snippet streamed click, move and scroll data into the heatmap tables
    whether or not anyone had asked for a heatmap of it.
    """

    def test_disabled_site_is_not_collected(self, api_client, disabled_website):
        with patch("apps.heatmap.views.process_heatmap_payload.delay") as mock_task:
            resp = api_client.post(
                "/api/ingest/heatmap/",
                _payload(disabled_website.site_id, page_url="https://quiet.io/"),
                format="json",
            )
        # 204, not 403: nothing is wrong, there is simply nothing to send. The
        # snippet reads it as "stop" and disarms for the rest of the visit.
        assert resp.status_code == 204
        mock_task.assert_not_called()

    def test_disabled_site_writes_no_rows(self, disabled_website):
        """The task re-reads the flag, because a payload can outlive a toggle.

        The view gate stops new work being queued; a message already sitting in
        the queue when collection is switched off would otherwise still land.
        """
        process_heatmap_payload(
            disabled_website.site_id,
            {
                "page_url": "https://quiet.io/",
                "device": "desktop",
                "final": True,
                "total_clicks": 5,
                "max_scroll_percent": 50,
                "cells": [{"kind": "click", "x": 10, "y": 10, "count": 3}],
            },
        )
        assert not HeatmapActivity.objects.filter(website=disabled_website).exists()
        assert not HeatmapPageStats.objects.filter(website=disabled_website).exists()

    def test_enabling_starts_collection_without_a_re_paste(
        self, api_client, disabled_website
    ):
        """The toggle takes effect on the next pageview, not on the next paste.

        A re-paste campaign across every client is the most expensive thing this
        codebase can ask for, so the gate lives in the ingest rather than in the
        snippet's markup.
        """
        disabled_website.heatmap_enabled = True
        disabled_website.save(update_fields=["heatmap_enabled"])
        with patch("apps.heatmap.views.process_heatmap_payload.delay") as mock_task:
            resp = api_client.post(
                "/api/ingest/heatmap/",
                _payload(disabled_website.site_id, page_url="https://quiet.io/"),
                format="json",
            )
        assert resp.status_code == 202
        mock_task.assert_called_once()


@pytest.mark.django_db
class TestPageUrlNormalization:
    """One page has to be one row, whatever spelling the browser reported.

    The snippet sends `window.location.href` verbatim, which is right for it to
    do and wrong to key on. Normalisation is server-side so the rule reaches
    every existing install without a re-paste.
    """

    def test_fragment_does_not_fork_a_page(self, website):
        for url in (
            "https://ingest.io/pricing/",
            "https://ingest.io/pricing/#plans",
            "https://ingest.io/pricing/#faq",
        ):
            process_heatmap_payload(
                website.site_id,
                {
                    "page_url": url,
                    "device": "desktop",
                    "final": True,
                    "total_clicks": 1,
                    "cells": [{"kind": "click", "x": 10, "y": 10, "count": 1}],
                },
            )
        stats = HeatmapPageStats.objects.filter(website=website)
        assert stats.count() == 1
        assert stats.first().visits == 3
        assert stats.first().page_url == "https://ingest.io/pricing/"

    def test_campaign_params_do_not_fork_a_page(self, website):
        """The landing page you most want a heatmap of is the one behind ads."""
        for url in (
            "https://ingest.io/offer/",
            "https://ingest.io/offer/?utm_source=google&utm_medium=cpc",
            "https://ingest.io/offer/?gclid=abc123",
            "https://ingest.io/offer/?fbclid=xyz",
        ):
            process_heatmap_payload(
                website.site_id,
                {"page_url": url, "device": "desktop", "final": True, "cells": []},
            )
        stats = HeatmapPageStats.objects.filter(website=website)
        assert stats.count() == 1
        assert stats.first().visits == 4

    def test_host_and_scheme_spellings_collapse(self, website):
        for url in (
            "https://ingest.io/about/",
            "http://ingest.io/about/",
            "https://www.ingest.io/about/",
            "https://ingest.io/about/index.html",
            "https://ingest.io/about",
        ):
            process_heatmap_payload(
                website.site_id,
                {"page_url": url, "device": "desktop", "final": True, "cells": []},
            )
        assert HeatmapPageStats.objects.filter(website=website).count() == 1

    def test_routing_params_still_separate_pages(self, website):
        """`?p=12` is a different page; `?utm_source=x` is the same one."""
        for url in ("https://ingest.io/?p=11", "https://ingest.io/?p=12"):
            process_heatmap_payload(
                website.site_id,
                {"page_url": url, "device": "desktop", "final": True, "cells": []},
            )
        assert HeatmapPageStats.objects.filter(website=website).count() == 2

    def test_param_order_does_not_fork_a_page(self, website):
        for url in (
            "https://ingest.io/shop/?lang=fr&page=2",
            "https://ingest.io/shop/?page=2&lang=fr",
        ):
            process_heatmap_payload(
                website.site_id,
                {"page_url": url, "device": "desktop", "final": True, "cells": []},
            )
        assert HeatmapPageStats.objects.filter(website=website).count() == 1

    def test_cells_merge_across_spellings(self, website):
        for url in ("https://ingest.io/x/", "https://ingest.io/x/?utm_source=n"):
            process_heatmap_payload(
                website.site_id,
                {
                    "page_url": url,
                    "device": "desktop",
                    "final": True,
                    "cells": [{"kind": "click", "x": 40, "y": 60, "count": 5}],
                },
            )
        cells = HeatmapActivity.objects.filter(website=website, kind="click")
        assert cells.count() == 1
        assert cells.first().count == 10
