from django.conf import settings
from django.db import models


class SystemOpsTicket(models.Model):
    """人工处理的系统运维工单，可由巡检报告发起。"""

    STATUS_OPEN = "open"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_RESOLVED = "resolved"
    STATUS_CLOSED = "closed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_OPEN, "待处理"),
        (STATUS_IN_PROGRESS, "处理中"),
        (STATUS_RESOLVED, "已解决"),
        (STATUS_CLOSED, "已关闭"),
        (STATUS_CANCELLED, "已取消"),
    ]

    SEVERITY_LOW = "low"
    SEVERITY_MEDIUM = "medium"
    SEVERITY_HIGH = "high"
    SEVERITY_CRITICAL = "critical"
    SEVERITY_CHOICES = [
        (SEVERITY_LOW, "低"),
        (SEVERITY_MEDIUM, "中"),
        (SEVERITY_HIGH, "高"),
        (SEVERITY_CRITICAL, "紧急"),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    inspection_report_id = models.CharField(max_length=64, db_index=True)
    inspection_snapshot = models.JSONField(default=dict, blank=True)
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, default=SEVERITY_MEDIUM)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_OPEN)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_system_ops_tickets",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_system_ops_tickets",
    )
    resolution_notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"#{self.pk} {self.title}"
