"""
Ensure sync task restore runs at most once per deployment slice:

- If TRAFFIC_REDIS_URL or REDIS_URL is set: Redis SET NX + TTL (works across pods).
- Else: non-blocking fcntl lock on state/sync_restore.lock (same host, multi-worker).
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import Callable

from core.logging import log


def _redis_url() -> str:
    return (os.environ.get("TRAFFIC_REDIS_URL") or os.environ.get("REDIS_URL") or "").strip()


def _lock_key() -> str:
    return (os.environ.get("SHARK_SYNC_RESTORE_LOCK_KEY") or "shark:sync:restore_lock").strip()


def _lock_ttl_sec() -> int:
    try:
        return max(30, int((os.environ.get("SHARK_SYNC_RESTORE_LOCK_TTL_SEC") or "120").strip()))
    except ValueError:
        return 120


def _try_restore_redis(restore_fn: Callable[[], None]) -> bool:
    url = _redis_url()
    if not url:
        return False
    try:
        import redis  # noqa: WPS433 — optional path
    except Exception:
        return False
    r = redis.from_url(url, decode_responses=True)
    key = _lock_key()
    ttl = _lock_ttl_sec()
    token = f"{os.getpid()}"
    try:
        ok = bool(r.set(key, token, nx=True, ex=ttl))
        if not ok:
            log("startup", "sync restore skipped (redis lock held)")
            return True
        try:
            restore_fn()
        finally:
            try:
                cur = r.get(key)
                if cur == token:
                    r.delete(key)
            except Exception:
                pass
        return True
    except Exception as e:
        log("startup", f"sync restore redis lock failed, fallback file lock: {e}")
        return False


def _state_dir() -> Path:
    return Path(os.environ.get("SHARK_STATE_DIR") or "state")


def _try_restore_fcntl(restore_fn: Callable[[], None]) -> None:
    _state_dir().mkdir(parents=True, exist_ok=True)
    path = _state_dir() / "sync_restore.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("startup", "sync restore skipped (file lock held)")
            return
        restore_fn()
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(fd)


def run_restore_once(restore_fn: Callable[[], None]) -> None:
    if _try_restore_redis(restore_fn):
        return
    _try_restore_fcntl(restore_fn)
