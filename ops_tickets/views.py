from django.contrib.auth.models import User
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from api.views import HasRolePermission

from .models import SystemOpsTicket
from .serializers import (
    SystemOpsTicketCreateSerializer,
    SystemOpsTicketSerializer,
    SystemOpsTicketUpdateSerializer,
)


def _serialize_ticket(t: SystemOpsTicket) -> dict:
    return SystemOpsTicketSerializer(t).data


@api_view(["GET", "POST"])
@permission_classes([HasRolePermission])
def ticket_collection(request):
    if request.method == "GET":
        qs = SystemOpsTicket.objects.select_related("created_by", "assigned_to").all()[:200]
        return Response({"items": [_serialize_ticket(t) for t in qs]})

    ser = SystemOpsTicketCreateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    data = ser.validated_data
    ticket = SystemOpsTicket.objects.create(
        title=data["title"],
        description=data.get("description") or "",
        inspection_report_id=data["inspection_report_id"],
        inspection_snapshot=data.get("inspection_snapshot") or {},
        severity=data.get("severity") or SystemOpsTicket.SEVERITY_MEDIUM,
        created_by=request.user if request.user.is_authenticated else None,
    )
    return Response(_serialize_ticket(ticket), status=201)


@api_view(["GET", "PATCH"])
@permission_classes([HasRolePermission])
def ticket_detail(request, pk: int):
    ticket = SystemOpsTicket.objects.select_related("created_by", "assigned_to").filter(pk=pk).first()
    if not ticket:
        return Response({"error": "not found"}, status=404)

    if request.method == "GET":
        return Response(_serialize_ticket(ticket))

    ser = SystemOpsTicketUpdateSerializer(data=request.data, partial=True)
    ser.is_valid(raise_exception=True)
    data = ser.validated_data
    if "status" in data:
        ticket.status = data["status"]
    if "severity" in data:
        ticket.severity = data["severity"]
    if "resolution_notes" in data:
        ticket.resolution_notes = data["resolution_notes"]
    if "assigned_to" in data:
        uid = data["assigned_to"]
        ticket.assigned_to = User.objects.filter(pk=uid).first() if uid else None
    ticket.save()
    return Response(_serialize_ticket(ticket))
