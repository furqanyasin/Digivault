from django.urls import path

from apps.monitors import views

urlpatterns = [
    # Public: the page our user-agent's +URL points at, so a site owner can
    # allowlist the monitor without needing a Digivault login.
    path("monitoring-info/", views.MonitoringInfoView.as_view(), name="monitoring-info"),
    path("monitors/", views.MonitorListCreateView.as_view(), name="monitor-list"),
    # Before the <uuid:pk> route so "uptime-trend" isn't parsed as an id.
    path("monitors/uptime-trend/", views.UptimeTrendView.as_view(), name="monitor-uptime-trend"),
    path("monitors/blocked-summary/", views.BlockedMonitorSummaryView.as_view(), name="monitor-blocked-summary"),
    path("monitors/<uuid:pk>/", views.MonitorDetailView.as_view(), name="monitor-detail"),
    path("monitors/<uuid:monitor_pk>/checks/", views.MonitorCheckListView.as_view(), name="monitor-checks"),
    path("monitors/<uuid:pk>/pause/", views.MonitorPauseView.as_view(), name="monitor-pause"),
    path("monitors/<uuid:pk>/resume/", views.MonitorResumeView.as_view(), name="monitor-resume"),
    path("monitors/<uuid:pk>/check-now/", views.MonitorCheckNowView.as_view(), name="monitor-check-now"),
    # Notification channels
    path("notification-channels/", views.NotificationChannelListCreateView.as_view(), name="notification-channel-list"),
    path("notification-channels/<uuid:pk>/", views.NotificationChannelDetailView.as_view(), name="notification-channel-detail"),
    path("notification-channels/<uuid:pk>/test/", views.NotificationChannelTestView.as_view(), name="notification-channel-test"),
    path("notification-channels/<uuid:pk>/apply-to-all-websites/", views.NotificationChannelApplyAllView.as_view(), name="notification-channel-apply-all"),
    # Per-monitor notification rules
    path("monitors/<uuid:monitor_pk>/notification-rules/", views.MonitorNotificationRuleListCreateView.as_view(), name="monitor-notification-rules"),
    path("monitors/<uuid:monitor_pk>/notification-rules/<uuid:pk>/", views.MonitorNotificationRuleDetailView.as_view(), name="monitor-notification-rule-detail"),
]
