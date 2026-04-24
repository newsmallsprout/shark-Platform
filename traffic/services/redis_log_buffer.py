"""
Redis list buffer for Nginx access lines shipped from remote hosts (K8s / separate Nginx).

Env:
  TRAFFIC_REDIS_URL — preferred (e.g. redis://redis.traffic.svc:6379/1)
  REDIS_URL — fallback if TRAFFIC_REDIS_URL unset
"""
import logging
import os
from typing import List

logger = logging.getLogger(__name__)


def redis_url() -> str:
    return (os.environ.get("TRAFFIC_REDIS_URL") or os.environ.get("REDIS_URL") or "").strip()


def is_configured() -> bool:
    return bool(redis_url())


def traffic_redis_client():
    """Shared Redis client for traffic features (ingest buffer, rollup buffer). None if not configured."""
    if not is_configured():
        return None
    try:
        return _client()
    except Exception as e:
        logger.warning("traffic_redis_client: %s", e)
        return None


def _client():
    import redis

    return redis.from_url(redis_url(), decode_responses=True, socket_connect_timeout=2)


def fetch_tail_lines(key: str, max_lines: int) -> List[str]:
    # max_lines <= 0: read the entire list (no line cap)
    if not key or not is_configured():
        return []
    try:
        r = _client()
        n = r.llen(key)
        if n <= 0:
            return []
        if max_lines <= 0:
            return [ln for ln in r.lrange(key, 0, -1) if ln and str(ln).strip()]
        start = max(0, n - max_lines)
        return [ln for ln in r.lrange(key, start, -1) if ln and str(ln).strip()]
    except Exception as e:
        logger.warning("redis_log_buffer fetch failed: %s", e)
        return []


def push_raw_lines(lines: List[str], key: str, max_lines: int) -> int:
    if not key or not is_configured():
        return 0
    # max_lines <= 0: append only, do not ltrim (no retention cap; rely on memory / external ops)
    cleaned = []
    for ln in lines:
        if not ln:
            continue
        s = str(ln).strip()
        if not s:
            continue
        cleaned.append(s[:65536])
    if not cleaned:
        return 0
    try:
        r = _client()
        r.rpush(key, *cleaned)
        if max_lines > 0:
            r.ltrim(key, -max_lines, -1)
        return len(cleaned)
    except Exception as e:
        logger.warning("redis_log_buffer push failed: %s", e)
        return 0
