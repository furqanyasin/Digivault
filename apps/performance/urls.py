from django.urls import path

from apps.performance import views

urlpatterns = [
    path("websites/<uuid:website_pk>/performance/", views.WebsitePerformanceListView.as_view(), name="website-performance-list"),
    path("websites/<uuid:website_pk>/performance/run/", views.WebsitePerformanceRunView.as_view(), name="website-performance-run"),
    path("websites/<uuid:website_pk>/performance/trends/", views.WebsitePerformanceTrendView.as_view(), name="website-performance-trends"),
    path("websites/<uuid:website_pk>/crux/", views.WebsiteCruxListView.as_view(), name="website-crux-list"),
    path("websites/<uuid:website_pk>/crux/run/", views.WebsiteCruxRunView.as_view(), name="website-crux-run"),
]
