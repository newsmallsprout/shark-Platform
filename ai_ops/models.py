from django.db import models

class Incident(models.Model):
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('analyzing', 'Analyzing'),
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
    
    # Prompt Template
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

    is_active = models.BooleanField(default=True)
    enable_ai_analysis = models.BooleanField(default=True, help_text="Switch to enable/disable AI analysis. If disabled, uses Prometheus metrics only.")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.provider} - {self.model}"

    @classmethod
    def get_active_config(cls):
        return cls.objects.filter(is_active=True).first() or cls.objects.create()

