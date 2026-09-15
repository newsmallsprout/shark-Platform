# ============================================================
# security/agents/auto_scan/nodes.py — 各阶段节点 (pentest 移植, 改 Channels/Django)
# ============================================================

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from django.conf import settings

from security.agents.auto_scan.prompts import ANALYZE_PROMPT
from security.agents.auto_scan.state import ScanState
from security import emitters
from security.tools.tool_registry import get_tool, get_default_tools

logger = logging.getLogger(__name__)

# ---- LLM Client ----

_llm_client = None


def _get_llm():
    global _llm_client
    if _llm_client is None:
        from langchain_openai import ChatOpenAI

        _llm_client = ChatOpenAI(
            model=settings.DEEPSEEK_MODEL,
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            temperature=0.3,
        )
    return _llm_client


# ---- Node: recon (信息收集) ----


async def recon_node(state: ScanState) -> ScanState:
    """运行 subfinder + httpx + nmap，实时推送 WS 事件"""
    state["current_stage"] = "recon"
    task_id = state["task_id"]
    await emitters.emit_stage_change(task_id, "recon")

    assets: list[dict] = []

    for tool in get_default_tools():
        logger.info(f"[{task_id}] Running {tool.name}...")
        await emitters.emit_tool_started(task_id, tool.name)

        lines = []
        try:
            async for line in tool.run(state["target"]):
                lines.append(line)
                await emitters.emit_tool_output(task_id, tool.name, line)
        except Exception as e:
            logger.error(f"[{task_id}] {tool.name} failed: {e}")
            await emitters.emit_tool_error(task_id, tool.name, str(e))
            continue

        parsed = tool.parse_output(lines)
        assets.extend(parsed)
        state["tool_results"][tool.name] = lines

        await emitters.emit_tool_done(task_id, tool.name, len(parsed))

    state["assets"] = assets
    await emitters.emit_progress(task_id, 25)
    return state


# ---- Node: fingerprint (指纹识别) ----


async def fingerprint_node(state: ScanState) -> ScanState:
    state["current_stage"] = "discovery"
    await emitters.emit_stage_change(state["task_id"], "discovery")
    await emitters.emit_progress(state["task_id"], 40)
    return state


# ---- Node: scan (漏洞扫描) ----


async def scan_node(state: ScanState) -> ScanState:
    state["current_stage"] = "vuln_scan"
    task_id = state["task_id"]
    await emitters.emit_stage_change(task_id, "vuln_scan")

    if "nuclei" not in state["allowed_tools"]:
        await emitters.emit_progress(task_id, 70)
        return state

    try:
        nuclei = get_tool("nuclei")
        await emitters.emit_tool_started(task_id, "nuclei")

        lines = []
        async for line in nuclei.run(state["target"]):
            lines.append(line)
            await emitters.emit_tool_output(task_id, "nuclei", line)

        parsed = nuclei.parse_output(lines)
        for vuln in parsed:
            vuln["found_by"] = "nuclei"
            vuln["found_at"] = datetime.now(timezone.utc).isoformat()
            state["vulnerabilities"].append(vuln)
            await emitters.emit_vuln_found(task_id, vuln)

        state["tool_results"]["nuclei"] = lines
        await emitters.emit_tool_done(task_id, "nuclei", len(parsed))

    except Exception as e:
        logger.error(f"[{task_id}] Nuclei failed: {e}")
        await emitters.emit_tool_error(task_id, "nuclei", str(e))

    await emitters.emit_progress(task_id, 65)
    return state


# ---- Node: analyze (AI 分析) ----


async def analyze_node(state: ScanState) -> ScanState:
    state["current_stage"] = "analyzing"
    task_id = state["task_id"]
    await emitters.emit_stage_change(task_id, "analyzing")

    all_output = ""
    for tool_name, lines in state["tool_results"].items():
        all_output += f"\n## {tool_name}\n```\n"
        all_output += "\n".join(lines[:200])
        all_output += "\n```\n"

    if not all_output.strip():
        await emitters.emit_progress(task_id, 80)
        return state

    prompt = ANALYZE_PROMPT.format(tool_output=all_output)

    try:
        llm = _get_llm()
        response = await llm.ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        json_match = None
        if "```json" in content:
            json_match = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_match = content.split("```")[1].strip()

        if json_match:
            ai_vulns = json.loads(json_match)
            for vuln in ai_vulns:
                vuln["found_by"] = "AI"
                vuln["found_at"] = datetime.now(timezone.utc).isoformat()
                state["vulnerabilities"].append(vuln)
                await emitters.emit_vuln_found(task_id, vuln)

    except Exception as e:
        logger.error(f"[{task_id}] AI analysis failed: {e}")

    await emitters.emit_progress(task_id, 85)
    return state


# ---- Node: report ----


async def report_node(state: ScanState) -> ScanState:
    state["current_stage"] = "reporting"
    task_id = state["task_id"]
    await emitters.emit_stage_change(task_id, "reporting")
    await emitters.emit_progress(task_id, 95)
    return state
