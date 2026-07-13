from django.urls import path

from apps.heatmaps.views import HeatmapEventListCreateView

urlpatterns = [
    path("heatmaps/events/", HeatmapEventListCreateView.as_view(), name="heatmap-events"),
]
