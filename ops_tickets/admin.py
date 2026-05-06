from django.contrib import admin

from .models import SystemOpsTicket


@admin.register(SystemOpsTicket)
class SystemOpsTicketAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "inspection_report_id", "severity", "status", "created_at")
    list_filter = ("status", "severity")
    search_fields = ("title", "description", "inspection_report_id")
