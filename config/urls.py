from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.common.health import HealthView, ReadyView

from apps.scripts.urls import ingest_urlpatterns, script_urlpatterns
from apps.site_health.urls import urlpatterns as site_health_urlpatterns
from apps.site_health.urls import website_urlpatterns as site_health_website_urlpatterns
from apps.websites.urls import urlpatterns as website_urlpatterns
from apps.heatmap.urls import urlpatterns as heatmap_urlpatterns
from apps.heatmap.urls import ingest_urlpatterns as heatmap_ingest_urlpatterns

urlpatterns = [
    path("admin/", admin.site.urls),
    # Liveness and readiness. Under /api/ because production nginx only proxies
    # /api/... to Django — a health endpoint nginx routes to the Next.js
    # frontend would report the wrong process entirely.
    path("api/health/", HealthView.as_view(), name="health"),
    path("api/ready/", ReadyView.as_view(), name="ready"),
    # Auth + teams
    path("api/v1/auth/", include("apps.accounts.urls")),
    # Platform owner (superuser) view across every workspace
    path("api/v1/platform/", include("apps.accounts.platform_urls")),
    # Free website tools on the marketing site, no login
    path("api/v1/public/tools/", include("apps.common.public_tools_urls")),
    # Websites CRUD
    path("api/v1/", include(website_urlpatterns)),
    # Scripts, changes, acknowledge
    path("api/v1/", include(script_urlpatterns)),
    # Credentials vault
    path("api/v1/", include("apps.credentials.urls")),
    # Extension autofill lookup (authenticated, no plaintext)
    path("api/extension/", include("apps.credentials.extension_urls")),
    # Domain intelligence
    path("api/v1/", include("apps.domains.urls")),
    # Alerts & notifications
    path("api/v1/", include("apps.alerts.urls")),
    # Uptime monitors
    path("api/v1/", include("apps.monitors.urls")),
    # Performance / Web Vitals
    path("api/v1/", include("apps.performance.urls")),
    # Status pages (dashboard + public)
    path("api/v1/", include("apps.status_pages.urls")),
    # Client management (hosting sheet + ClickUp sync)
    path("api/v1/clients/", include("apps.clients.urls")),
    # Ingest — version-free URL; snippet embeds this permanently
    path("api/", include(ingest_urlpatterns + heatmap_ingest_urlpatterns)),
    # Heatmaps (versioned dashboard endpoints)
    path("api/v1/", include(heatmap_urlpatterns)),
    # Dashboard chatbot
    path("api/v1/", include("apps.chat.urls")),
    # Activity audit log
    path("api/v1/", include("apps.audit.urls")),
    # Client reports (PDF/CSV)
    path("api/v1/", include("apps.reports.urls")),
    # Site health — PHP errors ingest (public) + website-scoped endpoints
    path("api/", include(site_health_urlpatterns)),
    path("api/v1/websites/<uuid:website_pk>/", include(site_health_website_urlpatterns)),
]

if settings.DEBUG and "debug_toolbar" in settings.INSTALLED_APPS:
    import debug_toolbar
    urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
