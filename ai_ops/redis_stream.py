"""
Agent 流式事件：与 SSE 服务共用同一 Redis Pub/Sub 频道与 JSON 载荷格式。

- 频道名与 ``brain.event_emitter.AgentEventEmitter.CHANNEL_PREFIX`` 一致：``agent:run:{run_id}``。
- 序号使用 Redis INCR，保证多工具/多节点并发下仍单调递增。
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

import redis

logger = logging.getLogger(__name__)

_POOL: Optional[redis.ConnectionPool] = None


def redis_url() -> str:
    return os.environ.get("AGENT_EVENT_REDIS_URL") or os.environ.get(
        "CELERY_BROKER_URL", "redis://localhost:6379/0"
    )


def get_sync_pool() -> redis.ConnectionPool:
    """进程级连接池，供 Celery Worker / Django 同步路径复用。"""
    global _POOL
    if _POOL is None:
        _POOL = redis.ConnectionPool.from_url(
            redis_url(),
            decode_responses=True,
            max_connections=64,
            socket_connect_timeout=5.0,
            socket_timeout=60.0,
            health_check_interval=30,
        )
    return _POOL


def publish_agent_event(
    run_id: str,
    event_type: str,
    payload: Dict[str, Any],
    *,
    incident_id: Optional[int] = None,
) -> None:
    """发布一条 JSON 事件（UTF-8 字符串）到 ``agent:run:{run_id}``。"""
    channel = f"agent:run:{run_id}"
    r = redis.Redis(connection_pool=get_sync_pool())
    try:
        seq = int(r.incr(f"agent:seq:{run_id}"))
    except redis.RedisError:
        logger.exception("redis INCR failed run_id=%s", run_id)
        seq = int(time.time() * 1000) % 1_000_000_000
    envelope = {
        "run_id": run_id,
        "incident_id": incident_id,
        "seq": seq,
        "ts": time.time(),
        "type": event_type,
        "payload": payload,
    }
    try:
        r.publish(channel, json.dumps(envelope, ensure_ascii=False))
    except redis.RedisError:
        logger.exception("redis PUBLISH failed channel=%s type=%s", channel, event_type)
