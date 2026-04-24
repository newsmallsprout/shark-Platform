"""
Normalize multi-site log sources (per-domain files or Redis lists).
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from ..models import TrafficDashboardConfig
from .nginx_log import load_records, records_from_lines
from .redis_log_buffer import fetch_tail_lines


def _env_file_path() -> str:
    return (os.environ.get("TRAFFIC_NGINX_ACCESS_LOG", "") or "").strip()


def legacy_file_path(cfg: TrafficDashboardConfig) -> str:
    return (cfg.access_log_path or _env_file_path() or "").strip()


def effective_log_format(cfg: TrafficDashboardConfig, src: Optional[Dict[str, Any]] = None) -> str:
    """
    Per-source optional log_format in log_sources (e.g. go-log-collector stream); falls back to cfg.log_format.
    Accepts the same values as parse_log_line: json, combined, auto, nginx_json, shark_json.
    """
    if src and isinstance(src, dict):
        lf = (str(src.get("log_format") or "").strip() or "").lower()
        if lf in ("json", "combined", "auto", "nginx_json", "shark_json"):
            return lf
    m = (cfg.log_format or "json").strip().lower()
    return m if m in ("json", "combined") else "json"


def resolve_ingest_log_format(
    cfg: TrafficDashboardConfig, source_id: str, request_format: str = ""
) -> str:
    """Batch log_format (e.g. from go-log-collector) wins; else per-source or global config."""
    q = (request_format or "").strip().lower()
    if q in ("json", "combined", "auto", "nginx_json", "shark_json"):
        return q
    sid = (source_id or "").strip()
    for s in normalized_log_sources(cfg):
        if s.get("id") == sid:
            return effective_log_format(cfg, s)
    return effective_log_format(cfg, None)


def legacy_redis_key(cfg: TrafficDashboardConfig) -> str:
    k = (cfg.redis_log_key or "traffic:access:lines").strip()
    return k or "traffic:access:lines"


def redis_cap(cfg: TrafficDashboardConfig) -> int:
    try:
        n = int(cfg.redis_max_lines or 200_000)
    except (TypeError, ValueError):
        n = 200_000
    return max(1_000, min(n, 2_000_000))


def _access_mode(cfg: TrafficDashboardConfig) -> str:
    m = (cfg.access_log_mode or os.environ.get("TRAFFIC_ACCESS_LOG_MODE", "file") or "file").strip()
    return m if m in ("file", "redis") else "file"


def resolve_effective_traffic_source_id(requested: str, cfg: TrafficDashboardConfig) -> str:
    """
    Align ?source= with go-log-collector / rollup `source_id` (stream_key).

    - all / 空: 不筛选（多流合并）。
    - default: 未配置多站点时，rollup 中可能是任意 stream_key，故映射为 all；
      仅配置一个非 default 的 id 时，将 default 视为该流（与旧「默认」项对齐）。
    """
    r = (requested or "").strip()
    if not r or r == "all":
        return "all"
    if r != "default":
        return r
    raw = getattr(cfg, "log_sources", None)
    if not isinstance(raw, list) or len(raw) == 0:
        return "all"
    ids = [str(x.get("id") or "").strip() for x in raw if isinstance(x, dict) and (x.get("id") or "").strip()]
    if len(ids) == 1 and ids[0] and ids[0] != "default":
        return ids[0]
    return "default"


def normalized_log_sources(cfg: TrafficDashboardConfig) -> List[Dict[str, Any]]:
    raw = getattr(cfg, "log_sources", None)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = []
    if not isinstance(raw, list) or not raw:
        if _access_mode(cfg) == TrafficDashboardConfig.ACCESS_LOG_MODE_REDIS:
            return [
                {
                    "id": "default",
                    "label": "默认",
                    "file_path": "",
                    "redis_key": legacy_redis_key(cfg),
                    "log_format": "",
                }
            ]
        p = legacy_file_path(cfg)
        return [
            {
                "id": "default",
                "label": "默认",
                "file_path": p,
                "redis_key": "",
                "log_format": "",
            }
        ]

    out: List[Dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("id") or "").strip()
        if not sid:
            continue
        label = (str(row.get("label") or sid).strip() or sid)[:128]
        fp = str(row.get("file_path") or "").strip()[:1024]
        rk = str(row.get("redis_key") or "").strip()[:256]
        row_lf = (str(row.get("log_format") or "").strip().lower() or "")[:32]
        out.append(
            {
                "id": sid[:64],
                "label": label,
                "file_path": fp,
                "redis_key": rk,
                "log_format": row_lf,
            }
        )

    if not out:
        if _access_mode(cfg) == TrafficDashboardConfig.ACCESS_LOG_MODE_REDIS:
            return [
                {
                    "id": "default",
                    "label": "默认",
                    "file_path": "",
                    "redis_key": legacy_redis_key(cfg),
                    "log_format": "",
                }
            ]
        p = legacy_file_path(cfg)
        return [
            {
                "id": "default",
                "label": "默认",
                "file_path": p,
                "redis_key": "",
                "log_format": "",
            }
        ]
    return out


def load_records_for_source(
    cfg: TrafficDashboardConfig,
    src: Dict[str, Any],
    *,
    redis_line_cap: Optional[int] = None,
    max_tail_bytes_override: Optional[int] = None,
) -> List[Dict[str, Any]]:
    mode = _access_mode(cfg)
    if mode == TrafficDashboardConfig.ACCESS_LOG_MODE_REDIS:
        key = (src.get("redis_key") or "").strip() or legacy_redis_key(cfg)
        cap = redis_cap(cfg)
        if redis_line_cap is not None:
            cap = min(cap, max(1000, redis_line_cap))
        lines = fetch_tail_lines(key, cap)
        return records_from_lines(lines, effective_log_format(cfg, src))
    path = (src.get("file_path") or "").strip()
    if not path:
        return []
    mtb = cfg.max_tail_bytes
    if max_tail_bytes_override is not None:
        mtb = min(mtb, max(65536, max_tail_bytes_override))
    return load_records(path, effective_log_format(cfg, src), mtb)


def load_raw_records(
    cfg: TrafficDashboardConfig,
    source_id: str,
    *,
    redis_line_cap: Optional[int] = None,
    max_tail_bytes_override: Optional[int] = None,
) -> List[Dict[str, Any]]:
    sources = normalized_log_sources(cfg)
    sid = (source_id or "").strip()
    if sid and sid != "all":
        src = next((s for s in sources if s["id"] == sid), None)
        if not src:
            return []
        return load_records_for_source(
            cfg, src, redis_line_cap=redis_line_cap, max_tail_bytes_override=max_tail_bytes_override
        )
    acc: List[Dict[str, Any]] = []
    for s in sources:
        acc.extend(
            load_records_for_source(
                cfg, s, redis_line_cap=redis_line_cap, max_tail_bytes_override=max_tail_bytes_override
            )
        )
    return acc


def redis_key_for_ingest(cfg: TrafficDashboardConfig, source_id: str) -> str:
    q = (source_id or "").strip()
    if not q:
        return legacy_redis_key(cfg)
    for s in normalized_log_sources(cfg):
        if s["id"] == q:
            return (s.get("redis_key") or "").strip() or legacy_redis_key(cfg)
    return legacy_redis_key(cfg)


def sources_for_api(cfg: TrafficDashboardConfig) -> List[Dict[str, str]]:
    items = []
    for s in normalized_log_sources(cfg):
        items.append({"id": s["id"], "label": s.get("label") or s["id"]})
    if items:
        items.insert(0, {"id": "all", "label": "全部"})
    return items


def log_source_configured(cfg: TrafficDashboardConfig, redis_configured: bool) -> bool:
    if _access_mode(cfg) == TrafficDashboardConfig.ACCESS_LOG_MODE_REDIS:
        return bool(redis_configured)
    for s in normalized_log_sources(cfg):
        if (s.get("file_path") or "").strip():
            return True
    return False
