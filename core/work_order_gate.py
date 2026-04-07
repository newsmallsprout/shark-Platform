"""
智能工单闸门（可选）：高危写操作在开启时需携带已批准的 Ticket UUID。

环境变量 ``SHARK_WORK_ORDER_GATE_ENABLED=true`` 时生效；默认关闭，避免破坏现有运维流程。
执行器 / 工单系统在调用写接口时应设置请求头：``X-Shark-Work-Order-Id: <ticket_uuid>``，
且 ``ai_ops.models.Ticket.status == approved``。
"""
from __future__ import annotations

import uuid
from typing import Optional

from django.conf import settings
from rest_framework.response import Response


def enforce_approved_work_order_or_response(request) -> Optional[Response]:
    """
    若闸门关闭或用户为超级管理员（可配置放行），返回 None 表示通过。
    否则校验请求头并 Ticket 状态；失败时返回对应 Response。
    """
    if not getattr(settings, "WORK_ORDER_GATE_ENABLED", False):
        return None
    if getattr(settings, "WORK_ORDER_GATE_ALLOW_SUPERUSER", True) and getattr(
        request.user, "is_superuser", False
    ):
        return None

    raw = (request.META.get("HTTP_X_SHARK_WORK_ORDER_ID") or "").strip()
    if not raw:
        return Response(
            {
                "error": "work_order_required",
                "detail": "此写操作需已批准的智能工单：请在请求头携带 X-Shark-Work-Order-Id（Ticket UUID）。",
            },
            status=403,
        )
    try:
        wid = uuid.UUID(raw)
    except ValueError:
        return Response({"error": "invalid_work_order_id"}, status=400)

    from ai_ops.models import Ticket

    try:
        ticket = Ticket.objects.get(pk=wid)
    except Ticket.DoesNotExist:
        return Response({"error": "work_order_not_found"}, status=404)

    if ticket.status != Ticket.STATUS_APPROVED:
        return Response(
            {
                "error": "work_order_not_approved",
                "detail": "工单必须为 approved 状态后方可触发写操作。",
                "current_status": ticket.status,
            },
            status=403,
        )
    return None
