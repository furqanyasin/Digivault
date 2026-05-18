from django.urls import path

from apps.status_pages.views import (
    PublicStatusPageView,
    StatusPageDetailView,
    StatusPageListCreateView,
    StatusPageMonitorDetailView,
    StatusPageMonitorListCreateView,
)

urlpatterns = [
    path("status-pages/", StatusPageListCreateView.as_view(), name="status-page-list"),
    path("status-pages/<uuid:pk>/", StatusPageDetailView.as_view(), name="status-page-detail"),
    path("status-pages/<uuid:page_pk>/monitors/", StatusPageMonitorListCreateView.as_view(), name="status-page-monitor-list"),
    path("status-pages/<uuid:page_pk>/monitors/<uuid:pk>/", StatusPageMonitorDetailView.as_view(), name="status-page-monitor-detail"),
    path("public/status/<slug:slug>/", PublicStatusPageView.as_view(), name="public-status-page"),
]
