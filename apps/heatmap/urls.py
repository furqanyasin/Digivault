from django.urls import path

from apps.heatmap.views import (
    HeatmapCellListView,
    HeatmapIngestView,
    HeatmapPageListView,
    HeatmapSiteSummaryView,
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
]
