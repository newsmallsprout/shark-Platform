"""Redis-backed binlog event bus: single reader → multi-consumer fan-out.

Reader LPUSH serialized events to a Redis list; consumers BRPOP in a loop.
This eliminates the N × MySQL-binlog-connection problem in Turbo shard mode.

Key format:  shark:sync:q:{task_id}          (Redis list)
             shark:sync:q:{task_id}:pos      (last binlog position, String)
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, Iterator, Optional

import redis as _redis


# ── JSON-friendly event keys (compact 2-char to save Redis memory) ──
_KEY_TYPE = "t"       # w|u|d
_KEY_TABLE = "tb"
_KEY_LOG_FILE = "lf"
_KEY_LOG_POS = "lp"
_KEY_ROWS = "r"
_KEY_VALUES = "v"
_KEY_AFTER = "a"


def _queue_key(task_id: str) -> str:
    return f"shark:sync:q:{task_id}"


def _pos_key(task_id: str) -> str:
    return f"shark:sync:q:{task_id}:pos"


def make_redis_client(redis_url: str) -> _redis.Redis:
    """Create Redis client from URL. Fallback to env if empty."""
    import os
    url = redis_url or os.environ.get("REDIS_URL") or os.environ.get("TRAFFIC_REDIS_URL") or "redis://localhost:6379/0"
    return _redis.from_url(url, decode_responses=False)


def serialize_event(ev_type: str, table: str, log_file: str, log_pos: int,
                    rows: list) -> bytes:
    """Serialize a binlog event to compact JSON bytes for Redis LPUSH."""
    payload = {
        _KEY_TYPE: ev_type,
        _KEY_TABLE: table,
        _KEY_LOG_FILE: log_file,
        _KEY_LOG_POS: log_pos,
        _KEY_ROWS: [],
    }
    for row in rows:
        item = {}
        values = row.get("values")
        after_values = row.get("after_values")
        if values:
            item[_KEY_VALUES] = _sanitize_row(values)
        if after_values:
            item[_KEY_AFTER] = _sanitize_row(after_values)
        if item:
            payload[_KEY_ROWS].append(item)
    return json.dumps(payload, default=str, ensure_ascii=False).encode("utf-8")


def deserialize_event(data: bytes) -> Dict[str, Any]:
    """Deserialize a Redis event back to dict with native row structure."""
    payload = json.loads(data)
    rows = []
    for item in payload.get(_KEY_ROWS, []):
        row = {}
        if _KEY_VALUES in item:
            row["values"] = item[_KEY_VALUES]
        if _KEY_AFTER in item:
            row["after_values"] = item[_KEY_AFTER]
        if row:
            rows.append(row)
    return {
        "type": payload[_KEY_TYPE],
        "table": payload[_KEY_TABLE],
        "log_file": payload[_KEY_LOG_FILE],
        "log_pos": payload[_KEY_LOG_POS],
        "rows": rows,
    }


def publish_event(r: _redis.Redis, task_id: str, ev_type: str, table: str,
                  log_file: str, log_pos: int, rows: list) -> None:
    """LPUSH one event to the task's Redis queue."""
    data = serialize_event(ev_type, table, log_file, log_pos, rows)
    r.lpush(_queue_key(task_id), data)
    # Trim queue to avoid unbounded growth (keep last 100k events)
    r.ltrim(_queue_key(task_id), 0, 99_999)


def save_reader_position(r: _redis.Redis, task_id: str, log_file: str,
                         log_pos: int) -> None:
    """Persist the reader's current binlog position."""
    r.set(_pos_key(task_id), json.dumps({"lf": log_file, "lp": log_pos}))


def load_reader_position(r: _redis.Redis, task_id: str) -> Optional[Dict[str, Any]]:
    """Load the last known reader binlog position."""
    raw = r.get(_pos_key(task_id))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def consume_events(r: _redis.Redis, task_id: str, stop_event,
                   timeout: int = 5) -> Iterator[Dict[str, Any]]:
    """Generator: BRPOP events from Redis queue, yield deserialized dicts.

    Yields one event dict at a time. Blocks up to `timeout` seconds.
    Exits when stop_event is set.
    """
    qk = _queue_key(task_id)
    while not stop_event.is_set():
        result = r.brpop(qk, timeout=timeout)
        if result is None:
            # Timeout — loop back and check stop_event
            continue
        _, data = result
        if data is None:
            continue
        try:
            yield deserialize_event(data)
        except (json.JSONDecodeError, TypeError, KeyError):
            continue


def clear_queue(r: _redis.Redis, task_id: str) -> None:
    """Delete the queue and position keys for a task."""
    r.delete(_queue_key(task_id), _pos_key(task_id))


def queue_length(r: _redis.Redis, task_id: str) -> int:
    """Return the current length of the task's event queue."""
    return r.llen(_queue_key(task_id)) or 0


def _sanitize_row(values: dict) -> dict:
    """Convert row values to JSON-serializable types."""
    out = {}
    for k, v in values.items():
        if isinstance(v, bytes):
            out[k] = v.decode("utf-8", errors="replace")
        elif isinstance(v, (int, float, str, bool, type(None))):
            out[k] = v
        else:
            out[k] = str(v)
    return out
