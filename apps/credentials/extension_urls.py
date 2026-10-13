from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.totp_views import ExtensionTokenObtainPairView

from apps.credentials.views import (
    ExtensionCredentialCheckView,
    ExtensionCredentialLookupView,
    ExtensionCredentialRevealView,
    ExtensionCredentialSaveView,
    CredentialReportBrokenView,
    CredentialTotpView,
    WebHandoffView,
    WebHandoffExchangeView,
)

urlpatterns = [
    path("token/", ExtensionTokenObtainPairView.as_view(), name="extension-token"),
    path("token/refresh/", TokenRefreshView.as_view(), name="extension-token-refresh"),
    path("credentials/", ExtensionCredentialLookupView.as_view(), name="extension-credentials"),
    path(
        "credentials/check/",
        ExtensionCredentialCheckView.as_view(),
        name="extension-credentials-check",
    ),
    path("credentials/save/", ExtensionCredentialSaveView.as_view(), name="extension-credentials-save"),
    path(
        "credentials/<uuid:pk>/reveal/",
        ExtensionCredentialRevealView.as_view(),
        name="extension-credential-reveal",
    ),
    path(
        "credentials/<uuid:pk>/totp/",
        CredentialTotpView.as_view(),
        name="extension-credential-totp",
    ),
    path(
        "credentials/<uuid:pk>/report-broken/",
        CredentialReportBrokenView.as_view(),
        name="extension-credential-report-broken",
    ),
    path("web-handoff/", WebHandoffView.as_view(), name="extension-web-handoff"),
    path("exchange/", WebHandoffExchangeView.as_view(), name="extension-exchange"),
]
