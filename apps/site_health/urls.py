from django.urls import path

from apps.site_health.views import (
    PhpErrorIngestView,
    WebsitePhpErrorListView,
    WebsiteSecurityScanView,
    WebsiteSeoView,
    WebsiteSiteEventCreateView,
    WebsiteSiteEventListView,
    WebsiteVulnerabilityListView,
)

urlpatterns = [
    # Public ingest — no JWT
    path("php-errors/", PhpErrorIngestView.as_view(), name="php-error-ingest"),
]

website_urlpatterns = [
    path("php-errors/", WebsitePhpErrorListView.as_view(), name="website-php-errors"),
    path("events/", WebsiteSiteEventListView.as_view(), name="website-events-list"),
    path("events/create/", WebsiteSiteEventCreateView.as_view(), name="website-events-create"),
    path("vulnerabilities/", WebsiteVulnerabilityListView.as_view(), name="website-vulnerabilities"),
    path("scan/", WebsiteSecurityScanView.as_view(), name="website-scan"),
    path("seo/", WebsiteSeoView.as_view(), name="website-seo"),
]
