"""
Read-only tool implementations for SRE ReAct Agent (Prometheus / K8s / log_monitor).
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from django.conf import settings
from django.utils import timezone as dj_timezone

logger = logging.getLogger(__name__)

try:
    from kubernetes import client
    from kubernetes import config as k8s_config

    K8S_AVAILABLE = True
except ImportError:
    client = None  # type: ignore
    k8s_config = None  # type: ignore
    K8S_AVAILABLE = False

# --- Prometheus sandbox ---
_PROM_FORBIDDEN = re.compile(
    r"\b(count|topk)\s*\(\s*[0-9]{4,}", re.I
)  # naive: block huge topk
_PROM_MAX_LEN = 1800


def tool_schemas() -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "query_log_monitor_errors",
                "description": "优先：检索 log_monitor 落盘的 error 日志（logs/monitor_logs/*_error.log）。按时间窗与 pod 名过滤。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_iso8601": {"type": "string"},
                        "end_iso8601": {"type": "string"},
                        "namespace": {"type": "string", "description": "可选，用于匹配任务目录"},
                        "pod_name_substring": {"type": "string", "description": "匹配文件名或内容"},
                        "max_entries": {"type": "integer", "default": 40},
                    },
                    "required": ["start_iso8601", "end_iso8601"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_container_raw_logs",
                "description": "兜底：读取指定 Pod 容器日志（与 log_monitor 同源 K8s API）。需精确 namespace+pod。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "namespace": {"type": "string"},
                        "pod": {"type": "string"},
                        "container": {"type": "string", "default": ""},
                        "tail_lines": {"type": "integer", "default": 200},
                        "grep_pattern": {"type": "string", "default": ""},
                    },
                    "required": ["namespace", "pod"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_prometheus",
                "description": "PromQL instant 或 range 查询；返回序列有上限。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "query_type": {"type": "string", "enum": ["instant", "range"]},
                        "range_minutes": {"type": "integer", "default": 60},
                        "step": {"type": "string", "default": "60s"},
                    },
                    "required": ["query", "query_type"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_k8s_resource_status",
                "description": "只读：Pod 详情摘要、Events（Warning 优先）。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "namespace": {"type": "string"},
                        "pod": {"type": "string"},
                        "max_events": {"type": "integer", "default": 80},
                    },
                    "required": ["namespace", "pod"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_service_dependencies",
                "description": "列出同 namespace 内 Service 与 Endpoints，辅助判断上下游（启发式，非全自动拓扑）。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "namespace": {"type": "string"},
                        "service_name": {"type": "string"},
                    },
                    "required": ["namespace", "service_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "submit_final_report",
                "description": "证据充分时调用，结束排查并输出结构化结论。禁止编造未出现在先前 Observation 中的指标或日志。"
                "mitigation_commands 仅填会改变集群状态的命令；只读 kubectl get/describe、PromQL 查询应写在 root_cause 的分步排查中。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "incident_summary": {"type": "string"},
                        "evidence_chain": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "step": {"type": "integer"},
                                    "hypothesis": {"type": "string"},
                                    "tool": {"type": "string"},
                                    "finding": {"type": "string"},
                                },
                            },
                        },
                        "root_cause": {"type": "string"},
                        "mitigation_commands": {"type": "array", "items": {"type": "string"}},
                        "prevention": {"type": "array", "items": {"type": "string"}},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "data_citations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string"},
                                    "excerpt": {"type": "string"},
                                },
                                "required": ["type", "excerpt"],
                            },
                        },
                    },
                    "required": [
                        "incident_summary",
                        "root_cause",
                        "evidence_chain",
                        "data_citations",
                        "confidence",
                    ],
                },
            },
        },
    ]


def _parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def query_log_monitor_errors(args: dict) -> dict:
    log_dir = os.path.join(settings.BASE_DIR, "logs", "monitor_logs")
    os.makedirs(log_dir, exist_ok=True)
    start = _parse_iso(args.get("start_iso8601", ""))
    end = _parse_iso(args.get("end_iso8601", ""))
    ns = (args.get("namespace") or "").strip()
    pod_sub = (args.get("pod_name_substring") or "").strip()
    max_entries = int(args.get("max_entries") or 40)
    max_entries = max(1, min(max_entries, 120))

    patterns = [os.path.join(log_dir, "*_error.log"), os.path.join(log_dir, "**", "*_error.log")]
    files: List[str] = []
    for p in patterns:
        files.extend(glob.glob(p, recursive=True))
    files = sorted(set(files), key=os.path.getmtime, reverse=True)

    entries: List[dict] = []
    total_bytes = 0
    cap_bytes = 120_000

    for fp in files[:80]:
        if ns and ns not in fp:
            continue
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(fp), tz=dt_timezone.utc)
            if start and mtime < start.astimezone(dt_timezone.utc):
                continue
            if end and mtime > end.astimezone(dt_timezone.utc) + timedelta(hours=24):
                continue
        except OSError:
            continue
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-400:]
            for i, line in enumerate(lines):
                if pod_sub and pod_sub not in line and pod_sub not in fp:
                    continue
                if start or end:
                    # 弱时间过滤：仅当有解析到的时间戳在行首时尝试
                    pass
                excerpt = line.strip()[:2000]
                if not excerpt:
                    continue
                total_bytes += len(excerpt)
                if total_bytes > cap_bytes:
                    break
                entries.append({"file": os.path.basename(fp), "line": excerpt})
                if len(entries) >= max_entries:
                    break
        except OSError as e:
            logger.warning("log_monitor read %s: %s", fp, e)
        if len(entries) >= max_entries or total_bytes > cap_bytes:
            break

    return {
        "ok": True,
        "source": "log_monitor",
        "matched_files_scanned": min(len(files), 80),
        "entries": entries,
        "truncated": len(entries) >= max_entries or total_bytes > cap_bytes,
    }


def _k8s_v1():
    if not K8S_AVAILABLE or client is None or k8s_config is None:
        return None
    try:
        k8s_config.load_incluster_config()
    except Exception:
        try:
            k8s_config.load_kube_config()
        except Exception:
            return None
    return client.CoreV1Api()


def fetch_container_raw_logs(args: dict) -> dict:
    ns = args.get("namespace", "").strip()
    pod = args.get("pod", "").strip()
    container = (args.get("container") or "").strip()
    tail = int(args.get("tail_lines") or 200)
    tail = max(10, min(tail, 3000))
    grep_pat = (args.get("grep_pattern") or "").strip()

    v1 = _k8s_v1()
    if not v1:
        return {"ok": False, "error": "K8s client unavailable"}

    try:
        kwargs = {"name": pod, "namespace": ns, "tail_lines": tail}
        if container:
            kwargs["container"] = container
        text = v1.read_namespaced_pod_log(**kwargs)
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}

    lines = text.splitlines()
    if grep_pat:
        try:
            rx = re.compile(grep_pat)
            lines = [ln for ln in lines if rx.search(ln)]
        except re.error:
            lines = [ln for ln in lines if grep_pat in ln]
    max_lines = 500
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    joined = "\n".join(lines)
    if len(joined) > 256_000:
        joined = joined[-256_000:]
    return {
        "ok": True,
        "namespace": ns,
        "pod": pod,
        "line_count": len(lines),
        "truncated": len(lines) >= max_lines or len(joined) >= 256_000,
        "log_excerpt": joined,
    }


def query_prometheus(args: dict, prometheus_url: str) -> dict:
    if not prometheus_url:
        return {"ok": False, "error": "Prometheus URL not configured (Inspection / platform config)"}
    q = (args.get("query") or "").strip()
    if len(q) > _PROM_MAX_LEN:
        return {"ok": False, "error": "query too long"}
    if _PROM_FORBIDDEN.search(q):
        return {"ok": False, "error": "query pattern rejected by sandbox"}

    qtype = args.get("query_type", "instant")
    now = dj_timezone.now()
    try:
        if qtype == "instant":
            url = f"{prometheus_url.rstrip('/')}/api/v1/query"
            r = requests.get(
                url,
                params={"query": q, "time": now.timestamp()},
                timeout=15,
            )
        else:
            url = f"{prometheus_url.rstrip('/')}/api/v1/query_range"
            mins = int(args.get("range_minutes") or 60)
            mins = max(5, min(mins, 1440))
            start = now - timedelta(minutes=mins)
            r = requests.get(
                url,
                params={
                    "query": q,
                    "start": start.timestamp(),
                    "end": now.timestamp(),
                    "step": args.get("step") or "60s",
                },
                timeout=20,
            )
        r.raise_for_status()
        data = r.json().get("data", {}) or {}
        result = data.get("result") or []
        max_series = 200
        if len(result) > max_series:
            result = result[:max_series]
        return {
            "ok": True,
            "result_type": data.get("resultType"),
            "series": result,
            "truncated": len(data.get("result") or []) > max_series,
        }
    except Exception as e:
        logger.warning("prometheus tool: %s", e)
        return {"ok": False, "error": str(e)[:400]}


def get_k8s_resource_status(args: dict) -> dict:
    ns = args.get("namespace", "").strip()
    pod = args.get("pod", "").strip()
    max_ev = int(args.get("max_events") or 80)
    max_ev = max(1, min(max_ev, 200))

    v1 = _k8s_v1()
    if not v1:
        return {"ok": False, "error": "K8s unavailable"}

    try:
        p = v1.read_namespaced_pod(name=pod, namespace=ns)
        summary = {
            "phase": p.status.phase,
            "node": p.spec.node_name,
            "pod_ip": p.status.pod_ip,
            "conditions": [
                {"type": c.type, "status": c.status, "reason": c.reason or ""}
                for c in (p.status.conditions or [])
            ],
            "container_statuses": [],
        }
        for cs in p.status.container_statuses or []:
            st = "running"
            if cs.state.waiting:
                st = f"waiting:{cs.state.waiting.reason}"
            elif cs.state.terminated:
                st = f"terminated:{cs.state.terminated.reason}:{cs.state.terminated.exit_code}"
            summary["container_statuses"].append(
                {"name": cs.name, "state": st, "restarts": cs.restart_count}
            )

        ev = v1.list_namespaced_event(
            namespace=ns, field_selector=f"involvedObject.name={pod}"
        )

        def _ev_ts(evt):
            t = evt.last_timestamp or evt.first_timestamp
            if t:
                return t
            return datetime.min.replace(tzinfo=dt_timezone.utc)

        events = []
        for e in sorted(ev.items, key=_ev_ts)[-max_ev:]:
            events.append(
                {
                    "type": e.type,
                    "reason": e.reason,
                    "message": (e.message or "")[:500],
                }
            )
        return {"ok": True, "pod_summary": summary, "events": events}
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}


def get_service_dependencies(args: dict) -> dict:
    ns = args.get("namespace", "").strip()
    name = args.get("service_name", "").strip()
    v1 = _k8s_v1()
    if not v1:
        return {"ok": False, "error": "K8s unavailable"}
    try:
        svcs = v1.list_namespaced_service(namespace=ns)
        ep = None
        try:
            ep = v1.read_namespaced_endpoints(name=name, namespace=ns)
        except Exception:
            pass
        subset_summary = []
        if ep and ep.subsets:
            for ss in ep.subsets:
                for a in ss.addresses or []:
                    subset_summary.append(
                        {"ip": a.ip, "target_ref": getattr(a.target_ref, "name", "") if a.target_ref else ""}
                    )
        others = [s.metadata.name for s in svcs.items if s.metadata.name != name][:20]
        return {
            "ok": True,
            "service": name,
            "namespace": ns,
            "endpoints_addresses_sample": subset_summary[:30],
            "other_services_in_namespace": others,
            "note": "启发式列表，非自动服务网格拓扑",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:400]}


def execute_tool(
    name: str,
    arguments: dict,
    *,
    prometheus_url: str,
) -> Tuple[dict, bool]:
    """
    Returns (observation_dict, is_final_report_tool).
    """
    args = arguments if isinstance(arguments, dict) else {}
    if name == "query_log_monitor_errors":
        return query_log_monitor_errors(args), False
    if name == "fetch_container_raw_logs":
        return fetch_container_raw_logs(args), False
    if name == "query_prometheus":
        return query_prometheus(args, prometheus_url), False
    if name == "get_k8s_resource_status":
        return get_k8s_resource_status(args), False
    if name == "get_service_dependencies":
        return get_service_dependencies(args), False
    if name == "submit_final_report":
        return {"ok": True, "final_report": args}, True
    return {"ok": False, "error": f"unknown tool {name}"}, False
