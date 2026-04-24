"""
从 Jaeger UI JSON 的一条 Trace 构造成「(span 为节点、父子为边)」的链路图数据，供 ECharts graph 使用。

中间件（Redis、各类 DB、MQ 等）通常体现为子 span 或带 db.system / peer 等 tag，会单独成节点并归类着色。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_MAX_NODES = 400


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


def _build_waterfall_payload(by_id: Dict[str, dict], processes: Any) -> Dict[str, Any]:
    """
    按调用树前序遍历，一行一个 span，横轴为相对 trace 起点的毫秒，便于用 Gantt/瀑布图人类阅读。
    """
    if not by_id:
        return {"rows": [], "trace_duration_ms": 0.0}
    t_starts: List[int] = []
    t_ends: List[int] = []
    for s in by_id.values():
        st = int(s.get("startTime", 0) or 0)
        du = int(s.get("duration", 0) or 0)
        t_starts.append(st)
        t_ends.append(st + max(0, du))
    t_min = min(t_starts) if t_starts else 0
    t_max = max(t_ends) if t_ends else t_min
    trace_duration_ms = (t_max - t_min) / 1000.0 if t_max >= t_min else 0.0
    if trace_duration_ms <= 0 and by_id:
        trace_duration_ms = max(0.001, max(int(s.get("duration", 0) or 0) for s in by_id.values()) / 1000.0)

    children: Dict[str, List[str]] = {}
    roots: List[str] = []
    for sid, s in by_id.items():
        p = _parent_id(s)
        if p and p in by_id:
            children.setdefault(p, []).append(sid)
        else:
            roots.append(sid)

    def cstart(x: str) -> int:
        return int(by_id[x].get("startTime", 0) or 0)

    for p in list(children.keys()):
        children[p].sort(key=cstart)
    roots.sort(key=cstart)
    if not roots:
        roots = sorted(by_id.keys(), key=cstart)

    rows: List[Dict[str, Any]] = []
    y_index = 0

    def walk(sid: str, depth: int) -> None:
        nonlocal y_index
        s = by_id[sid]
        op = s.get("operationName") or "span"
        if len(str(op)) > 120:
            op = str(op)[:117] + "..."
        svc = _service_of(s, processes)
        tg = _tag_map(s)
        _kind, cat = _infer_category(tg, svc, str(op))
        peer = _peer_line(tg)
        dur = int(s.get("duration", 0)) / 1000.0
        st0 = int(s.get("startTime", 0) or 0)
        start_ms = (st0 - t_min) / 1000.0
        end_ms = start_ms + max(0.0, dur)
        d_show = min(depth, 12)
        indent = "· " * d_show
        op_short = (str(op) if len(str(op)) <= 56 else str(op)[:53] + "…")
        if peer:
            label = f"{indent}{svc} – {op_short}  ({peer})"
        else:
            label = f"{indent}{svc} – {op_short}"
        if len(label) > 100:
            label = label[:97] + "…"
        rows.append(
            {
                "y_index": y_index,
                "depth": depth,
                "span_id": sid,
                "start_ms": round(start_ms, 4),
                "end_ms": round(end_ms, 4),
                "duration_ms": round(dur, 4),
                "label": label,
                "service": svc,
                "operation": op,
                "peer": peer,
                "kind": _kind,
                "category": cat,
            }
        )
        y_index += 1
        for c in children.get(sid, []):
            walk(c, depth + 1)

    for r in roots:
        walk(r, 0)

    return {
        "rows": rows,
        "trace_duration_ms": round(float(trace_duration_ms), 3),
    }


def build_trace_graph_payload(t: dict) -> Dict[str, Any]:
    """
    输入: Jaeger /api/traces/{id} 返回的 trace 单条 (UI JSON，含 processes + spans)
    输出: { nodes: [...], links: [...], categories: [...] }
    """
    processes = t.get("processes") or {}
    spans = t.get("spans") or []
    if not isinstance(spans, list) or not spans:
        return {
            "nodes": [],
            "links": [],
            "categories": [
                {"name": "http"},
                {"name": "db"},
                {"name": "redis"},
                {"name": "mongo"},
                {"name": "mq"},
                {"name": "other"},
            ],
            "truncated": False,
            "waterfall": {"rows": [], "trace_duration_ms": 0.0},
        }

    if len(spans) > _MAX_NODES:
        spans = spans[:_MAX_NODES]
        truncated = True
    else:
        truncated = False

    by_id: Dict[str, dict] = {}
    for s in spans:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("spanID", ""))
        if not sid:
            continue
        by_id[sid] = s

    def svc_of(s: dict) -> str:
        pid = s.get("processID") or s.get("processId") or "p1"
        pr = processes.get(pid) if isinstance(processes, dict) else None
        if not isinstance(pr, dict):
            return "?"
        return (pr.get("serviceName") or "?")[:64]

    nodes: List[dict] = []
    links: List[dict] = []
    seen: Set[str] = set()

    for s in spans:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("spanID", ""))
        if not sid or sid in seen:
            continue
        seen.add(sid)
        op = s.get("operationName") or "span"
        if len(str(op)) > 100:
            op = str(op)[:97] + "..."
        svc = svc_of(s)
        tg = _tag_map(s)
        _kind, cat = _infer_category(tg, svc, str(op))
        peer = _peer_line(tg)
        dur = int(s.get("duration", 0)) / 1000.0
        title = f"{svc}"
        if peer:
            title = f"{svc} → {peer}"
        name_lines = f"{title}\n{op}\n{round(dur, 3)} ms"
        nodes.append(
            {
                "id": sid,
                "name": name_lines,
                "title": title,
                "operation": op,
                "service": svc,
                "peer": peer,
                "duration_ms": round(dur, 4),
                "kind": _kind,
                "category": cat,
            }
        )
        p = _parent_id(s)
        if p and p in by_id:
            links.append(
                {
                    "source": p,
                    "target": sid,
                    "value": round(dur, 4),
                }
            )

    # 去重边
    uq = set()
    ulinks = []
    for l in links:
        k = (l["source"], l["target"])
        if k in uq:
            continue
        uq.add(k)
        ulinks.append(l)

    wf = _build_waterfall_payload(by_id, processes)

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
        "waterfall": wf,
    }


def sanitize_trace_id(raw: str) -> Optional[str]:
    s = (raw or "").strip()
    s = re.sub(r"[^0-9a-fA-F]", "", s)
    if len(s) < 8 or len(s) > 32:
        return None
    return s.lower()
