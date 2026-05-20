from django.urls import path

from apps.credentials.views import (
    CredentialAccessLogView,
    CredentialDetailView,
    CredentialListCreateView,
    CredentialRevealView,
    TeamCredentialListCreateView,
)

urlpatterns = [
    # Team-level vault: all credentials (website + standalone)
    path(
        "credentials/",
        TeamCredentialListCreateView.as_view(),
        name="credential-team-list-create",
    ),
    # Website-scoped list (kept for extension lookup)
    path(
        "websites/<uuid:website_pk>/credentials/",
        CredentialListCreateView.as_view(),
        name="credential-list-create",
    ),
    path(
        "credentials/<uuid:pk>/",
        CredentialDetailView.as_view(),
        name="credential-detail",
    ),
    path(
        "credentials/<uuid:pk>/reveal/",
        CredentialRevealView.as_view(),
        name="credential-reveal",
    ),
    path(
        "websites/<uuid:website_pk>/credential-audit/",
        CredentialAccessLogView.as_view(),
        name="credential-audit",
    ),
]
