from django.urls import path

from apps.common.public_tools import DomainExpiryView, ScriptScanView, SslCheckView, UptimeCheckView

urlpatterns = [
    path("ssl/", SslCheckView.as_view(), name="public-tool-ssl"),
    path("domain/", DomainExpiryView.as_view(), name="public-tool-domain"),
    path("uptime/", UptimeCheckView.as_view(), name="public-tool-uptime"),
    path("scripts/", ScriptScanView.as_view(), name="public-tool-scripts"),
]
