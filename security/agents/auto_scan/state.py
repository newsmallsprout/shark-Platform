# ============================================================
# security/agents/auto_scan/state.py — ScanState (pentest 原样)
# ============================================================

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class ScanState(TypedDict):
    """自动扫描 Agent 的状态"""

    task_id: str
    target: str
    scope: dict  # { target_url, allow_auto_scan, allowed_paths, excluded_paths, notes }
    allowed_tools: list[str]

    # 进度
    current_stage: str  # init / recon / discovery / vuln_scan / exploit / reporting

    # 累积数据
    assets: list[dict]
    vulnerabilities: list[dict]
    tool_results: dict[str, list[str]]  # tool_name → output_lines

    # LangGraph 消息流（用于 LLM 调用）
    messages: Annotated[list, add_messages]

    # 错误
    error: str | None
