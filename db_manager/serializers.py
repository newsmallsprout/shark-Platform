from rest_framework import serializers

from .models import BackupPlan, BackupRecord, DBInstance, RestoreJob, RollbackJob, SQLAIReview, SQLApprovalOrder, SQLApprovalPolicy, SQLExecutionJob, SQLExecutionPolicy


class DBInstanceSerializer(serializers.ModelSerializer):
    username = serializers.CharField(write_only=True, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    can_write = serializers.SerializerMethodField()

    class Meta:
        model = DBInstance
        fields = [
            "id",
            "name",
            "db_type",
            "deployment_mode",
            "environment",
            "host",
            "port",
            "default_database",
            "read_only",
            "owner_team",
            "tags",
            "extra_config",
            "status",
            "last_health_check_at",
            "created_at",
            "updated_at",
            "username",
            "password",
            "can_write",
        ]
        read_only_fields = ["status", "last_health_check_at", "created_at", "updated_at", "can_write"]

    def get_can_write(self, obj):
        return not obj.read_only


class SQLFormatRequestSerializer(serializers.Serializer):
    sql = serializers.CharField()


class SQLExplainRequestSerializer(serializers.Serializer):
    instance_id = serializers.IntegerField()
    database = serializers.CharField(required=False, allow_blank=True)
    sql = serializers.CharField()


class SQLExecuteRequestSerializer(serializers.Serializer):
    instance_id = serializers.IntegerField()
    database = serializers.CharField(required=False, allow_blank=True)
    sql = serializers.CharField()
    execute_mode = serializers.ChoiceField(choices=["auto_commit", "transaction", "explain", "dry_run"], default="auto_commit", required=False)
    ai_review_id = serializers.IntegerField(required=False)
    force_execute = serializers.BooleanField(default=False)
    applicant_user_id = serializers.IntegerField(required=False)


class SQLExecutionJobSerializer(serializers.ModelSerializer):
    instance_name = serializers.CharField(source="instance.name", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = SQLExecutionJob
        fields = [
            "id",
            "instance",
            "instance_name",
            "user",
            "username",
            "database_name",
            "sql_text",
            "sql_hash",
            "sql_type",
            "execute_mode",
            "trace_id",
            "status",
            "risk_level",
            "progress_percent",
            "affected_rows",
            "duration_ms",
            "error_message",
            "execution_context",
            "cancel_requested",
            "pause_requested",
            "started_at",
            "finished_at",
            "created_at",
            "updated_at",
        ]


class SQLAIReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = SQLAIReview
        fields = "__all__"


class SQLApprovalOrderSerializer(serializers.ModelSerializer):
    applicant_name = serializers.CharField(source="applicant.username", read_only=True)

    class Meta:
        model = SQLApprovalOrder
        fields = [
            "id",
            "job",
            "applicant",
            "applicant_name",
            "current_node",
            "status",
            "reason",
            "submitted_at",
            "approved_at",
            "rejected_at",
        ]


class SQLApprovalPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = SQLApprovalPolicy
        fields = "__all__"


class SQLExecutionPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = SQLExecutionPolicy
        fields = "__all__"


class BackupPlanSerializer(serializers.ModelSerializer):
    instance_name = serializers.CharField(source="instance.name", read_only=True)

    class Meta:
        model = BackupPlan
        fields = [
            "id",
            "instance",
            "instance_name",
            "name",
            "backup_type",
            "schedule_expr",
            "retention_days",
            "storage_uri",
            "storage_config",
            "compression_enabled",
            "encryption_enabled",
            "enabled",
            "last_run_at",
            "next_run_at",
            "created_at",
            "updated_at",
        ]


class BackupRecordSerializer(serializers.ModelSerializer):
    instance_name = serializers.CharField(source="instance.name", read_only=True)

    class Meta:
        model = BackupRecord
        fields = "__all__"


class RestoreJobSerializer(serializers.ModelSerializer):
    instance_name = serializers.CharField(source="instance.name", read_only=True)

    class Meta:
        model = RestoreJob
        fields = "__all__"


class RollbackJobSerializer(serializers.ModelSerializer):
    instance_name = serializers.CharField(source="instance.name", read_only=True)

    class Meta:
        model = RollbackJob
        fields = "__all__"
