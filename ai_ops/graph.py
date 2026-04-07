"""
AIOps Platform — LangGraph 闭环（感知 → 拓扑推断 → 经验库匹配 → 因果诊断 → 工单/自愈路由）。

置信度 ≥ AIOPS_AUTO_HEAL_CONFIDENCE_THRESHOLD 且命中经验库时：生成已批准工单并下发 PlaybookJob 至边缘 go-agent。
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, Optional, TypedDict

from django.conf import settings
from django.db.models import F

logger = logging.getLogger(__name__)


class IncidentGraphState(TypedDict, total=False):
    incident_id: int
    run_id: str
    operator_context: str
    human_feedback: str
    investigation_notes: str
    topology_json: str
    kb_signature: str
    kb_confidence: float
    kb_playbook_snippet: str
    diagnosis: str
    summary: str
    root_cause: str
    proposed_action: str
    impact_scope: Dict[str, Any]
    ticket_id: str
    routing: str


def _node_sense_metrics(state: IncidentGraphState) -> Dict[str, Any]:
    """感知：Prometheus 等只读指标（OS 级细粒度由边缘 Prometheus 承担）。"""
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


def _node_infer_topology(state: IncidentGraphState) -> Dict[str, Any]:
    """动态拓扑：由告警标签推导简化 Service Map（可后续接真实 trace/metrics 图）。"""
    from ai_ops.models import Incident, TopologySnapshot

    inc = Incident.objects.get(pk=state["incident_id"])
    labels = {}
    if isinstance(inc.raw_alert_data, dict):
        labels = inc.raw_alert_data.get("labels") or {}
    ns = labels.get("namespace") or "default"
    svc = labels.get("service") or labels.get("job") or "unknown-service"
    pod = labels.get("pod") or ""
    alert = inc.alert_name or "alert"

    unhealthy = inc.severity in ("critical", "warning")
    nodes = [
        {"id": "cluster", "label": "Cluster", "healthy": True},
        {"id": f"ns:{ns}", "label": f"NS/{ns}", "healthy": not unhealthy},
        {"id": f"svc:{svc}", "label": svc, "healthy": not unhealthy},
    ]
    if pod:
        nodes.append({"id": f"pod:{pod[:48]}", "label": pod[:32], "healthy": not unhealthy})
    edges = [
        {"from": "cluster", "to": f"ns:{ns}"},
        {"from": f"ns:{ns}", "to": f"svc:{svc}"},
    ]
    if pod:
        edges.append({"from": f"svc:{svc}", "to": f"pod:{pod[:48]}"})

    penalty = 15.0 if inc.severity == "critical" else (8.0 if inc.severity == "warning" else 3.0)
    health_score = max(35.0, 100.0 - penalty - (0 if not unhealthy else 12.0))

    TopologySnapshot.objects.update_or_create(
        scope="global",
        defaults={
            "nodes": nodes,
            "edges": edges,
            "health_score": health_score,
        },
    )
    topo_payload = {
        "alert": alert,
        "nodes": nodes,
        "edges": edges,
        "health_score": health_score,
    }
    return {"topology_json": json.dumps(topo_payload, ensure_ascii=False)}


def _node_match_knowledge(state: IncidentGraphState) -> Dict[str, Any]:
    """经验库匹配：签名命中则抬升置信度（简化 Davis 式「已知故障」路径）。"""
    from ai_ops.models import Incident, KnowledgeEntry

    inc = Incident.objects.get(pk=state["incident_id"])
    sig = hashlib.sha256(
        f"{inc.alert_name}|{inc.fingerprint}".encode("utf-8")
    ).hexdigest()[:32]
    entry = KnowledgeEntry.objects.filter(signature_hash=sig).first()
    conf = 0.0
    snippet = ""
    if entry:
        snippet = (entry.playbook_body or "")[:8000]
        conf = min(
            0.99,
            0.40
            + 0.06 * min(entry.hit_count, 10)
            + 0.14 * min(entry.success_after_apply, 5),
        )
        KnowledgeEntry.objects.filter(pk=entry.pk).update(hit_count=F("hit_count") + 1)
    return {
        "kb_signature": sig,
        "kb_confidence": conf,
        "kb_playbook_snippet": snippet,
    }


def _node_causal_analyze(state: IncidentGraphState) -> Dict[str, Any]:
    """因果诊断：融合指标摘要、拓扑上下文与人工反馈（占位实现，可换 LLM）。"""
    notes = state.get("investigation_notes") or ""
    op = (state.get("operator_context") or "").strip()
    hf = (state.get("human_feedback") or "").strip()
    topo = state.get("topology_json") or "{}"
    kb_snip = (state.get("kb_playbook_snippet") or "").strip()
    kb_conf = float(state.get("kb_confidence") or 0.0)

    try:
        topo_obj = json.loads(topo)
    except json.JSONDecodeError:
        topo_obj = {}

    if hf:
        summary = "【被动诊断·反思】已合并审批打回意见，沿拓扑重排假设。"
        root = f"人工反馈（高优）：{hf[:900]}\n关联拓扑片段：{json.dumps(topo_obj, ensure_ascii=False)[:600]}"
    elif op:
        summary = "【被动诊断】结合运维先验与 Service Map 上下文。"
        root = f"运维先验：{op[:500]}\n指标摘录：{notes[:1200]}\n拓扑：{len(topo_obj.get('nodes', []))} 节点"
    else:
        summary = "【被动诊断】基于 Prometheus 与动态拓扑的因果草稿（待模型增强）。"
        root = f"告警链路推断：{topo_obj.get('alert', '?')}\n指标：{notes[:1500]}"

    if kb_snip:
        root += f"\n\n【经验库命中】置信度≈{kb_conf:.2f}；历史 Playbook 摘要：{kb_snip[:400]}…"

    proposed = (
        kb_snip
        if kb_snip
        else "# 标准化处置（示例，未批准不得执行）\n# kubectl -n <ns> describe pod <pod>\n# kubectl rollout restart deploy/<svc>\n"
    )
    if hf:
        proposed = f"# 针对打回的调整\n{proposed[:4000]}"

    impact = {
        "topology": topo_obj,
        "evidence_chars": len(notes),
        "kb_confidence": kb_conf,
    }
    return {
        "diagnosis": notes[:4000],
        "summary": summary,
        "root_cause": root[:8000],
        "proposed_action": proposed[:20000],
        "impact_scope": impact,
    }


def _node_commit_ticket(state: IncidentGraphState) -> Dict[str, Any]:
    """决策与落库：高置信走 auto_heal + PlaybookJob；否则 draft 人工审批。"""
    from ai_ops.models import Incident, PlaybookJob, Ticket

    threshold = float(getattr(settings, "AIOPS_AUTO_HEAL_CONFIDENCE_THRESHOLD", 0.95))
    node_id = getattr(settings, "AIOPS_DEFAULT_PLAYBOOK_NODE", "default")

    conf = float(state.get("kb_confidence") or 0.0)
    routing = "auto_heal" if conf >= threshold else "human_approval"
    script = (state.get("kb_playbook_snippet") or "").strip() or (
        state.get("proposed_action") or ""
    )
    script = script[:50000]

    inc = Incident.objects.get(pk=state["incident_id"])
    impact = state.get("impact_scope") or {}

    if routing == "auto_heal" and script.strip():
        ticket = Ticket.objects.create(
            incident=inc,
            run_id=state.get("run_id") or "",
            status=Ticket.STATUS_APPROVED,
            summary=state.get("summary") or "",
            root_cause=state.get("root_cause") or "",
            proposed_action=state.get("proposed_action") or script,
            ticket_class=Ticket.TICKET_CLASS_REACTIVE,
            impact_scope=impact if isinstance(impact, dict) else {},
            ai_confidence=conf,
            routing="auto_heal",
            auto_heal_dispatched=True,
        )
        PlaybookJob.objects.create(
            target_node_id=node_id,
            ticket=ticket,
            script=script,
            status=PlaybookJob.STATUS_PENDING,
        )
    else:
        ticket = Ticket.objects.create(
            incident=inc,
            run_id=state.get("run_id") or "",
            status=Ticket.STATUS_DRAFT,
            summary=state.get("summary") or "",
            root_cause=state.get("root_cause") or "",
            proposed_action=state.get("proposed_action") or "",
            ticket_class=Ticket.TICKET_CLASS_REACTIVE,
            impact_scope=impact if isinstance(impact, dict) else {},
            ai_confidence=conf,
            routing="knowledge_matched" if conf > 0 else "human_approval",
            auto_heal_dispatched=False,
        )
    return {"ticket_id": str(ticket.ticket_id), "routing": routing}


def build_compiled_graph(checkpointer: Any):
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(IncidentGraphState)
    g.add_node("sense_metrics", _node_sense_metrics)
    g.add_node("infer_topology", _node_infer_topology)
    g.add_node("match_knowledge", _node_match_knowledge)
    g.add_node("causal_analyze", _node_causal_analyze)
    g.add_node("commit_ticket", _node_commit_ticket)
    g.add_edge(START, "sense_metrics")
    g.add_edge("sense_metrics", "infer_topology")
    g.add_edge("infer_topology", "match_knowledge")
    g.add_edge("match_knowledge", "causal_analyze")
    g.add_edge("causal_analyze", "commit_ticket")
    g.add_edge("commit_ticket", END)
    return g.compile(checkpointer=checkpointer)


def run_pipeline_for_incident(
    incident_id: int,
    run_id: str,
    *,
    operator_context: Optional[str] = None,
    human_feedback: Optional[str] = None,
) -> Dict[str, Any]:
    from ai_ops.redis_stream import publish_agent_event

    oc = (operator_context or "").strip()
    hf = (human_feedback or "").strip()

    publish_agent_event(
        run_id,
        "run_start",
        {
            "incident_id": incident_id,
            "has_operator_context": bool(oc),
            "has_human_feedback": bool(hf),
            "pipeline": "sense→topology→knowledge→causal→commit",
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

    url = __import__("ai_ops.redis_stream", fromlist=["redis_url"]).redis_url()
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
