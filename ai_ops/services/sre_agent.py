"""
DeepSeek / OpenAI-compatible ReAct SRE agent with function calling for incidents.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests
from django.utils import timezone as dj_timezone

from ..models import AIConfig, AnalysisReport, Incident
from .sre_tools import execute_tool, tool_schemas

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是 Kubernetes / 可观测性 SRE 值班助手，使用 ReAct：先调用工具收集只读证据，再调用 submit_final_report 结束。

硬性规则：
1. 优先顺序：query_log_monitor_errors（平台落盘 error 日志）→ query_prometheus / get_k8s_resource_status → 必要时 fetch_container_raw_logs。
2. 禁止编造未出现在工具 Observation 中的数值、日志行、Pod 名或指标；结论必须引用 data_citations 中的摘录。
3. 用词：避免「可能」「大概」等模糊表述；证据不足时在 root_cause 写明「依据当前 Observation 不足以确认根因」，并列出需补充的工具调用。
4. 安全：只读工具；mitigation_commands 仅建议人工在集群执行的命令，不假设平台代执行。
5. 达到证据充分或达到迭代/工具上限前，不要调用 submit_final_report；调用后停止。
"""


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


def _build_user_bootstrap(incident: Incident) -> str:
    labels = (incident.raw_alert_data or {}).get("labels", {}) or {}
    ns = labels.get("namespace", "")
    pod = labels.get("pod", "")
    return f"""告警事件（请据此选择工具参数）：
- alert_name: {incident.alert_name}
- severity: {incident.severity}
- description: {incident.description}
- labels: {json.dumps(labels, ensure_ascii=False)}
建议首轮：query_log_monitor_errors（namespace={ns!r}, pod_name_substring={pod!r}）与 query_prometheus（与告警相关的 PromQL，instant 或短 range）。
若 labels 含 namespace/pod，应用 get_k8s_resource_status。"""


