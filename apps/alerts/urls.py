from django.urls import path

from apps.alerts.views import (
    AlertRuleDetailView,
    AlertRuleListCreateView,
    AlertSuppressionDeleteView,
    AlertSuppressionListCreateView,
    MarkNotificationsReadView,
    NotificationListView,
)

urlpatterns = [
    path("alert-rules/", AlertRuleListCreateView.as_view(), name="alert-rule-list"),
    path("alert-rules/<uuid:pk>/", AlertRuleDetailView.as_view(), name="alert-rule-detail"),
    path("notifications/", NotificationListView.as_view(), name="notification-list"),
    path(
        "notifications/mark-read/",
        MarkNotificationsReadView.as_view(),
        name="notification-mark-read",
    ),
    path(
        "websites/<uuid:website_pk>/alert-suppressions/",
        AlertSuppressionListCreateView.as_view(),
        name="alert-suppression-list",
    ),
    path(
        "alert-suppressions/<uuid:pk>/",
        AlertSuppressionDeleteView.as_view(),
        name="alert-suppression-delete",
    ),
]
