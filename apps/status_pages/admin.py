from django.contrib import admin

from apps.status_pages.models import StatusPage, StatusPageMonitor


class StatusPageMonitorInline(admin.TabularInline):
    model = StatusPageMonitor
    extra = 0
    raw_id_fields = ("monitor",)


@admin.register(StatusPage)
class StatusPageAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "team", "allow_indexing", "created_at")
    inlines = [StatusPageMonitorInline]
    prepopulated_fields = {"slug": ("name",)}