def _chat(
    api_base: str,
    api_key: str,
    model: str,
    messages: List[dict],
    tools: List[dict],
    temperature: float,
    max_tokens: int,
    timeout: int = 120,
) -> dict:
    url = f"{api_base.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    r = requests.post(url, headers=headers, json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _persist_failure_report(incident: Incident, message: str, trace: list) -> None:
    AnalysisReport.objects.filter(incident=incident).delete()
    AnalysisReport.objects.create(
        incident=incident,
        phenomenon="分析未完成",
        root_cause=message,
        mitigation="请检查 AI 配置、网络与集群只读权限后重试。",
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


def run_sre_agent_analysis(incident: Incident) -> None:
    from django.conf import settings as dj_settings

    prom_url = (getattr(dj_settings, "PROMETHEUS_URL", "") or os.environ.get("PROMETHEUS_URL", "")).strip()

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
        )
        incident.status = "analyzed"
        incident.save(update_fields=["status"])
        return

    if not (ai.api_key or "").strip():
        trace.append({"type": "system", "message": "missing api_key"})
        incident.agent_trace = trace
        incident.save(update_fields=["agent_trace"])
        _persist_failure_report(incident, "未配置 API Key，无法运行 SRE Agent。", trace)
        incident.status = "open"
        incident.save(update_fields=["status"])
        return

    t_start, t_end = _alert_time_window(incident)
    bootstrap = _build_user_bootstrap(incident)
    bootstrap += f"\n时间窗（ISO8601，供 log 工具）: start={t_start}, end={t_end}"

    messages: List[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": bootstrap},
    ]
    tools = tool_schemas()

    final_payload: Optional[dict] = None

    try:
        for iteration in range(max_iter):
            trace.append({"type": "iteration", "n": iteration + 1})
            incident.agent_trace = list(trace)
            incident.save(update_fields=["agent_trace"])

            data = _chat(
                ai.api_base,
                ai.api_key,
                ai.model,
                messages,
                tools,
                float(ai.temperature),
                int(ai.max_tokens),
            )
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            assistant_content = msg.get("content") or ""
            tool_calls = msg.get("tool_calls") or []

            trace.append(
                {
                    "type": "assistant",
                    "iteration": iteration + 1,
                    "content": (assistant_content or "")[:8000],
                    "tool_calls": [
                        {
                            "id": tc.get("id"),
                            "name": (tc.get("function") or {}).get("name"),
                            "arguments": (tc.get("function") or {}).get("arguments"),
                        }
                        for tc in tool_calls
                    ],
                }
            )

            assistant_msg = {
                "role": "assistant",
                "content": assistant_content if assistant_content else None,
            }
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            if not tool_calls:
                messages.append(
                    {
                        "role": "user",
                        "content": "请继续：若证据仍不足，继续调用只读工具；若已足够，必须调用 submit_final_report 结束。",
                    }
                )
                continue

            tool_reply_contents: List[Tuple[str, str]] = []

            for tc in tool_calls:
                tid = tc.get("id") or f"call_{uuid.uuid4().hex[:12]}"
                if tool_calls_total >= max_tools:
                    trace.append(
                        {
                            "type": "limit",
                            "message": f"max_tool_calls_per_incident={max_tools} reached",
                        }
                    )
                    tool_reply_contents.append(
                        (
                            tid,
                            json.dumps(
                                {"ok": False, "error": "tool budget exhausted"},
                                ensure_ascii=False,
                            ),
                        )
                    )
                    continue

                tool_calls_total += 1
                fn = tc.get("function") or {}
                name = fn.get("name") or ""
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except json.JSONDecodeError:
                    args = {}
                if name == "query_log_monitor_errors":
                    if not args.get("start_iso8601"):
                        args["start_iso8601"] = t_start
                    if not args.get("end_iso8601"):
                        args["end_iso8601"] = t_end

                obs, is_final = execute_tool(name, args, prometheus_url=prom_url)

                trace.append(
                    {
                        "type": "tool_result",
                        "tool_name": name,
                        "tool_call_id": tid,
                        "observation": obs,
                    }
                )

                if is_final and obs.get("ok") and isinstance(obs.get("final_report"), dict):
                    final_payload = obs["final_report"]
                    tool_reply_contents.append(
                        (
                            tid,
                            json.dumps(
                                {"ok": True, "message": "Report accepted; stop calling tools."},
                                ensure_ascii=False,
                            ),
                        )
                    )
                else:
                    tool_reply_contents.append(
                        (
                            tid,
                            json.dumps(obs, ensure_ascii=False)[:120_000],
                        )
                    )

            for tid, content in tool_reply_contents:
                messages.append({"role": "tool", "tool_call_id": tid, "content": content})

            incident.agent_trace = list(trace)
            incident.save(update_fields=["agent_trace"])

            if final_payload is not None:
                break
            if tool_calls_total >= max_tools:
                break

        if final_payload is None:
            trace.append(
                {
                    "type": "system",
                    "message": "Agent stopped without submit_final_report; emitting fallback report.",
                }
            )
            incident.agent_trace = list(trace)
            incident.save(update_fields=["agent_trace"])
            _persist_failure_report(
                incident,
                "模型未在限制内提交 submit_final_report，或工具次数已达上限。请查看 agent_trace 中的 Observation。",
                trace,
            )
        else:
            _map_final_to_report(final_payload, incident, trace)
            trace.append({"type": "done", "message": "submit_final_report processed"})

        incident.agent_trace = list(trace)
        incident.status = "analyzed"
        incident.save(update_fields=["agent_trace", "status"])
    except Exception as e:
        logger.exception("SRE agent failed for incident %s", incident.id)
        trace.append({"type": "error", "message": str(e)[:2000]})
        incident.agent_trace = list(trace)
        incident.save(update_fields=["agent_trace"])
        _persist_failure_report(incident, f"SRE Agent 异常: {e}", trace)
        incident.status = "open"
        incident.save(update_fields=["status"])
