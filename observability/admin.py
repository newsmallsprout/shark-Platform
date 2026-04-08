from django.contrib import admin

from .models import LogEvent, LogInsight, LogStream


@admin.register(LogStream)
class LogStreamAdmin(admin.ModelAdmin):
    list_display = ("stream_key", "display_name", "last_event_at", "updated_at")
    search_fields = ("stream_key", "display_name")


@admin.register(LogEvent)
class LogEventAdmin(admin.ModelAdmin):
    list_display = ("stream_key", "event_time", "host", "method", "status_code", "request_time")
    list_filter = ("stream_key", "status_code")
    search_fields = ("path", "host")
    date_hierarchy = "event_time"


@admin.register(LogInsight)
class LogInsightAdmin(admin.ModelAdmin):
    list_display = ("title", "stream_key", "insight_type", "severity", "source", "created_at")
    list_filter = ("severity", "insight_type", "source")
