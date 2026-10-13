"""Retention for heatmap interaction data.

`HeatmapActivity` is the highest-cardinality table in the codebase — up to a
100x100 grid of cells times twenty segment buckets, per page, per site. Every
other event table here already has a purge (script snapshots at 90 days,
SiteEvent tiered at 365/90) and this one shipped without one, which is
survivable at a handful of sites and is not across an agency's whole book.
"""

from datetime import timedelta

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.heatmap.models import (
    HeatmapActivity,
    HeatmapPageSnapshot,
    HeatmapPageStats,
)
from apps.heatmap.tasks import purge_old_heatmap_data
from apps.websites.models import Website

PAGE = "https://purge.io/old/"
LIVE = "https://purge.io/live/"


@pytest.fixture
def website(team):
    return Website.objects.create(
        team=team, name="Purge Site", domain="purge.io", heatmap_enabled=True
    )


def _age(queryset, days):
    """Backdate `last_seen_at`, which `auto_now` would otherwise stamp to now."""
    queryset.update(last_seen_at=timezone.now() - timedelta(days=days))


@pytest.mark.django_db
class TestPurgeOldHeatmapData:
    def test_stale_cells_and_pages_go(self, website, settings):
        settings.HEATMAP_DATA_MAX_AGE_DAYS = 180
        HeatmapActivity.objects.create(
            website=website, page_url=PAGE, kind="click", x=1, y=1, count=5
        )
        HeatmapPageStats.objects.create(
            website=website, page_url=PAGE, device="desktop", visits=3
        )
        _age(HeatmapActivity.objects.all(), 400)
        _age(HeatmapPageStats.objects.all(), 400)

        result = purge_old_heatmap_data()

        assert result["cells"] == 1
        assert result["pages"] == 1
        assert not HeatmapActivity.objects.exists()
        assert not HeatmapPageStats.objects.exists()

    def test_a_page_still_being_visited_is_never_purged(self, website, settings):
        """Ageing is on `last_seen_at`, not on when the page was first seen.

        Keyed on creation, the busiest page on a site — the one that has been
        collecting for two years — would be the first thing deleted.
        """
        settings.HEATMAP_DATA_MAX_AGE_DAYS = 180
        cell = HeatmapActivity.objects.create(
            website=website, page_url=LIVE, kind="click", x=2, y=2, count=9
        )
        HeatmapActivity.objects.filter(pk=cell.pk).update(
            created_at=timezone.now() - timedelta(days=900)
        )
        stats = HeatmapPageStats.objects.create(
            website=website, page_url=LIVE, device="desktop", visits=50
        )
        HeatmapPageStats.objects.filter(pk=stats.pk).update(
            created_at=timezone.now() - timedelta(days=900)
        )

        purge_old_heatmap_data()

        assert HeatmapActivity.objects.filter(pk=cell.pk).exists()
        assert HeatmapPageStats.objects.filter(pk=stats.pk).exists()

    def test_snapshot_of_a_live_page_survives(self, website, settings):
        settings.HEATMAP_DATA_MAX_AGE_DAYS = 180
        HeatmapPageStats.objects.create(
            website=website, page_url=LIVE, device="desktop", visits=4
        )
        snap = HeatmapPageSnapshot.objects.create(
            website=website,
            page_url=LIVE,
            device="desktop",
            status=HeatmapPageSnapshot.Status.READY,
            captured_at=timezone.now() - timedelta(days=900),
        )
        # Old picture, live page: the snapshot is still the backdrop that page's
        # heatmap is drawn on, and it is the expensive row to re-acquire.
        result = purge_old_heatmap_data()
        assert result["snapshots"] == 0
        assert HeatmapPageSnapshot.objects.filter(pk=snap.pk).exists()

    def test_snapshot_is_purged_once_its_page_is_gone(self, website, settings):
        settings.HEATMAP_DATA_MAX_AGE_DAYS = 180
        HeatmapPageStats.objects.create(
            website=website, page_url=PAGE, device="desktop", visits=4
        )
        _age(HeatmapPageStats.objects.all(), 400)
        snap = HeatmapPageSnapshot.objects.create(
            website=website,
            page_url=PAGE,
            device="desktop",
            status=HeatmapPageSnapshot.Status.READY,
            captured_at=timezone.now(),
        )
        snap.image.save(f"{snap.pk}.png", ContentFile(b"\x89PNG\r\n\x1a\n x"), save=True)
        storage, name = snap.image.storage, snap.image.name

        result = purge_old_heatmap_data()

        assert result["snapshots"] == 1
        assert not HeatmapPageSnapshot.objects.filter(pk=snap.pk).exists()
        # The row going away does not reclaim the PNG on its own.
        assert not storage.exists(name)
