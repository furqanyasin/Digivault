"""The heatmap's backdrop screenshots.

The overlay is a grid of percentages; it only lines up on something whose width
and height are known. These tests cover the row that records that geometry, the
team scoping on the image (screenshots of clients' pages must not be reachable
from another team), and the guards that stop a capture sweep from behaving like
a scanner against a customer's origin.
"""

import uuid
from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.heatmap.capture import CaptureBlocked, CaptureResult, CaptureUnavailable
from apps.heatmap.models import HeatmapPageSnapshot, HeatmapPageStats
from apps.heatmap.tasks import capture_page_snapshot, run_due_snapshot_captures
from apps.websites.models import Website

# Already in normalised form (`apps/heatmap/page_urls.py`), which is what the
# ingest stores and what the read endpoints key on.
PAGE = "https://snap.io/pricing/"


@pytest.fixture
def website(team):
    return Website.objects.create(
        team=team, name="Snap Site", domain="snap.io", heatmap_enabled=True
    )


@pytest.fixture
def other_website(db):
    owner2 = User.objects.create_user(email="snap_other@test.com", password="Pass123!")
    team2 = TeamService.create(name="Snap Other", owner=owner2)
    return Website.objects.create(team=team2, name="Other", domain="othersnap.io")


def _ready_snapshot(website, page_url=PAGE, device="desktop"):
    snap = HeatmapPageSnapshot.objects.create(
        website=website,
        page_url=page_url,
        device=device,
        width=1280,
        height=3840,
        status=HeatmapPageSnapshot.Status.READY,
        captured_at=timezone.now(),
    )
    snap.image.save(f"{snap.pk}.png", ContentFile(b"\x89PNG\r\n\x1a\n fake"), save=True)
    return snap


@pytest.mark.django_db
class TestSnapshotEndpoint:
    def test_requires_auth(self, api_client, website):
        _ready_snapshot(website)
        resp = api_client.get(f"/api/v1/heatmap/snapshot/?website={website.id}")
        assert resp.status_code in (401, 403)

    def test_returns_geometry_and_image_url(self, auth_client, website):
        snap = _ready_snapshot(website)
        resp = auth_client.get(
            f"/api/v1/heatmap/snapshot/?website={website.id}"
            f"&page_url={PAGE}&device=desktop"
        )
        assert resp.status_code == 200
        # The aspect ratio is the whole point: without width/height the overlay
        # has nothing to size itself against.
        assert resp.data["width"] == 1280
        assert resp.data["height"] == 3840
        assert resp.data["image_url"] == f"/api/v1/heatmap/snapshots/{snap.pk}/image/"

    def test_404_when_nothing_captured(self, auth_client, website):
        resp = auth_client.get(
            f"/api/v1/heatmap/snapshot/?website={website.id}&page_url={PAGE}"
        )
        # A normal state, not an error — the dashboard falls back to the iframe.
        assert resp.status_code == 404

    def test_pending_snapshot_exposes_no_image_url(self, auth_client, website):
        HeatmapPageSnapshot.objects.create(
            website=website,
            page_url=PAGE,
            device="desktop",
            status=HeatmapPageSnapshot.Status.PENDING,
        )
        resp = auth_client.get(
            f"/api/v1/heatmap/snapshot/?website={website.id}&page_url={PAGE}"
        )
        assert resp.status_code == 200
        assert resp.data["image_url"] is None

    def test_scoped_to_team(self, auth_client, website, other_website):
        _ready_snapshot(other_website, page_url="https://othersnap.io/x/")
        resp = auth_client.get(
            f"/api/v1/heatmap/snapshot/?website={other_website.id}"
            "&page_url=https://othersnap.io/x/"
        )
        assert resp.status_code == 404

    def test_snapshot_is_shared_across_segments(self, auth_client, website):
        """A snapshot is a picture of a page, not of a visitor cohort."""
        _ready_snapshot(website)
        for visitor in ("new", "returning"):
            resp = auth_client.get(
                f"/api/v1/heatmap/snapshot/?website={website.id}&page_url={PAGE}"
                f"&device=desktop&visitor_type={visitor}"
            )
            assert resp.status_code == 200


@pytest.mark.django_db
class TestSnapshotImage:
    def test_serves_png(self, auth_client, website):
        snap = _ready_snapshot(website)
        resp = auth_client.get(f"/api/v1/heatmap/snapshots/{snap.pk}/image/")
        assert resp.status_code == 200
        assert resp["Content-Type"] == "image/png"

    def test_other_teams_image_is_not_readable(self, auth_client, other_website):
        """Screenshots can show pricing or staging content — never cross teams."""
        snap = _ready_snapshot(other_website, page_url="https://othersnap.io/x/")
        resp = auth_client.get(f"/api/v1/heatmap/snapshots/{snap.pk}/image/")
        assert resp.status_code == 404

    def test_requires_auth(self, api_client, website):
        snap = _ready_snapshot(website)
        resp = api_client.get(f"/api/v1/heatmap/snapshots/{snap.pk}/image/")
        assert resp.status_code in (401, 403)

    def test_missing_file_is_404_not_500(self, auth_client, website):
        """The row can outlive the file (volume reset). Fall back, do not crash."""
        snap = _ready_snapshot(website)
        snap.image.storage.delete(snap.image.name)
        resp = auth_client.get(f"/api/v1/heatmap/snapshots/{snap.pk}/image/")
        assert resp.status_code == 404


