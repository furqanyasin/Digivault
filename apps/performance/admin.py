from django.contrib import admin

from apps.performance.models import PerformanceReport


@admin.register(PerformanceReport)
class PerformanceReportAdmin(admin.ModelAdmin):
    list_display = ("website", "strategy", "performance_score", "fcp_ms", "lcp_ms", "checked_at")
    list_filter = ("strategy", "website")
    ordering = ("-checked_at",)
