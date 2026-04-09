"""
Celery 异步入口：M2M 协议 + 工具执行闭环，并落库工单（任务名保留 run_incident_langgraph 以兼容已有 Worker 配置）。
"""
from __future__ import annotations

import logging
from typing import Optional

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="ai_ops.run_incident_langgraph", max_retries=2, default_retry_delay=30)
def run_incident_langgraph(
    self,
    incident_id: int,
    run_id: Optional[str] = None,
    operator_context: Optional[str] = None,
    human_feedback: Optional[str] = None,
    trigger_source: str = "manual",
    create_ticket: bool = True,
) -> dict:
    """
    :param incident_id: Incident 主键
    :param run_id: 可选；Webhook/控制台均应显式传入 UUID，便于 SSE 订阅与 AgentRun 对齐。
        若省略，则使用 ``inc-{incident_id}-{celery_request_id}``，保证 Celery 重试时频道不变。
    :param operator_context: 运维排障指引（诊断入口）
    :param human_feedback: 审批打回理由（反思重试）
    :param trigger_source: webhook | manual | rejection_retry
    :param create_ticket: 告警自动分析时可关（仅写 AnalysisReport / agent_trace）
    """
    rid = run_id or f"inc-{incident_id}-{self.request.id}"
    try:
        from ai_ops.graph import run_pipeline_for_incident

        return run_pipeline_for_incident(
            incident_id,
            rid,
            operator_context=operator_context,
            human_feedback=human_feedback,
            trigger_source=trigger_source,
            create_ticket=create_ticket,
            celery_task_id=str(getattr(self.request, "id", "") or ""),
        )
    except Exception as exc:
        logger.exception("run_incident_langgraph incident_id=%s run_id=%s", incident_id, rid)
        try:
            from ai_ops.redis_stream import publish_agent_event

            publish_agent_event(
                rid,
                "error",
                {"message": str(exc)[:1200], "task_id": getattr(self.request, "id", "")},
                incident_id=incident_id,
            )
        except Exception:
            logger.exception("failed to publish error event")
        raise self.retry(exc=exc) from exc


@shared_task(name="ai_ops.verify_ticket_post_execution")
def verify_ticket_post_execution(ticket_uuid_str: str) -> dict:
    """执行成功后可选：用固定 PromQL 做一轮只读校验，结果写入 execution_result['post_verify']。"""
    from uuid import UUID

    from django.utils import timezone as dj_tz

    from ai_ops.models import Ticket
    from ai_ops.prometheus_urls import resolve_prometheus_base_url
    from ai_ops.services.sre_tools import query_prometheus

    promql = (getattr(settings, "AIOPS_POST_EXEC_VERIFY_PROMQL", "") or "").strip()
    if not promql:
        return {"ok": False, "skipped": True}

    try:
        tid = UUID(str(ticket_uuid_str))
    except ValueError:
        return {"ok": False, "error": "bad uuid"}

    t = Ticket.objects.select_related("incident").filter(pk=tid).first()
    if not t:
        return {"ok": False, "error": "ticket missing"}

    base = resolve_prometheus_base_url(t.incident)
    if not base:
        snap = {"ok": False, "error": "PROMETHEUS_URL empty", "promql": promql}
    else:
        snap = query_prometheus(
            {"query": promql, "query_type": "instant", "range_minutes": 60, "step": "60s"},
            base,
        )

    er = dict(t.execution_result or {})
    er["post_verify"] = {
        "at": dj_tz.now().isoformat(),
        "promql": promql,
        "observation": snap,
    }
    Ticket.objects.filter(pk=tid).update(execution_result=er, updated_at=dj_tz.now())
    return {"ok": True, "ticket_id": str(tid)}
