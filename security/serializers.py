# ============================================================
# security/serializers.py — DRF 序列化器 (pentest Pydantic → DRF)
# 响应字段名与 pentest 前端契约保持一致
# ============================================================

from rest_framework import serializers

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


class SecurityTaskSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = SecurityTask
        fields = (
            "id", "title", "platform", "platform_task_id", "mode", "status",
            "target", "scope", "progress", "vuln_count", "tags", "notes",
            "user_id", "created_at", "updated_at", "completed_at",
        )
        read_only_fields = ("id", "created_at", "updated_at", "completed_at")


class ScanToolSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScanTool
        fields = (
            "id", "name", "command", "status", "start_time", "end_time",
            "finding_count", "created_at",
        )
        read_only_fields = ("id", "created_at")


class AssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Asset
        fields = (
            "id", "type", "value", "port", "service", "version", "extra", "created_at",
        )
        read_only_fields = ("id", "created_at")


class ScanSessionSerializer(serializers.ModelSerializer):
    task_id = serializers.UUIDField(read_only=True)
    tools = ScanToolSerializer(many=True, read_only=True)
    assets = AssetSerializer(many=True, read_only=True)

    class Meta:
        model = ScanSession
        fields = (
            "id", "task_id", "current_stage", "start_time", "end_time",
            "tools", "assets", "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class VulnerabilitySerializer(serializers.ModelSerializer):
    task_id = serializers.UUIDField(read_only=True)
    session_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Vulnerability
        fields = (
            "id", "task_id", "session_id", "title", "severity", "type", "target",
            "endpoint", "method", "description", "proof", "steps", "impact",
            "recommendation", "cve", "cvss_score", "references", "tags",
            "status", "found_by", "found_at", "created_at", "updated_at",
        )
        read_only_fields = ("id", "found_at", "created_at", "updated_at")


class SecurityReportSerializer(serializers.ModelSerializer):
    task_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = SecurityReport
        fields = (
            "id", "task_id", "title", "status", "severity", "summary", "content",
            "edited_content", "target_info", "vuln_summary", "vuln_count",
            "platform_report_id", "platform_feedback", "score", "reward",
            "submitted_at", "created_at", "updated_at",
        )
        read_only_fields = ("id", "submitted_at", "created_at", "updated_at")


class KnowledgeDocSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeDoc
        fields = ("id", "title", "source", "tags", "url", "vector_id", "created_at")
        read_only_fields = ("id", "created_at")


class ChatMessageSerializer(serializers.ModelSerializer):
    session_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = ChatMessage
        fields = ("id", "session_id", "role", "type", "content", "command", "timestamp")
        read_only_fields = ("id", "timestamp")


class GuidedSessionSerializer(serializers.ModelSerializer):
    task_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = GuidedSession
        fields = ("id", "task_id", "current_stage", "is_completed", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")
