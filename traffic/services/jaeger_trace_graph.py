"""
从 Jaeger UI JSON 的一条 Trace 构造成 ECharts graph（力导向）数据。

节点按「服务 + 中间件/对端」聚合成少量点，同服务多 span 收拢；DB/Redis/MQ 等带 peer 的 span 单独成点，避免蛛网爆炸。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_MAX_SPANS_IN = 400
_MAX_GRAPH_NODES = 80
_MAX_GRAPH_LINKS = 200


def _tag_map(sp: dict) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for t in sp.get("tags") or []:
        if not isinstance(t, dict):
            continue
        k = t.get("key")
        v = t.get("value")
        if k is not None and v is not None:
            out[str(k)] = str(v)
    return out


def _parent_id(sp: dict) -> Optional[str]:
    for r in sp.get("references") or []:
        if not isinstance(r, dict):
            continue
        rt = str(r.get("refType", "")).upper()
        if "CHILD" in rt:
            psid = r.get("spanID")
            if psid is not None and str(psid) not in ("0", "0" * 16, ""):
                return str(psid)
    p = sp.get("parentSpanID")
    if p is not None and str(p) not in ("0", "0" * 16, ""):
        return str(p)
    return None


def _infer_category(tg: Dict[str, str], service: str, op: str) -> Tuple[str, int]:
    """(kind, categoryIndex for echarts)"""
    op_l = (op or "").lower()
    svc = (service or "").lower()
    dbs = (tg.get("db.system") or tg.get("db.type") or "").lower()
    if dbs in ("mysql", "mariadb", "postgresql", "postgres", "clickhouse", "cassandra"):
        return "db", 1
    if dbs in ("redis",) or "redis" in svc or "redis" in op_l:
        return "redis", 2
    if dbs in ("mongodb", "mongo") or "mongo" in op_l or "mongo" in svc:
        return "mongo", 3
    ms = (tg.get("messaging.system") or tg.get("messaging.destination") or "").lower()
    if ms or "kafka" in op_l or "rabbit" in op_l or "mq" in op_l:
        return "mq", 4
    if tg.get("http.url") or tg.get("http.method") or "grpc" in op_l or "/api" in op_l:
        return "http", 0
    if tg.get("peer.service") or tg.get("db.name") or tg.get("db.statement") or dbs:
        return "db", 1
    if "tcp" in op_l or "connect" in op_l:
        return "remote", 0
    return "other", 5


def _peer_line(tg: Dict[str, str]) -> str:
    for k in (
        "peer.service",
        "net.peer.name",
        "db.name",
        "db.instance",
        "messaging.destination",
    ):
        v = (tg.get(k) or "").strip()
        if v:
            return v[:48]
    return ""


def _service_of(s: dict, processes: Any) -> str:
    pid = s.get("processID") or s.get("processId") or "p1"
    pr = processes.get(pid) if isinstance(processes, dict) else None
    if not isinstance(pr, dict):
        return "?"
    return (pr.get("serviceName") or "?")[:64]


def _graph_node_id(s: dict, processes: Any) -> Tuple[str, int, str]:
    """
    聚合同一服务为单点；中间件/存储用 peer 拆成独立点，便于蛛网可读。
    返回 (node_id, category, 展示名多行).
    """
    svc = _service_of(s, processes)
    op = str(s.get("operationName") or "")
    if len(op) > 80:
        op = op[:77] + "..."
    tg = _tag_map(s)
    kind, cat = _infer_category(tg, svc, op)
    peer = _peer_line(tg)
    if kind in ("db", "redis", "mongo", "mq"):
        if peer:
            nid = f"ext:{kind}:{peer[:72]}"
            name = f"{peer}\n{kind}"
        else:
            nid = f"{svc}::{kind}"
            name = f"{svc}\n({kind})"
        return nid, cat, name
    nid = f"srv:{svc}"
    return nid, cat, svc


def _build_collapsed_graph(
    by_id: Dict[str, dict], processes: Any, spans: List[dict]
) -> Tuple[List[dict], List[dict]]:
    """同服务/同对端合并为少量节点与边；边上累计调用次数与最大子 span 耗时。"""
    node_acc: Dict[str, Dict[str, Any]] = {}
    for s in spans:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("spanID", ""))
        if not sid:
            continue
        nid, cat, label = _graph_node_id(s, processes)
        dur = int(s.get("duration", 0)) / 1000.0
        if nid not in node_acc:
            node_acc[nid] = {
                "id": nid,
                "name": label,
                "category": int(cat),
                "duration_ms": round(dur, 4),
                "span_count": 1,
            }
        else:
            a = node_acc[nid]
            a["duration_ms"] = round(max(float(a["duration_ms"]), dur), 4)
            a["span_count"] = int(a["span_count"]) + 1

    link_m: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for s in spans:
        if not isinstance(s, dict):
            continue
        p = _parent_id(s)
        if not p or p not in by_id:
            continue
        k1 = _graph_node_id(by_id[p], processes)[0]
        k2 = _graph_node_id(s, processes)[0]
        if k1 == k2:
            continue
        dur = int(s.get("duration", 0)) / 1000.0
        t = (k1, k2)
        if t not in link_m:
            link_m[t] = {"max_ms": dur, "count": 1, "sum_ms": dur}
        else:
            lm = link_m[t]
            lm["count"] = int(lm["count"]) + 1
            lm["max_ms"] = max(float(lm["max_ms"]), dur)
            lm["sum_ms"] = float(lm["sum_ms"]) + dur

    # 截断：边数优先截断（按 max_ms 降序保留）
    link_items = sorted(link_m.items(), key=lambda x: -x[1]["max_ms"])
    if len(link_items) > _MAX_GRAPH_LINKS:
        link_items = link_items[:_MAX_GRAPH_LINKS]
    used_ids: Set[str] = set()
    ulinks: List[dict] = []
    for (a, b), lm in link_items:
        used_ids.add(a)
        used_ids.add(b)
        cnt = int(lm["count"])
        mx = round(float(lm["max_ms"]), 3)
        sm = round(float(lm["sum_ms"]), 2)
        label = f"{cnt}× max {mx}ms"
        if cnt > 1:
            label += f"\nΣ {sm}ms"
        ulinks.append(
            {
                "source": a,
                "target": b,
                "value": mx,
                "label": label,
            }
        )

    nodes_list = list(node_acc.values())
    nodes_list.sort(
        key=lambda x: -float(x.get("duration_ms", 0) or 0) * max(1, int(x.get("span_count", 1) or 1))
    )
    if len(nodes_list) > _MAX_GRAPH_NODES:
        keep = {n["id"] for n in nodes_list[:_MAX_GRAPH_NODES]}
        nodes_list = [n for n in node_acc.values() if n["id"] in keep]
        ulinks = [x for x in ulinks if x["source"] in keep and x["target"] in keep]

    for n in nodes_list:
        sc = int(n.get("span_count") or 1)
        if sc > 1:
            n["name"] = f"{n['name']}\n{sc} spans · max {n['duration_ms']} ms"
        else:
            n["name"] = f"{n['name']}\n{n['duration_ms']} ms"

    return nodes_list, ulinks


def build_trace_graph_payload(t: dict) -> Dict[str, Any]:
    """
    输出: { nodes, links, categories, truncated } — 力导向蛛网，节点已按服务/中间件聚合。
    """
    processes = t.get("processes") or {}
    spans = t.get("spans") or []
    if not isinstance(spans, list) or not spans:
        return {
            "nodes": [],
            "links": [],
            "categories": [
                {"name": "http/rpc"},
                {"name": "db/sql"},
                {"name": "redis"},
                {"name": "mongo"},
                {"name": "mq"},
                {"name": "other"},
            ],
            "truncated": False,
        }

    truncated = len(spans) > _MAX_SPANS_IN
    if truncated:
        spans = spans[:_MAX_SPANS_IN]

    by_id: Dict[str, dict] = {}
    for s in spans:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("spanID", ""))
        if not sid:
            continue
        by_id[sid] = s

    nodes, ulinks = _build_collapsed_graph(by_id, processes, list(by_id.values()))

    return {
        "nodes": nodes,
        "links": ulinks,
        "categories": [
            {"name": "http/rpc"},
            {"name": "db/sql"},
            {"name": "redis"},
            {"name": "mongo"},
            {"name": "mq"},
            {"name": "other"},
        ],
        "truncated": truncated,
    }


def sanitize_trace_id(raw: str) -> Optional[str]:
    s = (raw or "").strip()
    s = re.sub(r"[^0-9a-fA-F]", "", s)
    if len(s) < 8 or len(s) > 32:
        return None
    return s.lower()
