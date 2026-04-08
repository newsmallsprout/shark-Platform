import uuid

from django.db import models
class LogStream(models.Model):
    """逻辑日志流：按 stream_key 区分域名/环境/文件来源（边缘推送时携带）。"""

    stream_key = models.CharField(max_length=128, unique=True, db_index=True)
    display_name = models.CharField(max_length=256, blank=True, default="")
    notes = models.TextField(blank=True, default="", help_text="运维备注，可选")
    last_event_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_event_at", "stream_key"]

    def __str__(self):
        return self.stream_key


class LogEvent(models.Model):
    """单条解析后的访问/代理事件（轻量字段 + 可选原始行尾部）。"""

    stream_key = models.CharField(max_length=128, db_index=True)
    event_time = models.DateTimeField(db_index=True)
    host = models.CharField(max_length=255, blank=True, default="")
    method = models.CharField(max_length=16, blank=True, default="")
    path = models.TextField(blank=True, default="")
    status_code = models.PositiveSmallIntegerField(default=0)
    bytes_sent = models.PositiveIntegerField(default=0)
    request_time = models.FloatField(
        null=True,
        blank=True,
        help_text="请求耗时（秒），来自 $request_time",
    )
    upstream_time = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="上游耗时原始串，可能含多值",
    )
    parser = models.CharField(max_length=32, blank=True, default="")
    raw_excerpt = models.CharField(max_length=512, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-event_time"]
        indexes = [
            models.Index(fields=["stream_key", "event_time"]),
            models.Index(fields=["stream_key", "status_code", "event_time"]),
        ]


class LogInsight(models.Model):
    """规则引擎或 LLM 产生的洞察，便于大屏与工单联动（可扩展 insight_type）。"""

    SEVERITY_INFO = "info"
    SEVERITY_WARN = "warning"
    SEVERITY_CRITICAL = "critical"
    SEVERITY_CHOICES = [
        (SEVERITY_INFO, "Info"),
        (SEVERITY_WARN, "Warning"),
        (SEVERITY_CRITICAL, "Critical"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stream_key = models.CharField(max_length=128, db_index=True)
    insight_type = models.CharField(max_length=64, db_index=True)
    severity = models.CharField(
        max_length=16, choices=SEVERITY_CHOICES, default=SEVERITY_WARN
    )
    title = models.CharField(max_length=512)
    body = models.TextField(blank=True, default="")
    evidence = models.JSONField(default=dict, blank=True)
    window_start = models.DateTimeField(null=True, blank=True)
    window_end = models.DateTimeField(null=True, blank=True)
    source = models.CharField(
        max_length=32,
        default="detector",
        help_text="detector | llm | manual",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["stream_key", "-created_at"]),
        ]
