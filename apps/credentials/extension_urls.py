from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.credentials.views import (
    ExtensionCredentialLookupView,
    ExtensionCredentialSaveView,
    WebHandoffView,
    WebHandoffExchangeView,
)

urlpatterns = [
    path("token/", TokenObtainPairView.as_view(), name="extension-token"),
    path("token/refresh/", TokenRefreshView.as_view(), name="extension-token-refresh"),
    path("credentials/", ExtensionCredentialLookupView.as_view(), name="extension-credentials"),
    path("credentials/save/", ExtensionCredentialSaveView.as_view(), name="extension-credentials-save"),
    path("web-handoff/", WebHandoffView.as_view(), name="extension-web-handoff"),
    path("exchange/", WebHandoffExchangeView.as_view(), name="extension-exchange"),
]
