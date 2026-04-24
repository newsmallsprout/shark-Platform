"""
Jaeger Query HTTP API（与 all-in-one / query 的 :16686 一致）。

环境变量：
  JAEGER_QUERY_BASE_URL  — 必填。须能作为 HTTP 访问 Query；可写 http://host:port，或仅 host:port（缺少协议时自
  动补 http://）。例：http://jaeger-query:16687 或 jaeger-query:16687（同集群 NS 内短名即可）。无则本模块返回未配置。
  JAEGER_QUERY_TOKEN     — 可选，Bearer
  JAEGER_QUERY_TLS_VERIFY — 默认 true；在集群内对 IP 可设为 false
  JAEGER_DEFAULT_SERVICE — 可选，未选 service 且拉服务列表时优先用
  JAEGER_UI_BASE_URL     — 可选，前端「打开 trace」用；未设时复用 Query Base

K8s 中 Query 的 **HTTP/JSON 端口未必是 16687**（常与服务定义有关）：若 /api/services 总为空，可改试
  http://jaeger-query:80 或 16686（与「打开 Jaeger UI」浏览器地址同源最稳）。
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from django.utils.dateparse import parse_datetime
from rest_framework.request import Request

logger = logging.getLogger(__name__)

_RANGE_DELTA = {
    "10m": timedelta(minutes=10),
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _normalize_base_url(raw: str) -> str:
    """若未带 http:// 或 https://，补全为 http://，避免 requests 报 No connection adapters。"""
    s = (raw or "").strip()
    if not s:
        return ""
    if "://" not in s:
        s = "http://" + s
    return s.rstrip("/")


def jaeger_configured() -> bool:
    return bool(_normalize_base_url(os.environ.get("JAEGER_QUERY_BASE_URL", "")))


def _base_url() -> str:
    return _normalize_base_url(os.environ.get("JAEGER_QUERY_BASE_URL", ""))


def _ui_base() -> str:
    u = _normalize_base_url(os.environ.get("JAEGER_UI_BASE_URL", ""))
    return u or _base_url()


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["Accept"] = "application/json"
    token = (os.environ.get("JAEGER_QUERY_TOKEN") or "").strip()
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    verify = os.environ.get("JAEGER_QUERY_TLS_VERIFY", "true").strip().lower() not in (
        "0",
        "false",
        "no",
    )
    s.verify = verify
    return s


def _get_json(path: str, params: Optional[dict] = None) -> Tuple[Optional[dict], Optional[str]]:
    if not path.startswith("/"):
        path = "/" + path
    url = _base_url() + path
    try:
        r = _session().get(url, params=params, timeout=(2, 15))
    except requests.RequestException as e:
        logger.warning("jaeger request failed: %s %s", url, e)
        return None, str(e)
    if r.status_code != 200:
        msg = f"HTTP {r.status_code}"
        try:
            j = r.json()
            if isinstance(j, dict) and (j.get("errors") or j.get("data") is not None):
                if j.get("errors"):
                    msg = str(j.get("errors"))
        except Exception:
            msg = (r.text or msg)[:500]
        logger.warning("jaeger bad response: %s %s", r.status_code, msg)
        return None, msg
    raw = r.text or ""
    if raw.lstrip().startswith("<"):
        err = (
            "返回了 HTML 而非 JSON：JAEGER_QUERY_BASE_URL 多半不是 Jaeger Query 的 HTTP 口，"
            "请与浏览器能打开 Jaeger UI 的地址一致（集群内常见 :80 或 :16686）。"
        )
        logger.warning("jaeger %s: %s", url, err[:200])
        return None, err
    try:
        return r.json(), None
    except Exception as e:
        logger.warning("jaeger json decode %s: %s body[:120]=%r", url, e, raw[:120])
        return None, str(e)


def _data_as_service_list(j: Any) -> List[str]:
    if j is None:
        return []
    if isinstance(j, list):
        return [str(x) for x in j if x]
    if not isinstance(j, dict):
        return []
    d = j.get("data")
    if isinstance(d, list):
        return [str(x) for x in d if x]
    if isinstance(d, dict):
        for k in ("serviceNames", "services", "items"):
            v = d.get(k)
            if isinstance(v, list):
                return [str(x) for x in v if x]
    return []


def list_services() -> Tuple[List[str], Optional[str]]:
    """(服务名列表, 拉取时的错误信息)。列表允许为空而仍有 HTTP 200。"""
    j, err = _get_json("/api/services")
    if j is None:
        return [], err
    out = _data_as_service_list(j)
    if not out and isinstance(j, dict) and not err:
        logger.info(
            "jaeger /api/services returned empty or unknown shape: keys=%s data_type=%s",
            list(j.keys()),
            type(j.get("data")).__name__,
        )
    return out, err


