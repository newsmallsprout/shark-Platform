# ============================================================
# security/agents/guided/nodes.py — 引导模式节点 (pentest 移植)
# ============================================================

from __future__ import annotations

import json
import logging

from django.conf import settings

from security.agents.guided.prompts import (
    SYSTEM_PROMPT,
    INIT_PROMPT,
    ANALYZE_RESULT_PROMPT,
)
from security.agents.guided.state import GuidedState

logger = logging.getLogger(__name__)

# ---- LLM ----

_llm_client = None


def _get_llm():
    global _llm_client
    if _llm_client is None:
        from langchain_openai import ChatOpenAI

        _llm_client = ChatOpenAI(
            model=settings.DEEPSEEK_MODEL,
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            temperature=0.5,
        )
    return _llm_client


# ---- Nodes ----


async def init_node(state: GuidedState) -> GuidedState:
    """初始化引导会话，给出第一条指令"""
    from langchain_core.messages import HumanMessage, SystemMessage

    state["current_stage"] = "recon"

    llm = _get_llm()
    scope_summary = json.dumps(state["scope"], ensure_ascii=False)

    messages = [
        SystemMessage(content=SYSTEM_PROMPT.format(
            target=state["target"],
            scope=scope_summary,
        )),
        HumanMessage(content=INIT_PROMPT.format(
            target=state["target"],
            scope=scope_summary,
        )),
    ]

    response = await llm.ainvoke(messages)
    content = response.content if hasattr(response, "content") else str(response)

    command = _extract_command(content)
    state["current_command"] = command
    state["context"] = f"## 目标: {state['target']}\n"

    return state


async def process_result_node(state: GuidedState) -> GuidedState:
    """处理用户提交的命令结果，分析并给出下一步"""
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = _get_llm()
    scope_summary = json.dumps(state["scope"], ensure_ascii=False)

    last_user_msg = ""
    for msg in reversed(state["conversation_history"]):
        if hasattr(msg, "type") and msg.type == "human":
            last_user_msg = msg.content if hasattr(msg, "content") else str(msg)
            break

    messages = [
        SystemMessage(content=SYSTEM_PROMPT.format(
            target=state["target"],
            scope=scope_summary,
        )),
        HumanMessage(content=ANALYZE_RESULT_PROMPT.format(
            user_result=last_user_msg,
            context=state["context"],
            current_stage=state["current_stage"],
        )),
    ]

    response = await llm.ainvoke(messages)
    content = response.content if hasattr(response, "content") else str(response)

    state["context"] += f"\n\n## AI 分析 ({state['current_stage']})\n{content}\n"

    command = _extract_command(content)
    state["current_command"] = command

    new_stage = _check_stage_transition(content, state["current_stage"])
    if new_stage != state["current_stage"]:
        state["current_stage"] = new_stage

    return state


async def report_node(state: GuidedState) -> GuidedState:
    """生成引导模式报告草稿"""
    state["current_stage"] = "summary"
    return state


# ---- Helpers ----


def _extract_command(content: str) -> dict | None:
    import re

    patterns = [
        r'```json\s*(\{.*?"command".*?\})\s*```',
        r'```\s*(\{.*?"command".*?\})\s*```',
        r'(\{"command"\s*:\s*".*?"\})',
    ]
    for pattern in patterns:
        match = re.search(pattern, content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
    return None


def _check_stage_transition(content: str, current_stage: str) -> str:
    stage_order = ["recon", "enumeration", "vuln_analysis", "exploit", "summary"]

    transition_keywords = [
        "推进到", "进入下一阶段", "下一阶段", "开始枚举",
        "进入漏洞分析", "阶段完成", "current stage",
    ]

    if any(kw in content for kw in transition_keywords):
        try:
            idx = stage_order.index(current_stage)
            if idx < len(stage_order) - 1:
                return stage_order[idx + 1]
        except ValueError:
            pass

    return current_stage
