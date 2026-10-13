from django.urls import path

from apps.heatmap.views import (
    HeatmapCellListView,
    HeatmapIngestView,
    HeatmapPageListView,
    HeatmapSiteSummaryView,
    HeatmapSnapshotImageView,
    HeatmapSnapshotRefreshView,
    HeatmapSnapshotView,
)

# Ingest lives under /api/ingest/heatmap/ — the same public, version-free prefix
# as the script ingest, so production nginx (which only proxies /api/ingest|...)
# already forwards it and the PublicIngestCorsMiddleware already allows it.
ingest_urlpatterns = [
    path("ingest/heatmap/", HeatmapIngestView.as_view(), name="heatmap-ingest"),
]

# Versioned endpoints read by the dashboard — included under /api/v1/
urlpatterns = [
    path("heatmap/pages/", HeatmapPageListView.as_view(), name="heatmap-pages"),
    path("heatmap/activity/", HeatmapCellListView.as_view(), name="heatmap-activity"),
    path("heatmap/summary/", HeatmapSiteSummaryView.as_view(), name="heatmap-summary"),
    path("heatmap/snapshot/", HeatmapSnapshotView.as_view(), name="heatmap-snapshot"),
    path(
        "heatmap/snapshot/refresh/",
        HeatmapSnapshotRefreshView.as_view(),
        name="heatmap-snapshot-refresh",
    ),
    # The image is served by the API, not MEDIA_URL, so it stays team-scoped.
    path(
        "heatmap/snapshots/<uuid:pk>/image/",
        HeatmapSnapshotImageView.as_view(),
        name="heatmap-snapshot-image",
    ),
]
