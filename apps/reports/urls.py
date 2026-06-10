from django.urls import path

from apps.reports.views import (
    ReportDeleteView,
    ReportDownloadView,
    ReportGenerateView,
    ReportListCreateView,
)

urlpatterns = [
    path("reports/", ReportListCreateView.as_view(), name="report-list"),
    path("reports/generate/", ReportGenerateView.as_view(), name="report-generate"),
    path("reports/<uuid:pk>/download/", ReportDownloadView.as_view(), name="report-download"),
    path("reports/<uuid:pk>/", ReportDeleteView.as_view(), name="report-delete"),
]
