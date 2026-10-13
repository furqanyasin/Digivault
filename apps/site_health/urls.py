from django.urls import path

from apps.site_health.views import (
    PhpErrorIngestView,
    WebsitePhpErrorListView,
    WebsiteSecurityHeadersView,
    WebsiteSecurityScanView,
    WebsiteSeoView,
    WebsiteTimelineView,
    WebsiteSiteEventCreateView,
    WebsiteSiteEventListView,
    WebsiteVulnerabilityListView,
    WpActivityIngestView,
)

urlpatterns = [
    # Public ingest — no JWT
    path("php-errors/", PhpErrorIngestView.as_view(), name="php-error-ingest"),
    path("wp-activity/", WpActivityIngestView.as_view(), name="wp-activity-ingest"),
]

website_urlpatterns = [
    path("php-errors/", WebsitePhpErrorListView.as_view(), name="website-php-errors"),
    path("events/", WebsiteSiteEventListView.as_view(), name="website-events-list"),
    path("events/create/", WebsiteSiteEventCreateView.as_view(), name="website-events-create"),
    path("vulnerabilities/", WebsiteVulnerabilityListView.as_view(), name="website-vulnerabilities"),
    path("scan/", WebsiteSecurityScanView.as_view(), name="website-scan"),
    path("security-headers/", WebsiteSecurityHeadersView.as_view(), name="website-security-headers"),
    path("seo/", WebsiteSeoView.as_view(), name="website-seo"),
    path("timeline/", WebsiteTimelineView.as_view(), name="website-timeline"),
]