@pytest.mark.django_db
class TestSnapshotRefresh:
    def test_queues_capture(self, auth_client, website):
        with (
            patch("apps.heatmap.capture.capture_available", return_value=True),
            patch("apps.heatmap.views.capture_page_snapshot.delay") as mock_task,
        ):
            resp = auth_client.post(
                "/api/v1/heatmap/snapshot/refresh/",
                {"website": str(website.id), "page_url": PAGE, "device": "desktop"},
                format="json",
            )
        assert resp.status_code == 202
        mock_task.assert_called_once_with(str(website.id), PAGE, "desktop")

    def test_capture_is_keyed_on_the_normalised_page_url(self, auth_client, website):
        """A snapshot must land on the row the heatmap is stored under.

        The dashboard hands back whatever URL it was given, and a person
        pasting one will include the fragment and the campaign params. Keyed
        raw, the picture attaches to a row nothing ever reads and the page goes
        on reporting "no screenshot yet" after every successful capture.
        """
        with (
            patch("apps.heatmap.capture.capture_available", return_value=True),
            patch("apps.heatmap.views.capture_page_snapshot.delay") as mock_task,
        ):
            resp = auth_client.post(
                "/api/v1/heatmap/snapshot/refresh/",
                {
                    "website": str(website.id),
                    "page_url": "https://www.snap.io/pricing?utm_source=ads#plans",
                    "device": "desktop",
                },
                format="json",
            )
        assert resp.status_code == 202
        mock_task.assert_called_once_with(str(website.id), PAGE, "desktop")

    def test_capture_unavailable_answers_503_immediately(self, auth_client, website):
        """Say why, rather than queueing work that can only record `unavailable`.

        The dashboard polls for ~36 seconds after a 202. On a deployment with
        no Chromium that looked exactly like a slow capture and then silently
        gave up, which is the loudest "the heatmap is broken" symptom there is.
        """
        with (
            patch("apps.heatmap.capture.capture_available", return_value=False),
            patch("apps.heatmap.views.capture_page_snapshot.delay") as mock_task,
        ):
            resp = auth_client.post(
                "/api/v1/heatmap/snapshot/refresh/",
                {"website": str(website.id), "page_url": PAGE, "device": "desktop"},
                format="json",
            )
        assert resp.status_code == 503
        assert resp.data["code"] == "capture_unavailable"
        mock_task.assert_not_called()

    def test_requires_page_url(self, auth_client, website):
        resp = auth_client.post(
            "/api/v1/heatmap/snapshot/refresh/",
            {"website": str(website.id)},
            format="json",
        )
        assert resp.status_code == 400

    def test_cannot_capture_another_teams_site(self, auth_client, other_website):
        with patch("apps.heatmap.views.capture_page_snapshot.delay") as mock_task:
            resp = auth_client.post(
                "/api/v1/heatmap/snapshot/refresh/",
                {
                    "website": str(other_website.id),
                    "page_url": "https://othersnap.io/x",
                },
                format="json",
            )
        assert resp.status_code == 404
        mock_task.assert_not_called()


@pytest.mark.django_db
class TestCaptureTask:
    """Every capture outcome must land on the row, never raise.

    The dashboard reads `status` to decide what backdrop to show, and a heatmap
    must keep rendering when its screenshot cannot be taken.
    """

    def test_missing_playwright_records_unavailable(self, website):
        with patch(
            "apps.heatmap.capture.capture_page",
            side_effect=CaptureUnavailable("no chromium"),
        ):
            capture_page_snapshot(str(website.id), PAGE, "desktop")

        snap = HeatmapPageSnapshot.objects.get(website=website, page_url=PAGE)
        assert snap.status == HeatmapPageSnapshot.Status.UNAVAILABLE

    def test_blocked_origin_records_blocked(self, website):
        with patch(
            "apps.heatmap.capture.capture_page", side_effect=CaptureBlocked("429")
        ):
            capture_page_snapshot(str(website.id), PAGE, "desktop")

        snap = HeatmapPageSnapshot.objects.get(website=website, page_url=PAGE)
        assert snap.status == HeatmapPageSnapshot.Status.BLOCKED
        assert "429" in snap.error_message

    def test_unexpected_error_records_failed(self, website):
        with patch(
            "apps.heatmap.capture.capture_page", side_effect=RuntimeError("boom")
        ):
            capture_page_snapshot(str(website.id), PAGE, "desktop")

        snap = HeatmapPageSnapshot.objects.get(website=website, page_url=PAGE)
        assert snap.status == HeatmapPageSnapshot.Status.FAILED

    def test_success_stores_image_and_geometry(self, website):
        result = CaptureResult(png=b"\x89PNG\r\n\x1a\n data", width=1280, height=2600)
        with patch("apps.heatmap.capture.capture_page", return_value=result):
            capture_page_snapshot(str(website.id), PAGE, "desktop")

        snap = HeatmapPageSnapshot.objects.get(website=website, page_url=PAGE)
        assert snap.status == HeatmapPageSnapshot.Status.READY
        assert (snap.width, snap.height) == (1280, 2600)
        assert snap.captured_at is not None
        assert snap.image

    def test_unknown_website_is_dropped(self, db):
        capture_page_snapshot(str(uuid.uuid4()), PAGE, "desktop")
        assert not HeatmapPageSnapshot.objects.exists()


