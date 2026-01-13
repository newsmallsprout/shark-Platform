from .models import SyncTask
from .schemas import SyncTaskRequest
from core.logging import log
import json

def load_state(task_id: str):
    try:
        task = SyncTask.objects.get(task_id=task_id)
        return task.state
    except SyncTask.DoesNotExist:
        return {}

def save_state(task_id: str, log_file: str, log_pos: int, metrics: dict):
    try:
        task = SyncTask.objects.get(task_id=task_id)
        state = task.state or {}
        state["log_file"] = log_file
        state["log_pos"] = log_pos
        state["metrics"] = metrics
        task.state = state
        task.save()
    except SyncTask.DoesNotExist:
        pass

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
    # We ignore path and just assume we load from DB in other places, 
    # but the legacy code passed a path.
    # We need to change the caller to pass task_id or handle it.
    # But for compatibility, if we change the caller, we don't need this.
    return {}
