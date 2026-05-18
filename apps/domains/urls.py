from django.urls import path

from apps.domains.views import DomainInfoView

urlpatterns = [
    path(
        "websites/<uuid:website_pk>/domain/",
        DomainInfoView.as_view(),
        name="domain-info",
    ),
    path(
        "websites/<uuid:website_pk>/domain/refresh/",
        DomainInfoView.as_view(),
        name="domain-refresh",
    ),
]