@pytest.mark.django_db
class TestCaptureSweep:
    def test_noop_without_playwright(self, website):
        HeatmapPageStats.objects.create(
            website=website, page_url=PAGE, device="desktop", visits=3
        )
        with patch("apps.heatmap.capture.capture_available", return_value=False):
            assert run_due_snapshot_captures() == 0

    def test_only_pages_with_traffic_are_captured(self, website):
        HeatmapPageStats.objects.create(
            website=website, page_url=PAGE, device="desktop", visits=3
        )
        # No visits — capturing it would spend the shared per-host budget on a
        # heatmap that has nothing to draw.
        HeatmapPageStats.objects.create(
            website=website,
            page_url="https://snap.io/quiet/",
            device="desktop",
            visits=0,
        )
        with (
            patch("apps.heatmap.capture.capture_available", return_value=True),
            patch("apps.heatmap.tasks.capture_page_snapshot.delay") as mock_task,
        ):
            assert run_due_snapshot_captures() == 1
        assert mock_task.call_args[0][1] == PAGE

    def test_fresh_snapshot_is_not_recaptured(self, website):
        HeatmapPageStats.objects.create(
            website=website, page_url=PAGE, device="desktop", visits=3
        )
        _ready_snapshot(website)
        with (
            patch("apps.heatmap.capture.capture_available", return_value=True),
            patch("apps.heatmap.tasks.capture_page_snapshot.delay") as mock_task,
        ):
            assert run_due_snapshot_captures() == 0
        mock_task.assert_not_called()

    def test_respects_per_run_cap(self, website, settings):
        settings.HEATMAP_SNAPSHOT_MAX_PER_RUN = 2
        for i in range(5):
            HeatmapPageStats.objects.create(
                website=website,
                page_url=f"https://snap.io/p{i}/",
                device="desktop",
                visits=2,
            )
        with (
            patch("apps.heatmap.capture.capture_available", return_value=True),
            patch("apps.heatmap.tasks.capture_page_snapshot.delay"),
        ):
            assert run_due_snapshot_captures() == 2


class TestCaptureSsrfGuard:
    """The guard has to survive redirects, not just vet the URL we were handed.

    Chromium follows redirects inside its own network stack, so checking
    `page_url` once and then calling `page.goto` guards nothing: a public host
    can answer 302 with `Location: http://169.254.169.254/` and the browser
    walks straight to the cloud metadata service. `apps/common/outbound.py`
    already re-runs the guard on every hop; a headless browser needs the same.

    A screenshot is data leaving the network, so subresources count too — an
    <iframe> pointed at an internal address would render internal content into
    a picture the customer can read back.
    """

    def test_internal_hosts_are_refused(self):
        from apps.heatmap.capture import _guard_factory

        allowed = _guard_factory()
        for url in (
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata
            "http://127.0.0.1:8000/api/v1/websites/",     # this very API
            "http://10.0.0.5/",
            "http://192.168.1.1/",
            "http://[::1]/",
            "file:///etc/passwd",
        ):
            assert allowed(url) is False, f"{url} should have been refused"

    def test_public_hosts_are_allowed(self):
        """The guard resolves DNS, so the pass case is stubbed — this asserts
        the wiring (a passing guard lets the request through), not resolution."""
        from unittest.mock import patch as _patch

        from apps.heatmap.capture import _guard_factory

        allowed = _guard_factory()
        with _patch("apps.heatmap.capture.assert_public_url", return_value=None):
            assert allowed("https://example.com/") is True

    def test_verdicts_are_memoised_per_host(self):
        """The guard resolves DNS; a real page hits the same origins dozens of
        times, so the result is cached rather than re-resolved per request."""
        from unittest.mock import patch as _patch

        from apps.heatmap.capture import _guard_factory

        allowed = _guard_factory()
        with _patch(
            "apps.heatmap.capture.assert_public_url", return_value=None
        ) as guard:
            for _ in range(5):
                allowed("https://example.com/a")
                allowed("https://example.com/b")
        assert guard.call_count == 1

    def test_a_blocked_host_stays_blocked_for_the_whole_capture(self):
        from apps.heatmap.capture import _guard_factory

        allowed = _guard_factory()
        assert allowed("http://169.254.169.254/one") is False
        # Same origin, different path — must not get a second chance.
        assert allowed("http://169.254.169.254/two") is False
