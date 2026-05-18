from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.scripts.urls import ingest_urlpatterns, script_urlpatterns
from apps.websites.urls import urlpatterns as website_urlpatterns

urlpatterns = [
    path("admin/", admin.site.urls),
    # Auth + teams
    path("api/v1/auth/", include("apps.accounts.urls")),
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
    path("api/", include(ingest_urlpatterns)),
    # Dashboard chatbot
    path("api/v1/", include("apps.chat.urls")),
]

if settings.DEBUG and "debug_toolbar" in settings.INSTALLED_APPS:
    import debug_toolbar
    urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
