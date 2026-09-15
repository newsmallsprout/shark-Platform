# ============================================================
# security/agents/guided/state.py — GuidedState (pentest 原样)
# ============================================================

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class GuidedState(TypedDict):
    """引导模式 Agent 的状态"""

    task_id: str
    target: str
    scope: dict

    current_stage: str  # briefing/recon/enumeration/vuln_analysis/exploit/summary

    # 对话历史
    conversation_history: Annotated[list, add_messages]

    # 累积的发现
    context: str          # 累积的关键信息（Markdown）
    found_vulns: list[dict]  # 已发现的漏洞

    # 当前指令
    current_command: dict | None  # { command, description }

    # 错误
    error: str | None
