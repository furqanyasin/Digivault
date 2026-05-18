from django.urls import path

from apps.clients.views import (
    ClientActivateView,
    ClientDeactivateView,
    ClientDetailView,
    ClientImportView,
    ClientListCreateView,
    ClientSearchView,
    ClientSyncAllView,
    ClientSyncClickUpView,
)

urlpatterns = [
    path("", ClientListCreateView.as_view(), name="client-list-create"),
    path("search/", ClientSearchView.as_view(), name="client-search"),
    path("import/", ClientImportView.as_view(), name="client-import"),
    path("sync-all/", ClientSyncAllView.as_view(), name="client-sync-all"),
    path("<uuid:pk>/", ClientDetailView.as_view(), name="client-detail"),
    path("<uuid:pk>/activate/", ClientActivateView.as_view(), name="client-activate"),
    path("<uuid:pk>/deactivate/", ClientDeactivateView.as_view(), name="client-deactivate"),
    path("<uuid:pk>/sync/", ClientSyncClickUpView.as_view(), name="client-sync"),
]
