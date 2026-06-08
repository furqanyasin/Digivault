from django.urls import path

from apps.status_pages.views import (
    MaintenanceWindowDetailView,
    MaintenanceWindowListCreateView,
    PublicStatusPageView,
    StatusPageDetailView,
    StatusPageIncidentDetailView,
    StatusPageIncidentListCreateView,
    StatusPageListCreateView,
    StatusPageMonitorDetailView,
    StatusPageMonitorListCreateView,
)

urlpatterns = [
    path("status-pages/", StatusPageListCreateView.as_view(), name="status-page-list"),
    path("status-pages/<uuid:pk>/", StatusPageDetailView.as_view(), name="status-page-detail"),
    path("status-pages/<uuid:page_pk>/monitors/", StatusPageMonitorListCreateView.as_view(), name="status-page-monitor-list"),
    path("status-pages/<uuid:page_pk>/monitors/<uuid:pk>/", StatusPageMonitorDetailView.as_view(), name="status-page-monitor-detail"),
    path("status-pages/<uuid:page_pk>/incidents/", StatusPageIncidentListCreateView.as_view(), name="status-page-incident-list"),
    path("status-pages/<uuid:page_pk>/incidents/<uuid:pk>/", StatusPageIncidentDetailView.as_view(), name="status-page-incident-detail"),
    path("status-pages/<uuid:page_pk>/maintenance/", MaintenanceWindowListCreateView.as_view(), name="status-page-maintenance-list"),
    path("status-pages/<uuid:page_pk>/maintenance/<uuid:pk>/", MaintenanceWindowDetailView.as_view(), name="status-page-maintenance-detail"),
    path("public/status/<slug:slug>/", PublicStatusPageView.as_view(), name="public-status-page"),
]
