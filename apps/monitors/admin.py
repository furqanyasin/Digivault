from django.contrib import admin

from apps.monitors.models import Monitor, MonitorCheck


@admin.register(Monitor)
class MonitorAdmin(admin.ModelAdmin):
    list_display = ("name", "monitor_type", "url", "status", "team", "last_checked_at", "uptime_24h")
    list_filter = ("monitor_type", "status", "is_active")
    search_fields = ("name", "url")
    readonly_fields = ("status", "last_checked_at", "last_response_time", "uptime_24h", "uptime_7d", "uptime_30d")


@admin.register(MonitorCheck)
class MonitorCheckAdmin(admin.ModelAdmin):
    list_display = ("monitor", "status", "response_time_ms", "status_code", "checked_at")
    list_filter = ("status",)
    readonly_fields = ("checked_at",)
