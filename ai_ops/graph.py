"""
Phase 1 极简 LangGraph：investigate -> diagnose -> draft_ticket。

Checkpointer 使用官方 RedisSaver（需 Redis 支持 RedisJSON + RediSearch，或 Redis 8+）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, TypedDict

logger = logging.getLogger(__name__)


class IncidentGraphState(TypedDict, total=False):
    incident_id: int
    run_id: str
    operator_context: str
    human_feedback: str
    investigation_notes: str
    diagnosis: str
    summary: str
    root_cause: str
    proposed_action: str
    ticket_id: str


def _node_investigate(state: IncidentGraphState) -> Dict[str, Any]:
    """调用带 Redis 事件包装的 Prom 工具，收集只读指标证据。"""
    from ai_ops.tools_adapter import make_streaming_sre_tools

    run_id = state["run_id"]
    iid = state["incident_id"]
    tools = make_streaming_sre_tools(run_id, incident_id=iid, include_prometheus=True)
    if not tools:
        return {"investigation_notes": "{}"}
    raw = tools[0].invoke(
        {
            "query": "up",
            "query_type": "instant",
            "range_minutes": 60,
            "step": "60s",
        }
    )
    return {"investigation_notes": (raw or "")[:12000]}


def _node_diagnose(state: IncidentGraphState) -> Dict[str, Any]:
    """Phase 1 占位：后续可换 LLM；此处将调查笔记与人工上下文折叠为工单字段草稿。"""
    notes = state.get("investigation_notes") or ""
    op = (state.get("operator_context") or "").strip()
    hf = (state.get("human_feedback") or "").strip()
    snippet = notes[:4000]

    if hf:
        summary = (
            "Phase1：已接收审批打回反馈，将结合 human_feedback 与调查笔记重拟工单（待 LLM 增强）。"
        )
        root = f"人工反馈（须优先响应）：{hf[:1200]}"
    elif op:
        summary = "Phase1：已结合运维排障指引与 Prometheus 上下文生成草稿（待 LLM 增强）。"
        root = f"运维指引：{op[:800]}\n（以下为自动占位根因，请复核）\nPhase1 占位：请结合 investigation_notes 人工复核或接入模型推理。"
    else:
        summary = "Phase1：基于 Prometheus `up` 探针与告警上下文的自动草稿（待 LLM 增强）。"
        root = "Phase1 占位：请结合 investigation_notes 人工复核或接入模型推理。"

    proposed = "# Phase1 示例（未批准不得执行）\n# kubectl -n <ns> get pods\n# 或回滚至上一稳定版本\n"
    if hf:
        proposed = (
            f"# 针对审批反馈的调整方向（占位）\n# 反馈摘要：{hf[:400]}\n"
            + proposed
        )
    elif op:
        proposed = f"# 运维指引摘要：{op[:400]}\n" + proposed

    return {
        "diagnosis": snippet,
        "summary": summary,
        "root_cause": root,
        "proposed_action": proposed,
    }


def _node_draft_ticket(state: IncidentGraphState) -> Dict[str, Any]:
    """持久化 Ticket（Draft），供审批台拉取。"""
    from ai_ops.models import Incident, Ticket

    inc = Incident.objects.get(pk=state["incident_id"])
    ticket = Ticket.objects.create(
        incident=inc,
        run_id=state.get("run_id") or "",
        status=Ticket.STATUS_DRAFT,
        summary=state.get("summary") or "",
        root_cause=state.get("root_cause") or "",
        proposed_action=state.get("proposed_action") or "",
    )
    return {"ticket_id": str(ticket.ticket_id)}


def build_compiled_graph(checkpointer: Any):
    """在给定 checkpointer 上编译状态机。"""
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(IncidentGraphState)
    g.add_node("investigate", _node_investigate)
    g.add_node("diagnose", _node_diagnose)
    g.add_node("draft_ticket", _node_draft_ticket)
    g.add_edge(START, "investigate")
    g.add_edge("investigate", "diagnose")
    g.add_edge("diagnose", "draft_ticket")
    g.add_edge("draft_ticket", END)
    return g.compile(checkpointer=checkpointer)


def run_pipeline_for_incident(
    incident_id: int,
    run_id: str,
    *,
    operator_context: Optional[str] = None,
    human_feedback: Optional[str] = None,
) -> Dict[str, Any]:
    """
    同步执行完整图（供 Celery task 调用）。
    返回 run_id、ticket_id；过程中通过 Redis Pub/Sub 推送 graph_node / tool_* 事件。
    """
    from ai_ops.redis_stream import publish_agent_event, redis_url

    oc = (operator_context or "").strip()
    hf = (human_feedback or "").strip()

    publish_agent_event(
        run_id,
        "run_start",
        {
            "incident_id": incident_id,
            "has_operator_context": bool(oc),
            "has_human_feedback": bool(hf),
        },
        incident_id=incident_id,
    )
    if oc:
        publish_agent_event(
            run_id,
            "operator_context",
            {"text": oc[:2000]},
            incident_id=incident_id,
        )
    if hf:
        publish_agent_event(
            run_id,
            "human_feedback",
            {"text": hf[:2000]},
            incident_id=incident_id,
        )

    try:
        from langgraph.checkpoint.redis import RedisSaver
    except ImportError as e:
        raise RuntimeError(
            "缺少 langgraph-checkpoint-redis，或 Python 版本过低；请安装兼容包并保证 Redis 含 JSON/Search 模块。"
        ) from e

    url = redis_url()
    with RedisSaver.from_conn_string(url) as checkpointer:
        checkpointer.setup()
        graph = build_compiled_graph(checkpointer)
        config: Dict[str, Any] = {"configurable": {"thread_id": run_id}}
        init: IncidentGraphState = {
            "incident_id": incident_id,
            "run_id": run_id,
        }
        if oc:
            init["operator_context"] = oc
        if hf:
            init["human_feedback"] = hf
        try:
            try:
                stream_iter = graph.stream(init, config=config, stream_mode="updates")
            except TypeError:
                stream_iter = graph.stream(init, config=config)
            for chunk in stream_iter:
                if not isinstance(chunk, dict):
                    continue
                for node_name, delta in chunk.items():
                    publish_agent_event(
                        run_id,
                        "graph_node",
                        {
                            "node": node_name,
                            "delta_keys": list(delta.keys()) if isinstance(delta, dict) else [],
                        },
                        incident_id=incident_id,
                    )
        except Exception:
            publish_agent_event(
                run_id,
                "error",
                {"phase": "graph_stream"},
                incident_id=incident_id,
            )
            raise

        snap = graph.get_state(config)
        values = getattr(snap, "values", None) or {}
        ticket_id = values.get("ticket_id")

    publish_agent_event(
        run_id,
        "done",
        {"ticket_id": ticket_id, "incident_id": incident_id},
        incident_id=incident_id,
    )
    return {"run_id": run_id, "ticket_id": ticket_id, "incident_id": incident_id}
