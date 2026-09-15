# ============================================================
# security/tasks.py — 自动扫描 Celery 任务 (pentest scan_tasks → Django ORM)
# 由 shark_platform.celery 的 autodiscover_tasks() 自动发现
# ============================================================

from __future__ import annotations

import asyncio
import logging

from celery.utils.log import get_task_logger
from django.utils import timezone

from shark_platform.celery import app as celery_app
from security.models import SecurityTask, ScanSession, Vulnerability
from security.emitters import emit_scan_complete, emit_error

logger = get_task_logger(__name__)


@celery_app.task(bind=True, name="security.run_auto_scan")
def run_auto_scan(self, task_id: str):
    """执行自动扫描任务 — LangGraph 编排，asyncio 运行"""
    # ---- 同步 DB：加载任务 / 会话 ----
    try:
        task = SecurityTask.objects.get(id=task_id)
    except SecurityTask.DoesNotExist:
        return {"error": "Task not found"}

    session, _ = ScanSession.objects.get_or_create(
        task=task, defaults={"current_stage": "recon", "start_time": timezone.now()}
    )
    if not session.start_time:
        session.start_time = timezone.now()
        session.save(update_fields=["start_time"])

    state = {
        "task_id": task_id,
        "target": task.target,
        "scope": task.scope or {},
        "allowed_tools": (task.scope or {}).get(
            "allowed_tools", ["nuclei", "nmap", "subfinder", "httpx"]
        ),
        "current_stage": "init",
        "assets": [],
        "vulnerabilities": [],
        "tool_results": {},
        "messages": [],
        "error": None,
    }

    # ---- 异步：运行 LangGraph 扫描流水线（含事件推送）----
    final_state = asyncio.run(_run_graph(state))

    if final_state.get("error"):
        task.status = "failed"
        task.save(update_fields=["status", "updated_at"])
        return {"error": final_state["error"]}

    # ---- 同步 DB：持久化漏洞 + 更新状态 ----
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for vuln_dict in final_state.get("vulnerabilities", []):
        severity = vuln_dict.get("severity", "info")
        if severity in severity_counts:
            severity_counts[severity] += 1
        Vulnerability.objects.create(
            task=task,
            session=session,
            title=vuln_dict.get("title", ""),
            severity=severity,
            type=vuln_dict.get("type", "vulnerability"),
            target=vuln_dict.get("target", task.target),
            endpoint=vuln_dict.get("endpoint"),
            method=vuln_dict.get("method"),
            description=vuln_dict.get("description", ""),
            proof=vuln_dict.get("proof"),
            impact=vuln_dict.get("impact"),
            recommendation=vuln_dict.get("recommendation", ""),
            cve=vuln_dict.get("cve"),
            cvss_score=vuln_dict.get("cvss_score"),
            references=vuln_dict.get("references", []) or [],
            tags=vuln_dict.get("tags", []) or [],
            found_by=vuln_dict.get("found_by", "AI"),
            found_at=timezone.now(),
        )

    task.status = "completed"
    task.progress = 100
    task.vuln_count = severity_counts
    task.completed_at = timezone.now()
    task.save()

    session.current_stage = "reporting"
    session.end_time = timezone.now()
    session.save(update_fields=["current_stage", "end_time", "updated_at"])

    asyncio.run(emit_scan_complete(task_id, {
        "status": "completed",
        "vuln_count": severity_counts,
        "total_vulns": len(final_state.get("vulnerabilities", [])),
        "assets_found": len(final_state.get("assets", [])),
    }))

    logger.info(f"Scan completed for task {task_id}: {severity_counts}")
    return {"status": "completed", "vuln_count": severity_counts}


async def _run_graph(state: dict) -> dict:
    """运行 LangGraph 扫描图；异常时发射错误事件并返回 error 状态"""
    from security.agents.auto_scan.graph import get_auto_scan_graph

    try:
        graph = get_auto_scan_graph()
        return await graph.ainvoke(state)
    except Exception as e:
        logger.error(f"Scan graph error for task {state['task_id']}: {e}")
        await emit_error(state["task_id"], str(e))
        return {
            "error": str(e),
            "vulnerabilities": [],
            "assets": [],
            "tool_results": {},
        }
