from django.contrib import admin

from .models import (
    SecurityTask,
    ScanSession,
    ScanTool,
    Asset,
    Vulnerability,
    SecurityReport,
    KnowledgeDoc,
    GuidedSession,
    ChatMessage,
)


@admin.register(SecurityTask)
class SecurityTaskAdmin(admin.ModelAdmin):
    list_display = ("title", "platform", "mode", "status", "target", "progress", "user", "created_at")
    list_filter = ("platform", "mode", "status")
    search_fields = ("title", "target")


@admin.register(ScanSession)
class ScanSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "current_stage", "start_time", "end_time")
    list_filter = ("current_stage",)


@admin.register(ScanTool)
class ScanToolAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "name", "status", "finding_count")
    list_filter = ("name", "status")


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "type", "value", "port", "service")
    list_filter = ("type",)


@admin.register(Vulnerability)
class VulnerabilityAdmin(admin.ModelAdmin):
    list_display = ("title", "severity", "type", "target", "status", "found_by", "found_at")
    list_filter = ("severity", "type", "status")
    search_fields = ("title", "target", "cve")


@admin.register(SecurityReport)
class SecurityReportAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "severity", "task", "score", "reward")
    list_filter = ("status", "severity")


@admin.register(KnowledgeDoc)
class KnowledgeDocAdmin(admin.ModelAdmin):
    list_display = ("title", "source", "created_at")
    list_filter = ("source",)
    search_fields = ("title", "content")


@admin.register(GuidedSession)
class GuidedSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "current_stage", "is_completed")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "role", "type", "timestamp")
    list_filter = ("role", "type")
