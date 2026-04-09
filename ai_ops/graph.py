"""
AIOps Platform — 异步诊断管线：M2M 协议（<EXECUTE>/<TICKET>）+ 工具执行 → 落库工单。

Celery 任务名仍保留 ``ai_ops.run_incident_langgraph``；实际为 ``run_pipeline_for_incident`` +
``run_react_diagnosis_loop``，不依赖 LangGraph StateGraph。

平台侧汇总「软上下文」（拓扑、经验库、可选接入层流量、服务目录）注入模型。
经验库置信度 ≥ AIOPS_AUTO_HEAL_CONFIDENCE_THRESHOLD 且存在 Playbook 时：生成已批准工单并下发 PlaybookJob。
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


def _alert_labels(inc: Any) -> Dict[str, Any]:
    raw = inc.raw_alert_data or {}
    labels = raw.get("labels") if isinstance(raw, dict) else None
    return dict(labels) if isinstance(labels, dict) else {}


def _labels_readable(labels: Dict[str, Any], limit: int = 28) -> str:
    if not labels:
        return "（当前告警未带 labels，请到 Alertmanager 原始 JSON 中核对。）"
    lines = []
    for i, (k, v) in enumerate(sorted(labels.items())):
        if i >= limit:
            lines.append(f"  · … 另有 {len(labels) - limit} 项未列出")
            break
        lines.append(f"  · {k}: {v}")
    return "\n".join(lines)


def _evidence_brief_from_prometheus_notes(notes: str, max_series: int = 12) -> str:
    """Turn Prometheus JSON into short Chinese lines; avoid pasting raw JSON as root cause."""
    s = (notes or "").strip()
    if not s or s == "{}":
        return (
            "（本轮未获取到有效的 Prometheus 指标正文；请检查环境变量 PROMETHEUS_URL、"
            "网络连通，以及平台是否有查询权限。）"
        )
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        clip = s[:900] + ("…" if len(s) > 900 else "")
        return f"指标接口返回了非 JSON 文本，前 900 字摘录如下（请到 Prometheus 控制台核对）：\n{clip}"

    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        inner = data["data"]
        rtype = inner.get("resultType") or "unknown"
        results = inner.get("result")
        if not isinstance(results, list):
            return f"Prometheus 返回结构异常：resultType={rtype}，result 非列表。"
        n = len(results)
        lines = [
            f"本轮查询结果类型：{rtype}；时间序列条数：{n}。",
            "下列为前若干条序列的标签摘要（不是根因结论，仅作取证）：",
        ]
        for i, item in enumerate(results[:max_series]):
            if not isinstance(item, dict):
                lines.append(f"  {i + 1}. {str(item)[:160]}")
                continue
            metric = item.get("metric") or {}
            parts = [f"{k}={v}" for k, v in list(metric.items())[:8]]
            lbl = ", ".join(parts) if parts else str(item)[:120]
            lines.append(f"  {i + 1}. {lbl}")
        if n > max_series:
            lines.append(f"  … 另有 {n - max_series} 条序列未展开，请在 Prometheus Expression 浏览器查看完整结果。")
        return "\n".join(lines)

    if isinstance(data, list):
        return f"返回 JSON 数组，长度 {len(data)}；首元素摘要：{str(data[0])[:240]}…"

    keys = list(data.keys())[:16] if isinstance(data, dict) else []
    return f"已收到结构化 JSON，顶层键：{keys}"


def _problem_statement_cn(inc: Any) -> str:
    parts = [
        f"告警名称：{inc.alert_name}",
        f"严重级别：{inc.severity}",
        f"事件在平台中的状态：{inc.status}",
    ]
    desc = (getattr(inc, "description", None) or "").strip()
    if desc:
        tail = "…" if len(desc) > 480 else ""
        parts.append(f"告警描述（摘录）：{desc[:480]}{tail}")
    return "\n".join(parts)


def _troubleshooting_runbook_cn(inc: Any, topo_obj: Dict[str, Any], notes: str) -> tuple[str, str, str]:
    """
    (summary, root_cause, proposed_action) for passive / placeholder pipeline.
    root_cause = 问题说明 + 分步排障（中文）；proposed_action = 只读阶段 vs 变更阶段。
    """
    labels = _alert_labels(inc)
    ns = (labels.get("namespace") or "").strip() or "<命名空间>"
    pod = (labels.get("pod") or "").strip() or "<Pod 名称>"
    svc = (
        (labels.get("service") or labels.get("job") or "").strip() or "<工作负载/Service>"
    )
    alert = topo_obj.get("alert") or inc.alert_name

    evidence = _evidence_brief_from_prometheus_notes(notes)

    summary = (
        "【被动诊断】已根据告警与一轮只读指标拉取，生成「问题说明 + 中文分步排障草案」。"
        "下方「根因」字段承载的是排查路线与已知事实，不是 LLM 最终定因；"
        "AI 置信度为经验库命中分值，未命中时为 0 属正常，不代表接口故障。"
    )

    root = f"""【一、问题说明（当前已知事实）】
{_problem_statement_cn(inc)}

