"""
Ticket 状态机：与 ``ai_ops.models.Ticket`` 对齐（Draft / Pending Approval / Approved / Executed / Rejected）。
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from ai_ops.models import Ticket

User = get_user_model()


class TicketManager:
    @staticmethod
    @transaction.atomic
    def create_draft(
        *,
        incident_id: int,
        run_id: str,
        summary: str,
        root_cause: str,
        proposed_action: str,
    ) -> Ticket:
        from ai_ops.models import Incident

        inc = Incident.objects.get(pk=incident_id)
        return Ticket.objects.create(
            incident=inc,
            run_id=run_id or "",
            summary=summary,
            root_cause=root_cause,
            proposed_action=proposed_action,
            status=Ticket.STATUS_DRAFT,
        )

    @staticmethod
    @transaction.atomic
    def submit_for_approval(ticket_uuid: UUID) -> Ticket:
        t = Ticket.objects.select_for_update().get(pk=ticket_uuid)
        if t.status != Ticket.STATUS_DRAFT:
            raise ValueError(f"工单 {ticket_uuid} 非 draft，当前={t.status}")
        t.status = Ticket.STATUS_PENDING_APPROVAL
        t.save(update_fields=["status", "updated_at"])
        return t

    @staticmethod
    @transaction.atomic
    def approve(ticket_uuid: UUID, approver: User, comment: str = "") -> Ticket:
        t = Ticket.objects.select_for_update().get(pk=ticket_uuid)
        if t.status != Ticket.STATUS_PENDING_APPROVAL:
            raise ValueError(f"工单 {ticket_uuid} 非待审，当前={t.status}")
        t.status = Ticket.STATUS_APPROVED
        t.approved_by = approver
        t.approved_at = timezone.now()
        t.approval_comment = comment
        t.save(update_fields=["status", "approved_by", "approved_at", "approval_comment", "updated_at"])
        return t

    @staticmethod
    @transaction.atomic
    def reject(ticket_uuid: UUID, approver: User, reason: str) -> Ticket:
        t = Ticket.objects.select_for_update().get(pk=ticket_uuid)
        if t.status != Ticket.STATUS_PENDING_APPROVAL:
            raise ValueError(f"工单 {ticket_uuid} 非待审，当前={t.status}")
        t.status = Ticket.STATUS_REJECTED
        t.approved_by = approver
        t.approved_at = timezone.now()
        t.approval_comment = reason
        t.save(update_fields=["status", "approved_by", "approved_at", "approval_comment", "updated_at"])
        return t

    @staticmethod
    @transaction.atomic
    def mark_executed(ticket_uuid: UUID, *, result: Optional[Dict[str, Any]] = None, error: str = "") -> Ticket:
        """人工批准后由执行器调用：Approved -> Executed。"""
        t = Ticket.objects.select_for_update().get(pk=ticket_uuid)
        if t.status != Ticket.STATUS_APPROVED:
            raise ValueError(f"工单 {ticket_uuid} 未批准，当前={t.status}")
        t.status = Ticket.STATUS_EXECUTED
        t.execution_result = result or {}
        t.execution_error = error
        t.executed_at = timezone.now()
        t.save(
            update_fields=[
                "status",
                "execution_result",
                "execution_error",
                "executed_at",
                "updated_at",
            ]
        )
        return t
