from django.urls import path

from apps.scripts.views import (
    AcknowledgeChangeView,
    ExtensionLookupView,
    IngestView,
    ScriptReviewView,
    SnippetJsView,
    WebsiteChangeListView,
    WebsiteScriptListView,
)

# Ingest lives outside /api/v1/ so the URL never changes even if the API version bumps
ingest_urlpatterns = [
    path("ingest/", IngestView.as_view(), name="ingest"),
    path("extension/lookup/", ExtensionLookupView.as_view(), name="extension-lookup"),
    path("s.js", SnippetJsView.as_view(), name="snippet-js"),
]

# Versioned script/change endpoints — included under /api/v1/
script_urlpatterns = [
    path(
        "websites/<uuid:website_pk>/scripts/",
        WebsiteScriptListView.as_view(),
        name="website-scripts",
    ),
    path(
        "websites/<uuid:website_pk>/changes/",
        WebsiteChangeListView.as_view(),
        name="website-changes",
    ),
    path(
        "changes/<uuid:pk>/acknowledge/",
        AcknowledgeChangeView.as_view(),
        name="change-acknowledge",
    ),
    path(
        "websites/<uuid:website_pk>/scripts/<uuid:pk>/review/",
        ScriptReviewView.as_view(),
        name="script-review",
    ),
]
