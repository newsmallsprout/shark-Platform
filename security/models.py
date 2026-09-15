# ============================================================
# security/models.py — pentest 后端模型 (SQLAlchemy → Django ORM)
# 原 pentest 的 Task/ScanSession/ScanTool/Asset/Vulnerability/
#   Report/KnowledgeDoc/GuidedSession/ChatMessage 平移到 Django
# 字段命名/状态枚举/默认值以 pentest 为准（冲突时 pentest 优先）
# 表名加 security_ 前缀避免与 shark 的 tasks.SyncTask 冲突
# ============================================================

import uuid

from django.conf import settings
from django.db import models


class TimeStampedMixin(models.Model):
    """pentest BaseModel 的 created_at / updated_at 公共字段"""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


def _vuln_count_default() -> dict:
    return {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}


class SecurityTask(TimeStampedMixin):
    """渗透测试任务 (pentest Task)"""

    class Meta:
        db_table = "security_tasks"
        ordering = ["-created_at"]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 基本信息
    title = models.CharField(max_length=200)
    platform = models.CharField(max_length=20, default="custom")  # butian/vulbox/custom
    platform_task_id = models.CharField(max_length=100, null=True, blank=True)
    mode = models.CharField(max_length=20, default="auto")  # auto/guided
    status = models.CharField(max_length=20, default="pending")
    # pending/running/analyzing/completed/failed/cancelled

    # 目标与范围
    target = models.CharField(max_length=500)
    scope = models.JSONField(default=dict)

    # 进度与统计
    progress = models.IntegerField(default=0)
    vuln_count = models.JSONField(default=_vuln_count_default)

    # 元数据
    tags = models.JSONField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # 关联
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="security_tasks"
    )

    def __repr__(self):
        return f"<SecurityTask(id={self.id}, title={self.title}, status={self.status})>"


class ScanSession(TimeStampedMixin):
    """扫描会话 — 每个扫描任务对应一个 session"""

    class Meta:
        db_table = "scan_sessions"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.OneToOneField(
        SecurityTask, on_delete=models.CASCADE, related_name="scan_session"
    )
    current_stage = models.CharField(max_length=30, default="init")
    # init/recon/discovery/vuln_scan/exploit/post_exploit/reporting
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)


class ScanTool(TimeStampedMixin):
    """单个扫描工具的运行记录"""

    class Meta:
        db_table = "scan_tools"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(ScanSession, on_delete=models.CASCADE, related_name="tools")
    name = models.CharField(max_length=50)  # nmap/nuclei/subfinder/httpx
    command = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, default="pending")
    # pending/running/completed/failed/timeout
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    output_lines = models.JSONField(null=True, blank=True, default=list)
    finding_count = models.IntegerField(default=0)


class Asset(TimeStampedMixin):
    """扫描发现的资产"""

    class Meta:
        db_table = "assets"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(ScanSession, on_delete=models.CASCADE, related_name="assets")
    type = models.CharField(max_length=30)  # ip/domain/subdomain/url/port/service/certificate
    value = models.CharField(max_length=500)
    port = models.IntegerField(null=True, blank=True)
    service = models.CharField(max_length=100, null=True, blank=True)
    version = models.CharField(max_length=100, null=True, blank=True)
    extra = models.JSONField(null=True, blank=True, default=dict)


class Vulnerability(TimeStampedMixin):
    """漏洞"""

    class Meta:
        db_table = "vulnerabilities"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(
        SecurityTask, on_delete=models.CASCADE, related_name="vulnerabilities"
    )
    session = models.ForeignKey(
        ScanSession, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="vulnerabilities",
    )

    title = models.CharField(max_length=300)
    severity = models.CharField(max_length=20)  # critical/high/medium/low/info
    type = models.CharField(max_length=50)  # sql_injection/xss/rce/ssrf...
    target = models.CharField(max_length=500)
    endpoint = models.CharField(max_length=500, null=True, blank=True)
    method = models.CharField(max_length=10, null=True, blank=True)  # GET/POST/...

    description = models.TextField()
    proof = models.TextField(null=True, blank=True)
    steps = models.JSONField(null=True, blank=True, default=list)

    impact = models.TextField(null=True, blank=True)
    recommendation = models.TextField(default="")

    cve = models.CharField(max_length=20, null=True, blank=True)
    cvss_score = models.FloatField(null=True, blank=True)
    references = models.JSONField(null=True, blank=True, default=list)
    tags = models.JSONField(null=True, blank=True)

    status = models.CharField(max_length=20, default="new")
    # new/confirmed/false_positive/duplicate/accepted/fixed
    found_by = models.CharField(max_length=50)  # 工具名或 "AI"
    found_at = models.DateTimeField()

    def __repr__(self):
        return f"<Vulnerability(id={self.id}, title={self.title}, severity={self.severity})>"


class SecurityReport(TimeStampedMixin):
    """渗透测试报告 (pentest Report)"""

    class Meta:
        db_table = "security_reports"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.OneToOneField(
        SecurityTask, on_delete=models.CASCADE, related_name="report"
    )

    title = models.CharField(max_length=300)
    status = models.CharField(max_length=20, default="draft")
    # draft/reviewed/finalized/submitted/accepted/rejected
    severity = models.CharField(max_length=20, default="info")

    summary = models.TextField(null=True, blank=True)
    content = models.TextField(null=True, blank=True)
    edited_content = models.TextField(null=True, blank=True)
    target_info = models.JSONField(null=True, blank=True, default=dict)
    vuln_summary = models.JSONField(null=True, blank=True, default=dict)
    vuln_count = models.JSONField(default=_vuln_count_default)

    platform_report_id = models.CharField(max_length=200, null=True, blank=True)
    platform_feedback = models.TextField(null=True, blank=True)
    score = models.FloatField(null=True, blank=True)
    reward = models.FloatField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)


class KnowledgeDoc(TimeStampedMixin):
    """知识库文档 — 文本在 DB，向量在 Qdrant(待定 pgvector)"""

    class Meta:
        db_table = "knowledge_docs"
        ordering = ["-created_at"]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=300)
    source = models.CharField(max_length=50)  # hacktricks/hackerone/cve/custom
    content = models.TextField()
    content_hash = models.CharField(max_length=64, null=True, blank=True)
    tags = models.JSONField(null=True, blank=True)
    vector_id = models.CharField(max_length=100, null=True, blank=True)
    url = models.CharField(max_length=1000, null=True, blank=True)

    def __repr__(self):
        return f"<KnowledgeDoc(id={self.id}, title={self.title})>"


class GuidedSession(TimeStampedMixin):
    """引导模式会话"""

    class Meta:
        db_table = "guided_sessions"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.OneToOneField(
        SecurityTask, on_delete=models.CASCADE, related_name="guided_session"
    )
    current_stage = models.CharField(max_length=30, default="recon")
    # briefing/recon/enumeration/vuln_analysis/exploit/post_exploit/summary
    is_completed = models.BooleanField(default=False)


class ChatMessage(TimeStampedMixin):
    """引导模式对话消息"""

    class Meta:
        db_table = "chat_messages"
        ordering = ["timestamp"]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        GuidedSession, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=20)  # system/user/assistant/tool
    type = models.CharField(max_length=20, default="text")  # text/command/result/stage_change
    content = models.TextField(null=True, blank=True)
    command = models.JSONField(null=True, blank=True)
    timestamp = models.DateTimeField()

    def __repr__(self):
        return f"<ChatMessage(id={self.id}, role={self.role}, type={self.type})>"
