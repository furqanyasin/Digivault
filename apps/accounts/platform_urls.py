from django.urls import path

from apps.accounts.platform_views import (
    PlatformOverviewView,
    PlatformTeamDetailView,
    PlatformTeamListView,
    PlatformUserDetailView,
    PlatformUserListView,
)

urlpatterns = [
    path("overview/", PlatformOverviewView.as_view(), name="platform-overview"),
    path("teams/", PlatformTeamListView.as_view(), name="platform-teams"),
    path("teams/<uuid:pk>/", PlatformTeamDetailView.as_view(), name="platform-team-detail"),
    path("users/", PlatformUserListView.as_view(), name="platform-users"),
    path("users/<uuid:pk>/", PlatformUserDetailView.as_view(), name="platform-user-detail"),
]
