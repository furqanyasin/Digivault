from rest_framework import serializers

from apps.common.serializers import BaseModelSerializer
from apps.heatmap.models import HeatmapActivity, HeatmapPageStats

# Hard caps bounding a single ingest payload. The snippet already aggregates
# into a 100x100 grid, but a hostile payload must not be allowed to mint
# arbitrary rows.
MAX_ACTIVITY_CELLS = 5000
MAX_CELL_COUNT = 100000


class HeatmapCellIngestSerializer(serializers.Serializer):
    """One pre-aggregated interaction cell from the snippet."""

    kind = serializers.ChoiceField(choices=HeatmapActivity.Kind.values)
    x = serializers.IntegerField(min_value=0, max_value=100)
    y = serializers.IntegerField(min_value=0, max_value=100)
    count = serializers.IntegerField(min_value=1, max_value=MAX_CELL_COUNT)
    # Optional best-effort element descriptor for click/rage cells.
    element = serializers.CharField(max_length=300, allow_blank=True, default="")


class HeatmapIngestSerializer(serializers.Serializer):
    """Aggregated interaction payload posted by the snippet."""

    site_id = serializers.CharField(max_length=64)
    page_url = serializers.URLField(max_length=2048)
    # Coarse bucket, not the raw user agent (the snippet decides the bucket).
    device = serializers.ChoiceField(
        choices=HeatmapPageStats.Device.values, default=HeatmapPageStats.Device.DESKTOP
    )
    # Segmentation dimensions — the snippet derives both and they bucket the
    # aggregated cells so the dashboard can filter/compare cohorts.
    visitor_type = serializers.ChoiceField(
        choices=HeatmapPageStats.VisitorType.values,
        default=HeatmapPageStats.VisitorType.NEW,
    )
    source = serializers.ChoiceField(
        choices=HeatmapPageStats.Source.values,
        default=HeatmapPageStats.Source.DIRECT,
    )
    user_agent = serializers.CharField(max_length=512, allow_blank=True, default="")
    # True on the page-unload flush. Only final flushes increment the page's
    # `visits` counter — incremental periodic flushes still carry their cells
    # and click totals but don't inflate the pageview count.
    final = serializers.BooleanField(default=False)
    viewport_width = serializers.IntegerField(min_value=1, max_value=10000, required=False)
    total_clicks = serializers.IntegerField(min_value=0, default=0)
    max_scroll_percent = serializers.IntegerField(
        min_value=0, max_value=100, default=0
    )
    # { bucket: share_reached } mapping — bucket is an int 5-100 step 5.
    scroll_histogram = serializers.DictField(
        child=serializers.FloatField(min_value=0.0, max_value=1.0),
        required=False,
        default=dict,
    )
    cells = HeatmapCellIngestSerializer(
        many=True, default=list, max_length=MAX_ACTIVITY_CELLS
    )


class HeatmapPageSerializer(BaseModelSerializer):
    """A page in the selector with its summary + scroll histogram."""

    class Meta:
        model = HeatmapPageStats
        fields = (
            "id", "page_url", "device", "visitor_type", "source", "visits",
            "total_clicks", "max_scroll_percent", "scroll_histogram",
            "first_seen_at", "last_seen_at",
        )
        read_only_fields = fields


class HeatmapCellSerializer(BaseModelSerializer):
    class Meta:
        model = HeatmapActivity
        fields = ("kind", "x", "y", "count", "device", "visitor_type", "source", "element")
        read_only_fields = fields
