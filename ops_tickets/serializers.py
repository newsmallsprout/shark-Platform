from django.contrib.auth.models import User
from rest_framework import serializers

from .models import SystemOpsTicket


class SystemOpsTicketSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    assigned_to_username = serializers.CharField(source="assigned_to.username", read_only=True)

    class Meta:
        model = SystemOpsTicket
        fields = [
            "id",
            "title",
            "description",
            "inspection_report_id",
            "inspection_snapshot",
            "severity",
            "status",
            "created_by",
            "created_by_username",
            "assigned_to",
            "assigned_to_username",
            "resolution_notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at", "created_by_username", "assigned_to_username"]


class SystemOpsTicketCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    inspection_report_id = serializers.CharField(max_length=64)
    inspection_snapshot = serializers.JSONField(required=False, default=dict)
    severity = serializers.ChoiceField(
        choices=[c[0] for c in SystemOpsTicket.SEVERITY_CHOICES],
        default=SystemOpsTicket.SEVERITY_MEDIUM,
    )


class SystemOpsTicketUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[c[0] for c in SystemOpsTicket.STATUS_CHOICES], required=False)
    severity = serializers.ChoiceField(
        choices=[c[0] for c in SystemOpsTicket.SEVERITY_CHOICES],
        required=False,
    )
    assigned_to = serializers.IntegerField(required=False, allow_null=True)
    resolution_notes = serializers.CharField(required=False, allow_blank=True)

    def validate_assigned_to(self, value):
        if value is None:
            return None
        if not User.objects.filter(pk=value).exists():
            raise serializers.ValidationError("用户不存在")
        return value
