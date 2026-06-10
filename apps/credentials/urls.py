from django.urls import path

from apps.credentials.views import (
    CredentialAccessLogView,
    CredentialDetailView,
    CredentialListCreateView,
    CredentialRevealView,
    CredentialShareDeleteView,
    CredentialShareListCreateView,
    TeamCredentialListCreateView,
    WebsiteCredentialShareView,
)

urlpatterns = [
    path(
        "credentials/",
        TeamCredentialListCreateView.as_view(),
        name="credential-team-list-create",
    ),
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
    path(
        "websites/<uuid:website_pk>/credentials/share/",
        WebsiteCredentialShareView.as_view(),
        name="website-credential-share",
    ),
    path(
        "credentials/<uuid:pk>/shares/",
        CredentialShareListCreateView.as_view(),
        name="credential-share-list-create",
    ),
    path(
        "credentials/<uuid:pk>/shares/<uuid:user_id>/",
        CredentialShareDeleteView.as_view(),
        name="credential-share-delete",
    ),
]