【二、关键标签（用于对齐监控与集群对象）】
{_labels_readable(labels)}

【三、分步排查（均为只读；不需要为「查询 / 描述」类操作单独提交变更工单）】

第一步：确认告警与影响面
· 需要的数据：Alertmanager 中该告警的 annotations、当前 firing 时间线。
· 权限：告警平台只读即可。
· 建议动作：在监控中打开关联 dashboard，确认是否与发布、扩缩容、节点异常同时发生。

第二步：核对 Kubernetes 工作负载（只读）
· 需要的数据：命名空间 `{ns}`、Pod `{pod}`、相关 Deployment/StatefulSet 名称。
· 权限：命名空间级 `get/list/watch`（Pod、Service、Endpoints、Event）即可。
· 建议命令（将占位符替换为实际上下文；仅查询，不修改集群）：
  kubectl get pods -n {ns} -o wide
  kubectl describe pod -n {ns} {pod}
  kubectl get svc,endpoints -n {ns}
  kubectl get events -n {ns} --sort-by='.lastTimestamp' | tail -n 30

第三步：对照 Prometheus 指标（只读）
· 需要的数据：与告警规则一致的 PromQL，或 `up`、`kube_pod_status_*` 等辅助指标。
· 权限：Prometheus HTTP API 查询权限（本平台的 query_prometheus 工具同源）。
· 建议：在 Prometheus UI 用与告警相同的表达式复现；关注 `up{{...}}=0`、目标缺失、 scrape 失败等。

第四步（可选）：节点与 DNS 等基础设施
· 若告警涉及 `node-local-dns`、`kube-proxy` 等，补充：
  kubectl get nodes -o wide
  kubectl -n kube-system get pods -o wide

【四、若 kubectl / API 返回 Forbidden（权限不足）】
请先由集群管理员为你的身份绑定只读角色，授权完成后再重复第二步、第三步。

集群级只读（示例，将用户名换成你的登录名或公司 IdP 主体）：
  kubectl create clusterrolebinding aiops-readonly-$USER \\
    --clusterrole=view \\
    --user=<你的用户名>

仅单个命名空间只读（示例）：
  kubectl -n {ns} create rolebinding aiops-ns-readonly-$USER \\
    --clusterrole=view \\
    --user=<你的用户名>

校验是否已有权限：
  kubectl auth can-i list pods -n {ns}

ServiceAccount 场景可将 `--user=` 换为 `--group=` 或使用 `rolebinding --serviceaccount=ns:sa`。

【五、指标摘录（条带化摘要，非最终根因结论）】
{evidence}
"""

    proposed = f"""--- 阶段 A：只读排查（查询、describe、日志拉取、Prometheus 查询）---
说明：上述操作不改变集群状态，不需要走「变更类」工单审批流程；在控制台或本页工具中执行即可。

建议在本阶段完成的命令（与上文一致，便于复制）：
  kubectl get pods -n {ns} -o wide
  kubectl describe pod -n {ns} {pod}
  kubectl get events -n {ns} --sort-by='.lastTimestamp' | tail -n 40

--- 阶段 B：拟定变更 / 修复（可能重启、删 Pod、改配置）---
说明：只有在你确认根因、且需要**改变**集群或应用状态时，才应提交工单并等待人工批准后再执行；未批准不得在生产环境操作。

示例（占位符须替换为真实对象；执行前请经变更评审）：
  # kubectl -n {ns} rollout restart deployment/<deployment-name>
  # kubectl -n {ns} delete pod {pod}   # 谨慎：会触发重建

