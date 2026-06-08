from django.urls import path

from apps.audit.views import ActivityLogExportView, ActivityLogListView

urlpatterns = [
    path("logs/", ActivityLogListView.as_view(), name="activity-logs"),
    path("logs/export/", ActivityLogExportView.as_view(), name="activity-logs-export"),
]
