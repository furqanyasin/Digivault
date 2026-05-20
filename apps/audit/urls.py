from django.urls import path

from apps.audit.views import ActivityLogListView

urlpatterns = [
    path("logs/", ActivityLogListView.as_view(), name="activity-logs"),
]
