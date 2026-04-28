"""
Redis list buffer for Nginx access lines shipped from remote hosts (K8s / separate Nginx).

Env:
  TRAFFIC_REDIS_URL — preferred (e.g. redis://redis.traffic.svc:6379/1)
  REDIS_URL — fallback if TRAFFIC_REDIS_URL unset
  TRAFFIC_REDIS_LRANGE_HARD_CAP — 调用方 max_lines<=0（不限制）时，LRANGE 最多取尾部多少行，默认 120000，防整表进内存 OOM；0=不截断（慎用）
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


def _lrange_hard_cap() -> int:
    """
    max_lines<=0 时表示「不限制」；在 K8s 上全量 lrange 极易 OOM。
    TRAFFIC_REDIS_LRANGE_HARD_CAP：最多从尾部取多少行，默认 120000；设为 0 关闭硬顶（慎用）。
    """
    try:
        v = int((os.environ.get("TRAFFIC_REDIS_LRANGE_HARD_CAP") or "120000").strip())
    except ValueError:
        v = 120000
    return max(0, min(v, 2_000_000))


def fetch_tail_lines(key: str, max_lines: int) -> List[str]:
    # max_lines <= 0: 仍受 TRAFFIC_REDIS_LRANGE_HARD_CAP 保护（默认），避免整表进内存
    if not key or not is_configured():
        return []
    try:
        r = _client()
        n = r.llen(key)
        if n <= 0:
            return []
        if max_lines <= 0:
            hard = _lrange_hard_cap()
            if hard > 0 and n > hard:
                logger.warning(
                    "redis LRANGE tail capped: key=%s len=%d hard_cap=%d (set TRAFFIC_REDIS_LRANGE_HARD_CAP)",
                    key,
                    n,
                    hard,
                )
                start = n - hard
            else:
                start = 0
            return [ln for ln in r.lrange(key, start, -1) if ln and str(ln).strip()]
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
