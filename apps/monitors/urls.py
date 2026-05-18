from django.urls import path

from apps.monitors import views

urlpatterns = [
    path("monitors/", views.MonitorListCreateView.as_view(), name="monitor-list"),
    path("monitors/<uuid:pk>/", views.MonitorDetailView.as_view(), name="monitor-detail"),
    path("monitors/<uuid:monitor_pk>/checks/", views.MonitorCheckListView.as_view(), name="monitor-checks"),
    path("monitors/<uuid:pk>/pause/", views.MonitorPauseView.as_view(), name="monitor-pause"),
    path("monitors/<uuid:pk>/resume/", views.MonitorResumeView.as_view(), name="monitor-resume"),
    path("monitors/<uuid:pk>/check-now/", views.MonitorCheckNowView.as_view(), name="monitor-check-now"),
    # Notification channels
    path("notification-channels/", views.NotificationChannelListCreateView.as_view(), name="notification-channel-list"),
    path("notification-channels/<uuid:pk>/", views.NotificationChannelDetailView.as_view(), name="notification-channel-detail"),
    # Per-monitor notification rules
    path("monitors/<uuid:monitor_pk>/notification-rules/", views.MonitorNotificationRuleListCreateView.as_view(), name="monitor-notification-rules"),
    path("monitors/<uuid:monitor_pk>/notification-rules/<uuid:pk>/", views.MonitorNotificationRuleDetailView.as_view(), name="monitor-notification-rule-detail"),
]