请根据阶段 A 的只读结论，把 `<deployment-name>` 等替换为实际资源名后再写入正式变更单。
"""

    return summary, root.strip(), proposed.strip()


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
    """因果诊断：中文分步排障 + 指标条带化摘要（占位管线；可换 LLM）。"""
    from ai_ops.models import Incident

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

    inc = Incident.objects.get(pk=state["incident_id"])
    summary, root, proposed = _troubleshooting_runbook_cn(inc, topo_obj, notes)

    if hf:
        summary = "【被动诊断·含审批打回意见】以下在标准排障之上叠加人工反馈，请优先核实。"
        root = (
            f"【优先：人工反馈】\n{hf[:2000]}\n\n"
            f"【拓扑上下文（结构化）】告警：{topo_obj.get('alert', '?')}；"
            f"Service Map 节点数：{len(topo_obj.get('nodes', []))}\n\n"
            f"{root}"
        )
    elif op:
        summary = "【被动诊断·含运维先验】已合并你在发起诊断时填写的先验信息。"
        root = f"【运维先验】\n{op[:1200]}\n\n{root}"

    if kb_snip:
        root += (
            f"\n\n【经验库命中】模型置信度分值≈{kb_conf:.2f}（用于自动愈合阈值判断）。"
            f"历史 Playbook 摘录（可纳入阶段 B 变更评审）：\n{kb_snip[:6000]}"
        )
        proposed = (
            f"{proposed}\n\n--- 经验库建议脚本 / 片段（须经审批后执行）---\n{kb_snip[:12000]}"
        )

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


def _observability_traffic_snippet() -> str:
    """接入层 / 边缘日志聚合摘要，注入 Agent 软上下文（失败则静默跳过）。"""
    try:
        from observability.aggregate import summarize_stream
        from observability.models import LogStream

        sk = (getattr(settings, "AIOPS_OBSERVABILITY_STREAM_KEY_FOR_INCIDENTS", "") or "").strip()
        if not sk:
            first = LogStream.objects.order_by("-last_event_at").first()
            if not first:
                return ""
            sk = first.stream_key
        s = summarize_stream(sk, window_minutes=60)
        d = s.to_dict()
        lines = [
            f"【接入层流量摘要·stream={sk}·近 {d['window_minutes']}m】",
            f"总请求 {d['total']}，错误 {d['errors']}，错误率 {d['error_rate']:.4f}，QPS≈{d['qps']:.4f}",
            f"延迟 ms p50/p95/p99: {d.get('latency_ms')}",
        ]
        top5 = d.get("top_paths_5xx") or []
        if top5:
            lines.append("5xx 较多 path（Top）: " + json.dumps(top5[:5], ensure_ascii=False)[:1200])
        return "\n".join(lines)[:4500]
    except Exception:
        logger.debug("observability traffic snippet skipped", exc_info=True)
        return ""


def _service_catalog_snippet() -> str:
    raw = (getattr(settings, "AIOPS_SERVICE_CATALOG_JSON", "") or "").strip()
    if not raw:
        return ""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return "【服务目录】配置 AIOPS_SERVICE_CATALOG_JSON 非合法 JSON，已忽略。\n"
    if isinstance(obj, list):
        clip = json.dumps(obj, ensure_ascii=False)[:6000]
        return f"【服务目录（轻量）】\n{clip}\n"
    if isinstance(obj, dict):
        clip = json.dumps(obj, ensure_ascii=False)[:6000]
        return f"【服务目录（轻量）】\n{clip}\n"
    return ""


def gather_soft_context(incident_id: int) -> Dict[str, Any]:
    """供大模型参考的拓扑 / 经验库 / 流量 / 服务目录摘要（非强制步骤）。"""
    st_topo = _node_infer_topology({"incident_id": incident_id, "run_id": ""})
    st_kb = _node_match_knowledge({"incident_id": incident_id, **st_topo})
    topo_json = st_topo.get("topology_json") or "{}"
    try:
        topology_obj = json.loads(topo_json)
    except json.JSONDecodeError:
        topology_obj = {}
    kb_conf = float(st_kb.get("kb_confidence") or 0.0)
    kb_snip = (st_kb.get("kb_playbook_snippet") or "").strip()
    parts: list[str] = []
    if topo_json.strip() and topo_json.strip() != "{}":
        parts.append("【拓扑草图（由告警标签推导）】\n" + topo_json[:6000])
    if kb_snip:
        parts.append(f"【经验库命中参考】置信度约 {kb_conf:.2f}，摘录：\n{kb_snip[:6000]}")
    obs = _observability_traffic_snippet()
    if obs:
        parts.append(obs)
    cat = _service_catalog_snippet()
    if cat:
        parts.append(cat)
    text = "\n\n".join(parts)
    return {
        "text": text,
        "topology_obj": topology_obj,
        "kb_confidence": kb_conf,
        "kb_playbook_snippet": kb_snip,
        "kb_signature": st_kb.get("kb_signature") or "",
    }


def create_interactive_ticket(
    incident: Any,
    run_id: str,
    final: Optional[Dict[str, Any]],
    ctx: Dict[str, Any],
) -> Any:
    """由互动诊断结论生成工单：成功时根因 + 可执行修复命令；失败时引导重试。"""
    from ai_ops.models import AnalysisReport, PlaybookJob, Ticket

    threshold = float(getattr(settings, "AIOPS_AUTO_HEAL_CONFIDENCE_THRESHOLD", 0.95))
    node_id = getattr(settings, "AIOPS_DEFAULT_PLAYBOOK_NODE", "default")
    kb_conf = float(ctx.get("kb_confidence") or 0.0)
    kb_snip = (ctx.get("kb_playbook_snippet") or "").strip()
    topology_obj = ctx.get("topology_obj") if isinstance(ctx.get("topology_obj"), dict) else {}

    if final:
        enum_c = str((final.get("confidence") or "low")).lower()
        model_score = {"high": 0.88, "medium": 0.62, "low": 0.35}.get(enum_c, 0.35)
        conf = max(kb_conf, model_score)
        summary = (final.get("incident_summary") or "").strip() or f"【交互诊断】{incident.alert_name}"
        root = (final.get("root_cause") or "").strip()
        mit = [str(x).strip() for x in (final.get("mitigation_commands") or []) if str(x).strip()]
        proposed_parts = [
            "【审批通过后可执行的修复命令（逐条执行前请再次确认变更窗口与影响面）】",
        ]
        if mit:
            proposed_parts.append("\n".join(f"{i + 1}. {c}" for i, c in enumerate(mit)))
        else:
            proposed_parts.append(
                "（模型未给出明确变更命令：请核对根因是否写明「不足以出具工单」，或补充证据后重新发起诊断。）"
            )
        prev = final.get("prevention") or []
        if prev:
            proposed_parts.append("\n【加固与预防（非紧急）】\n" + "\n".join(str(p) for p in prev))
        if kb_snip:
            proposed_parts.append("\n【经验库对照片段】\n" + kb_snip[:8000])
        proposed = "\n".join(proposed_parts)

        impact: Dict[str, Any] = {
            "topology": topology_obj,
            "kb_confidence": kb_conf,
            "model_confidence_enum": enum_c,
            "evidence_chain": final.get("evidence_chain"),
        }

        use_auto = kb_conf >= threshold and bool(kb_snip)
        script = kb_snip if use_auto else ""

        if use_auto and script.strip():
            ticket = Ticket.objects.create(
                incident=incident,
                run_id=run_id,
                status=Ticket.STATUS_APPROVED,
                summary=summary,
                root_cause=root,
                proposed_action=proposed[:50000],
                ticket_class=Ticket.TICKET_CLASS_REACTIVE,
                impact_scope=impact,
                ai_confidence=conf,
                routing="auto_heal",
                auto_heal_dispatched=True,
            )
            PlaybookJob.objects.create(
                target_node_id=node_id,
                ticket=ticket,
                script=script[:50000],
                status=PlaybookJob.STATUS_PENDING,
            )
            return ticket

        ticket = Ticket.objects.create(
            incident=incident,
            run_id=run_id,
            status=Ticket.STATUS_DRAFT,
            summary=summary,
            root_cause=root,
            proposed_action=proposed[:50000],
            ticket_class=Ticket.TICKET_CLASS_REACTIVE,
            impact_scope=impact,
            ai_confidence=conf,
            routing="interactive_diagnosis",
            auto_heal_dispatched=False,
        )
        return ticket

    impact_fail: Dict[str, Any] = {
        "topology": topology_obj,
        "kb_confidence": kb_conf,
    }
    rep = AnalysisReport.objects.filter(incident=incident).first()
    phen = (rep.phenomenon or "").strip() if rep else ""
    if phen == "未启动分析":
        return Ticket.objects.create(
            incident=incident,
            run_id=run_id,
            status=Ticket.STATUS_DRAFT,
            summary="【无法启动交互诊断】AI 未开启或未配置有效 Key",
            root_cause=(rep.root_cause if rep else "")[:8000] or "请查看 AI 配置后重试。",
            proposed_action=(
                "在后台「AI 配置」中开启分析开关并填写 API Key 与模型后，重新发起异步诊断。"
            ),
            ticket_class=Ticket.TICKET_CLASS_REACTIVE,
            impact_scope=impact_fail,
            ai_confidence=0.0,
            routing="human_approval",
            auto_heal_dispatched=False,
        )

    return Ticket.objects.create(
        incident=incident,
        run_id=run_id,
        status=Ticket.STATUS_DRAFT,
        summary="【交互诊断未完成】尚无可直接执行的修复工单",
        root_cause=(
            "大模型未在系统限制内提交完整结论，或工具/API 异常。"
            "请查看同步分析报告与「历史 Agent 轨迹」中的 Observation。"
        ),
        proposed_action=(
            "1）核对 AI 配置、Prometheus/K8s 只读连通与权限；"
            "2）适当提高 Agent 最大轮次与工具次数后重新发起诊断；"
            "3）具备证据后由人工编写变更命令并走工单审批。"
        ),
        ticket_class=Ticket.TICKET_CLASS_REACTIVE,
        impact_scope=impact_fail,
        ai_confidence=0.0,
        routing="human_approval",
        auto_heal_dispatched=False,
    )


def run_pipeline_for_incident(
    incident_id: int,
    run_id: str,
    *,
    operator_context: Optional[str] = None,
    human_feedback: Optional[str] = None,
    trigger_source: str = "manual",
    create_ticket: bool = True,
    celery_task_id: str = "",
) -> Dict[str, Any]:
    from django.utils import timezone as dj_tz

    from ai_ops.approval_policy import evaluate_ticket_after_creation
    from ai_ops.brain.ticket_manager import TicketManager
    from ai_ops.models import AgentRun, Incident, Ticket
    from ai_ops.notifications import notify_incident_ticket_event
    from ai_ops.redis_stream import publish_agent_event
    from ai_ops.services.sre_agent import run_react_diagnosis_loop

    oc = (operator_context or "").strip()
    hf = (human_feedback or "").strip()
    src_key = (trigger_source or "manual").strip().lower()
    source_map = {
        "webhook": AgentRun.SOURCE_WEBHOOK,
        "manual": AgentRun.SOURCE_MANUAL,
        "rejection_retry": AgentRun.SOURCE_REJECTION_RETRY,
    }
    ar_source = source_map.get(src_key, AgentRun.SOURCE_MANUAL)

    ar: AgentRun | None = None
    try:
        ar, _ = AgentRun.objects.get_or_create(
            run_id=run_id,
            defaults={
                "incident_id": incident_id,
                "source": ar_source,
                "status": AgentRun.STATUS_QUEUED,
            },
        )
        ar.incident_id = incident_id
        ar.source = ar_source
        ar.status = AgentRun.STATUS_RUNNING
        if celery_task_id:
            ar.celery_task_id = celery_task_id
        ar.error_message = ""
        ar.finished_at = None
        ar.ticket = None
        ar.save(
            update_fields=[
                "incident_id",
                "source",
                "status",
                "celery_task_id",
                "error_message",
                "finished_at",
                "ticket",
            ]
        )
    except Exception:
        logger.exception("AgentRun bookkeeping failed run_id=%s", run_id)

    publish_agent_event(
        run_id,
        "run_start",
        {
            "incident_id": incident_id,
            "has_operator_context": bool(oc),
            "has_human_feedback": bool(hf),
            "pipeline": "m2m_react→ticket",
            "trigger_source": ar_source,
            "create_ticket": create_ticket,
        },
        incident_id=incident_id,
    )

    if getattr(settings, "AIOPS_NOTIFY_ON_RUN_START", False):
        inc0 = Incident.objects.filter(pk=incident_id).first()
        if inc0:
            notify_incident_ticket_event(
                event="run_start",
                incident_id=incident_id,
                alert_name=inc0.alert_name,
                run_id=run_id,
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
        ctx = gather_soft_context(incident_id)
        incident = Incident.objects.get(pk=incident_id)
        publish_agent_event(
            run_id,
            "graph_node",
            {
                "node": "平台软上下文（拓扑 / 经验库 / 流量 / 服务目录）",
                "delta_keys": [
                    f"kb_confidence={ctx.get('kb_confidence', 0):.2f}",
                    f"has_kb_snippet={bool((ctx.get('kb_playbook_snippet') or '').strip())}",
                ],
            },
            incident_id=incident_id,
        )

        final = run_react_diagnosis_loop(
            incident,
            run_id=run_id,
            operator_context=oc,
            human_feedback=hf,
            soft_context=ctx.get("text") or "",
        )
        incident.refresh_from_db()

        ticket: Ticket | None = None
        ticket_id = ""
        if create_ticket:
            ticket = create_interactive_ticket(incident, run_id, final, ctx)
            ticket_id = str(ticket.ticket_id)

            if getattr(settings, "AIOPS_NOTIFY_ON_TICKET_EVENTS", True):
                notify_incident_ticket_event(
                    event="ticket_created",
                    incident_id=incident_id,
                    alert_name=incident.alert_name,
                    run_id=run_id,
                    ticket_id=ticket_id,
                    extra={"status": ticket.status, "routing": ticket.routing},
                )

            if ticket.status == Ticket.STATUS_DRAFT:
                action = evaluate_ticket_after_creation(
                    ticket,
                    incident,
                    final,
                    from_webhook=(ar_source == AgentRun.SOURCE_WEBHOOK),
                )
                if action == "submit_pending":
                    TicketManager.submit_for_approval(ticket.ticket_id)
                    ticket.refresh_from_db()
                    notify_incident_ticket_event(
                        event="pending_approval",
                        incident_id=incident_id,
                        alert_name=incident.alert_name,
                        run_id=run_id,
                        ticket_id=ticket_id,
                    )
                elif action == "auto_approve":
                    TicketManager.policy_auto_approve(
                        ticket.ticket_id, comment="policy:auto_low_risk"
                    )
                    ticket.refresh_from_db()
                    notify_incident_ticket_event(
                        event="auto_approved",
                        incident_id=incident_id,
                        alert_name=incident.alert_name,
                        run_id=run_id,
                        ticket_id=ticket_id,
                    )
        else:
            publish_agent_event(
                run_id,
                "graph_node",
                {"node": "已跳过工单落库（AIOPS_AUTO_CREATE_TICKET_ON_ALERT=false 或等价）", "delta_keys": []},
                incident_id=incident_id,
            )

        publish_agent_event(
            run_id,
            "done",
            {
                "ticket_id": ticket_id,
                "incident_id": incident_id,
                "skipped_ticket": not create_ticket,
            },
            incident_id=incident_id,
        )

        if ar:
            ar.status = AgentRun.STATUS_SUCCEEDED
            ar.ticket = ticket
            ar.meta = {
                "create_ticket": create_ticket,
                "ticket_status": ticket.status if ticket else None,
            }
            ar.finished_at = dj_tz.now()
            ar.save(update_fields=["status", "ticket", "meta", "finished_at"])

        return {
            "run_id": run_id,
            "ticket_id": ticket_id,
            "incident_id": incident_id,
            "skipped_ticket": not create_ticket,
        }
    except Exception as exc:
        if ar:
            ar.status = AgentRun.STATUS_FAILED
            ar.error_message = str(exc)[:2000]
            ar.finished_at = dj_tz.now()
            ar.save(update_fields=["status", "error_message", "finished_at"])
        incf = Incident.objects.filter(pk=incident_id).first()
        notify_incident_ticket_event(
            event="run_failed",
            incident_id=incident_id,
            alert_name=incf.alert_name if incf else "",
            run_id=run_id,
            extra={"error": str(exc)[:800]},
        )
        raise
