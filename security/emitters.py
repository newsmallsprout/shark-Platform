# ============================================================
# security/emitters.py — 扫描事件发射器 (FastAPI ws_manager → Django Channels)
# 与 pentest 的 services/event_emitter.py 同签名，底层改走 Channels 频道层
# ============================================================

from __future__ import annotations

import logging

from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


async def _group_send(task_id: str, event: str, data: dict | None = None) -> None:
    """向 task_{task_id} 频道组广播事件"""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    await channel_layer.group_send(
        f"task_{task_id}",
        {"type": "scan_event", "event": event, "data": data or {}},
    )


async def emit_tool_started(task_id: str, tool_name: str) -> None:
    await _group_send(task_id, "tool_started", {"tool": tool_name})


async def emit_tool_output(task_id: str, tool_name: str, line: str) -> None:
    await _group_send(task_id, "tool_output", {"tool": tool_name, "line": line})


async def emit_tool_done(task_id: str, tool_name: str, findings: int = 0) -> None:
    await _group_send(task_id, "tool_done", {"tool": tool_name, "findings": findings})


async def emit_tool_error(task_id: str, tool_name: str, error: str) -> None:
    await _group_send(task_id, "tool_error", {"tool": tool_name, "error": error})


async def emit_stage_change(task_id: str, stage: str) -> None:
    await _group_send(task_id, "stage_changed", {"stage": stage})


async def emit_vuln_found(task_id: str, vuln: dict) -> None:
    await _group_send(task_id, "vuln_found", {"vulnerability": vuln})


async def emit_progress(task_id: str, progress: int) -> None:
    await _group_send(task_id, "progress_update", {"progress": progress})


async def emit_scan_complete(task_id: str, summary: dict) -> None:
    await _group_send(task_id, "scan_complete", {"summary": summary})


async def emit_error(task_id: str, message: str) -> None:
    await _group_send(task_id, "error", {"message": message})
