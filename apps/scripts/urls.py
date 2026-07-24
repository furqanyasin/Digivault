from django.urls import path

from apps.scripts.views import (
    AcknowledgeChangeView,
    BulkAcknowledgeChangesView,
    BulkScriptReviewView,
    ExtensionLookupView,
    FormErrorIngestView,
    FormSubmissionIngestView,
    IngestView,
    ScriptReviewView,
    ScriptTimelineView,
    TeamChangeListView,
    TeamFormErrorListView,
    TeamFormListView,
    SnippetJsView,
    WebsiteChangeListView,
    WebsiteFormErrorListView,
    WebsiteFormListView,
    WebsiteScriptListView,
)

# Ingest lives outside /api/v1/ so the URL never changes even if the API version bumps.
# NOTE: production nginx only proxies /api/ingest|api/v1|api/php-errors|api/extension —
# new public endpoints must live under one of those prefixes.
ingest_urlpatterns = [
    path("ingest/", IngestView.as_view(), name="ingest"),
    path("ingest/form-errors/", FormErrorIngestView.as_view(), name="ingest-form-errors"),
    path("ingest/form-submission/", FormSubmissionIngestView.as_view(), name="ingest-form-submission"),
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
        "changes/",
        TeamChangeListView.as_view(),
        name="team-changes",
    ),
    path("forms/", TeamFormListView.as_view(), name="team-forms"),
    path("form-errors/", TeamFormErrorListView.as_view(), name="team-form-errors"),
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
        "changes/bulk-acknowledge/",
        BulkAcknowledgeChangesView.as_view(),
        name="change-bulk-acknowledge",
    ),
    path(
        "websites/<uuid:website_pk>/scripts/bulk-review/",
        BulkScriptReviewView.as_view(),
        name="script-bulk-review",
    ),
    path(
        "websites/<uuid:website_pk>/scripts/<uuid:pk>/review/",
        ScriptReviewView.as_view(),
        name="script-review",
    ),
    path(
        "websites/<uuid:website_pk>/scripts/<uuid:pk>/timeline/",
        ScriptTimelineView.as_view(),
        name="script-timeline",
    ),
    path(
        "websites/<uuid:website_pk>/forms/",
        WebsiteFormListView.as_view(),
        name="website-forms",
    ),
    path(
        "websites/<uuid:website_pk>/form-errors/",
        WebsiteFormErrorListView.as_view(),
        name="website-form-errors",
    ),
]
