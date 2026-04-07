"""
Celery 异步入口：触发 LangGraph 全链路，避免阻塞 Gunicorn WSGI。
"""
from __future__ import annotations

import logging
from typing import Optional

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="ai_ops.run_incident_langgraph", max_retries=2, default_retry_delay=30)
def run_incident_langgraph(
    self,
    incident_id: int,
    run_id: Optional[str] = None,
    operator_context: Optional[str] = None,
    human_feedback: Optional[str] = None,
) -> dict:
    """
    :param incident_id: Incident 主键
    :param run_id: 可选；建议由 API 生成 UUID 并下发前端订阅 SSE。
        若省略，则使用 ``inc-{incident_id}-{celery_request_id}``，保证 Celery 重试时频道不变。
    :param operator_context: 运维排障指引（诊断入口）
    :param human_feedback: 审批打回理由（反思重试）
    """
    rid = run_id or f"inc-{incident_id}-{self.request.id}"
    try:
        from ai_ops.graph import run_pipeline_for_incident

        return run_pipeline_for_incident(
            incident_id,
            rid,
            operator_context=operator_context,
            human_feedback=human_feedback,
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
