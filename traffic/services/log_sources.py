"""
Normalize multi-site log sources (per-domain files or Redis lists).

未在 DB 中配置多站点时，仍可根据：
  - 分钟聚合表 TrafficMinuteRollup.source_id
  - Redis 集合 traffic:known_stream_keys（ingest 时写入）
自动出现在大盘数据源下界；Redis 键名约定见 default_redis_key_for_stream_id。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Set

from ..models import TrafficDashboardConfig, TrafficMinuteRollup

logger = logging.getLogger(__name__)

KNOWN_STREAMS_REDIS_KEY = "traffic:known_stream_keys"
from .nginx_log import load_records, records_from_lines
from .redis_log_buffer import fetch_tail_lines, is_configured as redis_buffer_configured


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
    for s in effective_log_sources(cfg):
        if s.get("id") == sid:
            return effective_log_format(cfg, s)
    return effective_log_format(cfg, None)


def legacy_redis_key(cfg: TrafficDashboardConfig) -> str:
    k = (cfg.redis_log_key or "traffic:access:lines").strip()
    return k or "traffic:access:lines"


def _redis_read_cap(
    cfg: TrafficDashboardConfig, redis_line_cap: Optional[int] = None
) -> int:
    """Effective max lines to read. 0 in cfg or in redis_line_cap means no line cap (read full list)."""
    rmax = redis_cap(cfg)
    if redis_line_cap is None:
        return rmax
    d = int(redis_line_cap)
    if d <= 0 and rmax <= 0:
        return 0
    if d <= 0:
        return rmax
    if rmax <= 0:
        return d
    return min(d, rmax)


def redis_cap(cfg: TrafficDashboardConfig) -> int:
    try:
        n = int(getattr(cfg, "redis_max_lines", 0) or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return 0
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


def default_redis_key_for_stream_id(cfg: TrafficDashboardConfig, stream_id: str) -> str:
    """
    未在「多站点」表里写 redis_key 时，按 TRAFFIC_REDIS_STREAM_LAYOUT 生成 List 键。
    suffix（默认）: {redis_log_key}:{stream_id}，如 traffic:access:lines:api
    single: 所有流共用一个键（旧行为，不适合多流并行）
    """
    sid = (stream_id or "").strip() or "default"
    if sid == "default":
        return legacy_redis_key(cfg)
    layout = (os.environ.get("TRAFFIC_REDIS_STREAM_LAYOUT", "suffix") or "suffix").strip().lower()
    if layout in ("single", "legacy", "one"):
        return legacy_redis_key(cfg)
    base = legacy_redis_key(cfg).strip()
    if not base:
        return f"traffic:access:lines:{sid}"
    return f"{base}:{sid}"


def _effective_source_redis_key(src: Dict[str, Any], cfg: TrafficDashboardConfig) -> str:
    """Explicit redis_key in config; empty means per-id default list key (suffix), not only legacy base."""
    explicit = (src.get("redis_key") or "").strip()
    if explicit:
        return explicit
    sid = (str(src.get("id") or "").strip() or "default")
    return default_redis_key_for_stream_id(cfg, sid)


def _stream_keys_from_redis() -> Set[str]:
    out: Set[str] = set()
    try:
        from .redis_log_buffer import traffic_redis_client

        r = traffic_redis_client()
        if not r:
            return out
        for k in r.sscan_iter(KNOWN_STREAMS_REDIS_KEY, count=256):
            if k and str(k).strip():
                out.add(str(k).strip())
    except Exception as e:
        logger.debug("stream_keys_from_redis: %s", e)
    return out


def discovered_stream_ids(cfg: TrafficDashboardConfig) -> List[str]:
    s: Set[str] = set()
    s.update(_stream_keys_from_redis())
    try:
        from datetime import timedelta

        from django.utils import timezone

        since = timezone.now() - timedelta(days=30)
        for x in (
            TrafficMinuteRollup.objects.filter(bucket_start__gte=since)
            .values_list("source_id", flat=True)
            .distinct()[:500]
        ):
            if x:
                t = str(x).strip()
                if t:
                    s.add(t)
    except Exception as e:
        logger.debug("discovered_stream_ids rollup: %s", e)
    return sorted(s)


def _human_label(stream_id: str) -> str:
    sid = (stream_id or "").strip()
    if not sid:
        return sid
    if "_" in sid and sid.replace("_", "").isalnum():
        return sid.replace("_", " ").title()
    return sid


def effective_log_sources(cfg: TrafficDashboardConfig) -> List[Dict[str, Any]]:
    """
    手动配置行 + 自动发现的 stream_key；后者带 auto_discovered=True，读 Redis 时用约定键。
    """
    manual = normalized_log_sources(cfg)
    known = {str(s.get("id") or "").strip() for s in manual if s.get("id")}
    extra: List[Dict[str, Any]] = []
    for sid in discovered_stream_ids(cfg):
        if not sid or sid in known:
            continue
        extra.append(
            {
                "id": sid[:64],
                "label": _human_label(sid)[:128],
                "file_path": "",
                "redis_key": default_redis_key_for_stream_id(cfg, sid),
                "log_format": "",
                "auto_discovered": True,
            }
        )
    return manual + extra


def register_stream_key_observed(stream_key: str) -> None:
    """ingest 成功后登记，便于尚无 rollup 时也能在下拉里出现。"""
    sk = (stream_key or "").strip() or "default"
    if len(sk) > 128:
        sk = sk[:128]
    try:
        from .redis_log_buffer import traffic_redis_client

        r = traffic_redis_client()
        if r:
            r.sadd(KNOWN_STREAMS_REDIS_KEY, sk)
    except Exception as e:
        logger.debug("register_stream_key_observed: %s", e)


def _has_file_paths_to_read(cfg: TrafficDashboardConfig) -> bool:
    if (legacy_file_path(cfg) or "").strip():
        return True
    for s in normalized_log_sources(cfg):
        if (s.get("file_path") or "").strip():
            return True
    return False


def load_records_for_source(
    cfg: TrafficDashboardConfig,
    src: Dict[str, Any],
    *,
    redis_line_cap: Optional[int] = None,
    max_tail_bytes_override: Optional[int] = None,
    force_redis: bool = False,
) -> List[Dict[str, Any]]:
    mode = _access_mode(cfg)
    if force_redis or mode == TrafficDashboardConfig.ACCESS_LOG_MODE_REDIS:
        key = _effective_source_redis_key(src, cfg)
        cap = _redis_read_cap(cfg, redis_line_cap)
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
    sources = effective_log_sources(cfg)
    sid = (source_id or "").strip()
    if sid and sid != "all":
        src = next((s for s in sources if s["id"] == sid), None)
        if not src:
            return []
        acc = load_records_for_source(
            cfg, src, redis_line_cap=redis_line_cap, max_tail_bytes_override=max_tail_bytes_override
        )
    else:
        acc = []
        for s in sources:
            acc.extend(
                load_records_for_source(
                    cfg, s, redis_line_cap=redis_line_cap, max_tail_bytes_override=max_tail_bytes_override
                )
            )
    if not acc and redis_buffer_configured() and _access_mode(
        cfg
    ) == TrafficDashboardConfig.ACCESS_LOG_MODE_REDIS:
        # 未知 stream_key 的 ingest 只写 default list；多站点若每行有独立 redis_key 则初读会全空
        L = legacy_redis_key(cfg)
        cap = _redis_read_cap(cfg, redis_line_cap)
        if sid and sid != "all":
            src0 = next((s for s in sources if s["id"] == sid), None)
            if src0 and _effective_source_redis_key(src0, cfg) != L:
                lines = fetch_tail_lines(L, cap)
                if lines:
                    acc = records_from_lines(
                        lines, effective_log_format(cfg, src0)
                    )
        else:
            if not any(_effective_source_redis_key(s, cfg) == L for s in sources):
                lines = fetch_tail_lines(L, cap)
                if lines:
                    acc = records_from_lines(
                        lines, effective_log_format(cfg, None)
                    )
    if not acc and redis_buffer_configured() and _access_mode(
        cfg
    ) == TrafficDashboardConfig.ACCESS_LOG_MODE_FILE and not _has_file_paths_to_read(cfg):
        # 仅 go-log-collector/ingest 写 Redis、后台仍「文件模式」且未配可读路径时，改从 Redis 拉取
        if sid and sid != "all":
            src2 = next((s for s in sources if s["id"] == sid), None)
            if not src2:
                return acc
            return load_records_for_source(
                cfg,
                src2,
                redis_line_cap=redis_line_cap,
                max_tail_bytes_override=max_tail_bytes_override,
                force_redis=True,
            )
        acc2: List[Dict[str, Any]] = []
        for s in sources:
            acc2.extend(
                load_records_for_source(
                    cfg,
                    s,
                    redis_line_cap=redis_line_cap,
                    max_tail_bytes_override=max_tail_bytes_override,
                    force_redis=True,
                )
            )
        return acc2
    return acc


def redis_key_for_ingest(cfg: TrafficDashboardConfig, source_id: str) -> str:
    q = (source_id or "").strip() or "default"
    for s in normalized_log_sources(cfg):
        if s["id"] == q:
            explicit = (s.get("redis_key") or "").strip()
            if explicit:
                return explicit
            return default_redis_key_for_stream_id(cfg, q)
    return default_redis_key_for_stream_id(cfg, q)


def sources_for_api(cfg: TrafficDashboardConfig) -> List[Dict[str, str]]:
    items = []
    for s in effective_log_sources(cfg):
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