def _trace_id_to_str(tid: Any) -> str:
    if tid is None:
        return ""
    if isinstance(tid, str):
        return tid.lower() if len(tid) in (32, 16) else tid
    if isinstance(tid, dict) and "high" in tid and "low" in tid:
        h = int(tid.get("high", 0)) & 0xFFFFFFFFFFFFFFFF
        l = int(tid.get("low", 0)) & 0xFFFFFFFFFFFFFFFF
        return f"{h:016x}{l:016x}"
    if isinstance(tid, dict) and "traceID" in tid:
        return _trace_id_to_str(tid.get("traceID"))
    return str(tid).lower()


def _trace_row_from_ui_trace(t: dict) -> Optional[dict]:
    trace_id = _trace_id_to_str(t.get("traceID") or t.get("traceId"))
    spans: List[dict] = t.get("spans") or []
    if not trace_id or not spans:
        return None
    processes = t.get("processes") or {}
    starts = [int(s.get("startTime", 0)) for s in spans]
    ends = [int(s.get("startTime", 0)) + int(s.get("duration", 0)) for s in spans]
    t0, t1 = min(starts), max(ends)
    dur_ms = (t1 - t0) / 1000.0 if t1 >= t0 else 0.0
    root = min(spans, key=lambda s: int(s.get("startTime", 0)))
    pid = root.get("processID") or root.get("processId") or "p1"
    proc = processes.get(pid) if isinstance(processes, dict) else {}
    if not isinstance(proc, dict):
        proc = {}
    service = (proc.get("serviceName") or "unknown") if proc else "unknown"
    has_err = False
    for s in spans:
        for tag in s.get("tags") or []:
            if not isinstance(tag, dict):
                continue
            k = (tag.get("key") or "").lower()
            v = str(tag.get("value", "")).lower()
            if k == "error" and v in ("true", "1"):
                has_err = True
                break
            if "status_code" in k and v.isdigit() and int(v) >= 500:
                has_err = True
                break
        if has_err:
            break
    started = datetime.fromtimestamp(t0 / 1e6, tz=timezone.utc)
    return {
        "trace_id": trace_id,
        "root_service": service,
        "span_count": len(spans),
        "duration_ms": round(dur_ms, 2),
        "started_at": started.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": "error" if has_err else "ok",
    }


def search_traces(service: str, start_us: int, end_us: int, limit: int) -> Tuple[List[dict], Optional[str]]:
    params = {
        "service": service,
        "start": str(int(start_us)),
        "end": str(int(end_us)),
        "limit": str(max(1, min(limit, 500))),
    }
    j, err = _get_json("/api/traces", params)
    if err and j is None:
        return [], err
    if not j or not isinstance(j.get("data"), list):
        return [], err
    out: List[dict] = []
    for t in j["data"]:
        if not isinstance(t, dict):
            continue
        row = _trace_row_from_ui_trace(t)
        if row:
            out.append(row)
    return out, None


def get_trace_by_id(trace_id: str) -> Tuple[Optional[dict], Optional[str]]:
    """
    拉取单条 trace（与 Jaeger UI 详情页同源）。
    See: GET /api/traces/{traceID}
    """
    from urllib.parse import quote

    t = re.sub(r"[^0-9a-fA-F]", "", (trace_id or "")).lower()
    if len(t) < 8 or len(t) > 32:
        return None, "trace_id 格式无效"
    path = f"/api/traces/{quote(t, safe='')}"
    j, err = _get_json(path)
    if j is None:
        return None, err
    d = j.get("data")
    if isinstance(d, list) and d and isinstance(d[0], dict):
        return d[0], None
    if isinstance(d, dict) and (d.get("spans") is not None):
        return d, None
    return None, "trace 不存在或已过期"


def get_dependencies(end_ts_ms: int, lookback: str) -> List[dict]:
    """endTs: 毫秒；lookback: Jaeger 如 1h, 10m, 1d。"""
    # Jaeger: endTs 毫秒, lookback 为 duration 字符串
    j, _ = _get_json(
        "/api/dependencies", {"endTs": str(int(end_ts_ms)), "lookback": str(lookback)}
    )
    if not j or not isinstance(j, dict):
        return []
    data = j.get("data")
    if isinstance(data, list):
        raw = data
    elif isinstance(data, dict):
        raw = data.get("dependencies")
        if not isinstance(raw, list):
            return []
    else:
        return []
    items = []
    for d in raw:
        if not isinstance(d, dict):
            continue
        parent = d.get("parent") or d.get("Parent") or ""
        child = d.get("child") or d.get("Child") or ""
        n = d.get("callCount") or d.get("CallCount") or 0
        if parent and child:
            items.append(
                {
                    "parent": str(parent),
                    "child": str(child),
                    "call_count": int(n) if n is not None else 0,
                }
            )
    return items


