from django.urls import path

from apps.reports.views import (
    ReportDownloadView,
    ReportGenerateView,
    ReportListCreateView,
)

urlpatterns = [
    path("reports/", ReportListCreateView.as_view(), name="report-list"),
    path("reports/generate/", ReportGenerateView.as_view(), name="report-generate"),
    path("reports/<uuid:pk>/download/", ReportDownloadView.as_view(), name="report-download"),
]
