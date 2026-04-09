from django.contrib import admin

from .models import AgentRun, AIConfig, Incident, KnowledgeEntry, PlaybookJob, Ticket, TopologySnapshot


@admin.register(AgentRun)
class AgentRunAdmin(admin.ModelAdmin):
    list_display = ("run_id", "incident", "source", "status", "ticket", "created_at", "finished_at")
    list_filter = ("source", "status")
    search_fields = ("run_id", "celery_task_id")


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = ("id", "alert_name", "severity", "status", "last_received_at")
    list_filter = ("severity", "status")
    search_fields = ("alert_name", "fingerprint")


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        "ticket_id",
        "incident",
        "status",
        "routing",
        "ticket_class",
        "ai_confidence",
        "updated_at",
    )
    list_filter = ("status", "routing", "ticket_class")
    search_fields = ("summary", "ticket_id")


@admin.register(KnowledgeEntry)
class KnowledgeEntryAdmin(admin.ModelAdmin):
    list_display = ("signature_hash", "title", "hit_count", "success_after_apply", "updated_at")
    search_fields = ("title", "signature_hash")


@admin.register(TopologySnapshot)
class TopologySnapshotAdmin(admin.ModelAdmin):
    list_display = ("scope", "health_score", "updated_at")


@admin.register(PlaybookJob)
class PlaybookJobAdmin(admin.ModelAdmin):
    list_display = ("id", "target_node_id", "status", "ticket", "created_at", "completed_at")
    list_filter = ("status", "target_node_id")


@admin.register(AIConfig)
class AIConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "provider", "model", "enable_ai_analysis")
