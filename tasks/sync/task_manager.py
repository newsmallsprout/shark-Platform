import threading
from typing import Dict, List, Any
import os

from tasks.schemas import SyncTaskRequest
from tasks.models import SyncTask
from tasks.utils import save_task_config, delete_task_config, display_task_metrics
from core.logging import log
from .worker import SyncWorker
from .turbo_runner import TurboPodRunner


def _normal_supervisor_mode() -> bool:
    return (os.environ.get("SHARK_SYNC_NORMAL_MODE") or "inprocess").strip().lower() == "supervisor"


class TaskManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: Dict[str, SyncWorker] = {}
        self._turbo = TurboPodRunner()

    def is_running(self, task_id: str) -> bool:
        with self._lock:
            w = self._tasks.get(task_id)
            if bool(w and getattr(w, "_status", None) == "running"):
                return True
        try:
            t = SyncTask.objects.get(task_id=task_id)
            return t.status == "running"
        except SyncTask.DoesNotExist:
            return False

    def _apply_turbo_fields(self, t: SyncTask, cfg: SyncTaskRequest):
        t.turbo_enabled = bool(getattr(cfg, "turbo_enabled", False))
        t.turbo_no_limit = bool(getattr(cfg, "turbo_no_limit", True))
        t.turbo_pod_namespace = getattr(cfg, "turbo_pod_namespace", None)
        t.turbo_cpu_request = getattr(cfg, "turbo_cpu_request", None)
        t.turbo_mem_request = getattr(cfg, "turbo_mem_request", None)
        t.turbo_cpu_limit = getattr(cfg, "turbo_cpu_limit", None)
        t.turbo_mem_limit = getattr(cfg, "turbo_mem_limit", None)
        t.turbo_shard_count = int(getattr(cfg, "turbo_shard_count", 1) or 1)

    def start(self, cfg: SyncTaskRequest):
        save_task_config(cfg)

        defer_to_supervisor = False
        try:
            t = SyncTask.objects.get(task_id=cfg.task_id)
            self._apply_turbo_fields(t, cfg)
            if t.turbo_enabled:
                pod_names = self._turbo.start_task_pods(t)
                t.status = "running"
                t.turbo_pod_name = ",".join(pod_names)
                t.turbo_phase = "Pending"
                t.save()
                log(cfg.task_id, f"Turbo pods started: {pod_names}")
                return
            t.turbo_pod_name = None
            t.turbo_phase = None
            t.status = "running"
            t.save()
            defer_to_supervisor = _normal_supervisor_mode()
        except SyncTask.DoesNotExist:
            pass

        if defer_to_supervisor:
            log(cfg.task_id, "Normal sync: DB updated; supervisor process runs worker")
            return

        self._start_inprocess_worker(cfg)

    def start_by_id(self, task_id: str):
        try:
            t = SyncTask.objects.get(task_id=task_id)
            cfg = SyncTaskRequest(**t.config)
            self.start(cfg)
        except SyncTask.DoesNotExist:
            raise FileNotFoundError("Task config not found")

    def stop(self, task_id: str):
        stopped_worker = False
        with self._lock:
            w = self._tasks.get(task_id)
            if w is not None:
                w.stop()
                del self._tasks[task_id]
                stopped_worker = True

        try:
            t = SyncTask.objects.get(task_id=task_id)
            if t.turbo_enabled and t.turbo_pod_name:
                self._turbo.stop_task_pod(t)
                t.turbo_pod_name = None
                t.turbo_phase = "Stopped"
            t.status = "stopped"
            t.save()
        except SyncTask.DoesNotExist:
            pass

        if stopped_worker:
            log(task_id, "Task stopped")
        else:
            log(task_id, "Task stopped (turbo pod)")

    def stop_soft(self, task_id: str):
        # Turbo mode has no "soft stop" semantics: fallback to stop.
        self.stop(task_id)
        log(task_id, "Task stopped (soft)")

    def delete(self, task_id: str):
        self.stop(task_id)
        delete_task_config(task_id)
        # delete logs?
        lp = os.path.join("logs", f"{task_id}.log")
        if os.path.exists(lp):
            os.remove(lp)
        log(task_id, "Task deleted")

    def reset(self, task_id: str):
        try:
            t = SyncTask.objects.get(task_id=task_id)
            t.state = {}
            t.save()
        except SyncTask.DoesNotExist:
            pass
        log(task_id, "Task reset (state cleared)")

    def list_tasks(self) -> List[str]:
        # Return all tasks from DB
        return list(SyncTask.objects.values_list('task_id', flat=True))

    def get_all_tasks_status(self) -> List[Dict]:
        res = []
        # Get status from running workers
        with self._lock:
            for tid, w in self._tasks.items():
                res.append(w.get_status())
        
        # Merge with DB tasks that are not running
        running_ids = set(t['task_id'] for t in res)
        db_tasks = SyncTask.objects.all()
        for t in db_tasks:
            if t.task_id not in running_ids:
                turbo = {
                    "enabled": bool(t.turbo_enabled),
                    "pod_name": t.turbo_pod_name or "",
                    "phase": t.turbo_phase or "",
                    "namespace": t.turbo_pod_namespace or "",
                    "shard_count": int(t.turbo_shard_count or 1),
                }
                if t.turbo_enabled and t.turbo_pod_name and t.status == "running":
                    try:
                        turbo["phase"] = self._turbo.get_pod_phase(t) or turbo["phase"]
                    except Exception as e:
                        turbo["phase"] = f"Error: {str(e)[:120]}"
                res.append({
                    "task_id": t.task_id,
                    "status": t.status or "stopped",
                    "metrics": display_task_metrics(
                        t.state, int(t.turbo_shard_count or 1)
                    ),
                    "config": {"mode": "turbo" if t.turbo_enabled else "normal"},
                    "turbo": turbo,
                })
        return res

    def get_task_status(self, task_id: str) -> Dict:
        # Check running tasks first
        with self._lock:
            w = self._tasks.get(task_id)
            if w:
                return w.get_status()
        
        # Check DB
        try:
            t = SyncTask.objects.get(task_id=task_id)
            turbo = {
                "enabled": bool(t.turbo_enabled),
                "pod_name": t.turbo_pod_name or "",
                "phase": t.turbo_phase or "",
                "namespace": t.turbo_pod_namespace or "",
                "shard_count": int(t.turbo_shard_count or 1),
            }
            if t.turbo_enabled and t.turbo_pod_name and t.status == "running":
                try:
                    turbo["phase"] = self._turbo.get_pod_phase(t) or turbo["phase"]
                except Exception as e:
                    turbo["phase"] = f"Error: {str(e)[:120]}"
            return {
                "task_id": t.task_id,
                "status": t.status or "stopped",
                "metrics": display_task_metrics(
                    t.state, int(t.turbo_shard_count or 1)
                ),
                "config": {"mode": "turbo" if t.turbo_enabled else "normal"},
                "turbo": turbo,
            }
        except SyncTask.DoesNotExist:
            return None

    def _start_inprocess_worker(self, cfg: SyncTaskRequest):
        with self._lock:
            if cfg.task_id in self._tasks:
                return
            w = SyncWorker(cfg)
            self._tasks[cfg.task_id] = w
        threading.Thread(target=w.run, daemon=True).start()

    def restore_from_disk(self):
        tasks = SyncTask.objects.filter(status="running")
        for t in tasks:
            try:
                cfg = SyncTaskRequest(**(t.config or {}))
                if t.turbo_enabled:
                    self.start(cfg)
                elif _normal_supervisor_mode():
                    self._start_inprocess_worker(cfg)
                else:
                    self.start(cfg)
            except Exception as e:
                log("startup", f"restore failed {t.task_id}: {e}")

task_manager = TaskManager()
