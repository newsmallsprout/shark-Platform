"""
DeepSeek / OpenAI-compatible ReAct SRE agent with function calling for incidents.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import timedelta
from typing import Any, Dict, List, Optional

import requests
from django.utils import timezone as dj_timezone

from ..models import AIConfig, AnalysisReport, Incident
from ..prometheus_urls import resolve_prometheus_base_url
from .m2m_diagnostic import (
    M2M_SYSTEM_PROMPT,
    CommandStrikeTracker,
    parse_model_turn,
    run_diagnostic_line,
    ticket_body_to_final_report,
)

logger = logging.getLogger(__name__)


def _alert_time_window(incident: Incident) -> tuple[str, str]:
    now = dj_timezone.now()
    start = now - timedelta(hours=6)
    raw = incident.raw_alert_data or {}
    starts = raw.get("startsAt")
    if starts:
        try:
            s = str(starts).replace("Z", "+00:00")
            from datetime import datetime

            st = datetime.fromisoformat(s)
            if st.tzinfo is None:
                st = dj_timezone.make_aware(st)
            start = min(st, now)
        except (ValueError, TypeError):
            pass
    return start.isoformat(), now.isoformat()


def _build_m2m_user_bootstrap(
    incident: Incident,
    *,
    t_start: str,
    t_end: str,
    soft_context: str,
    operator_context: str,
    human_feedback: str,
) -> str:
    labels = (incident.raw_alert_data or {}).get("labels", {}) or {}
    raw = incident.raw_alert_data if isinstance(incident.raw_alert_data, dict) else {}
    raw_json = json.dumps(raw, ensure_ascii=False)
    if len(raw_json) > 12000:
        raw_json = raw_json[:12000] + "…[truncated]"
    parts = [
        "【告警输入】",
        f"alert_name: {incident.alert_name}",
        f"severity: {incident.severity}",
        f"description: {incident.description}",
        f"labels: {json.dumps(labels, ensure_ascii=False)}",
        f"raw_alert_json: {raw_json}",
        "",
        f"log_time_window_iso8601: start={t_start}, end={t_end}",
        "",
        "取证说明：在 <EXECUTE> 中每行一条命令；kubectl 只读子命令见 System；指标用 PROMQL|<PromQL instant 表达式>。",
    ]
    if soft_context.strip():
        parts.extend(["", "---", "【平台参考上下文】", soft_context.strip()[:12000]])
    if operator_context.strip():
        parts.extend(["", "【运维排障指引】", operator_context.strip()[:4000]])
    if human_feedback.strip():
        parts.extend(["", "【审批打回 / 人工反馈】", human_feedback.strip()[:4000]])
    parts.extend(
        [
            "",
            "请严格按 System：本轮仅输出 <EXECUTE>+<REASON>，或仅输出 <TICKET>。",
        ]
    )
    return "\n".join(parts)


def _chat_plain(
    api_base: str,
    api_key: str,
    model: str,
    messages: List[dict],
    temperature: float,
    max_tokens: int,
    timeout: int = 180,
) -> dict:
    """OpenAI 兼容 chat，无 tools（机读标签协议）。"""
    url = f"{api_base.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    r = requests.post(url, headers=headers, json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()


_DEFAULT_INCOMPLETE_MITIGATION = (
    "第一步：展开「历史 Agent 轨迹」，确认 query_prometheus / k8s 类工具是否 403 或超时。\n"
    "第二步：检查本平台的 AI API Key、模型可用性与网络出口。\n"
    "第三步：若集群只读权限不足，请管理员执行例如 "
    "`kubectl create clusterrolebinding <名> --clusterrole=view --user=<你的用户>` "
    "绑定后再重试。\n"
    "说明：只读排查不需要开变更工单；只有准备执行重启/删 Pod 等变更时才走工单审批。"
)


def _persist_failure_report(
    incident: Incident,
    message: str,
    trace: list,
    *,
    incomplete_agent: bool = True,
    mitigation_text: Optional[str] = None,
    phenomenon: str = "分析未完成",
) -> None:
    AnalysisReport.objects.filter(incident=incident).delete()
    if incomplete_agent:
        root_cause = (
            "【这条提示是什么】表示「同步 SRE Agent」本次运行**没有形成最终分析报告**，属于分析流程未收束，"
            "不是 Redis、工单服务或数据库本身的报错码。\n\n"
            "【常见原因】① 在系统允许的对话轮次或工具次数内，模型没有执行结束步骤；"
            "② 大模型或 API 超时、鉴权失败；③ 工具持续返回空数据/403，无法收束。\n\n"
            "【你怎么做】展开上方「历史 Agent 轨迹」，看每一步工具的 Observation（尤其最后几条）。"
            "核对 AI 配置与网络、PROMETHEUS_URL，以及集群只读权限；处理后再触发同步分析。\n\n"
            "【技术备注（可忽略）】"
            + message
        )
        mit = mitigation_text or _DEFAULT_INCOMPLETE_MITIGATION
    else:
        root_cause = message
        mit = mitigation_text or "请根据上述说明处理后重试。"

    AnalysisReport.objects.create(
        incident=incident,
        phenomenon=phenomenon,
        root_cause=root_cause,
        mitigation=mit,
        prevention="",
        refactoring="",
        platform_linkage="",
        solutions=[],
        related_metrics={},
        diagnosis_logs=[],
        k8s_events=[],
        k8s_pod_status={},
        raw_ai_response=json.dumps({"error": message, "agent_trace": trace}, ensure_ascii=False),
    )


def _map_final_to_report(final: dict, incident: Incident, trace: list) -> None:
    mit_cmds = final.get("mitigation_commands") or []
    prev = final.get("prevention") or []
    solutions = [str(x) for x in mit_cmds if str(x).strip()]
    phenomenon = (final.get("incident_summary") or "").strip() or incident.alert_name
    root = (final.get("root_cause") or "").strip()
    mitigation = "\n".join(solutions) if solutions else "见 solutions 列表或人工处置。"
    prevention_text = "\n".join(str(p) for p in prev) if prev else ""

    raw_blob = {
        "final_report": final,
        "agent_trace": trace,
        "confidence": final.get("confidence"),
        "evidence_chain": final.get("evidence_chain"),
        "data_citations": final.get("data_citations"),
    }

    AnalysisReport.objects.filter(incident=incident).delete()
    AnalysisReport.objects.create(
        incident=incident,
        phenomenon=phenomenon,
        root_cause=root,
        mitigation=mitigation,
        prevention=prevention_text,
        refactoring="",
        platform_linkage=f"SRE Agent 置信度: {final.get('confidence', 'unknown')}",
        solutions=solutions,
        related_metrics={},
        diagnosis_logs=_trace_to_log_snippets(trace),
        k8s_events=[],
        k8s_pod_status={},
        raw_ai_response=json.dumps(raw_blob, ensure_ascii=False),
    )


def _trace_to_log_snippets(trace: list, max_items: int = 24) -> List[str]:
    out: List[str] = []
    for step in trace:
        if step.get("type") != "tool_result":
            continue
        name = step.get("tool_name", "")
        obs = step.get("observation")
        if obs is None:
            continue
        s = json.dumps(obs, ensure_ascii=False)
        if len(s) > 4000:
            s = s[:4000] + "…[truncated]"
        out.append(f"[{name}] {s}")
        if len(out) >= max_items:
            break
    return out


def _stream_agent_event(
    run_id: Optional[str],
    event_type: str,
    payload: Dict[str, Any],
    incident_id: int,
) -> None:
    if not run_id:
        return
    try:
        from ai_ops.redis_stream import publish_agent_event

        publish_agent_event(run_id, event_type, payload, incident_id=incident_id)
    except Exception:
        logger.debug("agent stream publish failed", exc_info=True)


def run_react_diagnosis_loop(
    incident: Incident,
    *,
    run_id: Optional[str] = None,
    operator_context: str = "",
    human_feedback: str = "",
    soft_context: str = "",
) -> Optional[dict]:
    """
    大模型 + 工具互动排障（ReAct）。成功返回 submit_final_report 的 final_report 字典；
    失败或配置问题时返回 None（已写入 AnalysisReport / agent_trace）。
    """
    ai = AIConfig.get_active_config()
    max_iter = max(1, min(int(getattr(ai, "max_agent_iterations", 12) or 12), 24))
    max_tools = max(1, min(int(getattr(ai, "max_tool_calls_per_incident", 36) or 36), 80))

    trace: List[dict] = []
    tool_calls_total = 0

    incident.status = "analyzing"
    incident.agent_trace = []
    incident.evidence_checklist = []
    incident.user_evidence = {}
    incident.save(
        update_fields=[
            "status",
            "agent_trace",
            "evidence_checklist",
            "user_evidence",
        ]
    )

    if not ai.enable_ai_analysis:
        trace.append({"type": "system", "message": "enable_ai_analysis is false"})
        incident.agent_trace = trace
        incident.save(update_fields=["agent_trace"])
        _persist_failure_report(
            incident,
            "AI 分析已在配置中关闭；未调用模型。",
            trace,
            incomplete_agent=False,
            phenomenon="未启动分析",
            mitigation_text="在后台「AI 配置」中开启 enable_ai_analysis（或等价开关）后重新触发同步分析。",
        )
        incident.status = "analyzed"
        incident.save(update_fields=["status"])
        return None

    if not (ai.api_key or "").strip():
        trace.append({"type": "system", "message": "missing api_key"})
        incident.agent_trace = trace
        incident.save(update_fields=["agent_trace"])
        _persist_failure_report(
            incident,
            "未配置 API Key，无法调用大模型，同步分析未执行。",
            trace,
            incomplete_agent=False,
            phenomenon="未启动分析",
            mitigation_text="在「AI 配置」中填写有效的 API Key 与模型后重试。",
        )
        incident.status = "open"
        incident.save(update_fields=["status"])
        return None

    prom_url = resolve_prometheus_base_url(incident)

    t_start, t_end = _alert_time_window(incident)
    bootstrap = _build_m2m_user_bootstrap(
        incident,
        t_start=t_start,
        t_end=t_end,
        soft_context=soft_context,
        operator_context=(operator_context or "").strip(),
        human_feedback=(human_feedback or "").strip(),
    )

    messages: List[dict] = [
        {"role": "system", "content": M2M_SYSTEM_PROMPT},
        {"role": "user", "content": bootstrap},
    ]

    final_payload: Optional[dict] = None
    strikes = CommandStrikeTracker(3)
    max_exec_per_turn = 8

    try:
        for iteration in range(max_iter):
            trace.append({"type": "iteration", "n": iteration + 1, "protocol": "m2m_tags"})
            incident.agent_trace = list(trace)
            incident.save(update_fields=["agent_trace"])

            _stream_agent_event(
                run_id,
                "graph_node",
                {
                    "node": f"决策大脑·第 {iteration + 1} 轮（机读协议）",
                    "delta_keys": ["EXECUTE|TICKET"],
                },
                incident.pk,
            )

            data = _chat_plain(
                ai.api_base,
                ai.api_key,
                ai.model,
                messages,
                float(ai.temperature),
                int(ai.max_tokens),
            )
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            assistant_content = (msg.get("content") or "").strip()

            trace.append(
                {
                    "type": "assistant",
                    "iteration": iteration + 1,
                    "protocol": "m2m_tags",
                    "content": assistant_content[:16000],
                }
            )

            parsed = parse_model_turn(assistant_content)
            ticket_body = parsed.get("ticket_body")

            if ticket_body:
                final_payload = ticket_body_to_final_report(ticket_body, incident.alert_name)
                trace.append({"type": "m2m_ticket", "excerpt": ticket_body[:8000]})
                messages.append({"role": "assistant", "content": assistant_content})
                break

            exec_lines: List[str] = (parsed.get("execute_lines") or [])[:max_exec_per_turn]
            reason = parsed.get("reason") or ""

            if not exec_lines:
                messages.append({"role": "assistant", "content": assistant_content})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "未检测到 <TICKET> 或有效 <EXECUTE>。"
                            "请二选一输出：要么 <EXECUTE>…</EXECUTE> 与 <REASON>…</REASON>；"
                            "要么仅输出完整 <TICKET>…</TICKET>。禁止客套话。"
                        ),
                    }
                )
                incident.agent_trace = list(trace)
                incident.save(update_fields=["agent_trace"])
                continue

            messages.append({"role": "assistant", "content": assistant_content})

            feedback_parts: List[str] = []
            if reason:
                feedback_parts.append(f"【模型 REASON】\n{reason}\n")

            for cmd in exec_lines:
                if tool_calls_total >= max_tools:
                    trace.append({"type": "limit", "message": f"max_tool_calls_per_incident={max_tools}"})
                    feedback_parts.append("\n[AGENT] 已达工具/命令次数上限，请输出 <TICKET> 收束或转人工。\n")
                    break

                tool_calls_total += 1
                tid = f"m2m-{uuid.uuid4().hex[:12]}"
                _stream_agent_event(
                    run_id,
                    "tool_start",
                    {"tool_name": "m2m_exec", "call_id": tid, "arguments": {"command": cmd}},
                    incident.pk,
                )

                if strikes.blocked(cmd):
                    obs: Dict[str, Any] = {
                        "ok": False,
                        "error": "该命令已连续失败达到上限（3 次），请换其他只读命令或输出 <TICKET> 转人工。",
                        "command": cmd,
                    }
                else:
                    obs = run_diagnostic_line(
                        cmd,
                        prometheus_url=prom_url,
                        log_start_iso=t_start,
                        log_end_iso=t_end,
                    )
                    success = bool(isinstance(obs, dict) and obs.get("ok") is True)
                    strikes.record(cmd, success)

                trace.append(
                    {
                        "type": "tool_result",
                        "tool_name": "m2m_exec",
                        "tool_call_id": tid,
                        "observation": obs,
                    }
                )

                tool_err = None if obs.get("ok") else (obs.get("error") or "failed")
                _stream_agent_event(
                    run_id,
                    "tool_end",
                    {
                        "tool_name": "m2m_exec",
                        "call_id": tid,
                        "ok": bool(obs.get("ok")),
                        "error": tool_err,
                        "observation": obs,
                    },
                    incident.pk,
                )

                excerpt = json.dumps(obs, ensure_ascii=False)
                if len(excerpt) > 100_000:
                    excerpt = excerpt[:100_000] + "…[truncated]"
                feedback_parts.append(f"### COMMAND\n{cmd}\n### OBSERVATION_JSON\n{excerpt}\n")

            messages.append({"role": "user", "content": "\n".join(feedback_parts)[:120_000]})

            incident.agent_trace = list(trace)
            incident.save(update_fields=["agent_trace"])

            if tool_calls_total >= max_tools:
                break

        if final_payload is None:
            trace.append(
                {
                    "type": "system",
                    "message": "M2M loop ended without <TICKET>; emitting fallback report.",
                }
            )
            incident.agent_trace = list(trace)
            incident.save(update_fields=["agent_trace"])
            _persist_failure_report(
                incident,
                "内部原因摘要：未在限制内输出 <TICKET>，或命令次数用尽（详见 agent_trace）。",
                trace,
            )
        else:
            _map_final_to_report(final_payload, incident, trace)
            trace.append({"type": "done", "message": "m2m <TICKET> processed"})

        incident.agent_trace = list(trace)
        incident.status = "analyzed"
        incident.save(update_fields=["agent_trace", "status"])
        return final_payload
    except Exception as e:
        logger.exception("SRE agent failed for incident %s", incident.id)
        trace.append({"type": "error", "message": str(e)[:2000]})
        incident.agent_trace = list(trace)
        incident.save(update_fields=["agent_trace"])
        _persist_failure_report(
            incident,
            f"SRE Agent 运行异常（技术信息）：{e}",
            trace,
            incomplete_agent=False,
            phenomenon="分析失败",
            mitigation_text="请查看 Web/Celery Worker 日志中的完整异常堆栈，修复后重试。",
        )
        incident.status = "open"
        incident.save(update_fields=["status"])
        return None


def run_sre_agent_analysis(incident: Incident) -> None:
    run_react_diagnosis_loop(incident, run_id=None)