def _lookback_str_from_delta(d: timedelta) -> str:
    s = int(d.total_seconds())
    if s % 3600 == 0 and s >= 3600:
        h = s // 3600
        return f"{h}h" if h != 1 else "1h"
    if s % 60 == 0 and s >= 60:
        m = s // 60
        return f"{m}m" if m != 1 else "1m"
    return f"{s}s"


def _window_from_request(
    request: Request,
) -> Tuple[int, int, str]:
    """
    返回 (start_us, end_us, lookback_str_for_dependencies)。
    """
    p = request.query_params
    start_s = (p.get("start") or "").strip()
    end_s = (p.get("end") or "").strip()
    if start_s and end_s:
        try:
            a = parse_datetime(start_s)
            b = parse_datetime(end_s)
            if a and b and b > a:
                if a.tzinfo is None:
                    a = a.replace(tzinfo=timezone.utc)
                if b.tzinfo is None:
                    b = b.replace(tzinfo=timezone.utc)
                start_us = int(a.timestamp() * 1_000_000)
                end_us = int(b.timestamp() * 1_000_000)
                d = b - a
                return start_us, end_us, _lookback_str_from_delta(d)
        except Exception:
            pass
    range_key = (p.get("range") or "1h").strip() or "1h"
    d = _RANGE_DELTA.get(range_key, timedelta(hours=1))
    end = datetime.now(timezone.utc)
    start = end - d
    start_us = int(start.timestamp() * 1_000_000)
    end_us = int(end.timestamp() * 1_000_000)
    return start_us, end_us, _lookback_str_from_delta(d)


def resolve_service(request: Request, services: List[str]) -> str:
    p = (request.query_params.get("service") or "").strip()
    if p:
        return p
    env_def = (os.environ.get("JAEGER_DEFAULT_SERVICE") or "").strip()
    if env_def:
        return env_def
    if services:
        return services[0]
    return ""


def fetch_jaeger_flow(request: Request) -> dict:
    if not jaeger_configured():
        return {
            "configured": False,
            "error": "未设置环境变量 JAEGER_QUERY_BASE_URL",
            "traces": [],
            "dependencies": {"items": []},
            "services": [],
            "service_used": "",
            "jaeger_ui_base": "",
            "note": None,
        }

    limit = 20
    try:
        limit = int(request.query_params.get("limit") or "20")
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 200))

    services, services_err = list_services()
    service = resolve_service(request, services)
    if not service:
        if services_err:
            err_msg = f"无法拉取 Jaeger 服务列表: {services_err}"
        else:
            err_msg = (
                "未指定 service 且从 Query 拉到的服务列表为空。若 Jaeger UI 里已有服务，说明 "
                "JAEGER_QUERY_BASE_URL 可能连错了端口/服务（请与 UI 同源，多为 http://jaeger-query:80 或 "
                ":16686，而非 gRPC/其它端口）。也可在本页「服务」下拉手输服务名，或设环境变量 "
                "JAEGER_DEFAULT_SERVICE。"
            )
        return {
            "configured": True,
            "error": err_msg,
            "traces": [],
            "dependencies": {"items": []},
            "services": services,
            "service_used": "",
            "jaeger_ui_base": _ui_base(),
            "jaeger_list_error": services_err,
            "note": None,
        }

    start_us, end_us, lookback = _window_from_request(request)
    end_ms = end_us // 1000
    traces, err = search_traces(service, start_us, end_us, limit)
    if err and not traces:
        return {
            "configured": True,
            "error": err,
            "traces": [],
            "dependencies": {"items": []},
            "services": services,
            "service_used": service,
            "jaeger_ui_base": _ui_base(),
            "note": None,
        }

    deps: List[dict] = []
    try:
        deps = get_dependencies(end_ms, lookback)
    except Exception as e:
        logger.warning("jaeger dependencies: %s", e)

    return {
        "configured": True,
        "error": err if (err and traces) else None,
        "traces": traces,
        "dependencies": {"items": deps},
        "services": services,
        "service_used": service,
        "jaeger_ui_base": _ui_base(),
        "note": None,
    }
