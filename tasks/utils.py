from __future__ import annotations

import copy
from typing import Any, Dict, Optional

from django.db import transaction

from .models import SyncTask
from .schemas import SyncTaskRequest
from core.logging import log

_METRIC_SUM_KEYS = (
    "processed_count",
    "full_insert_count",
    "inc_insert_count",
    "update_count",
    "delete_count",
)


def _aggregate_shards_to_metrics(state: Dict[str, Any], shard_total: int) -> Dict[str, Any]:
    """Merge per-shard blocks into one metrics dict for API / legacy readers."""
    shards: Dict[str, Any] = dict(state.get("shards") or {})
    if not shards:
        return dict(state.get("metrics") or {})

    out: Dict[str, Any] = {k: 0 for k in _METRIC_SUM_KEYS}
    phases: list = []
    binlog_parts: list = []
    last_update = 0.0
    current_table = ""
    err_parts: list = []

    for i in range(max(1, int(shard_total or 1))):
        block = shards.get(str(i)) or {}
        m = block.get("metrics") or {}
        for k in _METRIC_SUM_KEYS:
            try:
                out[k] += int(m.get(k) or 0)
            except (TypeError, ValueError):
                pass
        phases.append(str(m.get("phase") or ""))
        lf, lp = block.get("log_file"), block.get("log_pos")
        if lf is not None and str(lf).strip():
            binlog_parts.append(f"S{i}:{lf}:{lp}")
        try:
            last_update = max(last_update, float(m.get("last_update") or 0))
        except (TypeError, ValueError):
            pass
        if m.get("current_table"):
            current_table = str(m["current_table"])
        e = m.get("error")
        if e:
            err_parts.append(f"S{i}:{e}")

    if any("error" in p for p in phases):
        out["phase"] = "error"
    elif any("inc" in p for p in phases):
        out["phase"] = "inc_sync"
    elif phases:
        out["phase"] = phases[0] or "inc_sync"
    else:
        out["phase"] = "inc_sync"

    out["binlog_file"] = "; ".join(binlog_parts) if binlog_parts else ""
    out["binlog_pos"] = 0
    out["last_update"] = last_update
    out["current_table"] = current_table
    if err_parts:
        out["error"] = " | ".join(err_parts)[:2000]
    else:
        out.pop("error", None)

    try:
        out["processed_count"] = (
            int(out.get("full_insert_count") or 0)
            + int(out.get("inc_insert_count") or 0)
            + int(out.get("update_count") or 0)
            + int(out.get("delete_count") or 0)
        )
    except (TypeError, ValueError):
        pass
    return out


def display_task_metrics(state: Optional[dict], turbo_shard_count: int = 1) -> Dict[str, Any]:
    """Metrics for UI: aggregated when turbo uses multiple shards."""
    state = state or {}
    n = max(1, int(turbo_shard_count or 1))
    if n > 1 and isinstance(state.get("shards"), dict) and state["shards"]:
        return _aggregate_shards_to_metrics(state, n)
    return dict(state.get("metrics") or {})


def load_state(task_id: str, shard_total: int = 1, shard_index: int = 0) -> Dict[str, Any]:
    try:
        task = SyncTask.objects.get(task_id=task_id)
        state = task.state or {}
        st = max(1, int(shard_total or 1))
        si = int(shard_index or 0)

        if st <= 1:
            return {
                "log_file": state.get("log_file"),
                "log_pos": state.get("log_pos"),
                "metrics": dict(state.get("metrics") or {}),
            }

        shards = state.get("shards") or {}
        sk = str(si)
        if sk in shards and isinstance(shards[sk], dict):
            block = shards[sk]
            return {
                "log_file": block.get("log_file"),
                "log_pos": block.get("log_pos"),
                "metrics": dict(block.get("metrics") or {}),
            }

        z = shards.get("0") if isinstance(shards.get("0"), dict) else {}
        if z.get("log_file"):
            return {
                "log_file": z.get("log_file"),
                "log_pos": z.get("log_pos"),
                "metrics": {} if si != 0 else dict(z.get("metrics") or {}),
            }

        # First run after enabling turbo: reuse legacy flat checkpoint (all shards share start)
        if state.get("log_file"):
            return {
                "log_file": state.get("log_file"),
                "log_pos": state.get("log_pos"),
                "metrics": dict(state.get("metrics") or {}) if si == 0 else {},
            }
        return {"log_file": None, "log_pos": None, "metrics": {}}
    except SyncTask.DoesNotExist:
        return {}


def save_state(
    task_id: str,
    log_file: Optional[str],
    log_pos: Optional[int],
    metrics: dict,
    shard_total: int = 1,
    shard_index: int = 0,
):
    max_retries = 3
    import time as _time
    for attempt in range(max_retries):
        try:
            with transaction.atomic():
                task = SyncTask.objects.select_for_update().get(task_id=task_id)
                state = copy.deepcopy(task.state or {})
                st = max(1, int(shard_total or 1))
                si = int(shard_index or 0)
                metrics = copy.deepcopy(metrics or {})

                if st <= 1:
                    if log_file:
                        state["log_file"] = log_file
                    if log_pos is not None:
                        state["log_pos"] = log_pos
                    state["metrics"] = metrics
                else:
                    shards: Dict[str, Any] = dict(state.get("shards") or {})
                    sk = str(si)
                    prev = dict(shards.get(sk) or {})
                    block: Dict[str, Any] = {
                        "metrics": metrics,
                    }
                    if log_file:
                        block["log_file"] = log_file
                    elif prev.get("log_file"):
                        block["log_file"] = prev.get("log_file")
                    if log_pos is not None:
                        block["log_pos"] = log_pos
                    elif prev.get("log_pos") is not None:
                        block["log_pos"] = prev.get("log_pos")
                    shards[sk] = block
                    state["shards"] = shards
                    state["metrics"] = _aggregate_shards_to_metrics(state, st)

                task.state = state
                task.save(update_fields=["state"])
            break  # success — exit retry loop
        except SyncTask.DoesNotExist:
            return
        except Exception as e:
            s = str(e).lower()
            if ("database is locked" in s or "locked" in s) and attempt < max_retries - 1:
                _time.sleep(0.2 * (attempt + 1))
                continue
            # Non-retriable or exhausted retries — silently skip this save


def save_task_config(cfg: SyncTaskRequest):
    try:
        task, created = SyncTask.objects.get_or_create(task_id=cfg.task_id)
        task.config = cfg.dict()
        task.save()
    except Exception as e:
        log("system", f"Failed to save task config: {e}")


def delete_task_config(task_id: str):
    try:
        SyncTask.objects.filter(task_id=task_id).delete()
    except Exception:
        pass


def load_task_config_file(path_ignored: str) -> dict:
    return {}
