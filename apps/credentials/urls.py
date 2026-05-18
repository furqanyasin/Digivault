from django.urls import path

from apps.credentials.views import (
    CredentialAccessLogView,
    CredentialDetailView,
    CredentialListCreateView,
    CredentialRevealView,
)

urlpatterns = [
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
