import uuid

from django.conf import settings
from django.db import models


class Incident(models.Model):
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('analyzing', 'Analyzing'),
        ('awaiting_evidence', 'Awaiting user evidence'),
        ('analyzed', 'Analyzed'),
        ('resolved', 'Resolved'),
    ]

    SEVERITY_CHOICES = [
        ('critical', 'Critical'),
        ('warning', 'Warning'),
        ('info', 'Info'),
    ]

    alert_name = models.CharField(max_length=255)
    severity = models.CharField(max_length=50, choices=SEVERITY_CHOICES)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='open')
    started_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    description = models.TextField()
    raw_alert_data = models.JSONField(help_text="Raw payload from Prometheus")
    
    # Deduplication & Throttling
    fingerprint = models.CharField(max_length=255, db_index=True, help_text="Unique hash of the alert labels", default='')
    occurrence_count = models.IntegerField(default=1)
    last_analyzed_at = models.DateTimeField(null=True, blank=True)
    last_received_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="最近一次 Alertmanager 推送 firing 的时间（用于列表排序，与 created_at 解耦）",
    )

    evidence_checklist = models.JSONField(
        default=list,
        help_text="Suggested commands and hints; operators paste outputs in UI.",
    )
    user_evidence = models.JSONField(
        default=dict,
        help_text="Map step_id -> pasted command output from operator.",
    )
    prefetched_metrics = models.JSONField(
        default=dict,
        help_text="Legacy: optional Prometheus snapshot; agent may leave empty.",
    )
    agent_trace = models.JSONField(
        default=list,
        help_text="SRE Agent iterations, tool calls and observations for UI/debug.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.alert_name} ({self.status})"

class AnalysisReport(models.Model):
    incident = models.OneToOneField(Incident, on_delete=models.CASCADE, related_name='report')
    
    # AI Analysis Sections
    phenomenon = models.TextField(help_text="What happened?", default="")
    root_cause = models.TextField(help_text="Why it happened? Which process/pod?", default="")
    mitigation = models.TextField(help_text="Immediate actions to fix", default="")
    prevention = models.TextField(help_text="Long term prevention", default="")
    refactoring = models.TextField(help_text="Architectural improvements", default="")
    platform_linkage = models.TextField(
        help_text="与监控/发布/容量等平台动作的联动建议",
        default="",
    )

    # Data
    solutions = models.JSONField(help_text="List of actionable steps", default=list)
    related_metrics = models.JSONField(help_text="Metrics data for visualization", default=dict)
    diagnosis_logs = models.JSONField(help_text="Logs from diagnostic commands", default=list)
    k8s_events = models.JSONField(help_text="K8s Events for frontend display", default=list)
    k8s_pod_status = models.JSONField(help_text="Pod status and conditions", default=dict)
    
    raw_ai_response = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Report for {self.incident.alert_name}"

class AIConfig(models.Model):
    PROVIDER_CHOICES = [
        ('openai', 'OpenAI'),
        ('deepseek', 'DeepSeek'),
        ('custom', 'Custom'),
    ]

    provider = models.CharField(max_length=50, choices=PROVIDER_CHOICES, default='openai')
    api_base = models.CharField(max_length=255, default='https://api.openai.com/v1', help_text="API Base URL")
    api_key = models.CharField(max_length=255, help_text="API Key", blank=True)
    model = models.CharField(max_length=100, default='gpt-3.5-turbo')
    max_tokens = models.IntegerField(default=2000)
    temperature = models.FloatField(default=0.7)
    
    # Prompt Template (legacy single-shot; used when evidence_first_workflow is False)
    prompt_template = models.TextField(default="""
你是一个Kubernetes和系统运维专家。请分析以下告警并以JSON格式输出分析报告。
请严格使用中文回答。

告警信息: {alert_name}
原始数据: {raw_data}
相关指标: {metrics}
诊断日志: {logs}

请按照以下步骤思考并输出JSON:
1. phenomenon: 用一句话描述发生了什么故障现象。
2. root_cause: 根本原因是什么？具体是哪个进程(PID)或Pod导致的？
3. mitigation: 现在的紧急处理措施是什么？(如 kill 进程, 限流等)
4. prevention: 未来如何防止复发？(配置修改, 资源限制等)
5. refactoring: 架构层面如何优化？
6. solutions: 一个包含具体可执行命令的字符串列表(list of strings)。

输出格式要求:
{
    "phenomenon": "...",
    "root_cause": "...",
    "mitigation": "...",
    "prevention": "...",
    "refactoring": "...",
    "solutions": ["cmd1", "cmd2"]
}
""")

    final_prompt_template = models.TextField(
        blank=True,
        default="",
        help_text="User pasted evidence pass; placeholders: {alert_name},{raw_data},{metrics},{logs},{evidence_checklist},{user_evidence}",
    )

    is_active = models.BooleanField(default=True)
    enable_ai_analysis = models.BooleanField(default=True, help_text="Switch to enable/disable AI analysis. If disabled, uses Prometheus metrics only.")
    evidence_first_workflow = models.BooleanField(
        default=False,
        help_text="Deprecated: kept for DB compatibility; agent flow ignores this.",
    )
    max_agent_iterations = models.IntegerField(
        default=12,
        help_text="Max ReAct LLM rounds per incident (cap 24).",
    )
    max_tool_calls_per_incident = models.IntegerField(
        default=36,
        help_text="Max tool invocations per incident (cap 80).",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.provider} - {self.model}"

    @classmethod
    def get_active_config(cls):
        return cls.objects.filter(is_active=True).first() or cls.objects.create()


class Ticket(models.Model):
    """
    Phase 1 智能工单：承载 AI 诊断结论与拟执行脚本；写操作须经人工审批后由执行器消费。
    业务主键为 ``ticket_id``（UUID），便于对外 API 与 SSE 载荷对齐。
    """

    STATUS_DRAFT = "draft"
    STATUS_PENDING_APPROVAL = "pending_approval"
    STATUS_APPROVED = "approved"
    STATUS_EXECUTED = "executed"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PENDING_APPROVAL, "Pending Approval"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_EXECUTED, "Executed"),
        (STATUS_REJECTED, "Rejected"),
    ]

    ticket_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    incident = models.ForeignKey(
        Incident,
        on_delete=models.CASCADE,
        related_name="tickets",
        db_index=True,
    )
    run_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="LangGraph / Celery 运行实例，对应 SSE 频道 agent:run:{run_id}",
    )
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)

    summary = models.TextField(help_text="故障总结（面向审批人）", default="")
    root_cause = models.TextField(help_text="根因分析", default="")
    proposed_action = models.TextField(
        help_text="修复方案：可执行 shell / kubectl / API 调用说明等（仅建议，未经批准不得执行）",
        default="",
    )

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_tickets",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_comment = models.TextField(blank=True, default="")

    execution_result = models.JSONField(default=dict, blank=True)
    execution_error = models.TextField(blank=True, default="")
    executed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]

    def __str__(self):
        return f"Ticket {self.ticket_id} ({self.status})"

