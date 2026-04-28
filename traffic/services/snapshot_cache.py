"""
Minute-rollup snapshot memoization.

TRAFFIC_SNAPSHOT_CACHE_SEC: TTL seconds (0 = disabled, max 60). Cuts PG/ClickHouse
pressure when the dashboard polls every few seconds with the same range/source.

Key includes TrafficDashboardConfig.updated_at and Inspection Prometheus URL so
config / blackbox source changes invalidate promptly.

Cache stores JSON text to avoid holding duplicate deepcopies of large nested dicts in RAM.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

_lock = threading.Lock()
_store: Dict[str, Tuple[float, str]] = {}
_MAX_ENTRIES = 12


def cache_ttl_seconds() -> float:
    try:
        v = float((os.environ.get("TRAFFIC_SNAPSHOT_CACHE_SEC") or "0").strip())
    except ValueError:
        v = 0.0
    return max(0.0, min(v, 60.0))


def rollup_cache_key(
    *,
    source_id: str,
    range_key: str,
    cfg_updated_ts: float,
    blackbox_sig: str,
    start_ts: Optional[float] = None,
    end_ts: Optional[float] = None,
) -> str:
    sig = (blackbox_sig or "")[:256]
    if start_ts is not None and end_ts is not None:
        return f"rs|{source_id}|c|{int(start_ts)}|{int(end_ts)}|{cfg_updated_ts:.6f}|{sig}"
    return f"rs|{source_id}|p|{range_key}|{cfg_updated_ts:.6f}|{sig}"


def _freeze(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def get_or_set_rollup(key: str, factory: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    ttl = cache_ttl_seconds()
    if ttl <= 0:
        return factory()
    now = time.monotonic()
    with _lock:
        ent = _store.get(key)
        if ent and ent[0] > now:
            return json.loads(ent[1])
    payload = factory()
    frozen = _freeze(payload)
    with _lock:
        if len(_store) >= _MAX_ENTRIES:
            cutoff = now
            dead = [k for k, (exp, _) in _store.items() if exp <= cutoff]
            for k in dead[:32]:
                _store.pop(k, None)
            if len(_store) >= _MAX_ENTRIES:
                for k in list(_store.keys())[:32]:
                    _store.pop(k, None)
        _store[key] = (now + ttl, frozen)
    return payload


def blackbox_cache_sig(inspection) -> str:
    try:
        u = getattr(inspection, "prometheus_url", None) or ""
        return str(u)
    except Exception:
        return ""
